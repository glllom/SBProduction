from rest_framework import serializers
from .models import OrderItemsGroupCustomizer

class OrderItemsGroupCustomizerSerializer(serializers.ModelSerializer):
    customizer_name = serializers.ReadOnlyField(source='customizer.name')
    customizer_code = serializers.ReadOnlyField(source='customizer.code')
    customizer_description = serializers.ReadOnlyField(source='customizer.description')
    
    # We also need labels and hints to show in the UI
    par1_label = serializers.ReadOnlyField(source='customizer.par1_label')
    par1_hint = serializers.ReadOnlyField(source='customizer.par1_hint')
    par2_label = serializers.ReadOnlyField(source='customizer.par2_label')
    par2_hint = serializers.ReadOnlyField(source='customizer.par2_hint')
    par3_label = serializers.ReadOnlyField(source='customizer.par3_label')
    par3_hint = serializers.ReadOnlyField(source='customizer.par3_hint')
    par4_label = serializers.ReadOnlyField(source='customizer.par4_label')
    par4_hint = serializers.ReadOnlyField(source='customizer.par4_hint')

    class Meta:
        model = OrderItemsGroupCustomizer
        fields = [
            'id', 'group', 'customizer', 'customizer_name', 'customizer_code', 'customizer_description',
            'par1', 'par2', 'par3', 'par4',
            'par1_label', 'par1_hint',
            'par2_label', 'par2_hint',
            'par3_label', 'par3_hint',
            'par4_label', 'par4_hint'
        ]
