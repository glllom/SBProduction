import math
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod

from .schemas import (
    ProductionSpec, SpecBOMItem, SpecCustomizerParam, SpecCustomizerReport,
    OrderHeaderSpec, OrderSpec
)
from .models import BOM, LockStandardHeight, HingeStandardHeight
from .bom_calculator import BOMCalculator

class SpecContext:
    def __init__(self, item):
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

class SpecStep(ABC):
    @abstractmethod
    def process(self, context: SpecContext):
        pass

class BaseItemStep(SpecStep):
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

class AppearanceStep(SpecStep):
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
            'customizers': {} # Future expansion
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
        
        # Frame type from first BOM if exists
        bom_first = BOM.objects.filter(product=product).first()
        if bom_first and bom_first.frame:
            spec.frame = bom_first.frame.name
            
        # Store bom_result in context data for subsequent steps (HardwareStep)
        context.data['bom_result'] = bom_result

class HardwareStep(SpecStep):
    def process(self, context: SpecContext):
        item = context.item
        spec = context.spec
        bom_result = context.data.get('bom_result', [])
        
        # Find hardware in BOM
        lock_bom = next((b for b in bom_result if b.get('tag') == 'Lock'), None)
        hinge_bom = next((b for b in bom_result if b.get('tag') == 'hinge'), None)
        
        lock_item = lock_bom['item'] if lock_bom else None
        hinge_item = hinge_bom['item'] if hinge_bom else None
        
        spec.lock_name = lock_item.name if lock_item else "N/A"
        spec.hinge_name = hinge_item.name if hinge_item else "N/A"
        
        # Calculate heights
        spec.lock_height = self._get_effective_lock_height(item, lock_item)
        spec.hinge_heights = self._get_effective_hinge_heights(item, hinge_item)

    def _get_effective_lock_height(self, item, lock_hardware) -> Optional[float]:
        if item.custom_lock_height:
            return float(item.custom_lock_height)
        if not lock_hardware or not item.group.product:
            return None
        std = LockStandardHeight.objects.filter(
            product_families=item.group.product.product_family,
            lock=lock_hardware
        ).first()
        if not std:
            return None
        door_h = float(item.height or 0)
        base_h = float(std.base_door_height)
        base_lock = float(std.base_lock_height)
        step = float(std.step)
        if step == 0:
            return base_lock
        diff = door_h - base_h
        intervals = math.ceil(diff / step)
        return base_lock + intervals * step

    def _get_effective_hinge_heights(self, item, hinge_hardware) -> List[float]:
        custom_hinges = [
            float(getattr(item, f'custom_hinge{i}'))
            for i in range(1, 6)
            if getattr(item, f'custom_hinge{i}')
        ]
        if custom_hinges:
            return custom_hinges
        if not hinge_hardware or not item.group.product:
            return []
        door_h = float(item.height or 0)
        std = HingeStandardHeight.objects.filter(
            product_families=item.group.product.product_family,
            hinge=hinge_hardware,
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

class TechnicalDataStep(SpecStep):
    def process(self, context: SpecContext):
        product = context.product
        spec = context.spec
        if product and hasattr(product, 'tech_data'):
            tech_data = product.tech_data
            if tech_data:
                spec.cnc_program = tech_data.cnc_program_name or ""
                spec.tech_notes = tech_data.technical_notes or ""

class MediaStep(SpecStep):
    def process(self, context: SpecContext):
        item = context.item
        spec = context.spec
        if item.sketch:
            spec.sketch_url = item.sketch.url

class CustomizerStep(SpecStep):
    def process(self, context: SpecContext):
        group = context.group
        spec = context.spec
        
        if not group:
            return

        group_customizers = group.customizers.select_related('customizer').order_by(
            'customizer__strategy', 'customizer__priority'
        )

        from collections import defaultdict
        strategy_map = defaultdict(list)
        for gc in group_customizers:
            strategy_map[gc.customizer.strategy].append(gc)

        # Execute strategies 1..10
        for s_num in range(1, 11):
            gcs = strategy_map.get(s_num, [])
            if s_num == 10:
                for gc in gcs:
                    spec.frames_report_customizers.append(self._format_customizer(gc))
            else:
                # Strategies 1-9 placeholders
                for gc in gcs:
                    pass

    def _format_customizer(self, group_customizer) -> SpecCustomizerReport:
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
    def __init__(self, steps: List[SpecStep] = None):
        self.steps = steps or [
            BaseItemStep(),
            ProductDataStep(),
            AppearanceStep(),
            BOMStep(),
            HardwareStep(),
            TechnicalDataStep(),
            MediaStep(),
            CustomizerStep(),
        ]

    def execute(self, item) -> ProductionSpec:
        context = SpecContext(item)
        for step in self.steps:
            step.process(context)
        return context.spec


class OrderSpecContext:
    def __init__(self, order, items=None):
        self.order = order
        # If items are not provided, we might want to take all items from the order groups
        if items is None:
            from .models import OrderItem
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
        """
        item_pipeline = SpecPipeline()
        for item in context.items:
            item_spec = item_pipeline.execute(item)
            context.spec.items.append(item_spec)


class OrderSpecPipeline:
    """
    Pipeline for forming a complete specification for the entire order.
    To add new processing steps, include them in the steps list.
    """
    def __init__(self, steps: List[OrderStep] = None):
        self.steps = steps or [
            OrderHeaderStep(),
            OrderItemsStep(),
        ]

    def execute(self, order, items=None) -> OrderSpec:
        context = OrderSpecContext(order, items)
        for step in self.steps:
            step.process(context)
        return context.spec
