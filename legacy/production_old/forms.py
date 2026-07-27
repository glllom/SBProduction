from django import forms
from .models import DBOrder, DBOrderItem, DBOrderItemCustomizer, DBCustomizer, DBProductModel

class OrderForm(forms.ModelForm):
    class Meta:
        model = DBOrder
        fields = ['order_number', 'customer']
        widgets = {
            'order_number': forms.TextInput(attrs={'class': 'form-control'}),
            'customer': forms.TextInput(attrs={'class': 'form-control'}),
        }

class OrderItemForm(forms.ModelForm):
    class Meta:
        model = DBOrderItem
        fields = ['number', 'product_model', 'width', 'height', 'wall', 'direction', 'opening', 'undercut', 'comment']
        widgets = {
            'number': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '№'}),
            'product_model': forms.Select(attrs={'class': 'form-select'}),
            'width': forms.NumberInput(attrs={'class': 'form-control'}),
            'height': forms.NumberInput(attrs={'class': 'form-control'}),
            'wall': forms.NumberInput(attrs={'class': 'form-control'}),
            'direction': forms.TextInput(attrs={'class': 'form-control'}),
            'opening': forms.TextInput(attrs={'class': 'form-control'}),
            'undercut': forms.NumberInput(attrs={'class': 'form-control'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'style': 'font-size: 0.8rem;'}),
        }

class OrderItemCustomizerForm(forms.ModelForm):
    class Meta:
        model = DBOrderItemCustomizer
        fields = ['customizer']
        widgets = {
            'customizer': forms.Select(attrs={'class': 'form-select'}),
        }

OrderItemFormSet = forms.inlineformset_factory(
    DBOrder, DBOrderItem, form=OrderItemForm, extra=1, can_delete=True
)

OrderItemCustomizerFormSet = forms.inlineformset_factory(
    DBOrderItem, DBOrderItemCustomizer, form=OrderItemCustomizerForm, extra=3, can_delete=True
)
