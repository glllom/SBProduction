from django.contrib import admin
from .models import (
    ProductType, ProductFamily, Series, ProductModel, 
    BomTags, Component, SheetMaterial, LineMaterial, 
    ProductModelBOM, Customizer
)

@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku')

@admin.register(ProductFamily)
class ProductFamilyAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'product_type')

@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku')

@admin.register(ProductModel)
class ProductModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'product_family', 'series')

@admin.register(BomTags)
class BomTagsAdmin(admin.ModelAdmin):
    list_display = ('tag',)

@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku')

@admin.register(SheetMaterial)
class SheetMaterialAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'width', 'length', 'thickness', 'group')

@admin.register(LineMaterial)
class LineMaterialAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku')

@admin.register(ProductModelBOM)
class ProductModelBOMAdmin(admin.ModelAdmin):
    list_display = ('product_model', 'component', 'tag', 'qty')

@admin.register(Customizer)
class CustomizerAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'product_model')
