from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
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

    thickness = models.FloatField('עובי (Толщина)', default=0.0)
    leaf_height_adjustment = models.FloatField(
        'תיקון גובה כנף (Корректировка высоты полотна)',
        default=0.0,
        validators=[MaxValueValidator(0)]
    )
    leaf_width_adjustment = models.FloatField(
        'תיקון רוחב כנף (Корректировка ширины полотна)',
        default=0.0,
        validators=[MaxValueValidator(0)]
    )

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
        return Color.objects.filter(
            id__in=self.available_frames.filter(color__isnull=False).values_list('color_id', flat=True).distinct(),
            active=True)


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
    product_types = models.ManyToManyField(
        ProductType,
        blank=True,
        related_name="hardware_items",
        verbose_name="סוגי מוצרים",
    )
    product_families = models.ManyToManyField(
        ProductFamily,
        blank=True,
        related_name="hardware_items",
        verbose_name="משפחות מוצרים",
    )
    product_models = models.ManyToManyField(
        "ProductModel",
        blank=True,
        related_name="hardware_items",
        verbose_name="דגמי מוצרים",
    )
    components = models.ManyToManyField(
        'self',
        blank=True,
        symmetrical=False,
        related_name='assembled_in',
        verbose_name='רכיבים (Components)',
        help_text='Components that make up this assembly',
    )

    class Meta:
        verbose_name = 'פרזול'
        verbose_name_plural = 'פרזול'

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def is_compatible_with(self, product_model):
        """
        Check if hardware is compatible with a given product model.
        OR logic: if explicitly listed, OR if model's family is listed, OR if model's type is listed.
        If all sets are empty, it's globally compatible.
        """
        if not product_model:
            return True

        # Check if any constraints exist
        has_types = self.product_types.exists()
        has_families = self.product_families.exists()
        has_models = self.product_models.exists()

        if not (has_types or has_families or has_models):
            return True

        if has_models:
            if self.product_models.filter(id=product_model.id).exists():
                return True
            if product_model.parent_model and self.product_models.filter(id=product_model.parent_model.id).exists():
                return True

        if has_families and self.product_families.filter(id=product_model.product_family_id).exists():
            return True
        if has_types and self.product_types.filter(id=product_model.product_family.product_type_id).exists():
            return True

        return False


class Material(models.Model):
    name = models.CharField('שם', max_length=255)
    common_name = models.CharField('שם רגיל', max_length=255, blank=True, default='')

    outward_substitute = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inward_originals',
        verbose_name='תחליף לפתיחה החוצה'
    )
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

    parent_model = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='derived_models',
        verbose_name='דגם אב'
    )

    class Meta:
        verbose_name = 'מוצר'
        verbose_name_plural = 'מוצרים'
        unique_together = ('product_family', 'series')

    def __str__(self):
        return f"[{self.code}] {self.name} ({self.product_family.name} / {self.series.name})"

    @property
    def has_door(self) -> bool:
        return self.product_family.product_type.has_door

    @property
    def has_frame(self) -> bool:
        return self.product_family.product_type.has_frame

    @property
    def effective_bom(self):
        """
        Returns the BOM for this model. If not defined, attempts to return the effective BOM 
        from the parent model.
        """
        try:
            return self.bom
        except Exception:
            if self.parent_model:
                return self.parent_model.effective_bom
            return None

    @property
    def all_production_stations(self):
        """
        Returns all production stations applicable to this product,
        considering inheritance: Type -> Family -> Series -> Model override.
        """
        from apps.production.models import ProductionRoute
        return ProductionRoute.get_stations_for_product(self)

    @property
    def available_frames(self):
        if not self.has_frame:
            return Material.objects.none()

        bom = self.effective_bom
        if not bom:
            return Material.objects.none()

        if bom.frame and bom.frame.common_name:
            return Material.objects.filter(common_name=bom.frame.common_name).order_by('name')

        if bom.frame:
            return Material.objects.filter(id=bom.frame.id)

        return Material.objects.none()

    @property
    def frame_colors(self):
        """Deprecated: use available_frames instead"""
        return Color.objects.filter(
            id__in=self.available_frames.filter(color__isnull=False).values_list('color_id', flat=True).distinct(),
            active=True)


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
    product_types = models.ManyToManyField(
        "ProductType",
        blank=True,
        related_name="customizers",
        verbose_name="סוגי מוצרים",
    )
    product_families = models.ManyToManyField(
        "ProductFamily",
        blank=True,
        related_name="customizers",
        verbose_name="משפחות מוצרים",
    )
    product_models = models.ManyToManyField(
        "ProductModel",
        blank=True,
        related_name="customizers",
        verbose_name="דגמי מוצרים",
    )

    hardware = models.ForeignKey(
        Hardware,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customizers",
        verbose_name="פרזול (Hardware)",
        help_text="קישור ישיר לפריט במחסן להזמנה אוטומטית",
    )

    # --- Engine/Pipeline settings (Strategy & Chain of Responsibility) ---
    tag = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name="תג / אלגוריתם",
        help_text="מזהה אסטרטגיית עיבוד בקוד",
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

    par5_label = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="פרמטר 5: תווית",
    )
    par5_value = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="פרמטר 5: ערך ברירת מחדל",
    )
    par5_hint = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="פרמטר5: רמז",
    )

    par1_options = models.TextField(
        blank=True,
        null=True,
        verbose_name="פרמטר 1: אפשרויות",
        help_text="Options separated by commas. Use SKU=prefix:LABEL for inventory (e.g. SKU=hrdw121-12: צילינדר) or KEY:LABEL for generic values (e.g. NONE: ללא, WC: תפוס/פנוי).",
    )
    par2_options = models.TextField(
        blank=True,
        null=True,
        verbose_name="פרמטר 2: אפשרויות",
        help_text="Options separated by commas. Use SKU=prefix:LABEL for inventory (e.g. SKU=hrdw121-12: צילינדר) or KEY:LABEL for generic values (e.g. NONE: ללא, WC: תפוס/פנוי).",
    )
    par3_options = models.TextField(
        blank=True,
        null=True,
        verbose_name="פרמטר 3: אפשרויות",
        help_text="Options separated by commas. Use SKU=prefix:LABEL for inventory (e.g. SKU=hrdw121-12: צילינדר) or KEY:LABEL for generic values (e.g. NONE: ללא, WC: תפוס/פנוי).",
    )
    par4_options = models.TextField(
        blank=True,
        null=True,
        verbose_name="פרמטר 4: אפשרויות",
        help_text="Options separated by commas. Use SKU=prefix:LABEL for inventory (e.g. SKU=hrdw121-12: צילינדר) or KEY:LABEL for generic values (e.g. NONE: ללא, WC: תפוס/פנוי).",
    )
    par5_options = models.TextField(
        blank=True,
        null=True,
        verbose_name="פרמטר 5: אפשרויות",
        help_text="Options separated by commas. Use SKU=prefix:LABEL for inventory (e.g. SKU=hrdw121-12: צילינדר) or KEY:LABEL for generic values (e.g. NONE: ללא, WC: תפוס/פנוי).",
    )

    materials = models.ManyToManyField(
        Material,
        blank=True,
        related_name="customizers",
        verbose_name='חומרים (Material)',
        help_text="חומרים להחלפה או הוספה במפרט הטכני",
    )

    class Meta:
        db_table = "customizers"
        verbose_name = "קסטומייזר / אפשרות"
        verbose_name_plural = "קסטומייזרים / אפשרויות"
        ordering = ["tag", "code"]

    def __str__(self):
        return f"[{self.code}] {self.name}"

    def get_parameter_options(self, par_number):
        """
        Parses the raw comma-separated option string into a structured list of key-value tuples.
        """
        field_name = f"par{par_number}_options"
        options_str = getattr(self, field_name, "") or ""
        if not options_str:
            return []

        result = []
        for item in options_str.split(','):
            item = item.strip()
            if not item:
                continue
            # Split each item strictly on the first colon (item.split(':', 1))
            parts = item.split(':', 1)
            key = parts[0].strip()
            label = parts[1].strip() if len(parts) > 1 else key
            result.append((key, label))
        return result

    def get_filtered_parameter_options(self, par_number, product_model):
        """
        Returns options for the given parameter, filtering SKU items by product model compatibility.
        """
        options = self.get_parameter_options(par_number)
        if not product_model:
            return options

        filtered = []
        # Pre-fetch all hardware items referenced in SKUs to avoid N+1
        sku_keys = [key for key, _ in options if key.upper().startswith('SKU=')]
        sku_values = [key.split('=', 1)[1].strip() for key in sku_keys]

        hardware_map = {h.sku: h for h in Hardware.objects.filter(sku__in=sku_values)}

        for key, label in options:
            if key.upper().startswith('SKU='):
                sku = key.split('=', 1)[1].strip()
                hw = hardware_map.get(sku)
                if hw:
                    if hw.is_compatible_with(product_model):
                        filtered.append((key, label))
                else:
                    # If SKU doesn't exist in DB, we keep it so clean() can report it, 
                    # OR we could skip it. The PRD says clean() should report invalid SKUs.
                    filtered.append((key, label))
            else:
                # Generic/system choices always available
                filtered.append((key, label))
        return filtered

    def is_available_for(self, product_model):
        """
        Check availability using OR logic across scoping levels.
        Empty sets = Global.
        """
        if not product_model:
            return True

        has_types = self.product_types.exists()
        has_families = self.product_families.exists()
        has_models = self.product_models.exists()

        if not (has_types or has_families or has_models):
            return True

        if has_models:
            if self.product_models.filter(id=product_model.id).exists():
                return True
            if product_model.parent_model and self.product_models.filter(id=product_model.parent_model.id).exists():
                return True

        if has_families and self.product_families.filter(id=product_model.product_family_id).exists():
            return True
        if has_types and self.product_types.filter(id=product_model.product_family.product_type_id).exists():
            return True

        return False

    def clean(self):
        super().clean()
        errors = {}

        skus_to_check = set()
        field_to_skus = {}

        for i in range(1, 6):
            field_name = f"par{i}_options"
            options = self.get_parameter_options(i)
            if not options:
                continue

            field_skus = []
            for key, label in options:
                # Check if key starts with SKU= (case-insensitive)
                if key.upper().startswith('SKU='):
                    # Extract the raw SKU
                    try:
                        raw_sku = key.split('=', 1)[1].strip()
                        field_skus.append(raw_sku)
                        skus_to_check.add(raw_sku)
                    except IndexError:
                        pass
                # Keys without SKU= bypass warehouse validation

            field_to_skus[field_name] = field_skus

        if skus_to_check:
            # Single bulk query to verify existence of all referenced SKUs
            existing_skus = set(
                Hardware.objects.filter(sku__in=skus_to_check).values_list('sku', flat=True)
            )
            for field_name, field_skus in field_to_skus.items():
                invalid_skus = [sku for sku in field_skus if sku not in existing_skus]
                if invalid_skus:
                    errors[field_name] = f"Invalid Hardware SKUs: {', '.join(invalid_skus)}"

        if errors:
            raise ValidationError(errors)
