from typing import Dict, Any

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
    def _normalize_to_mm(val: float) -> float:
        """Normalizes dimension value to mm if provided in cm."""
        if val <= 0:
            return 0.0
        return val * 10.0 if val < 300.0 else val

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
    def _build_qr_payload(
            cls,
            machine: str,
            label_type: int,
            draft: dict,
            item_spec,
            engraving_data: Dict[str, Any]
    ) -> str:
        """
        Builds CNC QR payload based on assigned target machine and operation type.
        Uses leaf-specific width/height from the draft.
        """
        w_raw = float(draft.get('width') or getattr(item_spec, 'width', 0) or 0)
        h_raw = float(draft.get('height') or getattr(item_spec, 'height', 0) or 0)
        w_mm = cls._normalize_to_mm(w_raw)
        h_mm = cls._normalize_to_mm(h_raw)

        order_num = draft.get('order_number') or getattr(item_spec, 'order_number', '')
        mark = draft.get('item_mark') or getattr(item_spec, 'mark', '1')
        lock_h = getattr(item_spec, 'lock_height', None) or 0
        hinges = getattr(item_spec, 'hinge_heights', []) or []
        hinges_str = ",".join(str(h) for h in hinges)
        edge = draft.get('edge_type') or getattr(item_spec, 'wood_edge_type', 'STANDARD') or 'STANDARD'

        # 1. Accord Custom Project File
        if machine == DoorLabel.TargetMachine.ACCORD_CUSTOM:
            return f"C:\\Ww8\\PROJECTS\\{order_num}\\d{mark}.pgmx"

        # 2. Essepigi Command Syntax
        if machine == DoorLabel.TargetMachine.ESSEPIGI:
            op_code = "CLEANING" if label_type in (0, 1) else "LOCKS"
            payload = (
                f"CMD={op_code};L={h_mm:g};W={w_mm:g};"
                f"EDGE={edge};LOCK_H={lock_h:g};HINGES={hinges_str}"
            )
            if engraving_data.get('icon_filename'):
                payload += f";ENGRAVE={engraving_data['icon_filename']}"
                for i in range(1, 6):
                    val = engraving_data.get(f'p{i}')
                    if val is not None:
                        payload += f";P{i}={val}"
            return payload

        # 3. Accord Standard Macro Syntax
        payload_parts = [
            "C:\\Ww8\\PRG\\MODELS\\STD_DOOR.pgmx",
            f"OP={label_type}",
            f"L={h_mm:g}",
            f"W={w_mm:g}",
            f"lock={lock_h:g}",
        ]
        payload_parts.extend(f"h{i + 1}={h:g}" for i, h in enumerate(hinges))

        if engraving_data.get('icon_filename'):
            payload_parts.append(f"engrave={engraving_data['icon_filename']}")
            for i in range(1, 6):
                val = engraving_data.get(f'p{i}')
                if val is not None:
                    payload_parts.append(f"p{i}={val}")

        return "|".join(payload_parts)

    @classmethod
    def enrich_hardware_and_cnc(cls, drafts: list[dict], spec, item) -> None:
        """
        Enriches label drafts with hardware, filtered label customizers,
        engraving icon name, and per-operation CNC target machine & QR payload.
        """
        if not drafts:
            return

        raw_hinges = getattr(spec, 'hinge_heights', []) or []
        padded_hinges = (list(raw_hinges) + [None] * 5)[:5]

        # Build addons summary strictly from tag-filtered label_customizers
        label_customizers = getattr(spec, 'label_customizers', []) or []
        addons_parts = []
        for c in label_customizers:
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
        engraving_data = getattr(spec, 'engraving_data', {}) or {}
        cnc_targets = getattr(spec, 'cnc_targets', {}) or {}

        for draft in drafts:
            l_type = draft.get('label_type', DoorLabel.LabelType.ROUGHING)
            target_machine = (
                    cnc_targets.get(l_type)
                    or cnc_targets.get(str(l_type))
                    or DoorLabel.TargetMachine.ESSEPIGI
            )
            qr_payload = cls._build_qr_payload(target_machine, l_type, draft, spec, engraving_data)

            draft.update({
                'lock_name': getattr(spec, 'lock_name', '') or '',
                'lock_height': getattr(spec, 'lock_height', None),
                'hinge_name': getattr(spec, 'hinge_name', '') or '',
                'hinge_1': padded_hinges[0],
                'hinge_2': padded_hinges[1],
                'hinge_3': padded_hinges[2],
                'hinge_4': padded_hinges[3],
                'hinge_5': padded_hinges[4],
                'icon_filename': engraving_data.get('icon_filename', ''),
                'addons_summary': addons_summary,
                'comment': comment,
                'target_machine': target_machine,
                'qr_payload': qr_payload,
            })

    @classmethod
    def persist_label_drafts(cls, order: Order, all_drafts: list[dict]) -> None:
        """
        Bulk creates or updates door labels in the database, preserving print counters.
        """
        if not all_drafts:
            return

        total_doors = len({d['order_item_id'] for d in all_drafts})
        for d in all_drafts:
            d['total_items'] = total_doors

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
            'icon_filename', 'addons_summary', 'comment', 'target_machine', 'qr_payload'
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
