import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Union

from apps.catalog.models import Hardware, Material
from apps.engineering.models import BOM
from apps.engineering.schemas import EngineeringRulesConfig
from apps.orders.models import Order, OrderItem, OrderItemsGroup, OrderItemsGroupCustomizer
from ..cache import OrderReferenceCache
from ..schemas import ProductionSpec, SpecBOMItem, SpecCustomizerParam, SpecCustomizerReport

LABEL_CUSTOMIZER_TAGS = {'WINDOW', 'CUSTOM_ROUTING', 'DOOR_CNC', 'HARDWARE_EXTRA'}
ENGRAVING_TAGS = {'ENGRAVING', 'FRONT_ENGRAVING', 'FACE_MILLING'}


@dataclass
class ItemRuntimeState:
    """Транзиентное состояние расчёта одной двери (не попадает в JSON-снимок БД)."""
    item: OrderItem
    group: OrderItemsGroup
    order: Order
    product: Any
    phase: str
    rules: EngineeringRulesConfig
    customizers: List[OrderItemsGroupCustomizer]
    spec: ProductionSpec

    effective_bom: Optional[BOM] = None
    resolved_frame_material: Optional[Material] = None

    is_double: bool = False
    double_door_par1: float = 0.5
    double_door_par2: float = 0.0

    wood_edge_wood_type: str = ""

    lock_mode: str = "WC"
    override_lock_height: Optional[float] = None
    override_hinge_heights: Optional[List[float]] = None
    hinge_hardware_id: Optional[int] = None
    lock_alignment_meta: Optional[Dict[str, Any]] = None

    def add_error(self, message: str) -> None:
        if message not in self.spec.errors:
            self.spec.errors.append(message)

    def find_customizers(self, tags: Union[str, Set[str]]) -> List[OrderItemsGroupCustomizer]:
        tags_set = {tags.upper()} if isinstance(tags, str) else {t.upper() for t in tags}
        found = []
        for gc in self.customizers:
            tag_str = (gc.customizer.tag or "").upper()
            item_tags = {t.strip() for t in tag_str.replace(',', ' ').split() if t.strip()}
            if item_tags & tags_set:
                found.append(gc)
        return found

    def set_bom_hardware_slot(
            self,
            slot_tag: str,
            section: str,
            main_hw: Optional[Hardware],
            cache: OrderReferenceCache,
    ) -> None:
        """Идемпотентно перезаписывает слот фурнитуры (lock / cylinder / hinge / handle)."""
        target_tag = slot_tag.lower()
        self.spec.bom_items = [
            b for b in self.spec.bom_items
            if str(b.tag or '').lower() != target_tag
        ]
        if not main_hw:
            return

        cached_hw = cache.hardware_by_id.get(main_hw.id, main_hw)
        hw_list = [cached_hw] + list(cached_hw.components.all())
        for hw in hw_list:
            self.spec.bom_items.append(
                SpecBOMItem(
                    type='hardware',
                    section=section,
                    item_name=hw.name,
                    sku=hw.sku or "",
                    common_name=hw.common_name or None,
                    quantity=1,
                    tag=target_tag,
                    item_id=hw.id,
                )
            )


def _resolve_item_customizers(item: OrderItem, raw_customizers: List) -> List:
    op = str(getattr(item, 'opening', '') or '').strip().upper()
    if op not in ('OUT', 'OUTWARD', 'החוצה'):
        return list(raw_customizers)

    resolved = []
    for gc in raw_customizers:
        replacement = getattr(gc.customizer, 'outward_replacement', None)
        if replacement and replacement.active:
            gc_copy = copy.copy(gc)
            gc_copy._original_customizer_id = gc.customizer_id
            gc_copy.customizer = replacement
            gc_copy.customizer_id = replacement.id
            resolved.append(gc_copy)
        else:
            resolved.append(gc)
    return resolved


def init_item_state(
        item: OrderItem,
        cache: OrderReferenceCache,
        phase: str = 'phase2',
) -> ItemRuntimeState:
    """Создаёт ItemRuntimeState и заполняет базовые данные, валидацию, DoubleDoor, WoodEdge, Appearance."""
    group = item.group
    order = group.order
    product = group.product
    rules = cache.rules_by_product.get(product.id, EngineeringRulesConfig()) if product else EngineeringRulesConfig()

    raw_customizers = cache.customizers_by_group.get(group.id, [])
    resolved_customizers = _resolve_item_customizers(item, raw_customizers)

    spec = ProductionSpec(
        item_id=item.id,
        mark=item.mark or "",
        place=item.place or "",
        comment=item.comment or "",
        sketch_url=item.sketch.url if item.sketch else "",
        addition_cut=float(item.bottom_correction) if item.bottom_correction else None,
        is_special_detail=bool(getattr(group, 'is_special_detail', False)),
        leaf_thickness=rules.thickness or 4.0,
    )

    state = ItemRuntimeState(
        item=item,
        group=group,
        order=order,
        product=product,
        phase=phase,
        rules=rules,
        customizers=resolved_customizers,
        spec=spec,
        effective_bom=cache.boms_by_product.get(product.id) if product else None,
    )

    _populate_base_and_validate(state, cache)
    _populate_double_door(state)
    _populate_wood_edge(state)
    _populate_appearance(state)
    _format_report_customizers(state)

    return state


def _populate_base_and_validate(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    item = state.item
    product = state.product
    spec = state.spec

    if not product:
        state.add_error("דגם מוצר לא נבחר")
        return

    spec.product_name = product.name
    spec.product_code = product.code
    spec.has_door = product.has_door
    spec.has_frame = product.has_frame
    spec.cut_coefficients = state.rules.cut_coefficients.model_dump(exclude_none=True)

    if product.product_family:
        spec.product_family = product.product_family.name
        if product.series:
            spec.series = product.series.name

    h = float(item.height or 0)
    w = float(item.width or 0)
    raw_wb = getattr(item, 'width_bottom', None)
    w_bottom = float(raw_wb) if raw_wb not in (None, '') else None
    if w_bottom is not None and w_bottom <= 0:
        w_bottom = None
    wall = float(item.wall or 0)

    if spec.has_door or spec.has_frame:
        if h <= 0:
            state.add_error("לא הוזן גובה תקין")
        if w <= 0:
            state.add_error("לא הוזן רוחב תקין")

    spec.height = h
    spec.width = w
    spec.width_bottom = w_bottom
    spec.wall = wall

    if spec.has_frame and wall <= 0:
        state.add_error("לא הוזן עובי קיר למשקוף")

    if spec.has_door:
        if not item.opening:
            state.add_error("לא נבחר כיוון פתיחה (פנימה/החוצה)")
        if not item.direction:
            state.add_error("לא נבחרה יד פתיחה (L/R)")

        if product.product_family and item.opening:
            allowed = getattr(product.product_family, 'allowed_direction', 'BOTH')
            op = str(item.opening).strip().upper()
            is_in = op in ('IN', 'INWARD', 'פנימה')
            is_out = op in ('OUT', 'OUTWARD', 'החוצה')
            if allowed == 'IN_ONLY' and not is_in:
                state.add_error("הדגם תומך בפתיחה פנימה בלבד (IN)")
            elif allowed == 'OUT_ONLY' and not is_out:
                state.add_error("הדגם תומך בפתיחה החוצה בלבד (OUT)")

    spec.direction_code = item.direction or ""
    spec.opening_code = item.opening or ""
    spec.direction = item.get_direction_display() if item.direction else ""
    spec.opening = item.get_opening_display() if item.opening else ""

    # Проверка обязательных кастомизаторов модели
    group_cust_ids = {gc.customizer_id for gc in state.customizers}
    group_cust_ids.update(
        getattr(gc, '_original_customizer_id')
        for gc in state.customizers
        if getattr(gc, '_original_customizer_id', None)
    )
    for req_cust in cache.required_customizers_by_product.get(product.id, []):
        if req_cust.id not in group_cust_ids:
            state.add_error(f"חסר קסטומייזר חובה '{req_cust.name}'")

    # Проверка обязательных параметров прикреплённых кастомизаторов
    for gc in state.customizers:
        c = gc.customizer
        for i in range(1, 6):
            if getattr(c, f'par{i}_required', False):
                val = getattr(gc, f'par{i}', None)
                if val is None or not str(val).strip():
                    p_label = getattr(c, f'par{i}_label') or f"פרמטר {i}"
                    state.add_error(f"בקסטומייזר '{c.name}' חסר ערך לשדה חובה '{p_label}'")


def _populate_double_door(state: ItemRuntimeState) -> None:
    found = state.find_customizers('DOUBLE_DOOR')
    if not found:
        return

    gc = found[0]
    c = gc.customizer
    state.spec.is_double_door = True
    state.is_double = True

    try:
        par1_str = gc.par1 if gc.par1 not in (None, '') else c.par1_value
        state.double_door_par1 = float(par1_str) if par1_str else 0.5
    except (ValueError, TypeError):
        state.double_door_par1 = 0.5

    try:
        par2_str = gc.par2 if gc.par2 not in (None, '') else c.par2_value
        state.double_door_par2 = float(par2_str) if par2_str else 0.0
    except (ValueError, TypeError):
        state.double_door_par2 = 0.0


def _populate_wood_edge(state: ItemRuntimeState) -> None:
    """Параметры деревянного канта — строго в сантиметрах (2.0 / 1.7 / 1.0 см)."""
    spec = state.spec
    if state.phase == 'phase1' or not spec.has_door:
        return

    found = state.find_customizers('WOOD_EDGE')
    if not found:
        return

    gc = found[0]
    c = gc.customizer

    state.wood_edge_wood_type = (gc.par1 if gc.par1 not in (None, '') else c.par1_value or '').strip()

    edge_type_raw = str(gc.par2 if gc.par2 not in (None, '') else c.par2_value or '').strip().lower()
    is_hidden = any(k in edge_type_raw for k in ('hidden', 'סמוי', 'פנימי'))

    thickness_raw = gc.par3 if gc.par3 not in (None, '') else c.par3_value
    custom_thickness_cm = None
    if thickness_raw:
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


def _populate_appearance(state: ItemRuntimeState) -> None:
    group = state.group
    order = state.order
    spec = state.spec

    if group.series:
        spec.series = group.series.name
    elif order and order.series:
        spec.series = order.series.name

    front = group.front or getattr(order, 'front', None)
    spec.front_name = front.name if front else ""
    spec.finish_type = getattr(front, 'finish_type', None) or "PAINT"

    if front:
        front_short = getattr(front, 'short_name', None) or getattr(front, 'code', None) or front.name
        spec.engraving_data = {
            'engraving_id': front.id,
            'icon_filename': str(front_short).strip(),
            'p1': None,
            'p2': None,
            'p3': None,
            'p4': None,
            'p5': None,
        }

    spec.color_panel_outside = group.effective_color_panel_outside or ""
    spec.color_panel_inside = group.effective_color_panel_inside or ""
    spec.color_frames = group.effective_color_frames or ""
    spec.panel_paint_option = group.panel_paint_option
    spec.frame_paint_option = group.frame_paint_option
    spec.basic_color_frames = str(group.basic_color_frames) if group.basic_color_frames else ""

    if order and order.handle:
        spec.handle_name = order.handle.name


def _format_report_customizers(state: ItemRuntimeState) -> None:
    spec = state.spec
    for gc in state.customizers:
        c = gc.customizer
        tag_str = (c.tag or "").upper()
        item_tags = {t.strip() for t in tag_str.replace(',', ' ').split() if t.strip()}

        formatted = _build_customizer_report(gc)
        if item_tags & {'FRAMES_REPORT', 'FRAME_MODIFICATION'}:
            spec.frames_report_customizers.append(formatted)
        if item_tags & {'DOORS_REPORT'}:
            spec.doors_report_customizers.append(formatted)
        if item_tags & LABEL_CUSTOMIZER_TAGS:
            spec.label_customizers.append(formatted)
        if item_tags & ENGRAVING_TAGS:
            spec.engraving_data = _extract_engraving_dict(gc)


def _build_customizer_report(gc: OrderItemsGroupCustomizer) -> SpecCustomizerReport:
    c = gc.customizer
    params = []
    for i in range(1, 6):
        label = getattr(c, f'par{i}_label')
        if not label:
            continue
        val_order = getattr(gc, f'par{i}')
        val_default = getattr(c, f'par{i}_value')
        is_custom = False
        val = val_order
        if val is None or val == '':
            val = val_default
        elif val_default and val != val_default:
            is_custom = True

        if val:
            display_val = gc.get_parameter_display_value(i)
            params.append(SpecCustomizerParam(label=label, value=str(display_val), is_custom=is_custom))

    return SpecCustomizerReport(id=c.id, code=c.code, name=c.name, tag=c.tag, params=params)


def _extract_engraving_dict(gc: OrderItemsGroupCustomizer) -> Dict[str, Any]:
    c = gc.customizer
    short_name = getattr(c, 'short_name', None) or c.code or c.name
    raw_vals = []
    for i in range(1, 6):
        val = getattr(gc, f'par{i}', None)
        if val in (None, ''):
            val = getattr(c, f'par{i}_value', None)
        raw_vals.append(val if val not in (None, '') else None)

    return {
        'engraving_id': c.id,
        'icon_filename': str(short_name).strip(),
        'p1': raw_vals[0],
        'p2': raw_vals[1],
        'p3': raw_vals[2],
        'p4': raw_vals[3],
        'p5': raw_vals[4],
    }
