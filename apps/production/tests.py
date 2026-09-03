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
        self.assertEqual(order.status, OrderStatus.IN_PRODUCTION_PHASE1)

        # start_production without handle should NOT raise ValueError if in Phase 1 and split
        # because it only does partial validation
        OrderProductionService.start_production(order, user=self.user)
        self.assertEqual(order.status, OrderStatus.IN_PRODUCTION_PHASE1)

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
        self.assertEqual(order.status, OrderStatus.IN_PRODUCTION_PHASE2)


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
            status=OrderStatus.IN_PRODUCTION_PHASE1
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
        self.assertEqual(order.status, OrderStatus.IN_PRODUCTION_PHASE1)

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
        self.pm = ProductModel.objects.create(code='PM3', name='Model 3', product_family=self.pf, series=self.series)

        self.s1 = ProductionStation.objects.create(name='Station 1', code='S1', label='Btn 1', has_specification=True)
        self.s2 = ProductionStation.objects.create(name='Station 2', code='S2', label='Btn 2', has_specification=True)
        self.s3 = ProductionStation.objects.create(name='Station 3', code='S3', label='Btn 3', has_specification=False)
        self.s_cust = ProductionStation.objects.create(name='Custom Station', code='SC', label='Btn C', has_specification=True)

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

        order = Order.objects.create(order_number='ORD-FILTER', customer='Customer', status=OrderStatus.IN_PRODUCTION)
        
        # Group 1 with PM3 (has S1)
        group1 = OrderItemsGroup.objects.create(order=order, product=self.pm, quantity=1)
        item1 = group1.items.first()
        item1.height = 2000; item1.width = 800; item1.wall = 120; item1.opening = 'L'; item1.direction = 'IN'; item1.save()

        # Group 2 with PM3 + customizer (has S1 + SC)
        group2 = OrderItemsGroup.objects.create(order=order, product=self.pm, quantity=1)
        item2 = group2.items.first()
        item2.height = 2000; item2.width = 800; item2.wall = 120; item2.opening = 'L'; item2.direction = 'IN'; item2.save()
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
        self.pm = ProductModel.objects.create(code='PM_PHASE', name='Phased Model', product_family=self.pf, series=self.series)

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
        order.status = OrderStatus.IN_PRODUCTION_PHASE1
        order.save()
        stations = order.get_production_stations()
        station_ids = [s.id for s in stations]
        self.assertIn(self.s_phase1.id, station_ids)
        self.assertNotIn(self.s_phase2.id, station_ids)
        self.assertEqual(len(stations), 1)

        # 3. PHASE2_PRODUCTION status - only phase 2 stations
        order.status = OrderStatus.IN_PRODUCTION_PHASE2
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
