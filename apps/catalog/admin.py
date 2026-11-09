from django.contrib import admin
from django.db import models
from django_json_widget.widgets import JSONEditorWidget
from unfold.admin import ModelAdmin, TabularInline, StackedInline

from apps.production.models import ProductTechnicalData, BOM
from .models import Customizer
from .models import (
    ProductType,
    ProductFamily,
    Series,
    Front,
    Color,
    Material,
    ProductModel,
    Handle,
    Hardware
)


JSON_FORMFIELD_OVERRIDES = {
    models.JSONField: {'widget': JSONEditorWidget},
}


@admin.register(ProductType)
class ProductTypeAdmin(ModelAdmin):
    list_display = ('id', 'name', 'code', 'active', 'has_door', 'has_frame')
    list_filter = ('active', 'has_door', 'has_frame')
    search_fields = ('name', 'code', 'description')
    fieldsets = (
        ('מידע כללי', {
            'fields': ('name', 'code', 'description', 'active')
        }),
        ('מבנה', {
            'fields': ('has_door', 'has_frame')
        }),
    )


@admin.register(ProductFamily)
class ProductFamilyAdmin(ModelAdmin):
    list_display = ('id', 'name', 'product_type', 'code', 'active', 'allowed_direction')
    list_select_related = ('product_type',)
    list_filter = ('product_type', 'active', 'supports_split_installation', 'allowed_direction')
    search_fields = ('name', 'code', 'description', 'product_type__code')
    fieldsets = (
        ('מידע כללי', {
            'fields': ('product_type', 'name', 'code', 'description', 'active', 'allowed_direction',
                       'supports_split_installation')
        }),
        ('גיאומטריה ועובי', {
            'fields': ('thickness', 'default_value_for_frame', 'frame_inner_height_reduction',
                       'frame_inner_width_reduction', 'double_leaf_overlap')
        }),
        ('מרווחי כנף', {
            'fields': ('leaf_top_clearance', 'leaf_bottom_clearance', 'leaf_side_clearance')
        }),
    )


class FrontInline(TabularInline):
    """Displays the list of fronts directly inside the series form."""
    model = Front
    extra = 1


class FrameColorInline(TabularInline):
    """Displays the list of frame colors directly inside the series form."""
    model = Color
    extra = 1


@admin.register(Series)
class SeriesAdmin(ModelAdmin):
    list_display = ('id', 'name', 'code', 'active')
    list_filter = ('active',)
    search_fields = ('name', 'code', 'description')


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


@admin.register(Handle)
class HandleAdmin(ModelAdmin):
    list_display = ('id', 'name', 'code', 'active')
    list_editable = ('active',)
    search_fields = ('name', 'code')


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


@admin.register(Hardware)
class HardwareAdmin(ModelAdmin):
    list_display = ('id', 'name', 'sku', 'common_name', 'price', 'color', 'active')
    list_select_related = ('color',)
    list_editable = ('active',)
    list_filter = ('active', 'color')
    search_fields = ('name', 'sku', 'common_name', 'description')
    filter_horizontal = ('product_types', 'product_families', 'product_models', 'components')
    save_as = True
    fieldsets = (
        ('מידע כללי', {
            'fields': ('name', 'sku', 'price', 'description', 'active', 'common_name', 'color')
        }),
        ('תאימות למוצרים', {
            'fields': ('product_types', 'product_families', 'product_models')
        }),
        ('הרכב (רכיבים)', {
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
    autocomplete_fields = ('covering', 'base', 'filling', 'panel_frame', 'casing', 'frame',
                           'profile1', 'profile2', 'profile3',
                           'other1', 'other2', 'other3', 'other4', 'other5',
                           'lock', 'hinges',
                           'filling_preset', 'panel_frame_preset', 'base_preset', 'covering_preset')
    filter_horizontal = ('additional', 'required_customizers')
    fieldsets = (
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


class ProductTechnicalDataInline(StackedInline):
    model = ProductTechnicalData
    can_delete = False
    verbose_name_plural = 'נתונים טכניים'


@admin.register(ProductModel)
class ProductAdmin(ModelAdmin):
    list_display = ('id', 'code', 'name', 'product_family', 'series', 'parent_model',
                    'active', 'has_door', 'has_frame')
    list_select_related = ('product_family__product_type', 'series', 'parent_model')
    list_filter = ('active', 'product_family__product_type', 'product_family', 'series')
    search_fields = ('code', 'name', 'description', 'series__code', 'product_family__code')
    autocomplete_fields = ('parent_model',)
    filter_horizontal = ('required_customizers',)
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
    inlines = [BOMInline, ProductTechnicalDataInline]


@admin.register(Customizer)
class CustomizerAdmin(ModelAdmin):
    list_display = ('id', 'code', 'name', 'tag', 'is_required', 'active', 'hardware')
    list_select_related = ('hardware',)
    list_filter = ('active', 'is_required', 'tag')
    search_fields = ('code', 'name', 'tag', 'description')
    autocomplete_fields = ('hardware',)
    filter_horizontal = ('product_types', 'product_families', 'product_models')
    formfield_overrides = JSON_FORMFIELD_OVERRIDES
    save_as = True
    fieldsets = (
        ('מידע כללי', {
            'fields': ('code', 'name', 'description', 'active', 'is_required', 'tag')
        }),
        ('שיוך לקטלוג (ריק = גלובלי)', {
            'fields': ('product_types', 'product_families', 'product_models')
        }),
        ('פרזול ו-BOM', {
            'fields': ('hardware', 'bom_overrides')
        }),
    ) + tuple(
        (f'פרמטר {i}', {
            'classes': ('collapse',),
            'fields': (f'par{i}_label', f'par{i}_required', f'par{i}_value', f'par{i}_hint', f'par{i}_options'),
        }) for i in range(1, 6)
    )
