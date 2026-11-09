import os
from typing import Dict, Any, Optional, List

from apps.orders.models import Order
from .models import DoorLabel, PerimeterRoutingFile, FrontEngravingFile, HardwareMacroFile, CustomizerMacroFile


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
    def _resolve_perimeter_routing(
            cls,
            label_type: int,
            door_family,
            leaf_role: str
    ) -> tuple[str, bool]:
        """
        Resolves routing filename and edge_shape for label types 0 and 1.
        Filters by door family using the 'doors' M2M field.
        """
        routing_obj: Optional[PerimeterRoutingFile] = None

        if label_type == DoorLabel.LabelType.PRE_ROUGHING:
            # Type 0: always defaults to the first record
            routing_obj = PerimeterRoutingFile.objects.order_by('id').first()
        elif label_type == DoorLabel.LabelType.ROUGHING and door_family:
            # Type 1: linked to specific door family
            routing_obj = PerimeterRoutingFile.objects.filter(doors=door_family).first()

        if not routing_obj or not routing_obj.file_name:
            return '', False

        raw_filename = routing_obj.file_name.strip()
        edge_shape = routing_obj.edge_shape

        # Append double door leaf suffixes
        if leaf_role == DoorLabel.LeafRole.ACTIVE:
            suffix = '_dbl1'
        elif leaf_role == DoorLabel.LeafRole.PASSIVE:
            suffix = '_dbl2'
        else:
            suffix = ''

        if suffix:
            name, ext = os.path.splitext(raw_filename)
            final_filename = f"{name}{suffix}{ext}" if ext else f"{name}{suffix}"
        else:
            final_filename = raw_filename

        return final_filename, edge_shape

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
        Uses leaf-specific width/height and perimeter routing file from draft.
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
        cnc_prog = draft.get('cnc_program') or ''
        edge_shape_flag = int(draft.get('edge_shape', False))

        # 1. Accord Custom Project File
        if machine == DoorLabel.TargetMachine.ACCORD_CUSTOM:
            return f"C:\\Ww8\\PROJECTS\\{order_num}\\d{mark}.pgmx"

        # 2. Essepigi Command Syntax
        if machine == DoorLabel.TargetMachine.ESSEPIGI:
            if label_type in (DoorLabel.LabelType.PRE_ROUGHING, DoorLabel.LabelType.ROUGHING):
                # Barcode payload for perimeter routing operations
                payload = f"PRG={cnc_prog};EDGE_SHAPE={edge_shape_flag};L={h_mm:g};W={w_mm:g};EDGE={edge}"
            else:
                # Finishing / Hardware routing operation
                payload = (
                    f"CMD=LOCKS;L={h_mm:g};W={w_mm:g};"
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
        prog_path = f"C:\\Ww8\\PRG\\ROUTING\\{cnc_prog}.pgmx" if cnc_prog else "C:\\Ww8\\PRG\\MODELS\\STD_DOOR.pgmx"
        payload_parts = [
            prog_path,
            f"OP={label_type}",
            f"EDGE_SHAPE={edge_shape_flag}",
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
    def enrich_hardware_and_cnc(
            cls,
            drafts: list[dict],
            spec,
            item,
            customizers: Optional[list] = None
    ) -> None:
        """
        Enriches label drafts with hardware, dimensions, perimeter routing,
        lock/hinge macros, front engraving, and customizer CNC files.
        """
        if not drafts:
            return

        raw_hinges = getattr(spec, 'hinge_heights', []) or []
        padded_hinges = (list(raw_hinges) + [None] * 5)[:5]

        # 1. Resolve product, door family and front
        product = getattr(item.group, 'product', None) if getattr(item, 'group', None) else None
        door_family = getattr(product, 'product_family', None) if product else None

        group = getattr(item, 'group', None)
        order = getattr(group, 'order', None) if group else None
        front = (getattr(group, 'front', None) or getattr(order, 'front', None)) if group else None

        # 2. Resolve lock & hinge macros
        lock_id = getattr(spec, 'lock_id', None)
        hinge_bi = next(
            (bi for bi in getattr(spec, 'bom_items', []) if str(bi.tag).lower() == 'hinge'),
            None
        )
        hinge_id = hinge_bi.item_id if hinge_bi else None

        lock_program = cls._resolve_hardware_macro(lock_id, door_family)
        hinge_program = cls._resolve_hardware_macro(hinge_id, door_family)

        # 3. Resolve front engraving and customizer macros
        front_program = cls._resolve_front_engraving(front)

        active_customizers = customizers
        if active_customizers is None and group:
            active_customizers = list(group.customizers.all())

        cmz_macros = cls._resolve_customizer_macros(active_customizers or [])
        padded_cmz_macros = (list(cmz_macros) + [''] * 10)[:10]

        # 4. Build addons summary strictly from tag-filtered label_customizers
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

        # 5. Enrich each label draft
        for draft in drafts:
            l_type = draft.get('label_type', DoorLabel.LabelType.ROUGHING)
            role = draft.get('leaf_role', DoorLabel.LeafRole.SINGLE)

            cnc_program, edge_shape = cls._resolve_perimeter_routing(
                label_type=l_type,
                door_family=door_family,
                leaf_role=role
            )

            target_machine = (
                    cnc_targets.get(l_type)
                    or cnc_targets.get(str(l_type))
                    or DoorLabel.TargetMachine.ESSEPIGI
            )

            draft['cnc_program'] = cnc_program
            draft['edge_shape'] = edge_shape

            qr_payload = cls._build_qr_payload(target_machine, l_type, draft, spec, engraving_data)

            draft.update({
                'lock_name': getattr(spec, 'lock_name', '') or '',
                'lock_height': getattr(spec, 'lock_height', None),
                'lock_program': lock_program,
                'hinge_name': getattr(spec, 'hinge_name', '') or '',
                'hinge_program': hinge_program,
                'hinge_1': padded_hinges[0],
                'hinge_2': padded_hinges[1],
                'hinge_3': padded_hinges[2],
                'hinge_4': padded_hinges[3],
                'hinge_5': padded_hinges[4],
                'front_program': front_program,
                'customizer_programs': ";".join(cmz_macros),
                'cmz_prg_1': padded_cmz_macros[0],
                'cmz_prg_2': padded_cmz_macros[1],
                'cmz_prg_3': padded_cmz_macros[2],
                'cmz_prg_4': padded_cmz_macros[3],
                'cmz_prg_5': padded_cmz_macros[4],
                'cmz_prg_6': padded_cmz_macros[5],
                'cmz_prg_7': padded_cmz_macros[6],
                'cmz_prg_8': padded_cmz_macros[7],
                'cmz_prg_9': padded_cmz_macros[8],
                'cmz_prg_10': padded_cmz_macros[9],
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
            'edge_type', 'is_paint', 'cnc_program', 'edge_shape',
            'lock_name', 'lock_height', 'lock_program',
            'hinge_name', 'hinge_program',
            'hinge_1', 'hinge_2', 'hinge_3', 'hinge_4', 'hinge_5',
            'front_program', 'customizer_programs',
            'cmz_prg_1', 'cmz_prg_2', 'cmz_prg_3', 'cmz_prg_4', 'cmz_prg_5',
            'cmz_prg_6', 'cmz_prg_7', 'cmz_prg_8', 'cmz_prg_9', 'cmz_prg_10',
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

    @classmethod
    def _resolve_hardware_macro(cls, hardware_id: Optional[int], door_family) -> str:
        """Resolves macro file name for given hardware and door family."""
        if not hardware_id or not door_family:
            return ""

        macro = HardwareMacroFile.objects.filter(
            hardware__id=hardware_id,
            door_families=door_family,
        ).first()

        return macro.file_name if (macro and macro.file_name) else ""

    @classmethod
    def _resolve_front_engraving(cls, front) -> str:
        """Resolves CNC engraving file name for the door front (1:1 relation)."""
        if not front:
            return ""

        engraving_file = getattr(front, "engraving_file", None)
        if not engraving_file:
            engraving_file = FrontEngravingFile.objects.filter(
                front=front
            ).first()

        return (
            engraving_file.file_name
            if (engraving_file and engraving_file.file_name)
            else ""
        )

    @classmethod
    def _resolve_customizer_macros(cls, customizers: list) -> List[str]:
        """Resolves CNC macro file names for applied customizers (up to 10 files)."""
        if not customizers:
            return []

        # Extract unique customizer instances from group customizers or objects
        cust_objs = []
        for c in customizers:
            cust_obj = getattr(c, "customizer", c)
            if cust_obj and cust_obj not in cust_objs:
                cust_objs.append(cust_obj)

        if not cust_objs:
            return []

        cust_ids = [c.id for c in cust_objs if getattr(c, "id", None)]

        # Fetch linked macro files in batch
        macro_map = {
            cmf.customizer_id: cmf.file_name
            for cmf in CustomizerMacroFile.objects.filter(
                customizer_id__in=cust_ids
            )
            if cmf.file_name
        }

        # Preserve customizer processing order and cap at 10
        result = [
            macro_map[c.id]
            for c in cust_objs
            if c.id in macro_map and macro_map[c.id].strip()
        ]
        return result[:10]
