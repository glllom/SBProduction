from django.contrib import admin
from .models import (
    ProductType,
    ProductFamily,
    Series,
    Front,
    Material,
    ProductModel,
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


@admin.register(ProductModel)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'product_family', 'series')
    list_filter = ('product_family__product_type', 'product_family', 'series')
    search_fields = ('code', 'name')
    inlines = [ProductMaterialInline]

from django.contrib import admin
from .models import Customizer


@admin.register(Customizer)
class CustomizerAdmin(admin.ModelAdmin):
    # Поля, отображаемые в списке
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

    # Быстрый фильтр справа
    list_filter = (
        "active",
        "tag",
        "product_type",
        "product_family",
        "product_model",
    )

    # Поиск по коду и названию
    search_fields = ("code", "name", "description", "tag")

    # Сортировка по умолчанию
    ordering = ("priority", "code")

    # Группировка полей в форме редактирования
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
                "classes": ("collapse",),  # Можно свернуть блок
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