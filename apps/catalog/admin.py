from django.contrib import admin
from .models import (
    ProductType,
    ProductFamily,
    Series,
    Front,
    Material,
    Product,
    ProductMaterial,
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
    """Отображает список фронтов прямо внутри формы серии."""
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


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'sku', 'material_type', 'thickness', 'price_per_unit')
    list_filter = ('material_type',)
    search_fields = ('name', 'sku')


class ProductMaterialInline(admin.TabularInline):
    """Позволяет добавлять материалы/комплектующие прямо на странице Продукта."""
    model = ProductMaterial
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'sku', 'name', 'family', 'series')
    list_filter = ('family__product_type', 'family', 'series')
    search_fields = ('sku', 'name')
    inlines = [ProductMaterialInline]