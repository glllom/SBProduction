from django import forms

from apps.catalog.models import Front, Color, ProductType, ProductFamily, Series, ProductModel, Material
from .models import Order, OrderItemsGroup, OrderItemsGroupCustomizer, OrderItem


class TooltipSelect(forms.Select):
    """
    Select widget that extracts description/help_text from Model instances
    and adds 'title' and 'data-description' attributes to each <option>.
    """

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, 'instance', None)
        if instance:
            desc = (
                    getattr(instance, 'description', None) or
                    getattr(instance, 'help_text', None) or
                    getattr(instance, 'par1_hint', None)
            )
            if desc:
                desc_str = str(desc).strip()
                if desc_str:
                    option['attrs']['data-description'] = desc_str
                    option['attrs']['title'] = desc_str
        return option


class TooltipRadioSelect(forms.RadioSelect):
    """
    RadioSelect widget that attaches descriptions to choices.
    """
    CHOICE_HELP = {
        'NO_PAINT': 'ללא צביעה במפעל (אספקה במצב גלם / סטנדרטי)',
        'MAIN_COLOR': 'צביעה לפי הגוון הראשי שנבחר בהזמנה',
        'SPECIAL_COLOR': 'הזנת קוד צבע מותאם אישית עבור פריטים אלו',
        'IN': 'פתיחת הדלת פנימה לתוך החדר',
        'OUT': 'פתיחת הדלת החוצה מהחדר',
        'LEFT': 'יד שמאל (L) - צירים בצד שמאל במבט מכיוון הפתיחה',
        'RIGHT': 'יד ימין (R) - צירים בצד ימין במבט מכיוון הפתיחה',
    }

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        val_str = str(value)
        if val_str in self.CHOICE_HELP:
            desc = self.CHOICE_HELP[val_str]
            option['attrs']['data-description'] = desc
            option['attrs']['title'] = desc
        return option


class TooltipFormMixin:
    """
    Mixin that configures tooltip data attributes on fields with help_text or descriptions.
    """

    def apply_tooltips(self):
        for field_name, field in self.fields.items():
            if field.help_text:
                ht = str(field.help_text).strip()
                if ht:
                    field.widget.attrs.setdefault('title', ht)
                    # For standard text inputs/textareas, data-bs-toggle tooltip works cleanly on hover
                    if not isinstance(field.widget, (forms.Select, forms.RadioSelect, forms.CheckboxInput)):
                        field.widget.attrs.setdefault('data-bs-toggle', 'tooltip')
                        field.widget.attrs.setdefault('data-bs-title', ht)
                        field.widget.attrs.setdefault('data-bs-placement', 'top')


class OrderItemForm(TooltipFormMixin, forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = [
            'mark', 'place', 'width', 'height', 'wall',
            'direction', 'opening', 'addition_cut', 'comment',
            'custom_lock_height', 'custom_hinge1', 'custom_hinge2',
            'custom_hinge3', 'custom_hinge4', 'custom_hinge5',
            'sketch'
        ]
        help_texts = {
            'mark': 'סימון פריט ייחודי בהזמנה (למשל 1, 2, 3)',
            'place': 'מיקום התקנה (חדר, קומה, דירה)',
            'width': 'רוחב פתח אור / כנף במילימטרים',
            'height': 'גובה פתח אור / כנף במילימטרים',
            'wall': 'עובי קיר עבור המשקוף במילימטרים',
            'direction': 'כיוון פתיחת הדלת (פנימה / החוצה)',
            'opening': 'יד פתיחה (L = שמאל, R = ימין)',
            'addition_cut': 'חיתוך תחתון נוסף במילימטרים (עבור ריצוף או שטיח)',
            'comment': 'הערה ספציפית לפריט זה',
            'custom_lock_height': 'גובה מרכז מנעול חריג מהרצפה במילימטרים',
            'custom_hinge1': 'גובה ציר 1 חריג מהרצפה במילימטרים',
            'custom_hinge2': 'גובה ציר 2 חריג מהרצפה במילימטרים',
            'custom_hinge3': 'גובה ציר 3 חריג מהרצפה במילימטרים',
            'custom_hinge4': 'גובה ציר 4 חריג מהרצפה במילימטרים',
            'custom_hinge5': 'גובה ציר 5 חריג מהרצפה במילימטרים',
            'sketch': 'קובץ שרטוט לפרט זה (PDF, JPEG, PNG)',
        }
        widgets = {
            'mark': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'סימון'}),
            'width': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'רוחב'}),
            'height': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'גובה'}),
            'wall': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'עובי קיר'}),
            'direction': TooltipSelect(attrs={'class': 'form-select'}),
            'opening': TooltipSelect(attrs={'class': 'form-select'}),
            'addition_cut': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'רווח נוסף'}),
            'place': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'מיקום'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'הערה'}),
            'custom_lock_height': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'גובה מנעול'}),
            'custom_hinge1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ציר 1'}),
            'custom_hinge2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ציר 2'}),
            'custom_hinge3': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ציר 3'}),
            'custom_hinge4': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ציר 4'}),
            'custom_hinge5': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ציר 5'}),
            'sketch': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_tooltips()

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


class OrderForm(TooltipFormMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            'order_number',
            'customer',
            'series',
            'front',
            'handle',
            'color_panels',
            'is_frames_to_paint',
            'color_frames',
            'comments'
        ]
        help_texts = {
            'order_number': 'מספר הזמנה ייחודי במערכת (למשל ORD-2026-001)',
            'customer': 'שם הלקוח או הפרויקט',
            'series': 'סדרת הדלתות (פרופיל / מבנה)',
            'front': 'חזית או גימור הכנף',
            'handle': 'דגם ידית נבחר',
            'color_panels': 'גוון צבע עבור כנפי הדלתות',
            'is_frames_to_paint': 'האם לצבוע את המשקופים בצבע ייעודי',
            'color_frames': 'גוון צבע עבור המשקופים',
            'comments': 'הערות והנחיות מיוחדות להזמנה',
        }
        widgets = {
            'order_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'מספר הזמנה'}),
            'customer': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'שם הלקוח'}),
            'series': TooltipSelect(attrs={'class': 'form-select'}),
            'front': TooltipSelect(attrs={'class': 'form-select'}),
            'handle': TooltipSelect(attrs={'class': 'form-select'}),
            'color_panels': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'צבע פנלים (כנף)'}),
            'is_frames_to_paint': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'color_frames': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'צבע משקופים'}),
            'comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'הערות להזמנה'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize front queryset based on series
        series_id = None
        if 'series' in self.data:
            try:
                series_id = int(self.data.get('series'))
            except (ValueError, TypeError):
                series_id = None
        elif self.instance.pk and self.instance.series:
            series_id = self.instance.series_id

        if series_id:
            self.fields['front'].queryset = Front.objects.filter(series_id=series_id, active=True).order_by('name')
        else:
            self.fields['front'].queryset = Front.objects.none()

        self.apply_tooltips()


class OrderHeaderForm(TooltipFormMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            'customer',
            'series',
            'front',
            'handle',
            'color_panels',
            'is_frames_to_paint',
            'color_frames',
            'comments'
        ]
        help_texts = {
            'customer': 'שם הלקוח או הפרויקט',
            'series': 'סדרת הדלתות (פרופיל / מבנה)',
            'front': 'חזית או גימור הכנף',
            'handle': 'דגם ידית נבחר',
            'color_panels': 'גוון צבע עבור כנפי הדלתות',
            'is_frames_to_paint': 'האם לצבוע את המשקופים בצבע ייעודי',
            'color_frames': 'גוון צבע עבור המשקופים',
            'comments': 'הערות והנחיות מיוחדות להזמנה',
        }
        widgets = {
            'customer': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'שם הלקוח'}),
            'series': TooltipSelect(attrs={'class': 'form-select'}),
            'front': TooltipSelect(attrs={'class': 'form-select'}),
            'handle': TooltipSelect(attrs={'class': 'form-select'}),
            'color_panels': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'צבע פנלים (כנף)'}),
            'is_frames_to_paint': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'color_frames': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'צבע משקופים'}),
            'comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'הערות להזמנה'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        series_id = None
        if 'series' in self.data:
            try:
                series_id = int(self.data.get('series'))
            except (ValueError, TypeError):
                series_id = None
        elif self.instance.pk and self.instance.series:
            series_id = self.instance.series_id

        if series_id:
            self.fields['front'].queryset = Front.objects.filter(series_id=series_id, active=True).order_by('name')
        else:
            self.fields['front'].queryset = Front.objects.none()

        self.apply_tooltips()


class OrderItemsGroupForm(TooltipFormMixin, forms.ModelForm):
    product_type = forms.ModelChoiceField(
        queryset=ProductType.objects.filter(active=True),
        label='סוג מוצר',
        help_text='סוג המוצר (דלתות פנים, דלתות כניסה וכו\')',
        required=False,
        widget=TooltipSelect(attrs={'class': 'form-select'})
    )
    product_family = forms.ModelChoiceField(
        queryset=ProductFamily.objects.all(),
        label='משפחת מוצרים',
        help_text='משפחת מוצרים לפי סוג המוצר',
        required=False,
        widget=TooltipSelect(attrs={'class': 'form-select'})
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
            'basic_color_frames',
            'panel_paint_option',
            'color_panels',
            'frame_paint_option',
            'color_frames',
            'is_split_installation',
            'comments'
        ]
        help_texts = {
            'quantity': 'כמות פריטים זהים (דלתות) בקבוצה זו',
            'product': 'דגם מוצר ספציפי מתוך המשפחה והסדרה',
            'series': 'סדרה ספציפית לקבוצה זו (אם ריק - יימשך מההזמנה)',
            'front': 'חזית ספציפית לקבוצה זו (אם ריק - יימשך מההזמנה)',
            'basic_color_frames': 'צבע משקוף בסיסי לקבוצה זו',
            'panel_paint_option': 'בחירת אופן צביעת כנפי הדלתות',
            'color_panels': 'גוון צבע עבור כנפי הדלתות בקבוצה זו',
            'frame_paint_option': 'בחירת אופן צביעת המשקופים',
            'color_frames': 'גוון צבע עבור המשקופים בקבוצה זו',
            'is_split_installation': 'התקנה מפוצלת: ייצור ואספקת משקופים בשלב א, ודלתות בשלב ב',
            'comments': 'הערות והנחיות מיוחדות לקבוצה זו',
        }
        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'placeholder': 'כמות'}),
            'product': TooltipSelect(attrs={'class': 'form-select'}),
            'series': TooltipSelect(attrs={'class': 'form-select'}),
            'front': TooltipSelect(attrs={'class': 'form-select'}),
            'basic_color_frames': TooltipSelect(attrs={'class': 'form-select'}),
            'panel_paint_option': TooltipRadioSelect(attrs={'class': 'form-check-input'}),
            'color_panels': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'צבע פנלים'}),
            'frame_paint_option': TooltipRadioSelect(attrs={'class': 'form-check-input'}),
            'color_frames': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'צבע משקופים'}),
            'is_split_installation': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'הערות לקבוצה'}),
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

            # Default series from order
            if self.order.series:
                self.initial['series'] = self.order.series

        series_id = None
        if 'series' in self.data:
            try:
                series_id = int(self.data.get('series'))
            except (ValueError, TypeError):
                series_id = None
        elif self.instance.pk and self.instance.series:
            series_id = self.instance.series_id
        elif self.order and self.order.series_id:
            series_id = self.order.series_id

        if series_id:
            self.fields['front'].queryset = Front.objects.filter(series_id=series_id, active=True).order_by('name')
        else:
            self.fields['front'].queryset = Front.objects.none()

        # Resolve product for frame color queryset
        product = None
        if 'product' in self.data:
            try:
                product_id = int(self.data.get('product'))
                product = ProductModel.objects.filter(id=product_id).first()
            except (ValueError, TypeError):
                product = None

        if not product and series_id:
            family_id = None
            if 'product_family' in self.data:
                try:
                    family_id = int(self.data.get('product_family'))
                except (ValueError, TypeError):
                    family_id = None
            elif self.instance.pk and self.instance.product_id:
                family_id = self.instance.product.product_family_id

            if family_id:
                product = ProductModel.objects.filter(series_id=series_id, product_family_id=family_id).first()

        if not product and self.instance.pk and self.instance.product:
            product = self.instance.product

        # Populate basic_color_frames queryset
        if product:
            available_frames = product.available_frames
            self.fields['basic_color_frames'].queryset = available_frames if available_frames.exists() else Material.objects.all().order_by('name')
        elif series_id:
            series = Series.objects.filter(id=series_id).first()
            if series:
                available_frames = series.available_frames
                self.fields['basic_color_frames'].queryset = available_frames if available_frames.exists() else Material.objects.all().order_by('name')
            else:
                self.fields['basic_color_frames'].queryset = Material.objects.all().order_by('name')
        else:
            self.fields['basic_color_frames'].queryset = Material.objects.none()

        if self.instance.pk and self.instance.basic_color_frames_id:
            self.fields['basic_color_frames'].queryset = (
                    self.fields['basic_color_frames'].queryset | Material.objects.filter(
                id=self.instance.basic_color_frames_id)).distinct()

        # Handle product_family queryset filtering if product_type is in data
        if 'product_type' in self.data:
            try:
                type_id = int(self.data.get('product_type'))
                self.fields['product_family'].queryset = ProductFamily.objects.filter(product_type_id=type_id).order_by(
                    'name')
            except (ValueError, TypeError):
                self.fields['product_family'].queryset = ProductFamily.objects.none()
        elif self.instance.pk and self.instance.product:
            self.fields['product_family'].queryset = ProductFamily.objects.filter(
                product_type=self.instance.product.product_family.product_type
            ).order_by('name')

        # Inheritance logic for front from order (if possible)
        if not self.instance.pk and self.order:
            if self.order.front and self.order.front in self.fields['front'].queryset:
                self.initial['front'] = self.order.front

        self.apply_tooltips()


class OrderItemsGroupCustomizerForm(TooltipFormMixin, forms.ModelForm):
    class Meta:
        model = OrderItemsGroupCustomizer
        fields = ['customizer', 'par1', 'par2', 'par3', 'par4']
        help_texts = {
            'customizer': 'בחירת קסטומייזר מהקטלוג',
            'par1': 'ערך פרמטר 1',
            'par2': 'ערך פרמטר 2',
            'par3': 'ערך פרמטר 3',
            'par4': 'ערך פרמטר 4',
        }
        widgets = {
            'customizer': TooltipSelect(attrs={'class': 'form-select'}),
            'par1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'פרמטר 1'}),
            'par2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'פרמטר 2'}),
            'par3': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'פרמטר 3'}),
            'par4': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'פרמטר 4'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_tooltips()
