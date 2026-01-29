from django.db import models

"""Product models"""
"""main group of products"""


class ProductType(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.name


class ProductFamily(models.Model):
    name = models.CharField(max_length=40)
    sku = models.CharField(max_length=20, unique=True)
    product_type = models.ForeignKey(ProductType, on_delete=models.CASCADE)

    def __str__(self):
        return self.name



class Series(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.name


class ProductModel(models.Model):
    product_family = models.ForeignKey(ProductFamily, on_delete=models.CASCADE)
    name = models.CharField(max_length=256)
    sku = models.CharField(max_length=20, unique=True)
    series = models.ForeignKey(Series, on_delete=models.CASCADE)
    panel_reduction_width = models.FloatField()
    panel_reduction_height = models.FloatField()
    double_door_gap = models.FloatField()


class BomTags(models.Model):
    tag = models.CharField(max_length=20)

"""Material"""
class Component(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)


class SheetMaterial(Component):
    width = models.FloatField()
    length = models.FloatField()
    thickness = models.FloatField()
    group = models.CharField(max_length=20)


class LineMaterial(Component):
    pass


class ProductModelBOM(models.Model):
    product_model = models.ForeignKey(ProductModel, on_delete=models.CASCADE)
    component = models.ForeignKey(Component, on_delete=models.CASCADE)
    tag = models.ForeignKey(BomTags, on_delete=models.CASCADE)
    qty = models.FloatField()

class Customizer(models.Model):
    name = models.CharField(max_length=20)
    sku = models.CharField(max_length=20, unique=True)
    product_model = models.ForeignKey(ProductModel, on_delete=models.CASCADE)