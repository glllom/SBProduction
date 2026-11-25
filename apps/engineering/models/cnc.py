from django.db import models


class PerimeterRoutingFile(models.Model):
    file_name = models.CharField(max_length=100, unique=True, verbose_name="שם קובץ")
    description = models.CharField(max_length=255, blank=True, verbose_name="תיאור")
    edge_shape = models.BooleanField(default=False, verbose_name="צורת קנט (edge_shape)")
    doors = models.ManyToManyField(
        'catalog.ProductFamily',
        blank=True,
        related_name='perimeter_routings',
        verbose_name='משפחת מוצרים',
    )

    class Meta:
        db_table = 'production_perimeterroutingfile'
        ordering = ['id']
        verbose_name = 'קובץ ניתוב היקפי'
        verbose_name_plural = 'קבצי ניתוב היקפי'

    def __str__(self):
        return f"{self.file_name} ({self.description})" if self.description else self.file_name


class HardwareMacroFile(models.Model):
    file_name = models.CharField(max_length=100, unique=True, verbose_name="שם קובץ / מאקרו")
    description = models.CharField(max_length=255, blank=True, verbose_name="תיאור")
    hardware = models.ManyToManyField(
        'catalog.Hardware',
        blank=True,
        related_name='macro_files',
        verbose_name='פרזול',
    )
    machining_feature = models.ForeignKey(
        'catalog.MachiningFeature',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='מאפיין עיבוד מיוחד',
    )
    label_name = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name="שם להדפסה על מדבקה",
        help_text="טקסט קצר למפעיל (למשל: מנעול מגנט חורים קטנים). אם ריק — יוצג שם הפרזול + מאפיין העיבוד.",
    )
    door_families = models.ManyToManyField(
        'catalog.ProductFamily',
        blank=True,
        related_name='hardware_macro_files',
        verbose_name='משפחות דלתות',
    )

    class Meta:
        db_table = 'production_hardwaremacrofile'
        ordering = ['file_name']
        verbose_name = 'קובץ מאקרו פרזול'
        verbose_name_plural = 'קבצי מאקרו פרזול'

    def __str__(self):
        return f"{self.file_name} ({self.description})" if self.description else self.file_name


class CustomizerMacroFile(models.Model):
    customizer = models.OneToOneField(
        'catalog.Customizer',
        on_delete=models.CASCADE,
        related_name='macro_file',
        verbose_name='התאמה אישית',
    )
    file_name = models.CharField(max_length=100, unique=True, verbose_name="שם קובץ / מאקרו")
    description = models.CharField(max_length=255, blank=True, verbose_name="תיאור")

    class Meta:
        db_table = 'production_customizermacrofile'
        ordering = ['file_name']
        verbose_name = 'קובץ התאמה אישית'
        verbose_name_plural = 'קבצי התאמות אישיות'

    def __str__(self):
        return f"{self.file_name} ({self.description})" if self.description else self.file_name


class FrontEngravingFile(models.Model):
    front = models.OneToOneField(
        'catalog.Front',
        on_delete=models.CASCADE,
        related_name='engraving_file',
        verbose_name='חזית / דוגמה',
    )
    file_name = models.CharField(max_length=100, unique=True, verbose_name="שם קובץ / מאקרו")
    description = models.CharField(max_length=255, blank=True, verbose_name="תיאור")

    class Meta:
        db_table = 'production_frontengravingfile'
        ordering = ['file_name']
        verbose_name = 'קובץ חריטה לחזית'
        verbose_name_plural = 'קבצי חריטה לחזיתות'

    def __str__(self):
        return f"{self.file_name} ({self.description})" if self.description else self.file_name
   