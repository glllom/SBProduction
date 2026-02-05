from django.db import models

"""Product models"""
"""main group of products"""


class DBProductType(models.Model):
    name = models.CharField(max_length=20, unique=True)
    sku = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<ProductType: {self.sku}>"


class DBProductFamily(models.Model):
    name = models.CharField(max_length=40)
    sku = models.CharField(max_length=20, unique=True)
    product_type = models.ForeignKey(DBProductType, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<ProductFamily: {self.sku}>"


class DBSeries(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<Series: {self.sku}>"




class DBFront(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)
    series = models.ForeignKey(DBSeries, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<Front: {self.sku}>"


class DBBomTag(models.Model):
    tag = models.CharField(max_length=20)

    def __str__(self):
        return self.tag

    def __repr__(self):
        return f"<BomTag: {self.tag}>"

class DBCustomizerTag(models.Model):
    tag = models.CharField(max_length=20)

    def __str__(self):
        return self.tag

    def __repr__(self):
        return f"<CustomizerTag: {self.tag}>"

"""Material"""


class DBComponent(models.Model):
    name = models.CharField(max_length=256)
    width = models.FloatField()
    length = models.FloatField()
    thickness = models.FloatField()
    sku = models.CharField(max_length=20, unique=True)
    group = models.CharField(max_length=20)
    component_type = models.CharField(max_length=20)
    color = models.CharField(max_length=20, blank=True, null=True)
    global_type = models.CharField(max_length=1)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<DBComponent: {self.sku}>"


class DBProductModel(models.Model):
    product_family = models.ForeignKey(DBProductFamily, on_delete=models.CASCADE)
    # series = models.ForeignKey(DBSeries, on_delete=models.CASCADE)
    panel_reduction_width = models.FloatField(default=0)
    panel_reduction_height = models.FloatField(default=0)
    double_door_gap = models.FloatField(default=0)
    description = models.CharField(max_length=256)
    bom = models.ManyToManyField(DBComponent, through='production.DBBomComponent', related_name='bom')
    sku = models.CharField(max_length=20, unique=True)
    global_type = models.CharField(max_length=1)
    product_type = models.ForeignKey(DBProductType, on_delete=models.CASCADE)



    def __str__(self):
        return f"{self.description} ({self.sku})"

    def __repr__(self):
        return f"<ProductModel: {self.sku}>"


class DBBomComponent(models.Model):
    product_model = models.ForeignKey(DBProductModel, on_delete=models.CASCADE, related_name='bom_details')
    DBComponent = models.ForeignKey(DBComponent, on_delete=models.CASCADE, related_name='used_in_boms')
    tag = models.ForeignKey(DBBomTag, on_delete=models.CASCADE)
    qty = models.FloatField(null=True, blank=True)

    @classmethod
    def get_components_for_product(cls, product_model):
        return cls.objects.filter(product_model=product_model)

    def __str__(self):
        return f"{self.product_model.sku} -> {self.DBComponent.sku} ({self.qty})"

    def __repr__(self):
        return f"<BomComponents: {self.product_model.sku} - {self.DBComponent.sku}>"


class DBCustomizer(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)
    tag = models.ForeignKey(DBCustomizerTag, on_delete=models.CASCADE)
    par1 = models.FloatField(blank=True)
    par2 = models.FloatField(blank=True)
    par3 = models.FloatField(blank=True)
    par1_description = models.CharField(max_length=200, blank=True)
    components_to_remove = models.ManyToManyField(DBComponent, related_name='removed_by_customizers', blank=True)

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def __repr__(self):
        return f"<Customizer: {self.sku}>"


class DBCustomizerComponentAdd(models.Model):
    customizer = models.ForeignKey(DBCustomizer, on_delete=models.CASCADE, related_name='added_components')
    component = models.ForeignKey(DBComponent, on_delete=models.CASCADE)
    tag = models.ForeignKey(DBBomTag, on_delete=models.CASCADE)
    qty = models.FloatField()

    def __str__(self):
        return f"{self.component.sku} ({self.tag.tag}) x {self.qty}"


class DBProductStages(models.Model):
    stage = models.CharField(max_length=20)

    def __str__(self):
        return self.stage

    def __repr__(self):
        return f"<ProductStage: {self.stage}>"



class DBOrder(models.Model):
    order_number = models.CharField(max_length=20)
    customer = models.CharField(max_length=100, default="Unknown")

    def __str__(self):
        return self.order_number

    def __repr__(self):
        return f"<Order: {self.order_number}>"


class DBOrderItem(models.Model):
    order = models.ForeignKey(DBOrder, on_delete=models.CASCADE, related_name='items')
    number = models.IntegerField()
    product_model = models.ForeignKey(DBProductModel, on_delete=models.CASCADE)
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


class DBOrderItemCustomizer(models.Model):
    order_item = models.ForeignKey(DBOrderItem, on_delete=models.CASCADE, related_name='customizers')
    customizer = models.ForeignKey(DBCustomizer, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.order_item} - {self.customizer.sku}"

    def __repr__(self):
        return f"<OrderItemCustomizer: {self.order_item.id}-{self.customizer.sku}>"
