import math
from typing import Dict, Optional

from .base import ItemRuntimeState


def round_press_dimension(val: float | int, allowance: float = 1.0) -> float:
    """Прибавляет технологический припуск и округляет вверх с шагом 0.5 см."""
    target = float(val) + float(allowance)
    integer_part = math.floor(target)
    fraction = round(target - integer_part, 4)

    if fraction == 0:
        return float(integer_part)
    if fraction <= 0.5:
        return integer_part + 0.5
    return float(integer_part + 1)


def calculate_geometry(state: ItemRuntimeState) -> None:
    product = state.product
    spec = state.spec
    rules = state.rules

    if not product or not product.product_family:
        return

    if not spec.has_door:
        spec.panel_dimensions = []
        spec.press_dimensions = []
        spec.cut_sheets = []
        return

    h = spec.height
    w = spec.width
    bottom_correction = float(spec.addition_cut or 0.0)

    # 1. Внутренний свет проёма коробки
    spec.inner_height = h - rules.frame_inner_height_reduction
    spec.inner_width = w - rules.frame_inner_width_reduction
    spec.frame_inner_height_reduction = rules.frame_inner_height_reduction
    spec.frame_inner_width_reduction = rules.frame_inner_width_reduction
    spec.leaf_top_clearance = rules.leaf_top_clearance

    if state.phase == 'phase1':
        spec.panel_dimensions = []
        spec.press_dimensions = []
        spec.cut_sheets = []
        return

    # 2. Чистовые размеры полотна (верх + опционально низ для трапеции)
    h_panel = spec.inner_height - rules.leaf_top_clearance - rules.leaf_bottom_clearance - bottom_correction
    has_trapezoid = bool(spec.width_bottom and spec.width_bottom > 0)
    inner_w_bottom = (
        float(spec.width_bottom) - rules.frame_inner_width_reduction
        if has_trapezoid else None
    )

    if not state.is_double:
        w_panel = spec.inner_width - rules.leaf_side_clearance
        panel_dict: Dict[str, Optional[float]] = {
            'width': round(w_panel, 2),
            'height': round(h_panel, 2),
        }
        if inner_w_bottom is not None:
            panel_dict['width_bottom'] = round(inner_w_bottom - rules.leaf_side_clearance, 2)
        panels = [panel_dict]
    else:
        w_net = spec.inner_width - 2 * rules.leaf_side_clearance
        par1 = state.double_door_par1
        par2 = state.double_door_par2

        if par2 > 0:
            w1 = par2 + 1.0
        else:
            if not (0 < par1 < 1):
                par1 = 0.5
            w1 = w_net * par1 + 1.0

        w2 = w_net - w1 + rules.double_leaf_overlap
        p1: Dict[str, Optional[float]] = {'width': round(w1, 2), 'height': round(h_panel, 2)}
        p2: Dict[str, Optional[float]] = {'width': round(w2, 2), 'height': round(h_panel, 2)}

        if inner_w_bottom is not None:
            w_net_bottom = inner_w_bottom - 2 * rules.leaf_side_clearance
            w1_b = (par2 + 1.0) if par2 > 0 else (w_net_bottom * par1 + 1.0)
            w2_b = w_net_bottom - w1_b + rules.double_leaf_overlap
            p1['width_bottom'] = round(w1_b, 2)
            p2['width_bottom'] = round(w2_b, 2)

        panels = [p1, p2]

    spec.panel_dimensions = panels

    # 3. Заготовки под пресс (в см, по большей ширине, вычет канта в см, шаг округления 0.5 см)
    press_dims = []
    for p in panels:
        pw = max(float(p['width'] or 0), float(p.get('width_bottom') or 0))
        ph = float(p['height'] or 0)


        press_dims.append({
            'width': round_press_dimension(pw, rules.press_allowance),
            'height': round_press_dimension(ph, rules.press_allowance),
        })

    spec.press_dimensions = press_dims

    # 4. Раскрой листов (с учётом максимальной ширины для трапеции)
    _calculate_cut_sheets(state)


def _calculate_cut_sheets(state: ItemRuntimeState) -> None:
    spec = state.spec
    coeffs = spec.cut_coefficients
    panels = spec.panel_dimensions

    if not coeffs or not panels:
        spec.cut_sheets = []
        return

    try:
        rail_delta = float(coeffs.get('rail_delta') or 0.0)
    except (ValueError, TypeError):
        rail_delta = 0.0

    cut_sheets = []
    for i, panel in enumerate(panels):
        panel_w = max(float(panel.get('width') or 0), float(panel.get('width_bottom') or 0))
        panel_h = float(panel.get('height') or 0)

        cut_sheets.append({
            'panel_index': i + 1,
            'alucobond': _calc_sheet(panel_w, panel_h, coeffs.get('alucobond')),
            'exterior_panel': _calc_sheet(panel_w, panel_h, coeffs.get('exterior_panel')),
            'interior_panel': _calc_sheet(panel_w, panel_h, coeffs.get('interior_panel')),
            'rails': {
                'width': round(panel_w + rail_delta, 2),
                'count': int(panel_h // 50),
            },
        })

    spec.cut_sheets = cut_sheets


def _calc_sheet(w: float, h: float, delta_dict: Optional[dict]) -> Optional[Dict[str, float]]:
    if not isinstance(delta_dict, dict):
        return None
    try:
        dw = float(delta_dict.get('width_delta') or 0)
        dh = float(delta_dict.get('height_delta') or 0)
        return {'width': round(w + dw, 2), 'height': round(h + dh, 2)}
    except (ValueError, TypeError):
        return None
