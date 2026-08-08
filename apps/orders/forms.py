from django import forms
from .models import Order, OrderItemsGroup, OrderItemsGroupCustomizer, OrderItem
from apps.catalog.models import Series, Front, ProductModel, ProductType, ProductFamily

class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = [
            'mark', 'place', 'width', 'height', 'wall', 
            'direction', 'opening', 'addition_cut', 'comment',
            'custom_lock_height', 'custom_hinge1', 'custom_hinge2', 
            'custom_hinge3', 'custom_hinge4', 'custom_hinge5',
            'sketch'
        ]
        widgets = {
            'mark': forms.TextInput(attrs={'class': 'form-control'}),
            'width': forms.TextInput(attrs={'class': 'form-control'}),
            'height': forms.TextInput(attrs={'class': 'form-control'}),
            'wall': forms.TextInput(attrs={'class': 'form-control'}),
            'direction': forms.Select(attrs={'class': 'form-select'}),
            'opening': forms.Select(attrs={'class': 'form-select'}),
            'addition_cut': forms.TextInput(attrs={'class': 'form-control'}),
            'place': forms.TextInput(attrs={'class': 'form-control'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'custom_lock_height': forms.TextInput(attrs={'class': 'form-control'}),
            'custom_hinge1': forms.TextInput(attrs={'class': 'form-control'}),
            'custom_hinge2': forms.TextInput(attrs={'class': 'form-control'}),
            'custom_hinge3': forms.TextInput(attrs={'class': 'form-control'}),
            'custom_hinge4': forms.TextInput(attrs={'class': 'form-control'}),
            'custom_hinge5': forms.TextInput(attrs={'class': 'form-control'}),
            'sketch': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        instance = self.instance
        if not instance or not instance.group or not instance.group.product:
            return cleaned_data
            
        product_type = instance.group.product.product_family.product_type
        
        # 1. Dimensions (width, height) - needed if has_door OR has_frame
        if not (product_type.has_door or product_type.has_frame):
            # For Wall Cladding, dimensions might be optional or hidden
            pass
        else:
            if not cleaned_data.get('width'):
                self.add_error('width', 'רוחב נדרש עבור סוג מוצר זה')
            if not cleaned_data.get('height'):
                self.add_error('height', 'גובה נדרש עבור סוג מוצר זה')
        
        # 2. Wall thickness dependency
        if product_type.has_frame:
            if not cleaned_data.get('wall'):
                self.add_error('wall', 'עובי קיר נדרש עבור סוג מוצר זה')
        else:
            cleaned_data['wall'] = None
            
        # 3. Door parameters dependency
        if not product_type.has_door:
            # Clear door-only fields if they were somehow submitted
            cleaned_data['direction'] = None
            cleaned_data['opening'] = None
            cleaned_data['addition_cut'] = None
            cleaned_data['custom_lock_height'] = None
            cleaned_data['custom_hinge1'] = None
            cleaned_data['custom_hinge2'] = None
            cleaned_data['custom_hinge3'] = None
            cleaned_data['custom_hinge4'] = None
            cleaned_data['custom_hinge5'] = None
            
        return cleaned_data

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            'order_number', 
            'customer', 
            'painting_date', 
            'completion_date', 
            'series', 
            'front', 
            'color_panels', 
            'is_frames_to_paint',
            'color_frames', 
            'comments'
        ]
        widgets = {
            'painting_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'completion_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'order_number': forms.TextInput(attrs={'class': 'form-control'}),
            'customer': forms.TextInput(attrs={'class': 'form-control'}),
            'series': forms.Select(attrs={'class': 'form-select'}),
            'front': forms.Select(attrs={'class': 'form-select'}),
            'color_panels': forms.TextInput(attrs={'class': 'form-control'}),
            'is_frames_to_paint': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'color_frames': forms.TextInput(attrs={'class': 'form-control'}),
            'comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Initialize front queryset as empty if no series is selected
        if 'series' in self.data:
            try:
                series_id = int(self.data.get('series'))
                self.fields['front'].queryset = Front.objects.filter(series_id=series_id).order_by('name')
            except (ValueError, TypeError):
                self.fields['front'].queryset = Front.objects.none()
        elif self.instance.pk and self.instance.series:
            self.fields['front'].queryset = self.instance.series.fronts.order_by('name')
        else:
            self.fields['front'].queryset = Front.objects.none()


class OrderHeaderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            'customer',
            'painting_date',
            'completion_date',
            'series',
            'front',
            'color_panels',
            'is_frames_to_paint',
            'color_frames',
            'comments'
        ]
        widgets = {
            'customer': forms.TextInput(attrs={'class': 'form-control'}),
            'painting_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'completion_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'series': forms.Select(attrs={'class': 'form-select'}),
            'front': forms.Select(attrs={'class': 'form-select'}),
            'color_panels': forms.TextInput(attrs={'class': 'form-control'}),
            'is_frames_to_paint': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'color_frames': forms.TextInput(attrs={'class': 'form-control'}),
            'comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'series' in self.data:
            try:
                series_id = int(self.data.get('series'))
                self.fields['front'].queryset = Front.objects.filter(series_id=series_id).order_by('name')
            except (ValueError, TypeError):
                self.fields['front'].queryset = Front.objects.none()
        elif self.instance.pk and self.instance.series:
            self.fields['front'].queryset = self.instance.series.fronts.order_by('name')
        else:
            self.fields['front'].queryset = Front.objects.none()


class OrderItemsGroupForm(forms.ModelForm):
    product_type = forms.ModelChoiceField(
        queryset=ProductType.objects.filter(active=True),
        label='סוג מוצר',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    product_family = forms.ModelChoiceField(
        queryset=ProductFamily.objects.all(),
        label='משפחת מוצרים',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = OrderItemsGroup
        fields = [
            'product_type',
            'product_family',
            'quantity',
            'product',
            'series',
            'front',
            'panel_paint_option',
            'color_panels',
            'frame_paint_option',
            'color_frames',
            'is_split_installation',
            'comments'
        ]
        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'product': forms.Select(attrs={'class': 'form-select'}),
            'series': forms.Select(attrs={'class': 'form-select'}),
            'front': forms.Select(attrs={'class': 'form-select'}),
            'panel_paint_option': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'color_panels': forms.TextInput(attrs={'class': 'form-control'}),
            'frame_paint_option': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'color_frames': forms.TextInput(attrs={'class': 'form-control'}),
            'is_split_installation': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'הערות'}),
        }

    def __init__(self, *args, **kwargs):
        self.order = kwargs.pop('order', None)
        super().__init__(*args, **kwargs)
        
        # Set initial values for product_type and product_family if product is set
        if self.instance.pk and self.instance.product:
            self.initial['product_family'] = self.instance.product.product_family
            self.initial['product_type'] = self.instance.product.product_family.product_type
            
        # Set default frame_paint_option based on order.is_frames_to_paint
        if not self.instance.pk and self.order:
            if self.order.is_frames_to_paint:
                self.initial['frame_paint_option'] = OrderItemsGroup.PaintOption.MAIN_COLOR
            else:
                self.initial['frame_paint_option'] = OrderItemsGroup.PaintOption.NO_PAINT
            
            # Default series and front from order
            if self.order.series:
                self.initial['series'] = self.order.series
            if self.order.front:
                self.initial['front'] = self.order.front

        if 'series' in self.data:
            try:
                series_id = int(self.data.get('series'))
                self.fields['front'].queryset = Front.objects.filter(series_id=series_id).order_by('name')
            except (ValueError, TypeError):
                self.fields['front'].queryset = Front.objects.none()
        elif self.instance.pk and self.instance.series:
            self.fields['front'].queryset = self.instance.series.fronts.order_by('name')
        elif self.order and self.order.series:
            self.fields['front'].queryset = self.order.series.fronts.order_by('name')
        else:
            self.fields['front'].queryset = Front.objects.none()

        # Handle product_family queryset filtering if product_type is in data
        if 'product_type' in self.data:
            try:
                type_id = int(self.data.get('product_type'))
                self.fields['product_family'].queryset = ProductFamily.objects.filter(product_type_id=type_id).order_by('name')
            except (ValueError, TypeError):
                self.fields['product_family'].queryset = ProductFamily.objects.none()
        elif self.instance.pk and self.instance.product:
            self.fields['product_family'].queryset = ProductFamily.objects.filter(
                product_type=self.instance.product.product_family.product_type
            ).order_by('name')


class OrderItemsGroupCustomizerForm(forms.ModelForm):
    class Meta:
        model = OrderItemsGroupCustomizer
        fields = ['customizer', 'par1', 'par2', 'par3', 'par4']
        widgets = {
            'customizer': forms.Select(attrs={'class': 'form-select'}),
            'par1': forms.TextInput(attrs={'class': 'form-control'}),
            'par2': forms.TextInput(attrs={'class': 'form-control'}),
            'par3': forms.TextInput(attrs={'class': 'form-control'}),
            'par4': forms.TextInput(attrs={'class': 'form-control'}),
        }
