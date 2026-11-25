"""
Плагин деревянного канта (apps.production.engine.plugins.wood_edge).

Назначение модуля:
    Инкапсулирует всю логику деревянного канта (наружного и скрытого):
        - on_init: разбирает породу дерева (par1), тип канта (par2: hidden/outer),
          толщину строго в см (par3 или дефолт 2.0 / 1.7 / 1.0 см) и число сторон (par4).
        - on_geometry: пересчитывает заготовки на пресс (press_dimensions) с вычетом
          толщины канта по активным сторонам и округлением с шагом 0.5 см.
        - on_bom: добавляет итоговую строку 'קנט עץ' (tag='wood_edge') в spec.bom_items.

Приоритет:
    priority = 20 — выполняется после DoubleDoorPlugin (priority=10), чтобы корректно
    выбрать толщину скрытого канта для двустворчатых дверей (1.7 см vs 1.0 см).
"""

from __future__ import annotations

from apps.production.engine.calculators.geometry import round_press_dimension
from apps.production.engine.schemas import SpecBOMItem
from .registry import BaseCustomizerPlugin, register_customizer


@register_customizer('WOOD_EDGE', label='קנט עץ (חישוב פרס, BOM ומדבקה 0)')
class WoodEdgePlugin(BaseCustomizerPlugin):
    """Полный цикл расчёта наружного и скрытого деревянного канта (в сантиметрах)."""

    priority = 20

    def on_init(self, state, gc, cache) -> None:
        spec = state.spec
        if state.phase == 'phase1' or not spec.has_door:
            return

        c = gc.customizer
        state.wood_edge_wood_type = (gc.par1 if gc.par1 not in (None, '') else c.par1_value or '').strip()

        edge_type_raw = str(gc.par2 if gc.par2 not in (None, '') else c.par2_value or '').strip().lower()
        is_hidden = any(k in edge_type_raw for k in ('hidden', 'סמוי', 'פנימי'))

        thickness_raw = gc.par3 if gc.par3 not in (None, '') else c.par3_value
        custom_thickness_cm = None
        if thickness_raw not in (None, ''):
            try:
                val = float(thickness_raw)
                if val > 0:
                    custom_thickness_cm = val
            except (ValueError, TypeError):
                pass

        if custom_thickness_cm is not None:
            thickness_cm = custom_thickness_cm
        elif not is_hidden:
            thickness_cm = 2.0
        else:
            thickness_cm = 1.7 if state.is_double else 1.0

        sides_raw = gc.par4 if gc.par4 not in (None, '') else c.par4_value
        try:
            sides_count = int(sides_raw) if sides_raw else 4
        except (ValueError, TypeError):
            sides_count = 4
        if sides_count not in (2, 3, 4):
            sides_count = 4

        spec.has_wood_edge = True
        spec.is_hidden_wood_edge = is_hidden
        spec.wood_edge_thickness = thickness_cm
        spec.wood_edge_sides = sides_count
        spec.wood_edge_type = 'hidden' if is_hidden else 'outer'

    def on_geometry(self, state, gc, cache) -> None:
        """Вычитает толщину деревянного канта (в см) из размеров заготовок на пресс."""
        spec = state.spec
        if (
                state.phase == 'phase1'
                or not spec.has_wood_edge
                or spec.wood_edge_thickness <= 0
                or not spec.panel_dimensions
        ):
            return

        t_cm = spec.wood_edge_thickness
        sides = spec.wood_edge_sides
        allowance = state.rules.press_allowance

        adjusted_press = []
        for panel in spec.panel_dimensions:
            pw = max(float(panel.get('width') or 0), float(panel.get('width_bottom') or 0)) - (t_cm * 2)
            ph = float(panel.get('height') or 0) - t_cm * ((1 if sides > 2 else 0) + (1 if sides > 3 else 0))
            adjusted_press.append({
                'width': round_press_dimension(pw, allowance),
                'height': round_press_dimension(ph, allowance),
            })

        spec.press_dimensions = adjusted_press

    def on_bom(self, state, gc, cache) -> None:
        """Добавляет позицию деревянного канта в итоговый список BOM."""
        spec = state.spec
        if state.phase == 'phase1' or not spec.has_wood_edge:
            return

        we_hw = gc.customizer.hardware
        type_he = 'סמוי' if spec.is_hidden_wood_edge else 'חיצוני'
        thickness_mm = round(spec.wood_edge_thickness * 10, 1)
        thickness_disp = int(thickness_mm) if thickness_mm.is_integer() else thickness_mm
        edge_label = (
            f"קנט עץ {state.wood_edge_wood_type} "
            f"({type_he}, {thickness_disp} מ\"מ, {spec.wood_edge_sides} צדדים)"
        ).strip()

        # Идемпотентная замена слота wood_edge (защита от дублирования)
        spec.bom_items = [b for b in spec.bom_items if b.tag != 'wood_edge']
        spec.bom_items.append(
            SpecBOMItem(
                type='material',
                section='קנט עץ',
                item_name=edge_label,
                sku=(we_hw.sku or "") if we_hw else "",
                quantity=spec.wood_edge_sides,
                tag='wood_edge',
                item_id=we_hw.id if we_hw else None,
            )
        )
