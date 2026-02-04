from django.contrib import admin
from .models import (
    DBProductType, DBProductFamily, DBSeries, DBProductModel,
    DBBomTag, DBCustomizerTag, DBComponent,
    DBBomComponent, DBCustomizer, DBProductStages, DBFront,
    DBComponentChanger, DBComponentChangerItem,
    DBOrder, DBOrderItem, DBOrderItemCustomizer
)

class BomComponentsInline(admin.TabularInline):
    model = DBBomComponent
    fk_name = 'product_model'
    extra = 1

class OrderItemCustomizerInline(admin.TabularInline):
    model = DBOrderItemCustomizer
    extra = 0

class OrderItemInline(admin.TabularInline):
    model = DBOrderItem
    extra = 0
    show_change_link = True

@admin.register(DBOrder)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number',)
    inlines = [OrderItemInline]

@admin.register(DBOrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'number', 'product_model', 'width', 'height', 'wall')
    inlines = [OrderItemCustomizerInline]

@admin.register(DBOrderItemCustomizer)
class OrderItemCustomizerAdmin(admin.ModelAdmin):
    list_display = ('order_item', 'customizer')

class ComponentChangerItemInline(admin.TabularInline):
    model = DBComponentChangerItem
    extra = 1

@admin.register(DBComponentChanger)
class ComponentChangerAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'customizer')
    filter_horizontal = ('product_models', 'components_to_remove')
    inlines = [ComponentChangerItemInline]

@admin.register(DBComponentChangerItem)
class ComponentChangerItemAdmin(admin.ModelAdmin):
    list_display = ('changer', 'DBComponent', 'tag', 'qty')

@admin.register(DBProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku')

@admin.register(DBProductFamily)
class ProductFamilyAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'product_type')

@admin.register(DBSeries)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku')

@admin.register(DBFront)
class FrontAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'series')

@admin.register(DBProductModel)
class ProductModelAdmin(admin.ModelAdmin):
    list_display = ('description', 'sku', 'product_family')
    inlines = [BomComponentsInline]

@admin.register(DBBomTag)
class BomTagsAdmin(admin.ModelAdmin):
    list_display = ('tag',)

@admin.register(DBCustomizerTag)
class CustomizerTagsAdmin(admin.ModelAdmin):
    list_display = ('tag',)

@admin.register(DBComponent)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku')


@admin.register(DBBomComponent)
class BomComponentsAdmin(admin.ModelAdmin):
    list_display = ('product_model', 'DBComponent', 'tag', 'qty')

@admin.register(DBCustomizer)
class CustomizerAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'tag')

@admin.register(DBProductStages)
class ProductStagesAdmin(admin.ModelAdmin):
    list_display = ('stage',)
