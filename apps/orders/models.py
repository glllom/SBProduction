import math
from datetime import date

from django.core.exceptions import ValidationError
from django.db import models, transaction


class OrderStatus(models.TextChoices):
    NEW = 'NEW', 'חדש'
    IN_PRODUCTION = 'IN_PRODUCTION', 'בייצור'
    PHASE1_PRODUCTION = 'PHASE1_PRODUCTION', 'ייצור שלב א'
    PHASE1_READY = 'PHASE1_READY', 'שלב א מוכן'
    PHASE2_PRODUCTION = 'PHASE2_PRODUCTION', 'ייצור שלב ב'
    COMPLETION_PRODUCTION = 'COMPLETION_PRODUCTION', 'ייצור השלמות'
    PARTIALLY_READY = 'PARTIALLY_READY', 'מוכן חלקית'
    COMPLETED = 'COMPLETED', 'ההזמנה מוכנה'
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
    class WarehouseState(models.IntegerChoices):
        UNINITIALIZED = 0, 'טרם הוכן (חדש)'
        DRAFT = 1, 'טיוטה / בעריכה'
        LOCKED = 2, 'מאושר ונעול'

    warehouse_state = models.PositiveSmallIntegerField(
        choices=WarehouseState.choices,
        default=WarehouseState.UNINITIALIZED,
        verbose_name='מצב תעודת ליקוט',
    )
    warehouse_version = models.PositiveSmallIntegerField(
        default=1,
        verbose_name='גרסת תעודת ליקוט',
    )
    warehouse_locked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='תאריך אישור ליקוט',
    )
    warehouse_locked_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_warehouse_slips',
        verbose_name='אושר ע"י',
    )

    order_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="מספר הזמנה",
        help_text="מספר ייחודי (למשל ORD-2026-001)",
    )
    customer = models.CharField(max_length=255, blank=True, null=True, verbose_name="לקוח")
    status = models.CharField(
        max_length=30,
        choices=OrderStatus.choices,
        default=OrderStatus.NEW,
        db_index=True,
        verbose_name="סטטוס",
    )

    production_start_date = models.DateField(
        null=True, blank=True, verbose_name="ירידה לייצור",
        help_text="תאריך הכניסה הראשון של ההזמנה לייצור",
    )
    completion_date = models.DateField(
        null=True, blank=True, verbose_name="סיום ייצור",
        help_text="תאריך סיום מתוכנן של הייצור במפעל",
    )
    painting_completion_date = models.DateField(
        null=True, blank=True, verbose_name="סיום צבע",
        help_text="תאריך סיום מתוכנן של הצביעה",
    )

    series = models.ForeignKey('catalog.Series', on_delete=models.SET_NULL, blank=True, null=True, verbose_name="סדרה")
    front = models.ForeignKey('catalog.Front', on_delete=models.SET_NULL, blank=True, null=True,
                              verbose_name="חזית / גימור")
    handle = models.ForeignKey(
        'catalog.Hardware',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'role': 'HANDLE', 'active': True},
        verbose_name='ידית',
    )

    is_frames_to_paint = models.BooleanField(default=False, verbose_name="לצבוע משקופים?")
    is_door_inside_different_color = models.BooleanField(default=False, verbose_name="צד שני צבע אחר")
    color_panel_outside = models.CharField(max_length=100, blank=True, null=True, verbose_name="צבע כנף בחוץ ")
    color_panel_inside = models.CharField(max_length=100, blank=True, null=True, verbose_name="צבע כנף בפנים ")
    color_frames = models.CharField(max_length=100, blank=True, null=True, verbose_name="צבע משקופים")

    comments = models.TextField(blank=True, null=True, verbose_name="הערות")
    warehouse_notes = models.TextField(
        'הערות למחסן',
        blank=True,
        default='',
        help_text='הוראות מיוחדות לליקוט (למשל: הלקוח מביא ידיות משלו)',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="נוצר במערכת")
    current_batch = models.PositiveSmallIntegerField(
        default=1,
        help_text="מספר האצווה האחרונה של הייצור ששוחררה",
    )

    class Meta:
        db_table = "orders"
        verbose_name = "הזמנה"
        verbose_name_plural = "הזמנות"
        ordering = ["-id"]

    def __str__(self):
        return f"הזמנה מס' {self.order_number} ({self.customer or 'ללא לקוח'})"

    def is_editable_by(self, user) -> bool:
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or getattr(user, 'role', None) == 'ADMIN':
            return True
        return self.status in [OrderStatus.NEW, OrderStatus.PHASE1_READY]

    def save(self, *args, **kwargs):
        from apps.orders.utils import add_israeli_working_days

        base_date = self.created_at.date() if self.created_at else date.today()
        if not self.completion_date:
            self.completion_date = add_israeli_working_days(base_date, 10)
        if not self.painting_completion_date:
            self.painting_completion_date = add_israeli_working_days(base_date, 20)

        super().save(*args, **kwargs)

    @property
    def has_split_installation(self):
        return self.groups.filter(is_split_installation=True).exclude(
            production_state__in=[
                OrderItemsGroup.ProductionState.WAITING,
                OrderItemsGroup.ProductionState.CANCELED,
            ]
        ).exists()

    def get_production_stations(self):
        from apps.engineering.models import ProductionRoute
        from apps.production.models import OrderStationNote

        all_stations = []
        seen_ids = set()

        notes_map = dict(
            OrderStationNote.objects.filter(order=self).values_list('station_id', 'comment')
        )
        groups = (
            self.groups.exclude(
                production_state__in=[
                    OrderItemsGroup.ProductionState.WAITING,
                    OrderItemsGroup.ProductionState.CANCELED,
                ]
            )
            .prefetch_related('customizers__customizer', 'product__product_family__product_type')
        )

        for group in groups:
            for s in ProductionRoute.get_stations_for_group(group):
                if s.id in seen_ids:
                    continue
                if self.status == OrderStatus.PHASE1_PRODUCTION and not s.is_phase1:
                    continue
                if self.status == OrderStatus.PHASE2_PRODUCTION and s.is_phase1:
                    continue

                s.note_text = notes_map.get(s.id, '')
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
    def can_start_production(self) -> bool:
        if self.status == OrderStatus.CANCELED:
            return False
        if self.status == OrderStatus.PHASE1_READY:
            return self.groups.filter(
                production_state__in=[
                    OrderItemsGroup.ProductionState.NEW,
                    OrderItemsGroup.ProductionState.IN_PRODUCTION,
                ]
            ).exists()
        return self.groups.filter(production_state=OrderItemsGroup.ProductionState.NEW).exists()

    @property
    def production_action_label(self) -> str:
        if self.status == OrderStatus.NEW:
            return "העבר לייצור"
        if self.status == OrderStatus.PHASE1_PRODUCTION:
            return "העבר אצווה לשלב א'"
        if self.status == OrderStatus.PHASE1_READY:
            return "העבר לשלב ב'"
        if self.status in (OrderStatus.COMPLETED, OrderStatus.PARTIALLY_READY):
            return "העבר לייצור השלמות"
        return "העבר אצווה לייצור"

    def get_quantity(self):
        return sum(gr.quantity for gr in self.groups.all())


class OrderChangeLog(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="changelogs", verbose_name="הזמנה")
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="משתמש")
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
# 2. PRODUCT GROUP (ORDER ITEMS GROUP)
# ==========================================

class OrderItemsGroup(models.Model):
    class PaintOption(models.TextChoices):
        NO_PAINT = 'NO_PAINT', 'לא לצבוע'
        MAIN_COLOR = 'MAIN_COLOR', 'גוון ראשי'
        SPECIAL_COLOR = 'SPECIAL_COLOR', 'גוון מיוחד'

    class ProductionState(models.TextChoices):
        NEW = 'NEW', 'חדש'
        WAITING = 'WAITING', 'ממתין'
        IN_PRODUCTION = 'IN_PRODUCTION', 'בייצור'
        COMPLETED = 'COMPLETED', 'הושלם'
        CANCELED = 'CANCELED', 'בוטל'

    batch_number = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="מספר גל השחרור של ההזמנה (1 להזמנה הראשונית, 2 ומעלה לתוספות)",
    )
    order = models.ForeignKey("Order", on_delete=models.CASCADE, related_name="groups", verbose_name="הזמנה")
    production_state = models.CharField(
        max_length=20,
        choices=ProductionState.choices,
        default=ProductionState.NEW,
        db_index=True,
        verbose_name="סטטוס ייצור של הקבוצה",
    )
    batch_date = models.DateField(
        null=True, blank=True,
        verbose_name="תאריך ירידה לייצור (באץ')",
        help_text="תאריך הכניסה של הקבוצה לייצור, נקבע בעת השחרור ואינו משתנה",
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
        'catalog.Series', on_delete=models.SET_NULL, blank=True, null=True,
        verbose_name="סדרה", help_text="אם ריק - יימשך מההזמנה",
    )
    front = models.ForeignKey(
        'catalog.Front', on_delete=models.SET_NULL, blank=True, null=True,
        verbose_name="חזית / גימור", help_text="אם ריק - יימשך מההזמנה",
    )
    basic_color_frames = models.ForeignKey(
        'catalog.Material', on_delete=models.SET_NULL, blank=True, null=True,
        verbose_name="צבע משקוף בסיסי",
    )

    panel_paint_option = models.CharField(
        max_length=20, choices=PaintOption.choices, default=PaintOption.MAIN_COLOR,
        verbose_name="אופציית צביעת כנף",
    )
    is_door_inside_different_color = models.BooleanField(default=False, verbose_name="צדדים שונים (חוץ/פנים)")
    color_panel_outside = models.CharField(max_length=100, blank=True, null=True, verbose_name="צבע כנף חוץ (מיוחד)")
    color_panel_inside = models.CharField(max_length=100, blank=True, null=True, verbose_name="צבע כנף פנים (מיוחד)")

    frame_paint_option = models.CharField(
        max_length=20, choices=PaintOption.choices, default=PaintOption.NO_PAINT,
        verbose_name="אופציית צביעת משקוף",
    )
    color_frames = models.CharField(max_length=100, blank=True, null=True, verbose_name="צבע משקוף (מיוחד)")

    is_split_installation = models.BooleanField(
        default=False,
        verbose_name="התקנה מפוצלת",
        help_text="כן = משקוף וכנף בתאריכים שונים, לא = בו זמנית",
    )
    is_special_detail = models.BooleanField(
        default=False,
        verbose_name="פרט מיוחד",
        help_text="מעביר את מדבקות ה-CNC למצב עבודה של פרט מיוחד",
    )

    has_handle = models.BooleanField('כולל ידית', default=True, editable=False)
    comments = models.TextField(blank=True, null=True, verbose_name="הערות")

    class Meta:
        db_table = "order_items_groups"
        verbose_name = "קבוצת פריטי הזמנה"
        verbose_name_plural = "קבוצות פריטי הזמנה"
        ordering = ["id"]

    def __str__(self):
        return f"קבוצה #{self.id} — {self.quantity} יח' (הזמנה ID:{self.order_id})"

    def __init__(self, *args, **kwargs):
        has_explicit_frame_paint = 'frame_paint_option' in kwargs
        super().__init__(*args, **kwargs)
        if self._state.adding and not has_explicit_frame_paint and self.order_id:
            if getattr(self.order, 'is_frames_to_paint', False):
                self.frame_paint_option = self.PaintOption.MAIN_COLOR
            else:
                self.frame_paint_option = self.PaintOption.NO_PAINT

    @property
    def available_frames(self):
        if self.product:
            return self.product.available_frames
        if self.series:
            return self.series.available_frames
        if self.order and self.order.series:
            return self.order.series.available_frames
        from apps.catalog.models import Material
        return Material.objects.none()

    def auto_populate_required_customizers(self):
        if not self.product:
            return
        for cust in self.product.get_required_customizers():
            if not self.customizers.filter(customizer=cust).exists():
                OrderItemsGroupCustomizer.objects.create(
                    group=self,
                    customizer=cust,
                    par1=cust.par1_value or '',
                    par2=cust.par2_value or '',
                    par3=cust.par3_value or '',
                    par4=cust.par4_value or '',
                    par5=cust.par5_value or '',
                )

    @property
    def effective_color_panel_outside(self):
        if self.panel_paint_option == self.PaintOption.NO_PAINT:
            return None
        if self.panel_paint_option == self.PaintOption.SPECIAL_COLOR and self.color_panel_outside:
            return self.color_panel_outside
        return getattr(self.order, 'color_panel_outside', None)

    @property
    def effective_color_panel_inside(self):
        if self.panel_paint_option == self.PaintOption.NO_PAINT:
            return None
        if self.panel_paint_option == self.PaintOption.SPECIAL_COLOR:
            if self.is_door_inside_different_color and self.color_panel_inside:
                return self.color_panel_inside
            return self.effective_color_panel_outside
        order_inside = getattr(self.order, 'color_panel_inside', None)
        return order_inside or getattr(self.order, 'color_panel_outside', None)

    @property
    def effective_color_frames(self):
        if self.frame_paint_option == self.PaintOption.NO_PAINT:
            return None
        if self.frame_paint_option == self.PaintOption.SPECIAL_COLOR and self.color_frames:
            return self.color_frames
        return getattr(self.order, 'color_frames', None)

    def is_editable_by(self, user=None) -> bool:
        if user and (
                getattr(user, 'is_superuser', False)
                or getattr(user, 'is_admin_user', False)
                or getattr(user, 'role', None) == 'ADMIN'
        ):
            return True
        if self.production_state in (self.ProductionState.NEW, self.ProductionState.WAITING):
            return True
        if not self.batch_date:
            return False
        return self.batch_date == date.today()

    def save(self, *args, **kwargs):
        from apps.orders.services import sync_group_items

        is_new = not self.pk
        update_fields = kwargs.get('update_fields')
        should_sync_items = (
                update_fields is None
                or 'product' in update_fields
                or 'product_id' in update_fields
                or 'quantity' in update_fields
        )

        if self.order_id:
            if not self.series and getattr(self.order, "series", None):
                self.series = self.order.series
            if not self.front and getattr(self.order, "front", None):
                self.front = self.order.front

        if self.panel_paint_option != self.PaintOption.SPECIAL_COLOR:
            self.color_panel_outside = None
            self.color_panel_inside = None
            self.is_door_inside_different_color = False
        elif not self.is_door_inside_different_color:
            self.color_panel_inside = None

        if self.frame_paint_option != self.PaintOption.SPECIAL_COLOR:
            self.color_frames = None

        if self.product_id and should_sync_items:
            product_changed = is_new
            if not is_new:
                old_product_id = (
                    OrderItemsGroup.objects.filter(pk=self.pk)
                    .values_list('product_id', flat=True)
                    .first()
                )
                product_changed = (old_product_id != self.product_id)

            if product_changed:
                fam = getattr(self.product, 'product_family', None)
                if fam is not None:
                    self.has_handle = fam.has_handle

        with transaction.atomic():
            # Сценарий 2: добавление/активация NEW split-группы на PHASE1_READY откатывает заказ в PHASE1_PRODUCTION
            if self.order_id and self.order.status == OrderStatus.PHASE1_READY:
                if self.is_split_installation and self.production_state == self.ProductionState.NEW:
                    self.order.status = OrderStatus.PHASE1_PRODUCTION
                    self.order.save(update_fields=['status'])
                    OrderChangeLog.objects.create(
                        order=self.order,
                        user=None,
                        field_name='status',
                        old_value=OrderStatus.PHASE1_READY,
                        new_value=OrderStatus.PHASE1_PRODUCTION,
                    )

            super().save(*args, **kwargs)
            if self.product and should_sync_items:
                self.auto_populate_required_customizers()
                sync_group_items(self)
                
    def delete(self, *args, **kwargs):
        from apps.orders.services import recalculate_item_marks

        order = self.order
        super().delete(*args, **kwargs)
        recalculate_item_marks(order)

    def duplicate(self):
        with transaction.atomic():
            new_group = OrderItemsGroup.objects.create(
                order=self.order,
                quantity=self.quantity,
                product=self.product,
                series=self.series,
                front=self.front,
                basic_color_frames=self.basic_color_frames,
                panel_paint_option=self.panel_paint_option,
                is_door_inside_different_color=self.is_door_inside_different_color,
                color_panel_inside=self.color_panel_inside,
                color_panel_outside=self.color_panel_outside,
                frame_paint_option=self.frame_paint_option,
                color_frames=self.color_frames,
                is_split_installation=self.is_split_installation,
                is_special_detail=self.is_special_detail,
                comments=self.comments,
                production_state=self.ProductionState.NEW,
                batch_number=None,
            )
            for cust in self.customizers.all():
                OrderItemsGroupCustomizer.objects.update_or_create(
                    group=new_group,
                    customizer=cust.customizer,
                    defaults={
                        'par1': cust.par1,
                        'par2': cust.par2,
                        'par3': cust.par3,
                        'par4': cust.par4,
                        'par5': cust.par5,
                    },
                )
            return new_group


class OrderItemsGroupCustomizer(models.Model):
    group = models.ForeignKey(
        'OrderItemsGroup', on_delete=models.CASCADE,
        related_name='customizers', verbose_name='קבוצת פריטים',
    )
    customizer = models.ForeignKey('catalog.Customizer', on_delete=models.CASCADE, verbose_name='קסטומייזר')
    par1 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 1")
    par2 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 2")
    par3 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 3")
    par4 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 4")
    par5 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 5")

    class Meta:
        verbose_name = 'קסטומייזר לקבוצה'
        verbose_name_plural = 'קסטומייזרים לקבוצה'

    @property
    def formatted_parameters(self):
        result = []
        for i in range(1, 6):
            label = getattr(self.customizer, f'par{i}_label', None)
            if label:
                val = self.get_parameter_display_value(i)
                if val:
                    result.append({
                        'label': label,
                        'hint': getattr(self.customizer, f'par{i}_hint', ''),
                        'value': val,
                    })
        return result

    def __str__(self):
        return f"{self.group} - {self.customizer.name}"

    def clean(self):
        super().clean()
        errors = {}
        product_model = getattr(self.group, 'product', None)

        if product_model and not self.customizer.is_available_for(product_model):
            errors['customizer'] = f"הקסטומייזר '{self.customizer.name}' אינו זמין עבור המוצר '{product_model}'."

        for i in range(1, 6):
            field_name = f"par{i}"
            value = getattr(self, field_name)
            options = self.customizer.get_filtered_parameter_options(i, product_model)
            if options and value and str(value).strip():
                valid_keys = [opt[0] for opt in options]
                stripped_value = str(value).strip()
                if stripped_value not in valid_keys:
                    all_keys = [opt[0] for opt in self.customizer.get_parameter_options(i)]
                    if stripped_value in all_keys:
                        errors[field_name] = f"הפרזול שנבחר '{stripped_value}' אינו תואם לדגם המוצר."
                    else:
                        errors[field_name] = (
                            f"הערך שנבחר '{stripped_value}' אינו אפשרות תקינה. "
                            f"אפשרויות מותרות: {', '.join(valid_keys)}"
                        )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.pk and self.customizer:
            for i in range(1, 6):
                field_name = f'par{i}'
                current_val = getattr(self, field_name)
                if current_val is None or current_val == '':
                    default_val = getattr(self.customizer, f'par{i}_value', None)
                    if default_val:
                        setattr(self, field_name, str(default_val))
        super().save(*args, **kwargs)

    def get_parameter_display_value(self, par_number):
        val = getattr(self, f'par{par_number}', None)
        if not val:
            return ""
        val_str = str(val).strip()
        for key, label in self.customizer.get_parameter_options(par_number):
            if key == val_str:
                return label
        return val_str


# ==========================================
# 3. PRODUCT (ORDER ITEM)
# ==========================================

class OrderItem(models.Model):
    class ItemState(models.TextChoices):
        ACTIVE = 'ACTIVE', 'פעיל'
        CANCELED = 'CANCELED', 'בוטל'

    state = models.CharField(
        max_length=20, choices=ItemState.choices, default=ItemState.ACTIVE,
        db_index=True, verbose_name="סטטוס פריט",
    )
    group = models.ForeignKey(
        "OrderItemsGroup", on_delete=models.CASCADE, related_name="items", verbose_name="קבוצת מוצרים",
    )
    mark = models.CharField(max_length=50, blank=True, null=True, verbose_name="סימון")

    # Dimensions (in cm)
    width = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True, verbose_name='רוחב')
    width_bottom = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True,
                                       verbose_name='רוחב תחתון')
    height = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True, verbose_name='גובה')
    wall = models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True, verbose_name='עובי קיר')

    direction = models.CharField(max_length=10, choices=OpeningSide.choices, blank=True, null=True,
                                 verbose_name="כיוון פתיחה")
    opening = models.CharField(max_length=10, choices=OpeningType.choices, blank=True, null=True,
                               verbose_name="צד פתיחה")
    bottom_correction = models.DecimalField(
        max_digits=5, decimal_places=1, blank=True, null=True, default=0, verbose_name="חיתוך / קיצור נוסף",
    )

    place = models.CharField(max_length=255, blank=True, null=True, verbose_name="מיקום התקנה (קומה / ציר / חדר)")
    comment = models.TextField(blank=True, null=True, verbose_name="הערה למוצר")

    custom_lock_height = models.DecimalField(max_digits=7, decimal_places=1, blank=True, null=True,
                                             verbose_name='גובה מנעול מותאם (ס"מ)')
    custom_hinge1 = models.DecimalField(max_digits=7, decimal_places=1, blank=True, null=True,
                                        verbose_name='גובה ציר 1 (ס"מ)')
    custom_hinge2 = models.DecimalField(max_digits=7, decimal_places=1, blank=True, null=True,
                                        verbose_name='גובה ציר 2 (ס"מ)')
    custom_hinge3 = models.DecimalField(max_digits=7, decimal_places=1, blank=True, null=True,
                                        verbose_name='גובה ציר 3 (ס"מ)')
    custom_hinge4 = models.DecimalField(max_digits=7, decimal_places=1, blank=True, null=True,
                                        verbose_name='גובה ציר 4 (ס"מ)')
    custom_hinge5 = models.DecimalField(max_digits=7, decimal_places=1, blank=True, null=True,
                                        verbose_name='גובה ציר 5 (ס"מ)')

    sketch = models.FileField(
        upload_to='order_sketches/%Y/%m/', blank=True, null=True,
        verbose_name='שרטוט ידני / קובץ', help_text='ניתן להעלות PDF, JPEG, PNG וכדומה',
    )

    class Meta:
        db_table = "order_items"
        verbose_name = "פריט הזמנה"
        verbose_name_plural = "פריטי הזמנה"
        ordering = ["id"]

    def __str__(self):
        return f"פריט #{self.id} (קבוצה מס' {self.group_id})"

    @staticmethod
    def format_decimal(value):
        if value is None:
            return ""
        val_float = float(value)
        if val_float == int(val_float):
            return str(int(val_float))
        return f"{val_float:.1f}"

    @property
    def h_fmt(self):
        return self.format_decimal(self.height)

    @property
    def w_fmt(self):
        return self.format_decimal(self.width)

    @property
    def w_bottom_fmt(self):
        return self.format_decimal(self.width_bottom)

    @property
    def wall_fmt(self):
        return self.format_decimal(self.wall)

    def save(self, *args, **kwargs):
        decimal_fields = (
            'width', 'width_bottom', 'height', 'wall', 'custom_lock_height',
            'custom_hinge1', 'custom_hinge2', 'custom_hinge3',
            'custom_hinge4', 'custom_hinge5', 'bottom_correction',
        )
        for field in decimal_fields:
            val = getattr(self, field)
            if val is not None:
                setattr(self, field, math.floor(float(val) * 10) / 10.0)
        super().save(*args, **kwargs)


# ==========================================
# 4. GROUP SPECIFICATION (PRESET / TEMPLATE)
# ==========================================

class GroupSpecification(models.Model):
    name = models.CharField(
        max_length=255,
        verbose_name="שם המפרט",
        help_text="שם מזהה למפרט השמור (למשל: דלתות קומה טיפוסית)",
    )
    description = models.TextField(blank=True, null=True, verbose_name="תיאור")
    product = models.ForeignKey(
        "catalog.ProductModel", on_delete=models.PROTECT,
        related_name="saved_specifications", verbose_name="דגם מוצר",
    )
    series = models.ForeignKey('catalog.Series', on_delete=models.SET_NULL, blank=True, null=True, verbose_name="סדרה")
    front = models.ForeignKey('catalog.Front', on_delete=models.SET_NULL, blank=True, null=True,
                              verbose_name="חזית / גימור")
    basic_color_frames = models.ForeignKey(
        'catalog.Material', on_delete=models.SET_NULL, blank=True, null=True, verbose_name="צבע משקוף בסיסי",
    )
    panel_paint_option = models.CharField(
        max_length=20, choices=OrderItemsGroup.PaintOption.choices,
        default=OrderItemsGroup.PaintOption.MAIN_COLOR, verbose_name="אופציית צביעת פנל",
    )
    is_door_inside_different_color = models.BooleanField(default=False, verbose_name="צדדים שונים (חוץ/פנים)")
    color_panel_outside = models.CharField(max_length=100, blank=True, null=True, verbose_name="צבע כנף חוץ (מיוחד)")
    color_panel_inside = models.CharField(max_length=100, blank=True, null=True, verbose_name="צבע כנף פנים (מיוחד)")

    frame_paint_option = models.CharField(
        max_length=20, choices=OrderItemsGroup.PaintOption.choices,
        default=OrderItemsGroup.PaintOption.NO_PAINT, verbose_name="אופציית צביעת משקוף",
    )
    color_frames = models.CharField(max_length=100, blank=True, null=True, verbose_name="צבע משקופים")
    is_split_installation = models.BooleanField(default=False, verbose_name="התקנה מפוצלת")
    is_special_detail = models.BooleanField(default=False, verbose_name="פרט מיוחד")
    quantity = models.PositiveIntegerField(default=1, verbose_name="כמות דלתות ברירת מחדל")
    comments = models.TextField(blank=True, null=True, verbose_name="הערות")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="נוצר במערכת")
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='נוצר ע"י',
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
                is_door_inside_different_color=group.is_door_inside_different_color,
                color_panel_outside=group.color_panel_outside,
                color_panel_inside=group.color_panel_inside,
                frame_paint_option=group.frame_paint_option,
                color_frames=group.color_frames,
                is_split_installation=group.is_split_installation,
                is_special_detail=group.is_special_detail,
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
                    par5=cust.par5,
                )
            return spec

    def apply_to_group(self, group, update_quantity=False, new_quantity=None):
        with transaction.atomic():
            group.product = self.product
            group.series = self.series
            group.front = self.front
            group.basic_color_frames = self.basic_color_frames
            group.panel_paint_option = self.panel_paint_option
            group.is_door_inside_different_color = self.is_door_inside_different_color
            group.color_panel_outside = self.color_panel_outside
            group.color_panel_inside = self.color_panel_inside
            group.frame_paint_option = self.frame_paint_option
            group.color_frames = self.color_frames
            group.is_split_installation = self.is_split_installation
            group.is_special_detail = self.is_special_detail
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
                    par5=cust.par5,
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
                is_door_inside_different_color=self.is_door_inside_different_color,
                color_panel_outside=self.color_panel_outside,
                color_panel_inside=self.color_panel_inside,
                frame_paint_option=self.frame_paint_option,
                color_frames=self.color_frames,
                is_split_installation=self.is_split_installation,
                is_special_detail=self.is_special_detail,
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
                    par5=cust.par5,
                )
            return new_group


class GroupSpecificationCustomizer(models.Model):
    specification = models.ForeignKey(
        GroupSpecification, on_delete=models.CASCADE, related_name="customizers", verbose_name="מפרט",
    )
    customizer = models.ForeignKey('catalog.Customizer', on_delete=models.CASCADE, verbose_name="קסטומייזר")
    par1 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 1")
    par2 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 2")
    par3 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 3")
    par4 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 4")
    par5 = models.CharField(max_length=255, blank=True, null=True, verbose_name="פרמטר 5")

    class Meta:
        db_table = "group_specification_customizers"
        verbose_name = "קסטומייזר למפרט"
        verbose_name_plural = "קסטומייזרים למפרט"

    def __str__(self):
        return f"{self.specification.name} - {self.customizer.name}"


class OrderWarehouseItem(models.Model):
    class Category(models.TextChoices):
        LOCKS = 'LOCKS', 'מנעולים'
        HANDLES = 'HANDLES', 'ידיות'
        HINGES = 'HINGES', 'צירים'
        OTHER = 'OTHER', 'תוספות'

    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='warehouse_items',
                              verbose_name='הזמנה')
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER, verbose_name='קטגוריה')
    common_name = models.CharField(max_length=255, blank=True, default='', db_index=True,
                                   verbose_name='שם קבוצה (לזיהוי גוונים)')
    hardware = models.ForeignKey('catalog.Hardware', on_delete=models.SET_NULL, null=True, blank=True,
                                 verbose_name='פריט קטלוג')
    name = models.CharField(max_length=255, verbose_name='שם פריט')
    sku = models.CharField(max_length=100, blank=True, default='', verbose_name='מק"ט')
    color_name = models.CharField(max_length=100, blank=True, default='', verbose_name='גוון')
    is_color_required = models.BooleanField(default=False, verbose_name='חובת בחירת גוון')
    quantity = models.DecimalField(max_digits=8, decimal_places=1, default=1, verbose_name='כמות')
    comment = models.CharField(max_length=255, blank=True, default='', verbose_name='הערה לפריט')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'order_warehouse_items'
        ordering = ['category', 'sort_order', 'id']
        verbose_name = 'פריט ליקוט מחסן'
        verbose_name_plural = 'פריטי ליקוט מחסן'

    def __str__(self):
        return f"{self.order.order_number} | {self.name} ({self.quantity})"

    @property
    def qty_display(self):
        return int(self.quantity) if self.quantity == int(self.quantity) else self.quantity
