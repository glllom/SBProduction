from django.contrib import admin
from .models import ProductTechnicalData, BOM, LockStandardHeight, HingeStandardHeight

@admin.register(ProductTechnicalData)
class ProductTechnicalDataAdmin(admin.ModelAdmin):
    list_display = ('product', 'cnc_program_name')
    search_fields = ('product__name', 'product__code', 'cnc_program_name')
    raw_id_fields = ('product',)


@admin.register(BOM)
class BOMAdmin(admin.ModelAdmin):
    list_display = ('product',)
    raw_id_fields = ('product', 'covering', 'base', 'filling', 'casing', 'frame', 
                    'profile1', 'profile2', 'profile3', 
                    'other1', 'other2', 'other3', 'other4', 'other5')
    filter_horizontal = ('lock', 'hinges', 'additional', 'nested_boms')
    
    fieldsets = (
        (None, {
            'fields': ('product',)
        }),
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


@admin.register(LockStandardHeight)
class LockStandardHeightAdmin(admin.ModelAdmin):
    list_display = ('lock', 'base_door_height', 'base_lock_height', 'step')
    filter_horizontal = ('product_families',)
    raw_id_fields = ('lock',)


@admin.register(HingeStandardHeight)
class HingeStandardHeightAdmin(admin.ModelAdmin):
    list_display = ('hinge', 'min_height', 'max_height', 'value1', 'value2', 'value3')
    filter_horizontal = ('product_families',)
    raw_id_fields = ('hinge',)
