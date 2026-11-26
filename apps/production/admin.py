import json

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import (
    DoorLabel,
    ItemStationProgress,
    OrderSpecificationSnapshot,
    OrderStationNote,
    StationDailySheetLog,
    StationScanAuditLog,
)


@admin.register(OrderSpecificationSnapshot)
class OrderSpecificationSnapshotAdmin(ModelAdmin):
    list_display = ('id', 'order', 'snapshot_type', 'created_at', 'created_by')
    list_filter = ('snapshot_type', 'created_at')
    list_select_related = ('order', 'created_by')
    date_hierarchy = 'created_at'
    search_fields = ('order__order_number', 'order__customer')
    readonly_fields = ('order', 'snapshot_type', 'created_at', 'created_by', 'formatted_spec_data')
    exclude = ('spec_data',)

    def formatted_spec_data(self, obj):
        pretty = json.dumps(obj.spec_data, ensure_ascii=False, indent=2)
        return format_html(
            '<details><summary style="cursor:pointer;font-weight:600">הצג JSON ({} תווים)</summary>'
            '<pre dir="ltr" style="max-height:480px;overflow:auto;margin-top:8px;padding:10px;'
            'background:#f8faf9;border:1px solid #cbd8d5;border-radius:6px;font-size:12px">{}</pre></details>',
            len(pretty),
            pretty,
        )

    formatted_spec_data.short_description = 'נתוני מפרט (JSON)'

    def has_add_permission(self, request):
        return False


@admin.register(OrderStationNote)
class OrderStationNoteAdmin(ModelAdmin):
    list_display = ('order', 'station', 'updated_at', 'updated_by')
    list_filter = ('station',)
    list_select_related = ('order', 'station', 'updated_by')
    search_fields = ('order__order_number', 'station__name', 'comment')
    autocomplete_fields = ('order', 'station', 'updated_by')


@admin.register(DoorLabel)
class DoorLabelAdmin(ModelAdmin):
    list_display = (
        'id', 'order_link', 'order_number', 'item_mark', 'label_type', 'leaf_role',
        'lock_name', 'hinge_name', 'target_machine', 'print_count', 'last_printed_at',
    )
    list_filter = ('label_type', 'leaf_role', 'target_machine', 'is_paint')
    list_select_related = ('order',)
    date_hierarchy = 'created_at'
    search_fields = ('order_number', 'client_name', 'item_mark', 'lock_name', 'hinge_name')
    autocomplete_fields = ('order', 'order_item')
    readonly_fields = ('created_at',)
    fieldsets = (
        ('הקשר', {
            'fields': (
                ('order', 'order_item'),
                ('order_number', 'client_name'),
                ('item_mark', 'total_items'),
                ('label_type', 'leaf_role', 'target_machine'),
            )
        }),
        ('הדפסה', {'fields': (('print_count', 'last_printed_at', 'created_at'),)}),
        ('גיאומטריה ועובי', {
            'fields': (
                ('width', 'height', 'thickness'),
                ('direction', 'opening', 'edge_type', 'is_paint'),
            )
        }),
        ('פרזול ותוספות', {
            'fields': (
                ('lock_name', 'lock_height', 'lock_program'),
                ('hinge_name', 'hinge_program'),
                ('hinge_1', 'hinge_2', 'hinge_3', 'hinge_4', 'hinge_5'),
                ('icon_filename', 'front_program_code'),
                'addons_summary',
                'comment',
            )
        }),
        ('תוכניות CNC ומאקרו', {
            'classes': ('collapse',),
            'fields': (
                ('cnc_program', 'edge_shape'),
                'customizer_programs',
                ('cmz_prg_1', 'cmz_prg_2', 'cmz_prg_3', 'cmz_prg_4', 'cmz_prg_5'),
                ('cmz_prg_6', 'cmz_prg_7', 'cmz_prg_8', 'cmz_prg_9', 'cmz_prg_10'),
                'qr_payload',
            )
        }),
    )

    def order_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:orders_order_change', args=[obj.order_id]),
            obj.order.order_number,
        )

    order_link.short_description = 'הזמנה'


@admin.register(ItemStationProgress)
class ItemStationProgressAdmin(ModelAdmin):
    list_display = ('id', 'item_link', 'station', 'sequence', 'status', 'source', 'started_at', 'completed_at',
                    'completed_by')
    list_filter = ('status', 'source', 'station')
    list_editable = ('status',)
    list_select_related = ('item', 'station', 'completed_by')
    date_hierarchy = 'started_at'
    search_fields = ('item__group__order__order_number', 'station__code', 'station__name')
    autocomplete_fields = ('item', 'station', 'completed_by')
    ordering = ('-id',)

    def item_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse('admin:orders_orderitem_change', args=[obj.item_id]),
            obj.item,
        )

    item_link.short_description = 'פריט הזמנה'


@admin.register(StationDailySheetLog)
class StationDailySheetLogAdmin(ModelAdmin):
    list_display = ('id', 'station', 'sheet_date', 'printed_at', 'printed_by')
    list_filter = ('station', 'sheet_date')
    list_select_related = ('station', 'printed_by')
    date_hierarchy = 'printed_at'
    search_fields = ('station__code', 'station__name', 'notes')
    readonly_fields = ('station', 'sheet_date', 'printed_at', 'printed_by', 'notes')

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StationScanAuditLog)
class StationScanAuditLogAdmin(ModelAdmin):
    list_display = ('id', 'created_at', 'raw_payload', 'station_code', 'order_number', 'item_mark', 'source',
                    'is_success')
    list_filter = ('is_success', 'source', 'station_code')
    date_hierarchy = 'created_at'
    search_fields = ('raw_payload', 'station_code', 'order_number', 'item_mark', 'message')
    readonly_fields = (
        'raw_payload', 'station_code', 'order_number', 'batch_number',
        'item_mark', 'source', 'is_success', 'message', 'created_at', 'created_by',
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
