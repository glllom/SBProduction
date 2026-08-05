from django.db import models
from django.db import transaction

from apps.catalog.models import ProductModel, Front



class OrderStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'טיוטה'
    MEASUREMENT = 'MEASUREMENT', 'ממתין למדידה'
    IN_PRODUCTION = 'IN_PRODUCTION', 'בייצור'
    READY = 'READY', 'מוכן למשלוח'
    COMPLETED = 'COMPLETED', 'הושלם'
    CANCELED = 'CANCELED', 'בוטל'


class OpeningDirection(models.TextChoices):
    LEFT = 'LEFT', 'שמאל'
    RIGHT = 'RIGHT', 'ימין'


class OpeningType(models.TextChoices):
    OUTWARD = 'OUTWARD', 'חוץ'
    INWARD = 'INWARD', 'פנים'


# ==========================================
# 1. ORDER
# ==========================================

from django.db import models

class Order(models.Model):
    # --- Identifiers and base data ---
    order_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="מספר הזמנה",
        help_text="מספר ייחודי (למשל ORD-2026-001)",
    )
    customer = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="לקוח",
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
        db_index=True,
        verbose_name="סטטוס",
    )

    # --- Stage dates ---
    painting_date = models.DateField(
        null=True, blank=True, verbose_name="תאריך צביעה"
    )
    completion_date = models.DateField(
        null=True, blank=True, verbose_name="תאריך סיום"
    )

    # --- Engineering / Specific order properties ---
    series = models.ForeignKey(
        'catalog.Series',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="סדרה"
    )
    front = models.ForeignKey(
        'catalog.Front',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="חזית / גימור"
    )
    is_frames_to_paint = models.BooleanField(
        default=False,
        verbose_name="לצבוע משקופים?",
    )
    color_panels = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="צבע פנלים (כנף)",
    )
    color_frames = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="צבע משקופים",
    )

    # --- Comments and System fields ---
    comments = models.TextField(
        blank=True, null=True, verbose_name="הערות"
    )
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="נוצר במערכת"
    )

    class Meta:
        db_table = "orders"
        verbose_name = "הזמנה"
        verbose_name_plural = "הזמנות"
        ordering = ["-id"]

    def __str__(self):
        return f"הזמנה מס' {self.order_number} ({self.customer or 'ללא לקוח'})"


class OrderChangeLog(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="changelogs",
        verbose_name="הזמנה"
    )
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="משתמש"
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="זמן שינוי")
    field_name = models.CharField(max_length=100, verbose_name="שדה")
    old_value = models.TextField(null=True, blank=True, verbose_name="ערך ישן")
    new_value = models.TextField(null=True, blank=True, verbose_name="ערך חדש")

    class Meta:
        verbose_name = "יומן שינויים"
        verbose_name_plural = "יומני שינויים"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.order.order_number} - {self.field_name}"
# ==========================================
# 2. PRODUCT GROUP (ORDER Items GROUP)
# ==========================================

class OrderItemsGroup(models.Model):
    class PaintOption(models.TextChoices):
        NO_PAINT = 'NO_PAINT', 'לא לצבוע'
        MAIN_COLOR = 'MAIN_COLOR', 'גוון ראשי'
        SPECIAL_COLOR = 'SPECIAL_COLOR', 'גוון מיוחד'

    # Django will automatically create an `order_id` field in the DB
    order = models.ForeignKey(
        "Order",
        on_delete=models.CASCADE,
        related_name="groups",
        verbose_name="הזמנה",
    )

    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name="כמות בקבוצה",
        help_text="מספר פריטים זהים (דלתות) בקבוצה זו",
    )
    product = models.ForeignKey(
        "catalog.ProductModel",
        on_delete=models.PROTECT,
        related_name="order_groups",
        verbose_name="דגם מוצר",
    )
    series = models.ForeignKey(
        'catalog.Series',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="סדרה",
        help_text="אם ריק - יימשך מההזמנה",
    )
    front = models.ForeignKey(
        'catalog.Front',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="חזית / גימור",
        help_text="אם ריק - יימשך מההזמנה",
    )

    panel_paint_option = models.CharField(
        max_length=20,
        choices=PaintOption.choices,
        default=PaintOption.MAIN_COLOR,
        verbose_name="אופציית צביעת פנל",
    )
    color_panels = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="צבע פנלים (כנף)",
    )
    frame_paint_option = models.CharField(
        max_length=20,
        choices=PaintOption.choices,
        default=PaintOption.NO_PAINT,
        verbose_name="אופציית צביעת משקוף",
    )
    color_frames = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="צבע משקופים",
    )

    is_split_installation = models.BooleanField(
        default=False,
        verbose_name="התקנה מפוצלת",
        help_text="True = משקוף וכנף בתאריכים שונים, False = בו זמנית",
    )

    comments = models.TextField(
        blank=True, null=True, verbose_name="הערות"
    )

    class Meta:
        db_table = "order_items_groups"
        verbose_name = "קבוצת פריטי הזמנה"
        verbose_name_plural = "קבוצות פריטי הזמנה"
        ordering = ["id"]

    def __str__(self):
        return f"קבוצה #{self.id} — {self.quantity} יח' (הזמנה ID:{self.order_id})"

    def save(self, *args, **kwargs):
        is_new = self.pk is None  # Check if the record is being created for the first time

        # Pull default values from Parent Order
        if self.order_id:
            if not self.series and getattr(self.order, "series", None):
                self.series = self.order.series
            if not self.front and getattr(self.order, "front", None):
                self.front = self.order.front

            # Logic for Panels
            if self.panel_paint_option == self.PaintOption.MAIN_COLOR:
                self.color_panels = self.order.color_panels
            elif self.panel_paint_option == self.PaintOption.NO_PAINT:
                self.color_panels = None
            # For SPECIAL_COLOR, color_panels should already be set by user

            # Logic for Frames
            if self.frame_paint_option == self.PaintOption.MAIN_COLOR:
                self.color_frames = self.order.color_frames
            elif self.frame_paint_option == self.PaintOption.NO_PAINT:
                self.color_frames = None
            # For SPECIAL_COLOR, color_frames should already be set by user

        # Save group
        super().save(*args, **kwargs)

        # Generate physical doors (OrderItems) when creating a group
        if is_new and self.quantity > 0:
            from .models import OrderItem

            items_to_create = [
                OrderItem(
                    group=self,
                    item_number=item_index,
                    )
                for item_index in range(1, self.quantity + 1)
            ]

            with transaction.atomic():
                OrderItem.objects.bulk_create(items_to_create)

# ==========================================
# 3. PRODUCT (ORDER ITEM)
# ==========================================

class OpeningSide(models.TextChoices):
    LEFT = "LEFT", "שמאל (L)"
    RIGHT = "RIGHT", "ימין (R)"


class OrderItem(models.Model):
    # --- Link to parent group ---
    group = models.ForeignKey(
        "OrderItemsGroup",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="קבוצת פריטים",
    )

    # --- Dimensions (in mm) ---
    width = models.PositiveIntegerField(
        blank=True, null=True, verbose_name='רוחב (מ""מ)'
    )
    height = models.PositiveIntegerField(
        blank=True, null=True, verbose_name='גובה (מ""מ)'
    )
    wall = models.PositiveIntegerField(
        blank=True, null=True, verbose_name='עובי קיר / פתח (מ""מ)'
    )

    # --- Structure and Opening ---
    direction = models.CharField(
        max_length=10,
        choices=OpeningDirection.choices,
        blank=True,
        null=True,
        verbose_name="כיוון פתיחה",
    )
    opening = models.CharField(
        max_length=10,
        choices=OpeningSide.choices,
        blank=True,
        null=True,
        verbose_name="צד פתיחה",
    )
    addition_cut = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="חיתוך / קיצור נוסף",
    )

    # --- Site location ---
    place = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="מיקום התקנה (קומה / ציר / חדר)",
    )
    comment = models.TextField(
        blank=True, null=True, verbose_name="הערה למוצר"
    )

    # --- Engineering customizers (milling heights) ---
    custom_lock_height = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='גובה מנעול מותאם (מ""מ)',
    )
    custom_hinge1 = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='גובה ציר 1 (מ""מ)',
    )
    custom_hinge2 = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='גובה ציר 2 (מ""מ)',
    )
    custom_hinge3 = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='גובה ציר 3 (מ""מ)',
    )
    custom_hinge4 = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='גובה ציר 4 (מ""מ)',
    )
    custom_hinge5 = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='גובה ציר 5 (מ""מ)',
    )

    class Meta:
        db_table = "order_items"
        verbose_name = "פריט הזמנה"
        verbose_name_plural = "פריטי הזמנה"
        ordering = ["id"]

    def __str__(self):
        return f"פריט #{self.id} (קבוצה מס' {self.group_id})"