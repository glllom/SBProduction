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

    def _resolve_material(self, material, tag=None):
        """
        Resolves a material to its colored version.
        For frame, it uses the pre-resolved material from FrameResolutionStep.
        """
        if not material:
            return None

        # 1. Frame-specific resolution (already handled in pipeline)
        if tag == 'frame':
            resolved_frame = self.context.get('resolved_frame_material')
            if resolved_frame:
                return resolved_frame

        # 2. General color resolution based on common_name
        selected_color_material = self.context.get('basic_color_frames')
        
        if material.common_name:
            if selected_color_material and selected_color_material.common_name == material.common_name:
                return selected_color_material

            if selected_color_material and selected_color_material.color:
                from apps.catalog.models import Material
                colored_material = Material.objects.filter(
                    common_name=material.common_name,
                    color=selected_color_material.color
                ).first()
                if colored_material:
                    return colored_material

        return material

    def calculate_for_product(self, product, quantity=1):
        """
        Recursively calculates BOM for a product based on the structured BOM model.
        Uses effective BOM (local or from parent model).
        """
        bom = product.effective_bom
        if not bom:
            return []

        bom_result = []
        has_frame = self.context.get('has_frame', True)

        # 1. Process Material Slots
        material_slots = [
            ('covering', 'כיסוי'), ('base', 'בסיס'), ('filling', 'מילוי'),
            ('casing', 'הלבשה'), ('frame', 'משקוף'), ('profile1', 'פרופיל 1'),
            ('profile2', 'פרופיל 2'), ('profile3', 'פרופיל 3'), ('other1', 'אחר 1'),
            ('other2', 'אחר 2'), ('other3', 'אחר 3'), ('other4', 'אחר 4'),
            ('other5', 'אחר 5')
        ]

        for slot_name, label in material_slots:
            # Skip frame-related materials if has_frame is False
            if not has_frame and slot_name in ['frame', 'casing']:
                continue
            material = getattr(bom, slot_name)
            if material:
                material = self._resolve_material(material, tag=slot_name)
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

        if not has_frame:
            bom_result = [b for b in bom_result if b.get('tag') != 'frame']

        return bom_result
