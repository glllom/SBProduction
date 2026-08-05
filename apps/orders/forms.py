from django import forms
from .models import Order
from apps.catalog.models import Series, Front

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
