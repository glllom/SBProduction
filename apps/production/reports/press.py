"""
Обработчик отчёта участка пресса и склейки полотен (apps.production.reports.press).

Назначение модуля:
    Группирует заготовки полотен по составу сэндвича (בסיס / מילוי / מסגרת עץ),
    покрытию (פורמייקה / צבע / קנט פנימי), применённым пресетам кастомизаторов
    и геометрии SVG-пазла. Использует готовые press_dimensions из расчётного ядра.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from apps.engineering.models import SvgPattern
from apps.production.engine.calculators.geometry import round_press_dimension
from .common import get_field
from .registry import BaseStationReport, ReportContext, register_report


def build_press_groups_data(items: List[Any]) -> List[Dict[str, Any]]:
    """
    Агрегирует список ProductionSpec (или dict-снимков) в карточки пресса
    с подсчётом количества одинаковых заготовок (width × height, шаг 0.5 см).
    """
    groups_map: Dict[tuple, Dict[str, Any]] = {}

    for item in items:
        if not get_field(item, 'has_door', True):
            continue

        is_hidden = bool(get_field(item, 'is_hidden_wood_edge', False))
        bom_items = get_field(item, 'bom_items', []) or []

        def _bom_name(b: Any) -> str:
            return get_field(b, 'common_name') or get_field(b, 'item_name') or ''

        base_names = [_bom_name(b) for b in bom_items if get_field(b, 'tag') == 'base' and _bom_name(b)]
        filling_names = [
            get_field(b, 'item_name')
            for b in bom_items
            if get_field(b, 'tag') == 'filling' and get_field(b, 'item_name')
        ]
        panel_frame_names = [
            _bom_name(b) for b in bom_items if get_field(b, 'tag') == 'panel_frame' and _bom_name(b)
        ]

        # Облицовка (при скрытом деревянном канте облицовка клеится позже — не показываем)
        finish_type = get_field(item, 'finish_type', 'PAINT')
        covering_names = ''
        if not is_hidden:
            if finish_type == 'FORMICA':
                c_out = str(get_field(item, 'color_panel_outside', '') or '').strip()
                c_in = str(get_field(item, 'color_panel_inside', '') or '').strip()
                if c_in and c_in != c_out:
                    covering_names = f"חוץ: {c_out} / פנים: {c_in}"
                elif c_out:
                    covering_names = c_out
            else:
                coverings = [_bom_name(b) for b in bom_items if get_field(b, 'tag') == 'covering' and _bom_name(b)]
                covering_names = coverings[0] if coverings else ''

        raw_components = base_names + filling_names + panel_frame_names
        comp_title = "  |  ".join(dict.fromkeys(filter(None, raw_components))) or get_field(item, 'product_name', '')

        # Пресеты кастомизаторов и подпись для группировки
        applied = get_field(item, 'applied_presets', []) or []
        customizer_presets, sig_parts = [], []
        for p in applied:
            name = str(get_field(p, 'name', '')).strip()
            if not name:
                continue
            labels = [
                {
                    'text': str(get_field(lbl, 'text', '')).strip(),
                    'is_custom': bool(get_field(lbl, 'is_custom', False)),
                }
                for lbl in (get_field(p, 'labels', []) or [])
                if str(get_field(lbl, 'text', '')).strip()
            ]
            customizer_presets.append({'name': name, 'labels': labels})
            if labels:
                lbl_items = ','.join(f"{lbl['text']}:{int(lbl['is_custom'])}" for lbl in labels)
                lbl_suffix = f"({lbl_items})"
            else:
                lbl_suffix = ""
            sig_parts.append(f"{name}{lbl_suffix}")

        presets_signature = " + ".join(dict.fromkeys(sig_parts))

        puzzle = get_field(item, 'puzzle_spec', None)
        face_blocks = get_field(puzzle, 'face_blocks', []) if puzzle else []
        sandwich_blocks = get_field(puzzle, 'sandwich_blocks', []) if puzzle else []

        def _blocks_sig(blocks: list) -> tuple:
            return tuple(
                (
                    get_field(b, 'x'), get_field(b, 'y'), get_field(b, 'w'), get_field(b, 'h'),
                    get_field(b, 'fill_type'), get_field(b, 'fill_color'),
                    get_field(b, 'pattern_name'), get_field(b, 'text'),
                )
                for b in blocks
            )

        group_key = (
            comp_title,
            covering_names,
            presets_signature,
            _blocks_sig(face_blocks),
            _blocks_sig(sandwich_blocks),
        )
        if group_key not in groups_map:
            groups_map[group_key] = {
                'composition_title': comp_title,
                'covering': covering_names,
                'customizer_presets': customizer_presets,
                'puzzle_face_blocks': face_blocks,
                'puzzle_sandwich_blocks': sandwich_blocks,
                'counter': Counter(),
            }

        # Используем готовые press_dimensions; fallback только для исторических снимков без них
        press_dims = get_field(item, 'press_dimensions', []) or []
        if press_dims:
            for pr in press_dims:
                pw, ph = get_field(pr, 'width'), get_field(pr, 'height')
                if pw is not None and ph is not None:
                    groups_map[group_key]['counter'][(float(pw), float(ph))] += 1
        else:
            has_edge = bool(get_field(item, 'has_wood_edge', False))
            raw_t = float(get_field(item, 'wood_edge_thickness', 0) or 0)
            t_cm = (raw_t / 10.0) if raw_t >= 5.0 else raw_t
            sides = int(get_field(item, 'wood_edge_sides', 4) or 4)

            for p_dim in (get_field(item, 'panel_dimensions', []) or []):
                w, h = get_field(p_dim, 'width'), get_field(p_dim, 'height')
                if w is None or h is None:
                    continue
                w_bottom = get_field(p_dim, 'width_bottom')
                w = max(float(w), float(w_bottom)) if w_bottom is not None else float(w)
                h = float(h)
                if has_edge and t_cm > 0:
                    w -= t_cm * 2
                    h -= t_cm * ((sides > 2) + (sides > 3))
                groups_map[group_key]['counter'][(round_press_dimension(w), round_press_dimension(h))] += 1

    panel_groups: List[Dict[str, Any]] = []
    for grp in groups_map.values():
        counter = grp.pop('counter', Counter())
        dims = [
            {'width': w, 'height': h, 'qty': qty}
            for (w, h), qty in sorted(counter.items(), key=lambda x: (x[0][0], x[0][1]), reverse=True)
        ]
        if dims:
            grp['dimensions'] = dims
            panel_groups.append(grp)

    return panel_groups


@register_report('press', label='דו"ח פרס (חיתוך והדבקה)', aliases=('cutting_press',))
class PressStationReport(BaseStationReport):
    """Книжный печатный отчёт участка пресса с SVG-пиктограммами."""

    template_name = 'production/reports/report_press.html'
    include_template = 'production/includes/report_press.html'
    is_portrait = True
    default_label = 'דו"ח פרס'

    def get_extra_context(self, ctx: ReportContext) -> Dict[str, Any]:
        return {
            'panel_groups': build_press_groups_data(ctx.station_items),
            'svg_patterns': SvgPattern.objects.all(),
        }