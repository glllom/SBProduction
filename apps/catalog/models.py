from django.db import models


# ==========================================
# 1. HIERARCHY: ProductType -> ProductFamily
# ==========================================

class ProductType(models.Model):
    code = models.CharField('Code', max_length=32, unique=True)
    name = models.CharField('Name', max_length=100, unique=True)
    description = models.TextField('Description', blank=True)

    class Meta:
        verbose_name = 'Product Type'
        verbose_name_plural = 'Product Types'

    def __str__(self):
        return self.name


class ProductFamily(models.Model):
    product_type = models.ForeignKey(
        ProductType,
        on_delete=models.PROTECT,
        related_name='families',
        verbose_name='Product Type'
    )
    name = models.CharField('Name', max_length=100)
    code = models.CharField('Code', max_length=32, unique=True)
    description = models.TextField('Description', blank=True)


    class Meta:
        verbose_name = 'Product Family'
        verbose_name_plural = 'Product Families'
        unique_together = ('product_type', 'name')

    def __str__(self):
        return f"{self.product_type.name} -> {self.name}"


# ==========================================
# 2. SERIES & FRONTS
# ==========================================

class Series(models.Model):
    code = models.CharField('Code', max_length=32, unique=True)
    name = models.CharField('Name', max_length=100, unique=True)
    description = models.TextField('Description', blank=True)

    class Meta:
        verbose_name = 'Series'
        verbose_name_plural = 'Series'

    def __str__(self):
        return self.name


class Front(models.Model):
    series = models.ForeignKey(
        Series,
        on_delete=models.CASCADE,
        related_name='fronts',
        verbose_name='Series'
    )
    name = models.CharField('Name', max_length=100)
    code = models.CharField('Code/SKU', max_length=50, blank=True)

    class Meta:
        verbose_name = 'Front'
        verbose_name_plural = 'Fronts'
        unique_together = ('series', 'name')

    def __str__(self):
        return f"{self.series.name} - Front: {self.name}"


# ==========================================
# 3. MATERIALS & COMPONENTS
# ==========================================


class Material(models.Model):
    name = models.CharField('Name', max_length=255)
    sku = models.CharField('SKU', max_length=100, unique=True)
    material_type = models.CharField(
        'Material Type',
        max_length=20,

    )

    thickness = models.DecimalField('Thickness, mm', max_digits=5, decimal_places=2, null=True, blank=True)
    length = models.DecimalField('Standard Length, mm', max_digits=7, decimal_places=2, null=True, blank=True)
    width = models.DecimalField('Standard Width, mm', max_digits=7, decimal_places=2, null=True, blank=True)

    price_per_unit = models.DecimalField('Price per unit', max_digits=10, decimal_places=2, default=0)
    unit_of_measure = models.CharField('Unit of Measure', max_length=20, default='pcs')

    class Meta:
        verbose_name = 'Material'
        verbose_name_plural = 'Materials'

    def __str__(self):
        return f"{self.name} ({self.sku})"


# ==========================================
# 4. PRODUCT & BILL OF MATERIALS (BOM)
# ==========================================

class Product(models.Model):
    """
    Product master definition.
    Represents a unique intersection of ProductFamily x Series.
    Stores all technological requirements, manufacturing parameters, and CNC rules.
    """
    sku = models.CharField('SKU', max_length=100, unique=True)
    name = models.CharField('Name', max_length=255)

    family = models.ForeignKey(
        ProductFamily,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name='Product Family'
    )
    series = models.ForeignKey(
        Series,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name='Series'
    )

    base_material_thickness = models.DecimalField(
        'Base Material Thickness, mm',
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True
    )
    finished_thickness = models.DecimalField(
        'Finished Product Thickness, mm',
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True
    )

    parametric_rules = models.JSONField(
        'Parametric Calculation & CNC Rules',
        default=dict,
        blank=True
    )

    created_at = models.DateTimeField('Created At', auto_now_add=True)
    updated_at = models.DateTimeField('Updated At', auto_now=True)

    class Meta:
        verbose_name = 'Product'
        verbose_name_plural = 'Products'
        unique_together = ('family', 'series')

    def __str__(self):
        return f"[{self.sku}] {self.name} ({self.family.name} / {self.series.name})"


class ProductMaterial(models.Model):
    """
    Bill of Materials (BOM) linking products and raw materials with formulas.
    """
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='bom_items',
        verbose_name='Product'
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        related_name='used_in_products',
        verbose_name='Material'
    )

    quantity_formula = models.CharField(
        'Consumption Formula',
        max_length=255,
        default='1',
        help_text='Use variables like H (height), W (width), D (depth)'
    )

    note = models.CharField('Part / Component Note', max_length=255, blank=True)

    class Meta:
        verbose_name = 'BOM Item'
        verbose_name_plural = 'BOM Items'
        unique_together = ('product', 'material', 'note')

    def __str__(self):
        return f"{self.product.sku} -> {self.material.name} ({self.quantity_formula})"