from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.catalog.models import ProductModel, ProductFamily, Front, Customizer, Hardware
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
                                 verbose_name='כיסוי')
    covering_consumption = models.CharField('צריכת כיסוי', max_length=255, default='1', blank=True)

    base = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                             verbose_name='בסיס')
    base_consumption = models.CharField('צריכת בסיס', max_length=255, default='1', blank=True)

    filling = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                verbose_name='מילוי')
    filling_consumption = models.CharField('צריכת מילוי', max_length=255, default='1', blank=True)

    panel_frame = models.ForeignKey('catalog.Material', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+',
                                    verbose_name='מסגרת עץ')
    panel_frame_consumption = models.CharField('צריכת מסגרת עץ', max_length=255, default='1', blank=True)

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

    # --- Hardware Sections ---
    lock = models.ForeignKey('catalog.Hardware', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                             verbose_name='מנעול')
    hinges = models.ForeignKey('catalog.Hardware', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               verbose_name='צירים')
    additional = models.ManyToManyField('catalog.Hardware', blank=True, related_name='+',
                                        verbose_name='תוספות')
    required_customizers = models.ManyToManyField(
        'catalog.Customizer',
        blank=True,
        related_name='required_for_boms',
        verbose_name='התאמות אישיות חובה'
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
        verbose_name='מנעולים'
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
        'צעד',
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
        verbose_name='צירים'
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
        return f'{self.hinge_count} צירים {', '.join(str(hinge.name) for hinge in self.hinges.all())} בגובה {self.min_height}-{self.max_height} לדלתות:{", ".join(str(product_families.code) for product_families in self.product_families.all())}'


class ProductionStation(models.Model):
    """
    Production stations or departments (areas / stations).
    """

    class TargetMachine(models.TextChoices):
        NONE = '', 'ללא שיוך למכונה'
        ESSEPIGI = 'ESSEPIGI', 'Essepigi'
        ACCORD_STD = 'ACCORD_STD', 'Accord (סטנדרטי)'
        ACCORD_CUSTOM = 'ACCORD_CUSTOM', 'Accord (מותאם אישית)'

    class SpecType(models.IntegerChoices):
        NONE = 0, 'ללא מפרט'
        LABEL_PRE_CLEANING = 1, 'מדבקה 0: כרסום מקדים'
        LABEL_CLEANING = 2, 'מדבקה 1: כרסום סופי'
        LABEL_FINISHING = 3, 'מדבקה 2: פרזול ומנעול'
        # 4-9: Reserved for future label/special types
        REPORT = 10, 'דו"ח תחנה רגיל'

    name = models.CharField('שם התחנה', max_length=255, unique=True)
    code = models.CharField('קוד תחנה', max_length=50, blank=False, unique=True)
    label = models.CharField('תווית לכפתור', max_length=100, blank=True, help_text='הטקסט שיופיע על הכפתור')
    hint = models.CharField('רמז/תיאור קצר', max_length=255, blank=True, help_text='יופיע כ-tooltip')
    description = models.TextField('תיאור מפורט', blank=True)
    order = models.PositiveIntegerField(
        'סדר תצוגה',
        default=0,
        db_index=True,
    )

    class Meta:
        ordering = ['order', 'id']

    target_machine = models.CharField(
        'מכונת CNC משויכת',
        max_length=32,
        choices=TargetMachine.choices,
        default=TargetMachine.NONE,
        blank=True,
        help_text='סוג המכונה ליצירת קוד QR ופקודות CNC'
    )
    alternative_station = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='primary_stations',
        verbose_name='תחנה חלופית (עומס / מידות חריגות)',
        help_text='תחנה שתחליף את הנוכחית כאשר המידות חורגות (למשל: Accord במקום Essepigi)'
    )

    # --- Type of output / specification ---
    specification_type = models.PositiveSmallIntegerField(
        'סוג מפרט / פלט',
        choices=SpecType.choices,
        default=SpecType.NONE,
        help_text='0 = ללא, 1-3 = מדבקות CNC, 10 = דו"ח מודפס'
    )

    template_name = models.CharField('שם תבנית HTML', max_length=255, blank=True,
                                     help_text='נתיב לקובץ ה-html של הדו"ח')
    is_phase1 = models.BooleanField('שלב א', default=False, help_text='האם תחנה זו שייכת לשלב א (ייצור מקדים/משקופים)')
    active = models.BooleanField('פעיל', default=True)

    class Meta:
        verbose_name = 'תחנת ייצור'
        verbose_name_plural = 'תחנות ייצור'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def has_specification(self) -> bool:
        """Backward compatibility for template button rendering."""
        return self.specification_type != self.SpecType.NONE

    @property
    def is_report(self) -> bool:
        """Station generates a standard printed HTML report."""
        return self.specification_type == self.SpecType.REPORT

    @property
    def is_label(self) -> bool:
        """Station requires a CNC barcode label (types 1, 2, 3)."""
        return 1 <= self.specification_type <= 3

    @property
    def label_type_index(self) -> int | None:
        """
        Maps specification_type to DoorLabel.label_type integer (0, 1, 2).
        SpecType.LABEL_PRE_CLEANING (1) -> 0
        SpecType.LABEL_CLEANING (2) -> 1
        SpecType.LABEL_FINISHING (3) -> 2
        """
        if self.is_label:
            return self.specification_type - 1
        return None


class CustomizerProductionStation(models.Model):
    """
    Production routing rules for catalog customizers.
    """
    customizer = models.ForeignKey(
        'catalog.Customizer',
        on_delete=models.CASCADE,
        related_name='production_station_rules',
        verbose_name='התאמה אישית'
    )
    station = models.ForeignKey(
        'ProductionStation',
        on_delete=models.CASCADE,
        related_name='customizer_rules',
        verbose_name='תחנת ייצור'
    )
    force_alternative_machine = models.BooleanField(
        'העברה למכונה חלופית',
        default=False,
        help_text='אם מסומן, מחייב שימוש בתחנה החלופית (למשל Accord במקום Essepigi)'
    )

    class Meta:
        verbose_name = 'ניתוב התאמה אישית לתחנה'
        verbose_name_plural = 'ניתוב התאמות אישיות לתחנות'


class ProductionRoute(models.Model):
    """
    Technological route (מסלול ייצור / שרשרת טכנולוגית).
    Describes the sequence of stations a product passes through.
    Supports inheritance: Type -> Family -> Series -> Model.
    """
    name = models.CharField('שם המסלול', max_length=255, blank=True)

    products = models.ManyToManyField(
        'catalog.ProductModel',  # Замените на 'catalog.Product', если модель называется так
        related_name='production_routes',
        verbose_name='מוצרים',
        blank=True
    )

    active = models.BooleanField('פעיל', default=True)

    class Meta:
        verbose_name = 'מסלול ייצור'
        verbose_name_plural = 'מסלולי ייצור'

    def __str__(self):
        return self.name

    @classmethod
    def get_stations_for_product(cls, product):
        """
        Возвращает список станций для конкретного продукта по прямой связи ManyToMany.
        """

        route = cls.objects.filter(products=product, active=True).first()

        if route:

            # Чистый способ достать станции с сохранением сортировки и без дублей
            route_steps = route.steps.select_related('station').order_by('order')
            stations = []
            for step in route_steps:
                if step.station not in stations:  # Защита от дублей
                    stations.append(step.station)

            return stations

        return []

    @classmethod
    def get_stations_for_group(cls, group):
        """
        Возвращает итоговый упорядоченный список станций для группы:
        1. Всегда первой идет станция верификации (VERIFICATION)
        2. Базовые технологические станции продукта
        3. Дополнительные станции от кастомизаторов
        4. Малярный цех (PAINTING), если требуется покраска
        """
        if not group.product:
            return []

        stations = []
        station_ids = set()

        def add_station(st):
            if st and st.id not in station_ids:
                stations.append(st)
                station_ids.add(st.id)

        # 1. Первая станция — всегда верификация
        verification = ProductionStation.objects.filter(code='VERIFICATION', active=True).first()
        add_station(verification)

        # 2. Базовые станции маршрута продукта
        for st in cls.get_stations_for_product(group.product):
            add_station(st)

        # 3. Станции от кастомизаторов группы
        for gc in group.customizers.all():
            customizer = gc.customizer
            c_station = getattr(customizer, 'production_station', None)
            add_station(c_station)

        # 4. Проверка необходимости покраски
        from apps.orders.models import OrderItemsGroup
        needs_paint = (
                group.panel_paint_option != OrderItemsGroup.PaintOption.NO_PAINT
                or group.frame_paint_option != OrderItemsGroup.PaintOption.NO_PAINT
        )
        if needs_paint:
            painting = ProductionStation.objects.filter(code__in=['PAINTING', 'PAINT'], active=True).first()
            add_station(painting)

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
        PRE_ROUGHING = 0, 'ניתוב היקפי ראשוני (לפני קנט פנימי)'
        ROUGHING = 1, 'ניתוב היקפי סטנדרטי'
        FINISHING = 2, 'פרזול ומנעולים'

    class LeafRole(models.IntegerChoices):
        SINGLE = 0, 'בודדת'
        ACTIVE = 1, 'פעילה (דומיננטית)'
        PASSIVE = 2, 'פסיבית (משנית)'

    leaf_role = models.PositiveSmallIntegerField(
        'סוג כנף',
        choices=LeafRole.choices,
        default=LeafRole.SINGLE,
        db_index=True
    )

    # Target CNC machines
    class TargetMachine(models.TextChoices):
        ESSEPIGI = 'ESSEPIGI', 'Essepigi'
        ACCORD_STD = 'ACCORD_STD', 'Accord (ספרייה)'
        ACCORD_CUSTOM = 'ACCORD_CUSTOM', 'Accord (פרויקט ידני)'

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='door_labels', verbose_name='הזמנה'
    )
    order_item = models.ForeignKey(
        OrderItem, on_delete=models.CASCADE, related_name='labels', verbose_name='פריט הזמנה'
    )

    # Context & Counters
    order_number = models.CharField('מספר הזמנה', max_length=64, db_index=True)
    client_name = models.CharField('שם לקוח', max_length=255, blank=True, default='')
    item_mark = models.CharField('סימון פריט', max_length=32)
    total_items = models.PositiveIntegerField('סך הפריטים', default=1)
    label_type = models.IntegerField('סוג מדבקה', choices=LabelType.choices, default=LabelType.ROUGHING)
    print_count = models.PositiveIntegerField('מספר הדפסות', default=0)
    last_printed_at = models.DateTimeField('הודפס לאחרונה', null=True, blank=True)

    # Geometry & Specs
    width = models.FloatField('רוחב', null=True, blank=True)
    height = models.FloatField('גובה', null=True, blank=True)
    thickness = models.FloatField('עובי', null=True, blank=True)
    direction = models.CharField('כיוון', max_length=32, blank=True, default='')
    opening = models.CharField('פתיחה', max_length=32, blank=True, default='')
    edge_type = models.CharField('סוג קנט', max_length=64, blank=True, default='')
    is_paint = models.BooleanField('צביעה', default=False)

    # Hardware & Addons
    lock_name = models.CharField('שם מנעול', max_length=128, blank=True, default='')
    lock_height = models.FloatField('גובה מנעול', null=True, blank=True)
    hinge_name = models.CharField('שם ציר', max_length=128, blank=True, default='')
    hinge_1 = models.FloatField('ציר 1', null=True, blank=True)
    hinge_2 = models.FloatField('ציר 2', null=True, blank=True)
    hinge_3 = models.FloatField('ציר 3', null=True, blank=True)
    hinge_4 = models.FloatField('ציר 4', null=True, blank=True)
    hinge_5 = models.FloatField('ציר 5', null=True, blank=True)
    addons_summary = models.TextField('סיכום תוספות', blank=True, default='')
    icon_filename = models.CharField('שם קובץ אייקון', max_length=128, blank=True, default='')
    comment = models.TextField('הערה', blank=True, default='')

    # CNC & Payload
    target_machine = models.CharField(
        'מכונת CNC משויכת', max_length=32, choices=TargetMachine.choices, default=TargetMachine.ACCORD_STD
    )
    qr_payload = models.TextField('מטען QR', blank=True, default='')
    created_at = models.DateTimeField('זמן יצירה', auto_now_add=True)

    # CNC programs and parameters
    cnc_program = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="תוכנית עיבוד היקפי (CNC)",
    )
    edge_shape = models.BooleanField(
        default=False,
        verbose_name="צורת קנט (edge_shape)",
    )
    lock_program = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="תוכנית מנעול (CNC)",
    )
    hinge_program = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="תוכנית צירים (CNC)",
    )
    front_program = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="תוכנית חריטה/חזית (CNC)",
    )
    customizer_programs = models.TextField(
        blank=True,
        default="",
        verbose_name="תוכניות קסטומייזרים",
    )

    # Granular customizer programs (up to 10 for label templates)
    cmz_prg_1 = models.CharField(max_length=100, blank=True, default="")
    cmz_prg_2 = models.CharField(max_length=100, blank=True, default="")
    cmz_prg_3 = models.CharField(max_length=100, blank=True, default="")
    cmz_prg_4 = models.CharField(max_length=100, blank=True, default="")
    cmz_prg_5 = models.CharField(max_length=100, blank=True, default="")
    cmz_prg_6 = models.CharField(max_length=100, blank=True, default="")
    cmz_prg_7 = models.CharField(max_length=100, blank=True, default="")
    cmz_prg_8 = models.CharField(max_length=100, blank=True, default="")
    cmz_prg_9 = models.CharField(max_length=100, blank=True, default="")
    cmz_prg_10 = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        verbose_name = 'תווית דלת'
        verbose_name_plural = 'תוויות דלתות'
        ordering = ['item_mark', 'leaf_role', 'label_type']
        indexes = [
            models.Index(fields=['order_number', 'print_count']),
            models.Index(fields=['order', 'label_type']),
            models.Index(fields=['order_number', 'item_mark', 'leaf_role', 'label_type']),
        ]

    def __str__(self):
        return f"{self.order_number} - פריט {self.item_mark} (סוג {self.label_type})"


class SvgPattern(models.Model):
    """Библиотека векторных SVG-паттернов для текстурной заливки блоков."""
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="מזהה (slug)",
        help_text="מפתח באנגלית למזהה ה-SVG (לדוגמה: foam, tubular, honeycomb)"
    )
    title = models.CharField(max_length=100, verbose_name="שם")
    width = models.PositiveIntegerField(default=20, verbose_name="רוחב אריח (px)")
    height = models.PositiveIntegerField(default=20, verbose_name="גובה אריח (px)")
    svg_content = models.TextField(
        verbose_name="תוכן SVG פנימי",
        help_text="תגיות rect, circle, path, line ללא תגית העטיפה <pattern>"
    )

    class Meta:
        verbose_name = "תבנית SVG"
        verbose_name_plural = "תבניות SVG"
        ordering = ['title']

    def __str__(self):
        return f"{self.title} ({self.name})"


class PuzzleBlockPrototype(models.Model):
    """Справочник визуальных прототипов блоков (внешний вид)."""

    class FillType(models.TextChoices):
        SOLID = 'SOLID', 'צבע אחיד'
        PATTERN = 'PATTERN', 'תבנית SVG'

    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="קוד אב טיפוס",
        help_text="לדוגמה: pine_timber, green_hdf, tubular_core"
    )
    name = models.CharField(max_length=100, verbose_name="שם")
    fill_type = models.CharField(
        max_length=10,
        choices=FillType.choices,
        default=FillType.SOLID,
        verbose_name="סוג מילוי"
    )
    fill_color = models.CharField(
        max_length=30,
        default="#fab005",
        verbose_name="צבע מילוי (HEX)"
    )
    pattern = models.ForeignKey(
        SvgPattern,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="block_prototypes",
        verbose_name="תבנית"
    )
    border_color = models.CharField(max_length=30, default="#000000", verbose_name="צבע גבול")
    border_width = models.FloatField(default=1.0, verbose_name="עובי גבול")
    border_dasharray = models.CharField(max_length=30, blank=True, default="", verbose_name="קו מקווקו")
    opacity = models.FloatField(default=1.0, verbose_name="אטימות (0.0 - 1.0)")
    default_text_color = models.CharField(max_length=30, default="#000000", verbose_name="צבע טקסט")
    default_font_size = models.PositiveSmallIntegerField(default=11, verbose_name="גודל גופן")

    class Meta:
        verbose_name = "אב טיפוס של בלוק פאזל"
        verbose_name_plural = "אבות טיפוס של בלוקי פאזל"

    def __str__(self):
        return f"{self.name} [{self.code}]"


class PuzzlePreset(models.Model):
    """
    Эскиз/пиктограмма узла. Содержит правила генерации блоков
    для анфаса и торца.
    """
    name = models.CharField(max_length=100, unique=True, verbose_name="שם פריסט")
    description = models.TextField(blank=True, verbose_name="תיאור")

    # Список словарей с вызовами прототипов и координатами
    # [{"component": "pine_timber", "view": "face", "x": 0, "y": 0, "w": 8, "h": 200, "order": 20}, ...]
    blocks_config = models.JSONField(
        default=list,
        blank=True,
        verbose_name="הגדרת בלוקים"
    )

    class Meta:
        verbose_name = "פריסט צומת (פיקטוגרמה)"
        verbose_name_plural = "פריסטים של צמתים (פיקטוגרמות)"

    def __str__(self):
        return self.name


class CustomizerPuzzleMapping(models.Model):
    """
    Производственное правило отрисовки для кастомизатора.
    Связывает коммерческий кастомизатор с пресетом и определяет действие со слотом.
    """

    class SlotAction(models.TextChoices):
        ADD = 'ADD', 'הוספה'
        REPLACE = 'REPLACE', 'החלפה'
        REMOVE = 'REMOVE', 'הסרה'

    customizer = models.OneToOneField(
        'catalog.Customizer',
        on_delete=models.CASCADE,
        related_name='puzzle_mapping',
        verbose_name="התאמה אישית"
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
        verbose_name = "מיפוי פיקטוגרמה להתאמה אישית"
        verbose_name_plural = "מיפויי פיקטוגרמות להתאמות אישיות"

    def __str__(self):
        return f"{self.customizer.name} -> {self.preset.name if self.preset else 'ללא פיקטוגרמה'}"


######################################
# Tracking orders in production line #
######################################


class StationStatus(models.TextChoices):
    PENDING = 'PENDING', 'ממתין'
    IN_PROGRESS = 'IN_PROGRESS', 'בעבודה'
    COMPLETED = 'COMPLETED', 'הושלם'
    SKIPPED = 'SKIPPED', 'דולג'


class StationProgressSource(models.TextChoices):
    MANUAL = 'MANUAL', 'ידנית (מתאם)'
    SCANNER = 'SCANNER', 'סורק משרדי (QR של הדף)'
    AGENT = 'AGENT', 'סוכן מחשב (מכונה)'
    TERMINAL = 'TERMINAL', 'מסוף ייצור'


class ItemStationProgress(models.Model):
    """
    Отслеживание прохождения конкретного изделия (OrderItem) через участок (ProductionStation).
    Базовый квант трекинга Фазы 2.
    """
    item = models.ForeignKey(
        'orders.OrderItem',
        on_delete=models.CASCADE,
        related_name='station_progress',
        verbose_name='פריט הזמנה'
    )
    station = models.ForeignKey(
        'production.ProductionStation',
        on_delete=models.CASCADE,
        related_name='items_progress',
        verbose_name='תחנה'
    )
    sequence = models.PositiveSmallIntegerField(
        default=1,
        verbose_name='מספר סידורי של שלב',
        help_text='סדר התחנה במסלול של הקבוצה'
    )
    status = models.CharField(
        max_length=20,
        choices=StationStatus.choices,
        default=StationStatus.PENDING,
        db_index=True,
        verbose_name='סטטוס'
    )
    source = models.CharField(
        max_length=20,
        choices=StationProgressSource.choices,
        default=StationProgressSource.MANUAL,
        verbose_name='מקור הסימון'
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='זמן התחלה'
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name='זמן סיום'
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='completed_station_progress',
        verbose_name='מפעיל / מתאם'
    )

    class Meta:
        db_table = 'production_item_station_progress'
        verbose_name = 'התקדמות פריט בתחנה'
        verbose_name_plural = 'התקדמות פריטים בתחנות'
        unique_together = ('item', 'station', 'sequence')
        ordering = ['sequence', 'id']
        indexes = [
            models.Index(fields=['station', 'status']),
            models.Index(fields=['completed_at']),
        ]

    def __str__(self):
        return f"{self.item} @ {self.station.code} [{self.get_status_display()}]"

    def mark_in_progress(self, user=None, source=StationProgressSource.MANUAL):
        """Переводит позицию в работу."""
        if self.status == StationStatus.PENDING:
            self.status = StationStatus.IN_PROGRESS
            self.started_at = timezone.now()
            self.source = source
            if user and user.is_authenticated:
                self.completed_by = user
            self.save(update_fields=['status', 'started_at', 'source', 'completed_by'])

    def mark_completed(self, user=None, source=StationProgressSource.MANUAL):
        """Отмечает позицию как выполненную."""
        self.status = StationStatus.COMPLETED
        self.completed_at = timezone.now()
        if not self.started_at:
            self.started_at = self.completed_at
        self.source = source
        if user and user.is_authenticated:
            self.completed_by = user
        self.save(update_fields=['status', 'started_at', 'completed_at', 'source', 'completed_by'])

    def reset_status(self):
        """Сброс отметки в исходное состояние при отмене или ошибке сканирования."""
        self.status = StationStatus.PENDING
        self.started_at = None
        self.completed_at = None
        self.completed_by = None
        self.source = StationProgressSource.MANUAL
        self.save(update_fields=['status', 'started_at', 'completed_at', 'completed_by', 'source'])


class StationDailySheetLog(models.Model):
    """
    Журнал выданных в цех сменных агрегатных отчетов по станциям.
    Фиксирует факт печати листа на смену для контроля переходящих остатков.
    """
    station = models.ForeignKey(
        'production.ProductionStation',
        on_delete=models.CASCADE,
        related_name='daily_sheet_logs',
        verbose_name='תחנה'
    )
    sheet_date = models.DateField(
        default=timezone.now,
        db_index=True,
        verbose_name='תאריך משמרת'
    )
    printed_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='זמן הדפסה'
    )
    printed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name='הודפס על ידי'
    )
    notes = models.TextField(
        blank=True,
        verbose_name='הערות'
    )

    class Meta:
        db_table = 'production_station_daily_log'
        verbose_name = 'יומן משמרת תחנה'
        verbose_name_plural = 'יומני משמרת תחנות'
        ordering = ['-sheet_date', '-printed_at']

    def __str__(self):
        return f"{self.station.code} - {self.sheet_date}"


class StationScanAuditLog(models.Model):
    """
    Аудит-лог каждого действия сканирования или запроса от локального агента.
    Позволяет разбирать конфликтные ситуации («почему заказ не отметился»).
    """
    raw_payload = models.CharField(
        max_length=255,
        verbose_name='קוד גולמי / מטען'
    )
    station_code = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='קוד תחנה'
    )
    order_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='מספר הזמנה'
    )
    batch_number = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name='מספר אצווה'
    )
    item_mark = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='סימון פריט'
    )
    source = models.CharField(
        max_length=20,
        choices=StationProgressSource.choices,
        default=StationProgressSource.SCANNER,
        verbose_name='מקור'
    )
    is_success = models.BooleanField(
        default=True,
        verbose_name='הצלחה'
    )
    message = models.TextField(
        blank=True,
        verbose_name='תוצאה / טקסט שגיאה'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name='זמן אירוע'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name='משתמש'
    )

    class Meta:
        db_table = 'production_station_scan_audit'
        verbose_name = 'ביקורת סריקת תחנה'
        verbose_name_plural = 'ביקורות סריקת תחנות'
        ordering = ['-created_at']

    def __str__(self):
        status_flag = "OK" if self.is_success else "ERR"
        return f"[{status_flag}] {self.raw_payload} ({self.created_at:%d.%m %H:%M})"


class PerimeterRoutingFile(models.Model):
    # File name scanned by the CNC barcode reader
    file_name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="שם קובץ",
    )
    # Short human-readable description for operators
    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="תיאור",
    )
    # Machine-specific flag defining edge geometry
    edge_shape = models.BooleanField(
        default=False,
        verbose_name="צורת קנט (edge_shape)",
    )
    # Associated door models for type 1 stickers
    doors = models.ManyToManyField(
        "catalog.ProductFamily",
        blank=True,
        related_name="perimeter_routings",
        verbose_name="משפחת מוצרים",
    )

    class Meta:
        ordering = ["id"]
        verbose_name = "קובץ ניתוב היקפי"
        verbose_name_plural = "קבצי ניתוב היקפי"

    def __str__(self):
        if self.description:
            return f"{self.file_name} ({self.description})"
        return self.file_name


class HardwareMacroFile(models.Model):
    # Macro or program file name recognized by the CNC machine
    file_name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="שם קובץ / מאקרו",
    )
    # Short human-readable description for operators
    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="תיאור",
    )
    # Locks, hinges, and other hardware using this macro
    hardware = models.ManyToManyField(
        "catalog.Hardware",  # Replace with your actual hardware model name
        blank=True,
        related_name="macro_files",
        verbose_name="פרזול",
    )
    # Door families where this specific macro applies
    door_families = models.ManyToManyField(
        "catalog.ProductFamily",
        blank=True,
        related_name="hardware_macro_files",
        verbose_name="משפחות דלתות",
    )

    class Meta:
        ordering = ["file_name"]
        verbose_name = "קובץ מאקרו פרזול"
        verbose_name_plural = "קבצי מאקרו פרזול"

    def __str__(self):
        if self.description:
            return f"{self.file_name} ({self.description})"
        return self.file_name


class CustomizerMacroFile(models.Model):
    # Strict 1:1 relation to the customizer (e.g. specific window cutout)
    customizer = models.OneToOneField(
        "catalog.Customizer",  # Replace with your actual Customizer model name
        on_delete=models.CASCADE,
        related_name="macro_file",
        verbose_name="התאמה אישית",
    )
    # CNC program file name
    file_name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="שם קובץ / מאקרו",
    )
    # Short human-readable description for operators
    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="תיאור",
    )

    class Meta:
        ordering = ["file_name"]
        verbose_name = "קובץ התאמה אישית"
        verbose_name_plural = "קבצי התאמות אישיות"

    def __str__(self):
        if self.description:
            return f"{self.file_name} ({self.description})"
        return self.file_name


class FrontEngravingFile(models.Model):
    # Strict 1:1 relation to the door front / pattern
    front = models.OneToOneField(
        "catalog.Front",
        on_delete=models.CASCADE,
        related_name="engraving_file",
        verbose_name="חזית / דוגמה",
    )
    # CNC program file name for engraving
    file_name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="שם קובץ / מאקרו",
    )
    # Short human-readable description for operators
    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="תיאור",
    )

    class Meta:
        ordering = ["file_name"]
        verbose_name = "קובץ חריטה לחזית"
        verbose_name_plural = "קבצי חריטה לחזיתות"

    def __str__(self):
        if self.description:
            return f"{self.file_name} ({self.description})"
        return self.file_name
