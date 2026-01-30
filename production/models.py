from django.db import models

"""Product models"""
"""main group of products"""


class ProductType(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<ProductType: {self.sku}>"


class ProductFamily(models.Model):
    name = models.CharField(max_length=40)
    sku = models.CharField(max_length=20, unique=True)
    product_type = models.ForeignKey(ProductType, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<ProductFamily: {self.sku}>"


class Series(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<Series: {self.sku}>"


class Front(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)
    series = models.ForeignKey(Series, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<Front: {self.sku}>"


class ProductModel(models.Model):
    product_family = models.ForeignKey(ProductFamily, on_delete=models.CASCADE)
    name = models.CharField(max_length=256)
    sku = models.CharField(max_length=20, unique=True)
    series = models.ForeignKey(Series, on_delete=models.CASCADE)
    panel_reduction_width = models.FloatField()
    panel_reduction_height = models.FloatField()
    double_door_gap = models.FloatField()

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<ProductModel: {self.sku}>"


class BomTags(models.Model):
    tag = models.CharField(max_length=20)

    def __str__(self):
        return self.tag

    def __repr__(self):
        return f"<BomTag: {self.tag}>"


"""Material"""


class Component(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<Component: {self.sku}>"


class SheetMaterial(Component):
    width = models.FloatField()
    length = models.FloatField()
    thickness = models.FloatField()
    sheet_material_name = models.CharField(max_length=20)
    sheet_material_sku = models.CharField(max_length=20, unique=True)
    group = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.sheet_material_name} ({self.sheet_material_sku})"

    def __repr__(self):
        return f"<SheetMaterial: {self.sheet_material_sku}>"


class LineMaterial(Component):
    line_material_name = models.CharField(max_length=20)
    line_material_sku = models.CharField(max_length=20, unique=True)
    group = models.CharField(max_length=20)
    par1 = models.FloatField()
    par2 = models.FloatField()
    par3 = models.FloatField()

    def __str__(self):
        return f"{self.line_material_name} ({self.line_material_sku})"

    def __repr__(self):
        return f"<LineMaterial: {self.line_material_sku}>"


class ProductModelBOM(models.Model):
    product_model = models.ForeignKey(ProductModel, on_delete=models.CASCADE, related_name='bom_items')
    component = models.ForeignKey(Component, on_delete=models.CASCADE, null=True, blank=True)
    sub_product_model = models.ForeignKey(ProductModel, on_delete=models.CASCADE, null=True, blank=True, related_name='used_in_boms')
    tag = models.ForeignKey(BomTags, on_delete=models.CASCADE)
    qty = models.FloatField(null=True, blank=True)

    def __str__(self):
        child = self.component.sku if self.component else self.sub_product_model.sku
        return f"BOM: {self.product_model.sku} -> {child} ({self.qty})"

    def __repr__(self):
        child = self.component.sku if self.component else self.sub_product_model.sku
        return f"<ProductModelBOM: {self.product_model.sku} - {child}>"


class Customizer(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)
    group = models.CharField(max_length=20)
    par1 = models.FloatField()
    par2 = models.FloatField()
    par3 = models.FloatField()

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<Customizer: {self.sku}>"


class ProductStages(models.Model):
    stage = models.CharField(max_length=20)

    def __str__(self):
        return self.stage

    def __repr__(self):
        return f"<ProductStage: {self.stage}>"


class ComponentChanger(models.Model):
    name = models.CharField(max_length=100)
    sku = models.CharField(max_length=20, unique=True)
    customizer = models.ForeignKey(Customizer, on_delete=models.CASCADE, null=True, blank=True)
    product_models = models.ManyToManyField(ProductModel, related_name='component_changers')
    components_to_remove = models.ManyToManyField(Component, related_name='removed_by_changers', blank=True)

    def __str__(self):
        return self.name

class ComponentChangerItem(models.Model):
    changer = models.ForeignKey(ComponentChanger, on_delete=models.CASCADE, related_name='components_to_add')
    component = models.ForeignKey(Component, on_delete=models.CASCADE)
    tag = models.CharField(max_length=50)
    qty = models.FloatField()

    def __str__(self):
        return f"{self.component.name} ({self.tag}) x {self.qty}"

class Order(models.Model):
    order_number = models.CharField(max_length=20)

    def __str__(self):
        return self.order_number

    def __repr__(self):
        return f"<Order: {self.order_number}>"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    number = models.IntegerField()
    product_model = models.ForeignKey(ProductModel, on_delete=models.CASCADE)
    width = models.FloatField(null=True, blank=True)
    height = models.FloatField(null=True, blank=True)
    wall = models.FloatField(null=True, blank=True)
    direction = models.CharField(max_length=10, null=True, blank=True)
    opening = models.CharField(max_length=10, null=True, blank=True)
    undercut = models.FloatField(null=True, blank=True)
    comment = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Order {self.order.order_number} Item {self.number}: {self.product_model.sku}"

    def __repr__(self):
        return f"<OrderItem: {self.order.order_number}-{self.number}>"


class OrderItemCustomizer(models.Model):
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='customizers')
    customizer = models.ForeignKey(Customizer, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.order_item} - {self.customizer.sku}"

    def __repr__(self):
        return f"<OrderItemCustomizer: {self.order_item.id}-{self.customizer.sku}>"
