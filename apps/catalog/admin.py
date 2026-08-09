from django.contrib import admin
from .models import (
    ProductType,
    ProductFamily,
    Series,
    Front,
    Material,
    ProductModel,
    ProductMaterial,
    Handle,
)
from apps.production.models import ProductTechnicalData


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


@admin.register(Handle)
class HandleAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'code', 'active')
    search_fields = ('name', 'code')


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'sku', 'material_type', 'thickness', 'price_per_unit')
    list_filter = ('material_type',)
    search_fields = ('name', 'sku')


class ProductMaterialInline(admin.TabularInline):
    """Allows adding materials/components directly on the Product page."""
    model = ProductMaterial
    extra = 1


class ProductTechnicalDataInline(admin.StackedInline):
    model = ProductTechnicalData
    can_delete = False
    verbose_name_plural = 'נתונים טכניים'


@admin.register(ProductModel)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'product_family', 'series')
    list_filter = ('product_family__product_type', 'product_family', 'series')
    search_fields = ('code', 'name')
    inlines = [ProductMaterialInline, ProductTechnicalDataInline]

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