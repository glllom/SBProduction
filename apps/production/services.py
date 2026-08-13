import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from decimal import Decimal
from .models import BOM, ProductTechnicalData
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
        
        hinge_heights = [
            float(getattr(item, f'custom_hinge{i}')) 
            for i in range(1, 6) 
            if getattr(item, f'custom_hinge{i}')
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
            lock_height=float(item.custom_lock_height) if item.custom_lock_height else None,
            hinge_name=hinge_name,
            hinge_heights=hinge_heights,
            bom_items=bom_result,
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
    def __init__(self, order):
        self.order = order

    def generate_production_zip(self):
        print("Generating production zip")
        buffer = io.BytesIO()
        is_phase_a = self.order.status == OrderStatus.PHASE1_PRODUCTION
        
        with zipfile.ZipFile(buffer, 'w') as zip_file:
            # 1. Generate Report
            order_data = self._get_order_data()
            report_content = self.generate_report_html()
            zip_file.writestr(f"Order_{self.order.order_number}_Report.html", report_content)

            # 2. Generate XML files for each position
            for group_data in order_data:
                for spec in group_data['items_specs']:
                    # Directory for each item
                    folder_name = f"{self.order.order_number}/{spec.mark}"
                    
                    # 4 stub XML files
                    for i in range(1, 5):
                        xml_content = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<root>\n  <order_number>{self.order.order_number}</order_number>\n  <item_mark>{spec.mark}</item_mark>\n  <file_number>{i}</file_number>\n  <status>{'Phase A' if is_phase_a else 'Full Production'}</status>\n</root>"
                        zip_file.writestr(f"{folder_name}/file_{i}.xml", xml_content)

        buffer.seek(0)
        return buffer

    def generate_report_html(self):
        context = {
            'order': self.order,
            'is_phase_a': self.order.status == OrderStatus.PHASE1_PRODUCTION,
            'groups_data': self._get_order_data(),
            'now': timezone.now(),
        }
        # print(context['order'])
        return render_to_string('orders/production_report.html', context)

    def _get_order_data(self):
        groups_data = []
        is_phase_a = self.order.status == OrderStatus.PHASE1_PRODUCTION

        for group in self.order.groups.all():

            # If Phase A, only process items with frames
            if is_phase_a and not group.product.product_family.product_type.has_frame:
                continue
            
            items_specs = []
            for item in group.items.all():
                spec = TechnicalSpecService.build_spec(item)
                items_specs.append(spec)
            
            # Собираем данные уровня группы
            group_spec = None
            if items_specs:
                first = items_specs[0]
                
                # Проверяем, являются ли высоты фурнитуры общими для всей группы
                common_lock_height = first.lock_height
                common_hinge_heights = first.hinge_heights
                
                for s in items_specs[1:]:
                    if s.lock_height != common_lock_height:
                        common_lock_height = "Различные"
                    if s.hinge_heights != common_hinge_heights:
                        common_hinge_heights = ["Различные"]
                
                group_spec = {
                    'product_name': first.product_name,
                    'front_name': first.front_name,
                    'color_frames': first.color_frames,
                    'color_panels': first.color_panels,
                    'lock_name': first.lock_name,
                    'hinge_name': first.hinge_name,
                    'common_lock_height': common_lock_height,
                    'common_hinge_heights': common_hinge_heights,
                }
            
            groups_data.append({
                'group': group,
                'group_spec': group_spec,
                'items_specs': items_specs,
            })
            
        return groups_data
