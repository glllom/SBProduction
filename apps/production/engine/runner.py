"""
Линейный оркестратор расчёта технической спецификации заказа (OrderSpecEngine).

Назначение модуля:
    Заменяет старый 27-шаговый пайплайн на приоритетах (pipeline.py) простым,
    детерминированным и линейным потоком расчёта без N+1 запросов к БД.

Порядок выполнения для каждой позиции заказа:
    1. init_item_state     — валидация проёма/направления, DoubleDoor, WoodEdge (см),
                             внешний вид (цвета/חזית) и форматирование кастомизаторов.
    2. calculate_geometry  — внутренний проём коробки, чистовые полотна (вкл. трапецию),
                             заготовки на пресс (шаг 0.5 см) и раскрой листов.
    3. calculate_bom       — подбор материала коробки, патчи bom_overrides / CASING,
                             подбор форматов листов и сборка SpecBOMItem (с SKU).
    4. calculate_hardware  — замок, режим (WC/CYLINDER/KEY), цилиндр, ручка, петли,
                             высоты на полотне и на коробке.
    5. calculate_routing   — флаг edge_shape, станции маршрута, лимиты Essepigi/Accord,
                             принудительный ACCORD_CUSTOM для наклейки 2 при is_special_detail.
    6. calculate_visuals   — SVG-пазл (face + sandwich) и applied_presets для отчёта пресса.

После прохода по позициям каждой партии (batch):
    7. align_batch_lock_heights — выравнивание высот замков между соседними дверями батча.
    8. DoorLabelGenerator       — однопроходная генерация и пакетная запись DoorLabel
                                  (только в Фазе 2, при save_labels=True и отсутствии ошибок).
"""

from __future__ import annotations

import collections
from typing import Dict, List, Optional

from apps.orders.models import Order, OrderItem, OrderItemsGroup
from .cache import OrderReferenceCache
from .calculators.base import ItemRuntimeState, init_item_state
from .calculators.bom import calculate_bom
from .calculators.geometry import calculate_geometry
from .calculators.hardware import align_batch_lock_heights, calculate_hardware
from .calculators.routing import calculate_routing
from .calculators.visuals import calculate_visuals
from .schemas import OrderHeaderSpec, OrderSpec


def format_spec_date(value) -> str:
    """Форматирует дату заказа в компактный вид dd/mm/yy для шапки спецификации."""
    return value.strftime("%d/%m/%y") if value else ""


class OrderSpecEngine:
    """
    Центральный движок расчёта технической спецификации заказа.

    Работает поверх OrderReferenceCache: все справочники (правила, BOM, материалы,
    фурнитура, стандарты высот, маршруты, ЧПУ-макросы и SVG-прототипы) загружаются
    в память один раз на вызов execute().
    """

    def execute(
            self,
            order: Order,
            items: Optional[List[OrderItem]] = None,
            phase: str = 'phase2',
            save_labels: bool = False,
    ) -> OrderSpec:
        """
        Выполняет полный расчёт спецификации заказа.

        Args:
            order: Объект заказа (apps.orders.models.Order).
            items: Предзагруженный список OrderItem. Если не передан — загружается
                   автоматически с исключением групп WAITING/CANCELED и отменённых позиций.
            phase: Этап расчёта ('phase1' — только коробки/проёмы, 'phase2' — полный комплект).
            save_labels: Если True (и phase != 'phase1', и нет ошибок расчёта),
                         синхронизирует таблицу DoorLabel через DoorLabelGenerator.

        Returns:
            Готовый типизированный Pydantic-объект OrderSpec (все размеры в см).
        """
        # 1. Загружаем позиции заказа, если вызывающий код не передал их заранее
        resolved_items = items if items is not None else self._load_default_items(order)

        # 2. Предзагружаем все справочники в память (устраняем N+1 запросы в циклах)
        cache = OrderReferenceCache.load_for_order(order, resolved_items, phase=phase)

        # 3. Формируем шапку заказа
        header = OrderHeaderSpec(
            number=str(order.order_number or ""),
            customer=order.customer or "",
            status=order.status,
            production_start_date=format_spec_date(getattr(order, 'production_start_date', None)),
            painting_completion_date=format_spec_date(getattr(order, 'painting_completion_date', None)),
            completion_date=format_spec_date(getattr(order, 'completion_date', None)),
        )

        # 4. Линейный расчёт каждой позиции с группировкой по номеру партии (batch)
        states_by_batch: Dict[str, List[ItemRuntimeState]] = collections.defaultdict(list)
        for item in resolved_items:
            raw_batch = item.group.batch_number if item.group else None
            batch_key = str(raw_batch) if raw_batch else 'NEW'

            state = self._calculate_single_item(item=item, cache=cache, phase=phase)
            states_by_batch[batch_key].append(state)

        # 5. Выравнивание высот замков внутри каждой партии (проверка конфликтов tolerance)
        for batch_states in states_by_batch.values():
            align_batch_lock_heights(batch_states)

        # 6. В Фазе 2 строим черновики наклеек в памяти (проверяем ЧПУ-макросы даже при dry-run)
        label_drafts = []
        if phase != 'phase1':
            from apps.production.labels.generator import DoorLabelGenerator
            label_drafts = DoorLabelGenerator.build_drafts_for_order(
                order=order,
                states_by_batch=states_by_batch,
                cache=cache,
            )

        # 7. Собираем итоговый OrderSpec (чистые ProductionSpec без транзиентного состояния)
        batches_payload = {
            batch_key: [st.spec for st in batch_states]
            for batch_key, batch_states in states_by_batch.items()
        }
        order_spec = OrderSpec(order=header, batches=batches_payload)

        # 8. Пакетная запись наклеек в DoorLabel — только при save_labels=True и 0 ошибках
        if save_labels and label_drafts:
            has_errors = any(
                st.spec.errors
                for batch_states in states_by_batch.values()
                for st in batch_states
            )
            if not has_errors:
                from apps.production.labels.generator import DoorLabelGenerator
                DoorLabelGenerator.persist_drafts(order=order, all_drafts=label_drafts)

        return order_spec

    @staticmethod
    def _run_plugin_hook(
            hook_name: str,
            active_plugins: list,
            state: ItemRuntimeState,
            cache: OrderReferenceCache,
    ) -> None:
        """Выполняет указанный хук (on_init, on_geometry, ...) у всех активных плагинов двери."""
        for plugin, gc in active_plugins:
            try:
                getattr(plugin, hook_name)(state, gc, cache)
            except Exception as exc:
                state.add_error(f"Unexpected error in plugin '{plugin.code}' ({hook_name}): {exc}")

    @classmethod
    def _calculate_single_item(
            cls,
            item: OrderItem,
            cache: OrderReferenceCache,
            phase: str,
    ) -> ItemRuntimeState:
        """
        Прогоняет одну позицию через 6 базовых калькуляторов и подключённые плагины
        кастомизаторов в строгом порядке зависимостей.
        """
        from production.engine.plugins import CustomizerPluginRegistry

        state = init_item_state(item=item, cache=cache, phase=phase)
        active_plugins = CustomizerPluginRegistry.resolve_for_item(state.customizers)

        # Хук 1: инициализация плагинов (DOUBLE_DOOR, WOOD_EDGE и др.)
        cls._run_plugin_hook('on_init', active_plugins, state, cache)

        # Строгий порядок этапов ядра и соответствующих хуков плагинов
        stages = (
            ("geometry", lambda: calculate_geometry(state), None, 'on_geometry'),
            ("bom", lambda: calculate_bom(state, cache), 'on_before_bom', 'on_bom'),
            ("hardware", lambda: calculate_hardware(state, cache), None, 'on_hardware'),
            ("routing", lambda: calculate_routing(state, cache), None, 'on_routing'),
            ("visuals", lambda: calculate_visuals(state, cache), None, 'on_visuals'),
        )

        for stage_name, stage_fn, pre_hook, post_hook in stages:
            if pre_hook:
                cls._run_plugin_hook(pre_hook, active_plugins, state, cache)
            try:
                stage_fn()
            except Exception as exc:
                state.add_error(f"Unexpected error in {stage_name}: {exc}")
            if post_hook:
                cls._run_plugin_hook(post_hook, active_plugins, state, cache)

        return state

    @staticmethod
    def _load_default_items(order: Order) -> List[OrderItem]:
        """Загружает активные позиции заказа с нужными связями для расчёта."""
        return list(
            OrderItem.objects.filter(group__order=order)
            .exclude(
                group__production_state__in=[
                    OrderItemsGroup.ProductionState.WAITING,
                    OrderItemsGroup.ProductionState.CANCELED,
                ]
            )
            .exclude(state=OrderItem.ItemState.CANCELED)
            .select_related(
                'group',
                'group__order',
                'group__order__series',
                'group__order__front',
                'group__order__handle',
                'group__product',
                'group__product__product_family',
                'group__product__product_family__product_type',
                'group__product__series',
                'group__front',
                'group__series',
                'group__basic_color_frames',
            )
            .order_by('group__id', 'id')
        )
