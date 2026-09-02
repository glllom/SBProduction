from rest_framework import serializers

from .models import OrderItemsGroupCustomizer, GroupSpecification, GroupSpecificationCustomizer


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


class GroupSpecificationCustomizerSerializer(serializers.ModelSerializer):
    customizer_name = serializers.ReadOnlyField(source='customizer.name')
    customizer_code = serializers.ReadOnlyField(source='customizer.code')
    customizer_description = serializers.ReadOnlyField(source='customizer.description')
    par1_label = serializers.ReadOnlyField(source='customizer.par1_label')
    par2_label = serializers.ReadOnlyField(source='customizer.par2_label')
    par3_label = serializers.ReadOnlyField(source='customizer.par3_label')
    par4_label = serializers.ReadOnlyField(source='customizer.par4_label')

    class Meta:
        model = GroupSpecificationCustomizer
        fields = [
            'id', 'customizer', 'customizer_name', 'customizer_code', 'customizer_description',
            'par1', 'par2', 'par3', 'par4',
            'par1_label', 'par2_label', 'par3_label', 'par4_label'
        ]


class GroupSpecificationSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    product_type_name = serializers.ReadOnlyField(source='product.product_family.product_type.name')
    product_family_name = serializers.ReadOnlyField(source='product.product_family.name')
    series_name = serializers.ReadOnlyField(source='series.name')
    front_name = serializers.ReadOnlyField(source='front.name')
    basic_color_frames_name = serializers.ReadOnlyField(source='basic_color_frames.name')
    panel_paint_option_display = serializers.CharField(source='get_panel_paint_option_display', read_only=True)
    frame_paint_option_display = serializers.CharField(source='get_frame_paint_option_display', read_only=True)
    customizers = GroupSpecificationCustomizerSerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()
    created_at_formatted = serializers.SerializerMethodField()

    class Meta:
        model = GroupSpecification
        fields = [
            'id', 'name', 'description', 'product', 'product_name', 'product_type_name', 'product_family_name',
            'series', 'series_name', 'front', 'front_name',
            'basic_color_frames', 'basic_color_frames_name',
            'panel_paint_option', 'panel_paint_option_display', 'color_panels',
            'frame_paint_option', 'frame_paint_option_display', 'color_frames',
            'is_split_installation', 'quantity', 'comments',
            'created_at', 'created_at_formatted', 'created_by', 'created_by_name',
            'customizers'
        ]

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return ""

    def get_created_at_formatted(self, obj):
        return obj.created_at.strftime('%d/%m/%Y %H:%M') if obj.created_at else ""
