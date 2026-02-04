from django import forms
from .models import DBOrder, DBOrderItem, DBOrderItemCustomizer, DBCustomizer, DBProductModel

class OrderForm(forms.ModelForm):
    class Meta:
        model = DBOrder
        fields = ['order_number']
        widgets = {
            'order_number': forms.TextInput(attrs={'class': 'form-control'}),
        }

class OrderItemForm(forms.ModelForm):
    customizers = forms.ModelMultipleChoiceField(
        queryset=DBCustomizer.objects.all(),
        widget=forms.SelectMultiple(attrs={'class': 'form-control'}),
        required=False
    )

    class Meta:
        model = DBOrderItem
        fields = ['number', 'product_model', 'width', 'height', 'wall', 'direction', 'opening', 'undercut', 'comment', 'customizers']
        widgets = {
            'number': forms.NumberInput(attrs={'class': 'form-control'}),
            'product_model': forms.Select(attrs={'class': 'form-control'}),
            'width': forms.NumberInput(attrs={'class': 'form-control'}),
            'height': forms.NumberInput(attrs={'class': 'form-control'}),
            'wall': forms.NumberInput(attrs={'class': 'form-control'}),
            'direction': forms.TextInput(attrs={'class': 'form-control'}),
            'opening': forms.TextInput(attrs={'class': 'form-control'}),
            'undercut': forms.NumberInput(attrs={'class': 'form-control'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['customizers'].initial = self.instance.customizers.values_list('customizer', flat=True)

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            self.save_customizers()
        return instance

    def save_customizers(self):
        if self.cleaned_data.get('customizers') is not None:
            # Удаляем старые, которых нет в новом списке
            self.instance.customizers.exclude(customizer__in=self.cleaned_data['customizers']).delete()
            # Добавляем новые
            existing_customizers = self.instance.customizers.values_list('customizer', flat=True)
            for customizer in self.cleaned_data['customizers']:
                if customizer.pk not in existing_customizers:
                    DBOrderItemCustomizer.objects.create(order_item=self.instance, customizer=customizer)

class OrderItemCustomizerForm(forms.ModelForm):
    class Meta:
        model = DBOrderItemCustomizer
        fields = ['customizer']
        widgets = {
            'customizer': forms.Select(attrs={'class': 'form-control'}),
        }

OrderItemFormSet = forms.inlineformset_factory(
    DBOrder, DBOrderItem, form=OrderItemForm, extra=1, can_delete=True
)

OrderItemCustomizerFormSet = forms.inlineformset_factory(
    DBOrderItem, DBOrderItemCustomizer, form=OrderItemCustomizerForm, extra=3, can_delete=True
)
