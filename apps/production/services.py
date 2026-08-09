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
                        'note': item.note
                    })
                
                elif item.hardware:
                    bom_result.append({
                        'type': 'hardware',
                        'item': item.hardware,
                        'quantity': total_qty,
                        'note': item.note
                    })
                
                elif item.child_product:
                    # Recursive call for nested BOM (e.g., Door in a Door Kit)
                    nested_bom = self.calculate_for_product(item.child_product, quantity=total_qty)
                    bom_result.extend(nested_bom)
                    
        return bom_result
