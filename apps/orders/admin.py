import csv
import io

from django.contrib import admin
from django.db import models
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html
from django_json_widget.widgets import JSONEditorWidget
from unfold.admin import ModelAdmin, TabularInline, StackedInline

from apps.production.models import DoorLabel, ItemStationProgress
from .models import Order, OrderChangeLog, OrderItem, OrderComponentSelection
from .models import OrderItemsGroup, OrderItemsGroupCustomizer, GroupSpecification, GroupSpecificationCustomizer

JSON_FORMFIELD_OVERRIDES = {
    models.JSONField: {'widget': JSONEditorWidget},
}


@admin.action(description='ייצוא השורות שנבחרו לקובץ CSV')
def export_selected_to_csv(modeladmin, request, queryset):
    meta = modeladmin.model._meta
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([str(field.verbose_name) for field in meta.fields])
    for obj in queryset:
        writer.writerow([getattr(obj, field.attname) for field in meta.fields])
    response = HttpResponse(
        output.getvalue().encode('utf-8-sig'),
        content_type='text/csv; charset=utf-8-sig',
    )
    response['Content-Disposition'] = f'attachment; filename="{meta.model_name}.csv"'
    return response


def _set_groups_production_state(modeladmin, request, queryset, state):
    updated = queryset.update(production_state=state)
    modeladmin.message_user(request, f'עודכנו {updated} קבוצות')


@admin.action(description='שינוי סטטוס ייצור ל: בייצור')
def mark_groups_in_production(modeladmin, request, queryset):
    _set_groups_production_state(modeladmin, request, queryset, OrderItemsGroup.ProductionState.IN_PRODUCTION)


@admin.action(description='שינוי סטטוס ייצור ל: הושלם')
def mark_groups_completed(modeladmin, request, queryset):
    _set_groups_production_state(modeladmin, request, queryset, OrderItemsGroup.ProductionState.COMPLETED)


@admin.action(description='שינוי סטטוס ייצור ל: בוטל')
def mark_groups_canceled(modeladmin, request, queryset):
    _set_groups_production_state(modeladmin, request, queryset, OrderItemsGroup.ProductionState.CANCELED)


class OrderItemsGroupCustomizerInline(TabularInline):
    model = OrderItemsGroupCustomizer
    extra = 0
    autocomplete_fields = ('customizer',)
    fields = ("customizer", "par1", "par2", "par3", "par4", "par5")


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 0
    fields = (
        "mark",
        "state",
        "width",
        "height",
        "wall",
        "opening",
        "direction",
        "bottom_correction",
        "place",
        "comment",
        "custom_lock_height",
        "custom_hinge1",
        "custom_hinge2",
        "custom_hinge3",
        "custom_hinge4",
        "custom_hinge5",
        "sketch",
    )


class OrderItemsGroupInline(StackedInline):
    model = OrderItemsGroup
    extra = 0
    show_change_link = True
    autocomplete_fields = ('product', 'basic_color_frames')
    readonly_fields = ('batch_number',)
    fieldsets = (
        (None, {
            'fields': (
                ('product', 'quantity'),
                ('production_state', 'batch_date', 'batch_number'),
                ('series', 'front'),
                ('basic_color_frames', 'is_split_installation'),
            )
        }),
        ('צביעת כנף', {
            'fields': (
                ('panel_paint_option', 'color_panel_outside'),
                ('is_door_inside_different_color', 'color_panel_inside'),
            )
        }),
        ('צביעת משקוף', {
            'fields': (
                ('frame_paint_option', 'color_frames'),
            )
        }),
        ('הערה', {
            'fields': ('comments',)
        }),
    )


@admin.register(OrderItemsGroup)
class OrderItemsGroupAdmin(ModelAdmin):
    list_display = (
        "id",
        "order_link",
        "product",
        "quantity",
        "production_state",
        "batch_number",
        "batch_date",
        "series",
        "front",
        "panel_paint_option",
        "frame_paint_option",
        "is_split_installation",
    )

    list_display_links = ("id",)
    list_editable = ("production_state",)
    list_select_related = ("order", "product", "series", "front")

    list_filter = (
        "production_state",
        "panel_paint_option",
        "frame_paint_option",
        "is_split_installation",
        "series",
        "product",
    )

    search_fields = (
        "order__order_number",
        "product__code",
        "comments",
        "color_panel_outside",
        "color_panel_inside",
        "color_frames",
    )

    autocomplete_fields = ("order", "product", "basic_color_frames")
    readonly_fields = ("batch_number",)
    ordering = ("id",)
    inlines = [OrderItemsGroupCustomizerInline, OrderItemInline]
    actions = [
        mark_groups_in_production,
        mark_groups_completed,
        mark_groups_canceled,
        export_selected_to_csv,
    ]

    fieldsets = (
        (
            "שיוך להזמנה וכמות",
            {
                "fields": ("order", "product", "quantity", "production_state", "batch_number", "batch_date"),
            },
        ),
        (
            "מבנה",
            {
                "fields": (
                    "series",
                    "front",
                    "basic_color_frames",
                    "is_split_installation",
                ),
            },
        ),
        (
            "צביעת כנף",
            {
                "fields": (
                    "panel_paint_option",
                    "is_door_inside_different_color",
                    "color_panel_outside",
                    "color_panel_inside",
                ),
            },
        ),
        (
            "צביעת משקוף",
            {
                "fields": ("frame_paint_option", "color_frames"),
            },
        ),
        (
            "הערה",
            {
                "fields": ("comments",),
            },
        ),
    )

    def order_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:orders_order_change', args=[obj.order_id]),
            obj.order.order_number,
        )

    order_link.short_description = 'מספר הזמנה'


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = (
        "id",
        "order_number",
        "customer",
        "status",
        "series",
        "front",
        "handle",
        "production_start_date",
        "completion_date",
        "painting_completion_date",
        "current_batch",
        "created_at",
    )

    list_filter = (
        "status",
        "series",
        "front",
        "handle",
        "is_frames_to_paint",
        "production_start_date",
        "completion_date",
        "painting_completion_date",
    )

    list_editable = ("status",)
    list_select_related = ("series", "front", "handle")
    date_hierarchy = "created_at"

    search_fields = ("order_number", "customer", "comments", "press_notes", "frames_notes", "warehouse_notes")

    ordering = ("-id",)

    readonly_fields = ("created_at", "current_batch")
    formfield_overrides = JSON_FORMFIELD_OVERRIDES
    inlines = [OrderItemsGroupInline]
    actions = [export_selected_to_csv]

    fieldsets = (
        (
            "מידע כללי",
            {
                "fields": (
                    "order_number",
                    "customer",
                    "status",
                    "current_batch",
                    "created_at",
                )
            },
        ),
        (
            "תאריכים ולוח זמנים",
            {
                "fields": (
                    "production_start_date",
                    "painting_completion_date",
                    "completion_date",
                )
            },
        ),
        (
            "מאפייני ההזמנה",
            {
                "fields": (
                    "series",
                    "front",
                    "handle",
                    "is_frames_to_paint",
                    "is_door_inside_different_color",
                    "color_panel_outside",
                    "color_panel_inside",
                    "color_frames",
                )
            },
        ),
        (
            "הערות למחלקות הייצור",
            {
                "fields": (
                    "comments",
                    "press_notes",
                    "frames_notes",
                    "warehouse_notes",
                )
            },
        ),
        (
            "מטמון מפרטים (פנימי)",
            {
                "classes": ("collapse",),
                "fields": ("phase1_spec_cache", "phase2_spec_cache"),
            },
        ),
    )


@admin.register(OrderChangeLog)
class OrderChangeLogAdmin(ModelAdmin):
    list_display = ("timestamp", "order", "user", "field_name", "old_value", "new_value")
    list_filter = ("timestamp", "field_name", "user")
    list_select_related = ("order", "user")
    date_hierarchy = "timestamp"
    search_fields = ("order__order_number", "field_name")
    readonly_fields = ("timestamp", "order", "user", "field_name", "old_value", "new_value")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ItemStationProgressInline(TabularInline):
    model = ItemStationProgress
    extra = 0
    can_delete = False
    fields = ("station", "sequence", "status", "source", "started_at", "completed_at", "completed_by")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class DoorLabelInline(TabularInline):
    model = DoorLabel
    extra = 0
    can_delete = False
    fields = ("order_number", "item_mark", "label_type", "leaf_role", "target_machine", "print_count",
              "last_printed_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(OrderItem)
class OrderItemAdmin(ModelAdmin):
    list_display = (
        "id",
        "mark",
        "state",
        "group",
        "order_link",
        "width",
        "height",
        "wall",
        "opening",
        "direction",
        "place",
        "custom_lock_height",
    )

    list_display_links = ("id",)
    list_editable = ("state",)
    list_select_related = ("group", "group__order")

    list_filter = (
        "opening",
        "direction",
        "group",
    )

    search_fields = (
        "mark",
        "place",
        "comment",
        "group__order__order_number",
        "group__product__code",
    )

    autocomplete_fields = ("group",)
    inlines = [ItemStationProgressInline, DoorLabelInline]
    ordering = ("id",)

    fieldsets = (
        (
            "שיוך עיקרי",
            {
                "fields": ("group", "mark", "state", "place"),
            },
        ),
        (
            "מידות ומבנה",
            {
                "fields": (
                    "width",
                    "height",
                    "wall",
                    "opening",
                    "direction",
                    "bottom_correction",
                ),
            },
        ),
        (
            "גובה מנעול וצירים (התאמות אישיות)",
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
            "נוסף",
            {
                "fields": ("comment", "sketch"),
            },
        ),
    )

    def order_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:orders_order_change', args=[obj.group.order_id]),
            obj.group.order.order_number,
        )

    order_link.short_description = 'מספר הזמנה'


class GroupSpecificationCustomizerInline(TabularInline):
    model = GroupSpecificationCustomizer
    extra = 0
    autocomplete_fields = ("customizer",)
    fields = ("customizer", "par1", "par2", "par3", "par4", "par5")


@admin.register(GroupSpecification)
class GroupSpecificationAdmin(ModelAdmin):
    list_display = (
        "id",
        "name",
        "product",
        "series",
        "front",
        "basic_color_frames",
        "quantity",
        "created_by",
        "created_at",
    )
    list_select_related = ("product", "series", "front", "basic_color_frames", "created_by")
    list_filter = (
        "product",
        "series",
        "is_split_installation",
        "created_at",
    )
    date_hierarchy = "created_at"
    search_fields = (
        "name",
        "description",
        "comments",
        "product__code",
    )
    save_as = True
    inlines = [GroupSpecificationCustomizerInline]
    ordering = ("-created_at",)
    autocomplete_fields = ("product", "basic_color_frames", "created_by")

    fieldsets = (
        (
            "מידע כללי",
            {
                "fields": ("name", "description", "product", "quantity", "created_by", "created_at"),
            },
        ),
        (
            "מבנה",
            {
                "fields": ("series", "front", "basic_color_frames", "is_split_installation"),
            },
        ),
        (
            "צביעה",
            {
                "fields": (
                    "panel_paint_option",
                    "color_panels",
                    "frame_paint_option",
                    "color_frames",
                ),
            },
        ),
        (
            "הערה",
            {
                "fields": ("comments",),
            },
        ),
    )
    readonly_fields = ("created_at",)


@admin.register(OrderComponentSelection)
class OrderComponentSelectionAdmin(ModelAdmin):
    list_display = ("id", "order", "common_name", "selected_hardware", "updated_at")
    list_select_related = ("order", "selected_hardware")
    list_filter = ("common_name",)
    date_hierarchy = "updated_at"
    search_fields = ("order__order_number", "common_name", "selected_hardware__name", "selected_hardware__sku")
    autocomplete_fields = ("order", "selected_hardware")
    readonly_fields = ("updated_at",)
