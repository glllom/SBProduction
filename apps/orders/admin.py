from django.contrib import admin
from .models import Order, OrderItemsGroup, OrderItem


class OrderItemInline(admin.TabularInline):
    """Позволяет замерщику/менеджеру вводить габариты дверей внутри группы."""
    model = OrderItem
    extra = 0
    readonly_fields = ('position_number',)
    fields = ('position_number', 'item_label', 'height', 'width', 'wall_thickness', 'opening_direction', 'opening_type',
              'note')
    ordering = ('position_number',)


@admin.register(OrderItemsGroup)
class OrderItemsGroupAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'order', 'product', 'front', 'has_window')
    list_filter = ('product', 'has_window')
    search_fields = ('name', 'order__order_number')
    inlines = [OrderItemInline]


class OrderGroupInline(admin.StackedInline):
    """Позволяет создавать группы прямо на странице Заказа."""
    model = OrderItemsGroup
    extra = 1


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('order_number',)
    inlines = [OrderGroupInline]

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('position_number', 'get_order_number', 'group', 'item_label', 'height', 'width')
    list_filter = ('group__order', 'opening_direction', 'opening_type')
    ordering = ('group__order', 'position_number')

    @admin.display(description='Order')
    def get_order_number(self, obj):
        return obj.group.order.order_number