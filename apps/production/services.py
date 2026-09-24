import io
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional

from django.conf import settings
from django.db import models
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.orders.models import OrderItemsGroup, OrderItem, OrderStatus, OrderChangeLog
from .models import (
    ProductionStation, OrderSpecificationSnapshot,
)


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
    def validate_for_report(cls, order, report_type: str = None, station=None) -> ValidationResult:
        """
        Appropriate validation before technical report generation.
        For Phase A frames report (PHASE1_FRAMES) - partial check.
        For other reports (doors, press, full frames, full production) - full check.
        """
        if order.status == OrderStatus.COMPLETION_PRODUCTION:
            return cls.validate_completion(order)
        if station and not station.has_specification:
            # If station doesn't require specification but we are here, do full validation
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
                    if not group.color_panels and not getattr(order, 'color_panels', None):
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
    Service for generating and managing technical specifications.
    Single point of entry for all specification requests.
    Supports batch structure: {"batch_1": OrderSpec, "batch_2": OrderSpec, ...}.
    """

    @staticmethod
    def get_or_build_spec(order, phase='phase1', user=None, batch_key: Optional[str] = None):
        """
        Gets the specification from cache or builds batch_1 if invalid/missing.
        Returns:
            - spec_obj (OrderSpec): aggregated spec across all batches (or specific batch if batch_key provided).
            - cache (dict): raw dictionary containing all batches {"batch_1": {...}, ...}.
        """
        from .schemas import OrderSpec, OrderSpecBatchContainer
        from .pipeline import OrderSpecPipeline

        is_validated = order.phase1_validated if phase == 'phase1' else order.phase2_validated
        cache = order.phase1_spec_cache if phase == 'phase1' else order.phase2_spec_cache

        if is_validated and cache:
            # Backward compatibility check: wrap legacy flat spec into batch_1
            if "items" in cache and "batch_1" not in cache:
                cache = {"batch_1": cache}
                field_name = 'phase1_spec_cache' if phase == 'phase1' else 'phase2_spec_cache'
                setattr(order, field_name, cache)
                order.save(update_fields=[field_name])

            batch_container = OrderSpecBatchContainer(
                batches={k: OrderSpec.model_validate(v) for k, v in cache.items() if k.startswith("batch_")}
            )

            if batch_key and batch_key in batch_container.batches:
                return batch_container.batches[batch_key], cache
            return batch_container.get_aggregated_spec(order), cache

        # Build fresh batch_1
        res = OrderValidationService.validate_for_phase(order, phase)
        if not res.is_valid:
            raise OrderValidationError(f"Validation failed for {phase}", errors=res.errors)

        pipeline = OrderSpecPipeline()
        spec_obj = pipeline.execute_for_order(order, phase=phase)

        all_errors = []
        for item_spec in spec_obj.items:
            if item_spec.errors:
                item_label = f"Item {item_spec.mark}" if item_spec.mark else f"Item #{item_spec.item_id}"
                for err in item_spec.errors:
                    all_errors.append(f"{item_label}: {err}")

        if all_errors:
            raise OrderValidationError(f"Specification building failed for {phase}", errors=all_errors)

        # Wrap into batch_1
        batch_1_json = spec_obj.model_dump()
        cache = {"batch_1": batch_1_json}

        snapshot_type = (
            OrderSpecificationSnapshot.SnapshotType.PHASE1
            if phase == 'phase1'
            else OrderSpecificationSnapshot.SnapshotType.PHASE2
        )

        if phase == 'phase1':
            order.phase1_validated = True
            order.phase1_spec_cache = cache
            order.save(update_fields=['phase1_validated', 'phase1_spec_cache'])
        else:
            order.phase2_validated = True
            order.phase2_spec_cache = cache
            order.save(update_fields=['phase2_validated', 'phase2_spec_cache'])

        OrderSpecificationSnapshot.objects.create(
            order=order,
            snapshot_type=snapshot_type,
            spec_data=batch_1_json,
            created_by=user
        )

        return spec_obj, cache

    @classmethod
    def build_completion_spec(cls, order, user=None):
        """
        Builds specification only for unfrozen/new groups (batch_N).
        Appends new batch without modifying previous batches.
        """
        from .pipeline import OrderSpecPipeline

        res = OrderValidationService.validate_completion(order)
        if not res.is_valid:
            raise OrderValidationError("Validation failed for completion production", errors=res.errors)

        # Fetch items strictly from NEW / unfrozen groups
        delta_items = list(OrderItem.objects.filter(
            group__order=order,
            group__production_state=OrderItemsGroup.ProductionState.NEW
        ).select_related('group', 'group__product'))

        if not delta_items:
            raise OrderValidationError("No unfrozen or new items found for completion production")

        pipeline = OrderSpecPipeline()
        delta_spec_obj = pipeline.execute(order, items=delta_items, phase='phase2')

        all_errors = []
        for item_spec in delta_spec_obj.items:
            if item_spec.errors:
                item_label = f"Item {item_spec.mark}" if item_spec.mark else f"Item #{item_spec.item_id}"
                for err in item_spec.errors:
                    all_errors.append(f"{item_label}: {err}")

        if all_errors:
            raise OrderValidationError("Specification building failed for completions", errors=all_errors)

        delta_spec_json = delta_spec_obj.model_dump()

        # Determine next batch key
        cache = order.phase2_spec_cache or {}
        # Backward compatibility check
        if "items" in cache and "batch_1" not in cache:
            cache = {"batch_1": cache}

        batch_count = sum(1 for k in cache.keys() if k.startswith("batch_"))
        next_batch_key = f"batch_{batch_count + 1}"
        cache[next_batch_key] = delta_spec_json

        # Persist new batch
        order.phase2_spec_cache = cache
        order.phase2_validated = True
        order.save(update_fields=['phase2_spec_cache', 'phase2_validated'])

        OrderSpecificationSnapshot.objects.create(
            order=order,
            snapshot_type=OrderSpecificationSnapshot.SnapshotType.PHASE2_COMPLETION,
            spec_data=delta_spec_json,
            created_by=user
        )

        return delta_spec_obj, delta_spec_json

    @staticmethod
    def validate(item: OrderItem) -> List[str]:
        """
        Validates if there is enough data to build the item specification.
        Returns a list of errors.
        """
        errors = []
        item_label = f"Item {item.mark}" if item.mark else f"Item #{item.id}"
        group = getattr(item, 'group', None)
        if not group or not group.product:
            errors.append(f"{item_label}: Product model not selected")
            return errors

        product_type = None
        if group.product and group.product.product_family and group.product.product_family.product_type:
            product_type = group.product.product_family.product_type

        has_door = product_type.has_door if product_type else True
        has_frame = product_type.has_frame if product_type else True

        if has_door or has_frame:
            if item.height is None or item.height <= 0:
                errors.append(f"{item_label}: Valid height not specified")
            if item.width is None or item.width <= 0:
                errors.append(f"{item_label}: Valid width not specified")

        if has_frame:
            if item.wall is None or item.wall <= 0:
                errors.append(f"{item_label}: Wall thickness not specified (frame)")

        return errors

    @classmethod
    def build_spec(cls, item: OrderItem):
        """
        Collects all data and returns a technical specification instance for an item.
        Uses SpecPipeline for step-by-step processing.
        """
        from .pipeline import SpecPipeline
        pipeline = SpecPipeline()
        return pipeline.execute(item)

    @classmethod
    def build_order_spec(cls, order, items=None):
        """
        Forms a complete specification for the entire order.
        Uses OrderSpecPipeline for step-by-step processing.
        """
        from .pipeline import OrderSpecPipeline
        pipeline = OrderSpecPipeline()
        return pipeline.execute(order, items)


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
                # NEW etc - just full report if any
                report_content = self.generate_report_html(self.ReportType.FULL_PRODUCTION, validate=False)
                zip_file.writestr(f"Order_{self.order.order_number}_Full.html", report_content)

            # Generate CNC files into zip
            self._add_cnc_files_to_zip(zip_file)

        buffer.seek(0)
        return buffer

    def _add_cnc_files_to_zip(self, zip_file):
        """Internal helper to add CNC files to the zip buffer"""
        is_phase_a = self.order.status == OrderStatus.PHASE1_PRODUCTION
        is_completion = self.order.status == OrderStatus.COMPLETION_PRODUCTION
        phase = 'phase1' if is_phase_a else 'phase2'
        order_spec, _ = TechnicalSpecService.get_or_build_spec(self.order, phase=phase)

        # In completion mode, filter out items from COMPLETED groups
        items_to_process = order_spec.items
        if is_completion:
            active_item_ids = set(OrderItem.objects.filter(
                group__order=self.order
            ).exclude(
                group__production_state=OrderItemsGroup.ProductionState.COMPLETED
            ).values_list('id', flat=True))
            items_to_process = [it for it in items_to_process if it.item_id in active_item_ids]

        for spec in items_to_process:
            folder_name = f"{self.order.order_number}/{spec.mark}"
            for i in range(1, 5):
                xml_content = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<root>\n  <order_number>{self.order.order_number}</order_number>\n  <item_mark>{spec.mark}</item_mark>\n  <file_number>{i}</file_number>\n  <status>{'Phase A' if is_phase_a else ('Completion Production' if is_completion else 'Full Production')}</status>\n</root>"
                zip_file.writestr(f"{folder_name}/file_{i}.xml", xml_content)

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

    def _generate_hinges_xml(self, spec, item_type):
        """
        Generates content for hinges.xml.
        Currently a placeholder, rules will be added in the future.
        """
        return '<?xml version="1.0" encoding="UTF-8"?>\n<hinges>\n  <status>placeholder</status>\n  <item_id>' + str(
            spec.item_id) + '</item_id>\n</hinges>'

    def _generate_lock_xml(self, spec, item_type):
        """
        Generates content for lock.xml.
        Currently a placeholder, rules will be added in the future.
        """
        return '<?xml version="1.0" encoding="UTF-8"?>\n<lock>\n  <status>placeholder</status>\n  <item_id>' + str(
            spec.item_id) + '</item_id>\n</lock>'

    def change_material(self):
        # for group in self.order.groups.all():
        #     print(group.basic_color_frames)
        pass

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
            'report_type': report_type,
            'station': station,
            'report_label': label,
            'stage_label': stage_label,
            'groups_data': self.prepare_grouped_data(order_spec_for_report),
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

    def _get_order_data(self, report_type=None, station=None):
        """
        Legacy method for backward compatibility (primarily for tests).
        Internally builds the full OrderSpec and groups it.
        """
        phase = 'phase1' if (
                report_type == self.ReportType.PHASE1_FRAMES or (station and station.is_phase1)) else 'phase2'
        order_spec, _ = TechnicalSpecService.get_or_build_spec(self.order, phase=phase)

        filtered_items = self.get_filtered_items(report_type, station=station)
        filtered_item_ids = [item.id for item in filtered_items]

        order_spec_filtered = order_spec.model_copy()
        order_spec_filtered.items = [item for item in order_spec.items if item.item_id in filtered_item_ids]

        return self.prepare_grouped_data(order_spec_filtered)

    def prepare_grouped_data(self, order_spec):
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
                spec.color_panels,
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
            common_color_panels = first.color_panels

            for s in items_specs[1:]:
                if s.front_name != common_front: common_front = "Various"
                if s.color_frames != common_color_frames: common_color_frames = "Various"
                if s.color_panels != common_color_panels: common_color_panels = "Various"

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
        # Import OrderItem locally to avoid circular import
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
    def start_production(order, user=None):
        """
        Transfers order to production. Handles stages for split installation.
        """
        # 1. Validation before production (partial or full depending on status and has_split_installation)
        has_split = order.has_split_installation
        if order.status == OrderStatus.PHASE1_READY:
            val_res = OrderValidationService.validate_full(order)
        elif has_split:
            val_res = OrderValidationService.validate_partial(order)
        else:
            val_res = OrderValidationService.validate_full(order)

        val_res.raise_if_invalid()

        old_status = order.status

        with transaction.atomic():
            order.groups.filter(
                production_state=OrderItemsGroup.ProductionState.NEW
            ).update(
                production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION
            )

            if order.status == OrderStatus.PHASE1_READY:
                # Transition from "Phase 1 ready" to production stage 2
                order.status = OrderStatus.PHASE2_PRODUCTION
            elif has_split:
                order.status = OrderStatus.PHASE1_PRODUCTION
            else:
                order.status = OrderStatus.IN_PRODUCTION
            order.save(update_fields=['status'])

            # Spec building / snapshot saving
            phase = 'phase1' if order.status == OrderStatus.PHASE1_PRODUCTION else 'phase2'
            TechnicalSpecService.get_or_build_spec(order, phase=phase, user=user)

            # CNC files generation
            service = ProductionDataService(order)
            service.generate_cnc_files()

            OrderChangeLog.objects.create(
                order=order,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=order.status
            )
        return order

    @staticmethod
    def start_completion_production(order, user=None):
        """
        Transfers order to completion production (ייצור השלמות) for new / unfrozen groups.
        """
        if order.status not in [OrderStatus.PARTIALLY_READY, OrderStatus.COMPLETED, OrderStatus.COMPLETED]:
            raise ValueError(
                "Completion production is only available from Phase 2 Ready, Ready, or Completed statuses.")

        # Check that there are uncompleted groups
        uncompleted_groups = order.groups.filter(
            production_state=OrderItemsGroup.ProductionState.NEW
        )
        if not uncompleted_groups.exists():
            raise ValueError("No new or waiting groups to produce completions for.")

        # Validate completion groups
        val_res = OrderValidationService.validate_completion(order)
        val_res.raise_if_invalid()

        old_status = order.status

        with transaction.atomic():
            # Build completion spec and snapshot
            delta_spec, _ = TechnicalSpecService.build_completion_spec(order, user=user)

            # Update groups to IN_PRODUCTION
            uncompleted_groups.update(production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION)

            order.status = OrderStatus.COMPLETION_PRODUCTION
            order.save()

            # CNC files generation only for delta items
            service = ProductionDataService(order)
            service.generate_cnc_files(spec_items=delta_spec.items)

            OrderChangeLog.objects.create(
                order=order,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=order.status
            )
        return order

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

    @staticmethod
    def start_phase1(order, user=None):
        """
        Explicit start of Phase A (frames production).
        """
        # 1. Partial validation before Phase 1
        val_res = OrderValidationService.validate_partial(order)
        val_res.raise_if_invalid()

        old_status = order.status
        with transaction.atomic():
            order.status = OrderStatus.PHASE1_PRODUCTION

            # Update waiting groups to IN_PRODUCTION
            order.groups.filter(
                production_state=OrderItemsGroup.ProductionState.NEW
            ).update(production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION)

            order.save()

            # Spec building / snapshot saving
            TechnicalSpecService.get_or_build_spec(order, phase='phase1', user=user)

            # CNC files generation
            service = ProductionDataService(order)
            service.generate_cnc_files()

            OrderChangeLog.objects.create(
                order=order,
                user=user,
                field_name='status',
                old_value=old_status,
                new_value=order.status
            )
        return order
