from django.contrib import admin

from apps.production.models import ProductTechnicalData, BOM
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
)


@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(ProductFamily)
class ProductFamilyAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'product_type')
    list_filter = ('product_type',)
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
    inlines = [FrontInline]


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


class BOMInline(admin.StackedInline):
    """Allows editing the BOM directly on the Product page."""
    model = BOM
    can_delete = False
    verbose_name_plural = 'עץ מוצר (BOM)'
    fk_name = 'product'
    filter_horizontal = ('lock', 'hinges', 'additional', 'nested_boms')
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
        ('Nested BOMs (עצי מוצר מוטמעים)', {
            'fields': ('nested_boms',)
        }),
    )


class ProductTechnicalDataInline(admin.StackedInline):
    model = ProductTechnicalData
    can_delete = False
    verbose_name_plural = 'נתונים טכניים'


@admin.register(ProductModel)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'product_family', 'series')
    list_filter = ('product_family__product_type', 'product_family', 'series')
    search_fields = ('code', 'name')
    inlines = [BOMInline, ProductTechnicalDataInline]


from django.contrib import admin
from .models import Customizer


@admin.register(Customizer)
class CustomizerAdmin(admin.ModelAdmin):
    # Fields displayed in the list
    list_display = (
        "id",
        "code",
        "name",
        "tag",
        "priority",
        "active",
        "product_type",
        "product_family",
        "product_model",
    )

    # Quick filter on the right
    list_filter = (
        "active",
        "tag",
        "product_type",
        "product_family",
        "product_model",
    )

    # Search by code and name
    search_fields = ("code", "name", "description", "tag")

    # Default ordering
    ordering = ("priority", "code")

    # Grouping fields in the edit form
    fieldsets = (
        (
            "Основная информация",
            {"fields": ("code", "name", "description", "active")},
        ),
        (
            "Привязка к каталогу",
            {
                "fields": (
                    "product_type",
                    "product_family",
                    "product_model",
                )
            },
        ),
        (
            "Настройки движка (Pipeline)",
            {
                "fields": ("tag", "priority"),
                "classes": ("collapse",),  # Can be collapsed
            },
        ),
        (
            "Параметр 1",
            {
                "fields": ("par1_label", "par1_value", "par1_hint"),
                "classes": ("collapse",),
            },
        ),
        (
            "Параметр 2",
            {
                "fields": ("par2_label", "par2_value", "par2_hint"),
                "classes": ("collapse",),
            },
        ),
        (
            "Параметр 3",
            {
                "fields": ("par3_label", "par3_value", "par3_hint"),
                "classes": ("collapse",),
            },
        ),
        (
            "Параметр 4",
            {
                "fields": ("par4_label", "par4_value", "par4_hint"),
                "classes": ("collapse",),
            },
        ),
    )
