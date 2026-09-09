from rest_framework import serializers

from .models import OrderItemsGroupCustomizer, GroupSpecification, GroupSpecificationCustomizer


class OrderItemsGroupCustomizerSerializer(serializers.ModelSerializer):
    customizer_name = serializers.ReadOnlyField(source='customizer.name')
    customizer_code = serializers.ReadOnlyField(source='customizer.code')
    customizer_description = serializers.ReadOnlyField(source='customizer.description')

    # We also need labels and hints to show in the UI
    par1_label = serializers.ReadOnlyField(source='customizer.par1_label')
    par1_hint = serializers.ReadOnlyField(source='customizer.par1_hint')
    par1_default_value = serializers.ReadOnlyField(source='customizer.par1_value')
    par1_options = serializers.SerializerMethodField()

    par2_label = serializers.ReadOnlyField(source='customizer.par2_label')
    par2_hint = serializers.ReadOnlyField(source='customizer.par2_hint')
    par2_default_value = serializers.ReadOnlyField(source='customizer.par2_value')
    par2_options = serializers.SerializerMethodField()

    par3_label = serializers.ReadOnlyField(source='customizer.par3_label')
    par3_hint = serializers.ReadOnlyField(source='customizer.par3_hint')
    par3_default_value = serializers.ReadOnlyField(source='customizer.par3_value')
    par3_options = serializers.SerializerMethodField()

    par4_label = serializers.ReadOnlyField(source='customizer.par4_label')
    par4_hint = serializers.ReadOnlyField(source='customizer.par4_hint')
    par4_default_value = serializers.ReadOnlyField(source='customizer.par4_value')
    par4_options = serializers.SerializerMethodField()

    par5_label = serializers.ReadOnlyField(source='customizer.par5_label')
    par5_hint = serializers.ReadOnlyField(source='customizer.par5_hint')
    par5_default_value = serializers.ReadOnlyField(source='customizer.par5_value')
    par5_options = serializers.SerializerMethodField()

    class Meta:
        model = OrderItemsGroupCustomizer
        fields = [
            'id', 'group', 'customizer', 'customizer_name', 'customizer_code', 'customizer_description',
            'par1', 'par2', 'par3', 'par4', 'par5',
            'par1_label', 'par1_hint', 'par1_default_value', 'par1_options',
            'par2_label', 'par2_hint', 'par2_default_value', 'par2_options',
            'par3_label', 'par3_hint', 'par3_default_value', 'par3_options',
            'par4_label', 'par4_hint', 'par4_default_value', 'par4_options',
            'par5_label', 'par5_hint', 'par5_default_value', 'par5_options',
        ]

    def get_par1_options(self, obj):
        options = obj.customizer.get_filtered_parameter_options(1, obj.group.product)
        return [{"key": k, "label": l} for k, l in options]

    def get_par2_options(self, obj):
        options = obj.customizer.get_filtered_parameter_options(2, obj.group.product)
        return [{"key": k, "label": l} for k, l in options]

    def get_par3_options(self, obj):
        options = obj.customizer.get_filtered_parameter_options(3, obj.group.product)
        return [{"key": k, "label": l} for k, l in options]

    def get_par4_options(self, obj):
        options = obj.customizer.get_filtered_parameter_options(4, obj.group.product)
        return [{"key": k, "label": l} for k, l in options]

    def get_par5_options(self, obj):
        options = obj.customizer.get_filtered_parameter_options(5, obj.group.product)
        return [{"key": k, "label": l} for k, l in options]


class GroupSpecificationCustomizerSerializer(serializers.ModelSerializer):
    customizer_name = serializers.ReadOnlyField(source='customizer.name')
    customizer_code = serializers.ReadOnlyField(source='customizer.code')
    customizer_description = serializers.ReadOnlyField(source='customizer.description')
    
    par1_label = serializers.ReadOnlyField(source='customizer.par1_label')
    par1_default_value = serializers.ReadOnlyField(source='customizer.par1_value')
    par1_options = serializers.SerializerMethodField()
    
    par2_label = serializers.ReadOnlyField(source='customizer.par2_label')
    par2_default_value = serializers.ReadOnlyField(source='customizer.par2_value')
    par2_options = serializers.SerializerMethodField()
    
    par3_label = serializers.ReadOnlyField(source='customizer.par3_label')
    par3_default_value = serializers.ReadOnlyField(source='customizer.par3_value')
    par3_options = serializers.SerializerMethodField()
    
    par4_label = serializers.ReadOnlyField(source='customizer.par4_label')
    par4_default_value = serializers.ReadOnlyField(source='customizer.par4_value')
    par4_options = serializers.SerializerMethodField()
    
    par5_label = serializers.ReadOnlyField(source='customizer.par5_label')
    par5_default_value = serializers.ReadOnlyField(source='customizer.par5_value')
    par5_options = serializers.SerializerMethodField()

    class Meta:
        model = GroupSpecificationCustomizer
        fields = [
            'id', 'customizer', 'customizer_name', 'customizer_code', 'customizer_description',
            'par1', 'par2', 'par3', 'par4', 'par5',
            'par1_label', 'par1_default_value', 'par1_options',
            'par2_label', 'par2_default_value', 'par2_options',
            'par3_label', 'par3_default_value', 'par3_options',
            'par4_label', 'par4_default_value', 'par4_options',
            'par5_label', 'par5_default_value', 'par5_options',
        ]

    def get_par1_options(self, obj):
        options = obj.customizer.get_filtered_parameter_options(1, obj.specification.product)
        return [{"key": k, "label": l} for k, l in options]

    def get_par2_options(self, obj):
        options = obj.customizer.get_filtered_parameter_options(2, obj.specification.product)
        return [{"key": k, "label": l} for k, l in options]

    def get_par3_options(self, obj):
        options = obj.customizer.get_filtered_parameter_options(3, obj.specification.product)
        return [{"key": k, "label": l} for k, l in options]

    def get_par4_options(self, obj):
        options = obj.customizer.get_filtered_parameter_options(4, obj.specification.product)
        return [{"key": k, "label": l} for k, l in options]

    def get_par5_options(self, obj):
        options = obj.customizer.get_filtered_parameter_options(5, obj.specification.product)
        return [{"key": k, "label": l} for k, l in options]


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
