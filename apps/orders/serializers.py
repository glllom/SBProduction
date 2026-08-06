from rest_framework import serializers
from .models import OrderItemsGroupCustomizer

class OrderItemsGroupCustomizerSerializer(serializers.ModelSerializer):
    customizer_name = serializers.ReadOnlyField(source='customizer.name')
    customizer_code = serializers.ReadOnlyField(source='customizer.code')
    
    # We also need labels to show in the UI
    par1_label = serializers.ReadOnlyField(source='customizer.par1_label')
    par2_label = serializers.ReadOnlyField(source='customizer.par2_label')
    par3_label = serializers.ReadOnlyField(source='customizer.par3_label')
    par4_label = serializers.ReadOnlyField(source='customizer.par4_label')

    class Meta:
        model = OrderItemsGroupCustomizer
        fields = [
            'id', 'group', 'customizer', 'customizer_name', 'customizer_code',
            'par1', 'par2', 'par3', 'par4',
            'par1_label', 'par2_label', 'par3_label', 'par4_label'
        ]
