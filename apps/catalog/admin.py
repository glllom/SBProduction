from django.contrib import admin
from django.db import models
from django_json_widget.widgets import JSONEditorWidget

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


@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'code')
    search_fields = ('name',)


@admin.register(ProductFamily)
class ProductFamilyAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'product_type', 'code',)
    list_filter = ('product_type', 'supports_split_installation',)
    search_fields = ('name',)


class FrontInline(admin.TabularInline):
    """Displays the list of fronts directly inside the series form."""
    model = Front
    extra = 1


class FrameColorInline(admin.TabularInline):
    """Displays the list of frame colors directly inside the series form."""
    model = Color
    extra = 1


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(Front)
class FrontAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'code', 'series')
    list_filter = ('series',)
    search_fields = ('name', 'code')


@admin.register(Color)
class FrameColorAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'active')
    list_filter = ('id', 'name')
    search_fields = ('name', 'code')


@admin.register(Handle)
class HandleAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'code', 'active')
    search_fields = ('name', 'code')


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'common_name', 'sku', 'material_type', 'color', 'thickness', 'price_per_unit')
    list_filter = ('material_type', 'color')
    search_fields = ('name', 'common_name', 'sku')


@admin.register(Hardware)
class HardwareAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'sku', 'price', 'active')
    search_fields = ('name', 'sku')
    filter_horizontal = ('product_types', 'product_families', 'product_models', 'components')


class BOMInline(admin.StackedInline):
    """Allows editing the BOM directly on the Product page."""
    model = BOM
    can_delete = False
    verbose_name_plural = 'עץ מוצר (BOM)'
    fk_name = 'product'
    raw_id_fields = ('covering', 'base', 'filling', 'casing', 'frame',
                     'profile1', 'profile2', 'profile3',
                     'other1', 'other2', 'other3', 'other4', 'other5',
                     'lock', 'hinges')
    filter_horizontal = ('additional', 'required_customizers')
    fieldsets = (
        ('Materials (חומרים)', {
            'fields': (
                ('covering', 'covering_consumption'),
                ('base', 'base_consumption'),
                ('filling', 'filling_consumption'),
                ('casing', 'casing_consumption'),
                ('frame', 'frame_consumption'),
            )
        }),
        ('Profiles & Others (פרופילים ואחרים)', {
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
        ('Hardware (פרזול)', {
            'fields': ('lock', 'hinges', 'additional', 'required_customizers')
        }),
        ('Technological Parameters (פרמטרים טכנולוגיים)', {
            'fields': ('cut_coefficients',)
        }),
    )


class ProductTechnicalDataInline(admin.StackedInline):
    model = ProductTechnicalData
    can_delete = False
    verbose_name_plural = 'נתונים טכניים'


@admin.register(ProductModel)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'product_family', 'series', 'parent_model',
                    'has_door', 'has_frame')
    list_filter = ('product_family__product_type', 'product_family', 'series')
    search_fields = ('code', 'name')
    raw_id_fields = ('parent_model',)
    filter_horizontal = ('required_customizers',)
    inlines = [BOMInline, ProductTechnicalDataInline]


@admin.register(Customizer)
class CustomizerAdmin(admin.ModelAdmin):
    formfield_overrides = {
        models.JSONField: {'widget': JSONEditorWidget},
    }
