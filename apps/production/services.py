import io
import math
import os
import shutil
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

from django.conf import settings
from django.db import models
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.orders.models import OrderItemsGroup, OrderItem, OrderStatus, OrderChangeLog
from .models import (
    ProductionStation, OrderSpecificationSnapshot, SvgPattern,
)
from .pipeline import OrderSpecPipeline
from .schemas import OrderSpec


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
    Validation service (data integrity check) for orders.
    Executed before production start, technical report generation, and CNC/ZIP file production.

    Supports validation types:
    1. PARTIAL (Phase A - frames in split installation):
       - Series and front/finish check for each group
       - Product model and item existence check in group
       - Item dimensions check (height and width for door/frame, wall thickness for frame, side/direction for door)
       - Handles are not checked at this stage.
    2. FULL (Phase B or regular order without split installation):
       - Includes all Phase A checks
       - Handle selection check
       - Paint color check when painting option is selected
    3. COMPLETION (Delta / Unfinished groups only):
       - Runs full validation for groups with production_state != COMPLETED.
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
        """
        Partial validation (Phase A - frames in split installation).
        """

        errors = cls._run_validation(order, is_full=False)
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            validation_type=ValidationType.PARTIAL
        )

    @classmethod
    def validate_full(cls, order) -> ValidationResult:
        """
        Full validation (Phase B or regular order without split installation).
        """

        errors = cls._run_validation(order, is_full=True)
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            validation_type=ValidationType.FULL
        )

    @classmethod
    def validate_completion(cls, order) -> ValidationResult:
        """
        Validation for completions / uncompleted groups only.
        """
        errors = cls._run_validation(order, is_full=True, completion_only=True)
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            validation_type=ValidationType.COMPLETION
        )

    @classmethod
    def validate_for_production(cls, order, phase: Optional[str] = None) -> ValidationResult:
        """
        Appropriate validation before transferring order to production.
        """
        if order.status == OrderStatus.COMPLETION_PRODUCTION or phase == 'phase2_completion':
            return cls.validate_completion(order)
        has_split = getattr(order, 'has_split_installation', False)
        if phase == str(order.status).upper() == 'PHASE1_PRODUCTION' or (
                has_split and getattr(order, 'status', None) == OrderStatus.NEW):
            return cls.validate_partial(order)
        return cls.validate_full(order)

    @classmethod
    def validate_for_report(cls, order,
                            report_type: Optional[str] = None,
                            station: Optional[ProductionStation] = None) -> ValidationResult:
        """
        Appropriate validation before technical report generation.
        For Phase A frames report (PHASE1_FRAMES) - partial check.
        For other reports (doors, press, full frames, full production) - full check.
        """
        if order.status == OrderStatus.COMPLETION_PRODUCTION:
            return cls.validate_completion(order)
        if station and not station.has_specification:
            # If station doesn't require specification, but we are here, do full validation
            return cls.validate_full(order)

        # Determine based on phase
        if report_type in ['PHASE1_FRAMES', 'PHASE1_PRODUCTION'] or (station and getattr(station, 'is_phase1', False)):
            return cls.validate_partial(order)
        return cls.validate_full(order)

    @classmethod
    def validate_for_phase(cls, order, phase: str) -> ValidationResult:
        """
        Validation for specific phase.
        """
        if phase == 'phase1':
            return cls.validate_partial(order)
        elif phase == 'phase2_completion':
            return cls.validate_completion(order)
        return cls.validate_full(order)

    @classmethod
    def validate_for_zip(cls, order) -> ValidationResult:
        """
        Appropriate validation before production file (ZIP) generation.
        """
        if order.status == OrderStatus.COMPLETION_PRODUCTION:
            return cls.validate_completion(order)
        has_split = getattr(order, 'has_split_installation', False)
        if has_split and getattr(order, 'status', None) == OrderStatus.PHASE1_PRODUCTION:
            return cls.validate_partial(order)
        return cls.validate_full(order)

    @classmethod
    def _run_validation(cls, order, is_full: bool, completion_only: bool = False) -> List[str]:
        errors = []

        if not getattr(order, 'order_number', None):
            errors.append("Order number missing")
        if not getattr(order, 'customer', None):
            errors.append("Customer name missing")

        active_groups_qs = order.groups.exclude(
            production_state__in=[
                OrderItemsGroup.ProductionState.WAITING,
                OrderItemsGroup.ProductionState.CANCELED,
            ]
        )

        if completion_only:
            groups = [g for g in active_groups_qs if g.production_state != OrderItemsGroup.ProductionState.COMPLETED]
            if not groups:
                errors.append("No active or uncompleted groups found for completion production")
                return errors
        else:
            groups = list(active_groups_qs)
            if not groups:
                errors.append("No active product groups in order")
                return errors

        has_any_doors = False

        for group in groups:
            group_name = group.product.name if group.product else f"Group #{group.id}"
            group_label = f"Group #{group.id} ({group_name})"

            if not group.product:
                errors.append(f"Group #{group.id}: Product model not selected")
                continue

            # 1. Series
            effective_series = group.series or getattr(order, 'series', None)
            if not effective_series:
                errors.append(f"{group_label}: Series not selected")

            # 2. Front / finish
            effective_front = group.front or getattr(order, 'front', None)
            if not effective_front:
                errors.append(f"{group_label}: Front / finish not selected")

            # 3. Colors in full validation (if a special shade is selected)
            if is_full:
                if group.panel_paint_option == OrderItemsGroup.PaintOption.SPECIAL_COLOR:
                    if not group.color_panel_outside and not getattr(order, 'color_panels', None):
                        errors.append(f"{group_label}: Special panel color selected but no panel color defined")
                if group.frame_paint_option == OrderItemsGroup.PaintOption.SPECIAL_COLOR:
                    if not group.basic_color_frames and not getattr(order, 'color_frames', None):
                        errors.append(f"{group_label}: Special frame color selected but no frame color defined")

            # 4. Items in a group
            items = list(group.items.all())
            if not items:
                errors.append(f"{group_label}: No items in group")
                continue

            product_type = None
            if group.product and group.product.product_family and group.product.product_family.product_type:
                product_type = group.product.product_family.product_type

            has_door = product_type.has_door if product_type else True
            has_frame = product_type.has_frame if product_type else True

            if has_door:
                has_any_doors = True

            for item in items:
                item_label = f"Item {item.mark}" if item.mark else f"Item #{item.id} ({group_label})"

                # Height and width check for door or frame
                if has_door or has_frame:
                    if item.height is None or item.height <= 0:
                        errors.append(f"{item_label}: Valid height not specified")
                    if item.width is None or item.width <= 0:
                        errors.append(f"{item_label}: Valid width not specified")

                # Wall thickness check for frame
                if has_frame:
                    if item.wall is None or item.wall <= 0:
                        errors.append(f"{item_label}: Wall thickness not specified (frame)")

                # Opening side and direction check for door
                if has_door:
                    if not item.opening:
                        errors.append(f"{item_label}: Opening side not selected (L/R)")
                    if not item.direction:
                        errors.append(f"{item_label}: Opening direction not selected (In/Out)")
                    elif group.product:
                        # Validate direction against product restrictions
                        allowed = getattr(group.product, 'allowed_direction', 'BOTH')
                        dir_val = str(item.direction).strip().upper()

                        # Handles both English ('IN', 'OUT') and Hebrew ('פנימה', 'החוצה') if used
                        is_in = dir_val in ('IN', 'INWARD', 'פנימה')
                        is_out = dir_val in ('OUT', 'OUTWARD', 'החוצה')

                        if allowed == 'IN_ONLY' and not is_in:
                            errors.append(
                                f"{item_label}: Model '{group.product.name}' only supports Inward (IN) opening"
                            )
                        elif allowed == 'OUT_ONLY' and not is_out:
                            errors.append(
                                f"{item_label}: Model '{group.product.name}' only supports Outward (OUT) opening"
                            )

                # 5. Required customizers and parameters check
            required_customizers = group.product.get_required_customizers()
            group_customizers = list(group.customizers.select_related('customizer').all())
            group_customizers_map = {gc.customizer_id: gc for gc in group_customizers}

            for req_cust in required_customizers:
                if req_cust.id not in group_customizers_map:
                    errors.append(f"{group_label}: Required customizer '{req_cust.name}' is missing")

            for gc in group_customizers:
                cust = gc.customizer
                for i in range(1, 6):
                    if getattr(cust, f'par{i}_required', False):
                        val = getattr(gc, f'par{i}', None)
                        if val is None or not str(val).strip():
                            param_label = getattr(cust, f'par{i}_label') or f"Parameter {i}"
                            errors.append(
                                f"{group_label} - {cust.name}: Parameter '{param_label}' is required and cannot be empty")

        # 6. Handle selection check in full validation (Phase B or no split installation)
        if is_full and has_any_doors:

            if not getattr(order, 'handle', None):
                errors.append("Handle not selected for order (required for Phase B / Full production)")

        return errors


class TechnicalSpecService:
    """
    Единый шлюз спецификаций заказа.
    Отвечает за сборку среза позиций, запуск пайплайна, сохранение и чтение снимков.
    Структура кэша в JSONField: {"batch_1": {...}, "batch_2": {...}}
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
                'group__customizers__customizer__materials',
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
        Иначе — прогоняет плоскую выборку позиций через пайплайн и фиксирует снимок в БД.
        """
        cache_field = 'phase1_spec_cache' if phase == 'phase1' else 'phase2_spec_cache'
        existing_cache = getattr(order, cache_field)

        # Защита от поврежденного кэша (если в поле лежал bool или None)
        if not isinstance(existing_cache, dict):
            existing_cache = {}

        batch_key = f"batch_{batch_number}" if batch_number is not None else "batch_all"

        # 1. Возврат из существующего снимка
        if not force_rebuild and batch_key in existing_cache:
            target_dict = existing_cache[batch_key]
            if isinstance(target_dict, dict):
                return OrderSpec.model_validate(target_dict), existing_cache

        # 2. Выборка позиций
        items = cls.get_rich_order_items(order_id=order.id, batch_number=batch_number)
        if not items:
            raise OrderValidationError(f"Нет активных позиций для формирования спецификации (batch={batch_number}).")

        # 3. Запуск пайплайна
        pipeline = OrderSpecPipeline()
        spec_obj = pipeline.execute(order, items=items, phase=phase)

        # Проверка ошибок расчетов в узлах
        errors = []
        for it in spec_obj.items:
            if it.errors:
                mark_label = f"Item {it.mark}" if it.mark else f"Item #{it.item_id}"
                errors.extend([f"{mark_label}: {err}" for err in it.errors])
        if errors:
            raise OrderValidationError("Ошибки при расчете спецификации:", errors=errors)

        # 4. Сериализация и сохранение снимка в базу
        spec_dict = spec_obj.model_dump()
        existing_cache[batch_key] = spec_dict
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
            spec_data=spec_dict,
            created_by=user
        )

        # Всегда возвращаем кортеж (объект спецификации, словарь кэша)
        return spec_obj, existing_cache

    @classmethod
    def get_batch_items(cls, order, phase: str = 'phase1', batch_number: int = 1) -> List[dict]:
        """
        Возвращает плоский список рассчитанных позиций из снимка для форм (например, перед Фазой 2).
        """
        cache_field = 'phase1_spec_cache' if phase == 'phase1' else 'phase2_spec_cache'
        cache = getattr(order, cache_field)
        if not isinstance(cache, dict):
            return []

        # Поддержка структуры с батчами и обратная совместимость со старыми плоскими снимками
        batch_dict = cache.get(f"batch_{batch_number}") or cache.get("batch_all")
        if isinstance(batch_dict, dict):
            return batch_dict.get('items', [])

        return cache.get('items', [])


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

    def generate_cnc_files(self, spec_items=None):
        """
        Standalone method to generate CNC files on the server filesystem.
        Creates folder structure cnc_files/mecal/<order_number>/ and fills it with XML files.
        If spec_items is provided, generates only for those items.
        If order is in COMPLETION_PRODUCTION, generates only for items from active/uncompleted groups.
        """
        is_phase_a = self.order.status == OrderStatus.PHASE1_PRODUCTION
        is_completion = self.order.status == OrderStatus.COMPLETION_PRODUCTION
        phase = 'phase1' if is_phase_a else 'phase2'

        if spec_items is not None:
            items_to_process = spec_items
        else:
            order_spec, _ = TechnicalSpecService.get_or_build_spec(self.order, phase=phase)
            items_to_process = order_spec.items
            if is_completion:
                active_item_ids = set(OrderItem.objects.filter(
                    group__order=self.order
                ).exclude(
                    group__production_state=OrderItemsGroup.ProductionState.COMPLETED
                ).values_list('id', flat=True))
                items_to_process = [it for it in items_to_process if it.item_id in active_item_ids]

        # Paths
        cnc_root = os.path.join(settings.BASE_DIR, 'cnc_files')
        mecal_dir = os.path.join(cnc_root, 'mecal')
        order_dir = os.path.join(mecal_dir, str(self.order.order_number))

        # Create base directories
        os.makedirs(mecal_dir, exist_ok=True)

        # Clean up order folder if it exists
        if os.path.exists(order_dir):
            shutil.rmtree(order_dir)
        os.makedirs(order_dir)

        # Create main subdirectories
        frames_root = os.path.join(order_dir, 'frames')
        doors_root = os.path.join(order_dir, 'doors')
        os.makedirs(frames_root)
        os.makedirs(doors_root)

        # Iterate through items in the order specification
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

    def generate_report_html(self, report_type=None, station_code=None, validate=True):
        """
        Creates an HTML file for the requested technical report.
        Performs validation before creation (unless validate=False).
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

            # Adjust label if no split installation in the whole order
            if not getattr(self.order, 'has_split_installation', False):
                if report_type == self.ReportType.PHASE2_DOORS:
                    label = 'Doors'

        # Use TechnicalSpecService as the single point of entry
        phase = 'phase1' if (
                report_type == self.ReportType.PHASE1_FRAMES or (station and station.is_phase1)) else 'phase2'
        order_spec, _ = TechnicalSpecService.get_or_build_spec(self.order, phase=phase)

        # Filter items if report_type or station is specified
        filtered_items = self.get_filtered_items(report_type, station=station)
        filtered_item_ids = [item.id for item in filtered_items]

        # Clone order_spec to avoid modifying the cached version if it's still in memory
        order_spec_for_report = order_spec.model_copy()
        order_spec_for_report.items = [item for item in order_spec.items if item.item_id in filtered_item_ids]

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
            'order_spec': order_spec_for_report,
            'order_spec_json': order_spec_for_report.model_dump_json(by_alias=True),
            'svg_patterns': SvgPattern.objects.all(),
            'report_type': report_type,
            'station': station,
            'report_label': label,
            'stage_label': stage_label,
            'groups_data': self.prepare_grouped_data(order_spec_for_report),
            'panel_groups': self.prepare_press_groups_data(order_spec_for_report),
            'now': timezone.now(),
        }
        return render_to_string(template, context)

    def get_filtered_items(self, report_type=None, station=None):
        """
        Returns a list of items that belong to the specified report or station.
        If the order is in COMPLETION_PRODUCTION, excludes items from COMPLETED groups.
        """
        items = []
        is_completion = self.order.status == OrderStatus.COMPLETION_PRODUCTION

        for group in self.order.groups.all():
            if group.production_state in [
                OrderItemsGroup.ProductionState.WAITING,
                OrderItemsGroup.ProductionState.CANCELED,
            ]:
                continue

            if is_completion and group.production_state == OrderItemsGroup.ProductionState.COMPLETED:
                continue

            is_split = group.is_split_installation
            product_type = None
            if group.product and group.product.product_family and group.product.product_family.product_type:
                product_type = group.product.product_family.product_type
            has_frame = product_type.has_frame if product_type else True
            has_door = product_type.has_door if product_type else True

            # Filter logic
            if station:
                from .models import ProductionRoute
                group_stations = ProductionRoute.get_stations_for_group(group)
                if station not in group_stations:
                    continue
            elif report_type in [self.ReportType.PHASE1_FRAMES, 'PHASE1_FRAMES', 'PHASE1_PRODUCTION']:
                if not is_split or not has_frame:
                    continue
            elif report_type in [self.ReportType.PHASE2_DOORS, 'PHASE2_DOORS']:
                if not has_door:
                    continue
            elif report_type in [self.ReportType.PHASE2_PRESS, 'PHASE2_PRESS']:
                if not has_door:
                    continue
            elif report_type in [self.ReportType.PHASE2_FRAMES, 'PHASE2_FRAMES']:
                if not has_frame:
                    continue

            for item in group.items.all():
                items.append(item)
        return items

    @staticmethod
    def prepare_grouped_data(order_spec):
        """
        Converts OrderSpec items into a grouped structure for legacy templates.
        """
        # 1. Grouping logic
        grouped_specs = {}
        for spec in order_spec.items:
            # Key for grouping: Product, Series, Front, Colors, and Profiles
            key = (
                spec.product_family,
                spec.series,
                spec.product_code,
                spec.front_name,
                spec.basic_color_frames,
                spec.frame_paint_option,
                spec.color_frames,
                spec.color_panel_outside,
                tuple(spec.profiles),
            )
            if key not in grouped_specs:
                grouped_specs[key] = []
            grouped_specs[key].append(spec)

        # 2. Form result structure
        groups_data = []
        # Sort by product name for consistent output
        sorted_keys = sorted(grouped_specs.keys())

        for key in sorted_keys:
            items_specs = grouped_specs[key]
            first = items_specs[0]

            # Common decorative params
            common_front = first.front_name
            common_color_frames = first.color_frames
            common_color_panels = first.color_panel_outside

            for s in items_specs[1:]:
                if s.front_name != common_front: common_front = "Various"
                if s.color_frames != common_color_frames: common_color_frames = "Various"
                if s.color_panel_outside != common_color_panels: common_color_panels = "Various"

            group_spec = {
                'product_name': first.product_name,
                'code': first.product_code,
                'front_name': common_front,
                'color_frames': common_color_frames,
                'basic_color_frames': first.basic_color_frames,
                'color_panels': common_color_panels,
                'lock_name': first.lock_name,
                'hinge_name': first.hinge_name,
                'common_lock_height': first.lock_height,
                'common_hinge_heights': first.hinge_heights,
                'profiles': first.profiles,
                'frame_paint_option': first.frame_paint_option,
                'frame': first.frame,
                'series': first.series,
                'product_family': first.product_family,
                'frames_report_customizers': first.frames_report_customizers,
            }

            groups_data.append({
                'group_spec': group_spec,
                'items_specs': items_specs,
            })
        return groups_data

    @staticmethod
    def prepare_press_groups_data(order_spec):
        groups_map = {}

        for item in getattr(order_spec, 'items', []):
            if not getattr(item, 'has_door', True):
                continue

            bom_items = getattr(item, 'bom_items', []) or []

            # 1. Основной состав: filling + covering + base
            filling_names = [
                b.item_name for b in bom_items
                if getattr(b, 'tag', '') == 'filling' and getattr(b, 'item_name', '')
            ]
            covering_names = [
                getattr(b, 'common_name', None) or b.item_name for b in bom_items
                if
                getattr(b, 'tag', '') == 'covering' and (getattr(b, 'common_name', None) or getattr(b, 'item_name', ''))
            ]
            base_names = [
                getattr(b, 'common_name', None) or b.item_name for b in bom_items
                if getattr(b, 'tag', '') == 'base' and (getattr(b, 'common_name', None) or getattr(b, 'item_name', ''))
            ]

            raw_components = base_names + covering_names + filling_names
            comp_title = "  |  ".join(dict.fromkeys(raw_components)) or getattr(item, 'product_name', '')

            # 2. Пресеты с вычисленными параметрами (labels)
            applied_presets = getattr(item, 'applied_presets', []) or []
            customizer_presets = []
            preset_signature_parts = []

            for p in applied_presets:
                p_name = str(p.get('name') if isinstance(p, dict) else getattr(p, 'name', '')).strip()
                if not p_name:
                    continue

                raw_labels = p.get('labels', []) if isinstance(p, dict) else getattr(p, 'labels', [])
                labels = []
                sig_labels = []

                for lbl in raw_labels:
                    text_val = str(lbl.get('text', '') if isinstance(lbl, dict) else getattr(lbl, 'text', '')).strip()
                    is_custom_val = bool(
                        lbl.get('is_custom', False) if isinstance(lbl, dict) else getattr(lbl, 'is_custom', False))
                    if text_val:
                        labels.append({
                            'text': text_val,
                            'is_custom': is_custom_val,
                        })
                        sig_labels.append(f"{text_val}:{'1' if is_custom_val else '0'}")

                customizer_presets.append({
                    'name': p_name,
                    'labels': labels,
                })

                # Подпись для корректного разделения групп при разных значениях параметров
                lbl_suffix = f"({','.join(sig_labels)})" if sig_labels else ""
                preset_signature_parts.append(f"{p_name}{lbl_suffix}")

            presets_signature = " + ".join(dict.fromkeys(preset_signature_parts))

            puzzle = getattr(item, 'puzzle_spec', None)
            face_blocks = getattr(puzzle, 'face_blocks', []) if puzzle else []
            sandwich_blocks = getattr(puzzle, 'sandwich_blocks', []) if puzzle else []

            # Группировка с учетом состава и параметров пресетов
            group_key = (comp_title, presets_signature)

            if group_key not in groups_map:
                groups_map[group_key] = {
                    'composition_title': comp_title,
                    'customizer_presets': customizer_presets,
                    'puzzle_face_blocks': face_blocks,
                    'puzzle_sandwich_blocks': sandwich_blocks,
                    'counter': Counter(),
                }

            # Direct panel dimensions calculation
            panel_dims = getattr(item, 'panel_dimensions', []) or []
            for p_dim in panel_dims:
                w = p_dim.get('width') if isinstance(p_dim, dict) else getattr(p_dim, 'width', None)
                h = p_dim.get('height') if isinstance(p_dim, dict) else getattr(p_dim, 'height', None)
                if w and h:
                    calc_w = round_press_dimension(w)
                    calc_h = round_press_dimension(h)
                    groups_map[group_key]['counter'][(calc_w, calc_h)] += 1

        panel_groups = []
        for grp in groups_map.values():
            raw_counter = grp.pop('counter')
            sorted_dims = sorted(raw_counter.items(), key=lambda x: (x[0][1], x[0][0]), reverse=True)
            grp['dimensions'] = [
                {'width': w, 'height': h, 'qty': count}
                for (w, h), count in sorted_dims
            ]
            if grp['dimensions']:
                panel_groups.append(grp)

        return panel_groups

    @staticmethod
    def get_wooden_frames_data(spec_obj):
        """
        Собирает данные для отчёта по деревянным коробкам из элементов спецификации.
        Берёт проёмы (ширина, высота, толщина стены).
        """
        frames_items = []
        for item in getattr(spec_obj, 'items', []):
            # Пропускаем, если позиция не имеет коробки или это скрытый алюминиевый короб
            is_hidden = getattr(item, 'is_hidden_frame', False)
            has_frame = getattr(item, 'has_frame', True)
            if not has_frame or is_hidden:
                continue

            frames_items.append({
                'mark': getattr(item, 'mark', ''),
                'place': getattr(item, 'place', '') or '',
                'opening_width': getattr(item, 'opening_width', None) or getattr(item, 'width', ''),
                'opening_height': getattr(item, 'opening_height', None) or getattr(item, 'height', ''),
                'wall_thickness': getattr(item, 'wall', '') or getattr(item, 'wall_thickness', ''),
                'direction': getattr(item, 'direction', ''),
                'opening': getattr(item, 'opening', ''),
                'color_frames': getattr(item, 'color_frames', '') or getattr(item, 'color', ''),
                'lock_name': getattr(item, 'lock_name', ''),
                'hinge_name': getattr(item, 'hinge_name', ''),
                'comment': getattr(item, 'comment', ''),
            })
        return frames_items

    @staticmethod
    def get_warehouse_hardware_summary(spec_obj):
        """
        Агрегирует фурнитуру под заказ для складской комплектации:
        замки, ручки, петли (с учетом их фактического количества).
        """
        from collections import defaultdict

        locks = defaultdict(int)
        handles = defaultdict(int)
        hinges = defaultdict(int)

        for item in getattr(spec_obj, 'items', []):
            # Замки
            lock = getattr(item, 'lock_name', None) or (item.get('lock_name') if isinstance(item, dict) else None)
            if lock:
                locks[lock] += 1

            # Ручки
            handle = getattr(item, 'handle_name', None) or (item.get('handle_name') if isinstance(item, dict) else None)
            if handle:
                handles[handle] += 1

            # Петли (считаем количество высот врезки)
            hinge = getattr(item, 'hinge_name', None) or (item.get('hinge_name') if isinstance(item, dict) else None)
            if hinge:
                raw_hinges = getattr(item, 'hinge_heights', []) or (
                    item.get('hinge_heights', []) if isinstance(item, dict) else [])
                count = len([h for h in raw_hinges if h is not None])
                # Если высоты не заполнены, берем минимум 3 по умолчанию
                hinges[hinge] += count if count > 0 else 3

        summary_list = []
        for name, qty in sorted(locks.items()):
            summary_list.append({'category': 'מנעולים (Замки)', 'name': name, 'quantity': qty})
        for name, qty in sorted(handles.items()):
            summary_list.append({'category': 'ידיות (Ручки)', 'name': name, 'quantity': qty})
        for name, qty in sorted(hinges.items()):
            summary_list.append({'category': 'צירים (Петли)', 'name': name, 'quantity': qty})

        return summary_list


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
        Increments order.latest_batch if there are NEW groups and assigns it to them.
        Returns the target batch number to process.
        """
        new_groups = order.groups.filter(
            production_state=OrderItemsGroup.ProductionState.NEW
        )
        if new_groups.exists():
            order.latest_batch += 1
            order.save(update_fields=['latest_batch'])

            new_groups.update(
                batch_number=order.latest_batch,
                production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION
            )
            return order.latest_batch

        return order.latest_batch

    @classmethod
    def start_production(cls, order, user=None):
        # 1. Если заказ в ожидании Фазы 2 — переводим его в PHASE2_PRODUCTION
        if order.status == OrderStatus.PHASE1_READY:
            active_groups = order.groups.exclude(
                production_state=OrderItemsGroup.ProductionState.CANCELED
            )
            if not active_groups.exists():
                raise OrderValidationError("Нет активных групп для запуска второй фазы.")

            order.status = OrderStatus.PHASE2_PRODUCTION
            order.save(update_fields=['status'])

            # Строим спецификацию для фазы 2
            TechnicalSpecService.get_or_build_spec(
                order, phase='phase2', force_rebuild=True, user=user
            )
            return

        # 2. Обычный запуск нового заказа или дозаказа (NEW -> PHASE1 или FULL)
        waiting_groups = order.groups.filter(
            production_state=OrderItemsGroup.ProductionState.WAITING
        )
        if not waiting_groups.exists():
            raise OrderValidationError("Нет новых групп для запуска в производство.")

        # Присваиваем номер батча и переводим в IN_PRODUCTION
        next_batch = (order.latest_batch or 0) + 1
        order.latest_batch = next_batch

        if getattr(order, 'has_split_installation', False):
            order.status = OrderStatus.PHASE1_PRODUCTION
        else:
            order.status = OrderStatus.IN_PRODUCTION

        order.save(update_fields=['status', 'latest_batch'])

        waiting_groups.update(
            production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION,
            batch_number=next_batch
        )

        # Строим спецификацию для текущей фазы
        phase = 'phase1' if order.status == OrderStatus.PHASE1_PRODUCTION else 'phase2'
        TechnicalSpecService.get_or_build_spec(
            order, phase=phase, batch_number=next_batch, force_rebuild=True, user=user
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
