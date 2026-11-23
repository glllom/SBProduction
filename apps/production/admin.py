from django.contrib import admin
from django.db import models
from django.urls import reverse
from django.utils.html import format_html
from django_json_widget.widgets import JSONEditorWidget
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    SvgPattern,
    PuzzleBlockPrototype,
    PuzzlePreset,
    CustomizerPuzzleMapping,
    ProductTechnicalData, BOM, LockStandardHeight, HingeStandardHeight,
    ProductionStation, ProductionRoute, ProductionRouteStep,
    CustomizerProductionStation, OrderSpecificationSnapshot,
    DoorLabel, ItemStationProgress, StationDailySheetLog, StationScanAuditLog,
    PerimeterRoutingFile, HardwareMacroFile, CustomizerMacroFile, FrontEngravingFile,
)

JSON_FORMFIELD_OVERRIDES = {
    models.JSONField: {'widget': JSONEditorWidget},
}


@admin.register(OrderSpecificationSnapshot)
class OrderSpecificationSnapshotAdmin(ModelAdmin):
    list_display = ('id', 'order', 'snapshot_type', 'created_at', 'created_by')
    list_filter = ('snapshot_type', 'created_at')
    list_select_related = ('order', 'created_by')
    date_hierarchy = 'created_at'
    search_fields = ('order__order_number', 'order__customer')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('order', 'created_by')
    formfield_overrides = JSON_FORMFIELD_OVERRIDES


@admin.register(ProductTechnicalData)
class ProductTechnicalDataAdmin(ModelAdmin):
    list_display = ('product', 'cnc_program_name')
    list_select_related = ('product',)
    search_fields = ('product__name', 'product__code', 'cnc_program_name')
    autocomplete_fields = ('product',)


@admin.register(BOM)
class BOMAdmin(ModelAdmin):
    list_display = ('product', 'lock', 'hinges', 'frame', 'covering', 'filling', 'display_additional_count')
    list_select_related = ('product', 'lock', 'hinges', 'frame', 'covering', 'filling')
    search_fields = (
        'product__name', 'product__code',
        'lock__name', 'lock__sku',
        'hinges__name', 'hinges__sku',
        'frame__name', 'covering__name',
    )
    save_as = True
    autocomplete_fields = (
        'product', 'covering', 'base', 'filling', 'casing', 'frame', 'panel_frame',
        'profile1', 'profile2', 'profile3',
        'other1', 'other2', 'other3', 'other4', 'other5',
        'lock', 'hinges',
        'panel_frame_preset', 'filling_preset', 'base_preset', 'covering_preset',
    )
    filter_horizontal = ('additional', 'required_customizers')
    formfield_overrides = JSON_FORMFIELD_OVERRIDES

    fieldsets = (
        (None, {
            'fields': ('product',)
        }),
        ('חומרים', {
            'fields': (
                ('covering', 'covering_consumption'),
                ('base', 'base_consumption'),
                ('filling', 'filling_consumption'),
                ('panel_frame', 'panel_frame_consumption'),
                ('casing', 'casing_consumption'),
                ('frame', 'frame_consumption'),
            )
        }),
        ('פריסטים של פאזל', {
            'description': 'פריסטים לשרטוט סכמת הפרס (חזית וקצה)',
            'fields': (
                ('panel_frame_preset', 'filling_preset'),
                ('base_preset', 'covering_preset'),
            )
        }),
        ('פרופילים ואחרים', {
            'fields': (
                ('profile1', 'profile1_consumption'),
                ('profile2', 'profile2_consumption'),
                ('profile3', 'profile3_consumption'),
                ('other1', 'other1_consumption'),
                ('other2', 'other2_consumption'),
                ('other3', 'other3_consumption'),
                ('other4', 'other4_consumption'),
                ('other5', 'other5_consumption'),
            )
        }),
        ('פרזול', {
            'fields': ('lock', 'hinges', 'additional', 'required_customizers')
        }),
        ('פרמטרים טכנולוגיים', {
            'fields': ('cut_coefficients',)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('additional')

    def display_additional_count(self, obj):
        items = list(obj.additional.all())
        if not items:
            return '-'
        preview = ", ".join(i.name for i in items[:3])
        return f"{preview} (+{len(items) - 3})" if len(items) > 3 else preview

    display_additional_count.short_description = 'תוספות ב-BOM'


@admin.register(LockStandardHeight)
class LockStandardHeightAdmin(ModelAdmin):
    list_display = ('id', 'display_locks', 'display_families', 'base_door_height', 'base_lock_height', 'step')
    list_filter = ('product_families', 'locks')
    search_fields = ('locks__name', 'locks__sku', 'product_families__name')
    filter_horizontal = ('product_families', 'locks')
    save_as = True
    fieldsets = (
        ('תחולה', {
            'fields': ('product_families', 'locks')
        }),
        ('חישוב גובה מנעול', {
            'fields': ('base_door_height', 'base_lock_height', 'step', 'alignment_tolerance')
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('locks', 'product_families')

    def display_locks(self, obj):
        return ", ".join(l.name for l in obj.locks.all()) or '-'

    display_locks.short_description = 'מנעולים'

    def display_families(self, obj):
        return ", ".join(f.name for f in obj.product_families.all()) or '-'

    display_families.short_description = 'משפחות מוצרים'


@admin.register(HingeStandardHeight)
class HingeStandardHeightAdmin(ModelAdmin):
    list_display = ('id', 'display_hinges', 'display_families', 'min_height', 'max_height', 'hinge_count',
                    'display_heights')
    list_filter = ('product_families', 'hinges')
    search_fields = ('hinges__name', 'hinges__sku', 'product_families__name')
    filter_horizontal = ('product_families', 'hinges')
    readonly_fields = ('hinge_count',)
    save_as = True
    fieldsets = (
        ('תחולה', {
            'fields': ('product_families', 'hinges')
        }),
        ('טווח גובה דלת', {
            'fields': (('min_height', 'max_height'),)
        }),
        ('גבהי צירים', {
            'fields': (('value1', 'value2', 'value3', 'value4', 'value5'), 'hinge_count')
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('hinges', 'product_families')

    def display_hinges(self, obj):
        return ", ".join(h.name for h in obj.hinges.all()) or '-'

    display_hinges.short_description = 'צירים'

    def display_families(self, obj):
        return ", ".join(f.name for f in obj.product_families.all()) or '-'

    display_families.short_description = 'משפחות מוצרים'

    def display_heights(self, obj):
        vals = [getattr(obj, f'value{i}', None) for i in range(1, 6)]
        active_vals = [str(int(v) if float(v).is_integer() else v) for v in vals if v]
        return " / ".join(active_vals) or '0 (ללא)'

    display_heights.short_description = 'מידות גובה'


@admin.register(CustomizerProductionStation)
class CustomizerProductionStationAdmin(ModelAdmin):
    list_display = ('customizer', 'station', 'force_alternative_machine')
    list_filter = ('force_alternative_machine', 'station')
    list_editable = ('force_alternative_machine',)
    list_select_related = ('customizer', 'station')
    autocomplete_fields = ('customizer', 'station')
    search_fields = ('customizer__name', 'customizer__code', 'station__name', 'station__code')


@admin.register(ProductionStation)
class ProductionStationAdmin(ModelAdmin):
    list_display = (
        'name',
        'code',
        'order',
        'specification_type',
        'target_machine',
        'alternative_station',
        'is_phase1',
        'active',
    )
    list_filter = ('active', 'specification_type', 'target_machine', 'is_phase1')
    list_select_related = ('alternative_station',)
    search_fields = ('name', 'code', 'order', 'label', 'description')
    ordering = ('order', 'name')
    autocomplete_fields = ('alternative_station',)

    fieldsets = (
        ('מידע כללי', {
            'fields': ('name', 'code', 'order', 'description', 'active', 'is_phase1')
        }),
        ('מפרט וסוג פלט', {
            'fields': ('specification_type', 'template_name')
        }),
        ('ניתוב וציוד CNC', {
            'fields': ('target_machine', 'alternative_station')
        }),
        ('כפתורים והגדרות ממשק', {
            'fields': ('label', 'hint')
        }),
    )


class ProductionRouteStepInline(TabularInline):
    model = ProductionRouteStep
    extra = 3
    ordering = ('order',)
    autocomplete_fields = ('station',)


@admin.register(ProductionRoute)
class ProductionRouteAdmin(ModelAdmin):
    list_display = ('name', 'active', 'display_products')
    list_filter = ('active',)
    filter_horizontal = ('products',)
    save_as = True
    inlines = [ProductionRouteStepInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('products')

    def display_products(self, obj):
        products = list(obj.products.all())
        return ", ".join(p.name for p in products[:5]) + ("..." if len(products) > 5 else "")

    display_products.short_description = 'מוצרים'


@admin.register(SvgPattern)
class SvgPatternAdmin(ModelAdmin):
    list_display = ('title', 'name', 'width', 'height')
    search_fields = ('title', 'name')


@admin.register(PuzzleBlockPrototype)
class PuzzleBlockPrototypeAdmin(ModelAdmin):
    list_display = ('name', 'code', 'fill_type', 'fill_color', 'pattern', 'border_color')
    list_filter = ('fill_type',)
    list_select_related = ('pattern',)
    search_fields = ('name', 'code')


class CustomizerPuzzleMappingInline(TabularInline):
    model = CustomizerPuzzleMapping
    extra = 1
    autocomplete_fields = ('customizer',)


@admin.register(PuzzlePreset)
class PuzzlePresetAdmin(ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name', 'description')
    save_as = True
    formfield_overrides = JSON_FORMFIELD_OVERRIDES
    inlines = [CustomizerPuzzleMappingInline]


@admin.register(CustomizerPuzzleMapping)
class CustomizerPuzzleMappingAdmin(ModelAdmin):
    list_display = ('customizer', 'preset', 'slot_action', 'target_slot')
    list_filter = ('slot_action', 'target_slot')
    list_select_related = ('customizer', 'preset')
    search_fields = ('customizer__name', 'customizer__code', 'preset__name')
    autocomplete_fields = ('customizer', 'preset')


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
        ('הדפסה', {
            'fields': (('print_count', 'last_printed_at', 'created_at'),)
        }),
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
                ('icon_filename', 'front_program'),
                'addons_summary',
                'comment',
            )
        }),
        ('תוכניות CNC ומאקרו', {
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
    list_display = (
        'id', 'item_link', 'station', 'sequence', 'status', 'source',
        'started_at', 'completed_at', 'completed_by',
    )
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
    list_display = (
        'id', 'created_at', 'raw_payload', 'station_code', 'order_number',
        'item_mark', 'source', 'is_success',
    )
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


@admin.register(PerimeterRoutingFile)
class PerimeterRoutingFileAdmin(ModelAdmin):
    list_display = ('id', 'file_name', 'display_doors', 'edge_shape', 'description')
    list_filter = ('edge_shape', 'doors')
    search_fields = ('file_name', 'description', 'doors__name')
    filter_horizontal = ('doors',)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('doors')

    def display_doors(self, obj):
        return ", ".join(d.name for d in obj.doors.all()) or '-'

    display_doors.short_description = 'משפחות דלתות'


@admin.register(HardwareMacroFile)
class HardwareMacroFileAdmin(ModelAdmin):
    list_display = (
        'id', 'file_name', 'label_name', 'machining_feature',
        'display_hardware', 'display_families', 'description',
    )
    list_select_related = ('machining_feature',)
    list_filter = ('machining_feature', 'door_families', 'hardware__role')
    search_fields = (
        'file_name', 'label_name', 'description',
        'machining_feature__name', 'machining_feature__code',
        'hardware__name', 'hardware__sku', 'door_families__name',
    )
    filter_horizontal = ('hardware', 'door_families')
    save_as = True
    fieldsets = (
        ('מידע כללי', {
            'fields': ('file_name', 'label_name', 'machining_feature', 'description')
        }),
        ('שיוך לפרזול ומשפחות', {
            'fields': ('hardware', 'door_families')
        }),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related('machining_feature')
            .prefetch_related('hardware', 'door_families')
        )

    def display_hardware(self, obj):
        return ", ".join(h.name for h in obj.hardware.all()) or '-'

    display_hardware.short_description = 'פרזול'

    def display_families(self, obj):
        return ", ".join(f.name for f in obj.door_families.all()) or '-'

    display_families.short_description = 'משפחות דלתות'


@admin.register(CustomizerMacroFile)
class CustomizerMacroFileAdmin(ModelAdmin):
    list_display = ('id', 'file_name', 'customizer', 'description')
    list_select_related = ('customizer',)
    search_fields = ('file_name', 'description', 'customizer__code', 'customizer__name')
    autocomplete_fields = ('customizer',)


@admin.register(FrontEngravingFile)
class FrontEngravingFileAdmin(ModelAdmin):
    list_display = ('id', 'file_name', 'front', 'description')
    list_select_related = ('front',)
    search_fields = ('file_name', 'description', 'front__name', 'front__code')
    autocomplete_fields = ('front',)
