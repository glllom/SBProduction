"""
Обработчик отчёта участка деревянных коробок (apps.production.reports.wood_frames).

Назначение модуля:
    Формирует 4-уровневую печатную иерархию:
        1. Страница: семейство модели (+ признак כפולה).
        2. Группа материала коробки и наличника (הלבשה).
        3. Группа фурнитуры (замок + высота, петли + высоты).
        4. Строки размеров (сортировка: толщина стены ↑, высота ↓, ширина ↓).
"""

from __future__ import annotations

from typing import Any, Dict, List

from apps.catalog.models import Material
from .common import get_field
from .registry import BaseStationReport, ReportContext, register_report


def build_wood_frames_report_data(items: List[Any]) -> List[Dict[str, Any]]:
    """Группирует позиции с коробками в постраничную структуру для отчёта деревянных коробок."""
    raw_items = [it for it in items if get_field(it, 'has_frame', True)]

    frame_mat_ids = {
        get_field(b, 'item_id')
        for it in raw_items
        for b in (get_field(it, 'bom_items', []) or [])
        if (get_field(b, 'tag', '') == 'frame' or get_field(b, 'section', '') == 'frame') and get_field(b, 'item_id')
    }
    frame_materials_map = (
        {m.id: m for m in Material.objects.filter(id__in=frame_mat_ids).select_related('color')}
        if frame_mat_ids
        else {}
    )

    pages_map: Dict[tuple, Dict[str, Any]] = {}
    for item in raw_items:
        is_double = bool(get_field(item, 'is_double_door', False))
        base_family = (get_field(item, 'product_family', '') or get_field(item, 'product_name', '')).strip()
        page_title = f"{base_family} כפולה" if is_double else base_family
        page_key = (base_family, is_double)

        if page_key not in pages_map:
            pages_map[page_key] = {
                'product_name': page_title,
                'is_double_door': is_double,
                'materials_map': {},
            }

        bom_items = get_field(item, 'bom_items', []) or []
        casing_names = [
            (get_field(b, 'common_name') or get_field(b, 'item_name', ''))
            for b in bom_items
            if get_field(b, 'tag', '') in ('door_casing', 'casing')
               or get_field(b, 'section', '') in ('door_casing', 'casing', 'הלבשה', 'הלבשות')
        ]

        paint_opt = str(get_field(item, 'frame_paint_option', '') or '').upper()
        frame_bom = next(
            (b for b in bom_items if get_field(b, 'tag', '') == 'frame' or get_field(b, 'section', '') == 'frame'),
            None,
        )

        common_name = str(get_field(frame_bom, 'common_name') or '').strip() if frame_bom else ''
        item_name = str(get_field(frame_bom, 'item_name') or '').strip() if frame_bom else ''
        mat_obj = frame_materials_map.get(get_field(frame_bom, 'item_id')) if frame_bom else None

        mat_color = ''
        if mat_obj and getattr(mat_obj, 'color', None):
            mat_color = str(mat_obj.color.name).strip()
        elif common_name and item_name.startswith(common_name):
            mat_color = item_name[len(common_name):].strip(' -')

        if paint_opt == 'NO_PAINT':
            if common_name:
                frames_caption = f"{common_name} {mat_color}".strip() if mat_color else (item_name or common_name)
            else:
                frames_caption = item_name or str(get_field(item, 'frame', '') or '').strip()
        else:
            base_frame_title = common_name or item_name or str(get_field(item, 'frame', '') or '').strip()
            frames_caption = f"{base_frame_title} צבע".strip()

        door_casing = " / ".join(dict.fromkeys(filter(None, casing_names))) or "ללא"

        mat_key = (
            frames_caption,
            door_casing,
            get_field(item, 'basic_color_frames', '') or '',
            get_field(item, 'color_frames', '') or '',
        )
        materials_map = pages_map[page_key]['materials_map']
        if mat_key not in materials_map:
            materials_map[mat_key] = {
                'frames_caption': frames_caption,
                'door_casing': door_casing,
                'hardware_map': {},
            }

        raw_cmz = get_field(item, 'frames_report_customizers', []) or []
        parsed_cmz, cmz_sig_parts = [], []
        for c in raw_cmz:
            c_name = str(get_field(c, 'name', '')).strip()
            if not c_name:
                continue
            clean_params, p_sig = [], []
            for p in (get_field(c, 'params', []) or []):
                p_val = get_field(p, 'value', '')
                if p_val in (None, ''):
                    continue
                p_label = str(get_field(p, 'label', '')).strip()
                p_val_str = str(p_val).strip()
                is_custom = bool(
                    get_field(p, 'is_custom', False)
                    or get_field(p, 'is_modified', False)
                    or (get_field(p, 'is_default', None) is False)
                )
                clean_params.append({'label': p_label, 'value': p_val_str, 'is_custom': is_custom})
                p_sig.append((p_label, p_val_str, is_custom))

            sig = (c_name, tuple(p_sig))
            if sig not in cmz_sig_parts:
                cmz_sig_parts.append(sig)
                parsed_cmz.append({'name': c_name, 'params': clean_params})

        cmz_sig = tuple(cmz_sig_parts)
        raw_hinges = get_field(item, 'hinge_heights', []) or []
        hinges_tuple = tuple(h for h in raw_hinges if h is not None)
        lock_name = '' if is_double else (get_field(item, 'lock_name', '') or '')
        lock_height = None if is_double else get_field(item, 'lock_height', None)

        hw_key = (lock_name, lock_height, get_field(item, 'hinge_name', '') or '', hinges_tuple)
        hardware_map = materials_map[mat_key]['hardware_map']
        if hw_key not in hardware_map:
            hardware_map[hw_key] = {
                'is_double_door': is_double,
                'lock_name': lock_name,
                'lock_height': lock_height,
                'hinge_name': get_field(item, 'hinge_name', '') or '',
                'hinge_heights': list(hinges_tuple),
                'items': [],
            }
        hardware_map[hw_key]['items'].append((item, parsed_cmz, cmz_sig))

    pages: List[Dict[str, Any]] = []
    for page_data in pages_map.values():
        material_groups = []
        for mat_data in page_data['materials_map'].values():
            sorted_hw_items = sorted(
                mat_data['hardware_map'].values(),
                key=lambda h: float(h['lock_height']) if h['lock_height'] is not None else float('-inf'),
                reverse=True,
            )

            hardware_groups = []
            for hw_grp in sorted_hw_items:
                row_groups: Dict[tuple, Dict[str, Any]] = {}
                for it, parsed_cmz, cmz_sig in hw_grp['items']:
                    w = get_field(it, 'width', None)
                    h = get_field(it, 'height', None)
                    wall = get_field(it, 'wall', None)
                    direction = '' if hw_grp['is_double_door'] else (get_field(it, 'direction', '') or '')
                    comment = (get_field(it, 'comment', '') or '').strip()

                    row_key = (w, h, wall, direction, comment, cmz_sig)
                    if row_key not in row_groups:
                        row_groups[row_key] = {
                            'width': w,
                            'height': h,
                            'wall': wall,
                            'direction': direction,
                            'qty': 0,
                            'customizers': parsed_cmz,
                            'comment': comment,
                        }
                    row_groups[row_key]['qty'] += 1

                sorted_rows = sorted(
                    row_groups.values(),
                    key=lambda r: (
                        float(r['wall']) if r['wall'] is not None else float('inf'),
                        -float(r['height']) if r['height'] is not None else float('inf'),
                        -float(r['width']) if r['width'] is not None else float('inf'),
                    ),
                )

                hinge_heights = hw_grp.get('hinge_heights', [])
                hinge_heights_display = (
                    "   ".join(str(int(hh)) if float(hh).is_integer() else str(hh) for hh in hinge_heights)
                    if hinge_heights
                    else ""
                )

                hardware_groups.append({
                    'is_double_door': hw_grp['is_double_door'],
                    'lock_name': hw_grp['lock_name'],
                    'lock_height': hw_grp['lock_height'],
                    'hinge_name': hw_grp['hinge_name'],
                    'hinge_heights_display': hinge_heights_display,
                    'grouped_rows': sorted_rows,
                })

            material_groups.append({
                'frames_caption': mat_data['frames_caption'],
                'door_casing': mat_data['door_casing'],
                'hardware_groups': hardware_groups,
            })

        pages.append({
            'product_name': page_data['product_name'],
            'is_double_door': page_data['is_double_door'],
            'material_groups': material_groups,
        })

    total_pages = len(pages)
    for idx, page in enumerate(pages, start=1):
        page['page_num'] = idx
        page['total_pages'] = total_pages

    return pages


@register_report('wood_frames', label='דו"ח משקופי עץ', aliases=('wooden_frames',))
class WoodFramesStationReport(BaseStationReport):
    """Книжный отчёт участка деревянных коробок."""

    template_name = 'production/reports/report_wood_frames.html'
    include_template = 'production/includes/report_wood_frames.html'
    is_portrait = True
    default_label = 'דו"ח משקופי עץ'

    def get_extra_context(self, ctx: ReportContext) -> Dict[str, Any]:
        return {
            'frame_groups': build_wood_frames_report_data(ctx.station_items),
        }
