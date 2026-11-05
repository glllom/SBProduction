from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.urls import reverse
from unittest.mock import patch

from apps.orders.models import Order, OrderStatus
from apps.production.models import ProductionStation

User = get_user_model()


class MasterReportTemplateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testmaster', password='password123')
        self.client.login(username='testmaster', password='password123')
        self.order = Order.objects.create(
            order_number='ORD-TEST-PRINT-001',
            customer='Israel Israeli',
            status=OrderStatus.NEW
        )

    def test_base_report_template_elements(self):
        """Проверка наличия базового шаблона с кнопками Печать и Отмена"""
        content = render_to_string('production/reports/base_report.html', {
            'order': self.order
        })
        self.assertIn('window.print()', content)
        self.assertIn('window.close()', content)
        self.assertIn('no-print', content)

    def test_master_report_template_rendering(self):
        """Проверка рендеринга мастер-отчета с базовым шаблоном и разрывом страниц"""
        sections = [
            {
                'station_code': 'FRAMES',
                'report_label': 'משקופים',
                'include_template': 'production/includes/report_alum_frames.html',
                'order_spec': None,
                'groups_data': [],
                'enriched_frames_items': [],
                'enriched_doors_items': [],
            },
            {
                'station_code': 'DOORS',
                'report_label': 'דלתות',
                'include_template': 'production/includes/report_alum_doors.html',
                'order_spec': None,
                'groups_data': [],
                'enriched_frames_items': [],
                'enriched_doors_items': [],
            }
        ]
        content = render_to_string('production/reports/master_report.html', {
            'order': self.order,
            'sections': sections,
            'stage_label': 'שלב א',
        })
        self.assertIn('window.print()', content)
        self.assertIn('window.close()', content)
        self.assertIn('מאסטר דו\'\'ח ייצור', content)

    def test_individual_reports_extend_base(self):
        """Проверка, что отдельные шаблоны отчетов содержат кнопки управления печатью и контент"""
        report_templates = [
            'production/reports/alum_frames_report.html',
            'production/reports/alum_doors_report.html',
            'production/reports/cut_sheets_report.html',
            'production/reports/report_facing.html',
            'production/reports/report_press.html',
            'production/reports/report_wood_frames.html',
            'production/reports/report_warehouse_hardware.html',
            'production/reports/split_measurer_report.html',
            'production/reports/order_sketches_report.html',
        ]
        for tmpl in report_templates:
            content = render_to_string(tmpl, {
                'order': self.order,
                'batches_label': 'הכל',
            })
            self.assertIn('window.print()', content, f"Template {tmpl} missing print button")
            self.assertIn('window.close()', content, f"Template {tmpl} missing close/cancel button")

    def test_portrait_orientation_in_reports(self):
        """Проверка портретной ориентации для отчетов пресса и деревянных коробок"""
        portrait_templates = [
            'production/reports/report_press.html',
            'production/reports/report_wooden_frames.html',
            'production/reports/report_wood_frames.html',
        ]
        for tmpl in portrait_templates:
            content = render_to_string(tmpl, {
                'order': self.order,
                'batches_label': 'הכל',
            })
            self.assertIn('portrait', content, f"Template {tmpl} missing portrait class/style")
            self.assertIn('size: A4 portrait', content, f"Template {tmpl} missing @page size: A4 portrait")

    def test_landscape_orientation_in_reports(self):
        """Проверка альбомной ориентации для отчетов алюминиевых дверей, משקופים и раскроя листов"""
        landscape_templates = [
            'production/reports/alum_doors_report.html',
            'production/reports/alum_frames_report.html',
            'production/reports/cut_sheets_report.html',
        ]
        for tmpl in landscape_templates:
            content = render_to_string(tmpl, {
                'order': self.order,
                'batches_label': 'הכל',
            })
            self.assertIn('landscape', content, f"Template {tmpl} missing landscape class/style")
            self.assertIn('size: A4 landscape', content, f"Template {tmpl} missing @page size: A4 landscape")

    def test_master_report_mixed_orientations(self):
        """Проверка смешанной ориентации (портретной и альбомной) в мастер-отчете"""
        sections = [
            {
                'station_code': 'PRESS',
                'report_label': 'פרס',
                'include_template': 'production/includes/report_press.html',
                'order_spec': None,
                'groups_data': [],
                'is_portrait': True,
            },
            {
                'station_code': 'DOORS',
                'report_label': 'דלתות אלומיניום',
                'include_template': 'production/includes/report_alum_doors.html',
                'order_spec': None,
                'groups_data': [],
                'is_portrait': False,
            }
        ]
        content = render_to_string('production/reports/master_report.html', {
            'order': self.order,
            'sections': sections,
            'stage_label': 'שלב א',
        })
        self.assertIn('page mb-4 portrait', content)
        self.assertIn('page mb-4 landscape', content)

    def test_split_measurer_report_standalone(self):
        """Проверка, что отчет замерщика изолирован и имеет собственные стили"""
        content = render_to_string('production/reports/split_measurer_report.html', {
            'order': self.order,
        })
        self.assertIn('window.print()', content)
        self.assertIn('window.close()', content)
        self.assertIn('דו\'\'ח למדידה', content)

    @patch('apps.production.services.OrderValidationService.validate_for_report')
    @patch('apps.production.services.TechnicalSpecService.get_or_build_spec')
    def test_station_report_master_portrait_detection(self, mock_get_spec, mock_validate):
        """Проверка корректности определения портретной ориентации в представлении station_report"""
        from apps.production.services import ValidationResult
        val_res = ValidationResult(is_valid=True, errors=[])
        mock_validate.return_value = val_res
        mock_get_spec.return_value = (None, False)

        press_station = ProductionStation.objects.create(
            name='פרס', code='PRESS', label='פרס', template_name='production/reports/report_press.html', active=True, has_specification=True
        )
        wood_frames_station = ProductionStation.objects.create(
            name='משקופים', code='FRAMES', label='משקופים', template_name='production/reports/report_wood_frames.html', active=True, has_specification=True
        )
        alum_doors_station = ProductionStation.objects.create(
            name='דלתות', code='alum_doors', label='דלתות', template_name='production/reports/alum_doors_report.html', active=True, has_specification=True
        )

        response = self.client.get(reverse('production:station-report', kwargs={'pk': self.order.id}) + "?station=ALL")
        self.assertEqual(response.status_code, 200)
        sections = response.context['sections']
        
        sec_map = {s['station_code']: s for s in sections}
        if 'PRESS' in sec_map:
            self.assertTrue(sec_map['PRESS']['is_portrait'])
            self.assertEqual(sec_map['PRESS']['include_template'], 'production/includes/report_press.html')
        if 'FRAMES' in sec_map:
            self.assertTrue(sec_map['FRAMES']['is_portrait'])
            self.assertEqual(sec_map['FRAMES']['include_template'], 'production/includes/report_wood_frames.html')
        if 'alum_doors' in sec_map:
            self.assertFalse(sec_map['alum_doors']['is_portrait'])
            self.assertEqual(sec_map['alum_doors']['include_template'], 'production/includes/report_alum_doors.html')
