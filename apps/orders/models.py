import math

from django.db import models
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import ProductModel, Front


class OrderStatus(models.TextChoices):
    NEW = 'NEW', 'חדש'
    IN_PRODUCTION = 'IN_PRODUCTION', 'בייצור'
    IN_PRODUCTION_PHASE1 = 'PHASE1_PRODUCTION', 'ייצור שלב א (משקופים)'
    PHASE1_READY = 'PHASE1_READY', 'שלב א מוכן (ממתין להמשך)'
    IN_PRODUCTION_PHASE2 = 'PHASE2_PRODUCTION', 'ייצור שלב ב'
    READY = 'READY', 'מוכן למשלוח'
    COMPLETED = 'COMPLETED', 'הושלם'
    CANCELED = 'CANCELED', 'בוטל'


class OpeningSide(models.TextChoices):
    LEFT = 'L', 'L'
    RIGHT = 'R', 'R'


class OpeningType(models.TextChoices):
    IN = 'IN', 'פנימה'
    OUT = 'OUT', 'החוצה'


# ==========================================
# 1. ORDER
# ==========================================


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
        default=OrderStatus.NEW,
        db_index=True,
        verbose_name="סטטוס",
    )

    # --- Stage dates ---
    painting_completion_date = models.DateField(
        null=True, blank=True, verbose_name="תאריך סיום צבע"
    )
    phase1_completion_date = models.DateField(
        null=True, blank=True, verbose_name="תאריך סיום שלב א"
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
    handle = models.ForeignKey(
        'catalog.Handle',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="ידית"
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

    # --- Specification Cache and Validation ---
    phase1_validated = models.BooleanField(default=False, verbose_name="שלב א' מאושר")
    phase2_validated = models.BooleanField(default=False, verbose_name="שלב ב' מאושר")
    phase1_spec_cache = models.JSONField(null=True, blank=True, verbose_name="מטמון מפרט שלב א")
    phase2_spec_cache = models.JSONField(null=True, blank=True, verbose_name="מטמון מפרט שלב ב")

    class Meta:
        db_table = "orders"
        verbose_name = "הזמנה"
        verbose_name_plural = "הזמנות"
        ordering = ["-id"]

    def __str__(self):
        return f"הזמנה מס' {self.order_number} ({self.customer or 'ללא לקוח'})"

    def save(self, *args, **kwargs):
        from apps.orders.utils import add_israeli_working_days

        # Approach 3: Freeze state if locked
        if self.pk:
            try:
                old_instance = Order.objects.get(pk=self.pk)
                if old_instance.is_locked:
                    # Allow only status changes or completion dates
                    # In a real app we would compare fields, here we just keep it simple
                    # as per architectural spec.
                    pass
            except Order.DoesNotExist:
                pass

        base_date = self.created_at.date() if self.created_at else timezone.now().date()
        if not self.completion_date:
            self.completion_date = add_israeli_working_days(base_date, 10)
        if not self.painting_completion_date:
            self.painting_completion_date = add_israeli_working_days(base_date, 20)

        # Approach 1: Reset validation on mutation (if not already locked)
        if self.pk and not self.is_locked:
            self.reset_validation()

        super().save(*args, **kwargs)

    def reset_validation(self, phase=None):
        """Resets validation flags and clears spec cache."""
        if phase == 'phase1':
            self.phase1_validated = False
            self.phase1_spec_cache = None
        elif phase == 'phase2':
            self.phase2_validated = False
            self.phase2_spec_cache = None
        else:
            self.phase1_validated = False
            self.phase1_spec_cache = None
            self.phase2_validated = False
            self.phase2_spec_cache = None

    @property
    def is_locked(self):
        """Check if order is in production or completed."""
        return self.status in [
            OrderStatus.IN_PRODUCTION,
            OrderStatus.IN_PRODUCTION_PHASE1,
            OrderStatus.IN_PRODUCTION_PHASE2,
            OrderStatus.PHASE1_READY,
            OrderStatus.READY,
            OrderStatus.COMPLETED,
        ]

    @property
    def has_split_installation(self):
        return self.groups.filter(is_split_installation=True).exists()

    def get_production_stations(self):
        """
        Returns all unique production stations for all items in this order,
        considering their routes and customizers.
        Also filters based on order status for phased production.
        """
        from apps.production.models import ProductionRoute
        all_stations = []
        seen_ids = set()

        # Prefetch groups and their customizers for efficiency
        groups = self.groups.all().prefetch_related('customizers__customizer', 'product__product_family__product_type')

        for group in groups:
            group_stations = ProductionRoute.get_stations_for_group(group)
            for s in group_stations:
                if s.id not in seen_ids:
                    # Filter for staged production
                    if self.status == OrderStatus.IN_PRODUCTION_PHASE1:
                        if not s.is_phase1:
                            continue
                    elif self.status == OrderStatus.IN_PRODUCTION_PHASE2:
                        if s.is_phase1:
                            continue

                    all_stations.append(s)
                    seen_ids.add(s.id)

        return all_stations

    @property
    def available_frames(self):
        if self.series:
            return self.series.available_frames
        from apps.catalog.models import Material
        return Material.objects.all().order_by('name')

    @property
    def available_frame_colors(self):
        """Deprecated: use available_frames instead"""
        if self.series:
            return self.series.frame_colors
        from apps.catalog.models import Color
        return Color.objects.filter(active=True).order_by('id')


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
    basic_color_frames = models.ForeignKey(
        'catalog.Material',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="צבע משקוף בסיסי",
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

    @property
    def available_frames(self):
        if self.product:
            return self.product.available_frames
        if self.series:
            return self.series.available_frames
        if self.order and self.order.series:
            return self.order.series.available_frames
        from apps.catalog.models import Material
        return Material.objects.all().order_by('name')

    @property
    def available_frame_colors(self):
        """Deprecated: use available_frames instead"""
        if self.product:
            return self.product.frame_colors
        if self.series:
            return self.series.frame_colors
        if self.order and self.order.series:
            return self.order.series.frame_colors
        from apps.catalog.models import Color
        return Color.objects.filter(active=True).order_by('id')

    def save(self, *args, **kwargs):
        # Approach 3: Freeze state if order is locked
        if self.order and self.order.is_locked:
            # In a production environment, we should raise a ValidationError
            pass

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

        # Save group and items in one transaction
        with transaction.atomic():
            super().save(*args, **kwargs)

            # Sync physical doors (OrderItems) with group quantity
            if self.quantity is not None:
                # Get existing items for this group
                existing_items = self.items.all().order_by('id')
                current_count = existing_items.count()

                if current_count < self.quantity:
                    # Create missing items
                    items_to_create = [
                        OrderItem(
                            group=self,
                            mark=str(item_index),
                            wall=self.product.product_family.default_value_for_frame or None,
                        )
                        for item_index in range(current_count + 1, self.quantity + 1)
                    ]
                    OrderItem.objects.bulk_create(items_to_create)
                elif current_count > self.quantity:
                    # Remove excess items from the end
                    items_to_delete = existing_items[self.quantity:]
                    OrderItem.objects.filter(id__in=[item.id for item in items_to_delete]).delete()

            # After syncing items in this group, recalculate marks for the entire order
            from apps.production.services import OrderProductionService
            OrderProductionService.recalculate_item_marks(self.order)

            # Approach 1: Reset parent order validation
            if not self.order.is_locked:
                self.order.reset_validation()
                # Save order without triggering its save() logic that might be complex
                type(self.order).objects.filter(pk=self.order.pk).update(
                    phase1_validated=False,
                    phase2_validated=False,
                    phase1_spec_cache=None,
                    phase2_spec_cache=None
                )

    def delete(self, *args, **kwargs):
        order = self.order
        super().delete(*args, **kwargs)
        # After deleting the group, recalculate marks for the remaining items in the order
        from apps.production.services import OrderProductionService
        OrderProductionService.recalculate_item_marks(order)

        # Approach 1: Reset parent order validation
        if not order.is_locked:
            order.reset_validation()
            type(order).objects.filter(pk=order.pk).update(
                phase1_validated=False,
                phase2_validated=False,
                phase1_spec_cache=None,
                phase2_spec_cache=None
            )

    def duplicate(self):
        """
        Creates a duplicate of the current group for the same order.
        Copies group parameters and its customizers.
        Doors (OrderItem) are created empty via standard OrderItemsGroup.save().
        """
        with transaction.atomic():
            new_group = OrderItemsGroup.objects.create(
                order=self.order,
                quantity=self.quantity,
                product=self.product,
                series=self.series,
                front=self.front,
                basic_color_frames=self.basic_color_frames,
                panel_paint_option=self.panel_paint_option,
                color_panels=self.color_panels,
                frame_paint_option=self.frame_paint_option,
                color_frames=self.color_frames,
                is_split_installation=self.is_split_installation,
                comments=self.comments,
            )
            for cust in self.customizers.all():
                OrderItemsGroupCustomizer.objects.create(
                    group=new_group,
                    customizer=cust.customizer,
                    par1=cust.par1,
                    par2=cust.par2,
                    par3=cust.par3,
                    par4=cust.par4
                )
            return new_group


class OrderItemsGroupCustomizer(models.Model):
    group = models.ForeignKey(
        'OrderItemsGroup',
        on_delete=models.CASCADE,
        related_name='customizers',
        verbose_name='קבוצת פריטים'
    )
    customizer = models.ForeignKey(
        'catalog.Customizer',
        on_delete=models.CASCADE,
        verbose_name='קסטומייזר'
    )
    par1 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 1")
    par2 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 2")
    par3 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 3")
    par4 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 4")
    par5 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 5")

    class Meta:
        verbose_name = 'קסטומייזר לקבוצה'
        verbose_name_plural = 'קסטומייזרים לקבוצה'

    def __str__(self):
        return f"{self.group} - {self.customizer.name}"

    def save(self, *args, **kwargs):
        if self.group.order.is_locked:
            pass
        super().save(*args, **kwargs)
        order = self.group.order
        if not order.is_locked:
            order.reset_validation()
            type(order).objects.filter(pk=order.pk).update(
                phase1_validated=False,
                phase2_validated=False,
                phase1_spec_cache=None,
                phase2_spec_cache=None
            )

    def delete(self, *args, **kwargs):
        order = self.group.order
        super().delete(*args, **kwargs)
        if not order.is_locked:
            order.reset_validation()
            type(order).objects.filter(pk=order.pk).update(
                phase1_validated=False,
                phase2_validated=False,
                phase1_spec_cache=None,
                phase2_spec_cache=None
            )


# ==========================================
# 3. PRODUCT (ORDER ITEM)
# ==========================================


class OrderItem(models.Model):
    # --- Link to parent group ---
    group = models.ForeignKey(
        "OrderItemsGroup",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="קבוצת מוצרים",
    )

    mark = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="#",
    )

    # --- Dimensions (in mm) ---
    width = models.DecimalField(
        max_digits=10, decimal_places=1, blank=True, null=True, verbose_name='רוחב (מ""מ)'
    )
    height = models.DecimalField(
        max_digits=10, decimal_places=1, blank=True, null=True, verbose_name='גובה (מ""מ)'
    )
    wall = models.DecimalField(
        max_digits=10, decimal_places=1, blank=True, null=True, verbose_name='עובי קיר / פתח (מ""מ)'
    )

    # --- Structure and Opening ---
    direction = models.CharField(
        max_length=10,
        choices=OpeningSide.choices,
        blank=True,
        null=True,
        verbose_name="כיוון פתיחה",
    )
    opening = models.CharField(
        max_length=10,
        choices=OpeningType.choices,
        blank=True,
        null=True,
        verbose_name="צד פתיחה",
    )
    addition_cut = models.DecimalField(
        max_digits=5,
        decimal_places=1,
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
        decimal_places=1,
        blank=True,
        null=True,
        verbose_name='גובה מנעול מותאם (מ""מ)',
    )
    custom_hinge1 = models.DecimalField(
        max_digits=7,
        decimal_places=1,
        blank=True,
        null=True,
        verbose_name='גובה ציר 1 (מ""מ)',
    )
    custom_hinge2 = models.DecimalField(
        max_digits=7,
        decimal_places=1,
        blank=True,
        null=True,
        verbose_name='גובה ציר 2 (מ""מ)',
    )
    custom_hinge3 = models.DecimalField(
        max_digits=7,
        decimal_places=1,
        blank=True,
        null=True,
        verbose_name='גובה ציר 3 (מ""מ)',
    )
    custom_hinge4 = models.DecimalField(
        max_digits=7,
        decimal_places=1,
        blank=True,
        null=True,
        verbose_name='גובה ציר 4 (מ""מ)',
    )
    custom_hinge5 = models.DecimalField(
        max_digits=7,
        decimal_places=1,
        blank=True,
        null=True,
        verbose_name='גובה ציר 5 (מ""מ)',
    )
    sketch = models.FileField(
        upload_to='order_sketches/%Y/%m/',
        blank=True,
        null=True,
        verbose_name='שרטוט ידני / קובץ',
        help_text='ניתן להעלות PDF, JPEG, PNG וכדומה'
    )

    class Meta:
        db_table = "order_items"
        verbose_name = "פריט הזמנה"
        verbose_name_plural = "פריטי הזמנה"
        ordering = ["id"]

    def __str__(self):
        return f"פריט #{self.id} (קבוצה מס' {self.group_id})"

    def format_decimal(self, value):
        if value is None:
            return ""
        # Truncate to 1 decimal place (already done in save, but just in case)
        val_float = float(value)
        if val_float == int(val_float):
            return str(int(val_float))
        return "{:.1f}".format(val_float)

    @property
    def h_fmt(self):
        return self.format_decimal(self.height)

    @property
    def w_fmt(self):
        return self.format_decimal(self.width)

    @property
    def wall_fmt(self):
        return self.format_decimal(self.wall)

    def save(self, *args, **kwargs):
        # Approach 3: Freeze state if order is locked
        if self.group.order.is_locked:
            # In a production environment, we should raise a ValidationError
            pass

        # Truncate all decimal fields to 1 decimal place
        decimal_fields = [
            'width', 'height', 'wall', 'custom_lock_height',
            'custom_hinge1', 'custom_hinge2', 'custom_hinge3',
            'custom_hinge4', 'custom_hinge5', 'addition_cut'
        ]
        for field in decimal_fields:
            val = getattr(self, field)
            if val is not None:
                f_val = float(val)
                truncated = math.floor(f_val * 10) / 10.0
                setattr(self, field, truncated)

        super().save(*args, **kwargs)

        # Approach 1: Reset parent order validation
        order = self.group.order
        if not order.is_locked:
            order.reset_validation()
            type(order).objects.filter(pk=order.pk).update(
                phase1_validated=False,
                phase2_validated=False,
                phase1_spec_cache=None,
                phase2_spec_cache=None
            )

    def delete(self, *args, **kwargs):
        order = self.group.order
        super().delete(*args, **kwargs)
        if not order.is_locked:
            order.reset_validation()
            type(order).objects.filter(pk=order.pk).update(
                phase1_validated=False,
                phase2_validated=False,
                phase1_spec_cache=None,
                phase2_spec_cache=None
            )


# ==========================================
# 4. GROUP SPECIFICATION (PRESET / TEMPLATE)
# ==========================================

class GroupSpecification(models.Model):
    name = models.CharField(
        max_length=255,
        verbose_name="שם המפרט",
        help_text="שם מזהה למפרט השמור (למשל: דלתות קומה טיפוסית)",
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="תיאור",
    )
    product = models.ForeignKey(
        "catalog.ProductModel",
        on_delete=models.PROTECT,
        related_name="saved_specifications",
        verbose_name="דגם מוצר",
    )
    series = models.ForeignKey(
        'catalog.Series',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="סדרה",
    )
    front = models.ForeignKey(
        'catalog.Front',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="חזית / גימור",
    )
    basic_color_frames = models.ForeignKey(
        'catalog.Material',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="צבע משקוף בסיסי",
    )
    panel_paint_option = models.CharField(
        max_length=20,
        choices=OrderItemsGroup.PaintOption.choices,
        default=OrderItemsGroup.PaintOption.MAIN_COLOR,
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
        choices=OrderItemsGroup.PaintOption.choices,
        default=OrderItemsGroup.PaintOption.NO_PAINT,
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
    )
    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name="כמות דלתות ברירת מחדל",
    )
    comments = models.TextField(
        blank=True,
        null=True,
        verbose_name="הערות",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="נוצר במערכת",
    )
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="נוצר ע\"י",
    )

    class Meta:
        db_table = "group_specifications"
        verbose_name = "מפרט קבוצה שמור"
        verbose_name_plural = "מפרטי קבוצות שמורים"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.product.name})"

    @classmethod
    def create_from_group(cls, group, name, description='', user=None):
        with transaction.atomic():
            spec = cls.objects.create(
                name=name,
                description=description,
                product=group.product,
                series=group.series,
                front=group.front,
                basic_color_frames=group.basic_color_frames,
                panel_paint_option=group.panel_paint_option,
                color_panels=group.color_panels,
                frame_paint_option=group.frame_paint_option,
                color_frames=group.color_frames,
                is_split_installation=group.is_split_installation,
                quantity=group.quantity,
                comments=group.comments,
                created_by=user if user and user.is_authenticated else None,
            )
            for cust in group.customizers.all():
                GroupSpecificationCustomizer.objects.create(
                    specification=spec,
                    customizer=cust.customizer,
                    par1=cust.par1,
                    par2=cust.par2,
                    par3=cust.par3,
                    par4=cust.par4,
                )
            return spec

    def apply_to_group(self, group, update_quantity=False, new_quantity=None):
        with transaction.atomic():
            group.product = self.product
            group.series = self.series
            group.front = self.front
            group.basic_color_frames = self.basic_color_frames
            group.panel_paint_option = self.panel_paint_option
            group.color_panels = self.color_panels
            group.frame_paint_option = self.frame_paint_option
            group.color_frames = self.color_frames
            group.is_split_installation = self.is_split_installation
            if self.comments:
                group.comments = self.comments
            if update_quantity and new_quantity:
                group.quantity = new_quantity
            group.save()

            group.customizers.all().delete()
            for cust in self.customizers.all():
                OrderItemsGroupCustomizer.objects.create(
                    group=group,
                    customizer=cust.customizer,
                    par1=cust.par1,
                    par2=cust.par2,
                    par3=cust.par3,
                    par4=cust.par4,
                )
            return group

    def create_order_group(self, order, quantity=None):
        with transaction.atomic():
            qty = quantity if (quantity is not None and quantity > 0) else self.quantity
            new_group = OrderItemsGroup.objects.create(
                order=order,
                quantity=qty,
                product=self.product,
                series=self.series,
                front=self.front,
                basic_color_frames=self.basic_color_frames,
                panel_paint_option=self.panel_paint_option,
                color_panels=self.color_panels,
                frame_paint_option=self.frame_paint_option,
                color_frames=self.color_frames,
                is_split_installation=self.is_split_installation,
                comments=self.comments,
            )
            for cust in self.customizers.all():
                OrderItemsGroupCustomizer.objects.create(
                    group=new_group,
                    customizer=cust.customizer,
                    par1=cust.par1,
                    par2=cust.par2,
                    par3=cust.par3,
                    par4=cust.par4,
                )
            return new_group


class GroupSpecificationCustomizer(models.Model):
    specification = models.ForeignKey(
        GroupSpecification,
        on_delete=models.CASCADE,
        related_name="customizers",
        verbose_name="מפרט",
    )
    customizer = models.ForeignKey(
        'catalog.Customizer',
        on_delete=models.CASCADE,
        verbose_name="קסטומייזר",
    )
    par1 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 1")
    par2 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 2")
    par3 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 3")
    par4 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 4")
    par5 = models.CharField(max_length=255, blank=True, null=True, verbose_name="5")

    class Meta:
        db_table = "group_specification_customizers"
        verbose_name = "קסטומייזר למפרט"
        verbose_name_plural = "קסטומייזרים למפרט"

    def __str__(self):
        return f"{self.specification.name} - {self.customizer.name}"
