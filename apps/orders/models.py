from django.db import models
from django.db import transaction

from apps.catalog.models import Product, Front



class OrderStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    MEASUREMENT = 'MEASUREMENT', 'Pending Measurement'
    IN_PRODUCTION = 'IN_PRODUCTION', 'In Production'
    READY = 'READY', 'Ready for Ship'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELED = 'CANCELED', 'Canceled'


class OpeningDirection(models.TextChoices):
    LEFT = 'LEFT', 'Left'
    RIGHT = 'RIGHT', 'Right'


class OpeningType(models.TextChoices):
    OUTWARD = 'OUTWARD', 'Outward'
    INWARD = 'INWARD', 'Inward'


# ==========================================
# 1. ЗАКАЗ (ORDER)
# ==========================================

class Order(models.Model):
    """Manufacturing order header."""
    order_number = models.CharField('Order Number', max_length=50, unique=True)
    status = models.CharField(
        'Status',
        max_length=20,
        choices=OrderStatus,
        default=OrderStatus.DRAFT
    )

    # Global order parameters (deadlines, global notes)
    created_at = models.DateTimeField('Created At', auto_now_add=True)
    updated_at = models.DateTimeField('Updated At', auto_now=True)
    note = models.TextField('General Order Note', blank=True)

    class Meta:
        verbose_name = 'Order'
        verbose_name_plural = 'Orders'

    def __str__(self):
        return f"Order #{self.order_number} [{self.get_status_display()}]"

    def get_next_position_number(self):
        """Возвращает следующий сквозной номер позиции внутри заказа."""
        last_item = OrderItem.objects.filter(
            group__order=self
        ).order_by('-position_number').first()

        return (last_item.position_number + 1) if last_item else 1


# ==========================================
# 2. ГРУППА ИЗДЕЛИЙ (ORDER Items GROUP)
# ==========================================

class OrderItemsGroup(models.Model):
    """
    Group of items sharing common customizable attributes
    (e.g., color, engraving, glass/window type, finish).
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='groups',
        verbose_name='Order'
    )
    name = models.CharField('Group Name/Label', max_length=100, help_text='e.g., 2nd Floor Doors')

    # Technology / Base Product definition
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='order_groups',
        verbose_name='Product Model'
    )
    front = models.ForeignKey(
        Front,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_groups',
        verbose_name='Catalog Front'
    )

    # Custom front option
    is_custom_front = models.BooleanField('Is Custom Front', default=False)
    custom_front_name = models.CharField('Custom Front Ref', max_length=255, blank=True)
    quantity = models.PositiveIntegerField('Items Quantity in Group', default=1)
    # Group parameters (Shared customization)
    has_window = models.BooleanField('Has Glass/Bathroom Window', default=False)
    engraving_code = models.CharField('Engraving Pattern / Code', max_length=100, blank=True)

    # Flexible container for less frequent or dynamic group parameters
    group_custom_params = models.JSONField('Additional Group Parameters', default=dict, blank=True)

    class Meta:
        verbose_name = 'Order Items Group'
        verbose_name_plural = 'Order Items Groups'

    def __str__(self):
        return f"{self.order.order_number} — Group: {self.name} ({self.product.name})"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # При первичном создании группы автоматически создаем заготовки дверей
        if is_new and self.quantity > 0:
            with transaction.atomic():
                start_number = self.order.get_next_position_number()
                items_to_create = []

                for i in range(self.quantity):
                    items_to_create.append(
                        OrderItem(
                            group=self,
                            position_number=start_number + i,
                            item_label=f"Door #{start_number + i}"
                        )
                    )
                OrderItem.objects.bulk_create(items_to_create)


# ==========================================
# 3. ИЗДЕЛИЕ (ORDER ITEM)
# ==========================================

class OrderItem(models.Model):
    """
    Individual door item inside a group, containing specific measurements
    filled by the measurer.
    """
    group = models.ForeignKey(
        OrderItemsGroup,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Order Group'
    )
    item_label = models.CharField('Item Tag/Room', max_length=100, blank=True, help_text='e.g., Bathroom, Bedroom 1')
    # Сквозной порядковый номер двери относительно ВСЕГО заказа
    position_number = models.PositiveIntegerField(
        'Item Number in Order',
        db_index=True
    )
    # Measurer dimensions (Item Parameters)
    height = models.DecimalField('Height (H), mm', max_digits=7, decimal_places=2, null=True, blank=True)
    width = models.DecimalField('Width (W), mm', max_digits=7, decimal_places=2, null=True, blank=True)
    wall_thickness = models.DecimalField('Wall Thickness, mm', max_digits=7, decimal_places=2, null=True, blank=True)

    opening_direction = models.CharField(
        'Opening Direction',
        max_length=10,
        choices=OpeningDirection,
        blank=True
    )
    opening_type = models.CharField(
        'Opening Type',
        max_length=10,
        choices=OpeningType,
        blank=True
    )

    note = models.CharField('Measurer / Production Note', max_length=255, blank=True)

    class Meta:
        verbose_name = 'Order Item'
        verbose_name_plural = 'Order Items'

    def __str__(self):
        dimensions = f"{self.height}x{self.width}mm" if self.height and self.width else "No measurements"
        return f"{self.group.name} - {self.item_label or 'Item'} ({dimensions})"