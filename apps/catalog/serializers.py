from rest_framework import serializers
from .models import Series, Front, ProductFamily, ProductModel, Customizer

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

class CustomizerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customizer
        fields = [
            'id', 'code', 'name', 'description', 
            'par1_label', 'par1_value', 'par1_hint',
            'par2_label', 'par2_value', 'par2_hint',
            'par3_label', 'par3_value', 'par3_hint',
            'par4_label', 'par4_value', 'par4_hint'
        ]
