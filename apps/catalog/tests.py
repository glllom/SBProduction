from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.production.models import BOM
from .models import ProductType, ProductFamily, Series, Front, Color, ProductModel, Customizer, Material
from .serializers import (
    SeriesSerializer, FrontSerializer, FrameColorSerializer, ProductFamilySerializer,
    ProductModelSerializer, CustomizerSerializer
)


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
        self.frame_color1 = Color.objects.create(
            name='לבן', code='WHITE', description='White matte frame'
        )
        self.frame_color2 = Color.objects.create(
            name='שחור', code='BLACK', description='Black matte frame'
        )
        self.mat1 = Material.objects.create(
            name='משקוף ליין לבן', common_name='משקוף ליין', color=self.frame_color1, sku='MAT-1'
        )
        self.mat2 = Material.objects.create(
            name='משקוף ליין שחור', common_name='משקוף ליין', color=self.frame_color2, sku='MAT-2'
        )
        self.bom = BOM.objects.create(product=self.pm, frame=self.mat1)

    def test_frame_color_api_and_serializer(self):
        fc_data = FrameColorSerializer(self.frame_color1).data
        self.assertEqual(fc_data['name'], 'לבן')
        self.assertEqual(fc_data['description'], 'White matte frame')

        # Test API endpoint filtering by series
        other_series = Series.objects.create(code='S200', name='Series 200')
        other_color = Color.objects.create(name='אנודייז')
        other_mat = Material.objects.create(name='משקוף אחר', common_name='משקוף אחר', color=other_color, sku='MAT-3')
        other_pm = ProductModel.objects.create(code='MDL-2', name='Other Model', product_family=self.pf,
                                               series=other_series)
        BOM.objects.create(product=other_pm, frame=other_mat)

        resp = self.client.get(f'/catalog/api/frame-colors/?series={self.series.id}')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data if isinstance(data, list) else data.get('results', [])
        self.assertEqual(len(results), 2)
        names = [r['name'] for r in results]
        self.assertIn('לבן', names)
        self.assertIn('שחור', names)
        self.assertNotIn('אנודייז', names)

        # Test API endpoint filtering by product
        resp_prod = self.client.get(f'/catalog/api/frame-colors/?product={self.pm.id}')
        self.assertEqual(resp_prod.status_code, 200)
        data_prod = resp_prod.json()
        results_prod = data_prod if isinstance(data_prod, list) else data_prod.get('results', [])
        self.assertEqual(len(results_prod), 2)

        # Test ProductModelSerializer includes frame_colors
        pm_data = ProductModelSerializer(self.pm).data
        self.assertIn('frame_colors', pm_data)
        pm_color_names = [c['name'] for c in pm_data['frame_colors']]
        self.assertIn('לבן', pm_color_names)
        self.assertIn('שחור', pm_color_names)

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


class SeriesSpecificFrameColorsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='seriesadmin', password='password123', role='ADMIN')
        self.client.force_login(self.user)

        self.pt = ProductType.objects.create(code='PT_DOOR', name='Doors')
        self.pf = ProductFamily.objects.create(product_type=self.pt, code='PF_FLUSH', name='Flush')

        # Colors
        self.color_white = Color.objects.create(id=1, name='לבן', code='white')
        self.color_black = Color.objects.create(id=2, name='שחור', code='black')
        self.color_anodize = Color.objects.create(id=3, name='אנודייז', code='anodized')

        # Series LINEA (has 3 colors: white, black, anodized)
        self.series_linea = Series.objects.create(code='LINEA', name='LINEA')
        self.pm_linea = ProductModel.objects.create(
            code='PM_LINEA', name='Door LINEA', product_family=self.pf, series=self.series_linea
        )
        self.mat_linea_w = Material.objects.create(
            name='משקוף ליין לבן', common_name='משקוף ליין', color=self.color_white, sku='MAT-L-W'
        )
        self.mat_linea_b = Material.objects.create(
            name='משקוף ליין שחור', common_name='משקוף ליין', color=self.color_black, sku='MAT-L-B'
        )
        self.mat_linea_a = Material.objects.create(
            name='משקוף ליין אנודייז', common_name='משקוף ליין', color=self.color_anodize, sku='MAT-L-A'
        )
        self.bom_linea = BOM.objects.create(product=self.pm_linea, frame=self.mat_linea_w)

        # Series MONOLITH (has 1 color: black only)
        self.series_monolith = Series.objects.create(code='MONOLITH', name='MONOLITH')
        self.pm_monolith = ProductModel.objects.create(
            code='PM_MONO', name='Door MONOLITH', product_family=self.pf, series=self.series_monolith
        )
        self.mat_mono_b = Material.objects.create(
            name='משקוף מונולית שחור', common_name='', color=self.color_black, sku='MAT-M-B'
        )
        self.bom_monolith = BOM.objects.create(product=self.pm_monolith, frame=self.mat_mono_b)

    def test_series_frame_colors_property(self):
        # LINEA should return white, black, anodized
        linea_colors = list(self.series_linea.frame_colors)
        self.assertEqual(len(linea_colors), 3)
        self.assertEqual(set(c.id for c in linea_colors), {1, 2, 3})

        # MONOLITH should return only black
        mono_colors = list(self.series_monolith.frame_colors)
        self.assertEqual(len(mono_colors), 1)
        self.assertEqual(mono_colors[0].id, 2)

    def test_frame_colors_api_returns_series_colors(self):
        # GET /catalog/api/frame-colors/?series=LINEA.id
        resp = self.client.get(f'/catalog/api/frame-colors/?series={self.series_linea.id}')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data if isinstance(data, list) else data.get('results', [])
        self.assertEqual(len(results), 3)
        result_ids = [r['id'] for r in results]
        self.assertEqual(result_ids, [1, 2, 3])

        # GET /catalog/api/frame-colors/?series=MONOLITH.id
        resp = self.client.get(f'/catalog/api/frame-colors/?series={self.series_monolith.id}')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        results = data if isinstance(data, list) else data.get('results', [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 2)
        self.assertEqual(results[0]['name'], 'שחור')
