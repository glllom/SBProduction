import base64
import io
import math
import os
import shutil
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from typing import List, Optional

import qrcode
from django.conf import settings
from django.db import models
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from qrcode.image.svg import SvgPathImage

from apps.orders.models import OrderItemsGroup, OrderItem, OrderChangeLog
from apps.orders.models import OrderStatus
from .models import (
    ProductionStation, OrderSpecificationSnapshot, SvgPattern,
)
from .pipeline import OrderSpecPipeline
from .schemas import OrderSpec
from .tracking_services import StationTrackingService


def get_qr_base64(data: str) -> str:
    """Генерирует QR-код в формате Base64 SVG."""
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


def round_press_dimension(val: float | int) -> float:
    # Add hardcoded tolerance +1
    target = float(val) + 1.0
    integer_part = math.floor(target)
    fraction = round(target - integer_part, 4)

    if fraction == 0:
        return float(integer_part)
    if fraction <= 0.5:
        return integer_part + 0.5
    return float(integer_part + 1)


class OrderValidationError(Exception):
    """Custom error for order validation failures."""

    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = errors or []


class ValidationType(models.TextChoices):
    PARTIAL = 'PARTIAL', 'Partial validation (Phase A)'
    FULL = 'FULL', 'Full validation (Phase B / Full production)'
    COMPLETION = 'COMPLETION', 'Completion validation (Unfinished groups only)'


@dataclass
class ValidationResult:
    """
    Data validation result for an order.
    """
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    validation_type: str = ValidationType.FULL

    def __iter__(self):
        return iter((self.is_valid, self.errors))

    def raise_if_invalid(self):
        if not self.is_valid:
            error_details = "; ".join(self.errors)
            raise ValueError(f"Data validation error ({self.validation_type}): {error_details}")


class OrderValidationService:
    """
    Валидатор готовности заказа.
    Использует Dry-run прогон OrderSpecPipeline для проверки технологической
    корректности фурнитуры, высот, кастомизаторов и материалов без сохранения в БД.
    """

    @classmethod
    def validate(cls, order, validation_type: str = ValidationType.FULL) -> ValidationResult:
        if validation_type == ValidationType.PARTIAL:
            return cls.validate_partial(order)
        elif validation_type == ValidationType.COMPLETION:
            return cls.validate_completion(order)
        return cls.validate_full(order)

    @classmethod
    def validate_partial(cls, order) -> ValidationResult:
        """Частичная проверка (Фаза А — коробки при раздельном монтаже)."""
        errors = cls._run_validation(order, phase='phase1', is_full=False)
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            validation_type=ValidationType.PARTIAL
        )

    @classmethod
    def validate_full(cls, order) -> ValidationResult:
        """Полная проверка (Фаза Б / стандартный заказ)."""
        errors = cls._run_validation(order, phase='phase2', is_full=True)
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            validation_type=ValidationType.FULL
        )

    @classmethod
    def validate_completion(cls, order) -> ValidationResult:
        """Проверка для дозаказов / незавершенных групп."""
        errors = cls._run_validation(order, phase='phase2', is_full=True, completion_only=True)
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            validation_type=ValidationType.COMPLETION
        )

    @staticmethod
    def validate_for_production(order, validation_type: Optional[str] = None):
        if validation_type:
            return OrderValidationService.validate(order, validation_type)
        elif order.has_split_installation and order.status == OrderStatus.NEW:
            return OrderValidationService.validate_partial(order)
        return OrderValidationService.validate_full(order)

    @classmethod
    def validate_for_report(cls, order,
                            report_type: Optional[str] = None,
                            station: Optional[ProductionStation] = None) -> ValidationResult:
        if order.status == OrderStatus.COMPLETION_PRODUCTION:
            return cls.validate_completion(order)
        if station and not station.has_specification:
            return cls.validate_full(order)

        if report_type in ['PHASE1_FRAMES', 'PHASE1_PRODUCTION'] or (station and getattr(station, 'is_phase1', False)):
            return cls.validate_partial(order)
        return cls.validate_full(order)

    @classmethod
    def validate_for_phase(cls, order, phase: str) -> ValidationResult:
        if phase == 'phase1':
            return cls.validate_partial(order)
        elif phase == 'phase2_completion':
            return cls.validate_completion(order)
        return cls.validate_full(order)

    @classmethod
    def validate_for_zip(cls, order) -> ValidationResult:
        if order.status == OrderStatus.COMPLETION_PRODUCTION:
            return cls.validate_completion(order)
        has_split = getattr(order, 'has_split_installation', False)
        if has_split and getattr(order, 'status', None) == OrderStatus.PHASE1_PRODUCTION:
            return cls.validate_partial(order)
        return cls.validate_full(order)

    @classmethod
    def _run_validation(cls, order, phase: str = 'phase2', is_full: bool = True, completion_only: bool = False) -> List[
        str]:
        errors = []

        if not getattr(order, 'order_number', None):
            errors.append("חסר מספר הזמנה")
        if not getattr(order, 'customer', None):
            errors.append("חסר שם לקוח")

        # 1. Выборка позиций
        items = TechnicalSpecService.get_rich_order_items(order_id=order.id)
        if completion_only:
            items = [it for it in items if it.group.production_state != OrderItemsGroup.ProductionState.COMPLETED]
        elif phase == 'phase1' and getattr(order, 'has_split_installation', False):
            # В Фазе 1 проверяются только позиции групп раздельного монтажа
            items = [it for it in items if it.group.is_split_installation]

        if not items:
            errors.append("אין פריטים פעילים בהזמנה לביצוע בדיקה")
            return errors

        # 2. Проверка шапки и групп
        has_any_doors = False
        target_groups = set(it.group for it in items)

        for group in target_groups:
            group_label = f"קבוצה #{group.id} ({group.product.name if group.product else 'ללא מוצר'})"

            if not group.product:
                errors.append(f"{group_label}: לא נבחר דגם מוצר")
                continue

            effective_series = group.series or getattr(order, 'series', None)
            if not effective_series:
                errors.append(f"{group_label}: לא נבחרה סדרה")

            effective_front = group.front or getattr(order, 'front', None)
            if not effective_front:
                errors.append(f"{group_label}: לא נבחרה חזית")

            if is_full:
                if group.panel_paint_option == OrderItemsGroup.PaintOption.SPECIAL_COLOR:
                    if not group.color_panel_outside and not getattr(order, 'color_panels', None):
                        errors.append(f"{group_label}: נבחר צבע מיוחד לכנף אך לא הוזן גוון")
                if group.frame_paint_option == OrderItemsGroup.PaintOption.SPECIAL_COLOR:
                    if not group.basic_color_frames and not getattr(order, 'color_frames', None):
                        errors.append(f"{group_label}: נבחר צבע מיוחד למשקוף אך לא הוזן גוון")

            if group.product.has_door:
                has_any_doors = True

        if is_full and has_any_doors and not getattr(order, 'handle', None):
            errors.append("חובה לבחור דגם ידית להזמנה")

        if errors:
            return errors

        # 3. Холостой прогон через пайплайн
        pipeline = OrderSpecPipeline()
        spec_obj = pipeline.execute(order, items=items, phase=phase)

        # 4. Сбор ошибок позиций
        for b_items in spec_obj.batches.values():
            for it in b_items:
                if it.errors:
                    mark_label = f"דלת מס' {it.mark}" if it.mark else f"פריט #{it.item_id}"
                    for err in it.errors:
                        errors.append(f"{mark_label}: {err}")

        return errors


class TechnicalSpecService:
    """
    Единый шлюз спецификаций заказа.
    Отвечает за сборку среза позиций, запуск пайплайна, сохранение и чтение снимков.
    Структура кэша в JSONField: {"order": {...}, "batches": {"1": [...], "2": [...]}}
    """

    @staticmethod
    def get_rich_order_items(order_id: int, batch_number: Optional[int] = None):
        """
        Плоская выборка позиций с отсечением WAITING и CANCELED.
        При указании batch_number возвращает только указанный батч.
        """
        qs = (
            OrderItem.objects.filter(group__order_id=order_id)
            .exclude(
                group__production_state__in=[
                    OrderItemsGroup.ProductionState.WAITING,
                    OrderItemsGroup.ProductionState.CANCELED,
                ]
            )
            .select_related(
                'group',
                'group__order',
                'group__order__series',
                'group__order__front',
                'group__order__handle',
                'group__product',
                'group__product__product_family',
                'group__product__product_family__product_type',
                'group__product__series',
                'group__product__tech_data',
                'group__product__bom',
                'group__product__bom__frame',
                'group__product__bom__covering',
                'group__product__bom__base',
                'group__product__bom__filling',
                'group__product__bom__lock',
                'group__product__bom__hinges',
                'group__front',
                'group__series',
                'group__basic_color_frames',
            )
            .prefetch_related(
                'group__customizers__customizer__hardware__components',
                'group__product__bom__additional',
            ).order_by('id')
        )

        if batch_number is not None:
            qs = qs.filter(group__batch_number=batch_number)

        return list(qs)

    @classmethod
    def get_or_build_spec(
            cls,
            order,
            phase: str = 'phase2',
            batch_number: Optional[int] = None,
            force_rebuild: bool = False,
            user=None
    ) -> tuple[OrderSpec, dict]:
        """
        Возвращает пару (OrderSpec, spec_cache_dict).
        Если снимок уже есть в базе и не запрошен force_rebuild — десериализует из JSON.
        Иначе — прогоняет выборку позиций через пайплайн и фиксирует снимок в БД.
        """
        cache_field = 'phase1_spec_cache' if phase == 'phase1' else 'phase2_spec_cache'
        existing_cache = getattr(order, cache_field)

        # Гарантируем корректную базовую структуру кэша
        if not isinstance(existing_cache, dict) or 'batches' not in existing_cache:
            existing_cache = {
                'order': {},
                'batches': {}
            }

        batch_str = str(batch_number) if batch_number is not None else None

        # 1. Возврат из существующего снимка (если запрашивался конкретный батч и он есть)
        if not force_rebuild:
            if batch_str and batch_str in existing_cache.get('batches', {}):
                return OrderSpec.model_validate(existing_cache), existing_cache
            elif batch_str is None and existing_cache.get('batches'):
                return OrderSpec.model_validate(existing_cache), existing_cache

        # 2. Выборка позиций
        items = cls.get_rich_order_items(order_id=order.id, batch_number=batch_number)
        if not items:
            raise OrderValidationError(f"Нет активных позиций для формирования спецификации (batch={batch_number}).")

        # 3. Запуск пайплайна
        pipeline = OrderSpecPipeline()
        spec_obj = pipeline.execute(order, items=items, phase=phase)

        # Проверка ошибок расчетов в узлах
        errors = []
        for b_items in spec_obj.batches.values():
            for it in b_items:
                if it.errors:
                    mark_label = f"Item {it.mark}" if it.mark else f"Item #{it.item_id}"
                    errors.extend([f"{mark_label}: {err}" for err in it.errors])
        # if errors:
        #     raise OrderValidationError("Ошибки при расчете спецификации:", errors=errors)
        if errors:
            raise OrderValidationError(f"Ошибки при расчете спецификации: {'; '.join(errors)}", errors=errors)
        # 4. Обновление кэша (слияние батчей, сохранение шапки)
        spec_dict = spec_obj.model_dump()
        existing_cache['order'] = spec_dict.get('order', {})

        if 'batches' not in existing_cache:
            existing_cache['batches'] = {}

        for b_key, b_items in spec_dict.get('batches', {}).items():
            existing_cache['batches'][b_key] = b_items

        setattr(order, cache_field, existing_cache)
        order.save(update_fields=[cache_field])

        # Фиксация в истории снимков
        snapshot_type = (
            OrderSpecificationSnapshot.SnapshotType.PHASE1
            if phase == 'phase1'
            else OrderSpecificationSnapshot.SnapshotType.PHASE2
        )
        OrderSpecificationSnapshot.objects.create(
            order=order,
            snapshot_type=snapshot_type,
            spec_data=existing_cache,
            created_by=user
        )

        return OrderSpec.model_validate(existing_cache), existing_cache

    @classmethod
    def get_batch_items(cls, order, phase: str = 'phase1', batch_number: int = 1) -> List[dict]:
        """
        Возвращает плоский список рассчитанных позиций конкретной партии из снимка.
        """
        cache_field = 'phase1_spec_cache' if phase == 'phase1' else 'phase2_spec_cache'
        cache = getattr(order, cache_field)
        if not isinstance(cache, dict):
            return []

        batches = cache.get('batches', {})
        if isinstance(batches, dict):
            return batches.get(str(batch_number), [])

        return []


class ProductionDataService:
    class ReportType(models.TextChoices):
        PHASE1_FRAMES = 'PHASE1_PRODUCTION', 'Phase A Frames'
        PHASE2_DOORS = 'PHASE2_DOORS', 'Phase B Doors'
        PHASE2_PRESS = 'PHASE2_PRESS', 'Press'
        PHASE2_FRAMES = 'PHASE2_FRAMES', 'Frames'
        IN_PRODUCTION = 'IN_PRODUCTION', 'Full Production Report'
        FULL_PRODUCTION = 'FULL_PRODUCTION', 'Full Production Report'

    def __init__(self, order):
        self.order = order

    def generate_production_zip(self):
        """
        Creates a ZIP archive of all production files (CNC XML) and technical reports.
        Performs validation before creation.
        """
        val_res = OrderValidationService.validate_for_zip(self.order)
        val_res.raise_if_invalid()

        buffer = io.BytesIO()
        has_split = getattr(self.order, 'has_split_installation', False)

        with zipfile.ZipFile(buffer, 'w') as zip_file:
            if has_split and self.order.status == OrderStatus.PHASE1_PRODUCTION:
                # Only Phase 1 report
                report_content = self.generate_report_html(self.ReportType.PHASE1_FRAMES, validate=False)
                zip_file.writestr(f"Order_{self.order.order_number}_PhaseA_Frames.html", report_content)
            elif self.order.status in [OrderStatus.IN_PRODUCTION, OrderStatus.PHASE1_READY]:
                # Reports for doors, press and frames
                for rt in [self.ReportType.PHASE2_DOORS, self.ReportType.PHASE2_PRESS, self.ReportType.PHASE2_FRAMES]:
                    report_content = self.generate_report_html(rt, validate=False)
                    zip_file.writestr(f"Order_{self.order.order_number}_{rt.name}.html", report_content)
            else:
                report_content = self.generate_report_html(self.ReportType.FULL_PRODUCTION, validate=False)
                zip_file.writestr(f"Order_{self.order.order_number}_Full.html", report_content)

            # Generate CNC files into zip
            self._add_cnc_files_to_zip(zip_file)

        buffer.seek(0)
        return buffer

    def _add_cnc_files_to_zip(self, zip_file):
        pass

    def generate_cnc_files(self, spec_items=None, batch_number=None):
        """
        Standalone method to generate CNC files on the server filesystem.
        Creates folder structure cnc_files/mecal/<order_number>/ and fills it with XML files.
        If batch_number is specified, generates only for that batch.
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
                active_item_ids = set(OrderItem.objects.filter(
                    group__order=self.order
                ).exclude(
                    group__production_state=OrderItemsGroup.ProductionState.COMPLETED
                ).values_list('id', flat=True))
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
        Универсальная строгая прослойка для отчетов.
        Ожидает явный список номеров батчей (например: [1], или ['1', '3']).
        Если список пуст или None — возвращает (None, None).
        Извлекает данные из сохраненного снимка спецификации, дедуплицирует по item_id.
        """
        if not requested_batches:
            return None, None

        batches_dict = getattr(spec_obj, 'batches', {}) or {}
        if not isinstance(batches_dict, dict):
            # Если передали обычный словарь вместо Pydantic модели
            batches_dict = spec_obj.get('batches', {}) if isinstance(spec_obj, dict) else {}

        # Приводим запрошенные номера к строкам
        requested_batches = [str(b) for b in requested_batches]

        unique_items = {}
        applied_batches = []

        # Извлекаем только те, которые явно запрошены в списке
        for b_num in requested_batches:
            if b_num in batches_dict:
                applied_batches.append(b_num)
                for item in batches_dict[b_num]:
                    item_id = getattr(item, 'item_id', None) if hasattr(item, 'item_id') else item.get('item_id')

                    if item_id:
                        unique_items[item_id] = item
                    else:
                        unique_items[id(item)] = item

        # Если батчи запросили, но в спецификации их не оказалось
        if not unique_items:
            return [], ",".join(applied_batches)

        flat_items = list(unique_items.values())

        # Сортировка по номеру двери для отчета
        def parse_mark(it):
            mark = getattr(it, 'mark', None) if hasattr(it, 'mark') else it.get('mark')
            try:
                return int(mark)
            except (ValueError, TypeError):
                return 999999

        flat_items.sort(key=parse_mark)

        if len(getattr(spec_obj, 'batches', {}) or {}) == 1:
            batches_label = ""
        else:
            batches_label = ", ".join(applied_batches)

        return flat_items, batches_label

    @staticmethod
    def _extract_items(spec_or_items):
        """Вспомогательный метод для распаковки позиций из OrderSpec или прямого списка."""
        if isinstance(spec_or_items, list):
            return spec_or_items
        batches = getattr(spec_or_items, 'batches', {})
        return [it for b in batches.values() for it in b]

    def generate_measurement_report_html(self, validate=True):
        """
        Генерация отчета замеров (דוח מדידה) для всех активных батчей первой фазы.
        Строго отсекает группы без номера батча и со статусом CANCELED.
        """
        if validate:
            val_res = OrderValidationService.validate_for_report(self.order, report_type='PHASE1_FRAMES')
            val_res.raise_if_invalid()

        # 1. Берем спецификацию первой фазы
        order_spec, _ = TechnicalSpecService.get_or_build_spec(self.order, phase='phase1')

        # 2. Находим все батчи, которые реально принадлежат запущенным группам
        # (исключая новые, ожидающие и отмененные)
        valid_groups = self.order.groups.filter(
            is_split_installation=True,
            batch_number__isnull=False
        ).exclude(
            production_state=OrderItemsGroup.ProductionState.CANCELED
        )

        active_batch_numbers = list(valid_groups.values_list('batch_number', flat=True).distinct())

        if not active_batch_numbers:
            return ""  # Нет запущенных батчей с раздельным монтажом

        # 3. Извлекаем позиции только по этим валидным батчам через ваш метод-прослойку
        flat_items, batches_label = self.extract_report_items(
            order_spec,
            requested_batches=active_batch_numbers
        )

        if not flat_items:
            flat_items = []

        # 4. Рендерим шаблон отчета
        template = 'production/alum_frames_report.html'  # Или ваш шаблон замеров

        context = {
            'order': self.order,
            'order_spec': order_spec,
            'spec_items': flat_items,
            'batches_label': batches_label,
            'groups_data': self.prepare_grouped_data(flat_items),
            'now': timezone.now(),
        }
        return render_to_string(template, context)

    @classmethod
    def get_wooden_frames_data(cls, spec_obj):
        frames_items = []
        for item in cls._extract_items(spec_obj):
            # Проверяем, является ли item словарем
            is_dict = isinstance(item, dict)

            has_frame = item.get('has_frame', True) if is_dict else getattr(item, 'has_frame', True)
            is_hidden = item.get('is_hidden_frame', False) if is_dict else getattr(item, 'is_hidden_frame', False)

            if not has_frame or is_hidden:
                continue

            frames_items.append({
                'mark': getattr(item, 'mark', '') if hasattr(item, 'mark') else item.get('mark', ''),
                'place': getattr(item, 'place', '') if hasattr(item, 'place') else item.get('place', '') or '',
                'opening_width': getattr(item, 'opening_width', None) if hasattr(item, 'opening_width') else item.get(
                    'opening_width', None) or (getattr(item, 'width', '') if hasattr(item, 'width') else item.get(
                    'width', '')),
                'opening_height': getattr(item, 'opening_height', None) if hasattr(item,
                                                                                   'opening_height') else item.get(
                    'opening_height', None) or (getattr(item, 'height', '') if hasattr(item, 'height') else item.get(
                    'height', '')),
                'wall_thickness': getattr(item, 'wall', '') if hasattr(item, 'wall') else item.get('wall', '') or (
                    getattr(item, 'wall_thickness', '') if hasattr(item, 'wall_thickness') else item.get(
                        'wall_thickness', '')),
                'direction': getattr(item, 'direction', '') if hasattr(item, 'direction') else item.get('direction',
                                                                                                        ''),
                'opening': getattr(item, 'opening', '') if hasattr(item, 'opening') else item.get('opening', ''),
                'color_frames': getattr(item, 'color_frames', '') if hasattr(item, 'color_frames') else item.get(
                    'color_frames', '') or (getattr(item, 'color', '') if hasattr(item, 'color') else item.get('color',
                                                                                                               '')),
                'lock_name': getattr(item, 'lock_name', '') if hasattr(item, 'lock_name') else item.get('lock_name',
                                                                                                        ''),
                'hinge_name': getattr(item, 'hinge_name', '') if hasattr(item, 'hinge_name') else item.get('hinge_name',
                                                                                                           ''),
                'comment': getattr(item, 'comment', '') if hasattr(item, 'comment') else item.get('comment', ''),
            })
        return frames_items

    @classmethod
    def get_warehouse_hardware_summary(cls, spec_obj):
        from collections import defaultdict

        locks = defaultdict(int)
        handles = defaultdict(int)
        hinges = defaultdict(int)

        for item in cls._extract_items(spec_obj):  # ИСПОЛЬЗУЕМ _extract_items
            lock = getattr(item, 'lock_name', None) if hasattr(item, 'lock_name') else item.get('lock_name')
            if lock:
                locks[lock] += 1

            handle = getattr(item, 'handle_name', None) if hasattr(item, 'handle_name') else item.get('handle_name')
            if handle:
                handles[handle] += 1

            hinge = getattr(item, 'hinge_name', None) if hasattr(item, 'hinge_name') else item.get('hinge_name')
            if hinge:
                raw_hinges = getattr(item, 'hinge_heights', []) if hasattr(item, 'hinge_heights') else item.get(
                    'hinge_heights', [])
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
    def prepare_wood_frames_report_data(cls, spec_obj):
        groups_map = {}

        for item in cls._extract_items(spec_obj):
            # Проверяем, является ли item словарем
            is_dict = isinstance(item, dict)

            has_frame = item.get('has_frame', True) if is_dict else getattr(item, 'has_frame', True)

            if not has_frame:
                continue

            bom_items = getattr(item, 'bom_items', []) if hasattr(item, 'bom_items') else item.get('bom_items', [])
            casing_names = [
                (getattr(b, 'common_name', None) if hasattr(b, 'common_name') else b.get('common_name', None)) or (
                    getattr(b, 'item_name', '') if hasattr(b, 'item_name') else b.get('item_name', ''))
                for b in bom_items
                if (getattr(b, 'tag', '') if hasattr(b, 'tag') else b.get('tag', '')) in ('door_casing', 'casing')
                or (getattr(b, 'section', '') if hasattr(b, 'section') else b.get('section', '')) in ('door_casing',
                                                                                                      'casing', 'הלבשה',
                                                                                                      'הלבשות')
            ]
            paint_opt = getattr(item, 'frame_paint_option', None) if hasattr(item, 'frame_paint_option') else item.get(
                'frame_paint_option', None)
            frame_finish_display = "צבע" if paint_opt and str(paint_opt).upper() != 'NO_PAINT' else ""
            frames_caption = ''
            for b in bom_items:
                b_tag = getattr(b, 'tag', '') if hasattr(b, 'tag') else b.get('tag', '')
                b_sec = getattr(b, 'section', '') if hasattr(b, 'section') else b.get('section', '')

                if b_tag == 'frame' or b_sec == 'frame':
                    common_name = getattr(b, 'common_name', None) if hasattr(b, 'common_name') else b.get('common_name',
                                                                                                          None)
                    if common_name:
                        frames_caption = str(common_name).strip()
                        break

            if not frames_caption:
                frames_caption = getattr(item, 'frame', '') if hasattr(item, 'frame') else item.get('frame', '')
            frames_caption += " " + frame_finish_display
            door_casing = " / ".join(dict.fromkeys(filter(None, casing_names))) or "-"

            raw_cmz = getattr(item, 'frames_report_customizers', []) if hasattr(item,
                                                                                'frames_report_customizers') else item.get(
                'frames_report_customizers', [])
            cmz_signature = []
            for c in raw_cmz:
                c_name = c.get('name') if isinstance(c, dict) else getattr(c, 'name', '')
                c_params = c.get('params', []) if isinstance(c, dict) else getattr(c, 'params', [])
                p_strs = [f"{p.get('label')}:{p.get('value')}" for p in c_params]
                cmz_signature.append(f"{c_name}({', '.join(p_strs)})")
            cmz_key = " + ".join(cmz_signature)
            raw_hinges = getattr(item, 'hinge_heights', []) if hasattr(item, 'hinge_heights') else item.get(
                'hinge_heights', [])
            hinges_tuple = tuple(h for h in raw_hinges if h is not None)

            group_key = (
                (getattr(item, 'product_family', '') if hasattr(item, 'product_family') else item.get('product_family',
                                                                                                      '')) or (
                    getattr(item, 'product_name', '') if hasattr(item, 'product_name') else item.get('product_name',
                                                                                                     '')),
                getattr(item, 'series', '') if hasattr(item, 'series') else item.get('series', ''),
                getattr(item, 'frame', '') if hasattr(item, 'frame') else item.get('frame', ''),
                door_casing,
                getattr(item, 'basic_color_frames', '') if hasattr(item, 'basic_color_frames') else item.get(
                    'basic_color_frames', ''),
                getattr(item, 'color_frames', '') if hasattr(item, 'color_frames') else item.get('color_frames', ''),
                getattr(item, 'lock_name', '') if hasattr(item, 'lock_name') else item.get('lock_name', ''),
                getattr(item, 'lock_height', None) if hasattr(item, 'lock_height') else item.get('lock_height', None),
                getattr(item, 'hinge_name', '') if hasattr(item, 'hinge_name') else item.get('hinge_name', ''),
                hinges_tuple,
                cmz_key,
            )

            if group_key not in groups_map:
                groups_map[group_key] = {
                    'product_name': (getattr(item, 'product_family', '') if hasattr(item,
                                                                                    'product_family') else item.get(
                        'product_family', '')) or (getattr(item, 'product_name', '') if hasattr(item,
                                                                                                'product_name') else item.get(
                        'product_name', '')),
                    'frames_caption': frames_caption,

                    'door_casing': door_casing,

                    'lock_name': getattr(item, 'lock_name', '') if hasattr(item, 'lock_name') else item.get('lock_name',
                                                                                                            ''),
                    'lock_height': getattr(item, 'lock_height', None) if hasattr(item, 'lock_height') else item.get(
                        'lock_height', None),
                    'hinge_name': getattr(item, 'hinge_name', '') if hasattr(item, 'hinge_name') else item.get(
                        'hinge_name', ''),
                    'hinge_heights': list(hinges_tuple),
                    'customizers_title': cmz_key,
                    'items': [],
                    'size_counter': Counter(),
                }

            w = getattr(item, 'width', None) if hasattr(item, 'width') else item.get('width', None)
            h = getattr(item, 'height', None) if hasattr(item, 'height') else item.get('height', None)
            wall = getattr(item, 'wall', None) if hasattr(item, 'wall') else item.get('wall', None)

            groups_map[group_key]['items'].append(item)
            if w and h:
                groups_map[group_key]['size_counter'][(h, w, wall)] += 1

        result_groups = []
        for grp in groups_map.values():
            raw_counter = grp.pop('size_counter')
            sorted_sizes = sorted(
                raw_counter.items(),
                key=lambda x: (x[0][0], x[0][1], x[0][2] or 0),
                reverse=True
            )
            grp['aggregated_sizes'] = [
                {'height': h, 'width': w, 'wall': wall, 'qty': count}
                for (h, w, wall), count in sorted_sizes
            ]

            def parse_mark(it):
                try:
                    return int(getattr(it, 'mark', 0) if hasattr(it, 'mark') else it.get('mark', 0) or 0)
                except (ValueError, TypeError):
                    return 999999

            grp['items'].sort(key=parse_mark)

            # Формирование сгруппированных строк для печатного отчета משקופים
            row_groups = {}
            for it in grp['items']:
                w = getattr(it, 'width', None) if hasattr(it, 'width') else it.get('width', None)
                h = getattr(it, 'height', None) if hasattr(it, 'height') else it.get('height', None)
                wall = getattr(it, 'wall', None) if hasattr(it, 'wall') else it.get('wall', None)
                direction = getattr(it, 'direction', '') if hasattr(it, 'direction') else it.get('direction', '')
                opening = getattr(it, 'opening', '') if hasattr(it, 'opening') else it.get('opening', '')
                comment = getattr(it, 'comment', '') if hasattr(it, 'comment') else it.get('comment', '')
                place = getattr(it, 'place', '') if hasattr(it, 'place') else it.get('place', '')

                row_key = (w, h, wall, direction or '', opening or '', (comment or '').strip(), (place or '').strip())
                if row_key not in row_groups:
                    row_groups[row_key] = {
                        'width': w,
                        'height': h,
                        'wall': wall,
                        'direction': direction,
                        'opening': opening,
                        'comment': (comment or '').strip(),
                        'place': (place or '').strip(),
                        'qty': 0,
                    }
                row_groups[row_key]['qty'] += 1

            grouped_rows = []
            for r in row_groups.values():
                w = r['width']
                h = r['height']
                wall = r['wall']
                direction = r['direction']
                opening = r['opening']
                comment = r['comment']
                place = r['place']
                qty = r['qty']

                w_str = str(int(w)) if (w is not None and float(w).is_integer()) else (str(w) if w is not None else "")
                h_str = str(int(h)) if (h is not None and float(h).is_integer()) else (str(h) if h is not None else "")
                wall_str = str(int(wall)) if (wall is not None and float(wall).is_integer()) else (
                    str(wall) if wall is not None else "")

                dim_display = f"{w_str} \\ {h_str} \t {wall_str}{direction}"

                notes_list = []
                if comment:
                    notes_list.append(comment)
                if opening in ('OUT', 'החוצה'):
                    notes_list.append('החוצה')
                elif place and not comment:
                    notes_list.append(place)

                note_text = " ".join(notes_list)
                qty_label = f"{qty}x" if qty > 1 else ""

                grouped_rows.append({
                    'qty': qty,
                    'qty_label': qty_label,
                    'note_text': note_text,
                    'dimension_display': dim_display,
                    'width': w,
                    'height': h,
                    'wall': wall,
                    'direction': direction,
                    'opening': opening,
                })

            grp['grouped_rows'] = grouped_rows

            hinge_heights = grp.get('hinge_heights', [])
            grp['hinge_heights_display'] = " \\ ".join(
                str(int(hh)) if float(hh).is_integer() else str(hh) for hh in hinge_heights
            ) if hinge_heights else ""

            casing_val = grp.get('door_casing', '')
            if not casing_val or casing_val.strip() in ('-', 'ללא'):
                grp['door_casing_display'] = 'ללא'
            else:
                grp['door_casing_display'] = casing_val.strip()

            result_groups.append(grp)

        return result_groups

    @classmethod
    def get_order_customizable_hardware(cls, order, spec_obj):
        from apps.catalog.models import Hardware

        common_names = set()
        for item in cls._extract_items(spec_obj):  # ИСПОЛЬЗУЕМ _extract_items
            for bom_item in getattr(item, 'bom_items', []) if hasattr(item, 'bom_items') else item.get('bom_items', []):
                c_name = getattr(bom_item, 'common_name', None) if hasattr(bom_item, 'common_name') else bom_item.get(
                    'common_name', None)
                if c_name:
                    common_names.add(c_name.strip())

        saved_selections = {
            s.common_name: s.selected_hardware_id
            for s in order.component_selections.all()
        }

        result = []
        for c_name in sorted(common_names):
            items_qs = Hardware.objects.filter(
                common_name=c_name,
                active=True,
                color__isnull=False
            ).select_related('color')

            colors_count = items_qs.values('color').distinct().count()
            if colors_count > 1:
                options = [
                    {
                        'id': h.id,
                        'name': h.name,
                        'color_name': h.color.name if h.color else '',
                        'sku': h.sku,
                    }
                    for h in items_qs
                ]
                result.append({
                    'common_name': c_name,
                    'options': options,
                    'selected_id': saved_selections.get(c_name),
                })

        return result

    @classmethod
    def prepare_warehouse_packing_slip_data(cls, order, spec_obj):
        from collections import defaultdict
        from apps.catalog.models import Hardware

        saved_selections = {
            s.common_name: s.selected_hardware
            for s in order.component_selections.select_related('selected_hardware__color').all()
        }

        handles_count = defaultdict(int)
        locks_count = defaultdict(int)
        hinges_count = defaultdict(int)
        bom_hardware_count = defaultdict(lambda: {'qty': 0, 'sku': '', 'obj': None, 'common_name': ''})

        processed_common_names = set()

        for item in cls._extract_items(spec_obj):  # ИСПОЛЬЗУЕМ _extract_items
            handle_name = getattr(item, 'handle_name', None) if hasattr(item, 'handle_name') else item.get(
                'handle_name', None) or getattr(order, 'handle_name', None)
            if not handle_name and getattr(order, 'handle', None):
                handle_name = order.handle.name
            if handle_name and (
                    getattr(item, 'has_door', True) if hasattr(item, 'has_door') else item.get('has_door', True)):
                handles_count[handle_name] += 1

            lock = getattr(item, 'lock_name', None) if hasattr(item, 'lock_name') else item.get('lock_name', None)
            if lock and (getattr(item, 'has_door', True) if hasattr(item, 'has_door') else item.get('has_door', True)):
                locks_count[lock] += 1

            hinge = getattr(item, 'hinge_name', None) if hasattr(item, 'hinge_name') else item.get('hinge_name', None)
            if hinge:
                raw_hinges = getattr(item, 'hinge_heights', []) if hasattr(item, 'hinge_heights') else item.get(
                    'hinge_heights', [])
                count = len([h for h in raw_hinges if h is not None])
                hinges_count[hinge] += count if count > 0 else 3

            for bom_item in getattr(item, 'bom_items', []) if hasattr(item, 'bom_items') else item.get('bom_items', []):
                tag = getattr(bom_item, 'tag', '') if hasattr(bom_item, 'tag') else bom_item.get('tag', '')
                if tag in ('lock', 'hinges', 'frame', 'covering', 'base', 'filling', 'door_casing', 'casing'):
                    continue

                item_name = getattr(bom_item, 'item_name', '') if hasattr(bom_item, 'item_name') else bom_item.get(
                    'item_name', '')
                c_name = getattr(bom_item, 'common_name', '') if hasattr(bom_item, 'common_name') else bom_item.get(
                    'common_name', '')
                sku = getattr(bom_item, 'sku', '') if hasattr(bom_item, 'sku') else bom_item.get('sku', '')
                qty = float(
                    getattr(bom_item, 'quantity', 1) if hasattr(bom_item, 'quantity') else bom_item.get('quantity', 1))

                if item_name:
                    key = c_name or item_name
                    bom_hardware_count[key]['qty'] += qty
                    bom_hardware_count[key]['sku'] = sku
                    bom_hardware_count[key]['common_name'] = c_name

        color_variants_items = []
        regular_hardware_items = []

        for key, data in bom_hardware_count.items():
            c_name = data['common_name']
            if c_name:
                color_qs = Hardware.objects.filter(common_name=c_name, active=True, color__isnull=False).select_related(
                    'color')
                if color_qs.values('color').distinct().count() > 1:
                    processed_common_names.add(c_name)
                    chosen_hw = saved_selections.get(c_name)

                    if chosen_hw:
                        color_variants_items.append({
                            'common_name': c_name,
                            'name': chosen_hw.name,
                            'color_name': chosen_hw.color.name if chosen_hw.color else '',
                            'sku': chosen_hw.sku,
                            'qty': int(data['qty']) if data['qty'].is_integer() else data['qty'],
                            'is_selected': True,
                        })
                    else:
                        available_options = [
                            {'name': h.name, 'color': h.color.name if h.color else '', 'sku': h.sku}
                            for h in color_qs
                        ]
                        color_variants_items.append({
                            'common_name': c_name,
                            'name': c_name,
                            'color_name': 'טרם נבחר / לבחירת לקוח',
                            'sku': '-',
                            'qty': int(data['qty']) if data['qty'].is_integer() else data['qty'],
                            'is_selected': False,
                            'available_options': available_options,
                        })
                    continue

            regular_hardware_items.append({
                'name': key,
                'sku': data['sku'],
                'qty': int(data['qty']) if data['qty'].is_integer() else data['qty'],
            })

        groups = []

        if handles_count:
            groups.append({
                'title': 'ידיות ורוזטות (Ручки и розетки)',
                'items': [{'name': k, 'qty': v, 'sku': ''} for k, v in sorted(handles_count.items())]
            })

        if locks_count:
            groups.append({
                'title': 'מנעולים וצילינדרים (Замки и цилиндры)',
                'items': [{'name': k, 'qty': v, 'sku': ''} for k, v in sorted(locks_count.items())]
            })

        if hinges_count:
            groups.append({
                'title': 'צירים (Петли - штучный подсчет)',
                'items': [{'name': k, 'qty': v, 'sku': ''} for k, v in sorted(hinges_count.items())]
            })

        if color_variants_items:
            groups.append({
                'title': 'רכיבים לפי גוון (Комплектующие с выбором цвета)',
                'is_color_group': True,
                'items': color_variants_items
            })

        if regular_hardware_items:
            groups.append({
                'title': 'פרזול משלים ומעצורים (Стопоры и доп. фурнитура из BOM)',
                'items': regular_hardware_items
            })

        return groups

    def _write_xml_files(self, target_dir, spec, item_type):
        """
        Helper method for writing XML files to the specified directory.
        Designed for future expansion of XML generation logic.
        """
        # Generate hinges.xml
        hinges_content = self._generate_hinges_xml(spec, item_type)
        with open(os.path.join(target_dir, 'hinges.xml'), 'w', encoding='utf-8') as f:
            f.write(hinges_content)

        # Generate lock.xml
        lock_content = self._generate_lock_xml(spec, item_type)
        with open(os.path.join(target_dir, 'lock.xml'), 'w', encoding='utf-8') as f:
            f.write(lock_content)

    @staticmethod
    def _generate_hinges_xml(spec, item_type):
        """
        Generates content for hinges.xml.
        Currently, a placeholder, rules will be added in the future.
        """
        return '<?xml version="1.0" encoding="UTF-8"?>\n<hinges>\n  <status>placeholder</status>\n  <item_id>' + str(
            spec.item_id) + str(item_type) + '</item_id>\n</hinges>'

    @staticmethod
    def _generate_lock_xml(spec, item_type):
        """
        Generates content for lock.xml.
        Currently, a placeholder, rules will be added in the future.
        """
        return '<?xml version="1.0" encoding="UTF-8"?>\n<lock>\n  <status>placeholder</status>\n  <item_id>' + str(
            spec.item_id) + str(item_type) + '</item_id>\n</lock>'

    def generate_report_html(self, report_type=None, station_code=None, batch_number=None, validate=True):
        """
        Creates an HTML file for the requested technical report.
        Builds report strictly for requested batch_number, or aggregates all batches if batch_number is None.
        """
        station = None
        if station_code:
            station = ProductionStation.objects.filter(code=station_code).first()

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

            if not getattr(self.order, 'has_split_installation', False):
                if report_type == self.ReportType.PHASE2_DOORS:
                    label = 'Doors'

        phase = 'phase1' if (
                report_type == self.ReportType.PHASE1_FRAMES or (station and station.is_phase1)) else 'phase2'

        # Получаем спецификацию заказа из единого шлюза
        order_spec, _ = TechnicalSpecService.get_or_build_spec(self.order, phase=phase)

        # 1. Извлечение позиций: конкретный батч или все доступные батчи
        if batch_number is not None:
            raw_spec_items = order_spec.batches.get(str(batch_number), [])
        else:
            raw_spec_items = [it for b_items in order_spec.batches.values() for it in b_items]

        # 2. Фильтрация по участку/типу отчета (коробки, двери и т.д.)
        filtered_items = self.get_filtered_items(report_type, station=station)
        filtered_item_ids = {item.id for item in filtered_items}

        target_items = [it for it in raw_spec_items if it.item_id in filtered_item_ids]

        # 3. Клонирование структуры OrderSpec с выбранными позициями для рендера
        order_spec_for_report = order_spec.model_copy()
        order_spec_for_report.batches = {
            str(batch_number or "all"): target_items
        }

        if self.order.status in [OrderStatus.PHASE1_PRODUCTION]:
            stage_label = "שלב א'"
        elif self.order.status in [OrderStatus.PHASE2_PRODUCTION, OrderStatus.PHASE1_READY]:
            stage_label = "שלב ב'"
        elif self.order.status == OrderStatus.COMPLETION_PRODUCTION:
            stage_label = "השלמות"
        else:
            stage_label = "קומפלט"

        context = {
            'order': self.order,
            'batch_number': batch_number,
            'order_spec': order_spec_for_report,
            'spec_items': target_items,
            'order_spec_json': order_spec_for_report.model_dump_json(by_alias=True),
            'svg_patterns': SvgPattern.objects.all(),
            'report_type': report_type,
            'station': station,
            'report_label': label,
            'stage_label': stage_label,
            'groups_data': self.prepare_grouped_data(target_items),
            'panel_groups': self.prepare_press_groups_data(target_items),
            'now': timezone.now(),
        }
        return render_to_string(template, context)

    def get_filtered_items(self, report_type=None, station=None):
        """
        Returns a list of items that belong to the specified report or station.
        """
        items = []
        is_completion = self.order.status == OrderStatus.COMPLETION_PRODUCTION

        from .models import ProductionRoute

        for group in self.order.groups.all():
            if group.production_state in [
                OrderItemsGroup.ProductionState.WAITING,
                OrderItemsGroup.ProductionState.CANCELED,
            ]:
                continue

            if is_completion and group.production_state == OrderItemsGroup.ProductionState.COMPLETED:
                continue

            # Получаем динамический список станций для группы
            group_stations = ProductionRoute.get_stations_for_group(group)
            group_station_codes = [s.code for s in group_stations if s.code]

            if station:
                # Надежная проверка по ID (защита от сравнения разных объектов памяти)
                is_valid = any(s.id == station.id for s in group_stations)
            else:
                # Фолбэки для стандартных типов отчетов, когда station_code не передан
                rt = str(report_type).upper()
                group_codes_upper = {c.upper() for c in group_station_codes}

                if rt in ['PHASE1_FRAMES', 'PHASE1_PRODUCTION', 'PHASE2_FRAMES', 'FRAMES', 'ALUM_FRAMES', 'WOOD_FRAMES',
                          '100']:
                    is_valid = bool(
                        group_codes_upper & {'FRAMES', 'ALUM_FRAMES', 'WOOD_FRAMES', 'WOODEN_FRAMES', '100'})
                elif rt in ['PHASE2_DOORS', 'DOORS', 'ALUM_DOORS']:
                    is_valid = bool(group_codes_upper & {'DOORS', 'ALUM_DOORS'})
                elif rt in ['PHASE2_PRESS', 'PRESS', 'CUTTING_PRESS', 'CUT_SHEETS']:
                    is_valid = bool(group_codes_upper & {'PRESS', 'CUTTING_PRESS', 'CUT_SHEETS'})
                elif rt in ['FACING', 'CLADDING', 'FACING_REPORT']:
                    is_valid = bool(group_codes_upper & {'FACING', 'CLADDING', 'FACING_REPORT'})
                else:
                    is_valid = True

            if is_valid:
                for item in group.items.all():
                    items.append(item)

        return items

    @staticmethod
    def prepare_grouped_data(items):
        """
        Converts a flat list of ProductionSpec items (or dicts) into a grouped structure.
        """
        # 1. Grouping logic (сразу перебираем переданный список items)
        grouped_specs = {}
        for spec in items:
            key = (
                getattr(spec, 'product_family', '') if hasattr(spec, 'product_family') else spec.get('product_family',
                                                                                                     ''),
                getattr(spec, 'series', '') if hasattr(spec, 'series') else spec.get('series', ''),
                getattr(spec, 'product_code', '') if hasattr(spec, 'product_code') else spec.get('product_code', ''),
                getattr(spec, 'front_name', '') if hasattr(spec, 'front_name') else spec.get('front_name', ''),
                getattr(spec, 'basic_color_frames', '') if hasattr(spec, 'basic_color_frames') else spec.get(
                    'basic_color_frames', ''),
                getattr(spec, 'frame_paint_option', '') if hasattr(spec, 'frame_paint_option') else spec.get(
                    'frame_paint_option', ''),
                getattr(spec, 'color_frames', '') if hasattr(spec, 'color_frames') else spec.get('color_frames', ''),
                getattr(spec, 'color_panel_outside', '') if hasattr(spec, 'color_panel_outside') else spec.get(
                    'color_panel_outside', ''),
                tuple(getattr(spec, 'profiles', []) if hasattr(spec, 'profiles') else spec.get('profiles', [])),
            )
            if key not in grouped_specs:
                grouped_specs[key] = []
            grouped_specs[key].append(spec)

        # 2. Form result structure
        groups_data = []
        sorted_keys = sorted(grouped_specs.keys())

        for key in sorted_keys:
            items_specs = grouped_specs[key]
            first = items_specs[0]

            common_front = getattr(first, 'front_name', '') if hasattr(first, 'front_name') else first.get('front_name',
                                                                                                           '')
            common_color_frames = getattr(first, 'color_frames', '') if hasattr(first, 'color_frames') else first.get(
                'color_frames', '')
            common_color_panels = getattr(first, 'color_panel_outside', '') if hasattr(first,
                                                                                       'color_panel_outside') else first.get(
                'color_panel_outside', '')

            for s in items_specs[1:]:
                s_front_name = getattr(s, 'front_name', '') if hasattr(s, 'front_name') else s.get('front_name', '')
                s_color_frames = getattr(s, 'color_frames', '') if hasattr(s, 'color_frames') else s.get('color_frames',
                                                                                                         '')
                s_color_panel_outside = getattr(s, 'color_panel_outside', '') if hasattr(s,
                                                                                         'color_panel_outside') else s.get(
                    'color_panel_outside', '')

                if s_front_name != common_front: common_front = "Various"
                if s_color_frames != common_color_frames: common_color_frames = "Various"
                if s_color_panel_outside != common_color_panels: common_color_panels = "Various"

            group_spec = {
                'product_name': getattr(first, 'product_name', '') if hasattr(first, 'product_name') else first.get(
                    'product_name', ''),
                'code': getattr(first, 'product_code', '') if hasattr(first, 'product_code') else first.get(
                    'product_code', ''),
                'front_name': common_front,
                'color_frames': common_color_frames,
                'basic_color_frames': getattr(first, 'basic_color_frames', '') if hasattr(first,
                                                                                          'basic_color_frames') else first.get(
                    'basic_color_frames', ''),
                'color_panels': common_color_panels,
                'lock_name': getattr(first, 'lock_name', '') if hasattr(first, 'lock_name') else first.get('lock_name',
                                                                                                           ''),
                'hinge_name': getattr(first, 'hinge_name', '') if hasattr(first, 'hinge_name') else first.get(
                    'hinge_name', ''),
                'common_lock_height': getattr(first, 'lock_height', '') if hasattr(first, 'lock_height') else first.get(
                    'lock_height', ''),
                'common_hinge_heights': getattr(first, 'hinge_heights', []) if hasattr(first,
                                                                                       'hinge_heights') else first.get(
                    'hinge_heights', []),
                'profiles': getattr(first, 'profiles', []) if hasattr(first, 'profiles') else first.get('profiles', []),
                'frame_paint_option': getattr(first, 'frame_paint_option', '') if hasattr(first,
                                                                                          'frame_paint_option') else first.get(
                    'frame_paint_option', ''),
                'frame': getattr(first, 'frame', '') if hasattr(first, 'frame') else first.get('frame', ''),
                'series': getattr(first, 'series', '') if hasattr(first, 'series') else first.get('series', ''),
                'product_family': getattr(first, 'product_family', '') if hasattr(first,
                                                                                  'product_family') else first.get(
                    'product_family', ''),
                'frames_report_customizers': getattr(first, 'frames_report_customizers', []) if hasattr(first,
                                                                                                        'frames_report_customizers') else first.get(
                    'frames_report_customizers', []),
            }

            groups_data.append({
                'group_spec': group_spec,
                'items_specs': items_specs,
            })
        return groups_data

    @staticmethod
    def prepare_press_groups_data(items):
        """
        Groups door panels for press report from a list of ProductionSpec items (or dict snapshots).
        Calculates press blank dimensions from net panel dimensions:
        - Standard doors: W + 1, H + 1
        - Wood edge doors:
            W_press = W_panel - (2 * T) + 1
            H_press = H_panel - T * ((sides > 2) + (sides > 3)) + 1
        """
        groups_map = {}

        def _get(obj, key, default=None):
            return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

        for item in items:
            if not _get(item, 'has_door', True):
                continue

            # 1. Wood edge parameters
            has_edge = _get(item, 'has_wood_edge', False)
            is_hidden = _get(item, 'is_hidden_wood_edge', False)
            thickness = float(_get(item, 'wood_edge_thickness', 0) or 0) / 10
            sides = int(_get(item, 'wood_edge_sides', 4) or 4)

            if not has_edge:
                ctx = _get(item, 'context', {}) or {}
                we = ctx.get('wood_edge') if isinstance(ctx, dict) else None
                if we:
                    has_edge = True
                    is_hidden = we.get('is_hidden', False)
                    thickness = float(we.get('thickness', 0) or 0)
                    sides = int(we.get('sides', 4) or 4)

            # 2. Base & filling layers from BOM
            bom_items = _get(item, 'bom_items', []) or []

            def _bom_name(b):
                return _get(b, 'common_name') or _get(b, 'item_name') or ''

            base_names = [_bom_name(b) for b in bom_items if _get(b, 'tag') == 'base' and _bom_name(b)]
            filling_names = [_get(b, 'item_name') for b in bom_items if
                             _get(b, 'tag') == 'filling' and _get(b, 'item_name')]

            # 3. Covering layer (hidden edge vs FORMICA vs PAINT)
            finish_type = _get(item, 'finish_type', 'PAINT')
            if is_hidden:
                covering_names = ''
            elif finish_type == 'FORMICA':
                c_out = str(_get(item, 'color_panel_outside', '') or '').strip()
                c_in = str(_get(item, 'color_panel_inside', '') or '').strip()
                if c_in and c_in != c_out:
                    covering_names = " חוץ: {c_out} / פנים: {c_in}"
                elif c_out:
                    covering_names = c_out
            else:
                covering_names = [_bom_name(b) for b in bom_items if _get(b, 'tag') == 'covering' and _bom_name(b)][
                                     0] or ''

            raw_components = base_names + filling_names
            comp_title = "  |  ".join(dict.fromkeys(filter(None, raw_components))) or _get(item, 'product_name', '')

            # 4. Customizer presets & signature
            applied = _get(item, 'applied_presets', []) or []
            customizer_presets, sig_parts = [], []
            for p in applied:
                name = str(_get(p, 'name', '')).strip()
                if not name:
                    continue
                raw_labels = _get(p, 'labels', []) or []
                labels = [
                    {'text': str(_get(l, 'text', '')).strip(), 'is_custom': bool(_get(l, 'is_custom', False))}
                    for l in raw_labels if str(_get(l, 'text', '')).strip()
                ]
                customizer_presets.append({'name': name, 'labels': labels})
                lbl_suffix = f"({','.join(f'{l['text']}:{int(l['is_custom'])}' for l in labels)})" if labels else ""
                sig_parts.append(f"{name}{lbl_suffix}")

            presets_signature = " + ".join(dict.fromkeys(sig_parts))

            # 5. Group registration
            group_key = (comp_title, presets_signature)
            if group_key not in groups_map:
                puzzle = _get(item, 'puzzle_spec', None)
                groups_map[group_key] = {
                    'composition_title': comp_title,
                    'covering': covering_names,
                    'customizer_presets': customizer_presets,
                    'puzzle_face_blocks': _get(puzzle, 'face_blocks', []) if puzzle else [],
                    'puzzle_sandwich_blocks': _get(puzzle, 'sandwich_blocks', []) if puzzle else [],
                    'counter': Counter(),
                }

            # 6. Press dimensions calculation
            for p_dim in (_get(item, 'panel_dimensions', []) or []):
                w, h = _get(p_dim, 'width'), _get(p_dim, 'height')
                if w is None or h is None:
                    continue

                w, h = float(w), float(h)
                if has_edge and thickness > 0:
                    w -= thickness * 2
                    h -= thickness * ((sides > 2) + (sides > 3))

                groups_map[group_key]['counter'][(round_press_dimension(w), round_press_dimension(h))] += 1

        # 7. Format output grouped list
        panel_groups = []
        for grp in groups_map.values():
            dims = [
                {'width': w, 'height': h, 'qty': qty}
                for (w, h), qty in sorted(grp.pop('counter').items(), key=lambda x: (x[0][1], x[0][0]), reverse=True)
            ]
            if dims:
                grp['dimensions'] = dims
                panel_groups.append(grp)

        return panel_groups

    @classmethod
    def get_door_labels_data(cls, order, spec_obj, requested_batches: list = None):
        flat_items, _ = cls.extract_report_items(spec_obj, requested_batches)
        if not flat_items:
            return []

        labels_data = []
        for it in flat_items:
            if not (getattr(it, 'has_door', True) if hasattr(it, 'has_door') else it.get('has_door', True)):
                continue

            mark = getattr(it, 'mark', '') if hasattr(it, 'mark') else it.get('mark', '')
            direction = getattr(it, 'direction', '') if hasattr(it, 'direction') else it.get('direction', '')

            panel_dims = getattr(it, 'panel_dimensions', []) if hasattr(it, 'panel_dimensions') else it.get(
                'panel_dimensions', [])
            first_panel = panel_dims[0] if panel_dims else {}
            width = first_panel.get('width', '') or (
                getattr(it, 'width', '') if hasattr(it, 'width') else it.get('width', ''))
            height = first_panel.get('height', '') or (
                getattr(it, 'height', '') if hasattr(it, 'height') else it.get('height', ''))

            text_data = f"Order: {order.order_number}, Door: {mark}, W: {width}, H: {height}, Dir: {direction}"
            qr_base64 = get_qr_base64(text_data)

            labels_data.append({
                'order_number': order.order_number,
                'mark': mark,
                'width': width,
                'height': height,
                'direction': direction,
                'qr_code': qr_base64,
                'quantity': order.get_quantity(),
                'product_name': it.product_name,
            })
        return labels_data


class OrderProductionService:
    """
    Order production lifecycle management service.
    Moves production start and status transition logic from orders app to production.
    """

    @staticmethod
    def recalculate_item_marks(order):
        """
        Recalculates sequential numbers (mark) for all items in the order.
        """
        from apps.orders.models import OrderItem
        all_items = OrderItem.objects.filter(group__order=order).order_by('group__id', 'id')

        items_to_update = []
        for i, item in enumerate(all_items, start=1):
            new_mark = str(i)
            if item.mark != new_mark:
                item.mark = new_mark
                items_to_update.append(item)

        if items_to_update:
            OrderItem.objects.bulk_update(items_to_update, ['mark'])

    @staticmethod
    def cleanup_cnc_files(order):
        """
        Deletes the directory with CNC files for the order.
        """
        from django.conf import settings
        import os
        import shutil

        cnc_root = os.path.join(settings.BASE_DIR, 'cnc_files')
        mecal_dir = os.path.join(cnc_root, 'mecal')
        order_dir = os.path.join(mecal_dir, str(order.order_number))

        if os.path.exists(order_dir):
            shutil.rmtree(order_dir)

    @staticmethod
    def validate_for_production(order, validation_type: Optional[str] = None):
        """
        Validates order readiness for production.
        Returns (is_valid, errors).
        """
        if validation_type:
            res = OrderValidationService.validate(order, validation_type)
        elif order.has_split_installation and order.status == OrderStatus.NEW:
            res = OrderValidationService.validate_partial(order)
        else:
            res = OrderValidationService.validate_full(order)
        return res.is_valid, res.errors

    @staticmethod
    def _assign_release_batch(order) -> int:
        """
        Increments order.current_batch if there are NEW groups and assigns it to them.
        Returns the target batch number to process.
        """
        new_groups = order.groups.filter(
            production_state=OrderItemsGroup.ProductionState.NEW
        )
        if new_groups.exists():
            batch_num = order.current_batch
            # Убеждаемся, что всем новым группам назначен текущий батч
            new_groups.filter(batch_number__isnull=True).update(batch_number=batch_num)
            new_groups.update(production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION)

            # Закрываем батч намертво для будущих добавлений
            order.current_batch += 1
            order.save(update_fields=['current_batch'])
            return batch_num

        return order.current_batch

    from django.db import transaction

    @classmethod
    @transaction.atomic
    def start_production(cls, order, user=None):
        # 1. Validation
        val_res = cls.validate_for_production(order)
        if isinstance(val_res, tuple):
            is_valid, errors = val_res
            if not is_valid:
                raise OrderValidationError("Data validation error", errors=errors)
        else:
            val_res.raise_if_invalid()

        if not order.production_start_date:
            order.production_start_date = timezone.now()

        released_batch = order.current_batch or 1

        # -------------------------------------------------------------
        # SCENARIO A: Launching Phase 2 (doors after on-site measurements)
        # -------------------------------------------------------------
        if order.status == OrderStatus.PHASE1_READY:
            # Retrieve waiting door groups held back during Phase 1
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

            # Update group states and assign batch
            group_ids = [g.id for g in phase2_groups]
            OrderItemsGroup.objects.filter(id__in=group_ids).update(
                batch_number=released_batch,
                production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION,
                batch_date=date.today(),
            )

            # Refresh local objects state
            for g in phase2_groups:
                g.batch_number = released_batch
                g.production_state = OrderItemsGroup.ProductionState.IN_PRODUCTION
                g.batch_date = date.today()

            # Update order state
            order.status = OrderStatus.PHASE2_PRODUCTION
            order.current_batch = released_batch + 1
            order.save(update_fields=['status', 'current_batch', 'production_start_date'])

            # Initialize granular station tracking for Phase 2 door batches
            for group in phase2_groups:
                StationTrackingService.initialize_batch_progress(group)

            # Build specification for Phase 2 batch
            TechnicalSpecService.get_or_build_spec(
                order, phase='phase2', batch_number=released_batch, force_rebuild=True, user=user
            )
            return

        # -------------------------------------------------------------
        # SCENARIO B: Standard launch or Phase 1 start (NEW groups)
        # -------------------------------------------------------------
        new_groups_qs = order.groups.filter(
            production_state=OrderItemsGroup.ProductionState.NEW
        )
        if not new_groups_qs.exists():
            raise OrderValidationError("Нет новых групп для запуска в производство.")

        has_split = getattr(order, 'has_split_installation', False)

        if has_split:
            # Move doors to WAITING until on-site measurements are ready
            new_groups_qs.filter(is_split_installation=False).update(
                production_state=OrderItemsGroup.ProductionState.WAITING
            )
            # Launch only frame groups in Phase 1
            groups_to_launch = list(new_groups_qs.filter(is_split_installation=True))
            if not groups_to_launch:
                raise OrderValidationError("Нет подходящих групп с раздельным монтажом для запуска первой фазы.")

            order.status = OrderStatus.PHASE1_PRODUCTION
        else:
            # Standard complete sets (both frames and doors together)
            groups_to_launch = list(new_groups_qs)
            order.status = OrderStatus.IN_PRODUCTION

        # Update launched groups
        launch_ids = [g.id for g in groups_to_launch]
        OrderItemsGroup.objects.filter(id__in=launch_ids).update(
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

        # Initialize station tracking only for full production sets (skip Phase 1 frames)
        if order.status == OrderStatus.IN_PRODUCTION:
            for group in groups_to_launch:
                StationTrackingService.initialize_batch_progress(group)

        # Build technical specification for the launched batch
        phase = 'phase1' if order.status == OrderStatus.PHASE1_PRODUCTION else 'phase2'
        TechnicalSpecService.get_or_build_spec(
            order, phase=phase, batch_number=released_batch, force_rebuild=True, user=user
        )

    @staticmethod
    def complete_phase1(order, user=None):
        """
        Completes the first phase of production and transitions the order to PHASE1_READY status.
        """
        if order.status != OrderStatus.PHASE1_PRODUCTION:
            raise ValueError("Phase A completion is only possible for orders in 'Phase A Production' status")

        old_status = order.status
        with transaction.atomic():
            order.status = OrderStatus.PHASE1_READY
            order.save()

            # Clean up CNC files when transitioning to Phase A readiness
            OrderProductionService.cleanup_cnc_files(order)

            OrderChangeLog.objects.create(
                order=order,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=order.status
            )
        return order

    @staticmethod
    def complete_production(order, user=None):
        """
        Completes order production and transitions it to READY status.
        Marks all IN_PRODUCTION groups as COMPLETED.
        """
        if order.status not in [OrderStatus.IN_PRODUCTION, OrderStatus.PHASE2_PRODUCTION,
                                OrderStatus.COMPLETION_PRODUCTION]:
            raise ValueError(
                "Production completion is only possible for orders in 'In Production', 'Phase B Production' or 'Completion Production' status")

        old_status = order.status
        with transaction.atomic():
            order.status = OrderStatus.COMPLETED
            # Mark active groups as completed
            order.groups.filter(
                production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION
            ).update(production_state=OrderItemsGroup.ProductionState.COMPLETED)

            order.save()

            # Clean up CNC files upon production completion
            OrderProductionService.cleanup_cnc_files(order)

            OrderChangeLog.objects.create(
                order=order,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=order.status
            )
        return order
