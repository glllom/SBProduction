from django.db import models


class ProductionStation(models.Model):
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
        REPORT = 10, 'דו"ח תחנה רגיל'

    name = models.CharField('שם התחנה', max_length=255, unique=True)
    code = models.CharField('קוד תחנה', max_length=50, blank=False, unique=True)
    label = models.CharField('תווית לכפתור', max_length=100, blank=True, help_text='הטקסט שיופיע על הכפתור')
    hint = models.CharField('רמז/תיאור קצר', max_length=255, blank=True, help_text='יופיע כ-tooltip')
    description = models.TextField('תיאור מפורט', blank=True)
    order = models.PositiveIntegerField('סדר תצוגה', default=0, db_index=True)

    target_machine = models.CharField(
        'מכונת CNC משויכת',
        max_length=32,
        default='',
        blank=True,
        help_text='סוג המכונה ליצירת קוד QR ופקודות CNC',
    )
    alternative_station = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='primary_stations',
        verbose_name='תחנה חלופית (עומס / מידות חריגות)',
        help_text='תחנה שתחליף את הנוכחית כאשר המידות חורגות (למשל: Accord במקום Essepigi)',
    )
    specification_type = models.PositiveSmallIntegerField(
        'סוג מפרט / פלט',
        choices=SpecType.choices,
        default=SpecType.NONE,
        help_text='0 = ללא, 1-3 = מדבקות CNC, 10 = דו"ח מודפס',
    )

    report_handler = models.CharField(
        'מודול דו"ח (Handler)',
        max_length=64,
        blank=True,
        default='',
        help_text='מזהה מודול הדו"ח מתוך apps/production/reports (ריק = ברירת מחדל גנרית לפי תבנית)',
    )

    template_name = models.CharField('שם תבנית HTML', max_length=255, blank=True,
                                     help_text='נתיב לקובץ ה-html של הדו"ח')
    is_phase1 = models.BooleanField('שלב א', default=False, help_text='האם תחנה זו שייכת לשלב א (ייצור מקדים/משקופים)')
    active = models.BooleanField('פעיל', default=True)

    class Meta:
        db_table = 'production_productionstation'
        verbose_name = 'תחנת ייצור'
        verbose_name_plural = 'תחנות ייצור'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    @property
    def has_specification(self) -> bool:
        return self.specification_type != self.SpecType.NONE

    @property
    def is_report(self) -> bool:
        return self.specification_type == self.SpecType.REPORT

    @property
    def is_label(self) -> bool:
        return 1 <= self.specification_type <= 3

    @property
    def label_type_index(self) -> int | None:
        return self.specification_type - 1 if self.is_label else None


class CustomizerProductionStation(models.Model):
    customizer = models.ForeignKey(
        'catalog.Customizer',
        on_delete=models.CASCADE,
        related_name='production_station_rules',
        verbose_name='התאמה אישית',
    )
    station = models.ForeignKey(
        ProductionStation,
        on_delete=models.CASCADE,
        related_name='customizer_rules',
        verbose_name='תחנת ייצור',
    )
    force_alternative_machine = models.BooleanField(
        'העברה למכונה חלופית',
        default=False,
        help_text='אם מסומן, מחייב שימוש בתחנה החלופית; אחרת — מוסיף תחנה למסלול הקבוצה',
    )

    class Meta:
        db_table = 'production_customizerproductionstation'
        verbose_name = 'ניתוב התאמה אישית לתחנה'
        verbose_name_plural = 'ניתוב התאמות אישיות לתחנות'


class ProductionRoute(models.Model):
    name = models.CharField('שם המסלול', max_length=255, blank=True)
    products = models.ManyToManyField(
        'catalog.ProductModel',
        related_name='production_routes',
        verbose_name='מוצרים',
        blank=True,
    )
    active = models.BooleanField('פעיל', default=True)

    class Meta:
        db_table = 'production_productionroute'
        verbose_name = 'מסלול ייצור'
        verbose_name_plural = 'מסלולי ייצור'

    def __str__(self):
        return self.name

    @classmethod
    def get_stations_for_product(cls, product):
        route = cls.objects.filter(products=product, active=True).first()
        if not route:
            return []

        stations = []
        seen_ids = set()
        for step in route.steps.select_related('station').order_by('order'):
            if step.station_id not in seen_ids:
                stations.append(step.station)
                seen_ids.add(step.station_id)
        return stations

    @classmethod
    def get_stations_for_group(cls, group):
        """
        Упорядоченный маршрут группы:
        1. VERIFICATION (всегда первая)
        2. Базовые станции маршрута продукта
        3. Дополнительные станции от кастомизаторов (CustomizerProductionStation с force_alternative_machine=False)
        4. PAINTING (если требуется покраска полотна или коробки)
        """
        if not group.product:
            return []

        stations = []
        station_ids = set()

        def add_station(st):
            if st and st.id not in station_ids:
                stations.append(st)
                station_ids.add(st.id)

        verification = ProductionStation.objects.filter(code='VERIFICATION', active=True).first()
        add_station(verification)

        for st in cls.get_stations_for_product(group.product):
            add_station(st)

        customizer_ids = [gc.customizer_id for gc in group.customizers.all() if gc.customizer_id]
        if customizer_ids:
            extra_rules = (
                CustomizerProductionStation.objects.filter(
                    customizer_id__in=customizer_ids,
                    force_alternative_machine=False,
                    station__active=True,
                )
                .select_related('station')
                .order_by('station__order', 'id')
            )
            for rule in extra_rules:
                add_station(rule.station)

        needs_paint = (
                group.panel_paint_option != 'NO_PAINT'
                or group.frame_paint_option != 'NO_PAINT'
        )
        if needs_paint:
            painting = ProductionStation.objects.filter(code__in=['PAINTING', 'PAINT'], active=True).first()
            add_station(painting)

        return stations


class ProductionRouteStep(models.Model):
    route = models.ForeignKey(ProductionRoute, on_delete=models.CASCADE, related_name='steps', verbose_name='מסלול')
    station = models.ForeignKey(ProductionStation, on_delete=models.CASCADE, related_name='route_steps',
                                verbose_name='תחנה')
    order = models.PositiveIntegerField('סדר', default=10)

    class Meta:
        db_table = 'production_productionroutestep'
        verbose_name = 'שלב במסלול'
        verbose_name_plural = 'שלבים במסלול'
        ordering = ['order']

    def __str__(self):
        return f"{self.order}: {self.station.name}"
