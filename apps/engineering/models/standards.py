from django.db import models


class LockStandardHeight(models.Model):
    product_families = models.ManyToManyField(
        'catalog.ProductFamily',
        related_name='lock_heights',
        verbose_name='משפחות מוצרים',
    )
    locks = models.ManyToManyField(
        'catalog.Hardware',
        related_name='lock_heights',
        verbose_name='מנעולים',
    )
    base_door_height = models.DecimalField(
        'גובה דלת בסיסי',
        max_digits=7,
        decimal_places=2,
        help_text='גובה דלת לייחוס (בס"מ)',
    )
    base_lock_height = models.DecimalField(
        'גובה מנעול בסיסי',
        max_digits=7,
        decimal_places=2,
        help_text='מיקום המנעול בגובה הבסיסי',
    )
    step = models.DecimalField(
        'צעד',
        max_digits=7,
        decimal_places=2,
        default=0,
        help_text='שינוי בגובה המנעול לכל יחידת גובה דלת',
    )
    alignment_tolerance = models.DecimalField(
        'סבילות התאמת גובה (ס"מ)',
        max_digits=5,
        decimal_places=2,
        default=2.5,
        help_text='הפרש גובה מקסימלי (בס"מ) לאיחוד אוטומטי של גובה מנעול בין דלתות סמוכות',
    )

    class Meta:
        db_table = 'production_lockstandardheight'
        verbose_name = 'גובה מנעול סטנדרטי'
        verbose_name_plural = 'גבהי מנעול סטנדרטיים'


class HingeStandardHeight(models.Model):
    product_families = models.ManyToManyField(
        'catalog.ProductFamily',
        related_name='hinge_heights',
        verbose_name='משפחות מוצרים',
    )
    hinges = models.ManyToManyField(
        'catalog.Hardware',
        related_name='hinge_heights',
        verbose_name='צירים',
    )
    min_height = models.DecimalField('גובה מינימלי', max_digits=7, decimal_places=2, help_text='מינימום גובה דלת בטווח')
    max_height = models.DecimalField('גובה מקסימלי', max_digits=7, decimal_places=2, help_text='מקסימום גובה דלת בטווח')

    value1 = models.DecimalField('גובה ציר 1', max_digits=7, decimal_places=2, null=True, blank=True)
    value2 = models.DecimalField('גובה ציר 2', max_digits=7, decimal_places=2, null=True, blank=True)
    value3 = models.DecimalField('גובה ציר 3', max_digits=7, decimal_places=2, null=True, blank=True)
    value4 = models.DecimalField('גובה ציר 4', max_digits=7, decimal_places=2, null=True, blank=True)
    value5 = models.DecimalField('גובה ציר 5', max_digits=7, decimal_places=2, null=True, blank=True)

    hinge_count = models.PositiveSmallIntegerField('כמות צירים', default=0, editable=False, db_index=True)

    class Meta:
        db_table = 'production_hingestandardheight'
        verbose_name = 'גובה צירים סטנדרטי'
        verbose_name_plural = 'גבהי צירים סטנדרטיים'

    def save(self, *args, **kwargs):
        values = [self.value1, self.value2, self.value3, self.value4, self.value5]
        self.hinge_count = sum(1 for v in values if v is not None and float(v) > 0)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        hinges_str = ', '.join(h.name for h in self.hinges.all())
        families_str = ', '.join(f.code for f in self.product_families.all())
        return f'{self.hinge_count} צירים {hinges_str} בגובה {self.min_height}-{self.max_height} לדלתות: {families_str}'
