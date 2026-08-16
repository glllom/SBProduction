import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from decimal import Decimal
from django.db import models
from .models import BOM, ProductTechnicalData, LockStandardHeight, HingeStandardHeight
from apps.orders.models import OrderItem, OrderStatus

@dataclass
class TechnicalSpec:
    """
    Полная техническая спецификация для конкретного изделия в заказе.
    Используется для генерации отчетов, техзаданий и передачи данных на производство.
    """
    item_id: int
    mark: str
    product_name: str
    product_code: str
    
    # Геометрия
    height: float
    width: float
    wall: float
    
    # Параметры открывания
    direction: str
    opening: str
    
    # Внешний вид
    front_name: str
    color_panels: str
    color_frames: str
    handle_name: str
    
    # Технические данные (из ProductTechnicalData)
    cnc_program: str
    tech_notes: str
    
    # Фурнитура и присадки
    lock_name: str
    lock_height: Optional[float]
    hinge_name: str
    hinge_heights: List[float]
    
    # Спецификация материалов (BOM)
    bom_items: List[Dict[str, Any]] = field(default_factory=list)
    profiles: List[str] = field(default_factory=list)
    
    # Дополнительно
    place: str = ""
    comment: str = ""
    sketch_url: str = ""

class TechnicalSpecService:
    """
    Сервис для формирования и валидации технической спецификации изделия.
    """
    
    @staticmethod
    def validate(item: OrderItem) -> List[str]:
        """
        Проверяет, достаточно ли данных для формирования спецификации.
        Возвращает список ошибок.
        """
        errors = []
        if not item.height: errors.append(f"Позиция {item.mark}: Не указана высота")
        if not item.width: errors.append(f"Позиция {item.mark}: Не указана ширина")
        
        group = item.group
        if not group.product: errors.append(f"Позиция {item.mark}: Не указана модель изделия")
        
        # Можно добавить проверку наличия BOM или техданных, если они обязательны
        return errors

    @staticmethod
    def get_effective_lock_height(item: OrderItem, lock_hardware) -> Optional[float]:
        if item.custom_lock_height:
            return float(item.custom_lock_height)
        
        if not lock_hardware:
            return None
            
        # Find standard height for this family and lock
        std = LockStandardHeight.objects.filter(
            product_families=item.group.product.product_family,
            lock=lock_hardware
        ).first()
        
        if not std:
            return None
            
        # Calculation: value = base_lock_height + ceil((door_height - base_door_height) / step) * step
        door_h = float(item.height or 0)
        base_h = float(std.base_door_height)
        base_lock = float(std.base_lock_height)
        step = float(std.step)
        
        if step == 0:
            return base_lock
            
        diff = door_h - base_h
        intervals = math.ceil(diff / step)
        return base_lock + intervals * step

    @staticmethod
    def get_effective_hinge_heights(item: OrderItem, hinge_hardware) -> List[float]:
        custom_hinges = [
            float(getattr(item, f'custom_hinge{i}')) 
            for i in range(1, 6) 
            if getattr(item, f'custom_hinge{i}')
        ]
        
        if custom_hinges:
            return custom_hinges
            
        if not hinge_hardware:
            return []
            
        # Find standard heights
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

    @classmethod
    def build_spec(cls, item: OrderItem) -> TechnicalSpec:
        """
        Собирает все данные и возвращает экземпляр TechnicalSpec.
        """
        group = item.group
        order = group.order
        product = group.product
        
        # Получаем техданные продукта
        tech_data = getattr(product, 'tech_data', None)
        
        # Рассчитываем BOM
        calc = BOMCalculator({
            'H': float(item.height or 0),
            'W': float(item.width or 0),
            'wall': float(item.wall or 0),
            'customizers': {} # Можно расширить в будущем
        })
        bom_result = calc.calculate_for_product(product)
        
        # Извлекаем фурнитуру из BOM для информации в спеке
        lock_item = next((b for b in bom_result if b.get('tag') == 'Lock'), None)
        hinge_item = next((b for b in bom_result if b.get('tag') == 'hinge'), None)
        
        lock_name = lock_item['item'].name if lock_item else "N/A"
        hinge_name = hinge_item['item'].name if hinge_item else "N/A"
        
        # Calculate effective heights
        lock_height = cls.get_effective_lock_height(item, lock_item['item'] if lock_item else None)
        hinge_heights = cls.get_effective_hinge_heights(item, hinge_item['item'] if hinge_item else None)
        
        # Extract profiles
        profiles = [
            b['item'].name for b in bom_result 
            if b.get('tag') in ['profile1', 'profile2', 'profile3']
        ]

        return TechnicalSpec(
            item_id=item.id,
            mark=item.mark or "",
            product_name=product.name,
            product_code=product.code,
            height=float(item.height or 0),
            width=float(item.width or 0),
            wall=float(item.wall or 0),
            direction=item.get_direction_display() if item.direction else "",
            opening=item.get_opening_display() if item.opening else "",
            front_name=group.front.name if group.front else (order.front.name if order.front else ""),
            color_panels=group.color_panels or "",
            color_frames=group.color_frames or "",
            handle_name=order.handle.name if order.handle else "",
            cnc_program=tech_data.cnc_program_name if tech_data else "",
            tech_notes=tech_data.technical_notes if tech_data else "",
            lock_name=lock_name,
            lock_height=lock_height,
            hinge_name=hinge_name,
            hinge_heights=hinge_heights,
            bom_items=bom_result,
            profiles=profiles,
            place=item.place or "",
            comment=item.comment or "",
            sketch_url=item.sketch.url if item.sketch else ""
        )

class BOMCalculator:
    """
    Service for dynamic Bill of Materials (BOM) calculation.
    Supports fixed-slot materials, categorized hardware, and nested BOMs.
    """
    def __init__(self, context=None):
        """
        :param context: Dict containing variables like 'H', 'W', 'D' 
                       and 'customizers' (dict of tags/values).
        """
        self.context = context or {}

    def _evaluate(self, formula):
        try:
            # Basic context
            safe_context = {
                'H': float(self.context.get('H', 0)),
                'W': float(self.context.get('W', 0)),
                'D': float(self.context.get('D', 0)),
                'wall': float(self.context.get('wall', 0)),
                'math': math,
            }
            # Add customizers
            if 'customizers' in self.context:
                safe_context.update(self.context['customizers'])
            
            # Simple eval
            return eval(formula, {"__builtins__": None}, safe_context)
        except Exception:
            return 0

    def calculate_for_product(self, product, quantity=1):
        """
        Recursively calculates BOM for a product based on the structured BOM model.
        """
        try:
            bom = product.bom
        except Exception: # RelatedObjectDoesNotExist
            return []

        bom_result = []
        
        # 1. Process Material Slots
        material_slots = [
            ('covering', 'כיסוי'), ('base', 'בסיס'), ('filling', 'מילוי'),
            ('casing', 'הלבשה'), ('frame', 'משקוף'), ('profile1', 'פרופיל 1'),
            ('profile2', 'פרופיל 2'), ('profile3', 'פרופיל 3'), ('other1', 'אחר 1'),
            ('other2', 'אחר 2'), ('other3', 'אחר 3'), ('other4', 'אחר 4'),
            ('other5', 'אחר 5')
        ]

        for slot_name, label in material_slots:
            material = getattr(bom, slot_name)
            if material:
                formula = getattr(bom, f"{slot_name}_consumption")
                local_qty = self._evaluate(formula)
                total_qty = local_qty * quantity
                if total_qty > 0:
                    bom_result.append({
                        'type': 'material',
                        'section': label,
                        'item': material,
                        'quantity': total_qty,
                        'tag': slot_name # For backward compatibility or extra identification
                    })

        # 2. Process Hardware M2M Slots
        hardware_slots = [
            ('lock', 'מנעול', 'Lock'), 
            ('hinges', 'צירים', 'hinge'), 
            ('additional', 'תוספות', 'additional')
        ]
        for slot_name, label, tag in hardware_slots:
            hardware_queryset = getattr(bom, slot_name).all()
            for hw in hardware_queryset:
                bom_result.append({
                    'type': 'hardware',
                    'section': label,
                    'item': hw,
                    'tag': tag,
                    'quantity': 1 * quantity # Default to 1 per unit
                })

        # 3. Process Nested BOMs
        for nested_bom in bom.nested_boms.all():
            # Recurse using the product of the nested BOM
            nested_results = self.calculate_for_product(nested_bom.product, quantity=quantity)
            bom_result.extend(nested_results)

        return bom_result


import os
import zipfile
import io
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.utils import timezone
from apps.orders.models import OrderStatus

class ProductionDataService:
    class ReportType(models.TextChoices):
        PHASE1_FRAMES = 'PHASE1_FRAMES', 'משקופים שלב א'
        PHASE2_DOORS = 'PHASE2_DOORS', 'דלתות שלב ב'
        PHASE2_PRESS = 'PHASE2_PRESS', 'פרס'
        PHASE2_FRAMES = 'PHASE2_FRAMES', 'משקופים'
        FULL_PRODUCTION = 'FULL_PRODUCTION', 'דו"ח ייצור מלא'

    def __init__(self, order):
        self.order = order

    def generate_production_zip(self):
        print("Generating production zip")
        buffer = io.BytesIO()
        has_split = self.order.has_split_installation
        
        with zipfile.ZipFile(buffer, 'w') as zip_file:
            if has_split and self.order.status == OrderStatus.PHASE1_PRODUCTION:
                # Only Phase 1 report
                report_content = self.generate_report_html(self.ReportType.PHASE1_FRAMES)
                zip_file.writestr(f"Order_{self.order.order_number}_PhaseA_Frames.html", report_content)
            elif self.order.status in [OrderStatus.IN_PRODUCTION, OrderStatus.PHASE1_READY]:
                # Reports for doors, press and frames
                for rt in [self.ReportType.PHASE2_DOORS, self.ReportType.PHASE2_PRESS, self.ReportType.PHASE2_FRAMES]:
                    report_content = self.generate_report_html(rt)
                    zip_file.writestr(f"Order_{self.order.order_number}_{rt.name}.html", report_content)
            else:
                # DRAFT etc - just full report if any
                report_content = self.generate_report_html(self.ReportType.FULL_PRODUCTION)
                zip_file.writestr(f"Order_{self.order.order_number}_Full.html", report_content)

            # Generate CNC files into zip
            self._add_cnc_files_to_zip(zip_file)

        buffer.seek(0)
        return buffer

    def _add_cnc_files_to_zip(self, zip_file):
        """Internal helper to add CNC files to the zip buffer"""
        is_phase_a = self.order.status == OrderStatus.PHASE1_PRODUCTION
        order_data = self._get_order_data() # Gets all for CNC
        
        for group_data in order_data:
            for spec in group_data['items_specs']:
                folder_name = f"{self.order.order_number}/{spec.mark}"
                for i in range(1, 5):
                    xml_content = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<root>\n  <order_number>{self.order.order_number}</order_number>\n  <item_mark>{spec.mark}</item_mark>\n  <file_number>{i}</file_number>\n  <status>{'Phase A' if is_phase_a else 'Full Production'}</status>\n</root>"
                    zip_file.writestr(f"{folder_name}/file_{i}.xml", xml_content)

    def generate_cnc_files(self):
        """
        Standalone method to generate CNC files. 
        In a real system, this would write to a network share or cloud storage.
        For now, we can log the action or prepare data.
        """
        print(f"Generating CNC XML files for Order {self.order.order_number}")
        # Implementation could involve saving files to a specific directory on disk
        # or sending them to a separate service.
        # As requested: "выдели процесс создания файлов (это xml) в отдельный процесс"
        pass

    def generate_report_html(self, report_type=ReportType.FULL_PRODUCTION):
        label = self.ReportType(report_type).label
        
        # Adjust label if no split installation in the whole order
        if not self.order.has_split_installation:
            if report_type == self.ReportType.PHASE2_DOORS:
                label = 'דלתות'
            # 'פרס' and 'משקופים' labels are already fine without "Phase" mentioning in TextChoices

        context = {
            'order': self.order,
            'report_type': report_type,
            'report_label': label,
            'groups_data': self._get_order_data(report_type),
            'now': timezone.now(),
        }
        return render_to_string('orders/production_report.html', context)

    def _get_order_data(self, report_type=None):
        # 1. Collect all specs
        all_specs = []
        for group in self.order.groups.all():
            is_split = group.is_split_installation
            has_frame = group.product.product_family.product_type.has_frame
            has_door = group.product.product_family.product_type.has_door

            # Filter based on report type
            if report_type == self.ReportType.PHASE1_FRAMES:
                if not is_split or not has_frame:
                    continue
            elif report_type == self.ReportType.PHASE2_DOORS:
                if not has_door:
                    continue
            elif report_type == self.ReportType.PHASE2_PRESS:
                if not has_door:
                    continue
            elif report_type == self.ReportType.PHASE2_FRAMES:
                if not has_frame:
                    continue
            # FULL_PRODUCTION or None -> all items
            
            for item in group.items.all():
                spec = TechnicalSpecService.build_spec(item)
                all_specs.append(spec)
        
        # 2. Grouping logic (remains the same as before)
        grouped_specs = {}
        for spec in all_specs:
            # Key for grouping: Model, Lock, Lock Height, Hinge, Hinge Heights, Profiles
            key = (
                spec.product_name,
                spec.lock_name,
                spec.lock_height,
                spec.hinge_name,
                tuple(spec.hinge_heights),
                tuple(spec.profiles)
            )
            if key not in grouped_specs:
                grouped_specs[key] = []
            grouped_specs[key].append(spec)
            
        # 3. Form result structure
        groups_data = []
        # Sort by product name for consistent output
        sorted_keys = sorted(grouped_specs.keys())
        
        for key in sorted_keys:
            items_specs = grouped_specs[key]
            first = items_specs[0]
            
            # Common decorative params
            common_front = first.front_name
            common_color_frames = first.color_frames
            common_color_panels = first.color_panels
            
            for s in items_specs[1:]:
                if s.front_name != common_front: common_front = "Различные"
                if s.color_frames != common_color_frames: common_color_frames = "Различные"
                if s.color_panels != common_color_panels: common_color_panels = "Различные"
                
            group_spec = {
                'product_name': first.product_name,
                'front_name': common_front,
                'color_frames': common_color_frames,
                'color_panels': common_color_panels,
                'lock_name': first.lock_name,
                'hinge_name': first.hinge_name,
                'common_lock_height': first.lock_height,
                'common_hinge_heights': first.hinge_heights,
                'profiles': first.profiles,
            }
            
            groups_data.append({
                'group_spec': group_spec,
                'items_specs': items_specs,
            })
            
        return groups_data
