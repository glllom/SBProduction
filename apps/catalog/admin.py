from django.contrib import admin
from django.db import models
from django_json_widget.widgets import JSONEditorWidget
from unfold.admin import ModelAdmin, StackedInline, TabularInline

from apps.engineering.models import BOM, ProductEngineeringRule
from .models import (
    Color,
    Customizer,
    Front,
    Hardware,
    MachiningFeature,
    Material,
    ProductFamily,
    ProductModel,
    ProductType,
    Series,
)

JSON_FORMFIELD_OVERRIDES = {
    models.JSONField: {'widget': JSONEditorWidget},
}


@admin.register(ProductType)
class ProductTypeAdmin(ModelAdmin):
    list_display = ('id', 'name', 'code', 'active')
    list_filter = ('active',)
    search_fields = ('name', 'code', 'description')
    fieldsets = (
        ('מידע כללי', {
            'fields': ('name', 'code', 'description', 'active')
        }),
    )


class FamilyEngineeringRuleInline(StackedInline):
    model = ProductEngineeringRule
    fk_name = 'product_family'
    exclude = ('product_model',)
    extra = 0
    max_num = 1
    verbose_name_plural = 'כללים הנדסיים למשפחה (JSON)'
    formfield_overrides = JSON_FORMFIELD_OVERRIDES


@admin.register(ProductFamily)
class ProductFamilyAdmin(ModelAdmin):
    list_display = ('id', 'name', 'product_type', 'code', 'active', 'allowed_direction')
    list_select_related = ('product_type',)
    list_filter = ('product_type', 'active', 'supports_split_installation', 'allowed_direction')
    search_fields = ('name', 'code', 'description', 'product_type__code')
    inlines = [FamilyEngineeringRuleInline]
    fieldsets = (
        ('מידע כללי', {
            'fields': (
                'product_type', 'name', 'code', 'description',
                'active', 'allowed_direction', 'supports_split_installation', 'has_handle',
            )
        }),
        ('מבנה', {
            'fields': ('has_door', 'has_frame', 'default_value_for_frame')
        }),
    )


class FrontInline(TabularInline):
    """Displays the list of fronts directly inside the series form."""
    model = Front
    extra = 1
    fields = ('name', 'code', 'finish_type', 'active')


@admin.register(Series)
class SeriesAdmin(ModelAdmin):
    list_display = ('id', 'name', 'code', 'active')
    list_filter = ('active',)
    search_fields = ('name', 'code', 'description')
    inlines = [FrontInline]


@admin.register(Front)
class FrontAdmin(ModelAdmin):
    list_display = ('id', 'name', 'code', 'series', 'finish_type', 'active')
    list_select_related = ('series',)
    list_filter = ('series', 'finish_type', 'active')
    search_fields = ('name', 'code', 'description', 'series__code')
    fieldsets = (
        ('מידע כללי', {
            'fields': ('series', 'name', 'code', 'description', 'active')
        }),
        ('גימור', {
            'fields': ('finish_type',)
        }),
    )


@admin.register(Color)
class FrameColorAdmin(ModelAdmin):
    list_display = ('id', 'name', 'code', 'active')
    list_editable = ('active',)
    list_filter = ('active',)
    search_fields = ('name', 'code', 'description')


@admin.register(Material)
class MaterialAdmin(ModelAdmin):
    list_display = ('id', 'name', 'common_name', 'sku', 'material_type', 'color', 'thickness', 'price_per_unit')
    list_select_related = ('color',)
    list_filter = ('material_type', 'color')
    search_fields = ('name', 'common_name', 'sku')
    autocomplete_fields = ('outward_substitute',)
    fieldsets = (
        ('מידע כללי', {
            'fields': ('name', 'common_name', 'sku', 'material_type', 'color')
        }),
        ('מידות', {
            'fields': ('thickness', 'length', 'width')
        }),
        ('מחיר והחלפה', {
            'fields': ('price_per_unit', 'unit_of_measure', 'outward_substitute')
        }),
    )


@admin.register(MachiningFeature)
class MachiningFeatureAdmin(ModelAdmin):
    list_display = ('id', 'name', 'code', 'affects_role')
    list_filter = ('affects_role',)
    search_fields = ('name', 'code')


@admin.register(Hardware)
class HardwareAdmin(ModelAdmin):
    list_display = (
        'id', 'name', 'sku', 'role', 'machining_feature', 'common_name',
        'par1_value', 'rule_tag', 'color', 'price', 'active',
    )
    list_select_related = ('color', 'machining_feature')
    list_editable = ('active',)
    list_filter = ('role', 'machining_feature', 'rule_tag', 'active', 'color')
    search_fields = ('name', 'sku', 'common_name', 'par1_value', 'description')
    autocomplete_fields = ('machining_feature', 'color', 'product_models', 'components')
    filter_horizontal = ('product_types', 'product_families')
    save_as = True
    fieldsets = (
        ('מידע כללי', {
            'fields': (
                ('name', 'sku'),
                ('role', 'common_name'),
                ('machining_feature', 'color'),
                ('price', 'active'),
                'description',
            )
        }),
        ('חוקי חישוב ופרמטרים (מחסן והתאמות)', {
            'description': 'par1 משמש למידה בס"מ (גיליוטינה) או סוג נעילה (WC / CYLINDER / KEY) לקישור זוגות.',
            'fields': (
                'rule_tag',
                ('par1_label', 'par1_value', 'par1_desc'),
                ('par2_label', 'par2_value', 'par2_desc'),
                ('par3_label', 'par3_value', 'par3_desc'),
            )
        }),
        ('תאימות למוצרים', {
            'classes': ('collapse',),
            'fields': ('product_types', 'product_families', 'product_models')
        }),
        ('הרכב (רכיבים)', {
            'classes': ('collapse',),
            'fields': ('components',)
        }),
    )


class BOMInline(StackedInline):
    """Allows editing the BOM directly on the Product page."""
    model = BOM
    can_delete = False
    verbose_name_plural = 'עץ מוצר (BOM)'
    fk_name = 'product'
    formfield_overrides = JSON_FORMFIELD_OVERRIDES
    autocomplete_fields = (
        'covering', 'base', 'filling', 'panel_frame', 'casing', 'frame',
        'profile1', 'profile2', 'profile3',
        'other1', 'other2', 'other3', 'other4', 'other5',
        'lock', 'hinges', 'additional',
        'filling_preset', 'panel_frame_preset', 'base_preset', 'covering_preset',
    )
    fieldsets = (
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

        ('פרמטרים טכנולוגיים', {
            'classes': ('collapse',),
            'fields': ('cut_coefficients',)
        }),
    )


class ModelEngineeringRuleInline(StackedInline):
    model = ProductEngineeringRule
    fk_name = 'product_model'
    exclude = ('product_family',)
    extra = 0
    max_num = 1
    verbose_name_plural = 'חריגות הנדסיות לדגם (JSON)'
    formfield_overrides = JSON_FORMFIELD_OVERRIDES


@admin.register(ProductModel)
class ProductAdmin(ModelAdmin):
    list_display = (
        'id', 'code', 'name', 'product_family', 'series',
        'parent_model', 'active',
    )
    list_select_related = ('product_family__product_type', 'series', 'parent_model')
    list_filter = ('active', 'product_family__product_type', 'product_family', 'series')
    search_fields = ('code', 'name', 'description', 'product_family__code')
    autocomplete_fields = ('parent_model', 'required_customizers')
    save_as = True
    fieldsets = (
        ('מידע כללי', {
            'fields': ('code', 'name', 'description', 'active')
        }),
        ('סיווג', {
            'fields': ('product_family', 'series', 'parent_model')
        }),
        ('התאמות אישיות', {
            'fields': ('required_customizers',)
        }),
    )
    inlines = [BOMInline, ModelEngineeringRuleInline]


@admin.register(Customizer)
class CustomizerAdmin(ModelAdmin):
    list_display = (
        'id', 'code', 'name', 'tag', 'hidden_in_sales',
        'outward_replacement', 'active', 'hardware',
    )
    list_select_related = ('hardware', 'outward_replacement')
    list_filter = ('active', 'hidden_in_sales', 'tag')
    search_fields = ('code', 'name', 'tag', 'description')
    autocomplete_fields = ('hardware', 'outward_replacement', 'product_models')
    filter_horizontal = ('product_types', 'product_families')
    formfield_overrides = JSON_FORMFIELD_OVERRIDES
    save_as = True
    fieldsets = (
                    ('מידע כללי', {
                        'fields': (
                            'code', 'name', 'description',
                            'active', 'hidden_in_sales',
                            'tag', 'outward_replacement',
                        )
                    }),
                    ('שיוך לקטלוג (ריק = גלובלי)', {
                        'classes': ('collapse',),
                        'fields': ('product_types', 'product_families', 'product_models')
                    }),
                    ('פרזול ו-BOM', {
                        'fields': ('hardware', 'bom_overrides')
                    }),
                ) + tuple(
        (f'פרמטר {i}', {
            'classes': ('collapse',),
            'fields': (
                f'par{i}_label', f'par{i}_required', f'par{i}_value',
                f'par{i}_hint', f'par{i}_options',
            ),
        }) for i in range(1, 6)
    )
