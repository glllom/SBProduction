from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.orders.models import Order, OrderItem


class OrderStationNote(models.Model):
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='station_notes',
                              verbose_name='הזמנה')
    station = models.ForeignKey('engineering.ProductionStation', on_delete=models.CASCADE, related_name='order_notes',
                                verbose_name='תחנת ייצור')
    comment = models.TextField('הערה לדו"ח', blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='עודכן לאחרונה')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name='עודכן ע"י')

    class Meta:
        db_table = 'production_order_station_notes'
        verbose_name = 'הערה לדו"ח תחנה'
        verbose_name_plural = 'הערות לדוחות תחנות'
        unique_together = ('order', 'station')

    def __str__(self):
        return f"{self.order.order_number} @ {self.station.code}"


class OrderSpecificationSnapshot(models.Model):
    class SnapshotType(models.TextChoices):
        PHASE1 = 'PHASE1', 'שלב א (משקופים)'
        PHASE2 = 'PHASE2', 'שלב ב (דלתות)'
        PHASE2_COMPLETION = 'PHASE2_COMPLETION', 'השלמות שלב ב'

    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='specification_snapshots',
                              verbose_name='הזמנה')
    snapshot_type = models.CharField(max_length=30, choices=SnapshotType.choices, default=SnapshotType.PHASE1,
                                     verbose_name='סוג סנאפשוט')
    spec_data = models.JSONField(verbose_name='נתוני מפרט (JSON)')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='זמן יצירה')
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name='נוצר על ידי')

    class Meta:
        verbose_name = 'סנאפשוט מפרט הזמנה'
        verbose_name_plural = 'סנאפשוטים של מפרטי הזמנות'
        ordering = ['-created_at']

    def __str__(self):
        return f"סנאפשוט {self.get_snapshot_type_display()} - הזמנה {self.order.order_number} ({self.created_at.strftime('%d/%m/%Y %H:%M')})"


class DoorLabel(models.Model):
    class LabelType(models.IntegerChoices):
        PRE_ROUGHING = 0, 'ניתוב היקפי ראשוני (לפני קנט פנימי)'
        ROUGHING = 1, 'ניתוב היקפי סטנדרטי'
        FINISHING = 2, 'פרזול ומנעולים'

    class LeafRole(models.IntegerChoices):
        SINGLE = 0, 'בודדת'
        ACTIVE = 1, 'פעילה (דומיננטית)'
        PASSIVE = 2, 'פסיבית (משנית)'

    class TargetMachine(models.TextChoices):
        ESSEPIGI = 'ESSEPIGI', 'Essepigi'
        ACCORD_STD = 'ACCORD_STD', 'Accord (ספרייה)'
        ACCORD_CUSTOM = 'ACCORD_CUSTOM', 'Accord (פרויקט ידני)'

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='door_labels', verbose_name='הזמנה')
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='labels',
                                   verbose_name='פריט הזמנה')

    order_number = models.CharField('מספר הזמנה', max_length=64, db_index=True)
    client_name = models.CharField('שם לקוח', max_length=255, blank=True, default='')
    item_mark = models.CharField('סימון פריט', max_length=32)
    total_items = models.PositiveIntegerField('סך הפריטים', default=1)
    leaf_role = models.PositiveSmallIntegerField('סוג כנף', choices=LeafRole.choices, default=LeafRole.SINGLE,
                                                 db_index=True)
    label_type = models.IntegerField('סוג מדבקה', choices=LabelType.choices, default=LabelType.ROUGHING)
    print_count = models.PositiveIntegerField('מספר הדפסות', default=0)
    last_printed_at = models.DateTimeField('הודפס לאחרונה', null=True, blank=True)

    width = models.FloatField('רוחב', null=True, blank=True)
    height = models.FloatField('גובה', null=True, blank=True)
    thickness = models.FloatField('עובי', null=True, blank=True)
    direction = models.CharField('כיוון', max_length=32, blank=True, default='')
    opening = models.CharField('פתיחה', max_length=32, blank=True, default='')
    edge_type = models.CharField('סוג קנט', max_length=64, blank=True, default='')
    is_paint = models.BooleanField('צביעה', default=False)

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

    target_machine = models.CharField('מכונת CNC משויכת', max_length=32, choices=TargetMachine.choices,
                                      default=TargetMachine.ACCORD_STD)
    qr_payload = models.TextField('מטען QR', blank=True, default='')
    created_at = models.DateTimeField('זמן יצירה', auto_now_add=True)

    cnc_program = models.CharField(max_length=100, blank=True, default="", verbose_name="תוכנית עיבוד היקפי (CNC)")
    edge_shape = models.BooleanField(default=False, verbose_name="צורת קנט (edge_shape)")
    lock_program = models.CharField(max_length=100, blank=True, default="", verbose_name="תוכנית מנעול (CNC)")
    hinge_program = models.CharField(max_length=100, blank=True, default="", verbose_name="תוכנית צירים (CNC)")
    front_program = models.CharField(max_length=100, blank=True, default="", verbose_name="תוכנית חריטה/חזית (CNC)")
    customizer_programs = models.TextField(blank=True, default="", verbose_name="תוכניות קסטומייזרים")

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
    item = models.ForeignKey('orders.OrderItem', on_delete=models.CASCADE, related_name='station_progress',
                             verbose_name='פריט הזמנה')
    station = models.ForeignKey('engineering.ProductionStation', on_delete=models.CASCADE,
                                related_name='items_progress', verbose_name='תחנה')
    sequence = models.PositiveSmallIntegerField(default=1, verbose_name='מספר סידורי של שלב',
                                                help_text='סדר התחנה במסלול של הקבוצה')
    status = models.CharField(max_length=50, choices=StationStatus.choices, default=StationStatus.PENDING,
                              db_index=True, verbose_name='סטטוס')
    source = models.CharField(max_length=50, choices=StationProgressSource.choices,
                              default=StationProgressSource.MANUAL, verbose_name='מקור הסימון')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='זמן התחלה')
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name='זמן סיום')
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='completed_station_progress', verbose_name='מפעיל / מתאם')

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
        if self.status == StationStatus.PENDING:
            self.status = StationStatus.IN_PROGRESS
            self.started_at = timezone.now()
            self.source = source
            if user and user.is_authenticated:
                self.completed_by = user
            self.save(update_fields=['status', 'started_at', 'source', 'completed_by'])

    def mark_completed(self, user=None, source=StationProgressSource.MANUAL):
        self.status = StationStatus.COMPLETED
        self.completed_at = timezone.now()
        if not self.started_at:
            self.started_at = self.completed_at
        self.source = source
        if user and user.is_authenticated:
            self.completed_by = user
        self.save(update_fields=['status', 'started_at', 'completed_at', 'source', 'completed_by'])

    def reset_status(self):
        self.status = StationStatus.PENDING
        self.started_at = None
        self.completed_at = None
        self.completed_by = None
        self.source = StationProgressSource.MANUAL
        self.save(update_fields=['status', 'started_at', 'completed_at', 'completed_by', 'source'])


class StationDailySheetLog(models.Model):
    station = models.ForeignKey('engineering.ProductionStation', on_delete=models.CASCADE,
                                related_name='daily_sheet_logs', verbose_name='תחנה')
    sheet_date = models.DateField(default=timezone.now, db_index=True, verbose_name='תאריך משמרת')
    printed_at = models.DateTimeField(auto_now_add=True, verbose_name='זמן הדפסה')
    printed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   verbose_name='הודפס על ידי')
    notes = models.TextField(blank=True, verbose_name='הערות')

    class Meta:
        db_table = 'production_station_daily_log'
        verbose_name = 'יומן משמרת תחנה'
        verbose_name_plural = 'יומני משמרת תחנות'
        ordering = ['-sheet_date', '-printed_at']

    def __str__(self):
        return f"{self.station.code} - {self.sheet_date}"


class StationScanAuditLog(models.Model):
    raw_payload = models.CharField(max_length=255, verbose_name='קוד גולמי / מטען')
    station_code = models.CharField(max_length=50, blank=True, verbose_name='קוד תחנה')
    order_number = models.CharField(max_length=50, blank=True, verbose_name='מספר הזמנה')
    batch_number = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='מספר אצווה')
    item_mark = models.CharField(max_length=20, blank=True, verbose_name='סימון פריט')
    source = models.CharField(max_length=20, choices=StationProgressSource.choices,
                              default=StationProgressSource.SCANNER, verbose_name='מקור')
    is_success = models.BooleanField(default=True, verbose_name='הצלחה')
    message = models.TextField(blank=True, verbose_name='תוצאה / טקסט שגיאה')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='זמן אירוע')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   verbose_name='משתמש')

    class Meta:
        db_table = 'production_station_scan_audit'
        verbose_name = 'ביקורת סריקת תחנה'
        verbose_name_plural = 'ביקורות סריקת תחנות'
        ordering = ['-created_at']

    def __str__(self):
        status_flag = "OK" if self.is_success else "ERR"
        return f"[{status_flag}] {self.raw_payload} ({self.created_at:%d.%m %H:%M})"


# --- Временные реэкспорты для обратной совместимости (уберём на Этапе 4-5) ---
from apps.engineering.models import (  # noqa: E402, F401
    BOM,
    CustomizerMacroFile,
    CustomizerProductionStation,
    CustomizerPuzzleMapping,
    FrontEngravingFile,
    HardwareMacroFile,
    HingeStandardHeight,
    LockStandardHeight,
    PerimeterRoutingFile,
    ProductEngineeringRule,
    ProductionRoute,
    ProductionRouteStep,
    ProductionStation,
    PuzzleBlockPrototype,
    PuzzlePreset,
    SvgPattern,
)
