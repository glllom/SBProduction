from django import forms
from django.contrib import admin
from django.db import models
from django_json_widget.widgets import JSONEditorWidget
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    BOM,
    CustomizerMacroFile,
    CustomizerProductionStation,
    CustomizerPuzzleMapping,
    FrontEngravingFile,
    HardwareMacroFile,
    HingeStandardHeight,
    LockStandardHeight,
    PerimeterRoutingFile,
    ProductEngineeringRule,
    ProductionRoute,
    ProductionRouteStep,
    ProductionStation,
    PuzzleBlockPrototype,
    PuzzlePreset,
    SvgPattern,
)

JSON_FORMFIELD_OVERRIDES = {
    models.JSONField: {'widget': JSONEditorWidget},
}


@admin.register(ProductEngineeringRule)
class ProductEngineeringRuleAdmin(ModelAdmin):
    list_display = ('id', 'product_family', 'product_model')
    list_select_related = ('product_family', 'product_model')
    search_fields = ('product_family__name', 'product_model__name', 'product_model__code')
    autocomplete_fields = ('product_family', 'product_model')
    formfield_overrides = JSON_FORMFIELD_OVERRIDES


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
        'lock', 'hinges', 'additional',
        'panel_frame_preset', 'filling_preset', 'base_preset', 'covering_preset',
    )
    formfield_overrides = JSON_FORMFIELD_OVERRIDES

    fieldsets = (
        (None, {'fields': ('product',)}),
        ('חומרים עיקריים', {
            'fields': (
                ('covering', 'covering_consumption'),
                ('base', 'base_consumption'),
                ('filling', 'filling_consumption'),
                ('panel_frame', 'panel_frame_consumption'),
                ('casing', 'casing_consumption'),
                ('frame', 'frame_consumption'),
            )
        }),
        ('פרזול', {
            'fields': ('lock', 'hinges', 'additional')
        }),
        ('פריסטים של פאזל', {
            'classes': ('collapse',),
            'fields': (
                ('panel_frame_preset', 'filling_preset'),
                ('base_preset', 'covering_preset'),
            )
        }),
        ('פרופילים ואחרים', {
            'classes': ('collapse',),
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
    list_display = ('id', 'display_locks', 'display_families', 'base_door_height', 'base_lock_height', 'step',
                    'alignment_tolerance')
    list_filter = ('product_families', 'locks')
    search_fields = ('locks__name', 'locks__sku', 'product_families__name')
    autocomplete_fields = ('locks',)
    filter_horizontal = ('product_families',)
    save_as = True
    fieldsets = (
        ('תחולה', {'fields': ('product_families', 'locks')}),
        ('חישוב גובה מנעול', {'fields': (('base_door_height', 'base_lock_height'), ('step', 'alignment_tolerance'))}),
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
    autocomplete_fields = ('hinges',)
    filter_horizontal = ('product_families',)
    readonly_fields = ('hinge_count',)
    save_as = True
    fieldsets = (
        ('תחולה', {'fields': ('product_families', 'hinges')}),
        ('טווח גובה דלת', {'fields': (('min_height', 'max_height'),)}),
        ('גבהי צירים', {'fields': (('value1', 'value2', 'value3', 'value4', 'value5'), 'hinge_count')}),
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


class ProductionStationAdminForm(forms.ModelForm):
    """
    Форма админки станции с динамическими выпадающими списками из реестров
    MachineRegistry и ReportRegistry (новые модули появляются без миграций).
    """

    target_machine = forms.ChoiceField(
        label='מכונת CNC משויכת',
        required=False,
        help_text='דרייברים רשומים אוטומטית מתוך apps/production/cnc/',
    )
    report_handler = forms.ChoiceField(
        label='מודול דו"ח (Handler)',
        required=False,
        help_text='מודולי דוחות רשומים אוטומטית מתוך apps/production/reports/',
    )

    class Meta:
        model = ProductionStation
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.production.cnc import MachineRegistry
        from apps.production.reports import ReportRegistry

        machine_choices = list(MachineRegistry.choices(include_empty=True))
        current_machine = getattr(self.instance, 'target_machine', '') or ''
        if current_machine and current_machine not in {c[0] for c in machine_choices}:
            machine_choices.append((current_machine, f"{current_machine} (לא רשום)"))
        self.fields['target_machine'].choices = machine_choices

        report_choices = list(ReportRegistry.choices(include_empty=True))
        current_handler = getattr(self.instance, 'report_handler', '') or ''
        if current_handler and current_handler not in {c[0] for c in report_choices}:
            report_choices.append((current_handler, f"{current_handler} (לא רשום)"))
        self.fields['report_handler'].choices = report_choices


@admin.register(ProductionStation)
class ProductionStationAdmin(ModelAdmin):
    form = ProductionStationAdminForm
    list_display = (
        'name', 'code', 'order', 'specification_type', 'report_handler',
        'target_machine', 'alternative_station', 'is_phase1', 'active',
    )
    list_editable = ('order', 'active')
    list_filter = ('active', 'specification_type', 'report_handler', 'target_machine', 'is_phase1')
    list_select_related = ('alternative_station',)
    search_fields = ('name', 'code', 'label', 'description')
    ordering = ('order', 'name')
    autocomplete_fields = ('alternative_station',)
    fieldsets = (
        ('מידע כללי', {'fields': (('name', 'code'), ('order', 'is_phase1', 'active'), 'description')}),
        ('מפרט וסוג פלט', {'fields': ('specification_type', 'report_handler', 'template_name')}),
        ('ניתוב וציוד CNC', {'fields': ('target_machine', 'alternative_station')}),
        ('כפתורים והגדרות ממשק', {'classes': ('collapse',), 'fields': ('label', 'hint')}),
    )


@admin.register(CustomizerProductionStation)
class CustomizerProductionStationAdmin(ModelAdmin):
    list_display = ('customizer', 'station', 'force_alternative_machine')
    list_filter = ('force_alternative_machine', 'station')
    list_editable = ('force_alternative_machine',)
    list_select_related = ('customizer', 'station')
    autocomplete_fields = ('customizer', 'station')
    search_fields = ('customizer__name', 'customizer__code', 'station__name', 'station__code')


class ProductionRouteStepInline(TabularInline):
    model = ProductionRouteStep
    extra = 2
    ordering = ('order',)
    autocomplete_fields = ('station',)


@admin.register(ProductionRoute)
class ProductionRouteAdmin(ModelAdmin):
    list_display = ('name', 'active', 'display_products')
    list_filter = ('active',)
    autocomplete_fields = ('products',)
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
    inlines = [CustomizerPuzzleMappingInline]


@admin.register(CustomizerPuzzleMapping)
class CustomizerPuzzleMappingAdmin(ModelAdmin):
    list_display = ('customizer', 'preset')
    list_select_related = ('customizer', 'preset')
    search_fields = ('customizer__name', 'customizer__code', 'preset__name')
    autocomplete_fields = ('customizer', 'preset')


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
    list_display = ('id', 'file_name', 'label_name', 'machining_feature', 'display_hardware', 'display_families')
    list_select_related = ('machining_feature',)
    list_filter = ('machining_feature', 'door_families', 'hardware__role')
    search_fields = (
        'file_name', 'label_name', 'description',
        'machining_feature__name', 'machining_feature__code',
        'hardware__name', 'hardware__sku', 'door_families__name',
    )
    autocomplete_fields = ('hardware', 'machining_feature')
    filter_horizontal = ('door_families',)
    save_as = True
    fieldsets = (
        ('מידע כללי', {'fields': ('file_name', 'label_name', 'machining_feature', 'description')}),
        ('שיוך לפרזול ומשפחות', {'fields': ('hardware', 'door_families')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('machining_feature').prefetch_related('hardware',
                                                                                                  'door_families')

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
