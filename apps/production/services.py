from .models import BOMItem

class BOMCalculator:
    """
    Service for dynamic Bill of Materials (BOM) calculation.
    Supports nesting, quantity formulas, and inclusion conditions.
    """
    def __init__(self, context=None):
        """
        :param context: Dict containing variables like 'H', 'W', 'D' 
                       and 'customizers' (dict of tags/values).
        """
        self.context = context or {}

    def calculate_for_product(self, product, quantity=1):
        """
        Recursively calculates BOM for a product.
        Returns a list of dictionaries with item details and total calculated quantity.
        """
        bom_result = []
        
        # Get all BOM items for the current product
        items = BOMItem.objects.filter(parent_product=product)
        
        for item in items:
            # 1. Check if this item should be included in the dynamic BOM
            if item.matches_condition(self.context):
                
                # 2. Calculate local quantity per unit of parent
                local_qty = item.get_quantity(self.context)
                total_qty = local_qty * quantity
                
                if total_qty <= 0:
                    continue
                
                # 3. Handle different types of BOM items
                if item.material:
                    bom_result.append({
                        'type': 'material',
                        'item': item.material,
                        'quantity': total_qty,
                        'tag': item.tag,
                        'note': item.note
                    })
                
                elif item.hardware:
                    bom_result.append({
                        'type': 'hardware',
                        'item': item.hardware,
                        'quantity': total_qty,
                        'tag': item.tag,
                        'note': item.note
                    })
                
                elif item.child_product:
                    # Recursive call for nested BOM (e.g., Door in a Door Kit)
                    nested_bom = self.calculate_for_product(item.child_product, quantity=total_qty)
                    bom_result.extend(nested_bom)
                    
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
        buffer = io.BytesIO()
        is_phase_a = self.order.status == OrderStatus.PHASE1_PRODUCTION
        
        with zipfile.ZipFile(buffer, 'w') as zip_file:
            # 1. Generate Report
            items_data = self._get_items_data()
            report_content = self.generate_report_html()
            zip_file.writestr(f"Order_{self.order.order_number}_Report.html", report_content)

            # 2. Generate XML files for each position in items_data
            for data in items_data:
                item = data['item']
                # Directory for each item
                folder_name = f"{self.order.order_number}/{item.mark}"
                
                # 4 stub XML files
                for i in range(1, 5):
                    xml_content = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<root>\n  <order_number>{self.order.order_number}</order_number>\n  <item_mark>{item.mark}</item_mark>\n  <file_number>{i}</file_number>\n  <status>{'Phase A' if is_phase_a else 'Full Production'}</status>\n</root>"
                    zip_file.writestr(f"{folder_name}/file_{i}.xml", xml_content)

        buffer.seek(0)
        return buffer

    def generate_report_html(self):
        context = {
            'order': self.order,
            'is_phase_a': self.order.status == OrderStatus.PHASE1_PRODUCTION,
            'items_data': self._get_items_data(),
            'now': timezone.now()
        }
        return render_to_string('orders/production_report.html', context)

    def _get_items_data(self):
        items_data = []
        is_phase_a = self.order.status == OrderStatus.PHASE1_PRODUCTION
        
        for group in self.order.groups.all():
            # If Phase A, only process items with frames
            if is_phase_a and not group.product.product_family.product_type.has_frame:
                continue
            
            for item in group.items.all():
                # Calculate BOM for this item
                calc = BOMCalculator({
                    'H': item.height,
                    'W': item.width,
                    'wall': item.wall,
                    'customizers': {} # We might need to add group customizers here
                })
                bom = calc.calculate_for_product(group.product)
                
                lock_data = next((b for b in bom if b.get('tag') == 'Lock'), None)
                hinge_data = next((b for b in bom if b.get('tag') == 'hinge'), None)
                
                items_data.append({
                    'item': item,
                    'group': group,
                    'lock_height': item.custom_lock_height if lock_data else None,
                    'hinge_heights': [getattr(item, f'custom_hinge{i}') for i in range(1, 6) if getattr(item, f'custom_hinge{i}')] if hinge_data else [],
                    'panel_color': group.color_panels,
                    'frame_color': group.color_frames,
                })
        return items_data
