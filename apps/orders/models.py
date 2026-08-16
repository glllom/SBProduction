import math
from django.db import models
from django.db import transaction

from apps.catalog.models import ProductModel, Front


class OrderStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'טיוטה'
    MEASUREMENT = 'MEASUREMENT', 'ממתין למדידה'
    IN_PRODUCTION = 'IN_PRODUCTION', 'בייצור'
    PHASE1_PRODUCTION = 'PHASE1_PRODUCTION', 'ייצור שלב א (משקופים)'
    PHASE1_READY = 'PHASE1_READY', 'שלב א מוכן (ממתין להמשך)'
    READY = 'READY', 'מוכן למשלוח'
    COMPLETED = 'COMPLETED', 'הושלם'
    CANCELED = 'CANCELED', 'בוטל'


class OpeningSide(models.TextChoices):
    LEFT = 'LEFT', 'L'
    RIGHT = 'RIGHT', 'R'


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
        default=OrderStatus.DRAFT,
        db_index=True,
        verbose_name="סטטוס",
    )

    # --- Stage dates ---
    painting_date = models.DateField(
        null=True, blank=True, verbose_name="תאריך צביעה"
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

    class Meta:
        db_table = "orders"
        verbose_name = "הזמנה"
        verbose_name_plural = "הזמנות"
        ordering = ["-id"]

    def __str__(self):
        return f"הזמנה מס' {self.order_number} ({self.customer or 'ללא לקוח'})"

    @property
    def has_split_installation(self):
        return self.groups.filter(is_split_installation=True).exists()

    def recalculate_item_marks(self):
        """
        Recalculates sequential numbers (mark) for all OrderItems in this order.
        Orders by group.id and then item.id.
        """
        # Prefetch items for efficiency if needed, but OrderItem.objects.filter is clear
        all_items = OrderItem.objects.filter(group__order=self).order_by('group__id', 'id')

        items_to_update = []
        for i, item in enumerate(all_items, start=1):
            new_mark = str(i)
            if item.mark != new_mark:
                item.mark = new_mark
                items_to_update.append(item)

        if items_to_update:
            OrderItem.objects.bulk_update(items_to_update, ['mark'])

    def validate_for_production(self):
        """
        Validates if the order is ready for production.
        If any group has is_split_installation = True, validation is partial.
        Returns (is_valid, errors)
        """
        errors = []
        has_split = self.groups.filter(is_split_installation=True).exists()
        
        # Base order validation
        if not self.order_number:
            errors.append("מספר הזמנה חסר")
        if not self.customer:
            errors.append("שם לקוח חסר")

        for group in self.groups.all():
            # Check basic item data
            items = group.items.all()
            if not items.exists():
                errors.append(f"קבוצה {group.id} ריקה")
            
            for item in items:
                if not item.height or not item.width:
                    errors.append(f"מידות חסרות בפריט {item.mark}")
                
            if group.is_split_installation:
                # Partial validation: series and frames should be defined, panels and handles can wait
                if not group.series and not self.series:
                    errors.append(f"סדרה חסרה בקבוצה {group.id} (שלב א)")
            else:
                # Full validation
                if not group.series and not self.series:
                    errors.append(f"סדרה חסרה בקבוצה {group.id}")
                if not group.front and not self.front:
                    errors.append(f"חזית/גימור חסרה בקבוצה {group.id}")
                if not self.handle:
                    errors.append("ידית לא נבחרה")

        return len(errors) == 0, errors

    def start_production(self, user=None):
        """
        Transitions order to production. Handles split installation phases.
        """
        from apps.production.services import TechnicalSpecService, ProductionDataService
        
        # 1. Validation before production
        all_errors = []
        for group in self.groups.all():
            for item in group.items.all():
                errors = TechnicalSpecService.validate(item)
                all_errors.extend(errors)
        
        if all_errors:
            # We could raise an exception here or handle it as requested.
            # The issue says "я хочу, чтобы после запуска заказа в работу, была валидация данных"
            # It might mean we should prevent transition if validation fails.
            raise ValueError(f"Validation failed for production: {', '.join(all_errors)}")

        old_status = self.status
        has_split = self.groups.filter(is_split_installation=True).exists()

        with transaction.atomic():
            if self.status == OrderStatus.PHASE1_READY:
                # Moving from Phase 1 Ready to full In Production
                self.status = OrderStatus.IN_PRODUCTION
            elif has_split:
                self.status = OrderStatus.PHASE1_PRODUCTION
                # Create sub-orders for split groups
                for group in self.groups.filter(is_split_installation=True):
                    SubOrder.objects.get_or_create(
                        order=self,
                        group=group,
                        phase=SubOrder.Phase.PHASE1,
                        defaults={
                            'status': OrderStatus.IN_PRODUCTION,
                            'completion_date': self.phase1_completion_date
                        }
                    )
            else:
                self.status = OrderStatus.IN_PRODUCTION

            self.save()
            
            # Generate CNC files
            service = ProductionDataService(self)
            service.generate_cnc_files()
            
            # 2. Generate Technical Specs
            for group in self.groups.all():
                for item in group.items.all():
                    spec = TechnicalSpecService.build_spec(item)
                    # Currently we just build it to ensure it works.
                    # In real usage, this will be called when generating reports.

            OrderChangeLog.objects.create(
                order=self,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=self.status
            )

    def start_phase1(self, user=None):
        """
        Explicitly starts Phase A (frames production).
        """
        from apps.production.services import ProductionDataService
        old_status = self.status
        with transaction.atomic():
            self.status = OrderStatus.PHASE1_PRODUCTION
            self.save()

            # Generate CNC files
            service = ProductionDataService(self)
            service.generate_cnc_files()

            OrderChangeLog.objects.create(
                order=self,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=self.status
            )


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
                        )
                        for item_index in range(current_count + 1, self.quantity + 1)
                    ]
                    OrderItem.objects.bulk_create(items_to_create)
                elif current_count > self.quantity:
                    # Remove excess items from the end
                    items_to_delete = existing_items[self.quantity:]
                    OrderItem.objects.filter(id__in=[item.id for item in items_to_delete]).delete()

            # After syncing items in this group, recalculate marks for the entire order
            self.order.recalculate_item_marks()

    def delete(self, *args, **kwargs):
        order = self.order
        super().delete(*args, **kwargs)
        # After deleting the group, recalculate marks for the remaining items in the order
        order.recalculate_item_marks()


class SubOrder(models.Model):
    """
    Represents a specific phase of production for an Order or a Group.
    Used for split installations where frames are produced first.
    """
    class Phase(models.TextChoices):
        PHASE1 = 'PHASE1', 'שלב א (משקופים)'
        PHASE2 = 'PHASE2', 'שלב ב (כנפיים והשאר)'

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="sub_orders",
        verbose_name="הזמנה",
    )
    group = models.ForeignKey(
        OrderItemsGroup,
        on_delete=models.CASCADE,
        related_name="sub_orders",
        null=True, blank=True,
        verbose_name="קבוצה",
    )
    phase = models.CharField(
        max_length=20,
        choices=Phase.choices,
        default=Phase.PHASE1,
        verbose_name="שלב",
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.IN_PRODUCTION,
        verbose_name="סטטוס",
    )
    completion_date = models.DateField(
        null=True, blank=True, verbose_name="תאריך סיום צפוי"
    )
    actual_completion_date = models.DateTimeField(
        null=True, blank=True, verbose_name="תאריך סיום בפועל"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if not is_new and self.status == OrderStatus.COMPLETED and self.phase == self.Phase.PHASE1:
            # When phase 1 suborder is completed, update the main order status
            order = self.order
            if order.status == OrderStatus.PHASE1_PRODUCTION:
                # Check if all other phase 1 suborders are completed
                if not order.sub_orders.filter(phase=self.Phase.PHASE1).exclude(status=OrderStatus.COMPLETED).exists():
                    order.status = OrderStatus.PHASE1_READY
                    order.save()

    class Meta:
        db_table = "sub_orders"
        verbose_name = "תת-הזמנה (שלב)"
        verbose_name_plural = "תת-הזמנות (שלבים)"

    def __str__(self):
        return f"{self.order.order_number} - {self.get_phase_display()}"


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

    class Meta:
        verbose_name = 'קסטומייזר לקבוצה'
        verbose_name_plural = 'קסטומייזרים לקבוצה'

    def __str__(self):
        return f"{self.group} - {self.customizer.name}"


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
        choices=OpeningType.choices,
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
    def h_fmt(self): return self.format_decimal(self.height)
    @property
    def w_fmt(self): return self.format_decimal(self.width)
    @property
    def wall_fmt(self): return self.format_decimal(self.wall)

    def save(self, *args, **kwargs):
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
