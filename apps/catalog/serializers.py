from rest_framework import serializers
from .models import Series, Front, ProductFamily, ProductModel

class SeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Series
        fields = ['id', 'code', 'name']

class FrontSerializer(serializers.ModelSerializer):
    class Meta:
        model = Front
        fields = ['id', 'series', 'name', 'code']

class ProductFamilySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductFamily
        fields = ['id', 'name']

class ProductModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductModel
        fields = ['id', 'code', 'name', 'product_family', 'series']
