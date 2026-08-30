from django.db import models


# ==========================================
# 1. HIERARCHY: ProductType -> ProductFamily
# ==========================================

class ProductType(models.Model):
    code = models.CharField('קוד', max_length=32, unique=True)
    name = models.CharField('שם', max_length=100, unique=True)
    description = models.TextField('תיאור', blank=True)
    active = models.BooleanField('פעיל', default=True)
    has_door = models.BooleanField('יש דלת (Есть дверь)', default=True)
    has_frame = models.BooleanField('יש משקוף (Есть косяк)', default=True)

    class Meta:
        verbose_name = 'סוג מוצר'
        verbose_name_plural = 'סוגי מוצרים'

    def __str__(self):
        return self.name


class ProductFamily(models.Model):
    product_type = models.ForeignKey(
        ProductType,
        on_delete=models.PROTECT,
        related_name='families',
        verbose_name='סוג מוצר'
    )
    name = models.CharField('שם', max_length=100)
    code = models.CharField('קוד', max_length=32, unique=True)
    description = models.TextField('תיאור', blank=True)
    active = models.BooleanField('פעיל', default=True)
    default_value_for_frame = models.CharField('עובי משקוף ברירת מחדל', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = 'משפחת מוצרים'
        verbose_name_plural = 'משפחות מוצרים'
        unique_together = ('product_type', 'name')

    def __str__(self):
        return f"{self.product_type.name} -> {self.name}"


# ==========================================
# 2. SERIES & FRONTS
# ==========================================

class Series(models.Model):
    code = models.CharField('קוד', max_length=32, unique=True)
    name = models.CharField('שם', max_length=100, unique=True)
    description = models.TextField('תיאור', blank=True)
    active = models.BooleanField('פעיל', default=True)

    class Meta:
        verbose_name = 'סדרה'
        verbose_name_plural = 'סדרות'

    def __str__(self):
        return self.name

    @property
    def available_frames(self):
        products = self.products.all()
        frames = Material.objects.filter(
            id__in=products.filter(bom__frame__isnull=False).values_list('bom__frame_id', flat=True)
        )
        common_names = frames.exclude(common_name='').values_list('common_name', flat=True).distinct()
        
        material_ids = set(frames.values_list('id', flat=True))
        if common_names:
            c_mats = Material.objects.filter(
                common_name__in=common_names
            ).values_list('id', flat=True)
            material_ids.update(c_mats)

        if material_ids:
            return Material.objects.filter(id__in=material_ids).order_by('name')
        return Material.objects.none()

    @property
    def frame_colors(self):
        """Deprecated: use available_frames instead"""
        return Color.objects.filter(id__in=self.available_frames.filter(color__isnull=False).values_list('color_id', flat=True).distinct(), active=True)


class Front(models.Model):
    series = models.ForeignKey(
        Series,
        on_delete=models.CASCADE,
        related_name='fronts',
        verbose_name='סדרה'
    )
    name = models.CharField('שם', max_length=100)
    code = models.CharField('קוד/SKU', max_length=50, blank=True)
    description = models.TextField('תיאור', blank=True)
    active = models.BooleanField('פעיל', default=True)

    class Meta:
        verbose_name = 'חזית'
        verbose_name_plural = 'חזיתות'
        unique_together = ('series', 'name')

    def __str__(self):
        return self.name


class Color(models.Model):
    name = models.CharField('שם', max_length=100)
    code = models.CharField('קוד/גוון', max_length=50, blank=True)
    description = models.TextField('תיאור', blank=True)
    active = models.BooleanField('פעיל', default=True)

    class Meta:
        verbose_name = 'צבע משקוף'
        verbose_name_plural = 'צבעי משקופים'
        unique_together = ('id', 'name')
        ordering = ['id']

    def __str__(self):
        return f"{self.name}"


class Handle(models.Model):
    name = models.CharField('שם', max_length=100, unique=True)
    code = models.CharField('קוד', max_length=32, unique=True)
    description = models.TextField('תיאור', blank=True)
    active = models.BooleanField('פעיל', default=True)

    class Meta:
        verbose_name = 'ידית'
        verbose_name_plural = 'ידיות'

    def __str__(self):
        return self.name


class Hardware(models.Model):
    """
    General hardware components (locks, hinges, etc.)
    """
    name = models.CharField('שם', max_length=255)
    sku = models.CharField('מק""ט', max_length=100, unique=True)
    price = models.DecimalField('מחיר', max_digits=10, decimal_places=2, default=0)
    description = models.TextField('תיאור', blank=True)
    active = models.BooleanField('פעיל', default=True)

    class Meta:
        verbose_name = 'פרזול'
        verbose_name_plural = 'פרזול'

    def __str__(self):
        return f"{self.name} ({self.sku})"


# ==========================================
# 3. MATERIALS & COMPONENTS
# ==========================================


class Material(models.Model):
    name = models.CharField('שם', max_length=255)
    common_name = models.CharField('שם רגיל', max_length=255, blank=True, default='')
    sku = models.CharField('מק""ט', max_length=100, unique=True)
    material_type = models.CharField(
        'סוג חומר',
        max_length=20,

    )

    thickness = models.DecimalField('עובי, מ""מ', max_digits=5, decimal_places=2, null=True, blank=True)
    length = models.DecimalField('אורך סטנדרטי, מ""מ', max_digits=7, decimal_places=2, null=True, blank=True)
    width = models.DecimalField('רוחב סטנדרטי, מ""מ', max_digits=7, decimal_places=2, null=True, blank=True)
    color = models.ForeignKey(Color, on_delete=models.SET_NULL, null=True, blank=True, related_name='materials')

    price_per_unit = models.DecimalField('מחיר ליחידה', max_digits=10, decimal_places=2, default=0)
    unit_of_measure = models.CharField('יחידת מידה', max_length=20, default='pcs')

    class Meta:
        verbose_name = 'חומר'
        verbose_name_plural = 'חומרים'

    def __str__(self):
        return f"{self.name}"


# ==========================================
# 4. PRODUCT & BILL OF MATERIALS (BOM)
# ==========================================

class ProductModel(models.Model):
    """
    Product master definition.
    Represents a unique intersection of ProductFamily x Series.
    Core catalog identity. Technological details are stored in apps.production.ProductTechnicalData.
    """
    code = models.CharField('מק""ט', max_length=100, unique=True)
    name = models.CharField('שם', max_length=255)
    description = models.TextField('תיאור', blank=True)
    active = models.BooleanField('פעיל', default=True)

    product_family = models.ForeignKey(
        ProductFamily,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name='משפחת מוצרים'
    )
    series = models.ForeignKey(
        Series,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name='סדרה'
    )

    class Meta:
        verbose_name = 'מוצר'
        verbose_name_plural = 'מוצרים'
        unique_together = ('product_family', 'series')

    def __str__(self):
        return f"[{self.code}] {self.name} ({self.product_family.name} / {self.series.name})"

    @property
    def available_frames(self):
        try:
            bom = self.bom
        except Exception:
            return Material.objects.none()
        if not bom or not bom.frame:
            return Material.objects.none()
        frame = bom.frame
        if not frame.common_name:
            return Material.objects.filter(id=frame.id)

        return Material.objects.filter(common_name=frame.common_name).order_by('name')

    @property
    def frame_colors(self):
        """Deprecated: use available_frames instead"""
        return Color.objects.filter(id__in=self.available_frames.filter(color__isnull=False).values_list('color_id', flat=True).distinct(), active=True)


class Customizer(models.Model):
    # --- Main identifiers ---
    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name='קוד / מק""ט קסטומייזר',
        help_text="קוד ייחודי לחיפוש מהיר על ידי מנהל (למשל cmz1)",
    )
    name = models.CharField(max_length=255, verbose_name="שם")
    description = models.TextField(
        blank=True, null=True, verbose_name="תיאור"
    )
    active = models.BooleanField(
        default=True, verbose_name="פעיל", db_index=True
    )

    # --- Catalog hierarchy link (Optional / Nullable) ---
    product_type = models.ForeignKey(
        "ProductType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customizers",
        verbose_name="סוג מוצר",
    )
    product_family = models.ForeignKey(
        "ProductFamily",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customizers",
        verbose_name="משפחת מוצרים",
    )
    product_model = models.ForeignKey(
        "ProductModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customizers",
        verbose_name="דגם מוצר",
    )

    # --- Engine/Pipeline settings (Strategy & Chain of Responsibility) ---
    class Strategy(models.IntegerChoices):
        NONE = 0, 'ללא אסטרטגיה'
        STRATEGY_1 = 1, 'אסטרטגיה 1'
        STRATEGY_2 = 2, 'אסטרטגיה 2'
        STRATEGY_3 = 3, 'אסטרטגיה 3'
        STRATEGY_4 = 4, 'אסטרטגיה 4'
        STRATEGY_5 = 5, 'אסטרטגיה 5'
        STRATEGY_6 = 6, 'אסטרטגיה 6'
        STRATEGY_7 = 7, 'אסטרטגיה 7'
        STRATEGY_8 = 8, 'אסטרטגיה 8'
        STRATEGY_9 = 9, 'אסטרטגיה 9'
        STRATEGY_10 = 10, 'אסטרטגיה 10 (Frames Report)'

    strategy = models.IntegerField(
        choices=Strategy.choices,
        default=Strategy.NONE,
        verbose_name="אסטרטגיה",
        help_text="שלב עיבוד שבו התוספת משתתפת"
    )
    tag = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="תג / אלגוריתם",
        help_text="מזהה אסטרטגיית עיבוד בקוד (למשל LOCK_SELECTION)",
    )
    priority = models.IntegerField(
        default=100,
        verbose_name="עדיפות",
        help_text="סדר ביצוע בתוך השלב (מספר קטן יותר מבוצע מוקדם יותר)",
    )

    # --- Parameters 1..4 (Labels, Default Values, Hints) ---
    par1_label = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="פרמטר 1: תווית",
    )
    par1_value = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="פרמטר 1: ערך ברירת מחדל",
    )
    par1_hint = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="פרמטר 1: רמז",
    )

    par2_label = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="פרמטר 2: תווית",
    )
    par2_value = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="פרמטר 2: ערך ברירת מחדל",
    )
    par2_hint = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="פרמטר 2: רמז",
    )

    par3_label = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="פרמטר 3: תווית",
    )
    par3_value = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="פרמטר 3: ערך ברירת מחדל",
    )
    par3_hint = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="פרמטר 3: רמז",
    )

    par4_label = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="פרמטר 4: תווית",
    )
    par4_value = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="פרמטר 4: ערך ברירת מחדל",
    )
    par4_hint = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="פרמטר 4: רמז",
    )

    class Meta:
        db_table = "customizers"
        verbose_name = "קסטומייזר / אפשרות"
        verbose_name_plural = "קסטומייזרים / אפשרויות"
        ordering = ["priority", "code"]

    def __str__(self):
        return f"[{self.code}] {self.name}"
