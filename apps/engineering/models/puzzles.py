from django.db import models


class SvgPattern(models.Model):
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="מזהה (slug)",
        help_text="מפתח באנגלית למזהה ה-SVG (לדוגמה: foam, tubular, honeycomb)",
    )
    title = models.CharField(max_length=100, verbose_name="שם")
    width = models.PositiveIntegerField(default=20, verbose_name="רוחב אריח (px)")
    height = models.PositiveIntegerField(default=20, verbose_name="גובה אריח (px)")
    svg_content = models.TextField(
        verbose_name="תוכן SVG פנימי",
        help_text="תגיות rect, circle, path, line ללא תגית העטיפה <pattern>",
    )

    class Meta:
        db_table = 'production_svgpattern'
        verbose_name = "תבנית SVG"
        verbose_name_plural = "תבניות SVG"
        ordering = ['title']

    def __str__(self):
        return f"{self.title} ({self.name})"


class PuzzleBlockPrototype(models.Model):
    class FillType(models.TextChoices):
        SOLID = 'SOLID', 'צבע אחיד'
        PATTERN = 'PATTERN', 'תבנית SVG'

    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="קוד אב טיפוס",
        help_text="לדוגמה: pine_timber, green_hdf, tubular_core",
    )
    name = models.CharField(max_length=100, verbose_name="שם")
    fill_type = models.CharField(max_length=10, choices=FillType.choices, default=FillType.SOLID,
                                 verbose_name="סוג מילוי")
    fill_color = models.CharField(max_length=30, default="#fab005", verbose_name="צבע מילוי (HEX)")
    pattern = models.ForeignKey(
        SvgPattern,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="block_prototypes",
        verbose_name="תבנית",
    )
    border_color = models.CharField(max_length=30, default="#000000", verbose_name="צבע גבול")
    border_width = models.FloatField(default=1.0, verbose_name="עובי גבול")
    border_dasharray = models.CharField(max_length=30, blank=True, default="", verbose_name="קו מקווקו")
    opacity = models.FloatField(default=1.0, verbose_name="אטימות (0.0 - 1.0)")
    default_text_color = models.CharField(max_length=30, default="#000000", verbose_name="צבע טקסט")
    default_font_size = models.PositiveSmallIntegerField(default=11, verbose_name="גודל גופן")

    class Meta:
        db_table = 'production_puzzleblockprototype'
        verbose_name = "אב טיפוס של בלוק פאזל"
        verbose_name_plural = "אבות טיפוס של בלוקי פאזל"

    def __str__(self):
        return f"{self.name} [{self.code}]"


class PuzzlePreset(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="שם פריסט")
    description = models.TextField(blank=True, verbose_name="תיאור")
    blocks_config = models.JSONField(default=list, blank=True, verbose_name="הגדרת בלוקים")

    class Meta:
        db_table = 'production_puzzlepreset'
        verbose_name = "פריסט צומת (פיקטוגרמה)"
        verbose_name_plural = "פריסטים של צמתים (פיקטוגרמות)"

    def __str__(self):
        return self.name


class CustomizerPuzzleMapping(models.Model):
    customizer = models.OneToOneField(
        'catalog.Customizer',
        on_delete=models.CASCADE,
        related_name='puzzle_mapping',
        verbose_name="התאמה אישית",
    )
    preset = models.ForeignKey(
        PuzzlePreset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customizer_mappings',
        verbose_name="פיקטוגרמה",
    )

    class Meta:
        db_table = 'production_customizerpuzzlemapping'
        verbose_name = "מיפוי פיקטוגרמה להתאמה אישית"
        verbose_name_plural = "מיפויי פיקטוגרמות להתאמות אישיות"

    def __str__(self):
        return f"{self.customizer.name} -> {self.preset.name if self.preset else 'ללא פיקטוגרמה'}"
