import datetime

from django import forms
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import ProductType, ProductFamily, Series, Front, Color, ProductModel, Customizer, Handle, \
    Material
from apps.production.models import BOM
from .forms import OrderForm, OrderHeaderForm, OrderItemsGroupForm
from .models import Order, OrderItemsGroup, OrderItem, OrderItemsGroupCustomizer, OrderStatus
from .serializers import OrderItemsGroupCustomizerSerializer
from .utils import add_israeli_working_days


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


class OrderDatesAndFrameColorTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='admin', password='password123', role='ADMIN')
        self.client.force_login(self.user)

        self.pt = ProductType.objects.create(name='דלתות פנים', code='DOORS', has_door=True, has_frame=True)
        self.pf = ProductFamily.objects.create(name='משפחה 1', code='FAM1', product_type=self.pt)
        self.series_linea = Series.objects.create(code='LINEA', name='LINEA')
        self.color_white = Color.objects.create(name='לבן')
        self.color_black = Color.objects.create(name='שחור')
        self.color_anodize = Color.objects.create(name='אנודייז')

        self.series_forma = Series.objects.create(code='FORMA', name='FORMA')
        self.color_forma_black = Color.objects.create(name='שחור פורמה')

        self.mat_frame_white = Material.objects.create(
            name='משקוף ליין לבן', common_name='משקוף ליין', color=self.color_white, sku='MAT-LIN-W'
        )
        self.mat_frame_black = Material.objects.create(
            name='משקוף ליין שחור', common_name='משקוף ליין', color=self.color_black, sku='MAT-LIN-B'
        )
        self.mat_frame_anodize = Material.objects.create(
            name='משקוף ליין אנודייז', common_name='משקוף ליין', color=self.color_anodize, sku='MAT-LIN-A'
        )
        self.mat_frame_forma = Material.objects.create(
            name='משקוף פורמה שחור', common_name='משקוף פורמה', color=self.color_forma_black, sku='MAT-FOR-B'
        )

        self.front_linea = Front.objects.create(series=self.series_linea, code='F_LIN', name='Linea Front')
        self.handle = Handle.objects.create(code='H_STD', name='Standard Handle')
        self.product = ProductModel.objects.create(
            name='דגם 1', code='M1', series=self.series_linea, product_family=self.pf
        )
        self.bom = BOM.objects.create(product=self.product, frame=self.mat_frame_white)

        self.product_forma = ProductModel.objects.create(
            name='דגם פורמה', code='M_FORMA', series=self.series_forma, product_family=self.pf
        )
        self.bom_forma = BOM.objects.create(product=self.product_forma, frame=self.mat_frame_forma)

    def test_add_israeli_working_days(self):
        # Sunday 2026-08-16
        start = datetime.date(2026, 8, 16)
        # +10 working days: 2 weeks of 5 days (Sun-Thu) -> Sun 2026-08-30
        target_10 = add_israeli_working_days(start, 10)
        self.assertEqual(target_10, datetime.date(2026, 8, 30))

        # +20 working days: includes Rosh Hashana (Sun 2026-09-13 holiday) -> Mon 2026-09-14
        target_20 = add_israeli_working_days(start, 20)
        self.assertEqual(target_20, datetime.date(2026, 9, 14))

    def test_order_auto_calculates_dates_on_creation(self):
        order = Order.objects.create(
            order_number='ORD-AUTO-DATES',
            customer='Customer Test',
            series=self.series_linea,
            color_frames='RAL 7016'
        )
        base_date = order.created_at.date()
        expected_completion = add_israeli_working_days(base_date, 10)
        expected_painting = add_israeli_working_days(base_date, 20)

        self.assertEqual(order.completion_date, expected_completion)
        self.assertEqual(order.painting_completion_date, expected_painting)

    def test_order_forms_exclude_manual_dates_and_have_color_frames(self):
        form = OrderForm()
        # Date fields should not be in the form fields
        self.assertNotIn('painting_date', form.fields)
        self.assertNotIn('painting_completion_date', form.fields)
        self.assertNotIn('completion_date', form.fields)
        self.assertNotIn('phase1_completion_date', form.fields)

        # color_frames is in form as TextInput (free text)
        self.assertIn('color_frames', form.fields)
        self.assertIsInstance(form.fields['color_frames'].widget, forms.TextInput)

        # HeaderForm also excludes dates and has both fields
        header_form = OrderHeaderForm()
        self.assertNotIn('painting_date', header_form.fields)
        self.assertNotIn('painting_completion_date', header_form.fields)
        self.assertNotIn('completion_date', header_form.fields)
        self.assertNotIn('phase1_completion_date', header_form.fields)
        self.assertIn('color_frames', header_form.fields)
        self.assertIsInstance(header_form.fields['color_frames'].widget, forms.TextInput)

    def test_order_creation_via_form_and_post(self):
        post_data = {
            'order_number': 'ORD-POST-CREATE',
            'customer': 'New Client',
            'series': self.series_linea.id,
            'front': self.front_linea.id,
            'handle': self.handle.id,
            'color_panels': 'RAL 9005',
            'is_frames_to_paint': True,
            'color_frames': 'RAL 9005',
            'comments': 'Test comments'
        }
        form = OrderForm(data=post_data)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")
        order = form.save()

        self.assertEqual(order.order_number, 'ORD-POST-CREATE')
        self.assertEqual(order.series, self.series_linea)
        self.assertEqual(order.color_frames, 'RAL 9005')
        self.assertIsNotNone(order.completion_date)
        self.assertIsNotNone(order.painting_completion_date)

    def test_order_header_edit_view(self):
        order = Order.objects.create(
            order_number='ORD-HEADER-EDIT',
            customer='Original Name',
            series=self.series_linea,
            color_frames='RAL 1013'
        )
        resp = self.client.post(reverse('order-edit-header', args=[order.pk]), {
            'customer': 'Updated Name',
            'series': self.series_linea.id,
            'front': self.front_linea.id,
            'handle': self.handle.id,
            'color_panels': '',
            'is_frames_to_paint': True,
            'color_frames': 'RAL 9005',
            'comments': ''
        })
        self.assertEqual(resp.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.customer, 'Updated Name')
        self.assertEqual(order.color_frames, 'RAL 9005')

    def test_group_inherits_from_order(self):
        order = Order.objects.create(
            order_number='ORD-GRP-INHERIT',
            customer='Inherit Test',
            series=self.series_linea,
            front=self.front_linea,
            color_frames='RAL 7016',
            is_frames_to_paint=False
        )
        group = OrderItemsGroup.objects.create(
            order=order,
            product=self.product,
            quantity=2,
            # No series, front explicitly specified
        )
        self.assertEqual(group.series, self.series_linea)
        self.assertEqual(group.front, self.front_linea)

    def test_group_form_initial_and_queryset(self):
        order = Order.objects.create(
            order_number='ORD-GRP-FORM',
            customer='Group Form Test',
            series=self.series_linea,
            front=self.front_linea,
        )
        form = OrderItemsGroupForm(order=order)
        self.assertEqual(form.initial.get('series'), self.series_linea)
        self.assertEqual(form.initial.get('front'), self.front_linea)
        self.assertIn(self.mat_frame_white, form.fields['basic_color_frames'].queryset)
        self.assertIn(self.mat_frame_black, form.fields['basic_color_frames'].queryset)
        self.assertNotIn(self.mat_frame_forma, form.fields['basic_color_frames'].queryset)

    def test_group_form_product_material_common_name_color_resolution(self):
        # When selecting product_family + series, product model is resolved with BOM frame common_name
        form = OrderItemsGroupForm(data={
            'series': self.series_linea.id,
            'product_family': self.pf.id,
            'product': self.product.id,
            'quantity': 1,
            'basic_color_frames': self.mat_frame_anodize.id,
            'panel_paint_option': OrderItemsGroup.PaintOption.NO_PAINT,
            'frame_paint_option': OrderItemsGroup.PaintOption.NO_PAINT,
        })
        self.assertIn(self.mat_frame_white, form.fields['basic_color_frames'].queryset)
        self.assertIn(self.mat_frame_black, form.fields['basic_color_frames'].queryset)
        self.assertIn(self.mat_frame_anodize, form.fields['basic_color_frames'].queryset)
        self.assertNotIn(self.mat_frame_forma, form.fields['basic_color_frames'].queryset)

    def test_order_detail_view_renders_header_and_dates(self):
        order = Order.objects.create(
            order_number='ORD-DETAIL-PAGE',
            customer='Detail Page Client',
            series=self.series_linea,
            front=self.front_linea,
            color_frames='RAL 7016',
            handle=self.handle,
        )
        resp = self.client.get(reverse('order-detail', args=[order.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ORD-DETAIL-PAGE')
        self.assertContains(resp, 'Detail Page Client')
        self.assertContains(resp, order.completion_date.strftime('%d/%m/%Y'))
        self.assertContains(resp, order.painting_completion_date.strftime('%d/%m/%Y'))

    def test_order_detail_view_renders_for_production_statuses(self):
        # Test PHASE1_PRODUCTION
        order_p1 = Order.objects.create(
            order_number='ORD-P1',
            customer='P1 Client',
            series=self.series_linea,
            front=self.front_linea,
            status=OrderStatus.PHASE1_PRODUCTION,
        )
        resp = self.client.get(reverse('order-detail', args=[order_p1.pk]))
        self.assertEqual(resp.status_code, 200)

        # Test PHASE1_READY
        order_p1_ready = Order.objects.create(
            order_number='ORD-P1-READY',
            customer='P1 Ready Client',
            series=self.series_linea,
            front=self.front_linea,
            status=OrderStatus.PHASE1_READY,
        )
        resp = self.client.get(reverse('order-detail', args=[order_p1_ready.pk]))
        self.assertEqual(resp.status_code, 200)

        # Test IN_PRODUCTION (regular)
        order_prod = Order.objects.create(
            order_number='ORD-IN-PROD',
            customer='Prod Client',
            series=self.series_linea,
            front=self.front_linea,
            handle=self.handle,
            status=OrderStatus.IN_PRODUCTION,
        )
        resp = self.client.get(reverse('order-detail', args=[order_prod.pk]))
        self.assertEqual(resp.status_code, 200)

        # Test IN_PRODUCTION (split installation)
        group_split = OrderItemsGroup.objects.create(
            order=order_prod,
            product=self.product,
            quantity=1,
            is_split_installation=True
        )
        resp = self.client.get(reverse('order-detail', args=[order_prod.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_order_production_report_url_resolution(self):
        order = Order.objects.create(
            order_number='ORD-REP-URL',
            customer='Rep Client',
            series=self.series_linea,
            front=self.front_linea,
            handle=self.handle,
            status=OrderStatus.IN_PRODUCTION,
        )
        url = reverse('order-production-report', args=[order.pk])
        self.assertEqual(url, f'/orders/{order.pk}/production-report/')
