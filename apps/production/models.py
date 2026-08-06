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
