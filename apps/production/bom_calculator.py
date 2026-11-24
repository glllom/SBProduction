class BOMCalculator:
    """
    Service for Bill of Materials (BOM) calculation.
    Supports fixed-slot materials and categorized hardware.
    """

    MATERIAL_SLOTS = (
        ('covering', 'כיסוי'),
        ('base', 'בסיס'),
        ('filling', 'מילוי'),
        ('panel_frame', 'panel_frame'),
        ('casing', 'הלבשה'),
        ('frame', 'משקוף'),
        ('profile1', 'פרופיל 1'),
        ('profile2', 'פרופיל 2'),
        ('profile3', 'פרופיל 3'),
        ('other1', 'אחר 1'),
        ('other2', 'אחר 2'),
        ('other3', 'אחר 3'),
        ('other4', 'אחר 4'),
        ('other5', 'אחר 5'),
    )

    HARDWARE_SLOTS = (
        ('lock', 'מנעול', 'lock'),
        ('hinges', 'צירים', 'hinge'),
        ('additional', 'תוספות', 'additional'),
    )

    def __init__(self, context=None):
        self.context = context or {}

    @staticmethod
    def _get_consumption(bom, slot_name: str) -> float:
        raw = getattr(bom, f"{slot_name}_consumption", None)
        if raw in (None, ''):
            return 0.0
        try:
            return float(raw)
        except (ValueError, TypeError):
            return 0.0

    def _resolve_material(self, material, tag=None):
        """
        Resolves a material to its colored version.
        For frame, it uses the pre-resolved material from FrameResolutionStep.
        """
        if not material:
            return None

        if tag == 'frame':
            resolved_frame = self.context.get('resolved_frame_material')
            if resolved_frame:
                return resolved_frame

        selected_color_material = self.context.get('basic_color_frames')

        if material.common_name:
            if selected_color_material and selected_color_material.common_name == material.common_name:
                return selected_color_material

            if selected_color_material and selected_color_material.color:
                from apps.catalog.models import Material
                colored_material = Material.objects.filter(
                    common_name=material.common_name,
                    color=selected_color_material.color,
                ).first()
                if colored_material:
                    return colored_material

        return material

    def calculate_for_product(self, product, quantity=1):
        """
        Calculates BOM for a product based on the structured BOM model.
        Uses in-memory effective_bom if prepared by BOMOverrideStep.
        """
        bom = self.context.get('effective_bom') or product.effective_bom
        if not bom:
            return []

        bom_result = []
        has_frame = self.context.get('has_frame', True)

        # 1. Process Material Slots
        for slot_name, label in self.MATERIAL_SLOTS:
            if not has_frame and slot_name in ('frame', 'casing'):
                continue

            material = getattr(bom, slot_name, None)
            if not material:
                continue

            material = self._resolve_material(material, tag=slot_name)
            total_qty = self._get_consumption(bom, slot_name) * quantity
            if total_qty > 0:
                bom_result.append({
                    'type': 'material',
                    'section': label,
                    'item': material,
                    'quantity': total_qty,
                    'tag': slot_name,
                })

        # 2. Process Hardware Slots
        for slot_name, label, tag in self.HARDWARE_SLOTS:
            val = getattr(bom, slot_name, None)
            if not val:
                continue

            hardware_list = val.all() if hasattr(val, 'all') else [val]
            for hw in hardware_list:
                bom_result.append({
                    'type': 'hardware',
                    'section': label,
                    'item': hw,
                    'tag': tag,
                    'quantity': 1 * quantity,
                })

        return bom_result
