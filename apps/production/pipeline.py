import collections
import math
from abc import ABC, abstractmethod
from typing import List, Optional

from apps.orders.models import OrderItem
from .bom_calculator import BOMCalculator
from .models import BOM, LockStandardHeight, HingeStandardHeight
from .schemas import (
    ProductionSpec, SpecBOMItem, SpecCustomizerParam, SpecCustomizerReport,
    OrderHeaderSpec, OrderSpec
)


class PipelineError(Exception):
    """Base class for pipeline errors that should be collected and shown to the user."""
    pass


class SpecContext:
    def __init__(self, item, customizers=None):
        self.item = item
        self.group = item.group
        self.order = self.group.order
        self.product = self.group.product
        self.spec = ProductionSpec(
            item_id=item.id,
            mark=item.mark or ""
        )
        # Shared transient data between steps
        self.data = {}

        # Optimized customizers loading
        if customizers is not None:
            self.customizers = customizers
        else:
            if self.group:
                self.customizers = list(self.group.customizers.select_related('customizer').prefetch_related(
                    'customizer__hardware__components', 'customizer__materials'
                ).order_by('customizer__tag', 'customizer__code'))
            else:
                self.customizers = []

        # Track processed customizers
        self.unprocessed_customizers = list(self.customizers)
        self.processed_customizers = []

    def add_error(self, message: str):
        self.spec.errors.append(message)

    def consume_customizers(self, tags) -> List:
        """
        Finds customizers by tag(s), moves them to processed, and returns them.
        """
        if isinstance(tags, str):
            tags_set = {tags.upper()}
        else:
            tags_set = {t.upper() for t in tags}

        found = []
        remaining = []
        for gc in self.unprocessed_customizers:
            tag = (gc.customizer.tag or "").upper()
            if tag in tags_set:
                found.append(gc)
                self.processed_customizers.append(gc)
            else:
                remaining.append(gc)

        self.unprocessed_customizers = remaining
        return found


class SpecStep(ABC):
    priority: int = 0

    @abstractmethod
    def process(self, context: SpecContext):
        pass


class BaseItemStep(SpecStep):
    priority = 100

    def process(self, context: SpecContext):
        item = context.item
        spec = context.spec
        spec.place = item.place or ""
        spec.comment = item.comment or ""
        spec.height = float(item.height or 0)
        spec.width = float(item.width or 0)
        spec.wall = float(item.wall or 0)
        spec.addition_cut = float(item.addition_cut) if item.addition_cut else None

        spec.direction_code = item.direction or ""
        spec.opening_code = item.opening or ""
        spec.direction = item.get_direction_display() if item.direction else ""
        spec.opening = item.get_opening_display() if item.opening else ""


class ProductDataStep(SpecStep):
    priority = 200

    def process(self, context: SpecContext):
        product = context.product
        spec = context.spec
        if product:
            spec.product_name = product.name
            spec.product_code = product.code
            if product.product_family:
                spec.product_family = product.product_family.name
                if not spec.series and product.series:
                    spec.series = product.series.name

                if product.product_family.product_type:
                    spec.has_door = product.product_family.product_type.has_door
                    spec.has_frame = product.product_family.product_type.has_frame


class AppearanceStep(SpecStep):
    priority = 300

    def process(self, context: SpecContext):
        group = context.group
        order = context.order
        spec = context.spec

        # Series
        if group.series:
            spec.series = group.series.name
        elif order and order.series:
            spec.series = order.series.name

        # Front
        if group.front:
            spec.front_name = group.front.name
        elif order and order.front:
            spec.front_name = order.front.name

        # Colors
        spec.color_panels = group.color_panels or ""
        spec.color_frames = group.color_frames or ""
        spec.panel_paint_option = group.panel_paint_option
        spec.frame_paint_option = group.frame_paint_option
        spec.basic_color_frames = str(group.basic_color_frames) if group.basic_color_frames else ""

        # Handle
        if order and order.handle:
            spec.handle_name = order.handle.name


class BOMStep(SpecStep):
    priority = 400

    def process(self, context: SpecContext):
        item = context.item
        group = context.group
        product = context.product
        spec = context.spec

        if not product:
            return

        # Prepare context for BOM calculator
        calc_context = {
            'H': float(item.height or 0),
            'W': float(item.width or 0),
            'wall': float(item.wall or 0),
            'basic_color_frames': group.basic_color_frames,
            'customizers': {}  # Future expansion
        }

        calc = BOMCalculator(calc_context)
        bom_result = calc.calculate_for_product(product)

        # Convert to Pydantic models
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

        # Frame type from first BOM if exists
        bom_first = BOM.objects.filter(product=product).first()
        if bom_first and bom_first.frame:
            spec.frame = bom_first.frame.name

        # Store bom_result in context data for later steps (HardwareStep)
        context.data['bom_result'] = bom_result


""" new classes"""


class LockSelectionStep(SpecStep):
    """
    Универсальный шаг применения кастомизаторов замка (Priority 450).
    Связывается с кастомизатором через tag == 'LOCK_SELECTION'.
    """
    priority = 450

    def process(self, context: SpecContext):
        spec = context.spec

        # Используем оптимизированный метод из контекста
        group_customizers = context.consume_customizers('LOCK')

        for gc in group_customizers:
            c = gc.customizer
            main_hw = c.hardware

            if main_hw:
                # 1. Формируем список комплектующих (основной + вложенные)
                hardware_list = [main_hw] + list(main_hw.components.all())

                # 2. Затираем все предыдущие позиции с тэгом Lock
                spec.bom_items = [item for item in spec.bom_items if item.tag != 'Lock']

                # 3. Первым элементом ВСЕГДА идет целевой замок
                spec.lock_id = main_hw.id
                spec.lock_name = main_hw.name
                spec.lock_height = 0

                # 4. Вставляем все элементы комплекта в BOM спецификации
                for hw in hardware_list:
                    spec.bom_items.append(
                        SpecBOMItem(
                            type='hardware',
                            section='Lock',
                            item_name=hw.name,
                            quantity=1,
                            tag='Lock',
                            item_id=hw.id
                        )
                    )
            # 2. Задание кастомной высоты (если указана)
            custom_h = self._extract_custom_height(gc)
            if custom_h > 0:
                context.data['override_lock_height'] = custom_h

    @staticmethod
    def _extract_custom_height(group_customizer) -> Optional[float]:
        """
        Извлекает значение высоты из par1 (или par1_value кастомизатора).
        """
        c = group_customizer.customizer
        val = group_customizer.par1 or c.par1_value

        if val:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return 0


class LockOptionSelectionStep(SpecStep):
    priority = 460

    def process(self, context: SpecContext):
        spec = context.spec

        # Retrieve the active locking customizer
        locking_tags = {'LOCK_OPTION', 'CYLINDER', 'KEY_LOCK', 'WC_LOCK'}
        found = context.consume_customizers(locking_tags)
        gc = found[0] if found else None

        if gc:
            c = gc.customizer
            # Read the effective option key
            # prioritize group_customizer.par1, falling back to customizer.par1_value, then customizer.tag
            val = (gc.par1 or c.par1_value or c.tag or "").upper()

            # Strip routing prefixes
            if val.startswith("SKU="):
                val = val[4:]
            elif val.startswith("SKU:"):
                val = val[4:]
            elif val.startswith("VAL:"):
                val = val[4:]

            tag = (c.tag or "").upper()

            # Set spec.cylinder_type based on the resolved value
            if val.startswith("CYLINDER") or tag == "CYLINDER":
                spec.cylinder_type = "צילינדר"
            elif val in ("WC", "WC_LOCK") or tag == "WC_LOCK":
                spec.cylinder_type = "תפוס/פנוי"
            elif val in ("KEY", "KEY_LOCK") or tag == "KEY_LOCK":
                spec.cylinder_type = "מפתח אפס"
            elif val in ("NONE", "WITHOUT_LOCK"):
                spec.cylinder_type = "ללא"
            else:
                # Warehouse SKU patterns (default fallback for custom cylinder options)
                spec.cylinder_type = "צילינדר"

            # Update BOM (Maintain placeholder)
            self._update_cylinder_bom(spec, c)
        else:
            # If no locking customizer provided, retain default behavior
            if not spec.cylinder_type:
                spec.cylinder_type = "תפוס/פנוי"

    @staticmethod
    def _update_cylinder_bom(spec, customizer):
        """
        Обновляет BOM в соответствии с выбранным кастомизатором цилиндра.
        (Заглушка для предотвращения ошибок вызова)
        """
        pass


class HingeSelectionStep(SpecStep):
    """
    Шаг применения кастомизаторов петель (Priority 470).
    Связывается с кастомизатором через tag == 'HINGE'.
    """
    priority = 470

    def process(self, context: SpecContext):
        spec = context.spec
        group_customizers = context.consume_customizers('HINGE')

        for gc in group_customizers:
            c = gc.customizer
            main_hw = c.hardware

            if main_hw:
                # 1. Формируем список комплектующих
                hardware_list = [main_hw] + list(main_hw.components.all())

                # 2. Затираем все предыдущие позиции с тэгом hinge
                spec.bom_items = [item for item in spec.bom_items if item.tag != 'hinge']

                # 3. Устанавливаем имя петли
                spec.hinge_name = main_hw.name

                # Сохраняем ID основной петли для поиска стандартов
                context.data['hinge_hardware_id'] = main_hw.id

                # 4. Вставляем все элементы комплекта в BOM
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

            # Извлечение кастомных высот
            custom_heights = self._extract_custom_heights(gc)
            if custom_heights:
                context.data['override_hinge_heights'] = custom_heights

    @staticmethod
    def _extract_custom_heights(group_customizer) -> List[float]:
        c = group_customizer.customizer
        res = []
        for i in range(1, 6):
            val = getattr(group_customizer, f'par{i}') or getattr(c, f'par{i}_value')
            if val:
                try:
                    res.append(float(val))
                except (ValueError, TypeError):
                    pass
        return res


class LockPositionStep(SpecStep):
    """
    Рассчитывает финальную позицию (высоту врезки) замка (Priority 500).
    Запускается ПОСЛЕ всех шагов подбора замков (LockSelectionStep).
    """
    priority = 500

    def process(self, context: SpecContext):
        item = context.item
        spec = context.spec

        # 1. Если замок отсутствует или выбран "ללא מנעול" — высота не нужна
        if spec.lock_id is None:
            return

        # 2. Переопределение высоты из кастомизатора (если было записано в context.data)
        effective_height = None

        # 1. НАИВЫСШИЙ ПРИОРИТЕТ: Прямой замер замерщика из OrderItem
        if item.custom_lock_height:
            try:
                val = float(item.custom_lock_height)
                if val > 0:
                    effective_height = val
            except (ValueError, TypeError):
                pass

        # 2. ВТОРОЙ ПРИОРИТЕТ: Кастомная высота из кастомизатора (если зафиксирована в context.data)
        if effective_height is None:
            override_h = context.data.get('override_lock_height') or 0
            if override_h and override_h > 0:
                effective_height = override_h

        # 3. ФОЛЛБЭК: Расчет по нормативной таблице стандартов
        if effective_height is None:
            effective_height = self._get_effective_lock_height(item, spec.lock_id)

        # Сохраняем финальный результат
        if effective_height is None or effective_height <= 0:
            raise PipelineError(f"Lock height could not be determined for lock ID {spec.lock_id}")
            
        spec.lock_height = effective_height

    @staticmethod
    def _get_effective_lock_height(item: OrderItem, lock_id: int) -> float:
        product = getattr(item.group, 'product', None)
        if not product or not product.product_family or not lock_id:
            return 0.0

        # Ищем запись стандартов для семейства продуктов и конкретного lock_id
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
        intervals = math.ceil(diff / step)

        # Финальная высота по формуле из модели
        calculated_height = base_lock + (intervals * step)

        return float(calculated_height)


class HingePositionStep(SpecStep):
    """
    Рассчитывает финальные позиции (высоты врезки) петель (Priority 510).
    """
    priority = 510

    def process(self, context: SpecContext):
        item = context.item
        spec = context.spec

        # 1. ПРИОРИТЕТ 1: Прямые замеры из OrderItem
        custom_hinges = [
            float(getattr(item, f'custom_hinge{i}'))
            for i in range(1, 6)
            if getattr(item, f'custom_hinge{i}')
        ]
        if custom_hinges:
            spec.hinge_heights = custom_hinges
            return

        # 2. ПРИОРИТЕТ 2: Кастомные высоты из кастомизатора
        override_heights = context.data.get('override_hinge_heights')
        if isinstance(override_heights, list):
            # Важно: если в кастомизаторе указаны высоты, затираем все старые значения
            spec.hinge_heights = [float(h) for h in override_heights]
            return

        # 3. ФОЛЛБЭК: Расчет по нормативной таблице
        hinge_id = context.data.get('hinge_hardware_id')

        if not hinge_id:
            # Ищем в BOM (если кастомизатора не было)
            hinge_bi = next((bi for bi in spec.bom_items if bi.tag == 'hinge'), None)
            if hinge_bi:
                hinge_id = hinge_bi.item_id

        if hinge_id:
            heights = self._get_std_hinge_heights(item, hinge_id)
            if not heights:
                raise PipelineError(f"Standard hinge heights not found for hinge ID {hinge_id} and door height {item.height}")
            spec.hinge_heights = heights
        else:
            # Если нет hinge_id, но это дверь - возможно тоже ошибка? 
            # Пока оставим как есть, возможно петли не предусмотрены продуктом.
            pass

    @staticmethod
    def _get_std_hinge_heights(item: OrderItem, hinge_id: int) -> List[float]:
        product = getattr(item.group, 'product', None)
        if not product or not product.product_family or not hinge_id:
            return []

        door_h = float(item.height or 0)
        std = HingeStandardHeight.objects.filter(
            product_families=product.product_family,
            hinges__id=hinge_id,
            min_height__lte=door_h,
            max_height__gte=door_h
        ).first()

        if not std:
            return []

        res = []
        for i in range(1, 6):
            val = getattr(std, f'value{i}')
            if val:
                res.append(float(val))
        return res


class HardwareStep(SpecStep):
    priority = 500

    def process(self, context: SpecContext):
        spec = context.spec
        bom_result = context.data.get('bom_result') or []

        # Find hardware in BOM
        lock_bom = next((b for b in bom_result if isinstance(b, dict) and b.get('tag') == 'Lock'), None)
        hinge_bom = next((b for b in bom_result if isinstance(b, dict) and b.get('tag') == 'hinge'), None)

        lock_item = lock_bom.get('item') if lock_bom else None
        hinge_item = hinge_bom.get('item') if hinge_bom else None

        spec.lock_name = lock_item.name if lock_item else "N/A"
        spec.hinge_name = hinge_item.name if hinge_item else "N/A"


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
    """
    Wraps a single customizer into a pipeline step.
    The tag determines processing logic and priority.
    """
    priority = 1000

    def __init__(self, group_customizer):
        self.group_customizer = group_customizer
        # Default priority is 1000, can be overridden by specific tags if needed

    def process(self, context: SpecContext):
        gc = self.group_customizer
        c = gc.customizer
        spec = context.spec
        tag = (c.tag or "").upper()

        # Handle warehouse hardware linkage (including components)
        if c.hardware:
            hardware_list = [c.hardware] + list(c.hardware.components.all())
            for hw in hardware_list:
                spec.bom_items.append(
                    SpecBOMItem(
                        type='hardware',
                        section=tag or 'Customizer',
                        item_name=hw.name,
                        quantity=1,
                        tag=tag,
                        item_id=hw.id
                    )
                )

        # Tag-based strategy logic
        if tag == 'FRAMES_REPORT':
            spec.frames_report_customizers.append(self._format_customizer(gc))
        else:
            # Other tag-based strategies placeholders
            pass

    @staticmethod
    def _format_customizer(group_customizer) -> SpecCustomizerReport:
        c = group_customizer.customizer
        params = []
        for i in range(1, 5):
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
                    params.append(SpecCustomizerParam(
                        label=label,
                        value=val,
                        is_custom=is_custom
                    ))
        return SpecCustomizerReport(name=c.name, params=params)


class SpecPipeline:
    def __init__(self):
        self.steps = [
            BaseItemStep(),
            ProductDataStep(),
            AppearanceStep(),
            BOMStep(),
            LockSelectionStep(),
            LockOptionSelectionStep(),
            HingeSelectionStep(),
            LockPositionStep(),
            HingePositionStep(),
            TechnicalDataStep(),
            MediaStep(),
        ]

    def execute(self, item, customizers=None) -> ProductionSpec:
        context = SpecContext(item, customizers=customizers)

        # Build the final list of steps
        all_steps = list(self.steps)

        # Sort everything by priority
        all_steps.sort(key=lambda s: getattr(s, 'priority', 9999))

        for step in all_steps:
            try:
                step.process(context)
            except PipelineError as e:
                context.add_error(str(e))
            except Exception as e:
                # Log unexpected errors as well
                context.add_error(f"Unexpected error in {step.__class__.__name__}: {str(e)}")

        # После всех специализированных шагов обрабатываем оставшиеся кастомизаторы
        # (те, что не были "потреблены" шагами типа LockSelectionStep)
        remaining = list(context.unprocessed_customizers)
        for gc in remaining:
            try:
                SingleCustomizerStep(gc).process(context)
            except PipelineError as e:
                context.add_error(str(e))
            except Exception as e:
                context.add_error(f"Unexpected error in customizer {gc.customizer.code}: {str(e)}")

        return context.spec


class OrderSpecContext:
    def __init__(self, order, items=None, phase='phase1'):
        self.order = order
        self.phase = phase
        # If items are not provided, we might want to take all items from the order groups
        if items is None:
            self.items = OrderItem.objects.filter(group__order=order)
        else:
            self.items = items

        self.spec = OrderSpec(
            order=OrderHeaderSpec(
                number=str(order.order_number or ""),
                customer=order.customer or "",
                status=order.status
            ),
            items=[]
        )
        # Shared transient data between order-level steps
        self.data = {}


class OrderStep(ABC):
    @abstractmethod
    def process(self, context: OrderSpecContext):
        """
        Perform a step in the order specification pipeline.
        This is where you can manually add calculation and substitution operations.
        """
        pass


class OrderHeaderStep(OrderStep):
    def process(self, context: OrderSpecContext):
        """
        Updates the order header information.
        """
        # Example of manual calculation/substitution
        # context.spec.order.customer = context.order.customer.upper()
        pass


class OrderItemsStep(OrderStep):
    def process(self, context: OrderSpecContext):
        """
        Processes each item in the order using the SpecPipeline.
        Optimized by preloading all group customizers.
        """
        from apps.orders.models import OrderItemsGroupCustomizer

        # Собираем ID всех групп в заказе
        group_ids = {item.group_id for item in context.items if item.group_id}

        # Предварительно загружаем все кастомизаторы для этих групп одним запросом
        all_group_customizers = OrderItemsGroupCustomizer.objects.filter(
            group_id__in=group_ids
        ).select_related('customizer').prefetch_related(
            'customizer__hardware__components', 'customizer__materials'
        ).order_by('customizer__tag', 'customizer__code')

        # Группируем кастомизаторы по group_id для быстрого доступа
        customizers_by_group = collections.defaultdict(list)
        for gc in all_group_customizers:
            customizers_by_group[gc.group_id].append(gc)

        item_pipeline = SpecPipeline()
        for item in context.items:
            group_customizers = customizers_by_group.get(item.group_id, [])
            item_spec = item_pipeline.execute(item, customizers=group_customizers)
            context.spec.items.append(item_spec)


class OrderSpecPipeline:
    """
    Pipeline for forming a complete specification for the entire order.
    To add new processing steps, include them in the step list.
    """

    def __init__(self, steps: Optional[List[OrderStep]] = None):
        self.steps = steps or [
            OrderHeaderStep(),
            OrderItemsStep(),
        ]

    def execute(self, order, items=None, phase='phase1') -> OrderSpec:
        context = OrderSpecContext(order, items, phase=phase)
        for step in self.steps:
            step.process(context)
        return context.spec

    def execute_for_order(self, order, phase='phase1') -> OrderSpec:
        """Alias for executing to match architectural specification."""
        return self.execute(order, phase=phase)
