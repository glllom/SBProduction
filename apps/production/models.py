import math
from django.db import models
from apps.catalog.models import ProductModel


class ProductTechnicalData(models.Model):
    """
    Technical specification of the product for production.
    Stores parameters required for CNC machines and technical task generation.
    """
    product = models.OneToOneField(
        ProductModel,
        on_delete=models.CASCADE,
        related_name='tech_data',
        verbose_name='דגם מוצר'
    )
    
    cnc_program_name = models.CharField(
        'שם תוכנית CNC',
        max_length=255,
        blank=True,
        help_text='למשל: door_v1_standard.prg'
    )
    
    technical_notes = models.TextField(
        'הערות טכניות',
        blank=True,
        help_text='הוראות לעובדי הייצור'
    )
    
    # Add any other technical parameters here
    # e.g., tolerances, cutter types, equipment settings, etc.

    class Meta:
        verbose_name = 'נתונים טכניים של המוצר'
        verbose_name_plural = 'נתונים טכניים של מוצרים'

    def __str__(self):
        return f"נתונים טכניים עבור {self.product.name}"


class BOMItem(models.Model):
    """
    Dynamic Bill of Materials (BOM) entry.
    Can be a Material, Hardware component, or another Product (nested BOM).
    Includes quantity formulas and inclusion conditions.
    """
    parent_product = models.ForeignKey(
        ProductModel,
        on_delete=models.CASCADE,
        related_name='bom_items',
        verbose_name='מוצר אב'
    )
    
    # Types of items (only one should be filled, but we keep it flexible)
    material = models.ForeignKey(
        'catalog.Material',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='used_in_bom',
        verbose_name='חומר'
    )
    hardware = models.ForeignKey(
        'catalog.Hardware',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='used_in_bom',
        verbose_name='פרזול'
    )
    child_product = models.ForeignKey(
        ProductModel,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='contained_in_bom',
        verbose_name='מוצר בן (BOM מוטמע)'
    )
    
    quantity_formula = models.CharField(
        'נוסחת כמות',
        max_length=255,
        default='1',
        help_text='נוסחה לחישוב כמות (למשל: H * W / 1000000)'
    )
    
    inclusion_condition = models.CharField(
        'תנאי הכללה',
        max_length=255,
        blank=True,
        help_text='תנאי להכללת הפריט ב-BOM (למשל: has_frame == True)'
    )
    
    tag = models.CharField(
        'תג',
        max_length=50,
        blank=True,
        help_text='תג לזיהוי פריט (למשл: Lock, hinge)'
    )
    
    note = models.CharField('הערה', max_length=255, blank=True)

    class Meta:
        verbose_name = 'פריט עץ מוצר (BOM)'
        verbose_name_plural = 'פריטי עץ מוצר (BOM)'

    def __str__(self):
        item_name = "ריק"
        if self.material:
            item_name = f"חומר: {self.material.name}"
        elif self.hardware:
            item_name = f"פרזול: {self.hardware.name}"
        elif self.child_product:
            item_name = f"מוצר: {self.child_product.name}"
        return f"{self.parent_product.name} -> {item_name}"

    def get_quantity(self, context):
        """
        Calculates quantity based on quantity_formula and context (H, W, D, etc.)
        """
        try:
            # Simple eval with limited context for safety
            safe_context = {
                'H': float(context.get('H', 0)),
                'W': float(context.get('W', 0)),
                'D': float(context.get('D', 0)),
                'math': math,
            }
            # Add customizer tags to context (e.g., {'HAS_LOCK': True})
            if 'customizers' in context:
                safe_context.update(context['customizers'])
            
            return eval(self.quantity_formula, {"__builtins__": None}, safe_context)
        except Exception as e:
            return 0

    def matches_condition(self, context):
        """
        Checks if the item should be included in BOM based on inclusion_condition.
        """
        if not self.inclusion_condition:
            return True
        try:
            safe_context = {
                'H': float(context.get('H', 0)),
                'W': float(context.get('W', 0)),
                'D': float(context.get('D', 0)),
                'math': math,
            }
            if 'customizers' in context:
                safe_context.update(context['customizers'])
                
            return bool(eval(self.inclusion_condition, {"__builtins__": None}, safe_context))
        except Exception:
            return False
