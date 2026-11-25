from decimal import Decimal

from django.db import models


def _consumption_field(verbose_name: str) -> models.DecimalField:
    return models.DecimalField(
        verbose_name,
        max_digits=7,
        decimal_places=2,
        default=Decimal('1.00'),
    )


class BOM(models.Model):
    """Bill of Materials (BOM): только физические материалы, расход и базовая фурнитура."""
    product = models.OneToOneField(
        'catalog.ProductModel',
        on_delete=models.CASCADE,
        related_name='bom',
        verbose_name='דגם מוצר',
    )

    covering = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name='כיסוי')
    covering_consumption = _consumption_field('צריכת כיסוי')

    base = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                             verbose_name='בסיס')
    base_consumption = _consumption_field('צריכת בסיס')

    filling = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                verbose_name='מילוי')
    filling_consumption = _consumption_field('צריכת מילוי')

    panel_frame = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+', verbose_name='מסגרת עץ')
    panel_frame_consumption = _consumption_field('צריכת מסגרת עץ')

    filling_preset = models.ForeignKey('engineering.PuzzlePreset', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+', verbose_name='פיקטוגרמה: מילוי')
    panel_frame_preset = models.ForeignKey('engineering.PuzzlePreset', on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name='+', verbose_name='פיקטוגרמה: מסגרת עץ')
    base_preset = models.ForeignKey('engineering.PuzzlePreset', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+', verbose_name='פיקטוגרמה: בסיס')
    covering_preset = models.ForeignKey('engineering.PuzzlePreset', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='+', verbose_name='פיקטוגרמה: כיסוי')

    casing = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='הלבשה')
    casing_consumption = _consumption_field('צריכת הלבשה')

    frame = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                              verbose_name='משקוף')
    frame_consumption = _consumption_field('צריכת משקוף')

    profile1 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name='פרופיל 1')
    profile1_consumption = _consumption_field('צריכת פרופיל 1')

    profile2 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name='פרופיל 2')
    profile2_consumption = _consumption_field('צריכת פרופיל 2')

    profile3 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name='פרופיל 3')
    profile3_consumption = _consumption_field('צריכת פרופיל 3')

    other1 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='אחר 1')
    other1_consumption = _consumption_field('צריכת אחר 1')

    other2 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='אחר 2')
    other2_consumption = _consumption_field('צריכת אחר 2')

    other3 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='אחר 3')
    other3_consumption = _consumption_field('צריכת אחר 3')

    other4 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='אחר 4')
    other4_consumption = _consumption_field('צריכת אחר 4')

    other5 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='אחר 5')
    other5_consumption = _consumption_field('צריכת אחר 5')

    lock = models.ForeignKey('catalog.Hardware', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                             verbose_name='מנעול')
    hinges = models.ForeignKey('catalog.Hardware', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='צירים')
    additional = models.ManyToManyField('catalog.Hardware', blank=True, related_name='+', verbose_name='תוספות')

    class Meta:
        db_table = 'production_bom'
        verbose_name = 'עץ מוצר (BOM)'
        verbose_name_plural = 'עצי מוצר (BOM)'

    def __str__(self):
        return f"BOM: {self.product.name}"
