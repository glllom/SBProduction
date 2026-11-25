from rest_framework import serializers

from .models import (
    GroupSpecification,
    GroupSpecificationCustomizer,
    OrderItemsGroupCustomizer,
)


class _BaseGroupCustomizerSerializer(serializers.ModelSerializer):
    customizer_name = serializers.ReadOnlyField(source='customizer.name')
    customizer_code = serializers.ReadOnlyField(source='customizer.code')
    customizer_description = serializers.ReadOnlyField(source='customizer.description')
    customizer_is_required = serializers.SerializerMethodField()

    par1_label = serializers.ReadOnlyField(source='customizer.par1_label')
    par1_required = serializers.ReadOnlyField(source='customizer.par1_required')
    par1_default_value = serializers.ReadOnlyField(source='customizer.par1_value')
    par1_options = serializers.SerializerMethodField()

    par2_label = serializers.ReadOnlyField(source='customizer.par2_label')
    par2_required = serializers.ReadOnlyField(source='customizer.par2_required')
    par2_default_value = serializers.ReadOnlyField(source='customizer.par2_value')
    par2_options = serializers.SerializerMethodField()

    par3_label = serializers.ReadOnlyField(source='customizer.par3_label')
    par3_required = serializers.ReadOnlyField(source='customizer.par3_required')
    par3_default_value = serializers.ReadOnlyField(source='customizer.par3_value')
    par3_options = serializers.SerializerMethodField()

    par4_label = serializers.ReadOnlyField(source='customizer.par4_label')
    par4_required = serializers.ReadOnlyField(source='customizer.par4_required')
    par4_default_value = serializers.ReadOnlyField(source='customizer.par4_value')
    par4_options = serializers.SerializerMethodField()

    par5_label = serializers.ReadOnlyField(source='customizer.par5_label')
    par5_required = serializers.ReadOnlyField(source='customizer.par5_required')
    par5_default_value = serializers.ReadOnlyField(source='customizer.par5_value')
    par5_options = serializers.SerializerMethodField()

    def _get_product(self, obj):
        raise NotImplementedError

    def _get_options(self, obj, par_number: int):
        options = obj.customizer.get_filtered_parameter_options(par_number, self._get_product(obj))
        return [{"key": k, "label": label} for k, label in options]

    def get_customizer_is_required(self, obj):
        product = self._get_product(obj)
        if not product or not obj.customizer_id:
            return False

        cache = getattr(self, '_required_ids_cache', None)
        if cache is None:
            cache = {}
            self._required_ids_cache = cache

        if product.id not in cache:
            cache[product.id] = set(
                product.get_required_customizers().values_list('id', flat=True)
            )
        return obj.customizer_id in cache[product.id]

    def get_par1_options(self, obj):
        return self._get_options(obj, 1)

    def get_par2_options(self, obj):
        return self._get_options(obj, 2)

    def get_par3_options(self, obj):
        return self._get_options(obj, 3)

    def get_par4_options(self, obj):
        return self._get_options(obj, 4)

    def get_par5_options(self, obj):
        return self._get_options(obj, 5)


class OrderItemsGroupCustomizerSerializer(_BaseGroupCustomizerSerializer):
    par1_hint = serializers.ReadOnlyField(source='customizer.par1_hint')
    par2_hint = serializers.ReadOnlyField(source='customizer.par2_hint')
    par3_hint = serializers.ReadOnlyField(source='customizer.par3_hint')
    par4_hint = serializers.ReadOnlyField(source='customizer.par4_hint')
    par5_hint = serializers.ReadOnlyField(source='customizer.par5_hint')

    class Meta:
        model = OrderItemsGroupCustomizer
        fields = [
            'id', 'group', 'customizer', 'customizer_name', 'customizer_code', 'customizer_description',
            'customizer_is_required',
            'par1', 'par2', 'par3', 'par4', 'par5',
            'par1_label', 'par1_required', 'par1_hint', 'par1_default_value', 'par1_options',
            'par2_label', 'par2_required', 'par2_hint', 'par2_default_value', 'par2_options',
            'par3_label', 'par3_required', 'par3_hint', 'par3_default_value', 'par3_options',
            'par4_label', 'par4_required', 'par4_hint', 'par4_default_value', 'par4_options',
            'par5_label', 'par5_required', 'par5_hint', 'par5_default_value', 'par5_options',
        ]

    def _get_product(self, obj):
        return getattr(getattr(obj, 'group', None), 'product', None)


class GroupSpecificationCustomizerSerializer(_BaseGroupCustomizerSerializer):
    class Meta:
        model = GroupSpecificationCustomizer
        fields = [
            'id', 'customizer', 'customizer_name', 'customizer_code', 'customizer_description',
            'customizer_is_required',
            'par1', 'par2', 'par3', 'par4', 'par5',
            'par1_label', 'par1_required', 'par1_default_value', 'par1_options',
            'par2_label', 'par2_required', 'par2_default_value', 'par2_options',
            'par3_label', 'par3_required', 'par3_default_value', 'par3_options',
            'par4_label', 'par4_required', 'par4_default_value', 'par4_options',
            'par5_label', 'par5_required', 'par5_default_value', 'par5_options',
        ]

    def _get_product(self, obj):
        return getattr(getattr(obj, 'specification', None), 'product', None)


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
            'panel_paint_option', 'panel_paint_option_display', 'is_door_inside_different_color', 'color_panel_outside',
            'color_panel_inside',
            'frame_paint_option', 'frame_paint_option_display', 'color_frames',
            'is_split_installation', 'quantity', 'comments',
            'created_at', 'created_at_formatted', 'created_by', 'created_by_name',
            'customizers',
        ]

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return ""

    def get_created_at_formatted(self, obj):
        return obj.created_at.strftime('%d/%m/%Y %H:%M') if obj.created_at else ""
