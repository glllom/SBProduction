from django.contrib import admin
from .models import (
    ProductType, ProductFamily, Series, ProductModel, 
    BomTags, Component, SheetMaterial, LineMaterial, 
    ProductModelBOM, Customizer, ProductStages, Front,
    ComponentChanger, ComponentChangerItem,
    Order, OrderItem, OrderItemCustomizer
)

class OrderItemCustomizerInline(admin.TabularInline):
    model = OrderItemCustomizer
    extra = 0

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    show_change_link = True

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number',)
    inlines = [OrderItemInline]

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'number', 'product_model', 'width', 'height', 'wall')
    inlines = [OrderItemCustomizerInline]

@admin.register(OrderItemCustomizer)
class OrderItemCustomizerAdmin(admin.ModelAdmin):
    list_display = ('order_item', 'customizer')

class ComponentChangerItemInline(admin.TabularInline):
    model = ComponentChangerItem
    extra = 1

@admin.register(ComponentChanger)
class ComponentChangerAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'customizer')
    filter_horizontal = ('product_models', 'components_to_remove')
    inlines = [ComponentChangerItemInline]

@admin.register(ComponentChangerItem)
class ComponentChangerItemAdmin(admin.ModelAdmin):
    list_display = ('changer', 'component', 'tag', 'qty')

@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku')

@admin.register(ProductFamily)
class ProductFamilyAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'product_type')

@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku')

@admin.register(Front)
class FrontAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'series')

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
    list_display = ('name', 'sku', 'group')

@admin.register(ProductModelBOM)
class ProductModelBOMAdmin(admin.ModelAdmin):
    list_display = ('product_model', 'component', 'sub_product_model', 'tag', 'qty')

@admin.register(Customizer)
class CustomizerAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'group')

@admin.register(ProductStages)
class ProductStagesAdmin(admin.ModelAdmin):
    list_display = ('stage',)
