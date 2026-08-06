from django.contrib import admin
from .models import Order, OrderItemsGroup, OrderItem, OrderChangeLog


from django.contrib import admin
from .models import OrderItemsGroup


class OrderItemsGroupInline(admin.TabularInline):
    model = OrderItemsGroup
    extra = 1
    fields = (
        "product",
        "quantity",
        "series",
        "front",
        "color_panels",
        "color_frames",
        "is_split_installation",
    )


@admin.register(OrderItemsGroup)
class OrderItemsGroupAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "product",
        "quantity",
        "series",
        "front",
        "color_panels",
        "color_frames",
        "is_split_installation",
    )

    list_filter = (
        "is_split_installation",
        "series",
        "product",
    )

    search_fields = (
        "order__order_number",
        "comments",
        "color_panels",
        "color_frames",
    )

    ordering = ("id",)

    fieldsets = (
        (
            "Привязка к заказу и Объем",
            {
                "fields": ("order", "product", "quantity"),
            },
        ),
        (
            "Конструкция и Отделка",
            {
                "fields": (
                    "series",
                    "front",
                    "color_panels",
                    "color_frames",
                ),
            },
        ),
        (
            "Параметры монтажа",
            {
                "fields": ("is_split_installation",),
            },
        ),
        (
            "Примечание",
            {
                "fields": ("comments",),
            },
        ),
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    # Поля в списке всех заказов
    list_display = (
        "id",
        "order_number",
        "customer",
        "status",
        "painting_date",
        "completion_date",
        "series",
        "created_at",
    )

    # Фильтры в правой панели
    list_filter = (
        "status",
        "series",
        "painting_date",
        "completion_date",
    )

    # Поиск по номеру, клиенту и комментариям
    search_fields = ("order_number", "customer", "comments")

    # Сортировка по умолчанию (новые вверху)
    ordering = ("-id",)

    # Структурированная форма редактирования
    fieldsets = (
        (
            "Основная информация",
            {
                "fields": (
                    "order_number",
                    "customer",
                    "status",
                )
            },
        ),
        (
            "Даты и График",
            {
                "fields": (
                    "painting_date",
                    "completion_date",
                )
            },
        ),
        (
            "Характеристики заказа",
            {
                "fields": (
                    "series",
                    "front",
                    "color_panels",
                    "color_frames",
                )
            },
        ),
        (
            "Дополнительно",
            {
                "fields": ("comments",),
            },
        ),
    )
from django.contrib import admin
from .models import OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = (
        "width",
        "height",
        "wall",
        "opening",
        "direction",
        "sketch",
        "place",
        "custom_lock_height",
    )


@admin.register(OrderChangeLog)
class OrderChangeLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "order", "user", "field_name", "old_value", "new_value")
    list_filter = ("timestamp", "field_name", "user")
    search_fields = ("order__order_number", "field_name")
    readonly_fields = ("timestamp", "order", "user", "field_name", "old_value", "new_value")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "group",
        "width",
        "height",
        "wall",
        "opening",
        "direction",
        "place",
        "custom_lock_height",
    )

    list_filter = (
        "opening",
        "direction",
        "group",
    )

    search_fields = (
        "place",
        "comment",
        "addition_cut",
        "group__order__order_number",
    )

    ordering = ("id",)

    fieldsets = (
        (
            "Основная привязка",
            {
                "fields": ("group", "place"),
            },
        ),
        (
            "Габариты и Конструкция",
            {
                "fields": (
                    "width",
                    "height",
                    "wall",
                    "opening",
                    "direction",
                    "addition_cut",
                ),
            },
        ),
        (
            "Врезка замка и петель (Кастомизация)",
            {
                "fields": (
                    "custom_lock_height",
                    "custom_hinge1",
                    "custom_hinge2",
                    "custom_hinge3",
                    "custom_hinge4",
                    "custom_hinge5",
                ),
            },
        ),
        (
            "Дополнительно",
            {
                "fields": ("comment",),
            },
        ),
    )