from django.contrib import admin
from .models import ProductTechnicalData, BOMItem

@admin.register(ProductTechnicalData)
class ProductTechnicalDataAdmin(admin.ModelAdmin):
    list_display = ('product', 'cnc_program_name')
    search_fields = ('product__name', 'product__code', 'cnc_program_name')
    raw_id_fields = ('product',)


@admin.register(BOMItem)
class BOMItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'parent_product', 'material', 'hardware', 'child_product', 'tag', 'quantity_formula')
    list_filter = ('parent_product', 'tag')
    search_fields = ('parent_product__name', 'material__name', 'hardware__name', 'child_product__name', 'tag')
    raw_id_fields = ('parent_product', 'material', 'hardware', 'child_product')
