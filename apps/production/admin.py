from django.contrib import admin
from .models import ProductTechnicalData

@admin.register(ProductTechnicalData)
class ProductTechnicalDataAdmin(admin.ModelAdmin):
    list_display = ('product', 'cnc_program_name')
    search_fields = ('product__name', 'product__code', 'cnc_program_name')
    raw_id_fields = ('product',)
