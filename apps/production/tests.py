import io
import zipfile

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import ProductType, ProductFamily, Series, Front, ProductModel, Handle
from apps.orders.models import Order, OrderItemsGroup, OrderStatus
from apps.production.services import OrderValidationService


class OrderValidationServiceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='admin_test', password='password123', role='ADMIN')
        self.client.force_login(self.user)

        # Standard Door + Frame Product Type
        self.pt_door_frame = ProductType.objects.create(
            code='INT_DOOR', name='Interior Door with Frame',
            has_door=True, has_frame=True
        )
        self.pf = ProductFamily.objects.create(
            product_type=self.pt_door_frame, code='FAM1', name='Flush Doors'
        )
        self.series = Series.objects.create(code='SR1', name='Series 1')
        self.front = Front.objects.create(series=self.series, code='FR1', name='White Matte')
        self.handle = Handle.objects.create(code='HD1', name='Magnetic Handle')
        self.product = ProductModel.objects.create(
            code='MD1', name='Flush Door Model 1', product_family=self.pf, series=self.series
        )

    def test_empty_order_validation(self):
        order = Order.objects.create(order_number='ORD-EMPTY', customer='Customer')
        res_partial = OrderValidationService.validate_partial(order)
        res_full = OrderValidationService.validate_full(order)

        self.assertFalse(res_partial.is_valid)
        self.assertFalse(res_full.is_valid)
        self.assertTrue(any('אין קבוצות' in err for err in res_partial.errors))

    def test_missing_series_or_front_validation(self):
        order = Order.objects.create(order_number='ORD-MISSING-SF', customer='Customer')
        group = OrderItemsGroup.objects.create(
            order=order, product=self.product, quantity=1
        )
        # Item with valid dimensions
        item = group.items.first()
        item.height = 2000
        item.width = 800
        item.wall = 120
        item.opening = 'LEFT'
        item.direction = 'IN'
        item.save()

        res_partial = OrderValidationService.validate_partial(order)
        self.assertFalse(res_partial.is_valid)
        self.assertTrue(any('סדרה' in err for err in res_partial.errors))
        self.assertTrue(any('חזית' in err for err in res_partial.errors))

    def test_partial_validation_succeeds_without_handle(self):
        """
        In Phase 1 (partial validation), handle is NOT required.
        Series, front, and item dimensions are required.
        """
        order = Order.objects.create(
            order_number='ORD-PHASE1', customer='Customer',
            series=self.series, front=self.front, handle=None
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.product, series=self.series, front=self.front,
            quantity=1, is_split_installation=True
        )
        item = group.items.first()
        item.height = 2050
        item.width = 850
        item.wall = 120
        item.opening = 'RIGHT'
        item.direction = 'IN'
        item.save()

        # Partial validation should pass
        res_partial = OrderValidationService.validate_partial(order)
        self.assertTrue(res_partial.is_valid, f"Expected valid, got errors: {res_partial.errors}")
        self.assertEqual(len(res_partial.errors), 0)

        # Full validation should FAIL because handle is missing
        res_full = OrderValidationService.validate_full(order)
        self.assertFalse(res_full.is_valid)
        self.assertTrue(any('ידית' in err for err in res_full.errors))

    def test_full_validation_succeeds_with_handle_and_all_fields(self):
        """
        Full validation (Phase 2 or split_installation=False) requires handle, series, front, and dimensions.
        """
        order = Order.objects.create(
            order_number='ORD-FULL-OK', customer='Customer',
            series=self.series, front=self.front, handle=self.handle
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.product, series=self.series, front=self.front,
            quantity=1, is_split_installation=False
        )
        item = group.items.first()
        item.height = 2050
        item.width = 850
        item.wall = 120
        item.opening = 'LEFT'
        item.direction = 'OUT'
        item.save()

        res_full = OrderValidationService.validate_full(order)
        self.assertTrue(res_full.is_valid, f"Expected full valid, got: {res_full.errors}")

    def test_item_dimensions_validation_for_doors_and_frames(self):
        """
        Items with has_door and has_frame must have height, width, wall, opening, direction.
        """
        order = Order.objects.create(
            order_number='ORD-NO-DIMS', customer='Customer',
            series=self.series, front=self.front, handle=self.handle
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.product, series=self.series, front=self.front,
            quantity=1
        )
        # The auto-created item has empty dimensions

        res_partial = OrderValidationService.validate_partial(order)
        self.assertFalse(res_partial.is_valid)
        self.assertTrue(any('גובה' in err for err in res_partial.errors))
        self.assertTrue(any('רוחב' in err for err in res_partial.errors))
        self.assertTrue(any('עובי קיר' in err for err in res_partial.errors))
        self.assertTrue(any('צד פתיחה' in err for err in res_partial.errors))
        self.assertTrue(any('כיוון פתיחה' in err for err in res_partial.errors))

    def test_frame_only_item_does_not_require_door_opening(self):
        """
        If product type only has frame (has_door=False, has_frame=True), opening/direction shouldn't be required.
        """
        pt_frame_only = ProductType.objects.create(
            code='FRAME_ONLY', name='Frame Only', has_door=False, has_frame=True
        )
        pf_frame = ProductFamily.objects.create(product_type=pt_frame_only, code='FAM_FR', name='Frame Fam')
        pm_frame = ProductModel.objects.create(code='MDL_FR', name='Frame Model', product_family=pf_frame,
                                               series=self.series)

        order = Order.objects.create(
            order_number='ORD-FRAME-ONLY', customer='Customer',
            series=self.series, front=self.front
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=pm_frame, series=self.series, front=self.front,
            quantity=1
        )
        item = group.items.first()
        item.height = 2100
        item.width = 900
        item.wall = 150
        item.save()

        res_partial = OrderValidationService.validate_partial(order)
        self.assertTrue(res_partial.is_valid, f"Expected valid, got: {res_partial.errors}")

        # Full validation for frame-only order doesn't require handle because has_any_doors is False
        res_full = OrderValidationService.validate_full(order)
        self.assertTrue(res_full.is_valid, f"Expected valid, got: {res_full.errors}")

    def test_special_paint_color_validation(self):
        """
        If panel or frame paint option is SPECIAL_COLOR, color must be specified.
        """
        order = Order.objects.create(
            order_number='ORD-PAINT-SPECIAL', customer='Customer',
            series=self.series, front=self.front, handle=self.handle
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.product, series=self.series, front=self.front,
            quantity=1, panel_paint_option=OrderItemsGroup.PaintOption.SPECIAL_COLOR,
            color_panels=None
        )
        item = group.items.first()
        item.height = 2050
        item.width = 850
        item.wall = 120
        item.opening = 'LEFT'
        item.direction = 'IN'
        item.save()

        res_full = OrderValidationService.validate_full(order)
        self.assertFalse(res_full.is_valid)
        self.assertTrue(any('גוון מיוחד' in err for err in res_full.errors))

        # Once color is set, full validation passes
        group.color_panels = 'RAL 9005'
        group.save()
        res_full = OrderValidationService.validate_full(order)
        self.assertTrue(res_full.is_valid, f"Expected valid, got: {res_full.errors}")

    def test_model_methods_validate_and_start(self):
        """
        Tests order.validate_for_production(), order.start_production(), order.start_phase1().
        """
        order = Order.objects.create(
            order_number='ORD-MODEL-METH', customer='Customer',
            series=self.series, front=self.front, handle=None
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.product, series=self.series, front=self.front,
            quantity=1, is_split_installation=True
        )
        item = group.items.first()
        item.height = 2050
        item.width = 850
        item.wall = 120
        item.opening = 'LEFT'
        item.direction = 'IN'
        item.save()

        # Partial validation via model
        is_valid, errors = order.validate_for_production()
        self.assertTrue(is_valid)

        # start_phase1 should succeed
        order.start_phase1(user=self.user)
        self.assertEqual(order.status, OrderStatus.PHASE1_PRODUCTION)

        # start_production without handle should raise ValueError
        with self.assertRaises(ValueError):
            order.start_production(user=self.user)

        # Add handle -> start_production should succeed
        order.handle = self.handle
        order.save()
        order.status = OrderStatus.PHASE1_READY
        order.save()

        order.start_production(user=self.user)
        self.assertEqual(order.status, OrderStatus.IN_PRODUCTION)


class ProductionReportAndZipValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='admin_reports', password='password123', role='ADMIN')
        self.client.force_login(self.user)

        self.pt = ProductType.objects.create(code='PT1', name='Standard Door', has_door=True, has_frame=True)
        self.pf = ProductFamily.objects.create(product_type=self.pt, code='PF1', name='Fam 1')
        self.series = Series.objects.create(code='SR1', name='Series 1')
        self.front = Front.objects.create(series=self.series, code='FR1', name='Front 1')
        self.handle = Handle.objects.create(code='HD1', name='Handle 1')
        self.pm = ProductModel.objects.create(code='PM1', name='Model 1', product_family=self.pf, series=self.series)

    def test_phase1_report_succeeds_without_handles(self):
        """
        Phase 1 frames report requires only partial validation (no handle needed).
        """
        order = Order.objects.create(
            order_number='ORD-REP-P1', customer='Client A',
            series=self.series, front=self.front, handle=None,
            status=OrderStatus.PHASE1_PRODUCTION
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.pm, series=self.series, front=self.front,
            quantity=1, is_split_installation=True
        )
        item = group.items.first()
        item.height = 2050
        item.width = 800
        item.wall = 100
        item.opening = 'LEFT'
        item.direction = 'IN'
        item.save()

        # GET phase 1 report
        url = reverse('alum-frames-report', args=[order.pk]) + '?type=PHASE1_FRAMES'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ORD-REP-P1')
        self.assertIn(
            b'\xd7\x9e\xd7\xa9\xd7\xa7\xd7\x95\xd7\xa4\xd7\x99\xd7\x9d \xd7\x90\xd7\x9c\xd7\x95\xd7\x9e\xd7\x99\xd7\x9e\xd7\x99\xd7\x95\xd7\x9d',
            resp.content)

    def test_phase2_report_fails_and_renders_error_page_if_no_handle(self):
        """
        Phase 2 report requires full validation (fails if handle is missing).
        """
        order = Order.objects.create(
            order_number='ORD-REP-P2', customer='Client B',
            series=self.series, front=self.front, handle=None,
            status=OrderStatus.IN_PRODUCTION
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.pm, series=self.series, front=self.front,
            quantity=1, is_split_installation=False
        )
        item = group.items.first()
        item.height = 2050
        item.width = 800
        item.wall = 100
        item.opening = 'LEFT'
        item.direction = 'IN'
        item.save()

        url = reverse('alum-frames-report', args=[order.pk]) + '?type=PHASE2_DOORS'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'לא ניתן להפיק את הדו"ח')
        self.assertContains(resp, 'לא נבחרה ידית להזמנה')

    def test_production_zip_fails_when_invalid(self):
        """
        order_production_data redirects with error messages if validation fails.
        """
        order = Order.objects.create(
            order_number='ORD-ZIP-FAIL', customer='Client C',
            status=OrderStatus.IN_PRODUCTION
        )
        # Empty order -> invalid
        url = reverse('order-production-data', args=[order.pk])
        resp = self.client.get(url)
        # Should redirect to order-detail with error message
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.endswith(reverse('order-detail', args=[order.pk])))

    def test_production_zip_succeeds_when_valid(self):
        """
        order_production_data returns ZIP archive when valid.
        """
        order = Order.objects.create(
            order_number='ORD-ZIP-OK', customer='Client D',
            series=self.series, front=self.front, handle=self.handle,
            status=OrderStatus.IN_PRODUCTION
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.pm, series=self.series, front=self.front,
            quantity=1
        )
        item = group.items.first()
        item.height = 2050
        item.width = 800
        item.wall = 100
        item.opening = 'LEFT'
        item.direction = 'IN'
        item.save()

        url = reverse('order-production-data', args=[order.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/zip')
        self.assertIn('attachment; filename="production_data_ORD-ZIP-OK.zip"', resp['Content-Disposition'])

        # Check zip content is valid
        zip_buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buf, 'r') as zf:
            file_names = zf.namelist()
            self.assertTrue(any('ORD-ZIP-OK' in fn for fn in file_names))


class OrderStatusTransitionValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='admin_trans', password='password123', role='ADMIN')
        self.client.force_login(self.user)

        self.pt = ProductType.objects.create(code='PT2', name='Door Type', has_door=True, has_frame=True)
        self.pf = ProductFamily.objects.create(product_type=self.pt, code='PF2', name='Fam 2')
        self.series = Series.objects.create(code='SR2', name='Series 2')
        self.front = Front.objects.create(series=self.series, code='FR2', name='Front 2')
        self.handle = Handle.objects.create(code='HD2', name='Handle 2')
        self.pm = ProductModel.objects.create(code='PM2', name='Model 2', product_family=self.pf, series=self.series)

    def test_transfer_to_phase1_view_success(self):
        """
        Transferring split order to Phase 1 requires partial validation and succeeds without handle.
        """
        order = Order.objects.create(
            order_number='ORD-TRANS-P1', customer='Client 1',
            series=self.series, front=self.front, handle=None,
            status=OrderStatus.DRAFT
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.pm, series=self.series, front=self.front,
            quantity=1, is_split_installation=True
        )
        item = group.items.first()
        item.height = 2050
        item.width = 800
        item.wall = 100
        item.opening = 'LEFT'
        item.direction = 'IN'
        item.save()

        resp = self.client.get(reverse('order-transfer-to-phase1', args=[order.pk]))
        self.assertEqual(resp.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PHASE1_PRODUCTION)

    def test_transfer_to_production_fails_when_handle_missing(self):
        """
        Transferring to full production requires full validation (fails if handle is missing).
        """
        order = Order.objects.create(
            order_number='ORD-TRANS-FULL-FAIL', customer='Client 2',
            series=self.series, front=self.front, handle=None,
            status=OrderStatus.DRAFT
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.pm, series=self.series, front=self.front,
            quantity=1, is_split_installation=False
        )
        item = group.items.first()
        item.height = 2050
        item.width = 800
        item.wall = 100
        item.opening = 'LEFT'
        item.direction = 'IN'
        item.save()

        resp = self.client.get(reverse('order-transfer-to-production', args=[order.pk]))
        self.assertEqual(resp.status_code, 302)
        order.refresh_from_db()
        # Status should NOT change
        self.assertEqual(order.status, OrderStatus.DRAFT)

    def test_transfer_to_production_succeeds_when_valid(self):
        """
        Transferring to full production succeeds when all data including handle is set.
        """
        order = Order.objects.create(
            order_number='ORD-TRANS-FULL-OK', customer='Client 3',
            series=self.series, front=self.front, handle=self.handle,
            status=OrderStatus.DRAFT
        )
        group = OrderItemsGroup.objects.create(
            order=order, product=self.pm, series=self.series, front=self.front,
            quantity=1, is_split_installation=False
        )
        item = group.items.first()
        item.height = 2050
        item.width = 800
        item.wall = 100
        item.opening = 'LEFT'
        item.direction = 'IN'
        item.save()

        resp = self.client.get(reverse('order-transfer-to-production', args=[order.pk]))
        self.assertEqual(resp.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.IN_PRODUCTION)
