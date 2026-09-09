from django.contrib import admin

from apps.production.models import ProductTechnicalData, BOM, ProductionRoute
from .models import (
    ProductType,
    ProductFamily,
    Series,
    Front,
    Color,
    Material,
    ProductModel,
    Handle,
    Hardware,
    Customizer,
)


class ProductionRouteTypeInline(admin.TabularInline):
    model = ProductionRoute
    fk_name = 'product_type'
    extra = 1


class ProductionRouteFamilyInline(admin.TabularInline):
    model = ProductionRoute
    fk_name = 'product_family'
    extra = 1


class ProductionRouteSeriesInline(admin.TabularInline):
    model = ProductionRoute
    fk_name = 'series'
    extra = 1


class ProductionRouteModelInline(admin.TabularInline):
    model = ProductionRoute
    fk_name = 'product_model'
    extra = 1


@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)
    inlines = [ProductionRouteTypeInline]


@admin.register(ProductFamily)
class ProductFamilyAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'product_type', 'thickness', 'leaf_height_adjustment', 'leaf_width_adjustment')
    list_filter = ('product_type',)
    search_fields = ('name',)
    inlines = [ProductionRouteFamilyInline]


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
    inlines = [FrontInline, ProductionRouteSeriesInline]


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
    filter_horizontal = ('lock', 'hinges', 'additional')
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
            'fields': ('lock', 'hinges', 'additional')
        }),
    )


class ProductTechnicalDataInline(admin.StackedInline):
    model = ProductTechnicalData
    can_delete = False
    verbose_name_plural = 'נתונים טכניים'


@admin.register(ProductModel)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'product_family', 'series', 'parent_model', 'has_door', 'has_frame')
    list_filter = ('product_family__product_type', 'product_family', 'series')
    search_fields = ('code', 'name')
    raw_id_fields = ('parent_model',)
    inlines = [BOMInline, ProductTechnicalDataInline, ProductionRouteModelInline]


from django.contrib import admin
from .models import Customizer


@admin.register(Customizer)
class CustomizerAdmin(admin.ModelAdmin):
    # Fields displayed in the list
    list_display = (
        "code",
        "name",
        "tag",
        "active",
        "hardware",
    )

    # Quick filter on the right
    list_filter = (
        "active",
        "tag",
        "product_types",
        "product_families",
        "product_models",
    )

    # Search by code and name
    search_fields = ("code", "name", "description", "tag")

    # Filter horizontal for M2M
    filter_horizontal = ("product_types", "product_families", "product_models", "materials")

    # Default ordering
    ordering = ("tag", "code")

    # Grouping fields in the edit form
    fieldsets = (
        (
            "Основная информация",
            {"fields": ("code", "name", "description", "active", "hardware")},
        ),
        (
            "Привязка к каталогу",
            {
                "fields": (
                    "product_types",
                    "product_families",
                    "product_models",
                )
            },
        ),
        (
            "Настройки движка (Pipeline)",
            {
                "fields": ("tag",),
                "classes": ("collapse",),  # Can be collapsed
            },
        ),
        (
            "Комплектующие и материалы (Replacement/Addition)",
            {
                "fields": ("materials",),
            },
        ),
        (
            "Параметр 1",
            {
                "fields": ("par1_label", 'par1_options', "par1_value", "par1_hint"),
                "classes": ("collapse",),
            },
        ),
        (
            "Параметр 2",
            {
                "fields": ("par2_label", 'par2_options', "par2_value", "par2_hint"),
                "classes": ("collapse",),
            },
        ),
        (
            "Параметр 3",
            {
                "fields": ("par3_label", 'par3_options', "par3_value", "par3_hint"),
                "classes": ("collapse",),
            },
        ),
        (
            "Параметр 4",
            {
                "fields": ("par4_label", 'par4_options', "par4_value", "par4_hint"),
                "classes": ("collapse",),
            },
        ),
        (
            "Параметр 5",
            {
                "fields": ("par5_label", 'par5_options', "par5_value", "par5_hint"),
                "classes": ("collapse",),
            },
        ),
    )
