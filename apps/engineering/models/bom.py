from django.db import models


class BOM(models.Model):
    """Bill of Materials (BOM) with structured sections for materials and hardware."""
    product = models.OneToOneField(
        'catalog.ProductModel',
        on_delete=models.CASCADE,
        related_name='bom',
        verbose_name='דגם מוצר',
    )

    covering = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name='כיסוי')
    covering_consumption = models.CharField('צריכת כיסוי', max_length=255, default='1', blank=True)

    base = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                             verbose_name='בסיס')
    base_consumption = models.CharField('צריכת בסיס', max_length=255, default='1', blank=True)

    filling = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                verbose_name='מילוי')
    filling_consumption = models.CharField('צריכת מילוי', max_length=255, default='1', blank=True)

    panel_frame = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+', verbose_name='מסגרת עץ')
    panel_frame_consumption = models.CharField('צריכת מסגרת עץ', max_length=255, default='1', blank=True)

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
    casing_consumption = models.CharField('צריכת הלבשה', max_length=255, default='1', blank=True)

    frame = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                              verbose_name='משקוף')
    frame_consumption = models.CharField('צריכת משקוף', max_length=255, default='1', blank=True)

    profile1 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name='פרופיל 1')
    profile1_consumption = models.CharField('צריכת פרופיל 1', max_length=255, default='1', blank=True)

    profile2 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name='פרופיל 2')
    profile2_consumption = models.CharField('צריכת פרופיל 2', max_length=255, default='1', blank=True)

    profile3 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name='פרופיל 3')
    profile3_consumption = models.CharField('צריכת פרופיל 3', max_length=255, default='1', blank=True)

    other1 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='אחר 1')
    other1_consumption = models.CharField('צריכת אחר 1', max_length=255, default='1', blank=True)

    other2 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='אחר 2')
    other2_consumption = models.CharField('צריכת אחר 2', max_length=255, default='1', blank=True)

    other3 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='אחר 3')
    other3_consumption = models.CharField('צריכת אחר 3', max_length=255, default='1', blank=True)

    other4 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='אחר 4')
    other4_consumption = models.CharField('צריכת אחר 4', max_length=255, default='1', blank=True)

    other5 = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='אחר 5')
    other5_consumption = models.CharField('צריכת אחר 5', max_length=255, default='1', blank=True)

    lock = models.ForeignKey('catalog.Hardware', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                             verbose_name='מנעול')
    hinges = models.ForeignKey('catalog.Hardware', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='צירים')
    additional = models.ManyToManyField('catalog.Hardware', blank=True, related_name='+', verbose_name='תוספות')
    required_customizers = models.ManyToManyField('catalog.Customizer', blank=True, related_name='required_for_boms',
                                                  verbose_name='התאמות אישיות חובה')

    cut_coefficients = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='מקדמי חיתוך חלקים',
        help_text='מילון מקדמי חיתוך חלקים במילימטרים (למשל {"transom_delta": 45})',
    )

    class Meta:
        db_table = 'production_bom'
        verbose_name = 'עץ מוצר (BOM)'
        verbose_name_plural = 'עצי מוצר (BOM)'

    def __str__(self):
        return f"BOM: {self.product.name}"
