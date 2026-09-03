import math
from typing import List, Dict, Any, Optional

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

    def _resolve_material(self, material):
        """
        Resolves a material to its colored version if basic_color_frames is set.
        If basic_color_frames is a Material object, we use its color to find 
        matching materials with the same common_name.
        """
        if not material:
            return None

        selected_frame_material = self.context.get('basic_color_frames')
        if not selected_frame_material:
            return material

        # 1. Exact match by common_name with selected material
        if material.common_name and selected_frame_material.common_name == material.common_name:
            return selected_frame_material

        # 2. Match other materials by common_name and the color of selected material
        if material.common_name and selected_frame_material.color:
            from apps.catalog.models import Material
            colored_material = Material.objects.filter(
                common_name=material.common_name,
                color=selected_frame_material.color
            ).first()
            if colored_material:
                return colored_material

        return material

    def calculate_for_product(self, product, quantity=1):
        """
        Recursively calculates BOM for a product based on the structured BOM model.
        """
        try:
            bom = product.bom
        except Exception:  # RelatedObjectDoesNotExist
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
                material = self._resolve_material(material)
                formula = getattr(bom, f"{slot_name}_consumption")
                local_qty = self._evaluate(formula)
                total_qty = local_qty * quantity
                if total_qty > 0:
                    bom_result.append({
                        'type': 'material',
                        'section': label,
                        'item': material,
                        'quantity': total_qty,
                        'tag': slot_name  # For backward compatibility or extra identification
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
                    'quantity': 1 * quantity  # Default to 1 per unit
                })

        # 3. Process Nested BOMs
        for nested_bom in bom.nested_boms.all():
            # Recurse using the product of the nested BOM
            nested_results = self.calculate_for_product(nested_bom.product, quantity=quantity)
            bom_result.extend(nested_results)

        return bom_result
