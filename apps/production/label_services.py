from typing import List, Tuple

from apps.orders.models import Order
from .models import DoorLabel


class DoorLabelService:
    @staticmethod
    def init_item_label_drafts(order, item, is_double_door: bool, has_inlaid_edge: bool) -> list[dict]:
        """
        Creates initial draft dictionaries for door labels.
        Sets identifiers, leaf role (0, 1, 2) and required label types.
        """
        drafts = []

        roles = (
            [DoorLabel.LeafRole.ACTIVE, DoorLabel.LeafRole.PASSIVE]
            if is_double_door
            else [DoorLabel.LeafRole.SINGLE]
        )

        label_types = [
            DoorLabel.LabelType.ROUGHING,
            DoorLabel.LabelType.FINISHING,
        ]
        if has_inlaid_edge:
            label_types.insert(0, DoorLabel.LabelType.PRE_ROUGHING)

        mark_str = str(item.mark or item.id)
        client_name = order.customer or ''

        for role in roles:
            for l_type in label_types:
                drafts.append({
                    'order_id': order.id,
                    'order_item_id': item.id,
                    'order_number': order.order_number,
                    'client_name': client_name,
                    'item_mark': mark_str,
                    'leaf_role': role,
                    'label_type': l_type,
                })

        return drafts

    @staticmethod
    def _evaluate_cnc_target(item_spec) -> Tuple[str, str]:
        """
        Determines the CNC machine and creates the payload string.
        Returns: (target_machine, qr_payload)
        """
        customizers = getattr(item_spec, 'doors_report_customizers', []) or []
        width = float(getattr(item_spec, 'leaf_width', 0) or getattr(item_spec, 'width', 0) or 0)
        height = float(getattr(item_spec, 'leaf_height', 0) or getattr(item_spec, 'height', 0) or 0)
        order_num = getattr(item_spec, 'order_number', '')
        mark = getattr(item_spec, 'mark', '1')

        # 1. Check custom project trigger
        has_custom = any(
            c.get('cnc_support') == 'CUSTOM_PROJECT' if isinstance(c, dict)
            else getattr(c, 'cnc_support', '') == 'CUSTOM_PROJECT'
            for c in customizers
        )
        if has_custom:
            payload = f"C:\\Ww8\\PROJECTS\\{order_num}\\d{mark}.pgmx"
            return DoorLabel.TargetMachine.ACCORD_CUSTOM, payload

        # 2. Check standard extra machining that forces Accord
        has_std_extra = any(
            c.get('cnc_support') == 'STANDARD' if isinstance(c, dict)
            else getattr(c, 'cnc_support', '') == 'STANDARD'
            for c in customizers
        )

        # 3. Check Essepigi dimensional limits
        is_double = getattr(item_spec, 'is_double_door', False)
        within_essepigi_limits = (
                not is_double
                and (600.0 <= width <= 1000.0)
                and (1800.0 <= height <= 2300.0)
        )

        lock_h = getattr(item_spec, 'lock_height', None) or 0
        hinges = getattr(item_spec, 'hinge_heights', []) or []
        hinges_str = ",".join(str(h) for h in hinges)

        if not has_std_extra and within_essepigi_limits:
            # Format payload for Essepigi
            payload = (
                f"CMD=DOOR;L={height:g};W={width:g};"
                f"EDGE={getattr(item_spec, 'edge_type', 'STANDARD')};"
                f"LOCK_H={lock_h:g};HINGES={hinges_str}"
            )
            return DoorLabel.TargetMachine.ESSEPIGI, payload

        # Default fallback: Accord Standard Macro
        payload = (
                f"C:\\Ww8\\PRG\\MODELS\\STD_DOOR.pgmx|"
                f"L={height:g}|W={width:g}|lock={lock_h:g}|"
                + "|".join(f"h{i + 1}={h:g}" for i, h in enumerate(hinges))
        )
        return DoorLabel.TargetMachine.ACCORD_STD, payload

    @classmethod
    def generate_labels_for_order(cls, order: Order, spec_obj) -> List[DoorLabel]:
        """
        Builds and bulk creates all DoorLabel records for the order specification.
        """
        # Clear existing unprinted or previous snapshot labels for this order
        order.door_labels.all().delete()

        items = getattr(spec_obj, 'items', [])
        total_items = len(items)
        client_name = getattr(order, 'customer', '')
        labels_to_create = []

        for item in items:
            has_door = getattr(item, 'has_door', True)
            if not has_door:
                continue

            target_machine, qr_payload = cls._evaluate_cnc_target(item)
            order_item_id = getattr(item, 'item_id', None)
            hinges = getattr(item, 'hinge_heights', []) or []
            padded_hinges = (hinges + [None] * 5)[:5]

            # Common parameters
            base_kwargs = {
                'order': order,
                'order_item_id': order_item_id,
                'order_number': order.order_number,
                'client_name': client_name,
                'item_mark': str(getattr(item, 'mark', order_item_id)),
                'total_items': total_items,
                'width': getattr(item, 'leaf_width', None) or getattr(item, 'width', None),
                'height': getattr(item, 'leaf_height', None) or getattr(item, 'height', None),
                'thickness': getattr(item, 'leaf_thickness', 40.0),
                'direction': getattr(item, 'direction', ''),
                'opening': getattr(item, 'opening', ''),
                'edge_type': getattr(item, 'edge_type', ''),
                'is_paint': bool(getattr(item, 'is_paint', False)),
                'lock_name': getattr(item, 'lock_name', ''),
                'lock_height': getattr(item, 'lock_height', None),
                'hinge_name': getattr(item, 'hinge_name', ''),
                'hinge_1': padded_hinges[0],
                'hinge_2': padded_hinges[1],
                'hinge_3': padded_hinges[2],
                'hinge_4': padded_hinges[3],
                'hinge_5': padded_hinges[4],
                'comment': getattr(item, 'comment', ''),
                'target_machine': target_machine,
                'qr_payload': qr_payload,
            }

            # Check if door requires inlaid wood edge (3 labels instead of 2)
            has_inlaid_edge = bool(getattr(item, 'has_inlaid_edge', False))

            if has_inlaid_edge:
                # 0. Pre-roughing label
                labels_to_create.append(DoorLabel(
                    **base_kwargs,
                    label_type=DoorLabel.LabelType.PRE_ROUGHING
                ))

            # 1. Standard / Final roughing label
            labels_to_create.append(DoorLabel(
                **base_kwargs,
                label_type=DoorLabel.LabelType.ROUGHING
            ))

            # 2. Finishing (locks & hardware) label
            labels_to_create.append(DoorLabel(
                **base_kwargs,
                label_type=DoorLabel.LabelType.FINISHING
            ))

        return DoorLabel.objects.bulk_create(labels_to_create)

    @staticmethod
    def enrich_geometry(
            drafts: list[dict],
            item_spec,
            leaf_width: float,
            leaf_height: float,
            leaf_thickness: float = 40.0,
            direction: str = '',
            opening: str = '',
            edge_type: str = '',
            is_paint: bool = False,
            passive_width: float = None,
    ) -> None:
        """
        Enriches label drafts with calculated panel dimensions, opening, and finish specs.
        Modifies drafts in-place.
        """
        for draft in drafts:
            # If double door and passive leaf has its own width
            if draft.get('leaf_role') == DoorLabel.LeafRole.PASSIVE and passive_width is not None:
                w = passive_width
            else:
                w = leaf_width

            draft.update({
                'width': float(w) if w is not None else None,
                'height': float(leaf_height) if leaf_height is not None else None,
                'thickness': float(leaf_thickness) if leaf_thickness is not None else 40.0,
                'direction': direction or '',
                'opening': opening or '',
                'edge_type': edge_type or '',
                'is_paint': is_paint,
            })

    @classmethod
    def enrich_hardware_and_cnc(cls, drafts: list[dict], spec, item) -> None:
        """
        Обогащает заготовки наклеек данными фурнитуры, высотами петель,
        комментариями, кастомизаторами и вычисляет управляющую программу ЧПУ.
        """
        if not drafts:
            return

        raw_hinges = getattr(spec, 'hinge_heights', []) or []
        padded_hinges = (list(raw_hinges) + [None] * 5)[:5]

        # Определение станка ЧПУ и QR-пейлоада
        target_machine, qr_payload = cls._evaluate_cnc_target(spec)

        # Сводка по кастомизаторам для наклейки
        customizers_list = getattr(spec, 'doors_report_customizers', []) or []
        addons_parts = []
        for c in customizers_list:
            c_name = getattr(c, 'name', '') if hasattr(c, 'name') else c.get('name', '')
            params = getattr(c, 'params', []) if hasattr(c, 'params') else c.get('params', [])
            p_strs = [
                f"{p.label}:{p.value}" if hasattr(p, 'label') else f"{p.get('label')}:{p.get('value')}"
                for p in params
            ]
            if p_strs:
                addons_parts.append(f"{c_name} ({', '.join(p_strs)})")
            elif c_name:
                addons_parts.append(c_name)
        addons_summary = " | ".join(addons_parts)

        comment = spec.comment or item.comment or ''

        for draft in drafts:
            draft.update({
                'lock_name': getattr(spec, 'lock_name', '') or '',
                'lock_height': getattr(spec, 'lock_height', None),
                'hinge_name': getattr(spec, 'hinge_name', '') or '',
                'hinge_1': padded_hinges[0],
                'hinge_2': padded_hinges[1],
                'hinge_3': padded_hinges[2],
                'hinge_4': padded_hinges[3],
                'hinge_5': padded_hinges[4],
                'addons_summary': addons_summary,
                'comment': comment,
                'target_machine': target_machine,
                'qr_payload': qr_payload,
            })

    @classmethod
    def persist_label_drafts(cls, order: Order, all_drafts: list[dict]) -> None:
        """
        Пакетно сохраняет или обновляет наклейки заказа в БД.
        Для существующих записей обновляет параметры геометрии и ЧПУ,
        сохраняя print_count и last_printed_at.
        """
        if not all_drafts:
            return

        # Общее число дверных позиций в заказе
        total_doors = len({d['order_item_id'] for d in all_drafts})
        for d in all_drafts:
            d['total_items'] = total_doors

        # Существующие наклейки по уникальному ключу створки
        existing_map = {
            (l.order_item_id, l.leaf_role, l.label_type): l
            for l in DoorLabel.objects.filter(order_id=order.id)
        }

        to_create = []
        to_update = []

        update_fields = [
            'order_number', 'client_name', 'item_mark', 'total_items',
            'width', 'height', 'thickness', 'direction', 'opening',
            'edge_type', 'is_paint', 'lock_name', 'lock_height',
            'hinge_name', 'hinge_1', 'hinge_2', 'hinge_3', 'hinge_4', 'hinge_5',
            'addons_summary', 'comment', 'target_machine', 'qr_payload'
        ]

        for d in all_drafts:
            key = (d['order_item_id'], d['leaf_role'], d['label_type'])
            if key in existing_map:
                lbl = existing_map[key]
                for f in update_fields:
                    if f in d:
                        setattr(lbl, f, d[f])
                to_update.append(lbl)
            else:
                to_create.append(DoorLabel(**d))

        if to_update:
            DoorLabel.objects.bulk_update(to_update, update_fields)
        if to_create:
            DoorLabel.objects.bulk_create(to_create)
