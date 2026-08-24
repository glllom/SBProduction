from rest_framework import serializers

from .models import Series, Front, Color, ProductFamily, ProductModel, Customizer, Material


class SeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Series
        fields = ['id', 'code', 'name', 'description']


class FrontSerializer(serializers.ModelSerializer):
    class Meta:
        model = Front
        fields = ['id', 'series', 'name', 'code', 'description']


class FrameColorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Color
        fields = ['id', 'name', 'code', 'description']


class MaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Material
        fields = ['id', 'name', 'sku', 'common_name']


class ProductFamilySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductFamily
        fields = ['id', 'name', 'code', 'description']


class ProductModelSerializer(serializers.ModelSerializer):
    available_frames = serializers.SerializerMethodField()

    class Meta:
        model = ProductModel
        fields = ['id', 'code', 'name', 'product_family', 'series', 'description', 'available_frames']

    def get_available_frames(self, obj):
        return MaterialSerializer(obj.available_frames, many=True).data


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
