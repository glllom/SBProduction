from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import UserRole
from apps.catalog.models import ProductType, ProductFamily, Series, Front, Material, ProductModel, Customizer
from apps.orders.models import (
    Order, OrderItemsGroup, OrderItem, OrderItemsGroupCustomizer,
    GroupSpecification, OrderStatus, OpeningSide, OpeningType
)

User = get_user_model()


class GroupDuplicationAndSpecificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='password123',
            role=UserRole.USER
        )
        self.admin_user = User.objects.create_user(
            username='adminuser',
            email='admin@example.com',
            password='password123',
            role=UserRole.ADMIN
        )
        self.client.login(username='testuser', password='password123')

        # Catalog setup
        self.product_type = ProductType.objects.create(
            code='INTERIOR',
            name='דלתות פנים',
            has_door=True,
            has_frame=True
        )
        self.product_family = ProductFamily.objects.create(
            product_type=self.product_type,
            name='משפחה 1',
            code='FAM1',
            default_value_for_frame='100'
        )
        self.series = Series.objects.create(
            name='סדרה 100',
            code='SER100'
        )
        self.front = Front.objects.create(
            series=self.series,
            name='חזית פורמייקה'
        )
        self.material_frame = Material.objects.create(
            name='אלומיניום שחור',
            sku='MAT_ALU_BLK',
            material_type='FRAME'
        )
        self.product = ProductModel.objects.create(
            product_family=self.product_family,
            series=self.series,
            name='דגם לייט 100',
            code='LIGHT100'
        )
        self.customizer = Customizer.objects.create(
            name='מנעול מגנטי',
            code='MAG_LOCK',
            par1_label='סוג לשונית'
        )
        self.customizer.product_families.add(self.product_family)

        # Order setup
        self.order = Order.objects.create(
            order_number='ORD-1001',
            customer='לקוח בדיקה',
            series=self.series,
            front=self.front,
            status=OrderStatus.NEW
        )

        # Group setup
        self.group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=self.series,
            front=self.front,
            basic_color_frames=self.material_frame,
            panel_paint_option=OrderItemsGroup.PaintOption.SPECIAL_COLOR,
            color_panels='RAL 9005',
            frame_paint_option=OrderItemsGroup.PaintOption.MAIN_COLOR,
            color_frames='RAL 7016',
            is_split_installation=True,
            quantity=2,
            comments='הערה לקבוצה'
        )

        # Customizer setup for group
        self.group_cust = OrderItemsGroupCustomizer.objects.create(
            group=self.group,
            customizer=self.customizer,
            par1='לשונית שקטה'
        )

        # Fill in measurements for the existing items
        items = list(self.group.items.all().order_by('id'))
        self.assertEqual(len(items), 2)
        items[0].width = 800
        items[0].height = 2050
        items[0].direction = OpeningSide.LEFT
        items[0].opening = OpeningType.IN
        items[0].custom_lock_height = 1050
        items[0].save()

        items[1].width = 900
        items[1].height = 2100
        items[1].direction = OpeningSide.RIGHT
        items[1].opening = OpeningType.OUT
        items[1].custom_lock_height = 1050
        items[1].save()

    def test_group_duplicate_method(self):
        """Test model method duplicate() copies parameters & customizers, but creates blank items."""
        duplicated_group = self.group.duplicate()

        self.assertNotEqual(duplicated_group.id, self.group.id)
        self.assertEqual(duplicated_group.order, self.order)
        self.assertEqual(duplicated_group.product, self.group.product)
        self.assertEqual(duplicated_group.series, self.group.series)
        self.assertEqual(duplicated_group.front, self.group.front)
        self.assertEqual(duplicated_group.basic_color_frames, self.group.basic_color_frames)
        self.assertEqual(duplicated_group.panel_paint_option, self.group.panel_paint_option)
        self.assertEqual(duplicated_group.color_panels, 'RAL 9005')
        self.assertEqual(duplicated_group.is_split_installation, True)
        self.assertEqual(duplicated_group.comments, 'הערה לקבוצה')

        # Check customizers are duplicated
        self.assertEqual(duplicated_group.customizers.count(), 1)
        dup_cust = duplicated_group.customizers.first()
        self.assertEqual(dup_cust.customizer, self.customizer)
        self.assertEqual(dup_cust.par1, 'לשונית שקטה')

        # Check that items in duplicated group are created as EMPTY positions
        dup_items = duplicated_group.items.all().order_by('id')
        self.assertEqual(dup_items.count(), 2)
        for item in dup_items:
            self.assertIsNone(item.width)
            self.assertIsNone(item.height)
            self.assertIn(item.direction, [None, ''])
            self.assertIn(item.opening, [None, ''])
            self.assertIsNone(item.custom_lock_height)
            # Wall should have default from product family
            self.assertEqual(item.wall, 100)

        # Marks across order should be numbered 1, 2, 3, 4
        all_marks = list(
            OrderItem.objects.filter(group__order=self.order).order_by('group__id', 'id').values_list('mark',
                                                                                                      flat=True))
        self.assertEqual(all_marks, ['1', '2', '3', '4'])

    def test_group_duplicate_view(self):
        """Test HTTP POST endpoint for group duplicate."""
        url = reverse('group-duplicate', kwargs={'pk': self.group.pk})
        response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        new_group_id = data['new_group_id']
        self.assertTrue(OrderItemsGroup.objects.filter(id=new_group_id).exists())

    def test_save_group_specification(self):
        """Test saving group as preset / specification."""
        url = reverse('group-save-specification', kwargs={'pk': self.group.pk})
        response = self.client.post(
            url,
            data={'name': 'מפרט פרויקט משרדים', 'description': 'דלתות קומה 2'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        spec_id = data['spec_id']

        spec = GroupSpecification.objects.get(id=spec_id)
        self.assertEqual(spec.name, 'מפרט פרויקט משרדים')
        self.assertEqual(spec.description, 'דלתות קומה 2')
        self.assertEqual(spec.product, self.product)
        self.assertEqual(spec.series, self.series)
        self.assertEqual(spec.front, self.front)
        self.assertEqual(spec.panel_paint_option, OrderItemsGroup.PaintOption.SPECIAL_COLOR)
        self.assertEqual(spec.color_panels, 'RAL 9005')
        self.assertEqual(spec.is_split_installation, True)
        self.assertEqual(spec.created_by, self.user)

        # Customizers attached
        self.assertEqual(spec.customizers.count(), 1)
        spec_cust = spec.customizers.first()
        self.assertEqual(spec_cust.customizer, self.customizer)
        self.assertEqual(spec_cust.par1, 'לשונית שקטה')

    def test_save_specification_validation(self):
        """Test saving specification requires name."""
        url = reverse('group-save-specification', kwargs={'pk': self.group.pk})
        response = self.client.post(url, data={'name': ''}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)

    def test_apply_group_specification(self):
        """Test applying a saved specification onto an existing group."""
        spec = GroupSpecification.create_from_group(
            group=self.group,
            name='מפרט בדיקה',
            user=self.user
        )

        # Create another group with different settings
        other_group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=None,
            front=None,
            quantity=1
        )
        self.assertEqual(other_group.customizers.count(), 0)

        # Apply spec to other_group
        url = reverse('group-apply-specification', kwargs={'pk': other_group.pk, 'spec_pk': spec.pk})
        response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)

        other_group.refresh_from_db()
        self.assertEqual(other_group.series, self.series)
        self.assertEqual(other_group.front, self.front)
        self.assertEqual(other_group.color_panels, 'RAL 9005')
        self.assertEqual(other_group.customizers.count(), 1)
        self.assertEqual(other_group.customizers.first().par1, 'לשונית שקטה')

    def test_create_group_from_specification(self):
        """Test creating a brand new group in an order from a saved specification."""
        spec = GroupSpecification.create_from_group(
            group=self.group,
            name='מפרט שמור',
            user=self.user
        )

        url = reverse('group-create-from-specification', kwargs={'order_pk': self.order.pk, 'spec_pk': spec.pk})
        response = self.client.post(url, data={'quantity': 3}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        new_group_id = data['new_group_id']

        new_group = OrderItemsGroup.objects.get(id=new_group_id)
        self.assertEqual(new_group.quantity, 3)
        self.assertEqual(new_group.items.count(), 3)
        self.assertEqual(new_group.customizers.count(), 1)
        self.assertEqual(new_group.product, self.product)
        self.assertEqual(new_group.series, self.series)

    def test_delete_specification(self):
        """Test deleting a specification."""
        spec = GroupSpecification.create_from_group(
            group=self.group,
            name='מפרט למחיקה',
            user=self.user
        )
        url = reverse('specification-delete', kwargs={'pk': spec.pk})
        response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GroupSpecification.objects.filter(id=spec.pk).exists())

    def test_specifications_api(self):
        """Test DRF API endpoint for listing specifications."""
        spec = GroupSpecification.create_from_group(
            group=self.group,
            name='מפרט API',
            user=self.user
        )
        url = '/orders/api/specifications/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        results = response.json()
        self.assertTrue(any(s['id'] == spec.id for s in results))
        item = next(s for s in results if s['id'] == spec.id)
        self.assertEqual(item['name'], 'מפרט API')
        self.assertEqual(item['product_name'], self.product.name)
        self.assertEqual(len(item['customizers']), 1)
        self.assertEqual(item['customizers'][0]['customizer_name'], 'מנעול מגנטי')

    def test_permissions_in_production(self):
        """Test non-admin cannot duplicate or modify groups when order is IN_PRODUCTION."""
        self.order.status = OrderStatus.IN_PRODUCTION
        self.order.save()

        # Non-admin duplicate attempt -> 403
        url = reverse('group-duplicate', kwargs={'pk': self.group.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

        # Admin duplicate attempt -> success
        self.client.login(username='adminuser', password='password123')
        response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)


class OrderStatusManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username='adminuser',
            email='admin@example.com',
            password='password123',
            role=UserRole.ADMIN
        )
        self.regular_user = User.objects.create_user(
            username='regularuser',
            email='user@example.com',
            password='password123',
            role=UserRole.USER
        )
        self.order = Order.objects.create(
            order_number='ORD-MGMT-TEST',
            status=OrderStatus.IN_PRODUCTION
        )

    def test_admin_can_reset_status(self):
        self.client.login(username='adminuser', password='password123')
        url = reverse('order-reset-to-new', kwargs={'pk': self.order.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.NEW)

        # Check changelog
        from apps.orders.models import OrderChangeLog
        self.assertTrue(OrderChangeLog.objects.filter(
            order=self.order,
            field_name='status',
            new_value=OrderStatus.NEW
        ).exists())

    def test_regular_user_cannot_reset_status(self):
        self.client.login(username='regularuser', password='password123')
        url = reverse('order-reset-to-new', kwargs={'pk': self.order.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)  # PermissionDenied
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.IN_PRODUCTION)

    def test_admin_can_cancel_order(self):
        self.client.login(username='adminuser', password='password123')
        url = reverse('order-cancel', kwargs={'pk': self.order.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELED)

        # Check changelog
        from apps.orders.models import OrderChangeLog
        self.assertTrue(OrderChangeLog.objects.filter(
            order=self.order,
            field_name='status',
            new_value=OrderStatus.CANCELED
        ).exists())

    def test_regular_user_cannot_cancel_order(self):
        self.client.login(username='regularuser', password='password123')
        url = reverse('order-cancel', kwargs={'pk': self.order.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.IN_PRODUCTION)


class RequiredCustomizersOrderTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='custmgr', email='mgr@example.com', password='password123', role=UserRole.USER
        )
        self.client.login(username='custmgr', password='password123')

        self.pt = ProductType.objects.create(code='PT1', name='Type 1', has_door=True, has_frame=True)
        self.pf = ProductFamily.objects.create(product_type=self.pt, code='PF1', name='Family 1')
        self.series = Series.objects.create(code='SR1', name='Series 1')
        self.front = Front.objects.create(series=self.series, code='FR1', name='Front 1')
        self.product = ProductModel.objects.create(
            product_family=self.pf, series=self.series, code='PR1', name='Product 1'
        )

        self.order = Order.objects.create(
            order_number='ORD-REQ-CUST',
            customer='Customer Test',
            series=self.series,
            front=self.front,
            status=OrderStatus.NEW
        )

    def test_product_get_required_customizers_sources(self):
        """Test ProductModel.get_required_customizers combines direct M2M, BOM M2M, and is_required=True."""
        from apps.production.models import BOM

        # 1. Direct product required customizer
        c1 = Customizer.objects.create(code='CUST1', name='Cust 1', tag='tag1')
        self.product.required_customizers.add(c1)

        # 2. BOM required customizer
        c2 = Customizer.objects.create(code='CUST2', name='Cust 2', tag='tag2')
        bom = BOM.objects.create(product=self.product)
        bom.required_customizers.add(c2)

        # 3. Customizer with is_required=True scoped to product family
        c3 = Customizer.objects.create(code='CUST3', name='Cust 3', tag='tag3', is_required=True)
        c3.product_families.add(self.pf)

        # 4. Customizer with is_required=True global (no families, types, models)
        c4 = Customizer.objects.create(code='CUST4', name='Cust 4', tag='tag4', is_required=True)

        # 5. Non-required customizer (should not be returned)
        c5 = Customizer.objects.create(code='CUST5', name='Cust 5', tag='tag5', is_required=False)
        c5.product_families.add(self.pf)

        req_custs = list(self.product.get_required_customizers())
        req_ids = {c.id for c in req_custs}

        self.assertIn(c1.id, req_ids)
        self.assertIn(c2.id, req_ids)
        self.assertIn(c3.id, req_ids)
        self.assertIn(c4.id, req_ids)
        self.assertNotIn(c5.id, req_ids)

    def test_group_creation_auto_populates_required_customizers_with_empty_required_params(self):
        """
        When a group is created, required customizers are automatically added to group.customizers.
        Required parameters (parX_required=True) are set to empty ('').
        Non-required parameters retain default values.
        """
        cust_glass = Customizer.objects.create(
            code='GLASS_TYPE',
            name='סוג זכוכית',
            tag='glass',
            is_required=True,
            par1_label='סוג זכוכית',
            par1_required=True,
            par1_value='שקופה',  # Default in catalog, but since it's required it should become '' on auto-population
            par2_label='הערות',
            par2_required=False,
            par2_value='סטנדרט'
        )
        cust_glass.product_models.add(self.product)

        # Create group
        group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=self.series,
            front=self.front,
            quantity=1
        )

        group_custs = group.customizers.all()
        self.assertEqual(group_custs.count(), 1)
        gc = group_custs.first()
        self.assertEqual(gc.customizer, cust_glass)
        # Required parameter must be empty
        self.assertEqual(gc.par1, '')
        # Non-required parameter takes default value
        self.assertEqual(gc.par2, 'סטנדרט')

    def test_group_duplicate_preserves_customizers(self):
        """Duplicating a group preserves filled customizer parameters without duplicate entries."""
        cust = Customizer.objects.create(
            code='REQ_CUST',
            name='קסטומייזר חובה',
            is_required=True,
            par1_label='פרמטר 1',
            par1_required=True,
            par1_value='Default'
        )
        self.product.required_customizers.add(cust)

        group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            series=self.series,
            front=self.front,
            quantity=1
        )

        # Manager fills in the required parameter
        gc = group.customizers.get(customizer=cust)
        gc.par1 = 'Filled Value by Manager'
        gc.save()

        # Duplicate the group
        dup_group = group.duplicate()
        self.assertEqual(dup_group.customizers.count(), 1)
        dup_gc = dup_group.customizers.first()
        self.assertEqual(dup_gc.customizer, cust)
        self.assertEqual(dup_gc.par1, 'Filled Value by Manager')

    def test_customizer_serializer_fields(self):
        """Serializer outputs is_required and parameter required flags."""
        from apps.orders.serializers import OrderItemsGroupCustomizerSerializer
        cust = Customizer.objects.create(
            code='SERIAL_CUST',
            name='בדיקת סריאליזציה',
            is_required=True,
            par1_label='P1',
            par1_required=True,
            par2_label='P2',
            par2_required=False
        )
        group = OrderItemsGroup.objects.create(
            order=self.order,
            product=self.product,
            quantity=1
        )
        gc = group.customizers.first()
        data = OrderItemsGroupCustomizerSerializer(gc).data

        self.assertTrue(data['customizer_is_required'])
        self.assertTrue(data['par1_required'])
        self.assertFalse(data['par2_required'])
