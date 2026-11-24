"""
Шлюз работы со снимками спецификаций заказа (OrderSpecificationSnapshot).

Назначение модуля:
    Единственная точка чтения, кэширования и перестроения спецификаций заказа.
    Вынесена в отдельный модуль внутри engine/, чтобы разорвать циклические импорты
    между services.py, tracking_services.py и views.py.

Правила хранения:
    - Все снимки хранятся исключительно в таблице OrderSpecificationSnapshot
      (поля phase1_spec_cache / phase2_spec_cache на Order удалены на Этапе 3Б).
    - Новые расчёты добавляют новую запись снимка (история версий сохраняется),
      мержа пересчитанный батч поверх предыдущих батчей того же этапа.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from django.db import transaction

from apps.orders.models import Order, OrderItem, OrderItemsGroup
from apps.production.models import OrderSpecificationSnapshot
from .runner import OrderSpecEngine
from .schemas import OrderSpec


class OrderValidationError(Exception):
    """Исключение с накопленным списком ошибок расчёта/валидации заказа."""

    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.errors: List[str] = errors if errors is not None else [message]


class TechnicalSpecService:
    """
    Высокоуровневый фасад над OrderSpecificationSnapshot и OrderSpecEngine.
    Отвечает за:
        - выборку актуального снимка (phase1 / phase2);
        - инкрементальное достроение и перестроение батчей заказа;
        - загрузку оптимизированного QuerySet позиций (get_rich_order_items).
    """

    @staticmethod
    def _snapshot_type(phase: str) -> str:
        """Преобразует строковый код этапа ('phase1'/'phase2') в enum SnapshotType."""
        return (
            OrderSpecificationSnapshot.SnapshotType.PHASE1
            if phase == 'phase1'
            else OrderSpecificationSnapshot.SnapshotType.PHASE2
        )

    @classmethod
    def get_latest_snapshot(
            cls,
            order: Order,
            phase: str = 'phase2',
    ) -> Optional[OrderSpecificationSnapshot]:
        """Возвращает самую свежую ORM-запись OrderSpecificationSnapshot для указанного этапа."""
        return (
            OrderSpecificationSnapshot.objects.filter(
                order=order,
                snapshot_type=cls._snapshot_type(phase),
            )
            .order_by('-created_at', '-id')
            .first()
        )

    @classmethod
    def get_latest_spec_data(cls, order: Order, phase: str = 'phase2') -> Optional[dict]:
        """Возвращает сырой JSON-словарь последнего снимка заказа (или None, если снимков нет)."""
        snap = cls.get_latest_snapshot(order, phase=phase)
        if snap and isinstance(snap.spec_data, dict):
            return snap.spec_data
        return None

    @classmethod
    def has_snapshot(cls, order: Order, phase: str = 'phase2') -> bool:
        """Проверяет наличие хотя бы одного сохранённого снимка для заказа и этапа."""
        return OrderSpecificationSnapshot.objects.filter(
            order=order,
            snapshot_type=cls._snapshot_type(phase),
        ).exists()

    @staticmethod
    def get_rich_order_items(
            order_id: int,
            batch_number: Optional[int] = None,
    ) -> List[OrderItem]:
        """
        Возвращает активные позиции заказа с предзагруженными связями (select_related).
        Исключает отложенные (WAITING) и отменённые (CANCELED) группы, а также отменённые позиции.
        """
        qs = (
            OrderItem.objects.filter(group__order_id=order_id)
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

        if batch_number is not None:
            qs = qs.filter(group__batch_number=batch_number)

        return list(qs)

    @classmethod
    def get_or_build_spec(
            cls,
            order: Order,
            phase: str = 'phase2',
            batch_number: Optional[int] = None,
            force_rebuild: bool = False,
            user=None,
    ) -> Tuple[OrderSpec, dict]:
        """
        Возвращает (OrderSpec, raw_dict) из последнего снимка либо пересчитывает заказ
        через OrderSpecEngine и сохраняет новый снимок в БД.

        Args:
            order: Заказ.
            phase: 'phase1' или 'phase2'.
            batch_number: Если указан — пересчитывается и дописывается только этот батч.
            force_rebuild: Принудительный пересчёт даже при наличии снимка.
            user: Пользователь, инициировавший построение снимка (пишется в created_by).

        Raises:
            OrderValidationError: Если в заказе нет активных позиций или калькуляторы
                                  вернули блокирующие ошибки.
        """
        latest_data = cls.get_latest_spec_data(order, phase=phase)
        existing_cache = (
            {
                'order': dict(latest_data.get('order', {})),
                'batches': dict(latest_data.get('batches', {})),
            }
            if isinstance(latest_data, dict) and 'batches' in latest_data
            else {'order': {}, 'batches': {}}
        )

        batch_str = str(batch_number) if batch_number is not None else None

        # Быстрый возврат из последнего снимка, если пересчёт не требуется
        if not force_rebuild:
            if batch_str and batch_str in existing_cache['batches']:
                return OrderSpec.model_validate(existing_cache), existing_cache
            if batch_str is None and existing_cache['batches']:
                return OrderSpec.model_validate(existing_cache), existing_cache

        items = cls.get_rich_order_items(order_id=order.id, batch_number=batch_number)
        if not items:
            raise OrderValidationError(
                f"Нет активных позиций для формирования спецификации (batch={batch_number})."
            )

        with transaction.atomic():
            engine = OrderSpecEngine()
            spec_obj = engine.execute(
                order=order,
                items=items,
                phase=phase,
                save_labels=(phase == 'phase2'),
            )

            # Собираем ошибки по всем позициям до записи снимка
            errors: List[str] = []
            for b_items in spec_obj.batches.values():
                for it in b_items:
                    if it.errors:
                        mark_label = f"Item {it.mark}" if it.mark else f"Item #{it.item_id}"
                        errors.extend(f"{mark_label}: {err}" for err in it.errors)

            if errors:
                raise OrderValidationError(
                    f"Ошибки при расчете спецификации: {'; '.join(errors)}",
                    errors=errors,
                )

            spec_dict = spec_obj.model_dump()
            existing_cache['order'] = spec_dict.get('order', {})
            for b_key, b_items in spec_dict.get('batches', {}).items():
                existing_cache['batches'][b_key] = b_items

            OrderSpecificationSnapshot.objects.create(
                order=order,
                snapshot_type=cls._snapshot_type(phase),
                spec_data=existing_cache,
                created_by=user if (user and getattr(user, 'is_authenticated', False)) else None,
            )

        return OrderSpec.model_validate(existing_cache), existing_cache

    @classmethod
    def get_batch_items(
            cls,
            order: Order,
            phase: str = 'phase1',
            batch_number: int = 1,
    ) -> List[dict]:
        """Возвращает список словарей позиций конкретного батча из последнего снимка."""
        cache = cls.get_latest_spec_data(order, phase=phase)
        if not isinstance(cache, dict):
            return []
        batches = cache.get('batches', {})
        return batches.get(str(batch_number), []) if isinstance(batches, dict) else []
