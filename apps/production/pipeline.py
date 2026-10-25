import collections
import math
import re
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

from apps.catalog.models import Material
from apps.orders.models import OrderItem, OrderItemsGroup, OrderItemsGroupCustomizer
from .bom_calculator import BOMCalculator
from .evaluator import FormulaEvaluator
from .models import LockStandardHeight, HingeStandardHeight, PuzzleBlockPrototype
from .schemas import (
    ProductionSpec, SpecBOMItem, SpecCustomizerParam, SpecCustomizerReport,
    OrderHeaderSpec, OrderSpec, DoorPuzzleSpec, SvgPuzzleBlock
)


def format_spec_date(d) -> str:
    """Helper to format a DateField into dd/mm/yyyy string."""
    return d.strftime("%d/%m/%y") if d else ""


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
            mark=item.mark or ""
        )
        self.data: Dict[str, Any] = {}

        if customizers is not None:
            self.customizers = customizers
        else:
            if self.group:
                self.customizers = list(
                    self.group.customizers.select_related('customizer', 'customizer__puzzle_mapping__preset')
                    .prefetch_related('customizer__hardware__components', 'customizer__materials')
                    .order_by('customizer__tag', 'customizer__code')
                )
            else:
                self.customizers = []

        self.unprocessed_customizers = list(self.customizers)
        self.processed_customizers = []

    def add_error(self, message: str):
        self.spec.errors.append(message)

    def consume_customizers(self, tags) -> List:
        """Finds customizers by tag(s), moves them to processed, and returns them."""
        if isinstance(tags, str):
            tags_set = {tags.upper()}
        else:
            tags_set = {t.upper() for t in tags}

        found = []
        remaining = []
        for gc in self.unprocessed_customizers:
            tag_str = (gc.customizer.tag or "").upper()
            item_tags = {t.strip() for t in tag_str.replace(',', ' ').split() if t.strip()}

            if item_tags & tags_set:
                found.append(gc)
                # ЕСЛИ у кастомизатора есть тег отчета, НЕ удаляем его из unprocessed,
                # чтобы он дошел до SingleCustomizerStep!
                report_tags = {'DOORS_REPORT', 'FRAMES_REPORT', 'FRAME_MODIFICATION'}
                if not (item_tags & report_tags):
                    self.processed_customizers.append(gc)
                else:
                    remaining.append(gc)  # оставляем для дальнейшей обработки в отчетах
            else:
                remaining.append(gc)

        self.unprocessed_customizers = remaining
        return found


class SpecStep(ABC):
    priority: int = 0
    important_for_phase1: bool = True  # По умолчанию участвует и в Фазе 1, и в Фазе 2

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

        # 1. Проверка габаритов
        h = float(item.height or 0)
        w = float(item.width or 0)
        wall = float(item.wall or 0)

        if h <= 0:
            context.add_error("לא הוזן גובה תקין")
        if w <= 0:
            context.add_error("לא הוזן רוחב תקין")

        spec.height = h
        spec.width = w
        spec.wall = wall

        # 2. Проверка коробки
        has_frame = product.has_frame if product else True
        if has_frame and wall <= 0:
            context.add_error("לא הוזן עובי קיר למשקוף")

        # 3. Проверка параметров открывания
        has_door = product.has_door if product else True
        if has_door:
            if not item.opening:
                context.add_error("לא נבחר כיוון פתיחה (פנימה/החוצה)")
            if not item.direction:
                context.add_error("לא נבחרה יד פתיחה (L/R)")

            if product and item.opening:
                allowed = getattr(product, 'allowed_direction', 'BOTH')
                op = str(item.opening).strip().upper()
                is_in = op in ('IN', 'INWARD', 'פנימה')
                is_out = op in ('OUT', 'OUTWARD', 'החוצה')

                if allowed == 'IN_ONLY' and not is_in:
                    context.add_error(f"הדגם תומך בפתיחה פנימה בלבד (IN)")
                elif allowed == 'OUT_ONLY' and not is_out:
                    context.add_error(f"הדגם תומך בפתיחה החוצה בלבד (OUT)")

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

        spec.product_name = product.name
        spec.product_code = product.code
        spec.has_door = product.has_door
        spec.has_frame = product.has_frame
        spec.cut_coefficients = product.cut_coefficients or {}
        if product.product_family:
            spec.product_family = product.product_family.name
            if not spec.series and product.series:
                spec.series = product.series.name

        # Проверка обязательных кастомизаторов модели
        group_customizers_map = {gc.customizer_id: gc for gc in context.customizers}
        for req_cust in product.get_required_customizers():
            if req_cust.id not in group_customizers_map:
                context.add_error(f"חסר קסטומייזר חובה '{req_cust.name}'")

        # Проверка обязательных параметров у прикрепленных кастомизаторов
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

    # important_for_phase1 = True (по умолчанию)

    def process(self, context: SpecContext):
        spec = context.spec
        item = context.item

        # Пропускаем только если модель в принципе не имеет полотна
        if not getattr(spec, 'has_door', True):
            return

        group_customizers = context.consume_customizers('LOCK')

        # 1. Проверка переопределения через кастомизатор
        if group_customizers:
            for gc in group_customizers:
                c = gc.customizer
                tag_val = (c.tag or '').upper()
                c_code = (c.code or '').upper()

                if any(k in tag_val or k in c_code for k in ('NO_LOCK', 'WITHOUT_LOCK', 'NONE')):
                    spec.lock_id = None
                    spec.lock_name = 'ללא מנעול'
                    spec.bom_items = [b for b in spec.bom_items if str(b.tag).lower() != 'lock']
                    return

                main_hw = c.hardware
                if main_hw:
                    hardware_list = [main_hw] + list(main_hw.components.all())
                    spec.bom_items = [b for b in spec.bom_items if str(b.tag).lower() != 'lock']
                    spec.lock_id = main_hw.id
                    spec.lock_name = main_hw.name

                    for hw in hardware_list:
                        spec.bom_items.append(
                            SpecBOMItem(
                                type='hardware',
                                section='Lock',
                                item_name=hw.name,
                                quantity=1,
                                tag='lock',
                                item_id=hw.id
                            )
                        )

                custom_h = self._extract_custom_height(gc)
                if custom_h and custom_h > 0:
                    context.data['override_lock_height'] = custom_h

        # 2. Проверка значения из BOM
        current_lock_name = (spec.lock_name or '').strip()
        if current_lock_name in ('ללא מנעול', 'ללא', 'NO_LOCK', 'NONE') or 'ללא' in current_lock_name:
            spec.lock_name = 'ללא מנעול'
            spec.lock_id = None
            return

        if not spec.lock_name or spec.lock_name == 'N/A':
            raise PipelineError(f"לא הוגדר דגם מנעול לדלת מס' {item.mark or item.id}")

    @staticmethod
    def _extract_custom_height(group_customizer) -> Optional[float]:
        c = group_customizer.customizer
        for i in range(1, 6):
            label = (getattr(c, f'par{i}_label') or '').lower()
            val = getattr(group_customizer, f'par{i}') or getattr(c, f'par{i}_value')
            if ('גובה' in label or 'height' in label) and val:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        val = group_customizer.par1 or c.par1_value
        if val:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return 0.0


class LockPositionStep(SpecStep):
    priority = 500

    # important_for_phase1 = True (по умолчанию)

    def process(self, context: SpecContext):
        spec = context.spec
        item = context.item

        if not getattr(spec, 'has_door', True):
            return

        # Если замок явно отменен
        if spec.lock_name == 'ללא מנעול' or spec.lock_id is None:
            spec.lock_height = 0.0
            return

        effective_height = None

        # Приоритет 1: Прямая высота позиции (Item)
        if item.custom_lock_height:
            try:
                val = float(item.custom_lock_height)
                if val > 0:
                    effective_height = val
            except (ValueError, TypeError):
                pass

        # Приоритет 2: Параметр кастомизатора группы
        if effective_height is None:
            override_h = context.data.get('override_lock_height')
            if override_h and float(override_h) > 0:
                effective_height = float(override_h)

        # Приоритет 3: Нормативная таблица
        if effective_height is None:
            effective_height = self._get_effective_lock_height(item, spec.lock_id)

        if not effective_height or effective_height <= 0:
            raise PipelineError(
                f"לא נמצא גובה תקני למנעול '{spec.lock_name}' (דלת מס' {item.mark or item.id})"
            )

        spec.lock_height = effective_height

    @staticmethod
    def _get_effective_lock_height(item: OrderItem, lock_id: int) -> float:
        product = getattr(item.group, 'product', None)
        if not product or not product.product_family or not lock_id:
            return 0.0

        std = LockStandardHeight.objects.filter(
            product_families=product.product_family,
            locks__id=lock_id
        ).first()

        if not std:
            return 0.0

        door_h = float(item.height or 0)
        base_h = float(std.base_door_height)
        base_lock = float(std.base_lock_height)
        step = float(std.step)

        diff = door_h - base_h
        intervals = math.ceil(diff / step) if step > 0 else 0
        return float(base_lock + (intervals * step))


class HingeSelectionStep(SpecStep):
    priority = 470

    # important_for_phase1 = True (по умолчанию)

    def process(self, context: SpecContext):
        spec = context.spec
        item = context.item

        if not getattr(spec, 'has_door', True):
            return

        group_customizers = context.consume_customizers('HINGE')

        # 1. Проверка переопределения через кастомизатор
        if group_customizers:
            for gc in group_customizers:
                c = gc.customizer
                tag_val = (c.tag or '').upper()
                c_code = (c.code or '').upper()

                if any(k in tag_val or k in c_code for k in ('NO_HINGES', 'WITHOUT_HINGES', 'NONE')):
                    spec.hinge_name = 'ללא צירים'
                    context.data['hinge_hardware_id'] = None
                    spec.bom_items = [b for b in spec.bom_items if str(b.tag).lower() != 'hinge']
                    return

                main_hw = c.hardware
                if main_hw:
                    hardware_list = [main_hw] + list(main_hw.components.all())
                    spec.bom_items = [b for b in spec.bom_items if str(b.tag).lower() != 'hinge']
                    spec.hinge_name = main_hw.name
                    context.data['hinge_hardware_id'] = main_hw.id

                    for hw in hardware_list:
                        spec.bom_items.append(
                            SpecBOMItem(
                                type='hardware',
                                section='צירים',
                                item_name=hw.name,
                                quantity=1,
                                tag='hinge',
                                item_id=hw.id
                            )
                        )

                custom_heights = self._extract_custom_heights(gc)
                if custom_heights:
                    context.data['override_hinge_heights'] = custom_heights

        # 2. Проверка значения из BOM
        current_hinge_name = (spec.hinge_name or '').strip()
        if current_hinge_name in ('ללא צירים', 'ללא', 'NO_HINGES', 'NONE') or 'ללא' in current_hinge_name:
            spec.hinge_name = 'ללא צירים'
            context.data['hinge_hardware_id'] = None
            return

        if not spec.hinge_name or spec.hinge_name == 'N/A':
            raise PipelineError(f"לא הוגדר דגם צירים לדלת מס' {item.mark or item.id}")

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


class HingePositionStep(SpecStep):
    priority = 510

    # important_for_phase1 = True (по умолчанию)

    def process(self, context: SpecContext):
        spec = context.spec
        item = context.item

        if not getattr(spec, 'has_door', True):
            return

        if spec.hinge_name == 'ללא צירים':
            spec.hinge_heights = []
            return

        effective_heights: List[float] = []

        # Проверяем, заданы ли петли на уровне двери (Item)
        has_item_hinges = any(
            getattr(item, f'custom_hinge{i}', None) not in (None, '', 0, '0')
            for i in range(1, 6)
        )

        if has_item_hinges:
            # Приоритет 1: Строго берем высоты ТОЛЬКО с двери
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
            # Приоритет 2: Кастомизатор группы
            override_heights = context.data.get('override_hinge_heights')
            if isinstance(override_heights, list) and override_heights:
                effective_heights = [float(h) for h in override_heights if float(h) > 0]

            # Приоритет 3: Таблица стандартов
            if not effective_heights:
                hinge_id = context.data.get('hinge_hardware_id')
                if not hinge_id:
                    hinge_bi = next((bi for bi in spec.bom_items if str(bi.tag).lower() == 'hinge'), None)
                    if hinge_bi:
                        hinge_id = hinge_bi.item_id

                if hinge_id:
                    effective_heights = self._get_std_hinge_heights(item, hinge_id)

        # Валидация
        if not effective_heights:
            raise PipelineError(
                f"לא נמצאו גבהים תקניים לצירים עבור '{spec.hinge_name}' (דלת מס' {item.mark or item.id})"
            )

        if len(effective_heights) < 2:
            raise PipelineError(
                f"נדרשים לפחות 2 צירים לדלת מס' {item.mark or item.id} (הוגדרו {len(effective_heights)})"
            )

        spec.hinge_heights = effective_heights

    @staticmethod
    def _get_std_hinge_heights(item: OrderItem, hinge_id: int) -> List[float]:
        product = getattr(item.group, 'product', None)
        if not product or not product.product_family or not hinge_id:
            return []

        door_h = float(item.height or 0)
        std = HingeStandardHeight.objects.filter(
            product_families__id=product.product_family.id,
            hinges__id=hinge_id,
            min_height__lte=door_h,
            max_height__gte=door_h
        ).first()

        if not std:
            return []

        res = []
        for i in range(1, 6):
            val = getattr(std, f'value{i}')
            if val and float(val) > 0:
                res.append(float(val))
        return res


class DoubleDoorStep(SpecStep):
    priority = 10

    def process(self, context: SpecContext):
        spec = context.spec
        found = context.consume_customizers('DOUBLE_DOOR')
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
    important_for_phase1 = False  # Wood edge belongs to door leaf production (Phase 2)

    def process(self, context: SpecContext):
        spec = context.spec
        item = context.item

        if not getattr(spec, 'has_door', True):
            return

        found = context.consume_customizers('WOOD_EDGE')
        if not found:
            return

        gc = found[0]
        c = gc.customizer

        # 1. Parameter 1: Wood type (oak, beech, etc.)
        wood_type = (gc.par1 if gc.par1 not in (None, '') else c.par1_value or '').strip()

        # 2. Parameter 2: Edge type ('outer' vs 'hidden')
        edge_type_raw = str(gc.par2 if gc.par2 not in (None, '') else c.par2_value or '').strip().lower()
        is_hidden = any(k in edge_type_raw for k in ('hidden', 'סמוי', 'פנימי'))

        # 3. Parameter 3: Thickness (optional)
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
                # Default for outer edge: 20 mm
                thickness_mm = 20.0
            else:
                # Default for hidden edge: 17 mm if double door, else 10 mm
                is_double = getattr(spec, 'is_double_door', False) or context.data.get('is_double', False)
                thickness_mm = 17.0 if is_double else 10.0

        # 4. Parameter 4: Sides (2, 3, 4, default = 4)
        sides_raw = gc.par4 if gc.par4 not in (None, '') else c.par4_value
        try:
            sides_count = int(sides_raw) if sides_raw else 4
        except (ValueError, TypeError):
            sides_count = 4

        if sides_count not in (2, 3, 4):
            sides_count = 4

        # 5. Store parameters in spec
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

        # BOM line
        edge_label = f"קנט עץ {wood_type} ({edge_data['type_name']}, {thickness_mm} מ\"מ, {sides_count} צדדים)".strip()
        spec.bom_items.append(
            SpecBOMItem(
                type='material',
                section='קנט עץ',
                item_name=edge_label,
                quantity=sides_count,
                tag='wood_edge',
                item_id=c.hardware_id if c.hardware else None
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

        pf = product.product_family
        h = float(item.height or 0)
        w = float(item.width or 0)
        bottom_correction = float(getattr(item, 'bottom_correction', 0) or 0)

        # 1. Внутренний свет проема коробки
        spec.inner_height = h + float(pf.frame_inner_height_reduction or 0)
        spec.inner_width = w + float(pf.frame_inner_width_reduction or 0)
        spec.frame_inner_height_reduction = float(pf.frame_inner_height_reduction or 0)
        spec.frame_inner_width_reduction = float(pf.frame_inner_width_reduction or 0)
        spec.leaf_top_clearance = float(pf.leaf_top_clearance or 0)

        if context.phase == 'phase1':
            spec.panel_dimensions = []
            spec.press_dimensions = []
            return

        # 2. Чистовые размеры полотна
        h_panel = spec.inner_height + float(pf.leaf_top_clearance or 0) + float(
            pf.leaf_bottom_clearance or 0) - bottom_correction

        if not context.data.get('is_double'):
            w_panel = spec.inner_width + float(pf.leaf_side_clearance or 0)
            panels = [{'width': round(w_panel, 2), 'height': round(h_panel, 2)}]
        else:
            w_net = spec.inner_width + 2 * float(pf.leaf_side_clearance or 0)
            par1 = context.data.get('double_door_par1', 0.5)
            par2 = context.data.get('double_door_par2', 0)

            if par2 > 0:
                w1 = par2 + 1
            else:
                if not (0 < par1 < 1):
                    par1 = 0.5
                w1 = w_net * par1 + 1

            w2 = w_net - w1 + float(pf.double_leaf_overlap or 0)
            panels = [
                {'width': round(w1, 2), 'height': round(h_panel, 2)},
                {'width': round(w2, 2), 'height': round(h_panel, 2)}
            ]

        spec.panel_dimensions = panels

        # 3. Габариты заготовки/каркаса под пресс (с вычетом канта)
        wood_edge = context.data.get('wood_edge')
        press_dims = []

        for p in panels:
            pw = p['width']
            ph = p['height']

            if not wood_edge:
                # Обычная дверь: полотно + 1 мм припуска
                press_w = pw + 1.0
                press_h = ph + 1.0
            else:
                t = float(wood_edge['thickness'])
                sides = int(wood_edge['sides'])

                # Ширина: вычитаем 2 стороны канта (лево и право) + 1 мм
                press_w = pw - (t * 2) + 1.0

                # Высота: вычитаем верх (sides > 2) и низ (sides > 3) + 1 мм
                height_sides_count = (1 if sides > 2 else 0) + (1 if sides > 3 else 0)
                press_h = ph - (t * height_sides_count) + 1.0

            press_dims.append({
                'width': round(press_w, 2),
                'height': round(press_h, 2)
            })

        spec.press_dimensions = press_dims


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
            panel_w = panel.get('width', 0)
            panel_h = panel.get('height', 0)

            sheet_data = {
                'panel_index': i + 1,
                'alucobond': self._calc(panel_w, panel_h, coeffs.get('alucobond')),
                'exterior_panel': self._calc(panel_w, panel_h, coeffs.get('exterior_panel')),
                'interior_panel': self._calc(panel_w, panel_h, coeffs.get('interior_panel')),
                'rails': {
                    'width': round(panel_w + rail_delta, 2),
                    'count': int(panel_h // 50)
                }
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
                'height': round(h + dh, 2)
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

        spec.color_panel_outside = group.effective_color_panel_outside or ""
        spec.color_panel_inside = group.effective_color_panel_inside or ""
        spec.color_frames = group.effective_color_frames or ""

        spec.panel_paint_option = group.panel_paint_option
        spec.frame_paint_option = group.frame_paint_option
        spec.basic_color_frames = str(group.basic_color_frames) if group.basic_color_frames else ""

        if order and order.handle:
            spec.handle_name = order.handle.name


class FrameResolutionStep(SpecStep):
    priority = 350

    def process(self, context: SpecContext):
        product = context.product
        group = context.group
        spec = context.spec

        if not spec.has_frame or not product:
            return

        material = group.basic_color_frames
        bom = getattr(product, 'effective_bom', None) or getattr(product, 'bom', None)
        if not material and bom:
            material = bom.frame

        if not material:
            return

        if context.item.opening == 'OUT' and material.outward_substitute:
            material = material.outward_substitute

        context.data['resolved_frame_material'] = material
        context.spec.context['resolved_frame_material'] = {
            'id': material.id,
            'name': material.name,
            'sku': material.sku
        }


class BOMStep(SpecStep):
    priority = 400

    def process(self, context: SpecContext):
        item = context.item
        group = context.group
        product = context.product
        spec = context.spec

        if not product:
            return

        calc_context = {
            'H': float(item.height or 0),
            'W': float(item.width or 0),
            'wall': float(item.wall or 0),
            'basic_color_frames': group.basic_color_frames,
            'resolved_frame_material': context.data.get('resolved_frame_material'),
            'has_frame': spec.has_frame,
            'customizers': {}
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
                tag=b.get('tag'),
                item_id=item_obj.id
            ))

            if b.get('tag') in ['profile1', 'profile2', 'profile3']:
                profiles.append(item_obj.name)

        spec.bom_items = spec_bom_items
        spec.profiles = profiles

        resolved_frame = context.data.get('resolved_frame_material')
        if resolved_frame:
            spec.frame = resolved_frame.name

        lock_bom = next((b for b in bom_result if isinstance(b, dict) and b.get('tag') == 'Lock'), None)
        if lock_bom and lock_bom.get('item'):
            lock_item = lock_bom['item']
            spec.lock_id = lock_item.id
            spec.lock_name = lock_item.name
        else:
            spec.lock_id = None
            spec.lock_name = "N/A"

        hinge_bom = next((b for b in bom_result if isinstance(b, dict) and b.get('tag') == 'hinge'), None)
        if hinge_bom and hinge_bom.get('item'):
            hinge_item = hinge_bom['item']
            spec.hinge_name = hinge_item.name
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
            if bom_item.tag not in ['covering', 'base']:
                new_bom_items.append(bom_item)
                continue

            original_material = Material.objects.filter(id=bom_item.item_id).first()
            if not original_material:
                new_bom_items.append(bom_item)
                continue

            common_name = original_material.common_name
            color = original_material.color

            for i, panel in enumerate(panels):
                panel_h = panel.get('height', 0)
                panel_w = panel.get('width', 0)

                suitable_material = Material.objects.filter(
                    common_name=common_name,
                    color=color,
                    length__gte=panel_h + 1,
                    width__gte=panel_w
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
                        item_id=suitable_material.id
                    ))
                else:
                    new_bom_items.append(SpecBOMItem(
                        type=bom_item.type,
                        section=f"{bom_item.section}{section_suffix}",
                        item_name=bom_item.item_name,
                        common_name=common_name,
                        quantity=bom_item.quantity / len(panels),
                        tag=bom_item.tag,
                        item_id=bom_item.item_id
                    ))
                    context.add_error(f"No suitable sheet found for {bom_item.section}{section_suffix}")

        spec.bom_items = new_bom_items


class LockOptionSelectionStep(SpecStep):
    priority = 460

    def process(self, context: SpecContext):
        spec = context.spec
        locking_tags = {'LOCK_OPTION', 'CYLINDER', 'KEY_LOCK', 'WC_LOCK'}
        found = context.consume_customizers(locking_tags)
        gc = found[0] if found else None

        if gc:
            c = gc.customizer
            val = (gc.par1 or c.par1_value or c.tag or "").upper()
            if val.startswith("SKU="):
                val = val[4:]

            tag_str = (c.tag or "").upper()
            item_tags = {t.strip() for t in tag_str.replace(',', ' ').split() if t.strip()}

            if val.startswith("CYLINDER") or "CYLINDER" in item_tags:
                spec.lock_option_type = "צילינדר"
            elif val in ("WC", "WC_LOCK") or "WC_LOCK" in item_tags:
                spec.lock_option_type = "תפוס/פנוי"
            elif val in ("KEY", "KEY_LOCK") or "KEY_LOCK" in item_tags:
                spec.lock_option_type = "מפתח אפס"
            elif val in ("NONE", "WITHOUT_LOCK"):
                spec.lock_option_type = "ללא"
            else:
                spec.lock_option_type = "צילינדר"
        else:
            if not spec.lock_option_type:
                spec.lock_option_type = "תפוס/פנוי"


class SandwichAndFrameStep(SpecStep):
    priority = 520
    important_for_phase1 = False

    def process(self, context: SpecContext):
        spec = context.spec
        if not getattr(spec, 'has_door', True) or getattr(context, 'phase', None) == 'phase1':
            return

        bom = getattr(context.product, 'effective_bom', None) or getattr(context.product, 'bom', None)
        if not bom:
            return

        puzzle_spec = DoorPuzzleSpec()
        prototypes = {p.code: p for p in PuzzleBlockPrototype.objects.select_related('pattern').all()}

        params = {
            'H': spec.height,
            'W': spec.width,
            'thickness': getattr(bom, 'total_thickness', 40.0)
        }

        # Do not unpack covering preset if door leaf has hidden wood edge
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

        # 1. Evaluate geometry
        x = FormulaEvaluator.evaluate(cfg.get('x', 0), params)
        y = FormulaEvaluator.evaluate(cfg.get('y', 0), params)
        w = FormulaEvaluator.evaluate(cfg.get('w', 0), params)
        h = FormulaEvaluator.evaluate(cfg.get('h', 0), params)

        # 2. Text label formatting
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

        # 3. Fill and border styling
        fill_color = cfg.get('fill_color') or proto.fill_color
        border_color = cfg.get('border_color') or proto.border_color
        border_width = cfg.get('border_width', proto.border_width)
        opacity = cfg.get('opacity', proto.opacity)

        # 4. Label coordinates
        text_x_raw = cfg.get('text_x')
        text_y_raw = cfg.get('text_y')
        text_x = FormulaEvaluator.evaluate(text_x_raw, params) if text_x_raw is not None else round(x + w / 2, 2)
        text_y = FormulaEvaluator.evaluate(text_y_raw, params) if text_y_raw is not None else round(y + h / 2, 2)

        # 5. Highlight custom parameters
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

    @staticmethod
    def _resolve_numeric(val, params: dict) -> float:
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val.format(**params))
            except (KeyError, ValueError):
                pass
        return 0.0


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

            # Собираем введенные параметры кастомизатора
            customizer_params: Dict[str, Any] = {
                'H': float(spec.height or 0),
                'W': float(spec.width or 0),
            }
            params_meta: Dict[str, Dict[str, Any]] = {}
            preset_labels = []

            for i in range(1, 6):
                val_order = getattr(gc, f'par{i}', None)
                val_default = getattr(c, f'par{i}_value', None)
                # Нормализуем строки для точного сравнения
                str_order = str(val_order).strip() if val_order not in (None, '') else ''
                str_default = str(val_default).strip() if val_default not in (None, '') else ''
                # Кастомным считается, если в заказе задано значение, отличное от дефолта
                if str_order != '':
                    val = val_order
                    # Сравниваем как числа, если оба числа, иначе как строки
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

            # Распаковываем блоки пресета в puzzle_spec
            sandwich_step.unpack_preset_blocks(
                blocks_config=blocks_config,
                prototypes=prototypes,
                puzzle_spec=spec.puzzle_spec,
                params=customizer_params,
                labels=preset_labels,
            )

            # Регистрируем пресет для шапки отчета на пресс
            spec.applied_presets.append({
                'name': preset.name,
                'code': getattr(preset, 'code', ''),
                'customizer_name': c.name,
                'labels': preset_labels,
            })


class MeasurerDataStep(SpecStep):
    priority = 600

    def process(self, context: SpecContext):
        spec = context.spec
        if spec.lock_height is not None:
            spec.lock_height_on_frame = spec.lock_height - float(spec.leaf_top_clearance or 0)

        if spec.hinge_heights:
            spec.hinge_heights_on_frame = [
                h - float(spec.leaf_top_clearance or 0)
                for h in spec.hinge_heights
            ]


class TechnicalDataStep(SpecStep):
    priority = 800

    def process(self, context: SpecContext):
        product = context.product
        spec = context.spec
        if product and hasattr(product, 'tech_data'):
            tech_data = product.tech_data
            if tech_data:
                spec.cnc_program = tech_data.cnc_program_name or ""
                spec.tech_notes = tech_data.technical_notes or ""


class MediaStep(SpecStep):
    priority = 900

    def process(self, context: SpecContext):
        item = context.item
        spec = context.spec
        if item.sketch:
            spec.sketch_url = item.sketch.url


class SingleCustomizerStep(SpecStep):
    priority = 1000

    def __init__(self, group_customizer):
        self.group_customizer = group_customizer

    def process(self, context: SpecContext):
        gc = self.group_customizer
        c = gc.customizer
        spec = context.spec
        tag_str = (c.tag or "").upper()
        item_tags = {t.strip() for t in tag_str.replace(',', ' ').split() if t.strip()}

        if c.hardware:
            hardware_list = [c.hardware] + list(c.hardware.components.all())
            for hw in hardware_list:
                spec.bom_items.append(
                    SpecBOMItem(
                        type='hardware',
                        section=tag_str or 'Customizer',
                        item_name=hw.name,
                        quantity=1,
                        tag=tag_str,
                        item_id=hw.id
                    )
                )

        formatted = None
        if item_tags & {'FRAMES_REPORT', 'FRAME_MODIFICATION'}:
            formatted = self._format_customizer(gc)
            spec.frames_report_customizers.append(formatted)

        if item_tags & {'DOORS_REPORT'}:
            if not formatted:
                formatted = self._format_customizer(gc)
            spec.doors_report_customizers.append(formatted)

    @staticmethod
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
                    # Автоматически получаем красивый текст вместо ключа
                    display_val = group_customizer.get_parameter_display_value(i)

                    params.append(SpecCustomizerParam(
                        label=label,
                        value=display_val,
                        is_custom=is_custom
                    ))
        return SpecCustomizerReport(name=c.name, tag=c.tag, params=params)


class SpecPipeline:
    def __init__(self):
        self.steps = [
            BaseItemStep(),
            ProductDataStep(),
            DoubleDoorStep(),
            WoodEdgeStep(),
            PanelDimensionStep(),
            CutSheetsStep(),
            AppearanceStep(),
            FrameResolutionStep(),
            BOMStep(),
            MaterialSelectionStep(),
            LockSelectionStep(),
            LockOptionSelectionStep(),
            HingeSelectionStep(),
            LockPositionStep(),
            HingePositionStep(),
            SandwichAndFrameStep(),
            CustomizerPuzzleStep(),
            MeasurerDataStep(),
            TechnicalDataStep(),
            MediaStep(),
        ]

    def execute(self, item: OrderItem, customizers=None, phase: str = 'phase2') -> ProductionSpec:
        context = SpecContext(item, customizers=customizers, phase=phase)
        all_steps = sorted(self.steps, key=lambda s: getattr(s, 'priority', 9999))

        for step in all_steps:
            # Skip steps not marked for Phase 1
            if phase == 'phase1' and not getattr(step, 'important_for_phase1', True):
                continue

            try:
                step.process(context)
            except PipelineError as e:
                context.add_error(str(e))
            except Exception as e:
                context.add_error(f"Unexpected error in {step.__class__.__name__}: {str(e)}")

        for gc in list(context.unprocessed_customizers):
            try:
                SingleCustomizerStep(gc).process(context)
            except PipelineError as e:
                context.add_error(str(e))
            except Exception as e:
                context.add_error(f"Unexpected error in customizer {gc.customizer.code}: {str(e)}")

        return context.spec


class OrderSpecContext:
    def __init__(self, order, items=None, phase: str = 'phase2'):
        self.order = order
        self.phase = phase
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
            batches={}
        )
        self.data: Dict[str, Any] = {}


class OrderItemsStep(OrderStep):
    def process(self, context: OrderSpecContext):
        group_ids = {item.group_id for item in context.items if item.group_id}
        all_group_customizers = OrderItemsGroupCustomizer.objects.filter(
            group_id__in=group_ids
        ).select_related('customizer', 'customizer__puzzle_mapping__preset').prefetch_related(
            'customizer__hardware__components', 'customizer__materials'
        ).order_by('customizer__tag', 'customizer__code')

        customizers_by_group = collections.defaultdict(list)
        for gc in all_group_customizers:
            customizers_by_group[gc.group_id].append(gc)

        item_pipeline = SpecPipeline()

        # Группируем позиции по номеру партии и наполняем batches
        for item in context.items:
            batch_num = str(item.group.batch_number if (item.group and item.group.batch_number) else 1)
            if batch_num not in context.spec.batches:
                context.spec.batches[batch_num] = []

            group_customizers = customizers_by_group.get(item.group_id, [])
            item_spec = item_pipeline.execute(item, customizers=group_customizers, phase=context.phase)
            context.spec.batches[batch_num].append(item_spec)


class OrderHeaderStep(OrderStep):
    """
    Step 1: Maps raw Order model fields into OrderHeaderSpec schema.
    """

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
            OrderHeaderStep(),  # 1. Header mapping
            OrderItemsStep(),  # 2. Door items processing
        ]

    def execute(self, order, items=None, phase: str = 'phase2') -> OrderSpec:
        context = OrderSpecContext(order, items, phase=phase)
        for step in self.steps:
            step.process(context)
        return context.spec
