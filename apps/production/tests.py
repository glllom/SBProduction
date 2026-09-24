import io
import zipfile

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import (
    ProductType, ProductFamily, Series, Front, ProductModel, Handle,
    Customizer
)
from apps.orders.models import Order, OrderItemsGroup, OrderStatus, OrderItemsGroupCustomizer
from apps.production.models import (
    ProductionStation, ProductionRoute, ProductionRouteStep,
    CustomizerProductionStation
)
from apps.production.services import OrderValidationService, OrderProductionService, ProductionDataService


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
        self.assertTrue(any('No product groups' in err for err in res_partial.errors))

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
        self.assertTrue(any('Series' in err for err in res_partial.errors))
        self.assertTrue(any('Front' in err for err in res_partial.errors))

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
        self.assertTrue(any('Handle' in err for err in res_full.errors))

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
        self.assertTrue(any('height' in err for err in res_partial.errors))
        self.assertTrue(any('width' in err for err in res_partial.errors))
        self.assertTrue(any('Wall thickness' in err for err in res_partial.errors))
        self.assertTrue(any('Opening side' in err for err in res_partial.errors))
        self.assertTrue(any('Opening direction' in err for err in res_partial.errors))

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
        self.assertTrue(any('Special' in err for err in res_full.errors))

        # Once color is set, full validation passes
        group.color_panels = 'RAL 9005'
        group.save()
        res_full = OrderValidationService.validate_full(order)
        self.assertTrue(res_full.is_valid, f"Expected valid, got: {res_full.errors}")

    def test_model_methods_validate_and_start(self):
        """
        Tests OrderProductionService.validate_for_production(), start_production(), start_phase1().
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

        # Partial validation via service
        is_valid, errors = OrderProductionService.validate_for_production(order)
        self.assertTrue(is_valid)

        # start_phase1 should succeed
        OrderProductionService.start_phase1(order, user=self.user)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PHASE1_PRODUCTION)

        # start_production without handle should NOT raise ValueError if in Phase 1 and split
        # because it only does partial validation
        OrderProductionService.start_production(order, user=self.user)
        self.assertEqual(order.status, OrderStatus.PHASE1_PRODUCTION)

        # Complete Phase 1
        OrderProductionService.complete_phase1(order, user=self.user)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PHASE1_READY)

        # Now start_production without handle SHOULD raise ValueError 
        # (Full validation required for Phase 2 regardless of has_split)
        with self.assertRaises(ValueError):
            OrderProductionService.start_production(order, user=self.user)

        # Add handle -> start_production should succeed
        order.handle = self.handle
        order.save()
        order.status = OrderStatus.PHASE1_READY
        order.save()

        OrderProductionService.start_production(order, user=self.user)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.PHASE2_PRODUCTION)


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
        url = reverse('production:alum-frames-report', args=[order.pk]) + '?type=PHASE1_FRAMES'
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

        url = reverse('production:alum-frames-report', args=[order.pk]) + '?type=PHASE2_DOORS'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # self.assertContains(resp, 'לא ניתן להפיק את הדו"ח')
        self.assertContains(resp, 'Handle not selected')

    def test_production_zip_fails_when_invalid(self):
        """
        order_production_data redirects with error messages if validation fails.
        """
        order = Order.objects.create(
            order_number='ORD-ZIP-FAIL', customer='Client C',
            status=OrderStatus.IN_PRODUCTION
        )
        # Empty order -> invalid
        url = reverse('production:order-production-data', args=[order.pk])
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

        url = reverse('production:order-production-data', args=[order.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/zip')
        self.assertIn('attachment; filename="production_data_ORD-ZIP-OK.zip"', resp['Content-Disposition'])

        # Check zip content is valid
        zip_buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buf, 'r') as zf:
            file_names = zf.namelist()
            self.assertTrue(any('ORD-ZIP-OK' in fn for fn in file_names))

    def test_master_report_aggregation_station_all(self):
        """
        station-report with ?station=ALL renders master_report.html with all sections and page breaks.
        """
        order = Order.objects.create(
            order_number='ORD-MASTER-REP', customer='Client Master',
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

        # Create stations and route
        s_frames = ProductionStation.objects.create(
            name='משקופים', code='FRAMES', label='משקופים', template_name='production/alum_frames_report.html',
            has_specification=True
        )
        s_doors = ProductionStation.objects.create(
            name='כנפיים', code='DOORS', label='כנפיים', template_name='production/alum_doors_report.html',
            has_specification=True
        )
        route = ProductionRoute.objects.create(product_type=self.pt, name='Full Route')
        ProductionRouteStep.objects.create(route=route, station=s_frames, order=10)
        ProductionRouteStep.objects.create(route=route, station=s_doors, order=20)

        url = reverse('production:station-report', args=[order.pk]) + '?station=ALL'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'production/master_report.html')
        self.assertContains(resp, 'מאסטר דו\'\'ח ייצור')
        self.assertContains(resp, 'page-break')
        self.assertContains(resp, 'ORD-MASTER-REP')

    def test_order_detail_action_toolbar_and_categories(self):
        """
        order_detail view renders primary CTAs, collapsible toolbar with 3 categories, and dev tools.
        """
        order = Order.objects.create(
            order_number='ORD-TOOLBAR-TEST', customer='Client Toolbar',
            series=self.series, front=self.front, handle=self.handle,
            status=OrderStatus.NEW
        )
        OrderItemsGroup.objects.create(
            order=order, product=self.pm, series=self.series, front=self.front,
            quantity=1
        )

        resp = self.client.get(reverse('order-detail', args=[order.pk]))
        self.assertEqual(resp.status_code, 200)
        # Primary CTA for NEW
        self.assertContains(resp, 'העבר לייצור')
        # Collapsible toolbar button & id
        self.assertContains(resp, 'פעולות ייצור ומסמכים')
        self.assertContains(resp, 'productionActionsPanel')
        # 3 categories
        self.assertContains(resp, 'דוחות ייצור')
        self.assertContains(resp, 'קבצי מכונות (CNC)')
        self.assertContains(resp, 'מדבקות')
        self.assertContains(resp, 'Master Print')
        # Dev Tools dropdown
        self.assertContains(resp, 'Dev Tools')
        self.assertContains(resp, 'Rebuild Spec')


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
            status=OrderStatus.NEW
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

        resp = self.client.get(reverse('production:order-transfer-to-phase1', args=[order.pk]))
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
            status=OrderStatus.NEW
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

        resp = self.client.get(reverse('production:order-transfer-to-production', args=[order.pk]))
        self.assertEqual(resp.status_code, 302)
        order.refresh_from_db()
        # Status should NOT change
        self.assertEqual(order.status, OrderStatus.NEW)

    def test_transfer_to_production_succeeds_when_valid(self):
        """
        Transferring to full production succeeds when all data including handle is set.
        """
        order = Order.objects.create(
            order_number='ORD-TRANS-FULL-OK', customer='Client 3',
            series=self.series, front=self.front, handle=self.handle,
            status=OrderStatus.NEW
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

        resp = self.client.get(reverse('production:order-transfer-to-production', args=[order.pk]))
        self.assertEqual(resp.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.IN_PRODUCTION)


class ProductionRouteAndDynamicButtonsTests(TestCase):
    def setUp(self):
        self.pt = ProductType.objects.create(code='PT3', name='Type 3')
        self.pf = ProductFamily.objects.create(product_type=self.pt, code='PF3', name='Fam 3')
        self.series = Series.objects.create(code='SR3', name='Series 3')
        self.front = Front.objects.create(series=self.series, code='FR3', name='Front 3')
        self.handle = Handle.objects.create(code='HD3', name='Handle 3')
        self.pm = ProductModel.objects.create(code='PM3', name='Model 3', product_family=self.pf, series=self.series)

        self.s1 = ProductionStation.objects.create(name='Station 1', code='S1', label='Btn 1', has_specification=True)
        self.s2 = ProductionStation.objects.create(name='Station 2', code='S2', label='Btn 2', has_specification=True)
        self.s3 = ProductionStation.objects.create(name='Station 3', code='S3', label='Btn 3', has_specification=False)
        self.s_cust = ProductionStation.objects.create(name='Custom Station', code='SC', label='Btn C',
                                                       has_specification=True)

        self.customizer = Customizer.objects.create(code='CUST1', name='Customizer 1')
        CustomizerProductionStation.objects.create(customizer=self.customizer, station=self.s_cust)

    def test_route_inheritance(self):
        # Route for Type
        route_type = ProductionRoute.objects.create(product_type=self.pt, name='Type Route')
        ProductionRouteStep.objects.create(route=route_type, station=self.s1, order=10)

        # Route for Family
        route_fam = ProductionRoute.objects.create(product_family=self.pf, name='Fam Route')
        ProductionRouteStep.objects.create(route=route_fam, station=self.s2, order=10)

        # Get stations for product
        stations = ProductionRoute.get_stations_for_product(self.pm)
        # Should inherit from Type and Family
        station_ids = [s.id for s in stations]
        self.assertIn(self.s1.id, station_ids)
        self.assertIn(self.s2.id, station_ids)
        self.assertEqual(len(stations), 2)

    def test_model_override(self):
        # Route for Type
        route_type = ProductionRoute.objects.create(product_type=self.pt, name='Type Route')
        ProductionRouteStep.objects.create(route=route_type, station=self.s1, order=10)

        # Route for Model (Override)
        route_model = ProductionRoute.objects.create(product_model=self.pm, name='Model Route')
        ProductionRouteStep.objects.create(route=route_model, station=self.s2, order=10)

        stations = ProductionRoute.get_stations_for_product(self.pm)
        # Should only have station from Model route
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0].id, self.s2.id)

    def test_customizer_adds_station(self):
        route_type = ProductionRoute.objects.create(product_type=self.pt, name='Type Route')
        ProductionRouteStep.objects.create(route=route_type, station=self.s1, order=10)

        order = Order.objects.create(order_number='ORD-CUST', customer='Customer')
        group = OrderItemsGroup.objects.create(order=order, product=self.pm, quantity=1)

        # Add customizer to group
        OrderItemsGroupCustomizer.objects.create(group=group, customizer=self.customizer)

        stations = ProductionRoute.get_stations_for_group(group)
        station_ids = [s.id for s in stations]
        self.assertIn(self.s1.id, station_ids)
        self.assertIn(self.s_cust.id, station_ids)
        self.assertEqual(len(stations), 2)

    def test_order_aggregated_stations(self):
        route_type = ProductionRoute.objects.create(product_type=self.pt, name='Type Route')
        ProductionRouteStep.objects.create(route=route_type, station=self.s1, order=10)

        order = Order.objects.create(order_number='ORD-AGGR', customer='Customer')

        # Group 1 with product PM3 (Station 1)
        group1 = OrderItemsGroup.objects.create(order=order, product=self.pm, quantity=1)

        # Group 2 with customizer (Station 1 + Custom Station)
        group2 = OrderItemsGroup.objects.create(order=order, product=self.pm, quantity=1)
        OrderItemsGroupCustomizer.objects.create(group=group2, customizer=self.customizer)

        stations = order.get_production_stations()
        station_ids = [s.id for s in stations]
        self.assertIn(self.s1.id, station_ids)
        self.assertIn(self.s_cust.id, station_ids)
        self.assertEqual(len(stations), 2)

        # Verify that only unique stations are returned
        self.assertEqual(len(set(station_ids)), len(station_ids))

    def test_report_filtering_by_station(self):
        # Route: S1 for PT3
        route_type = ProductionRoute.objects.create(product_type=self.pt, name='Type Route')
        ProductionRouteStep.objects.create(route=route_type, station=self.s1, order=10)

        order = Order.objects.create(
            order_number='ORD-FILTER', customer='Customer',
            series=self.series, front=self.front, handle=self.handle,
            status=OrderStatus.IN_PRODUCTION
        )

        # Group 1 with PM3 (has S1)
        group1 = OrderItemsGroup.objects.create(
            order=order, product=self.pm, series=self.series, front=self.front, quantity=1
        )
        item1 = group1.items.first()
        item1.height = 2000;
        item1.width = 800;
        item1.wall = 120;
        item1.opening = 'L';
        item1.direction = 'IN';
        item1.save()

        # Group 2 with PM3 + customizer (has S1 + SC)
        group2 = OrderItemsGroup.objects.create(
            order=order, product=self.pm, series=self.series, front=self.front, quantity=1
        )
        item2 = group2.items.first()
        item2.height = 2000;
        item2.width = 800;
        item2.wall = 120;
        item2.opening = 'L';
        item2.direction = 'IN';
        item2.save()
        OrderItemsGroupCustomizer.objects.create(group=group2, customizer=self.customizer)

        service = ProductionDataService(order)

        # Report for S1: should contain both groups (they will be grouped together because they have same attributes)
        data_s1 = service._get_order_data(station=self.s1)
        item_count_s1 = sum(len(g['items_specs']) for g in data_s1)
        self.assertEqual(item_count_s1, 2)

        # Report for SC: should contain only group 2
        data_sc = service._get_order_data(station=self.s_cust)
        item_count_sc = sum(len(g['items_specs']) for g in data_sc)
        self.assertEqual(item_count_sc, 1)


class PhasedProductionFilteringTests(TestCase):
    def setUp(self):
        self.pt = ProductType.objects.create(code='PT_PHASE', name='Phased Type')
        self.pf = ProductFamily.objects.create(product_type=self.pt, code='PF_PHASE', name='Phased Fam')
        self.series = Series.objects.create(code='SER_PHASE', name='Phased Series')
        self.pm = ProductModel.objects.create(code='PM_PHASE', name='Phased Model', product_family=self.pf,
                                              series=self.series)

        self.s_phase1 = ProductionStation.objects.create(
            name='Phase 1 Station', code='P1', is_phase1=True, has_specification=True
        )
        self.s_phase2 = ProductionStation.objects.create(
            name='Phase 2 Station', code='P2', is_phase1=False, has_specification=True
        )

        self.route = ProductionRoute.objects.create(product_type=self.pt, name='Phased Route')
        ProductionRouteStep.objects.create(route=self.route, station=self.s_phase1, order=10)
        ProductionRouteStep.objects.create(route=self.route, station=self.s_phase2, order=20)

    def test_station_filtering_by_status(self):
        order = Order.objects.create(order_number='ORD-PHASE-TEST', status=OrderStatus.NEW)
        OrderItemsGroup.objects.create(order=order, product=self.pm, quantity=1)

        # 1. NEW status - all stations should be returned
        stations = order.get_production_stations()
        station_ids = [s.id for s in stations]
        self.assertIn(self.s_phase1.id, station_ids)
        self.assertIn(self.s_phase2.id, station_ids)
        self.assertEqual(len(stations), 2)

        # 2. PHASE1_PRODUCTION status - only phase 1 stations
        order.status = OrderStatus.PHASE1_PRODUCTION
        order.save()
        stations = order.get_production_stations()
        station_ids = [s.id for s in stations]
        self.assertIn(self.s_phase1.id, station_ids)
        self.assertNotIn(self.s_phase2.id, station_ids)
        self.assertEqual(len(stations), 1)

        # 3. PHASE2_PRODUCTION status - only phase 2 stations
        order.status = OrderStatus.PHASE2_PRODUCTION
        order.save()
        stations = order.get_production_stations()
        station_ids = [s.id for s in stations]
        self.assertNotIn(self.s_phase1.id, station_ids)
        self.assertIn(self.s_phase2.id, station_ids)
        self.assertEqual(len(stations), 1)

        # 4. IN_PRODUCTION status (full cycle) - all stations
        order.status = OrderStatus.IN_PRODUCTION
        order.save()
        stations = order.get_production_stations()
        station_ids = [s.id for s in stations]
        self.assertIn(self.s_phase1.id, station_ids)
        self.assertIn(self.s_phase2.id, station_ids)
        self.assertEqual(len(stations), 2)


class RequiredCustomizersValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='prod_admin', password='password123', role='ADMIN')
        self.client.force_login(self.user)

        self.pt = ProductType.objects.create(code='PT_REQ', name='Required Customizers Type', has_door=True,
                                             has_frame=True)
        self.pf = ProductFamily.objects.create(product_type=self.pt, code='PF_REQ', name='Family')
        self.series = Series.objects.create(code='SR_REQ', name='Series')
        self.front = Front.objects.create(series=self.series, code='FR_REQ', name='Front')
        self.handle = Handle.objects.create(code='HD_REQ', name='Handle')
        self.product = ProductModel.objects.create(
            product_family=self.pf, series=self.series, code='PR_REQ', name='Door Model With Glass'
        )

        self.cust_glass = Customizer.objects.create(
            code='GLASS_SPEC',
            name='מפרט זכוכית',
            tag='glass',
            is_required=True,
            par1_label='סוג זכוכית',
            par1_required=True,
            par2_label='גוון זכוכית',
            par2_required=False,
            par2_value='שקוף'
        )
        self.product.required_customizers.add(self.cust_glass)

        self.order = Order.objects.create(
            order_number='ORD-GLASS-REQ',
            customer='Glass Customer',
            series=self.series,
            front=self.front,
            handle=self.handle,
            status=OrderStatus.NEW
        )

    def test_validation_fails_when_required_customizer_missing(self):
        """If required customizer is deleted/missing from group, validation fails."""
        group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=self.series,
            front=self.front,
            quantity=1
        )
        item = group.items.first()
        item.height = 2000;
        item.width = 800;
        item.wall = 100;
        item.opening = 'LEFT';
        item.direction = 'IN'
        item.save()

        # Delete the auto-populated customizer
        group.customizers.all().delete()

        res = OrderValidationService.validate_full(self.order)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Required customizer 'מפרט זכוכית' is missing" in err for err in res.errors))

    def test_validation_fails_when_required_parameter_empty(self):
        """If required parameter par1 is empty, validation fails and blocks transfer."""
        group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=self.series,
            front=self.front,
            quantity=1
        )
        item = group.items.first()
        item.height = 2000;
        item.width = 800;
        item.wall = 100;
        item.opening = 'LEFT';
        item.direction = 'IN'
        item.save()

        # By default auto-population left par1 empty
        gc = group.customizers.first()
        self.assertEqual(gc.par1, '')

        res = OrderValidationService.validate_full(self.order)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("Parameter 'סוג זכוכית' is required and cannot be empty" in err for err in res.errors))

        # Also when whitespace only
        gc.par1 = '   '
        gc.save()
        res_ws = OrderValidationService.validate_full(self.order)
        self.assertFalse(res_ws.is_valid)
        self.assertTrue(any("Parameter 'סוג זכוכית' is required and cannot be empty" in err for err in res_ws.errors))

    def test_validation_succeeds_when_required_parameter_filled(self):
        """When required parameter is filled, validation passes."""
        group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=self.series,
            front=self.front,
            quantity=1
        )
        item = group.items.first()
        item.height = 2000;
        item.width = 800;
        item.wall = 100;
        item.opening = 'LEFT';
        item.direction = 'IN'
        item.save()

        gc = group.customizers.first()
        gc.par1 = 'טריפלקס חלבי 3+3'
        gc.save()

        res = OrderValidationService.validate_full(self.order)
        self.assertTrue(res.is_valid, f"Validation failed with errors: {res.errors}")
        self.assertEqual(len(res.errors), 0)

    def test_order_check_validation_view_with_required_customizers(self):
        """Test the manual check validation view (order-check-validation)."""
        group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=self.series,
            front=self.front,
            quantity=1
        )
        item = group.items.first()
        item.height = 2000;
        item.width = 800;
        item.wall = 100;
        item.opening = 'LEFT';
        item.direction = 'IN'
        item.save()

        url = reverse('production:order-check-validation', args=[self.order.pk])

        # 1. First check with empty required par1 -> error message
        resp = self.client.get(url, follow=True)
        self.assertEqual(resp.status_code, 200)
        messages = list(resp.context['messages'])
        self.assertTrue(any("Parameter 'סוג זכוכית' is required" in str(m) for m in messages))

        # 2. Fill required parameter -> success message
        gc = group.customizers.first()
        gc.par1 = 'זכוכית מחוסמת 8 מ"מ'
        gc.save()

        resp_ok = self.client.get(url, follow=True)
        self.assertEqual(resp_ok.status_code, 200)
        messages_ok = list(resp_ok.context['messages'])
        self.assertTrue(any("Data is valid. Ready for production transfer." in str(m) for m in messages_ok))

    def test_transfer_to_production_blocked_by_unfilled_customizer(self):
        """Transfer to production is blocked when required customizer parameter is not filled."""
        group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=self.series,
            front=self.front,
            quantity=1
        )
        item = group.items.first()
        item.height = 2000;
        item.width = 800;
        item.wall = 100;
        item.opening = 'LEFT';
        item.direction = 'IN'
        item.save()

        url = reverse('production:order-transfer-to-production', args=[self.order.pk])

        # Attempt to transfer to production when par1 is empty
        resp = self.client.post(url, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.NEW)
        messages = list(resp.context['messages'])
        self.assertTrue(any("Parameter 'סוג זכוכית' is required" in str(m) for m in messages))

        # Fill par1 -> transfer succeeds
        gc = group.customizers.first()
        gc.par1 = 'זכוכית מחוסמת 8 מ"מ'
        gc.save()

        resp_success = self.client.post(url, follow=True)
        self.assertEqual(resp_success.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.IN_PRODUCTION)


class CompletionProductionServiceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='admin_completion', password='password123', role='ADMIN')
        self.client.force_login(self.user)

        self.pt = ProductType.objects.create(
            code='INT_DOOR', name='Interior Door with Frame',
            has_door=True, has_frame=True
        )
        self.pf = ProductFamily.objects.create(
            product_type=self.pt, code='FAM_COMPL', name='Flush Doors Compl'
        )
        self.series = Series.objects.create(code='SR_COMPL', name='Series Compl')
        self.front = Front.objects.create(series=self.series, code='FR_COMPL', name='Wood Veneer')
        self.handle = Handle.objects.create(code='HD_COMPL', name='Magnetic Handle')
        self.product = ProductModel.objects.create(
            code='MD_COMPL', name='Model Compl', product_family=self.pf, series=self.series
        )

        self.order = Order.objects.create(
            order_number='ORD-COMPL-001',
            customer='Completion Client',
            series=self.series,
            front=self.front,
            handle=self.handle,
            status=OrderStatus.PHASE2_READY
        )

        # Group 1: Initial completed group
        self.group1 = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=self.series,
            front=self.front,
            quantity=1,
            production_state=OrderItemsGroup.ProductionState.COMPLETED
        )
        self.item1 = self.group1.items.first()
        self.item1.height = 2050
        self.item1.width = 850
        self.item1.wall = 120
        self.item1.opening = 'LEFT'
        self.item1.direction = 'IN'
        self.item1.save()

    def test_group_lifecycle_and_completion_production_transfer(self):
        """
        Tests the entire completion workflow:
        1. Adding a new group (WAITING).
        2. Transferring to completion production.
        3. Snapshot creation (PHASE2_COMPLETION) and phase2_spec_cache update.
        4. Delta items in CNC / reports.
        5. Completion of production sets state to COMPLETED.
        """
        # 1. Add secondary group for completions (e.g. wall cladding / extra door)
        group2 = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=self.series,
            front=self.front,
            quantity=1,
            production_state=OrderItemsGroup.ProductionState.WAITING
        )
        item2 = group2.items.first()
        item2.height = 2100
        item2.width = 900
        item2.wall = 150
        item2.opening = 'RIGHT'
        item2.direction = 'OUT'
        item2.save()

        self.assertEqual(group2.production_state, OrderItemsGroup.ProductionState.WAITING)
        self.assertEqual(self.group1.production_state, OrderItemsGroup.ProductionState.COMPLETED)

        # 2. Transfer to completion production
        url = reverse('production:order-transfer-to-completion-production', args=[self.order.pk])
        resp = self.client.post(url, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.order.refresh_from_db()
        group2.refresh_from_db()
        self.group1.refresh_from_db()

        self.assertEqual(self.order.status, OrderStatus.COMPLETION_PRODUCTION)
        self.assertEqual(group2.production_state, OrderItemsGroup.ProductionState.IN_PRODUCTION)
        self.assertEqual(self.group1.production_state, OrderItemsGroup.ProductionState.COMPLETED)

        # 3. Verify snapshot creation
        from apps.production.models import OrderSpecificationSnapshot
        snapshots = self.order.specification_snapshots.filter(
            snapshot_type=OrderSpecificationSnapshot.SnapshotType.PHASE2_COMPLETION
        )
        self.assertEqual(snapshots.count(), 1)
        snapshot = snapshots.first()
        # Snapshot contains only delta items (item2)
        snapshot_item_ids = [it['item_id'] for it in snapshot.spec_data.get('items', [])]
        self.assertIn(item2.id, snapshot_item_ids)
        self.assertNotIn(self.item1.id, snapshot_item_ids)

        # 4. Check filtered items in ProductionDataService
        service = ProductionDataService(self.order)
        filtered_items = service.get_filtered_items()
        filtered_ids = [it.id for it in filtered_items]
        self.assertIn(item2.id, filtered_ids)
        self.assertNotIn(self.item1.id, filtered_ids)

        # 5. Complete production
        complete_url = reverse('production:order-complete-production', args=[self.order.pk])
        resp_comp = self.client.post(complete_url, follow=True)
        self.assertEqual(resp_comp.status_code, 200)

        self.order.refresh_from_db()
        group2.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.READY)
        self.assertEqual(group2.production_state, OrderItemsGroup.ProductionState.COMPLETED)

    def test_group_toggle_state(self):
        """Test unfreezing completed group back to WAITING."""
        url = reverse('production:group-toggle-state', args=[self.order.pk, self.group1.pk])
        resp = self.client.post(url, {'state': 'WAITING'}, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.group1.refresh_from_db()
        self.assertEqual(self.group1.production_state, OrderItemsGroup.ProductionState.WAITING)
