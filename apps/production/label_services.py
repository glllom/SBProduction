from typing import List, Tuple

from apps.orders.models import Order
from .models import DoorLabel


class DoorLabelService:
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
        client_name = getattr(order, 'customer_name', '') or str(order.user or '')
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
