from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from apps.accounts.models import User
from .models import ProductType, ProductFamily, Series, Front, ProductModel, Customizer
from .serializers import SeriesSerializer, FrontSerializer, ProductFamilySerializer, ProductModelSerializer, CustomizerSerializer


class CatalogTooltipTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testadmin', password='password123', role='ADMIN')
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
        self.pm = ProductModel.objects.create(
            code='MDL-1', name='Standard Flush Door', product_family=self.pf, series=self.series,
            description='Standard door model 1'
        )
        self.cust = Customizer.objects.create(
            code='CUST-H1', name='Concealed Hinges', tag='hinge', priority=100,
            description='Premium 3D adjustable concealed hinges',
            par1_label='Hinge Count', par1_hint='Number of hinges from 2 to 5', par1_value='3'
        )

    def test_serializers_contain_description_and_hints(self):
        s_data = SeriesSerializer(self.series).data
        self.assertEqual(s_data['description'], 'Standard hidden aluminum frame series')

        f_data = FrontSerializer(self.front).data
        self.assertEqual(f_data['description'], 'Matte white finish front')

        pf_data = ProductFamilySerializer(self.pf).data
        self.assertEqual(pf_data['description'], 'Flat flush door models')

        pm_data = ProductModelSerializer(self.pm).data
        self.assertEqual(pm_data['description'], 'Standard door model 1')

        c_data = CustomizerSerializer(self.cust).data
        self.assertEqual(c_data['description'], 'Premium 3D adjustable concealed hinges')
        self.assertEqual(c_data['par1_hint'], 'Number of hinges from 2 to 5')

    def test_catalog_list_views_render_tooltips(self):
        # Series list view
        resp = self.client.get(reverse('catalog:series-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-bs-toggle="tooltip"')
        self.assertContains(resp, 'Standard hidden aluminum frame series')

        # Family list view
        resp = self.client.get(reverse('catalog:family-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-bs-toggle="tooltip"')
        self.assertContains(resp, 'Flat flush door models')

        # Model list view
        resp = self.client.get(reverse('catalog:model-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-bs-toggle="tooltip"')
        self.assertContains(resp, 'Standard door model 1')

        # Customizer list view
        resp = self.client.get(reverse('catalog:customizer-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-bs-toggle="tooltip"')
        self.assertContains(resp, 'Premium 3D adjustable concealed hinges')
