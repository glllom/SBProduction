import copy
from typing import Optional

from apps.catalog.models import Material
from .base import ItemRuntimeState
from ..cache import OrderReferenceCache
from ..schemas import SpecBOMItem

MATERIAL_SLOTS = (
    ('covering', 'כיסוי'),
    ('base', 'בסיס'),
    ('filling', 'מילוי'),
    ('panel_frame', 'panel_frame'),
    ('casing', 'הלבשה'),
    ('frame', 'משקוף'),
    ('profile1', 'פרופיל 1'),
    ('profile2', 'פרופיל 2'),
    ('profile3', 'פרופיל 3'),
    ('other1', 'אחר 1'),
    ('other2', 'אחר 2'),
    ('other3', 'אחר 3'),
    ('other4', 'אחר 4'),
    ('other5', 'אחר 5'),
)

HARDWARE_SLOTS = (
    ('lock', 'מנעול', 'lock'),
    ('hinges', 'צירים', 'hinge'),
    ('additional', 'תוספות', 'additional'),
)


def calculate_bom(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    if not state.product or not state.effective_bom:
        return

    _resolve_frame_material(state, cache)
    _apply_bom_overrides(state, cache)
    _apply_casing_substitute(state)

    bom = state.effective_bom
    spec = state.spec
    bom_items = []
    profiles = []

    # 1. Материалы
    for slot_name, label in MATERIAL_SLOTS:
        if not spec.has_frame and slot_name in ('frame', 'casing'):
            continue

        material = getattr(bom, slot_name, None)
        if not material:
            continue

        resolved_mat = _resolve_slot_material(state, cache, material, slot_name)
        qty = _get_consumption(bom, slot_name)
        if qty <= 0 or not resolved_mat:
            continue

        if slot_name in ('profile1', 'profile2', 'profile3'):
            profiles.append(resolved_mat.name)

        # Подбор формата листов (covering / base) под каждую створку в Фазе 2
        if state.phase != 'phase1' and slot_name in ('covering', 'base') and spec.panel_dimensions:
            _append_sized_sheet_items(state, cache, bom_items, resolved_mat, label, slot_name, qty)
        else:
            bom_items.append(
                SpecBOMItem(
                    type='material',
                    section=label,
                    item_name=resolved_mat.name,
                    sku=resolved_mat.sku or "",
                    common_name=resolved_mat.common_name or None,
                    quantity=qty,
                    tag=slot_name,
                    item_id=resolved_mat.id,
                )
            )

    # 2. Деревянный кант (если активен WOOD_EDGE)
    if spec.has_wood_edge:
        we_customizers = state.find_customizers('WOOD_EDGE')
        we_hw = we_customizers[0].customizer.hardware if we_customizers else None
        type_he = 'סמוי' if spec.is_hidden_wood_edge else 'חיצוני'
        thickness_mm = round(spec.wood_edge_thickness * 10, 1)
        thickness_disp = int(thickness_mm) if thickness_mm.is_integer() else thickness_mm
        edge_label = (
            f"קנט עץ {state.wood_edge_wood_type} "
            f"({type_he}, {thickness_disp} מ\"מ, {spec.wood_edge_sides} צדדים)"
        ).strip()
        bom_items.append(
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

    # 3. Базовая фурнитура из BOM (lock / hinge / additional)
    spec.lock_id = None
    spec.lock_name = "N/A"
    spec.hinge_name = "N/A"

    for slot_name, label, tag in HARDWARE_SLOTS:
        val = getattr(bom, slot_name, None)
        if not val:
            continue
        hw_list = list(val.all()) if hasattr(val, 'all') else [val]
        for hw in hw_list:
            bom_items.append(
                SpecBOMItem(
                    type='hardware',
                    section=label,
                    item_name=hw.name,
                    sku=hw.sku or "",
                    common_name=hw.common_name or None,
                    quantity=1,
                    tag=tag,
                    item_id=hw.id,
                )
            )
            if tag == 'lock' and spec.lock_id is None:
                spec.lock_id = hw.id
                spec.lock_name = (hw.common_name or '').strip() or hw.name
            elif tag == 'hinge' and spec.hinge_name == "N/A":
                spec.hinge_name = (hw.common_name or '').strip() or hw.name
                state.hinge_hardware_id = hw.id

    # 4. Дополнительные аксессуары из кастомизаторов (только role == 'OTHER')
    for gc in state.customizers:
        c = gc.customizer
        if c.hardware and getattr(c.hardware, 'role', 'OTHER') == 'OTHER':
            cached_hw = cache.hardware_by_id.get(c.hardware_id, c.hardware)
            tag_str = (c.tag or "").upper()
            for hw in [cached_hw] + list(cached_hw.components.all()):
                bom_items.append(
                    SpecBOMItem(
                        type='hardware',
                        section=tag_str or 'Customizer',
                        item_name=hw.name,
                        sku=hw.sku or "",
                        common_name=hw.common_name or None,
                        quantity=1,
                        tag=tag_str,
                        item_id=hw.id,
                    )
                )

    if state.resolved_frame_material:
        rf = state.resolved_frame_material
        spec.frame = (rf.common_name or '').strip() or rf.name

    spec.bom_items = bom_items
    spec.profiles = profiles


def _get_consumption(bom, slot_name: str) -> float:
    raw = getattr(bom, f"{slot_name}_consumption", None)
    if raw in (None, ''):
        return 0.0
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def _resolve_frame_material(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    if not state.spec.has_frame or not state.product:
        return

    bom_frame = getattr(state.effective_bom, 'frame', None)
    chosen = state.group.basic_color_frames

    material = bom_frame
    if chosen and bom_frame:
        bom_cn = (bom_frame.common_name or '').strip()
        chosen_cn = (chosen.common_name or '').strip()
        if chosen.id == bom_frame.id or (bom_cn and chosen_cn == bom_cn):
            material = chosen
        elif bom_cn and chosen.color_id:
            candidates = cache.materials_by_group_color.get((bom_cn, chosen.color_id), [])
            material = candidates[0] if candidates else bom_frame
    elif chosen and not bom_frame:
        material = chosen

    if not material:
        return

    material = cache.materials_by_id.get(material.id, material)
    if state.item.opening == 'OUT' and material.outward_substitute:
        material = material.outward_substitute

    state.resolved_frame_material = material


def _apply_bom_overrides(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    if state.phase == 'phase1' or not state.effective_bom:
        return

    combined_materials = {}
    combined_pictograms = {}

    for gc in state.customizers:
        overrides = getattr(gc.customizer, 'bom_overrides', None)
        if not isinstance(overrides, dict) or not overrides:
            continue
        if isinstance(overrides.get('materials'), dict):
            combined_materials.update(overrides['materials'])
        if isinstance(overrides.get('pictograms'), dict):
            combined_pictograms.update(overrides['pictograms'])

    if not combined_materials and not combined_pictograms:
        return

    patched = copy.copy(state.effective_bom)

    for slot_name, raw_sku in combined_materials.items():
        if not hasattr(patched, slot_name):
            continue
        clean_sku = str(raw_sku).strip() if raw_sku else ""
        if not clean_sku:
            setattr(patched, slot_name, None)
        elif clean_sku in cache.materials_by_sku:
            setattr(patched, slot_name, cache.materials_by_sku[clean_sku])

    for slot_name, raw_name in combined_pictograms.items():
        if not hasattr(patched, slot_name):
            continue
        clean_name = str(raw_name).strip() if raw_name else ""
        if not clean_name:
            setattr(patched, slot_name, None)
        elif clean_name in cache.puzzle_presets_by_name:
            setattr(patched, slot_name, cache.puzzle_presets_by_name[clean_name])

    state.effective_bom = patched


def _apply_casing_substitute(state: ItemRuntimeState) -> None:
    if not state.effective_bom:
        return
    current_casing = getattr(state.effective_bom, 'casing', None)
    if not current_casing or not state.find_customizers('CASING'):
        return
    substitute = getattr(current_casing, 'outward_substitute', None)
    if not substitute:
        return
    patched = copy.copy(state.effective_bom)
    patched.casing = substitute
    state.effective_bom = patched


def _resolve_slot_material(
        state: ItemRuntimeState,
        cache: OrderReferenceCache,
        material: Material,
        slot_name: str,
) -> Optional[Material]:
    if slot_name == 'frame' and state.resolved_frame_material:
        return state.resolved_frame_material

    selected = state.resolved_frame_material or state.group.basic_color_frames
    cn = (material.common_name or '').strip()
    if cn and selected:
        if (selected.common_name or '').strip() == cn:
            return selected
        if selected.color_id:
            candidates = cache.materials_by_group_color.get((cn, selected.color_id), [])
            if candidates:
                return candidates[0]

    return cache.materials_by_id.get(material.id, material)


def _append_sized_sheet_items(
        state: ItemRuntimeState,
        cache: OrderReferenceCache,
        bom_items: list,
        original: Material,
        label: str,
        slot_name: str,
        total_qty: float,
) -> None:
    panels = state.spec.panel_dimensions
    cn = (original.common_name or '').strip()
    pool = cache.materials_by_group_color.get((cn, original.color_id), [])
    per_panel_qty = total_qty / len(panels)

    for i, panel in enumerate(panels):
        panel_h = float(panel.get('height') or 0)
        panel_w = max(float(panel.get('width') or 0), float(panel.get('width_bottom') or 0))
        suffix = f" (Panel {i + 1})" if len(panels) > 1 else ""

        suitable = next(
            (
                m for m in pool
                if m.length is not None and m.width is not None
                   and float(m.length) >= panel_h + 1.0
                   and float(m.width) >= panel_w
            ),
            None,
        )

        chosen = suitable or original
        bom_items.append(
            SpecBOMItem(
                type='material',
                section=f"{label}{suffix}",
                item_name=chosen.name,
                sku=chosen.sku or "",
                common_name=cn or None,
                quantity=per_panel_qty,
                tag=slot_name,
                item_id=chosen.id,
            )
        )
        if not suitable:
            state.add_error(f"No suitable sheet found for {label}{suffix}")
