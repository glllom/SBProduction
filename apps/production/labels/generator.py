"""
Однопроходный генератор производственных наклеек BarTender / CNC (DoorLabelGenerator).

Назначение модуля:
    Заменяет старый многоэтапный DoorLabelService (label_services.py), который 4 раза
    мутировал черновики наклеек в разных точках пайплайна и плодил N+1 запросы к БД.

Принципы работы:
    1. Запускается ОДИН раз в конце OrderSpecEngine.execute() — уже ПОСЛЕ того как
       рассчитаны геометрия, BOM, фурнитура, маршрутизация и выполнено выравнивание
       высот замков внутри батча (align_batch_lock_heights).
    2. Использует исключительно предзагруженный OrderReferenceCache (0 запросов к БД
       при построении черновиков; запись в БД — 1 транзакция bulk_update / bulk_create).
    3. Единственное место в проекте, где сантиметры переводятся в миллиметры (см * 10 -> мм)
       для QR-кодов Essepigi / Accord.
    4. Правило פרט מיוחד (is_special_detail): целевая машина ACCORD_CUSTOM выставляется
       в calculators/routing.py ТОЛЬКО для наклейки 2 (FINISHING), а генератор формирует
       для неё путь проекта C:\\Ww8\\PROJECTS\\{order_num}\\d{mark}.pgmx.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction

from apps.catalog.models import Hardware, MachiningFeature
from apps.engineering.models import HardwareMacroFile, PerimeterRoutingFile
from apps.orders.models import Order, OrderItemsGroup
from apps.production.cnc import MachineContext, MachineRegistry
from apps.production.engine.cache import OrderReferenceCache
from apps.production.engine.calculators.base import ItemRuntimeState
from apps.production.models import DoorLabel

# Теги материалов в SpecBOMItem, которые нужно игнорировать при сборе MachiningFeature фурнитуры
_MATERIAL_BOM_TAGS = frozenset({
    'frame', 'covering', 'base', 'filling', 'panel_frame',
    'casing', 'door_casing', 'profile1', 'profile2', 'profile3',
    'other1', 'other2', 'other3', 'other4', 'other5', 'wood_edge',
})

# Список полей DoorLabel, обновляемых при пересчёте (счётчики print_count и last_printed_at сохраняются!)
_LABEL_UPDATE_FIELDS = [
    'order_number', 'client_name', 'completion_date',
    'item_mark', 'total_items',
    'product_family_name', 'product_family_code',
    'width', 'width_bottom', 'height', 'direction', 'edge_type', 'is_paint',
    'lock_name', 'lock_height',
    'hinge_name', 'hinge_1', 'hinge_2', 'hinge_3', 'hinge_4', 'hinge_5',
    'addons_summary', 'comment',
    'target_machine', 'qr_payload', 'front_program_code',
]


class DoorLabelGenerator:
    """
    Генератор и синхронизатор таблицы DoorLabel для заказа.

    Жизненный цикл:
        1. build_drafts_for_order(...) — чистый расчёт в памяти (0 SQL-запросов).
           Попутно проверяет конфликты и отсутствие HardwareMacroFile по MachiningFeature
           и добавляет ошибки в state.spec.errors (чтобы их ловил и dry-run валидатор).
        2. persist_drafts(...) — пакетно обновляет/создаёт записи в DoorLabel
           с сохранением истории печати (print_count / last_printed_at) и удалением
           устаревших наклеек только для пересчитанных позиций.
    """

    @classmethod
    def build_drafts_for_order(
            cls,
            order: Order,
            states_by_batch: Dict[str, List[ItemRuntimeState]],
            cache: OrderReferenceCache,
    ) -> List[Dict[str, Any]]:
        """
        Формирует плоский список словарей-черновиков DoorLabel для всех дверных позиций заказа.
        Выполняется без обращений к БД (только по OrderReferenceCache).
        """
        all_drafts: List[Dict[str, Any]] = []
        for batch_states in states_by_batch.values():
            for state in batch_states:
                if not state.spec.has_door:
                    continue
                all_drafts.extend(cls._build_drafts_for_state(order, state, cache))

        total_doors = len({d['order_item_id'] for d in all_drafts})
        for draft in all_drafts:
            draft['total_items'] = total_doors

        return all_drafts

    @classmethod
    @transaction.atomic
    def persist_drafts(cls, order: Order, all_drafts: List[Dict[str, Any]]) -> None:
        """
        Синхронизирует таблицу DoorLabel для пересчитанных позиций заказа:
            - совпадающие (order_item_id, leaf_role, label_type) обновляются с сохранением print_count;
            - новые создаются через bulk_create;
            - устаревшие наклейки для ТЕХ ЖЕ order_item_id (например, дверь стала одинарной
              или убрали скрытый кант) удаляются; наклейки других батчей не затрагиваются.
        """
        if not all_drafts:
            return

        processed_item_ids = {d['order_item_id'] for d in all_drafts}
        existing_map = {
            (lbl.order_item_id, lbl.leaf_role, lbl.label_type): lbl
            for lbl in DoorLabel.objects.filter(
                order_id=order.id,
                order_item_id__in=processed_item_ids,
            )
        }

        active_keys = set()
        to_create: List[DoorLabel] = []
        to_update: List[DoorLabel] = []

        for draft in all_drafts:
            key = (draft['order_item_id'], draft['leaf_role'], draft['label_type'])
            active_keys.add(key)

            if key in existing_map:
                lbl = existing_map[key]
                for field_name in _LABEL_UPDATE_FIELDS:
                    if field_name in draft:
                        setattr(lbl, field_name, draft[field_name])
                to_update.append(lbl)
            else:
                to_create.append(DoorLabel(**draft))

        # Удаляем осиротевшие наклейки для пересчитанных дверей (например, сменилась роль створки)
        obsolete_ids = [
            lbl.id for key, lbl in existing_map.items()
            if key not in active_keys
        ]
        if obsolete_ids:
            DoorLabel.objects.filter(id__in=obsolete_ids).delete()

        if to_update:
            DoorLabel.objects.bulk_update(to_update, _LABEL_UPDATE_FIELDS)
        if to_create:
            DoorLabel.objects.bulk_create(to_create)

    @classmethod
    def _build_drafts_for_state(
            cls,
            order: Order,
            state: ItemRuntimeState,
            cache: OrderReferenceCache,
    ) -> List[Dict[str, Any]]:
        """Строит комплект наклеек (1-2 створки × 2-3 типа) для одной двери."""
        spec = state.spec
        item = state.item
        group = state.group
        product = state.product
        door_family = getattr(product, 'product_family', None) if product else None
        family_id = getattr(product, 'product_family_id', None) if product else None
        front = (getattr(group, 'front', None) or getattr(order, 'front', None)) if group else None

        # 1. Определяем роли створок и набор типов наклеек
        roles = (
            [DoorLabel.LeafRole.ACTIVE, DoorLabel.LeafRole.PASSIVE]
            if spec.is_double_door
            else [DoorLabel.LeafRole.SINGLE]
        )
        label_types = [
            DoorLabel.LabelType.ROUGHING,
            DoorLabel.LabelType.FINISHING,
        ]
        if spec.is_hidden_wood_edge:
            label_types.insert(0, DoorLabel.LabelType.PRE_ROUGHING)

        # 2. Геометрия полотен (напрямую из spec, без вычислений)
        panels = spec.panel_dimensions or []
        is_paint = bool(
            group and group.panel_paint_option != OrderItemsGroup.PaintOption.NO_PAINT
        )

        # 3. Валидация макросов и подписи замка/петель с учётом MachiningFeature
        hinge_id = state.hinge_hardware_id
        if not hinge_id:
            hinge_bi = next((bi for bi in spec.bom_items if str(bi.tag or '').lower() == 'hinge'), None)
            hinge_id = hinge_bi.item_id if hinge_bi else None

        features_by_role = cls._collect_active_machining_features(state, cache, hinge_id=hinge_id)

        lock_macro, lock_err = cls._resolve_hardware_macro(
            hardware_id=spec.lock_id,
            door_family=door_family,
            target_role=Hardware.HardwareRole.LOCK,
            features_by_role=features_by_role,
            cache=cache,
        )
        hinge_macro, hinge_err = cls._resolve_hardware_macro(
            hardware_id=hinge_id,
            door_family=door_family,
            target_role=Hardware.HardwareRole.HINGE,
            features_by_role=features_by_role,
            cache=cache,
        )
        for err_msg in (lock_err, hinge_err):
            if err_msg:
                state.add_error(err_msg)

        lock_label = cls._format_hardware_label(spec.lock_name, lock_macro)
        hinge_label = cls._format_hardware_label(spec.hinge_name, hinge_macro)

        # 4. Макрос фасада, текстовая сводка кастомизаторов и высоты петель
        front_program_code = cache.front_engravings.get(front.id, "") if front else ""
        addons_summary = cls._build_addons_summary(spec)
        padded_hinges = (list(spec.hinge_heights or []) + [None] * 5)[:5]
        engraving_data = spec.engraving_data or {}
        cnc_targets = spec.cnc_targets or {}

        mark_str = str(item.mark or item.id)
        client_name = order.customer or ''
        comment = spec.comment or item.comment or ''
        direction = spec.direction or (item.get_direction_display() if item.direction else '') or ''
        family_name = (getattr(door_family, 'name', '') or '')[:128]
        family_code = (getattr(door_family, 'code', '') or '')[:128]

        drafts: List[Dict[str, Any]] = []
        for role in roles:
            panel = (
                panels[1]
                if (role == DoorLabel.LeafRole.PASSIVE and len(panels) > 1)
                else (panels[0] if panels else {})
            )
            leaf_w = panel.get('width', spec.width)
            leaf_w_bottom = panel.get('width_bottom')
            leaf_h = panel.get('height', spec.height)

            for l_type in label_types:
                cnc_program, edge_shape = cls._resolve_perimeter_routing(
                    label_type=l_type,
                    family_id=family_id,
                    leaf_role=role,
                    cache=cache,
                )
                target_machine = (
                        cnc_targets.get(int(l_type))
                        or cnc_targets.get(str(int(l_type)))
                        or DoorLabel.TargetMachine.ACCORD_STD
                )

                draft: Dict[str, Any] = {
                    'order_id': order.id,
                    'order_item_id': item.id,
                    'order_number': order.order_number,
                    'client_name': client_name,
                    'completion_date': order.completion_date,
                    'item_mark': mark_str,
                    'leaf_role': role,
                    'label_type': l_type,
                    'product_family_name': family_name,
                    'product_family_code': family_code,
                    'width': leaf_w,
                    'width_bottom': leaf_w_bottom,
                    'height': leaf_h,
                    'direction': direction,
                    'edge_type': spec.wood_edge_type or '',
                    'is_paint': is_paint,
                    'lock_name': lock_label,
                    'lock_height': spec.lock_height,
                    'hinge_name': hinge_label,
                    'hinge_1': padded_hinges[0],
                    'hinge_2': padded_hinges[1],
                    'hinge_3': padded_hinges[2],
                    'hinge_4': padded_hinges[3],
                    'hinge_5': padded_hinges[4],
                    'addons_summary': addons_summary,
                    'comment': comment,
                    'target_machine': target_machine,
                    'front_program_code': front_program_code,
                }
                draft['qr_payload'] = cls._build_qr_payload(
                    machine=target_machine,
                    label_type=l_type,
                    draft=draft,
                    spec=spec,
                    engraving_data=engraving_data,
                    cnc_program=cnc_program,
                    edge_shape=edge_shape,
                )
                drafts.append(draft)

        return drafts

    @staticmethod
    def _cm_to_mm(val: float) -> float:
        """Единственная точка перевода линейных габаритов полотна из см в мм для ЧПУ."""
        if val <= 0:
            return 0.0
        return round(val * 10.0, 2)

    @classmethod
    def _resolve_perimeter_routing(
            cls,
            label_type: int,
            family_id: Optional[int],
            leaf_role: int,
            cache: OrderReferenceCache,
    ) -> Tuple[str, bool]:
        """Подбирает имя файла периметральной обработки и флаг edge_shape для наклеек 0 и 1."""
        routing_obj: Optional[PerimeterRoutingFile] = None

        if label_type == DoorLabel.LabelType.PRE_ROUGHING:
            routing_obj = cache.perimeter_pre_roughing
        elif label_type == DoorLabel.LabelType.ROUGHING and family_id:
            routing_obj = cache.perimeter_by_family.get(family_id)

        if not routing_obj or not routing_obj.file_name:
            return '', False

        raw_filename = routing_obj.file_name.strip()
        edge_shape = bool(routing_obj.edge_shape)

        # Для двустворчатых дверей добавляем суффикс _dbl1 / _dbl2 к имени программы
        if leaf_role == DoorLabel.LeafRole.ACTIVE:
            suffix = '_dbl1'
        elif leaf_role == DoorLabel.LeafRole.PASSIVE:
            suffix = '_dbl2'
        else:
            suffix = ''

        if suffix:
            name, ext = os.path.splitext(raw_filename)
            return (f"{name}{suffix}{ext}" if ext else f"{name}{suffix}"), edge_shape

        return raw_filename, edge_shape

    @classmethod
    def _build_qr_payload(
            cls,
            machine: str,
            label_type: int,
            draft: Dict[str, Any],
            spec,
            engraving_data: Dict[str, Any],
            cnc_program: str = '',
            edge_shape: bool = False,
    ) -> str:
        """Делегирует сборку QR-строки зарегистрированному драйверу станка ЧПУ."""
        driver = MachineRegistry.get(machine)
        raw_thickness = float(spec.leaf_thickness or 0)
        thickness_mm = (
            cls._cm_to_mm(raw_thickness)
            if 0 < raw_thickness < 15
            else (raw_thickness or 40.0)
        )
        ctx = MachineContext(
            order_number=str(draft.get('order_number') or ''),
            item_mark=str(draft.get('item_mark') or '1'),
            label_type=int(label_type),
            leaf_role=int(draft.get('leaf_role', DoorLabel.LeafRole.SINGLE)),
            width_mm=cls._cm_to_mm(float(draft.get('width') or spec.width or 0)),
            height_mm=cls._cm_to_mm(float(draft.get('height') or spec.height or 0)),
            thickness_mm=thickness_mm,
            edge_type=str(draft.get('edge_type') or spec.wood_edge_type or 'STANDARD'),
            edge_shape=edge_shape,
            cnc_program=cnc_program,
            lock_height=spec.lock_height,
            hinge_heights=list(spec.hinge_heights or []),
            engraving_data=engraving_data or {},
            spec=spec,
        )
        return driver.build_qr_payload(ctx)

    @staticmethod
    def _collect_active_machining_features(
            state: ItemRuntimeState,
            cache: OrderReferenceCache,
            hinge_id: Optional[int],
    ) -> Dict[str, List[MachiningFeature]]:
        """
        Собирает активные MachiningFeature со всей фурнитуры двери (ручка, замок, петли,
        фурнитура кастомизаторов и SpecBOMItem) из OrderReferenceCache без запросов к БД.
        """
        spec = state.spec
        features_by_role: Dict[str, Dict[int, MachiningFeature]] = {}

        def _register_hw(hw: Optional[Hardware]) -> None:
            if not hw:
                return
            feat = getattr(hw, 'machining_feature', None)
            if feat:
                features_by_role.setdefault(feat.affects_role, {})[feat.id] = feat

        # 1. Ручка заказа (только если на двери действительно есть ручка)
        if spec.has_handle and state.order.handle_id:
            _register_hw(cache.hardware_by_id.get(state.order.handle_id))

        # 2. Замок и петли
        if spec.lock_id:
            _register_hw(cache.hardware_by_id.get(spec.lock_id))
        if hinge_id:
            _register_hw(cache.hardware_by_id.get(hinge_id))

        # 3. Фурнитура и SKU-параметры кастомизаторов
        for gc in state.customizers:
            if gc.customizer.hardware_id:
                _register_hw(cache.hardware_by_id.get(gc.customizer.hardware_id))
            for i in range(1, 6):
                raw_val = getattr(gc, f'par{i}', None)
                if isinstance(raw_val, str) and raw_val.strip().upper().startswith('SKU='):
                    sku = raw_val.strip().split('=', 1)[1].strip()
                    if sku:
                        _register_hw(cache.hardware_by_sku.get(sku))

        # 4. Вся остальная фурнитура из итогового BOM (по item_id и sku)
        for bi in spec.bom_items:
            if bi.type != 'hardware' or str(bi.tag or '').lower() in _MATERIAL_BOM_TAGS:
                continue
            if bi.item_id and bi.item_id in cache.hardware_by_id:
                _register_hw(cache.hardware_by_id[bi.item_id])
            elif bi.sku and bi.sku in cache.hardware_by_sku:
                _register_hw(cache.hardware_by_sku[bi.sku])

        return {role: list(bucket.values()) for role, bucket in features_by_role.items()}

    @staticmethod
    def _resolve_hardware_macro(
            hardware_id: Optional[int],
            door_family,
            target_role: str,
            features_by_role: Dict[str, List[MachiningFeature]],
            cache: OrderReferenceCache,
    ) -> Tuple[Optional[HardwareMacroFile], Optional[str]]:
        """
        Подбирает HardwareMacroFile из кэша с учётом MachiningFeature.
        Возвращает (macro_obj, error_message).
        """
        if not hardware_id or not door_family:
            return None, None

        role_features = features_by_role.get(target_role, [])
        if len(role_features) > 1:
            names = ", ".join(f.name for f in role_features)
            return None, f"התנגשות מאפייני עיבוד עבור {target_role}: {names}"

        candidates = cache.hardware_macros.get((hardware_id, door_family.id), [])

        if len(role_features) == 1:
            feature = role_features[0]
            macro = next((m for m in candidates if m.machining_feature_id == feature.id), None)
            if not macro or not macro.file_name:
                return None, f"חסר קובץ מאקרו עבור '{feature.name}' למשפחת '{door_family.name}'"
            return macro, None

        macro = next((m for m in candidates if m.machining_feature_id is None), None)
        return macro, None

    @staticmethod
    def _format_hardware_label(base_name: str, macro: Optional[HardwareMacroFile]) -> str:
        """Формирует понятное оператору название замка/петель для печати на наклейке."""
        if macro and macro.label_name and macro.label_name.strip():
            return macro.label_name.strip()[:128]
        if macro and macro.machining_feature_id:
            feat_name = macro.machining_feature.name
            text = f"{base_name} — {feat_name}" if base_name else feat_name
            return text[:128]
        return (base_name or '')[:128]

    @staticmethod
    def _build_addons_summary(spec) -> str:
        """Собирает текстовую сводку доп. кастомизаторов наклейки (разделитель ' | ')."""
        parts: List[str] = []
        for c in spec.label_customizers or []:
            p_strs = [f"{p.label}:{p.value}" for p in (c.params or [])]
            if p_strs:
                parts.append(f"{c.name} ({', '.join(p_strs)})")
            elif c.name:
                parts.append(c.name)
        return " | ".join(parts)
