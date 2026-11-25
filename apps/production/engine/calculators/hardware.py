import collections
import math
from typing import List, Optional, Tuple

from apps.catalog.models import Hardware
from .base import ItemRuntimeState
from ..cache import OrderReferenceCache

MODE_LABELS = {
    'WC': 'תפוס/פנוי',
    'CYLINDER': 'צילינדר',
    'KEY': 'מפתח אפס',
    'NONE': 'ללא',
}

MODE_KEYWORDS = (
    (('CYLINDER', 'צילינדר', 'צילימדר'), 'CYLINDER'),
    (('WC', 'תפוס', 'פנוי'), 'WC'),
    (('KEY', 'מפתח'), 'KEY'),
    (('NONE', 'WITHOUT_LOCK', 'ללא'), 'NONE'),
)

CANCEL_HANDLE_TAGS = {'NO_LOCK', 'WITHOUT_LOCK', 'NO_HANDLE', 'WITHOUT_HANDLE', 'INTEGRAL_HANDLE'}
LOCK_ALIGNMENT_ERROR = "לא ניתן לקבוע גובה מנעול אוטומטית עבור חלק מהדלתות — נא להגדיר ידנית"


def calculate_hardware(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    if not state.spec.has_door:
        state.spec.lock_height = None
        state.spec.hinge_heights = []
        state.spec.hinge_heights_on_frame = []
        return

    _select_lock(state, cache)
    _select_lock_option(state, cache)
    _select_handle(state, cache)
    _select_hinges(state, cache)
    _calculate_lock_position(state, cache)
    _calculate_hinge_positions(state, cache)
    _calculate_frame_positions(state)


def align_batch_lock_heights(batch_states: List[ItemRuntimeState]) -> None:
    """Выравнивает высоты замков в рамках одной записи LockStandardHeight внутри батча."""
    buckets = collections.defaultdict(list)

    for st in batch_states:
        spec = st.spec
        if not spec.has_door or not spec.lock_id or spec.lock_height is None or spec.lock_height <= 0:
            continue
        meta = st.lock_alignment_meta or {}
        if meta.get('is_manual'):
            continue
        rule = meta.get('rule')
        if not rule or rule.get('step', 0) <= 0 or rule.get('alignment_tolerance', 0) <= 0:
            continue
        buckets[rule['id']].append((st, rule))

    for bucket in buckets.values():
        if len(bucket) < 2:
            continue
        _process_alignment_bucket(bucket)


def _process_alignment_bucket(bucket: list) -> None:
    bucket.sort(key=lambda pair: (float(pair[0].spec.height or 0), pair[0].spec.item_id))
    rule = bucket[0][1]
    tolerance = float(rule['alignment_tolerance'])
    base_h = float(rule['base_door_height'])
    base_lock = float(rule['base_lock_height'])
    step = float(rule['step'])

    has_conflict = any(
        (float(bucket[i + 1][0].spec.height or 0) - float(bucket[i][0].spec.height or 0)) < tolerance
        and bucket[i + 1][0].spec.lock_height != bucket[i][0].spec.lock_height
        for i in range(len(bucket) - 1)
    )
    if not has_conflict:
        return

    clusters = [[bucket[0][0]]]
    for i in range(1, len(bucket)):
        prev_st = bucket[i - 1][0]
        curr_st = bucket[i][0]
        if (float(curr_st.spec.height or 0) - float(prev_st.spec.height or 0)) < tolerance:
            clusters[-1].append(curr_st)
        else:
            clusters.append([curr_st])

    for cluster in clusters:
        if len(cluster) < 2:
            continue
        target_lock_h = min(float(st.spec.lock_height) for st in cluster)
        k = round((target_lock_h - base_lock) / step)
        threshold_h = base_h + (k * step)

        for st in cluster:
            if float(st.spec.lock_height) == target_lock_h:
                continue
            if abs(float(st.spec.height or 0) - threshold_h) <= tolerance:
                st.spec.lock_height = target_lock_h
                st.spec.lock_height_on_frame = target_lock_h + float(st.spec.leaf_top_clearance or 0)

    for i in range(len(bucket) - 1):
        st1 = bucket[i][0]
        st2 = bucket[i + 1][0]
        if (
                (float(st2.spec.height or 0) - float(st1.spec.height or 0)) < tolerance
                and st1.spec.lock_height != st2.spec.lock_height
        ):
            st1.add_error(LOCK_ALIGNMENT_ERROR)
            st2.add_error(LOCK_ALIGNMENT_ERROR)


def _select_lock(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    spec = state.spec
    for gc in state.find_customizers('LOCK'):
        c = gc.customizer
        tag_val = (c.tag or '').upper()
        c_code = (c.code or '').upper()

        if any(k in tag_val or k in c_code for k in ('NO_LOCK', 'WITHOUT_LOCK', 'NONE')):
            spec.lock_id = None
            spec.lock_name = 'ללא מנעול'
            state.set_bom_hardware_slot('lock', 'Lock', None, cache)
            return

        if c.hardware:
            spec.lock_id = c.hardware.id
            spec.lock_name = (c.hardware.common_name or '').strip() or c.hardware.name
            state.set_bom_hardware_slot('lock', 'Lock', c.hardware, cache)

        for i in range(1, 6):
            label = (getattr(c, f'par{i}_label') or '').lower()
            val = getattr(gc, f'par{i}') or getattr(c, f'par{i}_value')
            if ('גובה' in label or 'height' in label) and val not in (None, ''):
                try:
                    num = float(val)
                    if num != 0:
                        state.override_lock_height = num
                        break
                except (ValueError, TypeError):
                    pass

    current_name = (spec.lock_name or '').strip()
    if (
            not spec.lock_id
            or current_name in ('', 'N/A', 'ללא מנעול', 'ללא', 'NO_LOCK', 'NONE')
            or 'ללא' in current_name
    ):
        spec.lock_id = None
        spec.lock_name = 'ללא מנעול'
        state.set_bom_hardware_slot('lock', 'Lock', None, cache)


def _select_lock_option(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    spec = state.spec
    if not spec.lock_id or spec.lock_name == 'ללא מנעול':
        spec.lock_option_type = MODE_LABELS['NONE']
        state.lock_mode = 'NONE'
        state.set_bom_hardware_slot('cylinder', 'צילינדר', None, cache)
        return

    curr_lock = cache.hardware_by_id.get(spec.lock_id)
    base_mode = (curr_lock.par1_value or '').strip().upper() if curr_lock else ''
    target_mode = base_mode if base_mode in ('WC', 'CYLINDER', 'KEY') else 'WC'
    cylinder_hw: Optional[Hardware] = None

    for gc in state.find_customizers({'LOCK', 'LOCK_OPTION', 'CYLINDER', 'KEY_LOCK', 'WC_LOCK'}):
        c = gc.customizer
        tags = {t.strip() for t in (c.tag or '').upper().replace(',', ' ').split() if t.strip()}

        if c.hardware and (getattr(c.hardware, 'role', '') == 'CYLINDER' or 'CYLINDER' in tags):
            cylinder_hw = cache.hardware_by_id.get(c.hardware_id, c.hardware)
            target_mode = 'CYLINDER'
            continue

        raw_val = _extract_option_param(gc, tags)
        if raw_val:
            resolved_cyl = _resolve_cylinder(raw_val, cache)
            if resolved_cyl:
                cylinder_hw = resolved_cyl
                target_mode = 'CYLINDER'
            else:
                target_mode = _parse_mode_text(raw_val, target_mode)
        elif not cylinder_hw:
            if 'CYLINDER' in tags:
                target_mode = 'CYLINDER'
            elif 'KEY_LOCK' in tags:
                target_mode = 'KEY'
            elif 'WC_LOCK' in tags:
                target_mode = 'WC'

    state.lock_mode = target_mode
    spec.lock_option_type = MODE_LABELS.get(target_mode, MODE_LABELS['WC'])

    if cylinder_hw and spec.is_double_door:
        cylinder_hw = _resolve_double_door_cylinder(cylinder_hw, cache)

    state.set_bom_hardware_slot('cylinder', 'צילינדר', cylinder_hw, cache)

    matched_lock = cache.find_hardware_variant(curr_lock, 'LOCK', target_mode, match_color=False)
    if matched_lock and matched_lock.id != spec.lock_id:
        spec.lock_id = matched_lock.id
        spec.lock_name = (matched_lock.common_name or '').strip() or matched_lock.name
        state.set_bom_hardware_slot('lock', 'Lock', matched_lock, cache)


def _select_handle(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    spec = state.spec
    has_handle = getattr(state.group, 'has_handle', True)
    if not spec.lock_id or state.find_customizers(CANCEL_HANDLE_TAGS):
        has_handle = False

    spec.has_handle = has_handle
    if not has_handle or not state.order.handle_id:
        spec.handle_name = 'ללא ידית'
        state.set_bom_hardware_slot('handle', 'ידיות', None, cache)
        return

    base_handle = cache.hardware_by_id.get(state.order.handle_id, state.order.handle)
    eff_handle = cache.find_hardware_variant(base_handle, 'HANDLE', state.lock_mode, match_color=True)
    spec.handle_name = eff_handle.name
    state.set_bom_hardware_slot('handle', 'ידיות', eff_handle, cache)


def _select_hinges(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    spec = state.spec
    for gc in state.find_customizers('HINGE'):
        c = gc.customizer
        tag_val = (c.tag or '').upper()
        c_code = (c.code or '').upper()

        if any(k in tag_val or k in c_code for k in ('NO_HINGES', 'WITHOUT_HINGES', 'NONE')):
            spec.hinge_name = 'ללא צירים'
            state.hinge_hardware_id = None
            state.set_bom_hardware_slot('hinge', 'צירים', None, cache)
            return

        if c.hardware:
            spec.hinge_name = (c.hardware.common_name or '').strip() or c.hardware.name
            state.hinge_hardware_id = c.hardware.id
            state.set_bom_hardware_slot('hinge', 'צירים', c.hardware, cache)

        custom_heights = []
        for i in range(1, 6):
            val = getattr(gc, f'par{i}') or getattr(c, f'par{i}_value')
            if val:
                try:
                    num = float(val)
                    if num > 0:
                        custom_heights.append(num)
                except (ValueError, TypeError):
                    pass
        if custom_heights:
            state.override_hinge_heights = custom_heights

    current_name = (spec.hinge_name or '').strip()
    if (
            not state.hinge_hardware_id
            and (
            not current_name
            or current_name in ('N/A', 'ללא צירים', 'ללא', 'NO_HINGE', 'NONE')
            or 'ללא' in current_name
    )
    ):
        spec.hinge_name = 'ללא צירים'
        spec.hinge_heights = []
        state.set_bom_hardware_slot('hinge', 'צירים', None, cache)


def _calculate_lock_position(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    spec = state.spec
    item = state.item

    if not spec.lock_id or spec.lock_name == 'ללא מנעול':
        spec.lock_height = None
        return

    effective_height = None
    is_manual = False
    rule_meta = None

    if item.custom_lock_height is not None and str(item.custom_lock_height).strip() != '':
        try:
            val = float(item.custom_lock_height)
            if val != 0:
                effective_height = val
                is_manual = True
        except (ValueError, TypeError):
            pass

    if effective_height is None and state.override_lock_height:
        effective_height = float(state.override_lock_height)
        is_manual = True

    if effective_height is None:
        effective_height, rule_meta = _resolve_std_lock_height(state, cache)

    if effective_height is None or effective_height == 0:
        state.add_error(f"לא נמצא גובה תקני למנעול '{spec.lock_name}' (דלת מס' {item.mark or item.id})")
        return

    spec.lock_height = effective_height
    state.lock_alignment_meta = {'is_manual': is_manual, 'rule': rule_meta}


def _resolve_std_lock_height(state: ItemRuntimeState, cache: OrderReferenceCache) -> Tuple[
    Optional[float], Optional[dict]]:
    if not state.product or not state.product.product_family_id or not state.spec.lock_id:
        return None, None

    std = cache.lock_rules.get((state.product.product_family_id, state.spec.lock_id))
    if not std:
        return None, None

    door_h = float(state.item.height or 0)
    base_h = float(std.base_door_height)
    base_lock = float(std.base_lock_height)
    step = float(std.step)
    tolerance = float(getattr(std, 'alignment_tolerance', 2.5) or 0)

    if base_lock < 0:
        return base_lock, None

    intervals = math.ceil((door_h - base_h) / step) if step > 0 else 0
    return float(base_lock + intervals * step), {
        'id': std.id,
        'base_door_height': base_h,
        'base_lock_height': base_lock,
        'step': step,
        'alignment_tolerance': tolerance,
    }


def _calculate_hinge_positions(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    spec = state.spec
    item = state.item

    if not spec.hinge_name or spec.hinge_name in ('N/A', 'ללא צירים', 'ללא'):
        spec.hinge_heights = []
        return

    effective_heights: Optional[List[float]] = None

    has_item_hinges = any(
        getattr(item, f'custom_hinge{i}', None) not in (None, '', 0, '0')
        for i in range(1, 6)
    )
    if has_item_hinges:
        effective_heights = []
        for i in range(1, 6):
            val = getattr(item, f'custom_hinge{i}', None)
            if val not in (None, '', 0, '0'):
                try:
                    num = float(val)
                    if num > 0:
                        effective_heights.append(num)
                except (ValueError, TypeError):
                    pass
    elif isinstance(state.override_hinge_heights, list):
        effective_heights = [float(h) for h in state.override_hinge_heights if float(h) > 0]
    elif state.hinge_hardware_id and state.product and state.product.product_family_id:
        door_h = float(item.height or 0)
        rules = cache.hinge_rules.get((state.product.product_family_id, state.hinge_hardware_id), [])
        std = next((r for r in rules if float(r.min_height) <= door_h <= float(r.max_height)), None)
        if std:
            effective_heights = []
            for i in range(1, 6):
                val = getattr(std, f'value{i}', None)
                if val is not None and float(val) > 0:
                    effective_heights.append(float(val))

    if effective_heights is None:
        state.add_error(f"לא נמצאו גבהים תקניים לצירים עבור '{spec.hinge_name}' (דלת מס' {item.mark or item.id})")
        return

    if len(effective_heights) == 1:
        state.add_error(f"נדרשים לפחות 2 צירים לדלת מס' {item.mark or item.id} (הוגדר ציר 1)")
        return

    spec.hinge_heights = effective_heights


def _calculate_frame_positions(state: ItemRuntimeState) -> None:
    spec = state.spec
    top_clearance = float(spec.leaf_top_clearance or 0)

    if spec.lock_height is not None:
        spec.lock_height_on_frame = (
            spec.lock_height if spec.lock_height < 0 else spec.lock_height + top_clearance
        )
    spec.hinge_heights_on_frame = [h + top_clearance for h in spec.hinge_heights]


def _parse_mode_text(raw_val: str, default: str) -> str:
    up_val = raw_val.upper()
    for keywords, mode in MODE_KEYWORDS:
        if any(k in up_val for k in keywords):
            return mode
    return default


def _extract_option_param(gc, item_tags: set) -> str:
    c = gc.customizer
    for i in range(1, 6):
        label = (getattr(c, f'par{i}_label') or '').lower()
        if 'גובה' in label or 'height' in label:
            continue
        is_option = any(k in label for k in ('נעילה', 'סוג', 'צילינדר', 'option', 'type', 'lock'))
        if is_option or 'LOCK' not in item_tags:
            val = getattr(gc, f'par{i}') or getattr(c, f'par{i}_value')
            if val is not None and str(val).strip():
                return str(val).strip()
    return ''


def _resolve_cylinder(raw_val: str, cache: OrderReferenceCache) -> Optional[Hardware]:
    val = raw_val.strip()
    if not val:
        return None
    if val.upper().startswith('SKU='):
        return cache.hardware_by_sku.get(val.split('=', 1)[1].strip())
    if val.isdigit():
        hw = cache.hardware_by_id.get(int(val))
        return hw if (hw and hw.role == 'CYLINDER') else None
    hw = cache.hardware_by_sku.get(val)
    if hw and hw.role == 'CYLINDER':
        return hw
    return cache.hardware_by_name_role.get((val, 'CYLINDER'))


def _resolve_double_door_cylinder(cylinder_hw: Hardware, cache: OrderReferenceCache) -> Hardware:
    replacement_sku = ''
    for i in (2, 1, 3):
        val = (getattr(cylinder_hw, f'par{i}_value') or '').strip()
        if val and val.upper() not in ('WC', 'CYLINDER', 'KEY'):
            replacement_sku = val.split('=', 1)[1].strip() if val.upper().startswith('SKU=') else val
            break
    if not replacement_sku:
        return cylinder_hw
    repl = cache.hardware_by_sku.get(replacement_sku)
    return repl if (repl and repl.role == 'CYLINDER') else cylinder_hw
