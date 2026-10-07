from django.db import models

from apps.catalog.models import ProductModel
from apps.orders.models import Order, OrderItem


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


class BOM(models.Model):
    """
    Bill of Materials (BOM) with structured sections for materials and hardware.
    """
    product = models.OneToOneField(
        ProductModel,
        on_delete=models.CASCADE,
        related_name='bom',
        verbose_name='דגם מוצר'
    )

    # --- Materials Sections ---
    covering = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                 verbose_name='כיסוי (Covering)')
    covering_consumption = models.CharField('צריכת כיסוי', max_length=255, default='1', blank=True)

    base = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                             verbose_name='בסיס (Base)')
    base_consumption = models.CharField('צריכת בסיס', max_length=255, default='1', blank=True)

    filling = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                verbose_name='מילוי (Filling)')
    filling_consumption = models.CharField('צריכת מילוי', max_length=255, default='1', blank=True)

    panel_frame = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+',
                                    verbose_name='מסגרת עץ')
    panel_frame_consumption = models.CharField('צריכת מסגרת עץ', max_length=255, default='1', blank=True)

    # В класс BOM:
    filling_preset = models.ForeignKey(
        'PuzzlePreset', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='פיקטוגרמה: מילוי'
    )
    panel_frame_preset = models.ForeignKey(
        'PuzzlePreset', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='פיקטוגרמה: מסגרת עץ'
    )
    base_preset = models.ForeignKey(
        'PuzzlePreset', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='פיקטוגרמה: בסיס'
    )
    covering_preset = models.ForeignKey(
        'PuzzlePreset', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='פיקטוגרמה: כיסוי'
    )

    casing = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='הלבשה (Casing)')
    casing_consumption = models.CharField('צריכת הלבשה', max_length=255, default='1', blank=True)

    frame = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                              verbose_name='משקוף (Frame)')
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

    # --- Hardware Sections ---
    lock = models.ForeignKey('catalog.Hardware', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                             verbose_name='מנעול (Lock)')
    hinges = models.ForeignKey('catalog.Hardware', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='צירים (Hinges)')
    additional = models.ManyToManyField('catalog.Hardware', blank=True, related_name='+',
                                        verbose_name='תוספות (Additional)')
    required_customizers = models.ManyToManyField(
        'catalog.Customizer',
        blank=True,
        related_name='required_for_boms',
        verbose_name='קסטומייזרים חובה'
    )

    cut_coefficients = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='מקדמי חיתוך חלקים',
        help_text='מילון מקדמי חיתוך חלקים במילימטרים (למשל {"transom_delta": 45})'
    )

    class Meta:
        verbose_name = 'עץ מוצר (BOM)'
        verbose_name_plural = 'עצי מוצר (BOM)'

    def __str__(self):
        return f"BOM: {self.product.name}"


class LockStandardHeight(models.Model):
    """
    Standard lock heights based on door family and door height.
    Calculation: value = base_lock_height + ceil((door_height - base_door_height) / step) * step
    """
    product_families = models.ManyToManyField(
        'catalog.ProductFamily',
        related_name='lock_heights',
        verbose_name='משפחות מוצרים'
    )
    locks = models.ManyToManyField(
        'catalog.Hardware',
        related_name='lock_heights',
        verbose_name='מנעולים (Locks)'
    )
    base_door_height = models.DecimalField(
        'גובה דלת בסיסי',
        max_digits=7,
        decimal_places=2,
        help_text='גובה דלת לייחוס (למשל 2000 מ"מ)'
    )
    base_lock_height = models.DecimalField(
        'גובה מנעול בסיסי',
        max_digits=7,
        decimal_places=2,
        help_text='מיקום המנעול בגובה הבסיסי'
    )
    step = models.DecimalField(
        'צעד (Step)',
        max_digits=7,
        decimal_places=2,
        default=0,
        help_text='שינוי בגובה המנעול לכל יחידת גובה דלת'
    )

    class Meta:
        verbose_name = 'גובה מנעול סטנדרטי'
        verbose_name_plural = 'גבהי מנעול סטנדרטיים'


class HingeStandardHeight(models.Model):
    """
    Standard hinge positions for height intervals.
    """
    product_families = models.ManyToManyField(
        'catalog.ProductFamily',
        related_name='hinge_heights',
        verbose_name='משפחות מוצרים'
    )
    hinges = models.ManyToManyField(
        'catalog.Hardware',
        related_name='hinge_heights',
        verbose_name='צירים (Hinges)'
    )
    min_height = models.DecimalField(
        'גובה מינימלי',
        max_digits=7,
        decimal_places=2,
        help_text='מינימום גובה דלת בטווח'
    )
    max_height = models.DecimalField(
        'גובה מקסימלי',
        max_digits=7,
        decimal_places=2,
        help_text='מקסימום גובה דלת בטווח'
    )

    value1 = models.DecimalField('גובה ציר 1', max_digits=7, decimal_places=2, null=True, blank=True)
    value2 = models.DecimalField('גובה ציר 2', max_digits=7, decimal_places=2, null=True, blank=True)
    value3 = models.DecimalField('גובה ציר 3', max_digits=7, decimal_places=2, null=True, blank=True)
    value4 = models.DecimalField('גובה ציר 4', max_digits=7, decimal_places=2, null=True, blank=True)
    value5 = models.DecimalField('גובה ציר 5', max_digits=7, decimal_places=2, null=True, blank=True)

    hinge_count = models.PositiveSmallIntegerField(
        'כמות צירים',
        default=0,
        editable=False,
        db_index=True
    )

    class Meta:
        verbose_name = 'גובה צירים סטנדרטי'
        verbose_name_plural = 'גבהי צירים סטנדרטיים'

    def save(self, *args, **kwargs):
        # Считаем количество ненулевых/непустых высот
        values = [self.value1, self.value2, self.value3, self.value4, self.value5]
        self.hinge_count = sum(1 for v in values if v is not None and float(v) > 0)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.hinge_count} צירים  בגובה {self.min_height}-{self.max_height}'


class ProductionStation(models.Model):
    """
    Production stations or departments (areas / stations).
    """
    name = models.CharField('שם התחנה', max_length=255)
    code = models.CharField('קוד תחנה', max_length=50, blank=True)
    label = models.CharField('תווית לכפתור', max_length=100, blank=True, help_text='הטקסט שיופיע על הכפתור')
    hint = models.CharField('רמז/תיאור קצר', max_length=255, blank=True, help_text='יופיע כ-tooltip')
    description = models.TextField('תיאור מפורט', blank=True)
    template_name = models.CharField('שם תבנית HTML', max_length=255, blank=True,
                                     help_text='נתיב לקובץ ה-html של הדו"ח')
    has_specification = models.BooleanField('יש מפרט/כפתור', default=True,
                                            help_text='האם להציג כפתור להפקת דו"ח עבור תחנה זו')
    is_phase1 = models.BooleanField('שלב א', default=False, help_text='האם תחנה זו שייכת לשלב א (ייצור מקדים/משקופים)')
    active = models.BooleanField('פעיל', default=True)

    class Meta:
        verbose_name = 'תחנת ייצור'
        verbose_name_plural = 'תחנות ייצור'
        ordering = ['name']

    def __str__(self):
        return self.name


class CustomizerProductionStation(models.Model):
    """
    Links customizers to production stations.
    Example: Customizer 'Japanese Window' adds 'Glazing' station.
    """
    customizer = models.ForeignKey(
        'catalog.Customizer',
        on_delete=models.CASCADE,
        related_name='added_stations',
        verbose_name='קסטומייזר'
    )
    station = models.ForeignKey(
        ProductionStation,
        on_delete=models.CASCADE,
        related_name='customizer_links',
        verbose_name='תחנת ייצור'
    )

    class Meta:
        verbose_name = 'תחנה לקסטומייזר'
        verbose_name_plural = 'תחנות לקסטומייזרים'
        unique_together = ('customizer', 'station')

    def __str__(self):
        return f"{self.customizer.name} -> {self.station.name}"


class ProductionRoute(models.Model):
    """
    Technological route (מסלול ייצור / שרשרת טכנולוגית).
    Describes the sequence of stations a product passes through.
    Supports inheritance: Type -> Family -> Series -> Model.
    """
    name = models.CharField('שם המסלול', max_length=255, blank=True)

    product_type = models.ForeignKey(
        'catalog.ProductType',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='production_routes',
        verbose_name='סוג מוצר'
    )
    product_family = models.ForeignKey(
        'catalog.ProductFamily',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='production_routes',
        verbose_name='משפחת מוצרים'
    )
    series = models.ForeignKey(
        'catalog.Series',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='production_routes',
        verbose_name='סדרה'
    )
    product_model = models.ForeignKey(
        'catalog.ProductModel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='production_routes',
        verbose_name='דגם מוצר'
    )

    active = models.BooleanField('פעיל', default=True)

    class Meta:
        verbose_name = 'מסלול ייצור'
        verbose_name_plural = 'מסלולי ייצור'

    def __str__(self):
        if self.name:
            return self.name
        levels = []
        if self.product_type: levels.append(f"סוג: {self.product_type.name}")
        if self.product_family: levels.append(f"משפחה: {self.product_family.name}")
        if self.series: levels.append(f"סדרה: {self.series.name}")
        if self.product_model: levels.append(f"דגם: {self.product_model.name}")
        return " -> ".join(levels) if levels else f"מסלול #{self.pk}"

    @classmethod
    def get_stations_for_product(cls, product):
        """
        Returns a list of ProductionStation for a given product model, considering inheritance.
        """
        # 1. Check Model override
        model_route = cls.objects.filter(product_model=product, active=True).first()
        if model_route:
            return list(ProductionStation.objects.filter(
                id__in=model_route.steps.values_list('station_id', flat=True)
            ).order_by('route_steps__order'))

        # 2. Collect inherited chain: Type -> Family -> Series
        stations_ids = []

        # Type
        type_route = cls.objects.filter(product_type=product.product_family.product_type, active=True).first()
        if type_route:
            stations_ids.extend(type_route.steps.values_list('station_id', flat=True))

        # Family
        family_route = cls.objects.filter(product_family=product.product_family, active=True).first()
        if family_route:
            stations_ids.extend(family_route.steps.values_list('station_id', flat=True))

        # Series
        if product.series:
            series_route = cls.objects.filter(series=product.series, active=True).first()
            if series_route:
                stations_ids.extend(series_route.steps.values_list('station_id', flat=True))

        # Return unique stations while preserving order would be nice, 
        # but let's just return unique ones for now.
        return list(ProductionStation.objects.filter(id__in=stations_ids, active=True).distinct())

    @classmethod
    def get_stations_for_group(cls, group):
        """
        Returns a list of ProductionStation for an OrderItemsGroup,
        including stations from product hierarchy and from customizers.
        """
        # 1. Base stations from product hierarchy
        stations = cls.get_stations_for_product(group.product)

        # 2. Add stations from customizers
        for group_cust in group.customizers.all().select_related('customizer'):
            added_links = CustomizerProductionStation.objects.filter(
                customizer=group_cust.customizer
            ).select_related('station')
            for link in added_links:
                if link.station.active and link.station not in stations:
                    stations.append(link.station)

        return stations


class ProductionRouteStep(models.Model):
    """
    A single step in a production route.
    """
    route = models.ForeignKey(
        ProductionRoute,
        on_delete=models.CASCADE,
        related_name='steps',
        verbose_name='מסלול'
    )
    station = models.ForeignKey(
        ProductionStation,
        on_delete=models.CASCADE,
        related_name='route_steps',
        verbose_name='תחנה'
    )
    order = models.PositiveIntegerField('סדר', default=10)

    class Meta:
        verbose_name = 'שלב במסלול'
        verbose_name_plural = 'שלבים במסלול'
        ordering = ['order']

    def __str__(self):
        return f"{self.order}: {self.station.name}"


class OrderSpecificationSnapshot(models.Model):
    """
    Stores historical snapshots of order specifications at key milestones
    (e.g., Phase 1, Phase 2, Phase 2 Completion).
    """

    class SnapshotType(models.TextChoices):
        PHASE1 = 'PHASE1', 'שלב א (משקופים)'
        PHASE2 = 'PHASE2', 'שלב ב (דלתות)'
        PHASE2_COMPLETION = 'PHASE2_COMPLETION', 'השלמות שלב ב'

    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.CASCADE,
        related_name='specification_snapshots',
        verbose_name='הזמנה'
    )
    snapshot_type = models.CharField(
        max_length=30,
        choices=SnapshotType.choices,
        default=SnapshotType.PHASE1,
        verbose_name='סוג סנאפשוט'
    )
    spec_data = models.JSONField(
        verbose_name='נתוני מפרט (JSON)'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='זמן יצירה'
    )
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='נוצר על ידי'
    )

    class Meta:
        verbose_name = 'סנאפשוט מפרט הזמנה'
        verbose_name_plural = 'סנאפשוטים של מפרטי הזמנות'
        ordering = ['-created_at']

    def __str__(self):
        return f"סנאפשוט {self.get_snapshot_type_display()} - הזמנה {self.order.order_number} ({self.created_at.strftime('%d/%m/%Y %H:%M')})"


class DoorLabel(models.Model):
    # Label types
    class LabelType(models.IntegerChoices):
        PRE_ROUGHING = 0, 'Черновая обгонка (до вкладного канта)'
        ROUGHING = 1, 'Стандартная обгонка'
        FINISHING = 2, 'Фурнитура и замки'

    # Target CNC machines
    class TargetMachine(models.TextChoices):
        ESSEPIGI = 'ESSEPIGI', 'Essepigi'
        ACCORD_STD = 'ACCORD_STD', 'Accord (Библиотека)'
        ACCORD_CUSTOM = 'ACCORD_CUSTOM', 'Accord (Ручной проект)'

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='door_labels'
    )
    order_item = models.ForeignKey(
        OrderItem, on_delete=models.CASCADE, related_name='labels'
    )

    # Context & Counters
    order_number = models.CharField(max_length=64, db_index=True)
    client_name = models.CharField(max_length=255, blank=True, default='')
    item_mark = models.CharField(max_length=32)
    total_items = models.PositiveIntegerField(default=1)
    label_type = models.IntegerField(choices=LabelType.choices, default=LabelType.ROUGHING)
    print_count = models.PositiveIntegerField(default=0)
    last_printed_at = models.DateTimeField(null=True, blank=True)

    # Geometry & Specs
    width = models.FloatField(null=True, blank=True)
    height = models.FloatField(null=True, blank=True)
    thickness = models.FloatField(null=True, blank=True)
    direction = models.CharField(max_length=32, blank=True, default='')
    opening = models.CharField(max_length=32, blank=True, default='')
    edge_type = models.CharField(max_length=64, blank=True, default='')
    is_paint = models.BooleanField(default=False)

    # Hardware & Addons
    lock_name = models.CharField(max_length=128, blank=True, default='')
    lock_height = models.FloatField(null=True, blank=True)
    hinge_name = models.CharField(max_length=128, blank=True, default='')
    hinge_1 = models.FloatField(null=True, blank=True)
    hinge_2 = models.FloatField(null=True, blank=True)
    hinge_3 = models.FloatField(null=True, blank=True)
    hinge_4 = models.FloatField(null=True, blank=True)
    hinge_5 = models.FloatField(null=True, blank=True)
    addons_summary = models.TextField(blank=True, default='')
    icon_filename = models.CharField(max_length=128, blank=True, default='')
    comment = models.TextField(blank=True, default='')

    # CNC & Payload
    target_machine = models.CharField(
        max_length=32, choices=TargetMachine.choices, default=TargetMachine.ACCORD_STD
    )
    qr_payload = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['item_mark', 'label_type']
        indexes = [
            models.Index(fields=['order_number', 'print_count']),
            models.Index(fields=['order', 'label_type']),
        ]

    def __str__(self):
        return f"{self.order_number} - Item {self.item_mark} (Type {self.label_type})"


class SvgPattern(models.Model):
    """Библиотека векторных SVG-паттернов для текстурной заливки блоков."""
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Идентификатор (slug)",
        help_text="Латинский ключ для SVG ID (например: foam, tubular, honeycomb)"
    )
    title = models.CharField(max_length=100, verbose_name="Название")
    width = models.PositiveIntegerField(default=20, verbose_name="Ширина тайла (px)")
    height = models.PositiveIntegerField(default=20, verbose_name="Высота тайла (px)")
    svg_content = models.TextField(
        verbose_name="Внутренний SVG-контент",
        help_text="Теги rect, circle, path, line без обрамляющего тега <pattern>"
    )

    class Meta:
        verbose_name = "SVG Паттерн"
        verbose_name_plural = "SVG Паттерны"
        ordering = ['title']

    def __str__(self):
        return f"{self.title} ({self.name})"


class PuzzleBlockPrototype(models.Model):
    """Справочник визуальных прототипов блоков (внешний вид)."""

    class FillType(models.TextChoices):
        SOLID = 'SOLID', 'Сплошной цвет'
        PATTERN = 'PATTERN', 'SVG Паттерн'

    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Код прототипа",
        help_text="Например: pine_timber, green_hdf, tubular_core"
    )
    name = models.CharField(max_length=100, verbose_name="Название")
    fill_type = models.CharField(
        max_length=10,
        choices=FillType.choices,
        default=FillType.SOLID,
        verbose_name="Тип заполнения"
    )
    fill_color = models.CharField(
        max_length=30,
        default="#fab005",
        verbose_name="Цвет заливки (HEX)"
    )
    pattern = models.ForeignKey(
        SvgPattern,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="block_prototypes",
        verbose_name="Паттерн"
    )
    border_color = models.CharField(max_length=30, default="#000000", verbose_name="Цвет границы")
    border_width = models.FloatField(default=1.0, verbose_name="Толщина границы")
    border_dasharray = models.CharField(max_length=30, blank=True, default="", verbose_name="Пунктир")
    opacity = models.FloatField(default=1.0, verbose_name="Непрозрачность (0.0 - 1.0)")
    default_text_color = models.CharField(max_length=30, default="#000000", verbose_name="Цвет текста")
    default_font_size = models.PositiveSmallIntegerField(default=11, verbose_name="Размер шрифта")

    class Meta:
        verbose_name = "Прототип блока пазла"
        verbose_name_plural = "Прототипы блоков пазла"

    def __str__(self):
        return f"{self.name} [{self.code}]"


class PuzzlePreset(models.Model):
    """
    Эскиз/пиктограмма узла. Содержит правила генерации блоков
    для анфаса и торца.
    """
    name = models.CharField(max_length=100, unique=True, verbose_name="Название пресета")
    description = models.TextField(blank=True, verbose_name="Описание")

    # Список словарей с вызовами прототипов и координатами
    # [{"component": "pine_timber", "view": "face", "x": 0, "y": 0, "w": 8, "h": 200, "order": 20}, ...]
    blocks_config = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Конфигурация блоков"
    )

    class Meta:
        verbose_name = "Пресет узла (Пиктограмма)"
        verbose_name_plural = "Пресеты узлов (Пиктограммы)"

    def __str__(self):
        return self.name


class CustomizerPuzzleMapping(models.Model):
    """
    Производственное правило отрисовки для кастомизатора.
    Связывает коммерческий кастомизатор с пресетом и определяет действие со слотом.
    """

    class SlotAction(models.TextChoices):
        ADD = 'ADD', 'הוספה (Add blocks)'
        REPLACE = 'REPLACE', 'החלפה (Replace slot)'
        REMOVE = 'REMOVE', 'הסרה (Clear slot)'

    customizer = models.OneToOneField(
        'catalog.Customizer',
        on_delete=models.CASCADE,
        related_name='puzzle_mapping',
        verbose_name="קסטומייזר"
    )
    preset = models.ForeignKey(
        'production.PuzzlePreset',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customizer_mappings',
        verbose_name="פיקטוגרמה"
    )
    slot_action = models.CharField(
        max_length=10,
        choices=SlotAction.choices,
        default=SlotAction.ADD,
        verbose_name="פעולה על סלוט"
    )
    target_slot = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        verbose_name="סלוט יעד",
        help_text="FILLING, FRAME, BASE, COVERING (עבור החלפה או הסרה)"
    )

    class Meta:
        verbose_name = "מיפוי פיקטוגרמה לקסטומייזר"
        verbose_name_plural = "מיפוי פיקטוגרמות לקסטומייזרים"

    def __str__(self):
        return f"{self.customizer.name} -> {self.preset.name if self.preset else 'ללא פיקטוגרמה'}"
