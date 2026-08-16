from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from apps.accounts.models import User
from apps.catalog.models import ProductType, ProductFamily, Series, Front, ProductModel, Customizer, Handle
from .models import Order, OrderItemsGroup, OrderItem, OrderItemsGroupCustomizer
from .forms import OrderForm, OrderHeaderForm, OrderItemsGroupForm, OrderItemForm, TooltipSelect, TooltipRadioSelect
from .serializers import OrderItemsGroupCustomizerSerializer


class OrderTooltipTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', password='password123', role='ADMIN')
        self.client.force_login(self.user)

        self.pt = ProductType.objects.create(
            code='INT', name='Interior Doors', description='High quality interior doors',
            has_door=True, has_frame=True
        )
        self.pf = ProductFamily.objects.create(
            product_type=self.pt, code='FLAT', name='Flat Family', description='Flat flush door models'
        )
        self.series = Series.objects.create(
            code='S100', name='Series 100', description='Standard hidden aluminum frame series'
        )
        self.front = Front.objects.create(
            series=self.series, code='F01', name='White Matte', description='Matte white finish front'
        )
        self.handle = Handle.objects.create(
            code='HND-1', name='Magnetic Handle', description='Minimalist magnetic handle'
        )
        self.pm = ProductModel.objects.create(
            code='MDL-1', name='Standard Flush Door', product_family=self.pf, series=self.series,
            description='Standard door model 1'
        )
        self.cust = Customizer.objects.create(
            code='CUST-H1', name='Concealed Hinges', tag='hinge', priority=100,
            description='Premium 3D adjustable concealed hinges',
            par1_label='Hinge Count', par1_hint='Number of hinges from 2 to 5', par1_value='3'
        )
        self.order = Order.objects.create(
            order_number='ORD-2026-TEST',
            customer='Test Customer',
            series=self.series,
            front=self.front,
            handle=self.handle,
            color_panels='RAL 9003',
            color_frames='RAL 7016'
        )
        self.group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.pm,
            series=self.series,
            front=self.front,
            quantity=2
        )
        self.item1 = OrderItem.objects.create(
            group=self.group,
            mark='1',
            place='Living Room',
            width=800,
            height=2050,
            wall=120,
            direction='IN',
            opening='LEFT'
        )
        self.group_cust = OrderItemsGroupCustomizer.objects.create(
            group=self.group,
            customizer=self.cust,
            par1='3'
        )

    def test_form_widgets_have_tooltips(self):
        form = OrderForm()
        self.assertIn('data-bs-toggle', form.fields['order_number'].widget.attrs)
        self.assertEqual(form.fields['order_number'].widget.attrs['data-bs-toggle'], 'tooltip')
        self.assertIn('title', form.fields['order_number'].widget.attrs)

        group_form = OrderItemsGroupForm(order=self.order)
        self.assertIn('data-bs-toggle', group_form.fields['quantity'].widget.attrs)
        self.assertEqual(group_form.fields['quantity'].widget.attrs['data-bs-toggle'], 'tooltip')

    def test_tooltip_select_renders_data_description_on_options(self):
        form = OrderForm()
        rendered_series = str(form['series'])
        self.assertIn('data-description="Standard hidden aluminum frame series"', rendered_series)
        self.assertIn('title="Standard hidden aluminum frame series"', rendered_series)

        rendered_handle = str(form['handle'])
        self.assertIn('data-description="Minimalist magnetic handle"', rendered_handle)

    def test_tooltip_radio_select_renders_descriptions(self):
        group_form = OrderItemsGroupForm(order=self.order)
        rendered_panel_paint = str(group_form['panel_paint_option'])
        self.assertIn('data-description="ללא צביעה במפעל', rendered_panel_paint)
        self.assertIn('title="ללא צביעה במפעל', rendered_panel_paint)

    def test_group_customizer_serializer_includes_hints_and_descriptions(self):
        serializer = OrderItemsGroupCustomizerSerializer(self.group_cust)
        data = serializer.data
        self.assertEqual(data['customizer_description'], 'Premium 3D adjustable concealed hinges')
        self.assertEqual(data['par1_hint'], 'Number of hinges from 2 to 5')

    def test_order_views_contain_tooltips(self):
        # Order list view
        resp = self.client.get(reverse('order-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-bs-toggle="tooltip"')
        self.assertContains(resp, 'ORD-2026-TEST')

        # Order detail view
        resp = self.client.get(reverse('order-detail', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-bs-toggle="tooltip"')
        self.assertContains(resp, 'initTooltips')

        # Order measurements view
        resp = self.client.get(reverse('order-measurements', args=[self.order.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-bs-toggle="tooltip"')
