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
from datetime import date
from io import BytesIO
from typing import Any, List, Optional, Tuple

import qrcode
from django.conf import settings
from django.db import models, transaction
from django.template.loader import render_to_string
from django.utils import timezone
from qrcode.image.svg import SvgPathImage

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
from .models import OrderStationNote
from .tracking_services import StationTrackingService

DEFAULT_REPORT_TEMPLATE = 'production/reports/alum_frames_report.html'


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
    Специфическая логика каждого отчёта вынесена в модули пакета apps.production.reports.
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

    def _add_cnc_files_to_zip(self, zip_file: zipfile.ZipFile) -> None:
        """Точка расширения для добавления ЧПУ-файлов в ZIP-архив."""
        _ = zip_file

    def generate_cnc_files(
            self,
            spec_items: Optional[List[Any]] = None,
            batch_number: Optional[int] = None,
    ) -> None:
        """
        Генерирует управляющие файлы ЧПУ на диске сервера (cnc_files/mecal/<order_number>/)
        через зарегистрированный драйвер станка в MachineRegistry.
        """
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

        mecal_dir = os.path.join(settings.BASE_DIR, 'cnc_files', 'mecal')
        order_dir = os.path.join(mecal_dir, str(self.order.order_number))

        os.makedirs(mecal_dir, exist_ok=True)
        if os.path.exists(order_dir):
            shutil.rmtree(order_dir)
        os.makedirs(order_dir)

        from apps.production.cnc import MachineRegistry

        driver = MachineRegistry.get('MECAL')
        generated_files = driver.generate_files(self.order, items_to_process)
        for rel_path, content in generated_files.items():
            full_path = os.path.join(order_dir, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'wb') as f:
                f.write(content)

    @classmethod
    def extract_report_items(
            cls,
            spec_obj: Any,
            requested_batches: Optional[List[Any]] = None,
    ) -> Tuple[Optional[List[Any]], Optional[str]]:
        """
        Извлекает плоский отсортированный по mark список позиций для запрошенных батчей.
        Если requested_batches пуст или None — возвращает (None, None).
        """
        if not requested_batches:
            return None, None

        raw_batches = (
            spec_obj.get('batches')
            if isinstance(spec_obj, dict)
            else getattr(spec_obj, 'batches', None)
        )
        batches_dict = raw_batches if isinstance(raw_batches, dict) else {}

        requested_strs = [str(b) for b in requested_batches]
        unique_items: dict[Any, Any] = {}
        applied_batches: List[str] = []

        for b_num in requested_strs:
            if b_num in batches_dict:
                applied_batches.append(b_num)
                for item in batches_dict[b_num]:
                    item_id = cls._get(item, 'item_id')
                    unique_items[item_id if item_id is not None else id(item)] = item

        if not unique_items:
            return [], ",".join(applied_batches)

        flat_items = list(unique_items.values())

        def parse_mark(it: Any) -> int:
            mark = cls._get(it, 'mark')
            if mark is None:
                return 999999
            try:
                return int(str(mark))
            except (ValueError, TypeError):
                return 999999

        flat_items.sort(key=parse_mark)
        batches_label = "" if len(batches_dict) == 1 else ", ".join(applied_batches)
        return flat_items, batches_label

    @staticmethod
    def _extract_items(spec_or_items: Any) -> List[Any]:
        """Распаковывает позиции из OrderSpec или возвращает переданный список."""
        if isinstance(spec_or_items, list):
            return spec_or_items
        batches = getattr(spec_or_items, 'batches', None) or {}
        return [it for b in batches.values() for it in b]

    @staticmethod
    def _get(obj: Any, key: str, default: Any = None) -> Any:
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
            production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION,
        )

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
        return render_to_string(DEFAULT_REPORT_TEMPLATE, context)

    @classmethod
    def get_wooden_frames_data(cls, spec_obj: Any) -> List[dict]:
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

    def generate_report_html(
            self,
            report_type: Optional[str] = None,
            station_code: Optional[str] = None,
            batch_number: Optional[int] = None,
            validate: bool = True,
    ) -> str:
        """Рендерит автономный HTML-отчёт для запрошенной станции или типа отчёта (например, в ZIP)."""
        station = ProductionStation.objects.filter(code=station_code).first() if station_code else None
        report_type_str = str(report_type) if report_type is not None else ''

        if validate:
            val_res = OrderValidationService.validate_for_report(self.order, report_type, station=station)
            val_res.raise_if_invalid()

        if station:
            label = station.label or station.name
            template = station.template_name or DEFAULT_REPORT_TEMPLATE
        else:
            try:
                label = self.ReportType(report_type_str).label
            except ValueError:
                label = report_type_str
            template = DEFAULT_REPORT_TEMPLATE
            if (
                    not getattr(self.order, 'has_split_installation', False)
                    and report_type_str == self.ReportType.PHASE2_DOORS.value
            ):
                label = 'Doors'

        is_phase1_report = (
                report_type_str == self.ReportType.PHASE1_FRAMES.value
                or (station is not None and station.is_phase1)
        )
        phase = 'phase1' if is_phase1_report else 'phase2'
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

    def get_filtered_items(
            self,
            report_type: Optional[str] = None,
            station: Optional[ProductionStation] = None,
    ) -> List[OrderItem]:
        """Возвращает OrderItem заказа, чей маршрут включает указанную станцию (или её альтернативу)."""
        items: List[OrderItem] = []
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
                rt = str(report_type or '').upper()
                codes_up = {c.upper() for c in group_station_codes}

                if rt in (
                        'PHASE1_FRAMES', 'PHASE1_PRODUCTION', 'PHASE2_FRAMES',
                        'FRAMES', 'ALUM_FRAMES', 'WOOD_FRAMES', '100',
                ):
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
    def prepare_grouped_data(cls, items: List[Any]) -> List[dict]:
        """Делегирует стандартную табличную группировку в apps.production.reports.common."""
        from apps.production.reports.common import prepare_grouped_data
        return prepare_grouped_data(items)

    @classmethod
    def prepare_press_groups_data(cls, items: List[Any]) -> List[dict]:
        """Делегирует сборку карточек пресса в apps.production.reports.press."""
        from apps.production.reports.press import build_press_groups_data
        return build_press_groups_data(items)

    @classmethod
    def get_warehouse_hardware_summary(cls, spec_obj: Any) -> List[dict]:
        """Делегирует краткую сводку фурнитуры в apps.production.reports.warehouse."""
        from apps.production.reports.warehouse import build_warehouse_hardware_summary
        return build_warehouse_hardware_summary(cls._extract_items(spec_obj))

    @classmethod
    def prepare_wood_frames_report_data(cls, spec_obj: Any) -> List[dict]:
        """Делегирует 4-уровневую группировку деревянных коробок в apps.production.reports.wood_frames."""
        from apps.production.reports.wood_frames import build_wood_frames_report_data
        return build_wood_frames_report_data(cls._extract_items(spec_obj))


class OrderProductionService:
    """Управление жизненным циклом заказа в производстве (старт, фазы A/B, завершение)."""

    @staticmethod
    def recalculate_item_marks(order) -> None:
        """Пересчитывает сквозную нумерацию (mark) позиций заказа."""
        from apps.orders.services import recalculate_item_marks
        recalculate_item_marks(order)

    @staticmethod
    def cleanup_cnc_files(order) -> None:
        """Удаляет папку ЧПУ-файлов заказа с диска сервера."""
        order_dir = os.path.join(settings.BASE_DIR, 'cnc_files', 'mecal', str(order.order_number))
        if os.path.exists(order_dir):
            shutil.rmtree(order_dir)

    @staticmethod
    def _release_groups_to_batch(groups: List[OrderItemsGroup], batch_number: int) -> None:
        """Фиксирует номер батча, дату запуска и статус IN_PRODUCTION для списка групп."""
        today = date.today()
        OrderItemsGroup.objects.filter(id__in=[g.id for g in groups]).update(
            batch_number=batch_number,
            production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION,
            batch_date=today,
        )
        for group in groups:
            group.batch_number = batch_number
            group.production_state = OrderItemsGroup.ProductionState.IN_PRODUCTION
            group.batch_date = today

    @staticmethod
    def _transition_order_status(order, new_status: str, user=None) -> None:
        """Переводит заказ в новый статус, очищает временные файлы ЧПУ и пишет запись в аудит."""
        old_status = order.status
        order.status = new_status
        order.save(update_fields=['status'])
        OrderProductionService.cleanup_cnc_files(order)
        OrderChangeLog.objects.create(
            order=order,
            user=user,
            field_name='status',
            old_value=old_status,
            new_value=new_status,
        )

    @staticmethod
    def validate_launch_rules(order) -> List[str]:
        """Проверяет совместимость NEW-групп (раздельный монтаж vs обычные) с текущим статусом заказа."""
        if order.status == OrderStatus.CANCELED:
            return ["לא ניתן להעביר לייצור הזמנה מבוטלת."]

        new_groups = list(order.groups.filter(production_state=OrderItemsGroup.ProductionState.NEW))

        if order.status == OrderStatus.PHASE1_READY:
            if any(g.is_split_installation for g in new_groups):
                return [
                    "קיימות קבוצות חדשות עם התקנה מפוצלת. יש להעביר אותן בשלב א' לפני המעבר לשלב ב'."
                ]
            return []

        if not new_groups:
            return ["אין קבוצות חדשות להעברה לייצור."]

        has_new_split = any(g.is_split_installation for g in new_groups)
        has_new_regular = any(not g.is_split_installation for g in new_groups)

        if order.status == OrderStatus.NEW:
            if has_new_split and has_new_regular:
                return [
                    "לא ניתן להוריד לייצור שלב א' קבוצות עם התקנה מפוצלת וקבוצות רגילות יחד. "
                    "השהה את הקבוצות הרגילות עד המעבר לשלב ב'."
                ]
        elif order.status == OrderStatus.PHASE1_PRODUCTION:
            if has_new_regular:
                return [
                    "בזמן ייצור שלב א' ניתן להוריד לייצור רק קבוצות עם התקנה מפוצלת. "
                    "השהה או תקן את הקבוצות הרגילות."
                ]
        elif order.status in (
                OrderStatus.IN_PRODUCTION,
                OrderStatus.PHASE2_PRODUCTION,
                OrderStatus.COMPLETION_PRODUCTION,
                OrderStatus.PARTIALLY_READY,
                OrderStatus.COMPLETED,
        ):
            if has_new_split:
                return [
                    "לא ניתן להוריד לייצור קבוצות עם התקנה מפוצלת לאחר מעבר לשלב ב' או בייצור רגיל/השלמות."
                ]

        return []

    @classmethod
    def validate_for_production(cls, order, validation_type: Optional[str] = None) -> Tuple[bool, List[str]]:
        """Проверяет правила фаз и готовность данных заказа; возвращает (is_valid, errors)."""
        launch_errors = cls.validate_launch_rules(order)
        if launch_errors:
            return False, launch_errors
        res = OrderValidationService.validate_for_production(order, validation_type)
        return res.is_valid, res.errors

    @classmethod
    @transaction.atomic
    def change_group_state(cls, group: OrderItemsGroup, new_state: str, user=None) -> str:
        """
        Централизованное управление статусом группы:
          - NEW -> WAITING (ручная пауза) / COMPLETED -> WAITING (разморозка для доделок)
          - WAITING -> NEW (снятие с паузы, с валидацией фазы и откатом PHASE1_READY -> PHASE1_PRODUCTION)
          - CANCELED -> NEW (восстановление группы и её OrderItem)
          - * -> CANCELED (отмена группы и её активных OrderItem)
        """
        order = group.order
        old_state = group.production_state
        allowed_states = {
            OrderItemsGroup.ProductionState.NEW,
            OrderItemsGroup.ProductionState.WAITING,
            OrderItemsGroup.ProductionState.CANCELED,
        }

        if new_state not in allowed_states:
            raise OrderValidationError(f"סטטוס יעד לא חוקי: {new_state}")
        if order.status == OrderStatus.CANCELED:
            raise OrderValidationError("לא ניתן לשנות סטטוס קבוצה בהזמנה מבוטלת.")
        if old_state == new_state:
            return f"סטטוס קבוצה #{group.id} כבר {group.get_production_state_display()}."

        rolled_back_phase1 = False
        update_fields = ['production_state']

        if new_state == OrderItemsGroup.ProductionState.WAITING:
            if old_state not in (
                    OrderItemsGroup.ProductionState.NEW,
                    OrderItemsGroup.ProductionState.COMPLETED,
            ):
                raise OrderValidationError("ניתן להשהות רק קבוצה חדשה או להפשיר קבוצה שהושלמה.")
            if old_state == OrderItemsGroup.ProductionState.COMPLETED:
                group.batch_number = None
                group.batch_date = None
                update_fields.extend(['batch_number', 'batch_date'])

        elif new_state == OrderItemsGroup.ProductionState.NEW:
            if old_state not in (
                    OrderItemsGroup.ProductionState.WAITING,
                    OrderItemsGroup.ProductionState.CANCELED,
            ):
                raise OrderValidationError("ניתן להחזיר לפעילות רק קבוצה מושהית או מבוטלת.")

            if order.status == OrderStatus.PHASE1_PRODUCTION and not group.is_split_installation:
                raise OrderValidationError(
                    "לא ניתן להחזיר לפעילות קבוצה ללא התקנה מפוצלת בזמן שההזמנה בייצור שלב א'."
                )
            if order.status in (
                    OrderStatus.IN_PRODUCTION,
                    OrderStatus.PHASE2_PRODUCTION,
                    OrderStatus.COMPLETION_PRODUCTION,
                    OrderStatus.PARTIALLY_READY,
                    OrderStatus.COMPLETED,
            ) and group.is_split_installation:
                raise OrderValidationError(
                    "לא ניתן להחזיר לפעילות קבוצה עם התקנה מפוצלת לאחר מעבר לשלב ב' או בייצור רגיל/השלמות."
                )

            if group.batch_number is not None or group.batch_date is not None:
                group.batch_number = None
                group.batch_date = None
                update_fields.extend(['batch_number', 'batch_date'])

            if old_state == OrderItemsGroup.ProductionState.CANCELED:
                group.items.filter(state=OrderItem.ItemState.CANCELED).update(
                    state=OrderItem.ItemState.ACTIVE
                )

            # Сценарий 2: откат PHASE1_READY -> PHASE1_PRODUCTION (логируем с реальным пользователем)
            if order.status == OrderStatus.PHASE1_READY and group.is_split_installation:
                order.status = OrderStatus.PHASE1_PRODUCTION
                order.save(update_fields=['status'])
                OrderChangeLog.objects.create(
                    order=order,
                    user=user,
                    field_name='status',
                    old_value=OrderStatus.PHASE1_READY,
                    new_value=OrderStatus.PHASE1_PRODUCTION,
                )
                rolled_back_phase1 = True

        elif new_state == OrderItemsGroup.ProductionState.CANCELED:
            if order.status == OrderStatus.COMPLETED:
                raise OrderValidationError("לא ניתן לבטל קבוצה בהזמנה שכבר הושלמה.")
            group.items.filter(state=OrderItem.ItemState.ACTIVE).update(
                state=OrderItem.ItemState.CANCELED
            )

        group.production_state = new_state
        group.save(update_fields=update_fields)

        OrderChangeLog.objects.create(
            order=order,
            user=user,
            field_name=f"Group #{group.id} production_state",
            old_value=old_state,
            new_value=new_state,
        )

        msg = f"סטטוס קבוצה #{group.id} עודכן ל-{group.get_production_state_display()}."
        if rolled_back_phase1:
            msg += " סטטוס ההזמנה הוחזר ל'ייצור שלב א' להורדת האצווה החדשה."
        return msg

    @classmethod
    @transaction.atomic
    def start_production(cls, order, user=None) -> None:
        """Переводит заказ или новые NEW-группы в производство (WAITING-группы игнорируются)."""
        is_valid, errors = cls.validate_for_production(order)
        if not is_valid:
            raise OrderValidationError("Data validation error", errors=errors)

        if not order.production_start_date:
            order.production_start_date = timezone.localdate()

        released_batch = order.current_batch or 1
        old_status = order.status

        # Сценарий A: Переход PHASE1_READY -> PHASE2_PRODUCTION (вызов напрямую через сервис)
        if order.status == OrderStatus.PHASE1_READY:
            new_groups = list(order.groups.filter(production_state=OrderItemsGroup.ProductionState.NEW))
            if new_groups:
                cls._release_groups_to_batch(new_groups, released_batch)
                order.current_batch = released_batch + 1

            order.status = OrderStatus.PHASE2_PRODUCTION
            order.save(update_fields=['status', 'current_batch', 'production_start_date'])

            OrderChangeLog.objects.create(
                order=order,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=order.status,
            )
            TechnicalSpecService.get_or_build_spec(
                order, phase='phase2', force_rebuild=True, user=user
            )
            for group in order.groups.filter(production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION):
                StationTrackingService.initialize_batch_progress(group)
            return

        # Сценарий B: Первичный запуск или дозапуск нового батча из NEW-групп
        groups_to_launch = list(order.groups.filter(production_state=OrderItemsGroup.ProductionState.NEW))
        if not groups_to_launch:
            raise OrderValidationError("אין קבוצות חדשות להעברה לייצור.")

        is_split_launch = groups_to_launch[0].is_split_installation

        if order.status == OrderStatus.NEW:
            target_status = OrderStatus.PHASE1_PRODUCTION if is_split_launch else OrderStatus.IN_PRODUCTION
            phase = 'phase1' if is_split_launch else 'phase2'
        elif order.status == OrderStatus.PHASE1_PRODUCTION:
            target_status = OrderStatus.PHASE1_PRODUCTION
            phase = 'phase1'
        elif order.status in (OrderStatus.COMPLETED, OrderStatus.PARTIALLY_READY):
            target_status = OrderStatus.COMPLETION_PRODUCTION
            phase = 'phase2'
        else:
            target_status = order.status
            phase = 'phase2'

        cls._release_groups_to_batch(groups_to_launch, released_batch)
        order.status = target_status
        order.current_batch = released_batch + 1
        order.save(update_fields=['status', 'current_batch', 'production_start_date'])

        if target_status != old_status:
            OrderChangeLog.objects.create(
                order=order,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=target_status,
            )

        TechnicalSpecService.get_or_build_spec(
            order, phase=phase, batch_number=released_batch, force_rebuild=True, user=user
        )

        if phase == 'phase2':
            for group in groups_to_launch:
                StationTrackingService.initialize_batch_progress(group)

    @classmethod
    def complete_phase1(cls, order, user=None):
        """Завершает Фазу 1 и переводит заказ в PHASE1_READY (группы остаются IN_PRODUCTION)."""
        if order.status != OrderStatus.PHASE1_PRODUCTION:
            raise ValueError("Phase A completion is only possible for orders in 'Phase A Production' status")
        if order.groups.filter(production_state=OrderItemsGroup.ProductionState.NEW).exists():
            raise OrderValidationError(
                "קיימות קבוצות חדשות שטרם הועברו לייצור — העבר אותן לאצווה או השהה לפני סיום שלב א'."
            )

        with transaction.atomic():
            cls._transition_order_status(order, OrderStatus.PHASE1_READY, user=user)
        return order

    @classmethod
    def complete_production(cls, order, user=None):
        """Завершает производство заказа и переводит активные IN_PRODUCTION-группы в COMPLETED."""
        if order.status not in (
                OrderStatus.IN_PRODUCTION,
                OrderStatus.PHASE2_PRODUCTION,
                OrderStatus.COMPLETION_PRODUCTION,
                OrderStatus.PARTIALLY_READY,
        ):
            raise ValueError(
                "Production completion is only possible for orders in 'In Production', "
                "'Phase B Production', 'Completion Production' or 'Partially Ready' status"
            )
        if order.groups.filter(production_state=OrderItemsGroup.ProductionState.NEW).exists():
            raise OrderValidationError(
                "קיימות קבוצות חדשות שטרם הועברו לייצור — העבר אותן או השהה לפני סיום הייצור."
            )

        with transaction.atomic():
            order.groups.filter(
                production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION
            ).update(production_state=OrderItemsGroup.ProductionState.COMPLETED)
            cls._transition_order_status(order, OrderStatus.COMPLETED, user=user)
        return order
