"""
Сервисы жизненного цикла производства и подготовки данных для отчётов (apps.production.services).

Назначение модуля:
    - OrderProductionService: запуск заказа/батчей в производство, завершение фаз A и B.
    - ProductionDataService: фильтрация позиций по станциям и агрегация данных для
      печатных отчётов (пресс, деревянные коробки, алюминиевые рамы/двери, замеры, ZIP).
    - get_qr_base64: генерация SVG QR-кодов в Base64 для шапок печатных листов.

Примечание:
    Расчёт спецификаций, работа со снимками и валидация перенесены в пакет
    apps.production.engine и реэкспортируются здесь для совместимости со слоем views.
"""

from __future__ import annotations

import base64
import io
import os
import shutil
import zipfile
from collections import Counter, defaultdict
from datetime import date
from io import BytesIO
from typing import Optional

import qrcode
from django.conf import settings
from django.db import models, transaction
from django.template.loader import render_to_string
from django.utils import timezone
from qrcode.image.svg import SvgPathImage

from apps.catalog.models import Material
from apps.engineering.models import ProductionRoute, ProductionStation, SvgPattern
from apps.orders.models import OrderChangeLog, OrderItem, OrderItemsGroup, OrderStatus
from apps.production.engine import (  # noqa: F401 — реэкспорт для views.py
    OrderSpec,
    OrderValidationError,
    OrderValidationService,
    TechnicalSpecService,
    ValidationResult,
    ValidationType,
)
from apps.production.engine.calculators.geometry import round_press_dimension
from .models import OrderStationNote
from .tracking_services import StationTrackingService


def get_qr_base64(data: str) -> str:
    """Генерирует QR-код в формате Base64 SVG для вставки в HTML-отчёты."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)

    buffer = BytesIO()
    img = qr.make_image(image_factory=SvgPathImage)
    img.save(buffer)

    return base64.b64encode(buffer.getvalue()).decode('utf-8')


class ProductionDataService:
    """
    Сервис подготовки и агрегации данных спецификации для производственных отчётов и экспорта.
    """

    class ReportType(models.TextChoices):
        PHASE1_FRAMES = 'PHASE1_PRODUCTION', 'Phase A Frames'
        PHASE2_DOORS = 'PHASE2_DOORS', 'Phase B Doors'
        PHASE2_PRESS = 'PHASE2_PRESS', 'Press'
        PHASE2_FRAMES = 'PHASE2_FRAMES', 'Frames'
        IN_PRODUCTION = 'IN_PRODUCTION', 'Full Production Report'
        FULL_PRODUCTION = 'FULL_PRODUCTION', 'Full Production Report'

    def __init__(self, order):
        self.order = order

    def generate_production_zip(self) -> io.BytesIO:
        """Формирует ZIP-архив с HTML-отчётами и файлами ЧПУ после валидации заказа."""
        val_res = OrderValidationService.validate_for_zip(self.order)
        val_res.raise_if_invalid()

        buffer = io.BytesIO()
        has_split = getattr(self.order, 'has_split_installation', False)

        with zipfile.ZipFile(buffer, 'w') as zip_file:
            if has_split and self.order.status == OrderStatus.PHASE1_PRODUCTION:
                report_content = self.generate_report_html(self.ReportType.PHASE1_FRAMES, validate=False)
                zip_file.writestr(f"Order_{self.order.order_number}_PhaseA_Frames.html", report_content)
            elif self.order.status in (OrderStatus.IN_PRODUCTION, OrderStatus.PHASE1_READY):
                for rt in (
                        self.ReportType.PHASE2_DOORS,
                        self.ReportType.PHASE2_PRESS,
                        self.ReportType.PHASE2_FRAMES,
                ):
                    report_content = self.generate_report_html(rt, validate=False)
                    zip_file.writestr(f"Order_{self.order.order_number}_{rt.name}.html", report_content)
            else:
                report_content = self.generate_report_html(self.ReportType.FULL_PRODUCTION, validate=False)
                zip_file.writestr(f"Order_{self.order.order_number}_Full.html", report_content)

            self._add_cnc_files_to_zip(zip_file)

        buffer.seek(0)
        return buffer

    def _add_cnc_files_to_zip(self, zip_file) -> None:
        """Точка расширения для добавления ЧПУ-файлов в ZIP-архив."""
        pass

    def generate_cnc_files(self, spec_items=None, batch_number=None) -> None:
        """Генерирует структуру папок cnc_files/mecal/<order_number>/ на диске сервера."""
        is_phase_a = self.order.status == OrderStatus.PHASE1_PRODUCTION
        is_completion = self.order.status == OrderStatus.COMPLETION_PRODUCTION
        phase = 'phase1' if is_phase_a else 'phase2'

        if spec_items is not None:
            items_to_process = spec_items
        else:
            order_spec, _ = TechnicalSpecService.get_or_build_spec(self.order, phase=phase)
            if batch_number is not None:
                items_to_process = order_spec.batches.get(str(batch_number), [])
            else:
                items_to_process = [it for b_items in order_spec.batches.values() for it in b_items]

            if is_completion:
                active_item_ids = set(
                    OrderItem.objects.filter(group__order=self.order)
                    .exclude(group__production_state=OrderItemsGroup.ProductionState.COMPLETED)
                    .values_list('id', flat=True)
                )
                items_to_process = [it for it in items_to_process if it.item_id in active_item_ids]

        cnc_root = os.path.join(settings.BASE_DIR, 'cnc_files')
        mecal_dir = os.path.join(cnc_root, 'mecal')
        order_dir = os.path.join(mecal_dir, str(self.order.order_number))

        os.makedirs(mecal_dir, exist_ok=True)
        if os.path.exists(order_dir):
            shutil.rmtree(order_dir)
        os.makedirs(order_dir)

        frames_root = os.path.join(order_dir, 'frames')
        doors_root = os.path.join(order_dir, 'doors')
        os.makedirs(frames_root)
        os.makedirs(doors_root)

        for spec in items_to_process:
            mark = spec.mark
            if spec.has_frame:
                item_frame_dir = os.path.join(frames_root, f"frame_{mark}")
                os.makedirs(item_frame_dir, exist_ok=True)
                self._write_xml_files(item_frame_dir, spec, "frame")
            if spec.has_door:
                item_door_dir = os.path.join(doors_root, f"door_{mark}")
                os.makedirs(item_door_dir, exist_ok=True)
                self._write_xml_files(item_door_dir, spec, "door")

    @staticmethod
    def extract_report_items(spec_obj, requested_batches: list = None):
        """
        Извлекает плоский отсортированный по mark список позиций для запрошенных батчей.
        Если requested_batches пуст или None — возвращает (None, None).
        """
        if not requested_batches:
            return None, None

        batches_dict = getattr(spec_obj, 'batches', {}) or {}
        if not isinstance(batches_dict, dict):
            batches_dict = spec_obj.get('batches', {}) if isinstance(spec_obj, dict) else {}

        requested_strs = [str(b) for b in requested_batches]
        unique_items = {}
        applied_batches = []

        for b_num in requested_strs:
            if b_num in batches_dict:
                applied_batches.append(b_num)
                for item in batches_dict[b_num]:
                    item_id = getattr(item, 'item_id', None) if hasattr(item, 'item_id') else item.get('item_id')
                    unique_items[item_id or id(item)] = item

        if not unique_items:
            return [], ",".join(applied_batches)

        flat_items = list(unique_items.values())

        def parse_mark(it):
            mark = getattr(it, 'mark', None) if hasattr(it, 'mark') else it.get('mark')
            try:
                return int(mark)
            except (ValueError, TypeError):
                return 999999

        flat_items.sort(key=parse_mark)
        batches_label = "" if len(batches_dict) == 1 else ", ".join(applied_batches)
        return flat_items, batches_label

    @staticmethod
    def _extract_items(spec_or_items) -> list:
        """Распаковывает позиции из OrderSpec или возвращает переданный список."""
        if isinstance(spec_or_items, list):
            return spec_or_items
        batches = getattr(spec_or_items, 'batches', {}) or {}
        return [it for b in batches.values() for it in b]

    @staticmethod
    def _get(obj, key: str, default=None):
        """Унифицированное чтение поля из Pydantic-модели или словаря."""
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    def generate_measurement_report_html(self, validate: bool = True) -> str:
        """Генерирует HTML отчёта замеров (דוח מדידה) для активных батчей Фазы 1."""
        if validate:
            val_res = OrderValidationService.validate_for_report(self.order, report_type='PHASE1_FRAMES')
            val_res.raise_if_invalid()

        order_spec, _ = TechnicalSpecService.get_or_build_spec(self.order, phase='phase1')

        valid_groups = self.order.groups.filter(
            is_split_installation=True,
            batch_number__isnull=False,
        ).exclude(production_state=OrderItemsGroup.ProductionState.CANCELED)

        active_batch_numbers = list(valid_groups.values_list('batch_number', flat=True).distinct())
        if not active_batch_numbers:
            return ""

        flat_items, batches_label = self.extract_report_items(order_spec, requested_batches=active_batch_numbers)
        flat_items = flat_items or []

        context = {
            'order': self.order,
            'order_spec': order_spec,
            'spec_items': flat_items,
            'batches_label': batches_label,
            'groups_data': self.prepare_grouped_data(flat_items),
            'now': timezone.now(),
        }
        return render_to_string('production/alum_frames_report.html', context)

    @classmethod
    def get_wooden_frames_data(cls, spec_obj) -> list:
        """Возвращает плоский список деревянных коробок из спецификации."""
        frames_items = []
        for item in cls._extract_items(spec_obj):
            if not cls._get(item, 'has_frame', True) or cls._get(item, 'is_hidden_frame', False):
                continue

            frames_items.append({
                'mark': cls._get(item, 'mark', ''),
                'place': cls._get(item, 'place', '') or '',
                'opening_width': cls._get(item, 'opening_width') or cls._get(item, 'width', ''),
                'opening_height': cls._get(item, 'opening_height') or cls._get(item, 'height', ''),
                'wall_thickness': cls._get(item, 'wall') or cls._get(item, 'wall_thickness', ''),
                'direction': cls._get(item, 'direction', ''),
                'opening': cls._get(item, 'opening', ''),
                'color_frames': cls._get(item, 'color_frames') or cls._get(item, 'color', ''),
                'lock_name': cls._get(item, 'lock_name', ''),
                'hinge_name': cls._get(item, 'hinge_name', ''),
                'comment': cls._get(item, 'comment', ''),
            })
        return frames_items

    @classmethod
    def get_warehouse_hardware_summary(cls, spec_obj) -> list:
        """Краткая сводка фурнитуры (замки, ручки, петли) для секции Master Print."""
        locks = defaultdict(int)
        handles = defaultdict(int)
        hinges = defaultdict(int)

        for item in cls._extract_items(spec_obj):
            lock = cls._get(item, 'lock_name')
            if lock:
                locks[lock] += 1

            handle = cls._get(item, 'handle_name')
            if handle:
                handles[handle] += 1

            hinge = cls._get(item, 'hinge_name')
            if hinge:
                raw_hinges = cls._get(item, 'hinge_heights', []) or []
                count = len([h for h in raw_hinges if h is not None])
                hinges[hinge] += count if count > 0 else 3

        summary_list = []
        for name, qty in sorted(locks.items()):
            summary_list.append({'category': 'מנעולים (Замки)', 'name': name, 'quantity': qty})
        for name, qty in sorted(handles.items()):
            summary_list.append({'category': 'ידיות (Ручки)', 'name': name, 'quantity': qty})
        for name, qty in sorted(hinges.items()):
            summary_list.append({'category': 'צירים (Петли)', 'name': name, 'quantity': qty})

        return summary_list

    @classmethod
    def prepare_wood_frames_report_data(cls, spec_obj) -> list:
        """
        Группирует деревянные коробки в 4-уровневую иерархию для печатного отчёта:
        Страница (семейство + כפולה) -> Материал/наличник -> Фурнитура -> Строки размеров.
        """
        _get = cls._get
        raw_items = [it for it in cls._extract_items(spec_obj) if _get(it, 'has_frame', True)]

        frame_mat_ids = {
            _get(b, 'item_id')
            for it in raw_items
            for b in (_get(it, 'bom_items', []) or [])
            if (_get(b, 'tag', '') == 'frame' or _get(b, 'section', '') == 'frame') and _get(b, 'item_id')
        }
        frame_materials_map = {
            m.id: m
            for m in Material.objects.filter(id__in=frame_mat_ids).select_related('color')
        } if frame_mat_ids else {}

        pages_map = {}
        for item in raw_items:
            is_double = bool(_get(item, 'is_double_door', False))
            base_family = (_get(item, 'product_family', '') or _get(item, 'product_name', '')).strip()
            page_title = f"{base_family} כפולה" if is_double else base_family
            page_key = (base_family, is_double)

            if page_key not in pages_map:
                pages_map[page_key] = {
                    'product_name': page_title,
                    'is_double_door': is_double,
                    'materials_map': {},
                }

            bom_items = _get(item, 'bom_items', []) or []
            casing_names = [
                (_get(b, 'common_name') or _get(b, 'item_name', ''))
                for b in bom_items
                if _get(b, 'tag', '') in ('door_casing', 'casing')
                   or _get(b, 'section', '') in ('door_casing', 'casing', 'הלבשה', 'הלבשות')
            ]

            paint_opt = str(_get(item, 'frame_paint_option', '') or '').upper()
            frame_bom = next(
                (b for b in bom_items if _get(b, 'tag', '') == 'frame' or _get(b, 'section', '') == 'frame'),
                None,
            )

            common_name = str(_get(frame_bom, 'common_name') or '').strip() if frame_bom else ''
            item_name = str(_get(frame_bom, 'item_name') or '').strip() if frame_bom else ''
            mat_obj = frame_materials_map.get(_get(frame_bom, 'item_id')) if frame_bom else None

            mat_color = ''
            if mat_obj and getattr(mat_obj, 'color', None):
                mat_color = str(mat_obj.color.name).strip()
            elif common_name and item_name.startswith(common_name):
                mat_color = item_name[len(common_name):].strip(' -')

            if paint_opt == 'NO_PAINT':
                if common_name:
                    frames_caption = f"{common_name} {mat_color}".strip() if mat_color else (item_name or common_name)
                else:
                    frames_caption = item_name or str(_get(item, 'frame', '') or '').strip()
            else:
                base_frame_title = common_name or item_name or str(_get(item, 'frame', '') or '').strip()
                frames_caption = f"{base_frame_title} צבע".strip()

            door_casing = " / ".join(dict.fromkeys(filter(None, casing_names))) or "ללא"

            mat_key = (
                frames_caption,
                door_casing,
                _get(item, 'basic_color_frames', '') or '',
                _get(item, 'color_frames', '') or '',
            )
            materials_map = pages_map[page_key]['materials_map']
            if mat_key not in materials_map:
                materials_map[mat_key] = {
                    'frames_caption': frames_caption,
                    'door_casing': door_casing,
                    'hardware_map': {},
                }

            raw_cmz = _get(item, 'frames_report_customizers', []) or []
            parsed_cmz = []
            cmz_sig_parts = []
            for c in raw_cmz:
                c_name = str(_get(c, 'name', '')).strip()
                if not c_name:
                    continue
                clean_params = []
                p_sig = []
                for p in (_get(c, 'params', []) or []):
                    p_val = _get(p, 'value', '')
                    if p_val in (None, ''):
                        continue
                    p_label = str(_get(p, 'label', '')).strip()
                    p_val_str = str(p_val).strip()
                    is_custom = bool(
                        _get(p, 'is_custom', False)
                        or _get(p, 'is_modified', False)
                        or (_get(p, 'is_default', None) is False)
                    )
                    clean_params.append({'label': p_label, 'value': p_val_str, 'is_custom': is_custom})
                    p_sig.append((p_label, p_val_str, is_custom))

                sig = (c_name, tuple(p_sig))
                if sig not in cmz_sig_parts:
                    cmz_sig_parts.append(sig)
                    parsed_cmz.append({'name': c_name, 'params': clean_params})

            cmz_sig = tuple(cmz_sig_parts)
            raw_hinges = _get(item, 'hinge_heights', []) or []
            hinges_tuple = tuple(h for h in raw_hinges if h is not None)
            lock_name = '' if is_double else (_get(item, 'lock_name', '') or '')
            lock_height = None if is_double else _get(item, 'lock_height', None)

            hw_key = (lock_name, lock_height, _get(item, 'hinge_name', '') or '', hinges_tuple)
            hardware_map = materials_map[mat_key]['hardware_map']
            if hw_key not in hardware_map:
                hardware_map[hw_key] = {
                    'is_double_door': is_double,
                    'lock_name': lock_name,
                    'lock_height': lock_height,
                    'hinge_name': _get(item, 'hinge_name', '') or '',
                    'hinge_heights': list(hinges_tuple),
                    'items': [],
                }
            hardware_map[hw_key]['items'].append((item, parsed_cmz, cmz_sig))

        pages = []
        for page_data in pages_map.values():
            material_groups = []
            for mat_data in page_data['materials_map'].values():
                sorted_hw_items = sorted(
                    mat_data['hardware_map'].values(),
                    key=lambda h: float(h['lock_height']) if h['lock_height'] is not None else float('-inf'),
                    reverse=True,
                )

                hardware_groups = []
                for hw_grp in sorted_hw_items:
                    row_groups = {}
                    for it, parsed_cmz, cmz_sig in hw_grp['items']:
                        w = _get(it, 'width', None)
                        h = _get(it, 'height', None)
                        wall = _get(it, 'wall', None)
                        direction = '' if hw_grp['is_double_door'] else (_get(it, 'direction', '') or '')
                        comment = (_get(it, 'comment', '') or '').strip()

                        row_key = (w, h, wall, direction, comment, cmz_sig)
                        if row_key not in row_groups:
                            row_groups[row_key] = {
                                'width': w,
                                'height': h,
                                'wall': wall,
                                'direction': direction,
                                'qty': 0,
                                'customizers': parsed_cmz,
                                'comment': comment,
                            }
                        row_groups[row_key]['qty'] += 1

                    sorted_rows = sorted(
                        row_groups.values(),
                        key=lambda r: (
                            float(r['wall']) if r['wall'] is not None else float('inf'),
                            -float(r['height']) if r['height'] is not None else float('inf'),
                            -float(r['width']) if r['width'] is not None else float('inf'),
                        ),
                    )

                    hinge_heights = hw_grp.get('hinge_heights', [])
                    hinge_heights_display = "   ".join(
                        str(int(hh)) if float(hh).is_integer() else str(hh) for hh in hinge_heights
                    ) if hinge_heights else ""

                    hardware_groups.append({
                        'is_double_door': hw_grp['is_double_door'],
                        'lock_name': hw_grp['lock_name'],
                        'lock_height': hw_grp['lock_height'],
                        'hinge_name': hw_grp['hinge_name'],
                        'hinge_heights_display': hinge_heights_display,
                        'grouped_rows': sorted_rows,
                    })

                material_groups.append({
                    'frames_caption': mat_data['frames_caption'],
                    'door_casing': mat_data['door_casing'],
                    'hardware_groups': hardware_groups,
                })

            pages.append({
                'product_name': page_data['product_name'],
                'is_double_door': page_data['is_double_door'],
                'material_groups': material_groups,
            })

        total_pages = len(pages)
        for idx, page in enumerate(pages, start=1):
            page['page_num'] = idx
            page['total_pages'] = total_pages

        return pages

    def _write_xml_files(self, target_dir: str, spec, item_type: str) -> None:
        """Записывает XML-файлы петель и замка для позиции (точка расширения для Mecal)."""
        with open(os.path.join(target_dir, 'hinges.xml'), 'w', encoding='utf-8') as f:
            f.write(self._generate_hinges_xml(spec, item_type))
        with open(os.path.join(target_dir, 'lock.xml'), 'w', encoding='utf-8') as f:
            f.write(self._generate_lock_xml(spec, item_type))

    @staticmethod
    def _generate_hinges_xml(spec, item_type: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<hinges>\n  <status>placeholder</status>\n  <item_id>{spec.item_id}{item_type}</item_id>\n</hinges>'
        )

    @staticmethod
    def _generate_lock_xml(spec, item_type: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<lock>\n  <status>placeholder</status>\n  <item_id>{spec.item_id}{item_type}</item_id>\n</lock>'
        )

    def generate_report_html(self, report_type=None, station_code=None, batch_number=None,
                             validate: bool = True) -> str:
        """Рендерит HTML-отчёт для запрошенной станции или типа отчёта."""
        station = ProductionStation.objects.filter(code=station_code).first() if station_code else None

        if validate:
            val_res = OrderValidationService.validate_for_report(self.order, report_type, station=station)
            val_res.raise_if_invalid()

        if station:
            label = station.label or station.name
            template = station.template_name or 'production/alum_frames_report.html'
        else:
            try:
                label = self.ReportType(report_type).label
            except ValueError:
                label = str(report_type)
            template = 'production/alum_frames_report.html'
            if not getattr(self.order, 'has_split_installation', False) and report_type == self.ReportType.PHASE2_DOORS:
                label = 'Doors'

        phase = (
            'phase1'
            if (report_type == self.ReportType.PHASE1_FRAMES or (station and station.is_phase1))
            else 'phase2'
        )
        order_spec, _ = TechnicalSpecService.get_or_build_spec(self.order, phase=phase)

        if batch_number is not None:
            raw_spec_items = order_spec.batches.get(str(batch_number), [])
        else:
            raw_spec_items = [it for b_items in order_spec.batches.values() for it in b_items]

        filtered_items = self.get_filtered_items(report_type, station=station)
        filtered_item_ids = {item.id for item in filtered_items}

        target_items = []
        for it in raw_spec_items:
            it_id = self._get(it, 'item_id')
            if it_id not in filtered_item_ids:
                continue
            if station:
                it_station_ids = self._get(it, 'route_station_ids')
                if it_station_ids and station.id not in it_station_ids:
                    continue
            target_items.append(it)

        order_spec_for_report = order_spec.model_copy()
        order_spec_for_report.batches = {str(batch_number or "all"): target_items}

        if self.order.status == OrderStatus.PHASE1_PRODUCTION:
            stage_label = "שלב א'"
        elif self.order.status in (OrderStatus.PHASE2_PRODUCTION, OrderStatus.PHASE1_READY):
            stage_label = "שלב ב'"
        elif self.order.status == OrderStatus.COMPLETION_PRODUCTION:
            stage_label = "השלמות"
        else:
            stage_label = "קומפלט"

        station_notes_by_code = dict(
            OrderStationNote.objects.filter(order=self.order)
            .select_related('station')
            .values_list('station__code', 'comment')
        )
        station_comment = station_notes_by_code.get(station.code, '') if station else ''

        context = {
            'order': self.order,
            'batch_number': batch_number,
            'order_spec': order_spec_for_report,
            'spec_items': target_items,
            'order_spec_json': order_spec_for_report.model_dump_json(by_alias=True),
            'svg_patterns': SvgPattern.objects.all(),
            'report_type': report_type,
            'station': station,
            'station_comment': station_comment,
            'station_notes_by_code': station_notes_by_code,
            'report_label': label,
            'stage_label': stage_label,
            'groups_data': self.prepare_grouped_data(target_items),
            'panel_groups': self.prepare_press_groups_data(target_items),
            'now': timezone.now(),
        }
        return render_to_string(template, context)

    def get_filtered_items(self, report_type=None, station=None) -> list:
        """Возвращает OrderItem заказа, чей маршрут включает указанную станцию (или её альтернативу)."""
        items = []
        is_completion = self.order.status == OrderStatus.COMPLETION_PRODUCTION

        for group in self.order.groups.all():
            if group.production_state in (
                    OrderItemsGroup.ProductionState.WAITING,
                    OrderItemsGroup.ProductionState.CANCELED,
            ):
                continue
            if is_completion and group.production_state == OrderItemsGroup.ProductionState.COMPLETED:
                continue

            group_stations = ProductionRoute.get_stations_for_group(group)
            group_station_codes = [s.code for s in group_stations if s.code]

            if station:
                is_valid = any(
                    s.id == station.id or getattr(s, 'alternative_station_id', None) == station.id
                    for s in group_stations
                )
            else:
                rt = str(report_type).upper()
                codes_up = {c.upper() for c in group_station_codes}

                if rt in ('PHASE1_FRAMES', 'PHASE1_PRODUCTION', 'PHASE2_FRAMES', 'FRAMES', 'ALUM_FRAMES', 'WOOD_FRAMES',
                          '100'):
                    is_valid = bool(codes_up & {'FRAMES', 'ALUM_FRAMES', 'WOOD_FRAMES', 'WOODEN_FRAMES', '100'})
                elif rt in ('PHASE2_DOORS', 'DOORS', 'ALUM_DOORS'):
                    is_valid = bool(codes_up & {'DOORS', 'ALUM_DOORS'})
                elif rt in ('PHASE2_PRESS', 'PRESS', 'CUTTING_PRESS', 'CUT_SHEETS'):
                    is_valid = bool(codes_up & {'PRESS', 'CUTTING_PRESS', 'CUT_SHEETS'})
                elif rt in ('FACING', 'CLADDING', 'FACING_REPORT'):
                    is_valid = bool(codes_up & {'FACING', 'CLADDING', 'FACING_REPORT'})
                else:
                    is_valid = True

            if is_valid:
                items.extend(group.items.all())

        return items

    @classmethod
    def prepare_grouped_data(cls, items) -> list:
        """Группирует плоский список ProductionSpec (или словарей) для табличных отчётов."""
        _get = cls._get
        grouped_specs = {}
        for spec in items:
            key = (
                _get(spec, 'product_family', ''),
                _get(spec, 'series', ''),
                _get(spec, 'product_code', ''),
                _get(spec, 'front_name', ''),
                _get(spec, 'basic_color_frames', ''),
                _get(spec, 'frame_paint_option', ''),
                _get(spec, 'color_frames', ''),
                _get(spec, 'color_panel_outside', ''),
                tuple(_get(spec, 'profiles', []) or []),
            )
            grouped_specs.setdefault(key, []).append(spec)

        groups_data = []
        for key in sorted(grouped_specs.keys()):
            items_specs = grouped_specs[key]
            first = items_specs[0]

            common_front = _get(first, 'front_name', '')
            common_color_frames = _get(first, 'color_frames', '')
            common_color_panels = _get(first, 'color_panel_outside', '')

            for s in items_specs[1:]:
                if _get(s, 'front_name', '') != common_front:
                    common_front = "Various"
                if _get(s, 'color_frames', '') != common_color_frames:
                    common_color_frames = "Various"
                if _get(s, 'color_panel_outside', '') != common_color_panels:
                    common_color_panels = "Various"

            group_spec = {
                'product_name': _get(first, 'product_name', ''),
                'code': _get(first, 'product_code', ''),
                'front_name': common_front,
                'color_frames': common_color_frames,
                'basic_color_frames': _get(first, 'basic_color_frames', ''),
                'color_panels': common_color_panels,
                'lock_name': _get(first, 'lock_name', ''),
                'hinge_name': _get(first, 'hinge_name', ''),
                'common_lock_height': _get(first, 'lock_height', ''),
                'common_hinge_heights': _get(first, 'hinge_heights', []),
                'profiles': _get(first, 'profiles', []),
                'frame_paint_option': _get(first, 'frame_paint_option', ''),
                'frame': _get(first, 'frame', ''),
                'series': _get(first, 'series', ''),
                'product_family': _get(first, 'product_family', ''),
                'frames_report_customizers': _get(first, 'frames_report_customizers', []),
            }
            groups_data.append({'group_spec': group_spec, 'items_specs': items_specs})

        return groups_data

    @classmethod
    def prepare_press_groups_data(cls, items) -> list:
        """
        Группирует заготовки дверных полотен для отчёта на пресс.
        Использует готовые press_dimensions из ядра (уже округлённые с шагом 0.5 см
        и вычетом канта в см), с безопасным fallback на panel_dimensions для старых снимков.
        """
        _get = cls._get
        groups_map = {}

        for item in items:
            if not _get(item, 'has_door', True):
                continue

            is_hidden = bool(_get(item, 'is_hidden_wood_edge', False))
            bom_items = _get(item, 'bom_items', []) or []

            def _bom_name(b):
                return _get(b, 'common_name') or _get(b, 'item_name') or ''

            base_names = [_bom_name(b) for b in bom_items if _get(b, 'tag') == 'base' and _bom_name(b)]
            filling_names = [_get(b, 'item_name') for b in bom_items if
                             _get(b, 'tag') == 'filling' and _get(b, 'item_name')]
            panel_frame_names = [_bom_name(b) for b in bom_items if _get(b, 'tag') == 'panel_frame' and _bom_name(b)]

            finish_type = _get(item, 'finish_type', 'PAINT')
            covering_names = ''
            if not is_hidden:
                if finish_type == 'FORMICA':
                    c_out = str(_get(item, 'color_panel_outside', '') or '').strip()
                    c_in = str(_get(item, 'color_panel_inside', '') or '').strip()
                    if c_in and c_in != c_out:
                        covering_names = f"חוץ: {c_out} / פנים: {c_in}"
                    elif c_out:
                        covering_names = c_out
                else:
                    coverings = [_bom_name(b) for b in bom_items if _get(b, 'tag') == 'covering' and _bom_name(b)]
                    covering_names = coverings[0] if coverings else ''

            raw_components = base_names + filling_names + panel_frame_names
            comp_title = "  |  ".join(dict.fromkeys(filter(None, raw_components))) or _get(item, 'product_name', '')

            applied = _get(item, 'applied_presets', []) or []
            customizer_presets, sig_parts = [], []
            for p in applied:
                name = str(_get(p, 'name', '')).strip()
                if not name:
                    continue
                labels = [
                    {'text': str(_get(l, 'text', '')).strip(), 'is_custom': bool(_get(l, 'is_custom', False))}
                    for l in (_get(p, 'labels', []) or [])
                    if str(_get(l, 'text', '')).strip()
                ]
                customizer_presets.append({'name': name, 'labels': labels})
                lbl_suffix = f"({','.join(f'{l['text']}:{int(l['is_custom'])}' for l in labels)})" if labels else ""
                sig_parts.append(f"{name}{lbl_suffix}")

            presets_signature = " + ".join(dict.fromkeys(sig_parts))

            puzzle = _get(item, 'puzzle_spec', None)
            face_blocks = _get(puzzle, 'face_blocks', []) if puzzle else []
            sandwich_blocks = _get(puzzle, 'sandwich_blocks', []) if puzzle else []

            def _blocks_sig(blocks):
                return tuple(
                    (
                        _get(b, 'x'), _get(b, 'y'), _get(b, 'w'), _get(b, 'h'),
                        _get(b, 'fill_type'), _get(b, 'fill_color'),
                        _get(b, 'pattern_name'), _get(b, 'text'),
                    )
                    for b in blocks
                )

            group_key = (
                comp_title,
                covering_names,
                presets_signature,
                _blocks_sig(face_blocks),
                _blocks_sig(sandwich_blocks),
            )
            if group_key not in groups_map:
                groups_map[group_key] = {
                    'composition_title': comp_title,
                    'covering': covering_names,
                    'customizer_presets': customizer_presets,
                    'puzzle_face_blocks': face_blocks,
                    'puzzle_sandwich_blocks': sandwich_blocks,
                    'counter': Counter(),
                }

            # Используем уже рассчитанные ядром press_dimensions; fallback только для старых снимков
            press_dims = _get(item, 'press_dimensions', []) or []
            if press_dims:
                for pr in press_dims:
                    pw, ph = _get(pr, 'width'), _get(pr, 'height')
                    if pw is not None and ph is not None:
                        groups_map[group_key]['counter'][(float(pw), float(ph))] += 1
            else:
                has_edge = bool(_get(item, 'has_wood_edge', False))
                raw_t = float(_get(item, 'wood_edge_thickness', 0) or 0)
                t_cm = (raw_t / 10.0) if raw_t >= 5.0 else raw_t
                sides = int(_get(item, 'wood_edge_sides', 4) or 4)

                for p_dim in (_get(item, 'panel_dimensions', []) or []):
                    w, h = _get(p_dim, 'width'), _get(p_dim, 'height')
                    if w is None or h is None:
                        continue
                    w_bottom = _get(p_dim, 'width_bottom')
                    w = max(float(w), float(w_bottom)) if w_bottom is not None else float(w)
                    h = float(h)
                    if has_edge and t_cm > 0:
                        w -= t_cm * 2
                        h -= t_cm * ((sides > 2) + (sides > 3))
                    groups_map[group_key]['counter'][(round_press_dimension(w), round_press_dimension(h))] += 1

        panel_groups = []
        for grp in groups_map.values():
            counter = grp.pop('counter', Counter())
            dims = [
                {'width': w, 'height': h, 'qty': qty}
                for (w, h), qty in sorted(counter.items(), key=lambda x: (x[0][0], x[0][1]), reverse=True)
            ]
            if dims:
                grp['dimensions'] = dims
                panel_groups.append(grp)

        return panel_groups


class OrderProductionService:
    """Управление жизненным циклом заказа в производстве (старт, фазы A/B, завершение)."""

    @staticmethod
    def recalculate_item_marks(order) -> None:
        from apps.orders.services import recalculate_item_marks
        recalculate_item_marks(order)

    @staticmethod
    def cleanup_cnc_files(order) -> None:
        """Удаляет папку ЧПУ-файлов заказа с диска сервера."""
        order_dir = os.path.join(settings.BASE_DIR, 'cnc_files', 'mecal', str(order.order_number))
        if os.path.exists(order_dir):
            shutil.rmtree(order_dir)

    @staticmethod
    def validate_for_production(order, validation_type: Optional[str] = None):
        """Проверяет готовность заказа и возвращает кортеж (is_valid, errors)."""
        res = OrderValidationService.validate_for_production(order, validation_type)
        return res.is_valid, res.errors

    @classmethod
    @transaction.atomic
    def start_production(cls, order, user=None) -> None:
        """Переводит заказ или новые группы в производство с фиксацией батча и снимка."""
        is_valid, errors = cls.validate_for_production(order)
        if not is_valid:
            raise OrderValidationError("Data validation error", errors=errors)

        if not order.production_start_date:
            order.production_start_date = timezone.now()

        released_batch = order.current_batch or 1

        # Сценарий A: Запуск Фазы 2 (полотна после замеров Фазы 1)
        if order.status == OrderStatus.PHASE1_READY:
            phase2_groups = list(
                order.groups.filter(
                    production_state__in=[
                        OrderItemsGroup.ProductionState.WAITING,
                        OrderItemsGroup.ProductionState.NEW,
                    ]
                )
            )
            if not phase2_groups:
                raise OrderValidationError("Нет групп в ожидании (WAITING) для запуска второй фазы.")

            OrderItemsGroup.objects.filter(id__in=[g.id for g in phase2_groups]).update(
                batch_number=released_batch,
                production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION,
                batch_date=date.today(),
            )
            for g in phase2_groups:
                g.batch_number = released_batch
                g.production_state = OrderItemsGroup.ProductionState.IN_PRODUCTION
                g.batch_date = date.today()

            order.status = OrderStatus.PHASE2_PRODUCTION
            order.current_batch = released_batch + 1
            order.save(update_fields=['status', 'current_batch', 'production_start_date'])

            TechnicalSpecService.get_or_build_spec(
                order, phase='phase2', batch_number=released_batch, force_rebuild=True, user=user
            )
            for group in phase2_groups:
                StationTrackingService.initialize_batch_progress(group)
            return

        # Сценарий B: Первичный запуск (полный комплект или Фаза 1 при раздельном монтаже)
        new_groups_qs = order.groups.filter(production_state=OrderItemsGroup.ProductionState.NEW)
        if not new_groups_qs.exists():
            raise OrderValidationError("Нет новых групп для запуска в производство.")

        has_split = getattr(order, 'has_split_installation', False)
        if has_split:
            new_groups_qs.filter(is_split_installation=False).update(
                production_state=OrderItemsGroup.ProductionState.WAITING
            )
            groups_to_launch = list(new_groups_qs.filter(is_split_installation=True))
            if not groups_to_launch:
                raise OrderValidationError("Нет подходящих групп с раздельным монтажом для запуска первой фазы.")
            order.status = OrderStatus.PHASE1_PRODUCTION
        else:
            groups_to_launch = list(new_groups_qs)
            order.status = OrderStatus.IN_PRODUCTION

        OrderItemsGroup.objects.filter(id__in=[g.id for g in groups_to_launch]).update(
            batch_number=released_batch,
            production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION,
            batch_date=date.today(),
        )
        for g in groups_to_launch:
            g.batch_number = released_batch
            g.production_state = OrderItemsGroup.ProductionState.IN_PRODUCTION
            g.batch_date = date.today()

        order.current_batch = released_batch + 1
        order.save(update_fields=['status', 'current_batch', 'production_start_date'])

        phase = 'phase1' if order.status == OrderStatus.PHASE1_PRODUCTION else 'phase2'
        TechnicalSpecService.get_or_build_spec(
            order, phase=phase, batch_number=released_batch, force_rebuild=True, user=user
        )

        if order.status == OrderStatus.IN_PRODUCTION:
            for group in groups_to_launch:
                StationTrackingService.initialize_batch_progress(group)

    @staticmethod
    def complete_phase1(order, user=None):
        """Завершает Фазу 1 и переводит заказ в статус ожидания замеров (PHASE1_READY)."""
        if order.status != OrderStatus.PHASE1_PRODUCTION:
            raise ValueError("Phase A completion is only possible for orders in 'Phase A Production' status")

        old_status = order.status
        with transaction.atomic():
            order.status = OrderStatus.PHASE1_READY
            order.save(update_fields=['status'])
            OrderProductionService.cleanup_cnc_files(order)
            OrderChangeLog.objects.create(
                order=order,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=order.status,
            )
        return order

    @staticmethod
    def complete_production(order, user=None):
        """Завершает производство заказа и переводит активные группы в COMPLETED."""
        if order.status not in (
                OrderStatus.IN_PRODUCTION,
                OrderStatus.PHASE2_PRODUCTION,
                OrderStatus.COMPLETION_PRODUCTION,
        ):
            raise ValueError(
                "Production completion is only possible for orders in 'In Production', "
                "'Phase B Production' or 'Completion Production' status"
            )

        old_status = order.status
        with transaction.atomic():
            order.status = OrderStatus.COMPLETED
            order.groups.filter(
                production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION
            ).update(production_state=OrderItemsGroup.ProductionState.COMPLETED)
            order.save(update_fields=['status'])

            OrderProductionService.cleanup_cnc_files(order)
            OrderChangeLog.objects.create(
                order=order,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=order.status,
            )
        return order
