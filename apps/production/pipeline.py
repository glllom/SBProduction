from __future__ import annotations

import collections
import copy
import math
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from apps.catalog.models import Hardware, Material
from apps.engineering.models import (
    CustomizerProductionStation,
    HingeStandardHeight,
    LockStandardHeight,
    ProductEngineeringRule,
    ProductionRoute,
    PuzzleBlockPrototype,
    PuzzlePreset,
)
from apps.orders.models import OrderItem, OrderItemsGroup, OrderItemsGroupCustomizer
from .bom_calculator import BOMCalculator
from .evaluator import FormulaEvaluator
from .models import DoorLabel
from .schemas import (
    DoorPuzzleSpec,
    OrderHeaderSpec,
    OrderSpec,
    ProductionSpec,
    SpecBOMItem,
    SpecCustomizerParam,
    SpecCustomizerReport,
    SvgPuzzleBlock,
)


def format_spec_date(d) -> str:
    """Helper to format a DateField into dd/mm/yy string."""
    return d.strftime("%d/%m/%y") if d else ""


def _find_hardware_variant(
        base_hw: Optional[Hardware],
        role: str,
        target_mode: str,
        match_color: bool = False,
) -> Optional[Hardware]:
    """Подбирает вариант фурнитуры (WC / CYLINDER / KEY) по common_name и par1_value."""
    if not base_hw or not base_hw.common_name or target_mode not in ('WC', 'CYLINDER', 'KEY'):
        return base_hw

    curr_mode = (base_hw.par1_value or '').strip().upper()
    if curr_mode == target_mode:
        return base_hw

    qs = Hardware.objects.filter(
        active=True,
        role=role,
        common_name=base_hw.common_name,
        par1_value__iexact=target_mode,
    )
    if match_color and base_hw.color_id:
        return qs.filter(color_id=base_hw.color_id).first() or qs.order_by('id').first() or base_hw

    return qs.order_by('id').first() or base_hw


def _resolve_item_customizers(item: OrderItem, raw_customizers: List) -> List:
    """
    Для дверей с открыванием наружу (OUT) подменяет кастомизатор на outward_replacement
    на копии OrderItemsGroupCustomizer, не мутируя общий объект группы.
    """
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


class PipelineError(Exception):
    """Base class for pipeline errors that should be collected and shown to the user."""
    pass


class OrderStep(ABC):
    @abstractmethod
    def process(self, context: OrderSpecContext):
        pass


class SpecContext:
    def __init__(self, item: OrderItem, customizers=None, phase: str = 'phase2'):
        self.item = item
        self.phase = phase
        self.group = item.group
        self.order = self.group.order
        self.product = self.group.product
        self.spec = ProductionSpec(
            item_id=item.id,
            mark=item.mark or "",
        )
        self.data: Dict[str, Any] = {}
        self.label_drafts: List[Dict[str, Any]] = []
        self._bom = None

        if customizers is not None:
            self.customizers = _resolve_item_customizers(item, customizers)
        else:
            if self.group:
                raw_customizers = list(
                    self.group.customizers.select_related(
                        'customizer',
                        'customizer__puzzle_mapping__preset',
                        'customizer__outward_replacement',
                        'customizer__outward_replacement__puzzle_mapping__preset',
                    )
                    .prefetch_related(
                        'customizer__hardware__components',
                        'customizer__outward_replacement__hardware__components',
                    )
                    .order_by('customizer__tag', 'customizer__code')
                )
                self.customizers = _resolve_item_customizers(item, raw_customizers)
            else:
                self.customizers = []

    @property
    def bom(self):
        if self._bom is not None:
            return self._bom
        if self.product:
            return getattr(self.product, 'effective_bom', None) or getattr(self.product, 'bom', None)
        return None

    @bom.setter
    def bom(self, value):
        self._bom = value

    def get_engineering_rules(self):
        rules = self.data.get('engineering_rules')
        if rules is None:
            rules = ProductEngineeringRule.resolve_for_product(self.product)
            self.data['engineering_rules'] = rules
        return rules

    def add_error(self, message: str):
        self.spec.errors.append(message)

    def find_customizers(self, tags) -> List:
        """Возвращает все кастомизаторы группы, у которых есть хотя бы один из указанных тегов."""
        if isinstance(tags, str):
            tags_set = {tags.upper()}
        else:
            tags_set = {t.upper() for t in tags}

        found = []
        for gc in self.customizers:
            tag_str = (gc.customizer.tag or "").upper()
            item_tags = {t.strip() for t in tag_str.replace(',', ' ').split() if t.strip()}
            if item_tags & tags_set:
                found.append(gc)
        return found

    def set_bom_hardware_slot(self, slot_tag: str, section: str, main_hw: Optional[Hardware]):
        """
        Идемпотентно перезаписывает слот фурнитуры в spec.bom_items (lock / cylinder / hinge / handle).
        Гарантирует отсутствие дублей.
        """
        target_tag = slot_tag.lower()
        self.spec.bom_items = [
            b for b in self.spec.bom_items
            if str(b.tag or '').lower() != target_tag
        ]
        if not main_hw:
            return

        hw_list = [main_hw] + list(main_hw.components.all())
        for hw in hw_list:
            self.spec.bom_items.append(
                SpecBOMItem(
                    type='hardware',
                    section=section,
                    item_name=hw.name,
                    common_name=hw.common_name or None,
                    quantity=1,
                    tag=target_tag,
                    item_id=hw.id,
                )
            )


class SpecStep(ABC):
    priority: int = 0
    important_for_phase1: bool = True

    @abstractmethod
    def process(self, context: SpecContext):
        pass


class BaseItemStep(SpecStep):
    priority = 1

    def process(self, context: SpecContext):
        item = context.item
        spec = context.spec
        product = context.product

        spec.place = item.place or ""
        spec.comment = item.comment or ""
        spec.addition_cut = float(item.bottom_correction) if item.bottom_correction else None

        has_frame = product.has_frame if product else True
        has_door = product.has_door if product else True

        h = float(item.height or 0)
        w = float(item.width or 0)
        raw_wb = getattr(item, 'width_bottom', None)
        w_bottom = float(raw_wb) if raw_wb not in (None, '') else None
        if w_bottom is not None and w_bottom <= 0:
            w_bottom = None
        wall = float(item.wall or 0)

        if has_door or has_frame:
            if h <= 0:
                context.add_error("לא הוזן גובה תקין")
            if w <= 0:
                context.add_error("לא הוזן רוחב תקין")

        spec.height = h
        spec.width = w
        spec.width_bottom = w_bottom
        spec.wall = wall

        if has_frame and wall <= 0:
            context.add_error("לא הוזן עובי קיר למשקוף")

        if has_door:
            if not item.opening:
                context.add_error("לא נבחר כיוון פתיחה (פנימה/החוצה)")
            if not item.direction:
                context.add_error("לא נבחרה יד פתיחה (L/R)")

            if product and product.product_family and item.opening:
                allowed = getattr(product.product_family, 'allowed_direction', 'BOTH')
                op = str(item.opening).strip().upper()
                is_in = op in ('IN', 'INWARD', 'פנימה')
                is_out = op in ('OUT', 'OUTWARD', 'החוצה')

                if allowed == 'IN_ONLY' and not is_in:
                    context.add_error("הדגם תומך בפתיחה פנימה בלבד (IN)")
                elif allowed == 'OUT_ONLY' and not is_out:
                    context.add_error("הדגם תומך בפתיחה החוצה בלבד (OUT)")

        spec.direction_code = item.direction or ""
        spec.opening_code = item.opening or ""
        spec.direction = item.get_direction_display() if item.direction else ""
        spec.opening = item.get_opening_display() if item.opening else ""


class ProductDataStep(SpecStep):
    priority = 200

    def process(self, context: SpecContext):
        product = context.product
        spec = context.spec
        if not product:
            context.add_error("דגם מוצר לא נבחר")
            return

        rules = context.get_engineering_rules()

        spec.product_name = product.name
        spec.product_code = product.code
        spec.has_door = product.has_door
        spec.has_frame = product.has_frame
        spec.cut_coefficients = rules.cut_coefficients.model_dump(exclude_none=True)

        if product.product_family:
            spec.product_family = product.product_family.name
            if not spec.series and product.series:
                spec.series = product.series.name

        group_customizer_ids = {gc.customizer_id for gc in context.customizers}
        group_customizer_ids.update(
            getattr(gc, '_original_customizer_id')
            for gc in context.customizers
            if getattr(gc, '_original_customizer_id', None)
        )
        for req_cust in product.get_required_customizers():
            if req_cust.id not in group_customizer_ids:
                context.add_error(f"חסר קסטומייזר חובה '{req_cust.name}'")

        for gc in context.customizers:
            c = gc.customizer
            for i in range(1, 6):
                if getattr(c, f'par{i}_required', False):
                    val = getattr(gc, f'par{i}', None)
                    if val is None or not str(val).strip():
                        p_label = getattr(c, f'par{i}_label') or f"פרמטר {i}"
                        context.add_error(f"בקסטומייזר '{c.name}' חסר ערך לשדה חובה '{p_label}'")


class LockSelectionStep(SpecStep):
    priority = 450

    def process(self, context: SpecContext):
        spec = context.spec
        if not getattr(spec, 'has_door', True):
            return

        lock_customizers = context.find_customizers('LOCK')

        for gc in lock_customizers:
            c = gc.customizer
            tag_val = (c.tag or '').upper()
            c_code = (c.code or '').upper()

            if any(k in tag_val or k in c_code for k in ('NO_LOCK', 'WITHOUT_LOCK', 'NONE')):
                spec.lock_id = None
                spec.lock_name = 'ללא מנעול'
                context.set_bom_hardware_slot('lock', 'Lock', None)
                return

            if c.hardware:
                spec.lock_id = c.hardware.id
                spec.lock_name = (c.hardware.common_name or '').strip() or c.hardware.name
                context.set_bom_hardware_slot('lock', 'Lock', c.hardware)

            custom_h = self._extract_custom_height(gc)
            if custom_h is not None and custom_h != 0:
                context.data['override_lock_height'] = custom_h

        current_lock_name = (spec.lock_name or '').strip()
        if (
                not spec.lock_id
                or current_lock_name in ('', 'N/A', 'ללא מנעול', 'ללא', 'NO_LOCK', 'NONE')
                or 'ללא' in current_lock_name
        ):
            spec.lock_id = None
            spec.lock_name = 'ללא מנעול'
            context.set_bom_hardware_slot('lock', 'Lock', None)

    @staticmethod
    def _extract_custom_height(group_customizer) -> Optional[float]:
        c = group_customizer.customizer
        for i in range(1, 6):
            label = (getattr(c, f'par{i}_label') or '').lower()
            val = getattr(group_customizer, f'par{i}') or getattr(c, f'par{i}_value')
            if ('גובה' in label or 'height' in label) and val not in (None, ''):
                try:
                    num = float(val)
                    if num != 0:
                        return num
                except (ValueError, TypeError):
                    pass
        return None


class LockOptionSelectionStep(SpecStep):
    priority = 460

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

    def process(self, context: SpecContext):
        spec = context.spec
        if not getattr(spec, 'has_door', True):
            return

        if not spec.lock_id or spec.lock_name == 'ללא מנעול':
            spec.lock_option_type = self.MODE_LABELS['NONE']
            context.data['lock_mode'] = 'NONE'
            context.set_bom_hardware_slot('cylinder', 'צילינדר', None)
            return

        curr_lock = Hardware.objects.filter(pk=spec.lock_id).first()
        base_mode = (curr_lock.par1_value or '').strip().upper() if curr_lock else ''
        target_mode = base_mode if base_mode in ('WC', 'CYLINDER', 'KEY') else 'WC'
        cylinder_hw: Optional[Hardware] = None

        for gc in context.find_customizers({'LOCK', 'LOCK_OPTION', 'CYLINDER', 'KEY_LOCK', 'WC_LOCK'}):
            c = gc.customizer
            tags = {t.strip() for t in (c.tag or '').upper().replace(',', ' ').split() if t.strip()}

            if c.hardware and (getattr(c.hardware, 'role', '') == 'CYLINDER' or 'CYLINDER' in tags):
                cylinder_hw = c.hardware
                target_mode = 'CYLINDER'
                continue

            raw_val = self._extract_option_param(gc, tags)
            if raw_val:
                resolved_cyl = self._resolve_cylinder_hardware(raw_val)
                if resolved_cyl:
                    cylinder_hw = resolved_cyl
                    target_mode = 'CYLINDER'
                else:
                    target_mode = self._parse_mode_text(raw_val, target_mode)
            elif not cylinder_hw:
                if 'CYLINDER' in tags:
                    target_mode = 'CYLINDER'
                elif 'KEY_LOCK' in tags:
                    target_mode = 'KEY'
                elif 'WC_LOCK' in tags:
                    target_mode = 'WC'

        context.data['lock_mode'] = target_mode
        spec.lock_option_type = self.MODE_LABELS.get(target_mode, self.MODE_LABELS['WC'])
        if cylinder_hw and getattr(spec, 'is_double_door', False):
            cylinder_hw = self._resolve_double_door_cylinder(cylinder_hw)

        context.set_bom_hardware_slot('cylinder', 'צילינדר', cylinder_hw)

        matched_lock = _find_hardware_variant(curr_lock, 'LOCK', target_mode, match_color=False)
        if matched_lock and matched_lock.id != spec.lock_id:
            spec.lock_id = matched_lock.id
            spec.lock_name = (matched_lock.common_name or '').strip() or matched_lock.name
            context.set_bom_hardware_slot('lock', 'Lock', matched_lock)

    @classmethod
    def _parse_mode_text(cls, raw_val: str, default: str) -> str:
        up_val = raw_val.upper()
        for keywords, mode in cls.MODE_KEYWORDS:
            if any(k in up_val for k in keywords):
                return mode
        return default

    @staticmethod
    def _extract_option_param(group_customizer, item_tags: set[str]) -> str:
        c = group_customizer.customizer
        for i in range(1, 6):
            label = (getattr(c, f'par{i}_label') or '').lower()
            if 'גובה' in label or 'height' in label:
                continue
            is_option_label = any(k in label for k in ('נעילה', 'סוג', 'צילינדר', 'option', 'type', 'lock'))
            if is_option_label or 'LOCK' not in item_tags:
                val = getattr(group_customizer, f'par{i}') or getattr(c, f'par{i}_value')
                if val is not None and str(val).strip():
                    return str(val).strip()
        return ''

    @staticmethod
    def _resolve_cylinder_hardware(raw_val: str) -> Optional[Hardware]:
        val = raw_val.strip()
        if not val:
            return None
        if val.upper().startswith('SKU='):
            return Hardware.objects.filter(sku=val.split('=', 1)[1].strip(), active=True).first()
        if val.isdigit():
            return Hardware.objects.filter(pk=int(val), role='CYLINDER', active=True).first()
        return (
                Hardware.objects.filter(sku=val, role='CYLINDER', active=True).first()
                or Hardware.objects.filter(name=val, role='CYLINDER', active=True).first()
        )

    @staticmethod
    def _resolve_double_door_cylinder(cylinder_hw: Hardware) -> Hardware:
        replacement_sku = ''
        for i in (2, 1, 3):
            val = (getattr(cylinder_hw, f'par{i}_value') or '').strip()
            if val and val.upper() not in ('WC', 'CYLINDER', 'KEY'):
                replacement_sku = val.split('=', 1)[1].strip() if val.upper().startswith('SKU=') else val
                break

        if not replacement_sku:
            return cylinder_hw

        replacement_hw = Hardware.objects.filter(
            sku=replacement_sku,
            role='CYLINDER',
            active=True,
        ).first()

        return replacement_hw or cylinder_hw


class HandleSelectionStep(SpecStep):
    priority = 470

    CANCEL_TAGS = {'NO_LOCK', 'WITHOUT_LOCK', 'NO_HANDLE', 'WITHOUT_HANDLE', 'INTEGRAL_HANDLE'}

    def process(self, context: SpecContext):
        spec = context.spec
        if not getattr(spec, 'has_door', True):
            return

        has_handle = getattr(context.item.group, 'has_handle', True)

        if not spec.lock_id or context.find_customizers(self.CANCEL_TAGS):
            has_handle = False

        spec.has_handle = has_handle

        if not has_handle:
            spec.handle_name = 'ללא ידית'
            context.set_bom_hardware_slot('handle', 'ידיות', None)
            return

        base_handle = getattr(context.order, 'handle', None)
        if not base_handle:
            spec.handle_name = 'ללא ידית'
            context.set_bom_hardware_slot('handle', 'ידיות', None)
            return

        target_mode = context.data.get('lock_mode', 'WC')
        eff_handle = _find_hardware_variant(base_handle, 'HANDLE', target_mode, match_color=True)

        spec.handle_name = eff_handle.name
        context.set_bom_hardware_slot('handle', 'ידיות', eff_handle)


class HingeSelectionStep(SpecStep):
    priority = 470

    def process(self, context: SpecContext):
        spec = context.spec

        if not getattr(spec, 'has_door', True):
            return

        hinge_customizers = context.find_customizers('HINGE')

        for gc in hinge_customizers:
            c = gc.customizer
            tag_val = (c.tag or '').upper()
            c_code = (c.code or '').upper()

            if any(k in tag_val or k in c_code for k in ('NO_HINGES', 'WITHOUT_HINGES', 'NONE')):
                spec.hinge_name = 'ללא צירים'
                context.data['hinge_hardware_id'] = None
                context.set_bom_hardware_slot('hinge', 'צירים', None)
                return

            if c.hardware:
                spec.hinge_name = (c.hardware.common_name or '').strip() or c.hardware.name
                context.data['hinge_hardware_id'] = c.hardware.id
                context.set_bom_hardware_slot('hinge', 'צירים', c.hardware)

            custom_heights = self._extract_custom_heights(gc)
            if custom_heights:
                context.data['override_hinge_heights'] = custom_heights

        current_hinge_name = (spec.hinge_name or '').strip()
        if (
                not context.data.get('hinge_hardware_id')
                and (
                not current_hinge_name
                or current_hinge_name in ('N/A', 'ללא צירים', 'ללא', 'NO_HINGE', 'NONE')
                or 'ללא' in current_hinge_name
        )
        ):
            spec.hinge_name = 'ללא צירים'
            spec.hinge_heights = []
            context.set_bom_hardware_slot('hinge', 'צירים', None)

    @staticmethod
    def _extract_custom_heights(group_customizer) -> List[float]:
        c = group_customizer.customizer
        res = []
        for i in range(1, 6):
            val = getattr(group_customizer, f'par{i}') or getattr(c, f'par{i}_value')
            if val:
                try:
                    num = float(val)
                    if num > 0:
                        res.append(num)
                except (ValueError, TypeError):
                    pass
        return res


class LockPositionStep(SpecStep):
    priority = 500

    def process(self, context: SpecContext):
        spec = context.spec
        item = context.item

        if not getattr(spec, 'has_door', True) or not spec.lock_id:
            spec.lock_height = None
            return

        if spec.lock_name == 'ללא מנעול' or spec.lock_id is None:
            spec.lock_height = 0.0
            return

        effective_height = None
        is_manual_override = False
        std_rule_meta = None

        if item.custom_lock_height is not None and str(item.custom_lock_height).strip() != '':
            try:
                val = float(item.custom_lock_height)
                if val != 0:
                    effective_height = val
                    is_manual_override = True
            except (ValueError, TypeError):
                pass

        if effective_height is None:
            override_h = context.data.get('override_lock_height')
            if override_h is not None and str(override_h).strip() != '':
                try:
                    val = float(override_h)
                    if val != 0:
                        effective_height = val
                        is_manual_override = True
                except (ValueError, TypeError):
                    pass

        if effective_height is None:
            effective_height, std_rule_meta = self._get_effective_lock_height(item, spec.lock_id)

        if effective_height is None or effective_height == 0:
            raise PipelineError(
                f"לא נמצא גובה תקני למנעול '{spec.lock_name}' (דלת מס' {item.mark or item.id})"
            )

        spec.lock_height = effective_height
        spec.context['lock_alignment_meta'] = {
            'is_manual': is_manual_override,
            'rule': std_rule_meta,
        }

    @staticmethod
    def _get_effective_lock_height(item: OrderItem, lock_id: int) -> tuple[Optional[float], Optional[dict]]:
        product = getattr(item.group, 'product', None)
        if not product or not product.product_family or not lock_id:
            return None, None

        std = LockStandardHeight.objects.filter(
            product_families=product.product_family,
            locks__id=lock_id,
        ).first()

        if not std:
            return None, None

        door_h = float(item.height or 0)
        base_h = float(std.base_door_height)
        base_lock = float(std.base_lock_height)
        step = float(std.step)
        tolerance = float(getattr(std, 'alignment_tolerance', 2.5) or 0)

        if base_lock < 0:
            return float(base_lock), None

        diff = door_h - base_h
        intervals = math.ceil(diff / step) if step > 0 else 0
        calculated_lock_h = float(base_lock + (intervals * step))

        rule_meta = {
            'id': std.id,
            'base_door_height': base_h,
            'base_lock_height': base_lock,
            'step': step,
            'alignment_tolerance': tolerance,
        }
        return calculated_lock_h, rule_meta


class HingePositionStep(SpecStep):
    priority = 510

    def process(self, context: SpecContext):
        spec = context.spec
        item = context.item

        if (
                not getattr(spec, 'has_door', True)
                or not spec.hinge_name
                or spec.hinge_name in ('N/A', 'ללא צירים', 'ללא')
        ):
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
        else:
            override_heights = context.data.get('override_hinge_heights')
            if isinstance(override_heights, list):
                effective_heights = [float(h) for h in override_heights if float(h) > 0]
            else:
                hinge_id = context.data.get('hinge_hardware_id')
                if not hinge_id:
                    hinge_bi = next((bi for bi in spec.bom_items if str(bi.tag).lower() == 'hinge'), None)
                    if hinge_bi:
                        hinge_id = hinge_bi.item_id

                if hinge_id:
                    effective_heights = self._get_std_hinge_heights(item, hinge_id)

        if effective_heights is None:
            raise PipelineError(
                f"לא נמצאו גבהים תקניים לצירים עבור '{spec.hinge_name}' (דלת מס' {item.mark or item.id})"
            )

        if len(effective_heights) == 1:
            raise PipelineError(
                f"נדרשים לפחות 2 צירים לדלת מס' {item.mark or item.id} (הוגדר ציר 1)"
            )

        spec.hinge_heights = effective_heights

    @staticmethod
    def _get_std_hinge_heights(item: OrderItem, hinge_id: int) -> Optional[List[float]]:
        product = getattr(item.group, 'product', None)
        if not product or not product.product_family or not hinge_id:
            return None

        door_h = float(item.height or 0)
        std = HingeStandardHeight.objects.filter(
            product_families__id=product.product_family.id,
            hinges__id=hinge_id,
            min_height__lte=door_h,
            max_height__gte=door_h,
        ).first()

        if not std:
            return None

        res = []
        for i in range(1, 6):
            val = getattr(std, f'value{i}', None)
            if val is not None:
                try:
                    num = float(val)
                    if num > 0:
                        res.append(num)
                except (ValueError, TypeError):
                    pass
        return res


class MeasurerDataStep(SpecStep):
    priority = 600

    def process(self, context: SpecContext):
        spec = context.spec
        top_clearance = float(spec.leaf_top_clearance or 0)

        if spec.lock_height is not None:
            if spec.lock_height < 0:
                spec.lock_height_on_frame = spec.lock_height
            else:
                spec.lock_height_on_frame = spec.lock_height + top_clearance

        if spec.hinge_heights:
            spec.hinge_heights_on_frame = [h + top_clearance for h in spec.hinge_heights]
        else:
            spec.hinge_heights_on_frame = []


class DoubleDoorStep(SpecStep):
    priority = 10

    def process(self, context: SpecContext):
        spec = context.spec
        found = context.find_customizers('DOUBLE_DOOR')
        if found:
            gc = found[0]
            c = gc.customizer
            spec.is_double_door = True
            context.data['is_double'] = True

            try:
                par1_str = gc.par1 if gc.par1 not in (None, '') else c.par1_value
                par1 = float(par1_str) if par1_str else 0.5
            except (ValueError, TypeError):
                par1 = 0.5

            try:
                par2_str = gc.par2 if gc.par2 not in (None, '') else c.par2_value
                par2 = float(par2_str) if par2_str else 0
            except (ValueError, TypeError):
                par2 = 0

            context.data['double_door_par1'] = par1
            context.data['double_door_par2'] = par2


class WoodEdgeStep(SpecStep):
    priority = 15
    important_for_phase1 = False

    def process(self, context: SpecContext):
        spec = context.spec

        if not getattr(spec, 'has_door', True):
            return

        found = context.find_customizers('WOOD_EDGE')
        if not found:
            return

        gc = found[0]
        c = gc.customizer

        wood_type = (gc.par1 if gc.par1 not in (None, '') else c.par1_value or '').strip()

        edge_type_raw = str(gc.par2 if gc.par2 not in (None, '') else c.par2_value or '').strip().lower()
        is_hidden = any(k in edge_type_raw for k in ('hidden', 'סמוי', 'פנימי'))

        thickness_raw = gc.par3 if gc.par3 not in (None, '') else c.par3_value
        custom_thickness = None
        if thickness_raw:
            try:
                val = float(thickness_raw)
                if val > 0:
                    custom_thickness = val
            except (ValueError, TypeError):
                pass

        if custom_thickness is not None:
            thickness_mm = custom_thickness * 10
        else:
            if not is_hidden:
                thickness_mm = 20.0
            else:
                is_double = getattr(spec, 'is_double_door', False) or context.data.get('is_double', False)
                thickness_mm = 17.0 if is_double else 10.0

        sides_raw = gc.par4 if gc.par4 not in (None, '') else c.par4_value
        try:
            sides_count = int(sides_raw) if sides_raw else 4
        except (ValueError, TypeError):
            sides_count = 4

        if sides_count not in (2, 3, 4):
            sides_count = 4

        spec.has_wood_edge = True
        spec.is_hidden_wood_edge = is_hidden
        spec.wood_edge_thickness = thickness_mm
        spec.wood_edge_sides = sides_count
        spec.wood_edge_type = 'hidden' if is_hidden else 'outer'

        edge_data = {
            'wood_type': wood_type,
            'is_hidden': is_hidden,
            'edge_type': spec.wood_edge_type,
            'type_name': 'סמוי' if is_hidden else 'חיצוני',
            'thickness': thickness_mm,
            'sides': sides_count,
        }

        context.data['wood_edge'] = edge_data
        spec.context['wood_edge'] = edge_data

        edge_label = f"קנט עץ {wood_type} ({edge_data['type_name']}, {thickness_mm} מ\"מ, {sides_count} צדדים)".strip()
        spec.bom_items.append(
            SpecBOMItem(
                type='material',
                section='קנט עץ',
                item_name=edge_label,
                quantity=sides_count,
                tag='wood_edge',
                item_id=c.hardware_id if c.hardware else None,
            )
        )


class PanelDimensionStep(SpecStep):
    priority = 20

    def process(self, context: SpecContext):
        item = context.item
        product = context.product
        spec = context.spec

        if not product or not product.product_family:
            return

        if not getattr(product, 'has_door', True):
            spec.panel_dimensions = []
            spec.press_dimensions = []
            return

        rules = context.get_engineering_rules()
        h = float(item.height or 0)
        w = float(item.width or 0)
        bottom_correction = float(getattr(item, 'bottom_correction', 0) or 0)

        # 1. Внутренний свет проема коробки (все допуски положительные, в см)
        spec.inner_height = h - rules.frame_inner_height_reduction
        spec.inner_width = w - rules.frame_inner_width_reduction
        spec.frame_inner_height_reduction = rules.frame_inner_height_reduction
        spec.frame_inner_width_reduction = rules.frame_inner_width_reduction
        spec.leaf_top_clearance = rules.leaf_top_clearance

        if context.phase == 'phase1':
            spec.panel_dimensions = []
            spec.press_dimensions = []
            return

        # 2. Чистовые размеры полотна (верх + опционально низ для трапеции)
        h_panel = spec.inner_height - rules.leaf_top_clearance - rules.leaf_bottom_clearance - bottom_correction

        has_trapezoid = bool(spec.width_bottom and spec.width_bottom > 0)
        inner_w_bottom = (
            float(spec.width_bottom) - rules.frame_inner_width_reduction
            if has_trapezoid else None
        )

        if not context.data.get('is_double'):
            w_panel = spec.inner_width - rules.leaf_side_clearance
            panel_dict: Dict[str, float] = {
                'width': round(w_panel, 2),
                'height': round(h_panel, 2),
            }
            if inner_w_bottom is not None:
                panel_dict['width_bottom'] = round(inner_w_bottom - rules.leaf_side_clearance, 2)
            panels = [panel_dict]
        else:
            w_net = spec.inner_width - 2 * rules.leaf_side_clearance
            par1 = context.data.get('double_door_par1', 0.5)
            par2 = context.data.get('double_door_par2', 0)

            if par2 > 0:
                w1 = par2 + 1
            else:
                if not (0 < par1 < 1):
                    par1 = 0.5
                w1 = w_net * par1 + 1

            w2 = w_net - w1 + rules.double_leaf_overlap
            p1: Dict[str, float] = {'width': round(w1, 2), 'height': round(h_panel, 2)}
            p2: Dict[str, float] = {'width': round(w2, 2), 'height': round(h_panel, 2)}

            if inner_w_bottom is not None:
                w_net_bottom = inner_w_bottom - 2 * rules.leaf_side_clearance
                w1_b = (par2 + 1) if par2 > 0 else (w_net_bottom * par1 + 1)
                w2_b = w_net_bottom - w1_b + rules.double_leaf_overlap
                p1['width_bottom'] = round(w1_b, 2)
                p2['width_bottom'] = round(w2_b, 2)

            panels = [p1, p2]

        spec.panel_dimensions = panels

        # 3. Габариты заготовки/каркаса под пресс (в см, всегда по большей ширине + с вычетом канта)
        wood_edge = context.data.get('wood_edge')
        allowance = rules.press_allowance
        press_dims = []

        for p in panels:
            pw = max(float(p['width'] or 0), float(p.get('width_bottom') or 0))
            ph = float(p['height'] or 0)

            if not wood_edge:
                press_w = pw + allowance
                press_h = ph + allowance
            else:
                t_cm = float(wood_edge['thickness']) / 10.0
                sides = int(wood_edge['sides'])

                press_w = pw - (t_cm * 2) + allowance
                height_sides_count = (1 if sides > 2 else 0) + (1 if sides > 3 else 0)
                press_h = ph - (t_cm * height_sides_count) + allowance

            press_dims.append({
                'width': round(press_w, 2),
                'height': round(press_h, 2),
            })

        spec.press_dimensions = press_dims

        # 4. Обогащение заготовок наклеек геометрией полотен
        if context.label_drafts:
            from .label_services import DoorLabelService

            is_double = len(panels) > 1
            passive_w = panels[1]['width'] if is_double else None
            is_paint = bool(
                context.group and context.group.panel_paint_option != OrderItemsGroup.PaintOption.NO_PAINT
            )
            leaf_thickness_mm = (
                rules.thickness * 10.0
                if 0 < rules.thickness < 15
                else (rules.thickness or 40.0)
            )

            DoorLabelService.enrich_geometry(
                drafts=context.label_drafts,
                item_spec=spec,
                leaf_width=panels[0]['width'],
                leaf_height=panels[0]['height'],
                leaf_thickness=leaf_thickness_mm,
                direction=spec.direction or item.get_direction_display() or '',
                opening=spec.opening or item.get_opening_display() or '',
                edge_type=getattr(spec, 'wood_edge_type', '') or '',
                is_paint=is_paint,
                passive_width=passive_w,
            )


class CutSheetsStep(SpecStep):
    priority = 210
    important_for_phase1 = False

    def process(self, context: SpecContext):
        spec = context.spec
        coeffs = spec.cut_coefficients
        panels = spec.panel_dimensions

        if not coeffs or not panels:
            return

        cut_sheets = []
        rail_delta = coeffs.get('rail_delta')
        try:
            rail_delta = float(str(rail_delta)) if rail_delta is not None else 0.0
        except (ValueError, TypeError):
            rail_delta = 0.0

        for i, panel in enumerate(panels):
            panel_w = max(float(panel.get('width') or 0), float(panel.get('width_bottom') or 0))
            panel_h = float(panel.get('height') or 0)

            sheet_data = {
                'panel_index': i + 1,
                'alucobond': self._calc(panel_w, panel_h, coeffs.get('alucobond')),
                'exterior_panel': self._calc(panel_w, panel_h, coeffs.get('exterior_panel')),
                'interior_panel': self._calc(panel_w, panel_h, coeffs.get('interior_panel')),
                'rails': {
                    'width': round(panel_w + rail_delta, 2),
                    'count': int(panel_h // 50),
                },
            }
            cut_sheets.append(sheet_data)

        spec.cut_sheets = cut_sheets

    @staticmethod
    def _calc(w: float | int, h: float | int, delta_dict: Optional[dict]):
        if not isinstance(delta_dict, dict):
            return None
        try:
            dw = float(delta_dict.get('width_delta') or 0)
            dh = float(delta_dict.get('height_delta') or 0)
            return {
                'width': round(w + dw, 2),
                'height': round(h + dh, 2),
            }
        except (ValueError, TypeError):
            return None


class AppearanceStep(SpecStep):
    priority = 300

    def process(self, context: SpecContext):
        group = context.group
        order = context.order
        spec = context.spec

        if group.series:
            spec.series = group.series.name
        elif order and order.series:
            spec.series = order.series.name

        front = group.front or getattr(order, 'front', None)

        spec.front_name = front.name if front else ""
        spec.finish_type = getattr(front, 'finish_type', None) or "PAINT"

        if front:
            front_short = (
                    getattr(front, 'short_name', None)
                    or getattr(front, 'code', None)
                    or front.name
            )
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


class SingleCustomizerStep(SpecStep):
    priority = 700

    LABEL_CUSTOMIZER_TAGS = {'WINDOW', 'CUSTOM_ROUTING', 'DOOR_CNC', 'HARDWARE_EXTRA'}
    ENGRAVING_TAGS = {'ENGRAVING', 'FRONT_ENGRAVING', 'FACE_MILLING'}

    def __init__(self, group_customizer):
        self.group_customizer = group_customizer

    def process(self, context: SpecContext):
        gc = self.group_customizer
        c = gc.customizer
        spec = context.spec
        tag_str = (c.tag or "").upper()
        item_tags = {t.strip() for t in tag_str.replace(',', ' ').split() if t.strip()}

        if c.hardware and getattr(c.hardware, 'role', 'OTHER') == 'OTHER':
            hardware_list = [c.hardware] + list(c.hardware.components.all())
            for hw in hardware_list:
                spec.bom_items.append(
                    SpecBOMItem(
                        type='hardware',
                        section=tag_str or 'Customizer',
                        item_name=hw.name,
                        common_name=hw.common_name or None,
                        quantity=1,
                        tag=tag_str,
                        item_id=hw.id,
                    )
                )

        formatted = self._format_customizer(gc)

        if item_tags & {'FRAMES_REPORT', 'FRAME_MODIFICATION'}:
            spec.frames_report_customizers.append(formatted)

        if item_tags & {'DOORS_REPORT'}:
            spec.doors_report_customizers.append(formatted)

        if item_tags & self.LABEL_CUSTOMIZER_TAGS:
            spec.label_customizers.append(formatted)

        if item_tags & self.ENGRAVING_TAGS:
            spec.engraving_data = self._extract_engraving_dict(gc)

    @staticmethod
    def _format_customizer(group_customizer) -> SpecCustomizerReport:
        c = group_customizer.customizer
        params = []
        for i in range(1, 6):
            label = getattr(c, f'par{i}_label')
            if label:
                val_order = getattr(group_customizer, f'par{i}')
                val_default = getattr(c, f'par{i}_value')
                is_custom = False
                val = val_order
                if val is None or val == '':
                    val = val_default
                elif val_default and val != val_default:
                    is_custom = True

                if val:
                    display_val = group_customizer.get_parameter_display_value(i)
                    params.append(SpecCustomizerParam(
                        label=label,
                        value=str(display_val),
                        is_custom=is_custom,
                    ))
        return SpecCustomizerReport(
            id=c.id,
            code=c.code,
            name=c.name,
            tag=c.tag,
            params=params,
        )

    @staticmethod
    def _extract_engraving_dict(group_customizer) -> Dict[str, Any]:
        c = group_customizer.customizer
        short_name = getattr(c, 'short_name', None) or c.code or c.name
        raw_vals = []
        for i in range(1, 6):
            val = getattr(group_customizer, f'par{i}', None)
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


class CustomizersFormattingStep(SpecStep):
    """
    Priority 700: Формирует данные кастомизаторов для отчетов, наклеек, гравировки
    и добавляет в BOM дополнительные аксессуары (role == 'OTHER').
    """
    priority = 700

    def process(self, context: SpecContext):
        for gc in context.customizers:
            try:
                SingleCustomizerStep(gc).process(context)
            except PipelineError as e:
                context.add_error(str(e))
            except Exception as e:
                context.add_error(f"Unexpected error in customizer {gc.customizer.code}: {e}")


class MachiningRoutingStep(SpecStep):
    """
    Priority 750: Resolves individual station routing and CNC target machines for the item.
    Uses CNC dimensional limits from ProductEngineeringRule (in cm).
    """
    priority = 750
    important_for_phase1 = False

    def process(self, context: SpecContext):
        spec = context.spec
        group = context.group
        if not group:
            return

        rules = context.get_engineering_rules()
        limits = rules.cnc_limits

        base_stations = ProductionRoute.get_stations_for_group(group)

        if spec.panel_dimensions:
            p0 = spec.panel_dimensions[0]
            w_cm = max(float(p0.get('width') or 0), float(p0.get('width_bottom') or 0))
            h_cm = float(p0.get('height') or 0)
        else:
            w_cm = max(float(spec.width or 0), float(spec.width_bottom or 0))
            h_cm = float(spec.height or 0)

        fits_essepigi_dims = (
                not spec.is_double_door
                and (limits.essepigi_min_w <= w_cm <= limits.essepigi_max_w)
                and (limits.essepigi_min_h <= h_cm <= limits.essepigi_max_h)
        )

        customizer_ids = [gc.customizer_id for gc in context.customizers if gc.customizer_id]
        forced_alt_global = False
        forced_station_ids = set()

        if customizer_ids:
            forced_rules = CustomizerProductionStation.objects.filter(
                customizer_id__in=customizer_ids,
                force_alternative_machine=True,
            ).values_list('station_id', flat=True)
            forced_station_ids = set(forced_rules)
            forced_alt_global = bool(forced_station_ids)

        final_stations = []
        cnc_targets: Dict[int, str] = {}

        for st in base_stations:
            effective_st = st
            is_cnc_label_station = (1 <= getattr(st, 'specification_type', 0) <= 3)

            if is_cnc_label_station:
                needs_alternative = (
                        not fits_essepigi_dims
                        or forced_alt_global
                        or (st.id in forced_station_ids)
                )
                if needs_alternative and st.alternative_station_id:
                    effective_st = st.alternative_station

                label_type_idx = effective_st.specification_type - 1
                if effective_st.target_machine:
                    cnc_targets[label_type_idx] = effective_st.target_machine

            final_stations.append(effective_st)

        default_machine = (
            DoorLabel.TargetMachine.ESSEPIGI
            if (fits_essepigi_dims and not forced_alt_global)
            else DoorLabel.TargetMachine.ACCORD_STD
        )
        for l_idx in (0, 1, 2):
            if l_idx not in cnc_targets:
                cnc_targets[l_idx] = default_machine

        spec.route_station_ids = [s.id for s in final_stations if s and s.id]
        spec.route_station_codes = [s.code for s in final_stations if s and s.code]
        spec.cnc_targets = cnc_targets


class FrameResolutionStep(SpecStep):
    priority = 350

    def process(self, context: SpecContext):
        product = context.product
        group = context.group
        spec = context.spec

        if not spec.has_frame or not product:
            return

        bom = context.bom
        bom_frame = getattr(bom, 'frame', None) if bom else None
        chosen = group.basic_color_frames

        material = bom_frame
        if chosen and bom_frame:
            bom_cn = (bom_frame.common_name or '').strip()
            chosen_cn = (chosen.common_name or '').strip()

            if chosen.id == bom_frame.id or (bom_cn and chosen_cn == bom_cn):
                material = chosen
            elif bom_cn and chosen.color_id:
                same_color_mat = Material.objects.filter(
                    common_name=bom_cn,
                    color_id=chosen.color_id,
                ).first()
                material = same_color_mat or bom_frame
        elif chosen and not bom_frame:
            material = chosen

        if not material:
            return

        if context.item.opening == 'OUT' and material.outward_substitute:
            material = material.outward_substitute

        context.data['resolved_frame_material'] = material
        context.spec.context['resolved_frame_material'] = {
            'id': material.id,
            'name': material.name,
            'common_name': material.common_name or '',
            'sku': material.sku,
        }


class CasingResolutionStep(SpecStep):
    """
    Priority 390: Replaces BOM casing material with its `outward_substitute`
    when an active customizer with the 'CASING' tag is attached to the group.
    """
    priority = 390

    def process(self, context: SpecContext):
        base_bom = context.bom
        if not base_bom:
            return

        current_casing = getattr(base_bom, 'casing', None)
        if not current_casing:
            return

        if not context.find_customizers('CASING'):
            return

        substitute = getattr(current_casing, 'outward_substitute', None)
        if not substitute:
            return

        patched_bom = copy.copy(base_bom)
        patched_bom.casing = substitute
        context.bom = patched_bom


class BOMOverrideStep(SpecStep):
    """
    Priority 380: Patches base product BOM with overrides declared
    in active group customizers. Operates strictly with Material SKU.
    """
    priority = 380
    important_for_phase1 = False

    def process(self, context: SpecContext):
        base_bom = context.bom
        if not base_bom:
            return

        combined_materials = {}
        combined_pictograms = {}

        for gc in context.customizers:
            c = gc.customizer
            overrides = getattr(c, 'bom_overrides', None)
            if not isinstance(overrides, dict) or not overrides:
                continue

            mat_block = overrides.get('materials')
            if isinstance(mat_block, dict):
                combined_materials.update(mat_block)

            pic_block = overrides.get('pictograms')
            if isinstance(pic_block, dict):
                combined_pictograms.update(pic_block)

        if not combined_materials and not combined_pictograms:
            return

        patched_bom = copy.copy(base_bom)

        if combined_materials:
            try:
                active_skus = {
                    str(sku).strip()
                    for sku in combined_materials.values()
                    if sku and str(sku).strip()
                }
                materials_map = {
                    m.sku: m
                    for m in Material.objects.filter(sku__in=active_skus)
                }

                for slot_name, raw_sku in combined_materials.items():
                    if not hasattr(patched_bom, slot_name):
                        continue

                    clean_sku = str(raw_sku).strip() if raw_sku else ""
                    if not clean_sku:
                        setattr(patched_bom, slot_name, None)
                    else:
                        target_mat = materials_map.get(clean_sku)
                        if target_mat:
                            setattr(patched_bom, slot_name, target_mat)
            except Exception as e:
                context.add_error(f"Error overriding BOM materials: {e}")

        if combined_pictograms:
            try:
                active_preset_names = {
                    str(name).strip()
                    for name in combined_pictograms.values()
                    if name and str(name).strip()
                }
                presets_map = {
                    p.name: p
                    for p in PuzzlePreset.objects.filter(name__in=active_preset_names)
                }

                for slot_name, raw_name in combined_pictograms.items():
                    if not hasattr(patched_bom, slot_name):
                        continue

                    clean_name = str(raw_name).strip() if raw_name else ""
                    if not clean_name:
                        setattr(patched_bom, slot_name, None)
                    else:
                        target_preset = presets_map.get(clean_name)
                        if target_preset:
                            setattr(patched_bom, slot_name, target_preset)
            except Exception as e:
                context.add_error(f"Error overriding BOM pictograms: {e}")

        context.bom = patched_bom


class BOMStep(SpecStep):
    priority = 400

    def process(self, context: SpecContext):
        item = context.item
        group = context.group
        product = context.product
        spec = context.spec

        if not product:
            return

        resolved_frame = context.data.get('resolved_frame_material')

        calc_context = {
            'H': float(item.height or 0),
            'W': float(item.width or 0),
            'wall': float(item.wall or 0),
            'basic_color_frames': resolved_frame or group.basic_color_frames,
            'resolved_frame_material': resolved_frame,
            'effective_bom': context.bom,
            'has_frame': spec.has_frame,
            'customizers': {},
        }

        calc = BOMCalculator(calc_context)
        bom_result = calc.calculate_for_product(product)

        spec_bom_items = []
        profiles = []
        for b in bom_result:
            item_obj = b['item']
            spec_bom_items.append(SpecBOMItem(
                type=b['type'],
                section=b['section'],
                item_name=item_obj.name,
                quantity=b['quantity'],
                common_name=getattr(item_obj, 'common_name', None),
                tag=b.get('tag'),
                item_id=item_obj.id,
            ))

            if b.get('tag') in ('profile1', 'profile2', 'profile3'):
                profiles.append(item_obj.name)

        if resolved_frame:
            spec.frame = (resolved_frame.common_name or '').strip() or resolved_frame.name

        # Сохраняем уже добавленные на ранних шагах позиции (например, wood_edge)
        preserved_items = [b for b in spec.bom_items if b.tag == 'wood_edge']
        spec.bom_items = spec_bom_items + preserved_items
        spec.profiles = profiles

        lock_bom = next(
            (b for b in bom_result if isinstance(b, dict) and str(b.get('tag') or '').lower() == 'lock'),
            None,
        )
        if lock_bom and lock_bom.get('item'):
            lock_item = lock_bom['item']
            spec.lock_id = lock_item.id
            spec.lock_name = (getattr(lock_item, 'common_name', '') or '').strip() or lock_item.name
        else:
            spec.lock_id = None
            spec.lock_name = "N/A"

        hinge_bom = next(
            (b for b in bom_result if isinstance(b, dict) and str(b.get('tag') or '').lower() == 'hinge'),
            None,
        )
        if hinge_bom and hinge_bom.get('item'):
            hinge_item = hinge_bom['item']
            spec.hinge_name = (getattr(hinge_item, 'common_name', '') or '').strip() or hinge_item.name
        else:
            spec.hinge_name = "N/A"

        context.data['bom_result'] = bom_result


class MaterialSelectionStep(SpecStep):
    priority = 410
    important_for_phase1 = False

    def process(self, context: SpecContext):
        spec = context.spec
        panels = spec.panel_dimensions
        if not panels:
            return

        new_bom_items = []
        for bom_item in spec.bom_items:
            if bom_item.tag not in ('covering', 'base'):
                new_bom_items.append(bom_item)
                continue

            original_material = Material.objects.filter(id=bom_item.item_id).first()
            if not original_material:
                new_bom_items.append(bom_item)
                continue

            common_name = original_material.common_name
            color = original_material.color

            for i, panel in enumerate(panels):
                panel_h = float(panel.get('height') or 0)
                panel_w = max(float(panel.get('width') or 0), float(panel.get('width_bottom') or 0))

                suitable_material = Material.objects.filter(
                    common_name=common_name,
                    color=color,
                    length__gte=panel_h + 1,
                    width__gte=panel_w,
                ).order_by('length', 'width').first()

                section_suffix = f" (Panel {i + 1})" if len(panels) > 1 else ""
                if suitable_material:
                    new_bom_items.append(SpecBOMItem(
                        type=bom_item.type,
                        section=f"{bom_item.section}{section_suffix}",
                        item_name=suitable_material.name,
                        common_name=common_name,
                        quantity=bom_item.quantity / len(panels),
                        tag=bom_item.tag,
                        item_id=suitable_material.id,
                    ))
                else:
                    new_bom_items.append(SpecBOMItem(
                        type=bom_item.type,
                        section=f"{bom_item.section}{section_suffix}",
                        item_name=bom_item.item_name,
                        common_name=common_name,
                        quantity=bom_item.quantity / len(panels),
                        tag=bom_item.tag,
                        item_id=bom_item.item_id,
                    ))
                    context.add_error(f"No suitable sheet found for {bom_item.section}{section_suffix}")

        spec.bom_items = new_bom_items


class SandwichAndFrameStep(SpecStep):
    priority = 520
    important_for_phase1 = False

    def process(self, context: SpecContext):
        spec = context.spec
        if not getattr(spec, 'has_door', True) or getattr(context, 'phase', None) == 'phase1':
            return

        bom = context.bom
        if not bom:
            return

        rules = context.get_engineering_rules()
        puzzle_spec = DoorPuzzleSpec()
        prototypes = {p.code: p for p in PuzzleBlockPrototype.objects.select_related('pattern').all()}

        params = {
            'H': spec.height,
            'W': spec.width,
            'thickness': rules.thickness or 4.0,
        }

        preset_fields = ['filling_preset', 'panel_frame_preset', 'base_preset']
        if not getattr(spec, 'is_hidden_wood_edge', False):
            preset_fields.append('covering_preset')

        for preset_field in preset_fields:
            preset = getattr(bom, preset_field, None)
            if preset and preset.blocks_config:
                self.unpack_preset_blocks(preset.blocks_config, prototypes, puzzle_spec, params)

        spec.puzzle_spec = puzzle_spec

    def unpack_preset_blocks(
            self,
            blocks_config,
            prototypes: dict,
            puzzle_spec: DoorPuzzleSpec,
            params: Optional[dict] = None,
            labels: Optional[list] = None,
    ):
        params = params or {}
        if not blocks_config:
            return

        if isinstance(blocks_config, dict):
            for view_name in ('face', 'sandwich'):
                items = blocks_config.get(view_name, [])
                for cfg in items:
                    block = self._create_puzzle_block(cfg, prototypes, params, labels=labels)
                    if not block:
                        continue
                    if view_name == 'face':
                        puzzle_spec.face_blocks.append(block)
                    elif view_name == 'sandwich':
                        puzzle_spec.sandwich_blocks.append(block)
        elif isinstance(blocks_config, list):
            for cfg in blocks_config:
                block = self._create_puzzle_block(cfg, prototypes, params, labels=labels)
                if not block:
                    continue
                view = cfg.get('view')
                if view == 'face':
                    puzzle_spec.face_blocks.append(block)
                elif view == 'sandwich':
                    puzzle_spec.sandwich_blocks.append(block)

    def _create_puzzle_block(self, cfg: dict, prototypes: dict, params: dict, labels: Optional[list] = None):
        proto = prototypes.get(cfg.get('component'))
        if not proto:
            return None

        x = FormulaEvaluator.evaluate(cfg.get('x', 0), params)
        y = FormulaEvaluator.evaluate(cfg.get('y', 0), params)
        w = FormulaEvaluator.evaluate(cfg.get('w', 0), params)
        h = FormulaEvaluator.evaluate(cfg.get('h', 0), params)

        raw_text = cfg.get('text', '')
        rendered_text = ''

        if raw_text:
            def eval_match(match):
                expr = match.group(1).strip()
                try:
                    res = FormulaEvaluator.evaluate(expr, params)
                    return str(int(res)) if res == int(res) else str(round(res, 2))
                except Exception:
                    return match.group(0)

            rendered_text = re.sub(r'\{([^}]+)}', eval_match, str(raw_text))

        fill_color = cfg.get('fill_color') or proto.fill_color
        border_color = cfg.get('border_color') or proto.border_color
        border_width = cfg.get('border_width', proto.border_width)
        opacity = cfg.get('opacity', proto.opacity)

        text_x_raw = cfg.get('text_x')
        text_y_raw = cfg.get('text_y')
        text_x = FormulaEvaluator.evaluate(text_x_raw, params) if text_x_raw is not None else round(x + w / 2, 2)
        text_y = FormulaEvaluator.evaluate(text_y_raw, params) if text_y_raw is not None else round(y + h / 2, 2)

        params_meta = params.get('params_meta', {})
        text_param_key = cfg.get('text_param')
        if not text_param_key and raw_text:
            for p_k in ('p1', 'p2', 'p3', 'p4', 'p5'):
                if f"{{{p_k}" in str(raw_text):
                    text_param_key = p_k
                    break

        is_param_custom = False
        if text_param_key and text_param_key in params_meta:
            is_param_custom = bool(params_meta[text_param_key].get('is_custom'))

        text_color = '#dc3545' if is_param_custom else (cfg.get('text_color') or proto.default_text_color or '#000000')

        if rendered_text and labels is not None:
            labels.append({
                'text': rendered_text,
                'is_custom': is_param_custom,
            })

        return SvgPuzzleBlock(
            x=x,
            y=y,
            w=w,
            h=h,
            fill_type=proto.fill_type,
            fill_color=fill_color,
            pattern_name=proto.pattern.name if proto.pattern else None,
            border_color=border_color,
            border_width=border_width,
            opacity=opacity,
            order=cfg.get('order', 10),
            text=rendered_text,
            text_color=text_color,
            text_x=text_x,
            text_y=text_y,
            font_size=cfg.get('font_size') or proto.default_font_size,
        )


class CustomizerPuzzleStep(SpecStep):
    """
    Приоритет 530: Обрабатывает кастомизаторы, у которых есть CustomizerPuzzleMapping.
    Добавляет геометрию в puzzle_spec и регистрирует примененные пресеты в applied_presets.
    """
    priority = 530
    important_for_phase1 = False

    def process(self, context: SpecContext):
        spec = context.spec
        if not getattr(spec, 'has_door', True) or getattr(context, 'phase', None) == 'phase1':
            return

        if not spec.puzzle_spec:
            spec.puzzle_spec = DoorPuzzleSpec()

        prototypes = {p.code: p for p in PuzzleBlockPrototype.objects.select_related('pattern').all()}
        sandwich_step = SandwichAndFrameStep()

        for gc in context.customizers:
            c = gc.customizer
            mapping = getattr(c, 'puzzle_mapping', None)
            if not mapping or not mapping.preset:
                continue

            preset = mapping.preset
            blocks_config = preset.blocks_config
            if not blocks_config:
                continue

            customizer_params: Dict[str, Any] = {
                'H': float(spec.height or 0),
                'W': float(spec.width or 0),
            }
            params_meta: Dict[str, Dict[str, Any]] = {}
            preset_labels = []

            for i in range(1, 6):
                val_order = getattr(gc, f'par{i}', None)
                val_default = getattr(c, f'par{i}_value', None)
                str_order = str(val_order).strip() if val_order not in (None, '') else ''
                str_default = str(val_default).strip() if val_default not in (None, '') else ''

                if str_order != '':
                    val = val_order
                    try:
                        is_custom = float(str_order) != float(str_default) if str_default != '' else True
                    except ValueError:
                        is_custom = str_order != str_default
                else:
                    val = val_default
                    is_custom = False

                if val is not None and str(val).strip() != '':
                    val_str = str(val).strip()
                    try:
                        parsed_val = float(val_str)
                    except ValueError:
                        parsed_val = val_str

                    p_key = f'p{i}'
                    customizer_params[p_key] = parsed_val
                    params_meta[p_key] = {
                        'val': parsed_val,
                        'is_custom': is_custom,
                    }

            customizer_params['params_meta'] = params_meta

            sandwich_step.unpack_preset_blocks(
                blocks_config=blocks_config,
                prototypes=prototypes,
                puzzle_spec=spec.puzzle_spec,
                params=customizer_params,
                labels=preset_labels,
            )

            spec.applied_presets.append({
                'name': preset.name,
                'code': getattr(preset, 'code', ''),
                'customizer_name': c.name,
                'labels': preset_labels,
            })


class MediaStep(SpecStep):
    priority = 900

    def process(self, context: SpecContext):
        item = context.item
        spec = context.spec
        if item.sketch:
            spec.sketch_url = item.sketch.url


class SpecPipeline:
    def __init__(self):
        self.steps = [
            BaseItemStep(),
            ProductDataStep(),
            DoubleDoorStep(),
            WoodEdgeStep(),
            DoorLabelInitStep(),
            PanelDimensionStep(),
            CutSheetsStep(),
            AppearanceStep(),
            FrameResolutionStep(),
            BOMOverrideStep(),
            CasingResolutionStep(),
            BOMStep(),
            MaterialSelectionStep(),
            LockSelectionStep(),
            LockOptionSelectionStep(),
            HandleSelectionStep(),
            HingeSelectionStep(),
            LockPositionStep(),
            HingePositionStep(),
            SandwichAndFrameStep(),
            CustomizerPuzzleStep(),
            MeasurerDataStep(),
            CustomizersFormattingStep(),
            MachiningRoutingStep(),
            MediaStep(),
            DoorLabelEnrichStep(),
        ]

    def execute(self, item: OrderItem, customizers=None, phase: str = 'phase2') -> ProductionSpec:
        context = SpecContext(item, customizers=customizers, phase=phase)
        all_steps = sorted(self.steps, key=lambda s: getattr(s, 'priority', 9999))

        for step in all_steps:
            if phase == 'phase1' and not getattr(step, 'important_for_phase1', True):
                continue

            try:
                step.process(context)
            except PipelineError as e:
                context.add_error(str(e))
            except Exception as e:
                context.add_error(f"Unexpected error in {step.__class__.__name__}: {e}")

        return context.spec


class OrderSpecContext:
    def __init__(self, order, items=None, phase: str = 'phase2', save_labels: bool = False):
        self.order = order
        self.phase = phase
        self.save_labels = save_labels
        self.items = items if items is not None else list(
            OrderItem.objects.filter(group__order=order).exclude(
                group__production_state__in=[
                    OrderItemsGroup.ProductionState.WAITING,
                    OrderItemsGroup.ProductionState.CANCELED,
                ]
            )
        )
        self.spec = OrderSpec(
            order=OrderHeaderSpec(
                number="",
                customer="",
                status="",
                production_start_date="",
                completion_date="",
                painting_completion_date="",
            ),
            batches={},
        )
        self.data: Dict[str, Any] = {}


class OrderItemsStep(OrderStep):
    def process(self, context: OrderSpecContext):
        group_ids = {item.group_id for item in context.items if item.group_id}
        all_group_customizers = OrderItemsGroupCustomizer.objects.filter(
            group_id__in=group_ids
        ).select_related(
            'customizer',
            'customizer__puzzle_mapping__preset',
            'customizer__outward_replacement',
            'customizer__outward_replacement__puzzle_mapping__preset',
        ).prefetch_related(
            'customizer__hardware__components',
            'customizer__outward_replacement__hardware__components',
        ).order_by('customizer__tag', 'customizer__code')

        customizers_by_group = collections.defaultdict(list)
        for gc in all_group_customizers:
            customizers_by_group[gc.group_id].append(gc)

        item_pipeline = SpecPipeline()
        context.data['item_inputs'] = {}

        for item in context.items:
            raw_batch = item.group.batch_number if item.group else None
            batch_num = str(raw_batch) if raw_batch else 'NEW'
            if batch_num not in context.spec.batches:
                context.spec.batches[batch_num] = []

            group_customizers = customizers_by_group.get(item.group_id, [])
            context.data['item_inputs'][item.id] = (item, group_customizers)

            item_spec = item_pipeline.execute(item, customizers=group_customizers, phase=context.phase)
            context.spec.batches[batch_num].append(item_spec)


class OrderLockHeightAlignmentStep(OrderStep):
    """
    Автоматическое выравнивание высот замков внутри партии (батча) в рамках
    одной записи LockStandardHeight и блокирующая проверка при неразрешимом конфликте.
    """
    ERROR_MESSAGE = "לא ניתן לקבוע גובה מנעול אוטומטית עבור חלק מהדלתות — נא להגדיר ידנית"

    def process(self, context: OrderSpecContext):
        item_inputs = context.data.get('item_inputs', {})

        for batch_specs in context.spec.batches.values():
            buckets = collections.defaultdict(list)

            for spec in batch_specs:
                if (
                        not getattr(spec, 'has_door', True)
                        or not spec.lock_id
                        or spec.lock_height is None
                        or spec.lock_height <= 0
                ):
                    continue

                meta = spec.context.get('lock_alignment_meta') or {}
                if meta.get('is_manual'):
                    continue

                rule = meta.get('rule')
                if not rule or rule.get('step', 0) <= 0 or rule.get('alignment_tolerance', 0) <= 0:
                    continue

                buckets[rule['id']].append((spec, rule))

            for bucket in buckets.values():
                if len(bucket) < 2:
                    continue
                self._process_bucket(bucket, context.phase, item_inputs)

    def _process_bucket(self, bucket: list, phase: str, item_inputs: dict):
        bucket.sort(key=lambda pair: (float(pair[0].height or 0), pair[0].item_id))
        rule = bucket[0][1]
        tolerance = float(rule['alignment_tolerance'])
        base_h = float(rule['base_door_height'])
        base_lock = float(rule['base_lock_height'])
        step = float(rule['step'])

        has_conflict = any(
            (float(bucket[i + 1][0].height or 0) - float(bucket[i][0].height or 0)) < tolerance
            and bucket[i + 1][0].lock_height != bucket[i][0].lock_height
            for i in range(len(bucket) - 1)
        )
        if not has_conflict:
            return

        clusters = [[bucket[0][0]]]
        for i in range(1, len(bucket)):
            prev_spec = bucket[i - 1][0]
            curr_spec = bucket[i][0]
            if (float(curr_spec.height or 0) - float(prev_spec.height or 0)) < tolerance:
                clusters[-1].append(curr_spec)
            else:
                clusters.append([curr_spec])

        for cluster in clusters:
            if len(cluster) < 2:
                continue

            target_lock_h = min(float(s.lock_height) for s in cluster)
            k = round((target_lock_h - base_lock) / step)
            threshold_h = base_h + (k * step)

            for s in cluster:
                if float(s.lock_height) == target_lock_h:
                    continue
                door_h = float(s.height or 0)
                if abs(door_h - threshold_h) <= tolerance:
                    self._apply_lock_height(s, target_lock_h, phase, item_inputs)

        for i in range(len(bucket) - 1):
            s1 = bucket[i][0]
            s2 = bucket[i + 1][0]
            if (
                    (float(s2.height or 0) - float(s1.height or 0)) < tolerance
                    and s1.lock_height != s2.lock_height
            ):
                if self.ERROR_MESSAGE not in s1.errors:
                    s1.errors.append(self.ERROR_MESSAGE)
                if self.ERROR_MESSAGE not in s2.errors:
                    s2.errors.append(self.ERROR_MESSAGE)

    @staticmethod
    def _apply_lock_height(spec: ProductionSpec, new_lock_h: float, phase: str, item_inputs: dict):
        spec.lock_height = new_lock_h
        spec.lock_height_on_frame = new_lock_h + float(spec.leaf_top_clearance or 0)

        drafts = spec.context.get('label_drafts')
        if phase != 'phase1' and drafts and spec.item_id in item_inputs:
            from .label_services import DoorLabelService
            item, customizers = item_inputs[spec.item_id]
            DoorLabelService.enrich_hardware_and_cnc(
                drafts=drafts,
                spec=spec,
                item=item,
                customizers=customizers,
            )


class OrderHeaderStep(OrderStep):
    """Step 1: Maps raw Order model fields into OrderHeaderSpec schema."""

    def process(self, context: OrderSpecContext):
        order = context.order
        context.spec.order = OrderHeaderSpec(
            number=str(order.order_number or ""),
            customer=order.customer or "",
            status=order.status,
            production_start_date=format_spec_date(getattr(order, 'production_start_date', None)),
            completion_date=format_spec_date(getattr(order, 'completion_date', None)),
            painting_completion_date=format_spec_date(getattr(order, 'painting_completion_date', None)),
        )


class OrderSpecPipeline:
    def __init__(self, steps: Optional[List[OrderStep]] = None):
        self.steps = steps or [
            OrderHeaderStep(),
            OrderItemsStep(),
            OrderLockHeightAlignmentStep(),
            OrderDoorLabelsStep(),
        ]

    def execute(self, order, items=None, phase: str = 'phase2', save_labels: bool = False) -> OrderSpec:
        context = OrderSpecContext(order, items, phase=phase, save_labels=save_labels)
        for step in self.steps:
            step.process(context)
        return context.spec


class DoorLabelInitStep(SpecStep):
    priority = 18
    important_for_phase1 = False

    def process(self, context: SpecContext):
        product = context.product
        has_door = product.has_door if product else True
        if not has_door:
            return

        is_double = getattr(context.spec, 'is_double_door', False) or context.data.get('is_double', False)
        has_inlaid = getattr(context.spec, 'is_hidden_wood_edge', False)

        from .label_services import DoorLabelService
        context.label_drafts = DoorLabelService.init_item_label_drafts(
            order=context.order,
            item=context.item,
            is_double_door=is_double,
            has_inlaid_edge=has_inlaid,
        )
        context.spec.context['label_drafts'] = context.label_drafts


class DoorLabelEnrichStep(SpecStep):
    priority = 1100
    important_for_phase1 = False

    def process(self, context: SpecContext):
        if not context.label_drafts:
            return

        from .label_services import DoorLabelService
        DoorLabelService.enrich_hardware_and_cnc(
            drafts=context.label_drafts,
            spec=context.spec,
            item=context.item,
            customizers=context.customizers,
        )
        context.spec.edge_shape = any(bool(d.get('edge_shape')) for d in context.label_drafts)


class OrderDoorLabelsStep(OrderStep):
    def process(self, context: OrderSpecContext):
        if context.phase == 'phase1' or not getattr(context, 'save_labels', False):
            return

        all_drafts = []
        for batch_items in context.spec.batches.values():
            for item_spec in batch_items:
                drafts = item_spec.context.get('label_drafts') or []
                all_drafts.extend(drafts)

        if all_drafts:
            from .label_services import DoorLabelService
            DoorLabelService.persist_label_drafts(context.order, all_drafts)
