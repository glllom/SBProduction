import io
import math
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from django.conf import settings
from django.db import models
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.orders.models import OrderItemsGroup, OrderItem, OrderStatus, OrderChangeLog
from .models import (
    LockStandardHeight, HingeStandardHeight, BOM, 
    ProductionStation, ProductionRoute, CustomizerProductionStation
)


class ValidationType(models.TextChoices):
    PARTIAL = 'PARTIAL', 'בדיקה חלקית (שלב א)'
    FULL = 'FULL', 'בדיקה מלאה (שלב ב / ייצור מלא)'


@dataclass
class ValidationResult:
    """
    תוצאת בדיקת תקינות נתונים של הזמנה (וולידציה).
    """
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    validation_type: str = ValidationType.FULL

    def __iter__(self):
        return iter((self.is_valid, self.errors))

    def raise_if_invalid(self):
        if not self.is_valid:
            error_details = "; ".join(self.errors)
            raise ValueError(f"שגיאת תקינות נתונים ({self.validation_type}): {error_details}")


class OrderValidationService:
    """
    שירות וולידציה (בדיקת תקינות נתונים) עבור הזמנות.
    מתבצע לפני מעבר לייצור, לפני הפקת דוחות טכניים ולפני ייצור קבצי CNC / ZIP.

    תומך בשני סוגי וולידציה:
    1. PARTIAL (בדיקה חלקית - שלב א' בהתקנה מפוצלת):
       - בדיקת סדרה וחזית/גימור עבור כל קבוצה
       - בדיקת דגם מוצר וקיום פריטים בקבוצה
       - בדיקת מידות פריטים (גובה ורוחב אם יש דלת או משקוף, עובי קיר אם יש משקוף, צד/כיוון אם יש דלת)
       - ידיות (handle) לא נבדקות בשלב זה.
    2. FULL (בדיקה מלאה - שלב ב' או כאשר התקנה מפוצלת = False):
       - כולל את כל בדיקות שלב א'
       - בדיקת בחירת ידית להזמנה (Handle)
       - בדיקת גווני צבע כאשר נבחרה אפשרות צביעה
    """

    @classmethod
    def validate(cls, order, validation_type: str = ValidationType.FULL) -> ValidationResult:
        if validation_type == ValidationType.PARTIAL:
            return cls.validate_partial(order)
        return cls.validate_full(order)

    @classmethod
    def validate_partial(cls, order) -> ValidationResult:
        """
        בדיקה חלקית (שלב א - משקופים בהתקנה מפוצלת).
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
        בדיקה מלאה (שלב ב או הזמנה רגילה ללא התקנה מפוצלת).
        """
        errors = cls._run_validation(order, is_full=True)
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            validation_type=ValidationType.FULL
        )

    @classmethod
    def validate_for_production(cls, order, phase: Optional[str] = None) -> ValidationResult:
        """
        בדיקה מתאימה לפני העברת ההזמנה לייצור.
        """
        has_split = getattr(order, 'has_split_installation', False)
        if phase == str(order.status).upper() == 'PHASE1_PRODUCTION' or (
                has_split and getattr(order, 'status', None) == OrderStatus.NEW):
            return cls.validate_partial(order)
        return cls.validate_full(order)

    @classmethod
    def validate_for_report(cls, order, report_type: str = None, station=None) -> ValidationResult:
        """
        בדיקה מתאימה לפני הפקת דו"ח טכני.
        עבור דו"ח משקופים שלב א (PHASE1_FRAMES) - בדיקה חלקית.
        עבור שאר הדו"חות (דלתות, פרס, משקופים מלא, ייצור מלא) - בדיקה מלאה.
        """
        if station and not station.has_specification:
             # Если станция не требует спецификации, но мы почему-то тут, делаем полную
             return cls.validate_full(order)

        p1_values = [
            'PHASE1_PRODUCTION',
            'PHASE1_FRAMES',
            str(ProductionDataService.ReportType.PHASE1_FRAMES)
        ]
        
        # Если передан код станции, проверяем не является ли она станцией "משקופים שלב א"
        # Для простоты пока считаем, что если report_type или код станции содержит PHASE1, то PARTIAL
        r_type_str = str(report_type).upper() if report_type else ""
        s_code_str = station.code.upper() if station else ""
        
        if r_type_str in p1_values or 'PHASE1' in s_code_str:
            return cls.validate_partial(order)
            
        return cls.validate_full(order)

    @classmethod
    def validate_for_zip(cls, order) -> ValidationResult:
        """
        בדיקה מתאימה לפני הפקת קובצי ייצור (ZIP).
        """
        has_split = getattr(order, 'has_split_installation', False)
        print(order.status)
        if has_split and getattr(order, 'status', None) == OrderStatus.IN_PRODUCTION_PHASE1:
            return cls.validate_partial(order)
        return cls.validate_full(order)

    @classmethod
    def _run_validation(cls, order, is_full: bool) -> List[str]:
        errors = []

        if not getattr(order, 'order_number', None):
            errors.append("מספר הזמנה חסר")
        if not getattr(order, 'customer', None):
            errors.append("שם לקוח חסר")

        groups = list(order.groups.all())
        if not groups:
            errors.append("אין קבוצות מוצרים בהזמנה")
            return errors

        has_any_doors = False

        for group in groups:
            group_name = group.product.name if group.product else f"קבוצה #{group.id}"
            group_label = f"קבוצה #{group.id} ({group_name})"

            if not group.product:
                errors.append(f"קבוצה #{group.id}: לא נבחר דגם מוצר")
                continue

            # 1. סדרה (Series)
            effective_series = group.series or getattr(order, 'series', None)
            if not effective_series:
                errors.append(f"{group_label}: לא נבחרה סדרה")

            # 2. חזית / גימור (Front)
            effective_front = group.front or getattr(order, 'front', None)
            if not effective_front:
                errors.append(f"{group_label}: לא נבחרה חזית / גימור")

            # 3. צבעי צביעה בבדיקה מלאה (אם נבחר גוון מיוחד)
            if is_full:
                if group.panel_paint_option == OrderItemsGroup.PaintOption.SPECIAL_COLOR:
                    if not group.color_panels and not getattr(order, 'color_panels', None):
                        errors.append(f"{group_label}: נבחר גוון מיוחד לפנל אך לא הוגדר צבע פנלים")
                if group.frame_paint_option == OrderItemsGroup.PaintOption.SPECIAL_COLOR:
                    if not group.basic_colormes and not getattr(order, 'color_frames', None):
                        errors.append(f"{group_label}: נבחר גוון מיוחד למשקוף אך לא הוגדר צבע משקופים")

            # 4. פריטים בקבוצה
            items = list(group.items.all())
            if not items:
                errors.append(f"{group_label}: אין פריטים בקבוצה")
                continue

            product_type = None
            if group.product and group.product.product_family and group.product.product_family.product_type:
                product_type = group.product.product_family.product_type

            has_door = product_type.has_door if product_type else True
            has_frame = product_type.has_frame if product_type else True

            if has_door:
                has_any_doors = True

            for item in items:
                item_label = f"פריט {item.mark}" if item.mark else f"פריט #{item.id} ({group_label})"

                # בדיקת גובה ורוחב אם יש דלת או משקוף
                if has_door or has_frame:
                    if item.height is None or item.height <= 0:
                        errors.append(f"{item_label}: לא צוין גובה תקין")
                    if item.width is None or item.width <= 0:
                        errors.append(f"{item_label}: לא צוין רוחב תקין")

                # בדיקת עובי קיר עבור משקוף
                if has_frame:
                    if item.wall is None or item.wall <= 0:
                        errors.append(f"{item_label}: לא צוין עובי קיר (משקוף)")

                # בדיקת כיוון וצד פתיחה עבור דלת
                if has_door:
                    if not item.opening:
                        errors.append(f"{item_label}: לא נבחר צד פתיחה (L/R)")
                    if not item.direction:
                        errors.append(f"{item_label}: לא נבחר כיוון פתיחה (פנימה/החוצה)")

        # 5. בדיקת ידית בבדיקה מלאה (שלב ב' או ללא התקנה מפוצלת)
        if is_full and has_any_doors:
            if not getattr(order, 'handle', None):
                errors.append("לא נבחרה ידית להזמנה (חובה לשלב ב' / ייצור מלא)")

        return errors


@dataclass
class TechnicalSpec:
    """
    Полная техническая спецификация для конкретного изделия в заказе.
    Используется для генерации отчетов, техзаданий и передачи данных на производство.
    """
    item_id: int
    mark: str
    product_name: str
    product_code: str
    product_family: str
    series: str

    # Геометрия
    height: float
    width: float
    wall: float

    # Параметры открывания
    direction: str
    opening: str

    # Внешний вид
    front_name: str
    color_panels: str
    color_frames: str
    basic_color_frames: str
    frame_paint_option: str
    handle_name: str

    # Технические данные (из ProductTechnicalData)
    cnc_program: str
    tech_notes: str

    # Фурнитура и присадки
    lock_name: str
    lock_height: Optional[float]
    hinge_name: str
    hinge_heights: List[float]

    # Спецификация материалов (BOM)
    frame: str

    bom_items: List[Dict[str, Any]] = field(default_factory=list)

    profiles: List[str] = field(default_factory=list)

    # Дополнительно
    place: str = ""
    comment: str = ""
    sketch_url: str = ""
    frames_report_customizers: List[Dict[str, Any]] = field(default_factory=list)


class TechnicalSpecService:
    """
    Сервис для формирования и валидации технической спецификации изделия.
    """

    @staticmethod
    def validate(item: OrderItem) -> List[str]:
        """
        Проверяет, достаточно ли данных для формирования спецификации изделия.
        Возвращает список ошибок.
        """
        errors = []
        item_label = f"פריט {item.mark}" if item.mark else f"פריט #{item.id}"
        group = getattr(item, 'group', None)
        if not group or not group.product:
            errors.append(f"{item_label}: לא נבחר דגם מוצר")
            return errors

        product_type = None
        if group.product and group.product.product_family and group.product.product_family.product_type:
            product_type = group.product.product_family.product_type

        has_door = product_type.has_door if product_type else True
        has_frame = product_type.has_frame if product_type else True

        if has_door or has_frame:
            if item.height is None or item.height <= 0:
                errors.append(f"{item_label}: לא צוין גובה תקין")
            if item.width is None or item.width <= 0:
                errors.append(f"{item_label}: לא צוין רוחב תקין")

        if has_frame:
            if item.wall is None or item.wall <= 0:
                errors.append(f"{item_label}: לא צוין עובי קיר (משקוף)")

        return errors

    @staticmethod
    def get_effective_lock_height(item: OrderItem, lock_hardware) -> Optional[float]:
        if item.custom_lock_height:
            return float(item.custom_lock_height)

        if not lock_hardware:
            return None

        # Find standard height for this family and lock
        std = LockStandardHeight.objects.filter(
            product_families=item.group.product.product_family,
            lock=lock_hardware
        ).first()

        if not std:
            return None

        # Calculation: value = base_lock_height + ceil((door_height - base_door_height) / step) * step
        door_h = float(item.height or 0)
        base_h = float(std.base_door_height)
        base_lock = float(std.base_lock_height)
        step = float(std.step)

        if step == 0:
            return base_lock

        diff = door_h - base_h
        intervals = math.ceil(diff / step)
        return base_lock + intervals * step

    @staticmethod
    def get_effective_hinge_heights(item: OrderItem, hinge_hardware) -> List[float]:
        custom_hinges = [
            float(getattr(item, f'custom_hinge{i}'))
            for i in range(1, 6)
            if getattr(item, f'custom_hinge{i}')
        ]

        if custom_hinges:
            return custom_hinges

        if not hinge_hardware:
            return []

        # Find standard heights
        door_h = float(item.height or 0)
        std = HingeStandardHeight.objects.filter(
            product_families=item.group.product.product_family,
            hinge=hinge_hardware,
            min_height__lte=door_h,
            max_height__gte=door_h
        ).first()

        if not std:
            return []

        res = []
        for i in range(1, 6):
            val = getattr(std, f'value{i}')
            if val:
                res.append(float(val))
        return res

    @staticmethod
    def _format_customizer_for_report(group_customizer) -> Dict[str, Any]:
        """
        Formats a customizer for the production report (Strategy 10).
        Returns a dictionary with name and parameters (label, value, is_custom).
        """
        c = group_customizer.customizer
        params = []
        for i in range(1, 5):
            label = getattr(c, f'par{i}_label')
            if label:
                # Value from order group
                val_order = getattr(group_customizer, f'par{i}')
                # Default value from catalog
                val_default = getattr(c, f'par{i}_value')

                is_custom = False
                val = val_order
                if val is None or val == '':
                    val = val_default
                elif val_default and val != val_default:
                    is_custom = True

                if val:
                    params.append({
                        'label': label,
                        'value': val,
                        'is_custom': is_custom
                    })

        return {
            'name': c.name,
            'params': params
        }

    @classmethod
    def build_spec(cls, item: OrderItem) -> TechnicalSpec:
        """
        Собирает все данные и возвращает экземпляр TechnicalSpec.
        """
        group = item.group
        order = group.order if group else None
        product = group.product if group else None
        bom_first = BOM.objects.filter(product=product).first() if product else None
        frame = bom_first.frame if bom_first else None

        # Получаем техданные продукта
        tech_data = getattr(product, 'tech_data', None)

        # Рассчитываем BOM
        calc = BOMCalculator({
            'H': float(item.height or 0),
            'W': float(item.width or 0),
            'wall': float(item.wall or 0),
            'basic_color_frames': group.basic_color_frames if group else None,
            'customizers': {}  # Можно расширить в будущем
        })
        bom_result = calc.calculate_for_product(product) if product else []

        # Извлекаем фурнитуру из BOM для информации в спеке
        lock_item = next((b for b in bom_result if b.get('tag') == 'Lock'), None)
        hinge_item = next((b for b in bom_result if b.get('tag') == 'hinge'), None)

        lock_name = lock_item['item'].name if lock_item else "N/A"
        hinge_name = hinge_item['item'].name if hinge_item else "N/A"

        # Calculate effective heights
        lock_height = cls.get_effective_lock_height(item, lock_item['item'] if lock_item else None)
        hinge_heights = cls.get_effective_hinge_heights(item, hinge_item['item'] if hinge_item else None)

        # Extract profiles
        profiles = [
            b['item'].name for b in bom_result
            if b.get('tag') in ['profile1', 'profile2', 'profile3']
        ]

        # Processing Customizer Strategies (1-10)
        frames_report_customizers = []
        if group:
            # Get all customizers for the group, pre-fetching the definitions
            group_customizers = group.customizers.select_related('customizer').order_by('customizer__strategy',
                                                                                        'customizer__priority')

            from collections import defaultdict
            strategy_map = defaultdict(list)
            for gc in group_customizers:
                strategy_map[gc.customizer.strategy].append(gc)

            # Execute strategies in sequence 1..10
            for s_num in range(1, 11):
                gcs = strategy_map.get(s_num, [])

                if s_num == 10:
                    # Strategy 10: Frames Report presentation
                    for gc in gcs:
                        formatted = cls._format_customizer_for_report(gc)
                        frames_report_customizers.append(formatted)
                else:
                    # Strategies 1-9 placeholders
                    for gc in gcs:
                        # Placeholder for future logic
                        pass

        series_name = ""
        if group and group.series:
            series_name = group.series.name
        elif order and order.series:
            series_name = order.series.name

        product_family_name = ""
        if product and product.product_family:
            product_family_name = product.product_family.name

        return TechnicalSpec(
            item_id=item.id,
            mark=item.mark or "",
            product_name=product.name if product else "",
            product_code=product.code if product else "",
            height=float(item.height or 0),
            width=float(item.width or 0),
            wall=float(item.wall or 0),
            direction=item.get_direction_display() if item.direction else "",
            opening=item.get_opening_display() if item.opening else "",
            front_name=group.front.name if (group and group.front) else (
                order.front.name if (order and order.front) else ""),
            color_panels=(group.color_panels if group else "") or "",
            color_frames=(group.color_frames if group else "") or "",
            frame_paint_option=group.frame_paint_option if group else "",
            basic_color_frames=str(group.basic_color_frames) if (group and group.basic_color_frames) else "",
            handle_name=order.handle.name if (order and order.handle) else "",
            cnc_program=tech_data.cnc_program_name if tech_data else "",
            tech_notes=tech_data.technical_notes if tech_data else "",
            lock_name=lock_name,
            lock_height=lock_height,
            hinge_name=hinge_name,
            hinge_heights=hinge_heights,
            bom_items=bom_result,
            profiles=profiles,
            place=item.place or "",
            comment=item.comment or "",
            sketch_url=item.sketch.url if item.sketch else "",
            frame=frame.name if frame else "",
            series=series_name,
            product_family=product_family_name,
            frames_report_customizers=frames_report_customizers,
        )


class BOMCalculator:
    """
    Service for dynamic Bill of Materials (BOM) calculation.
    Supports fixed-slot materials, categorized hardware, and nested BOMs.
    """

    def __init__(self, context=None):
        """
        :param context: Dict containing variables like 'H', 'W', 'D' 
                       and 'customizers' (dict of tags/values).
        """
        self.context = context or {}

    def _evaluate(self, formula):
        try:
            # Basic context
            safe_context = {
                'H': float(self.context.get('H', 0)),
                'W': float(self.context.get('W', 0)),
                'D': float(self.context.get('D', 0)),
                'wall': float(self.context.get('wall', 0)),
                'math': math,
            }
            # Add customizers
            if 'customizers' in self.context:
                safe_context.update(self.context['customizers'])

            # Simple eval
            return eval(formula, {"__builtins__": None}, safe_context)
        except Exception:
            return 0

    def _resolve_material(self, material):
        """
        Resolves a material to its colored version if basic_color_frames is set.
        If basic_color_frames is a Material object, we use its color to find 
        matching materials with the same common_name.
        """
        if not material:
            return None

        selected_frame_material = self.context.get('basic_color_frames')
        if not selected_frame_material:
            return material

        # 1. Exact match by common_name with selected material
        if material.common_name and selected_frame_material.common_name == material.common_name:
            return selected_frame_material

        # 2. Match other materials by common_name and the color of selected material
        if material.common_name and selected_frame_material.color:
            from apps.catalog.models import Material
            colored_material = Material.objects.filter(
                common_name=material.common_name,
                color=selected_frame_material.color
            ).first()
            if colored_material:
                return colored_material

        return material

    def calculate_for_product(self, product, quantity=1):
        """
        Recursively calculates BOM for a product based on the structured BOM model.
        """
        try:
            bom = product.bom
        except Exception:  # RelatedObjectDoesNotExist
            return []

        bom_result = []

        # 1. Process Material Slots
        material_slots = [
            ('covering', 'כיסוי'), ('base', 'בסיס'), ('filling', 'מילוי'),
            ('casing', 'הלבשה'), ('frame', 'משקוף'), ('profile1', 'פרופיל 1'),
            ('profile2', 'פרופיל 2'), ('profile3', 'פרופיל 3'), ('other1', 'אחר 1'),
            ('other2', 'אחר 2'), ('other3', 'אחר 3'), ('other4', 'אחר 4'),
            ('other5', 'אחר 5')
        ]

        for slot_name, label in material_slots:
            material = getattr(bom, slot_name)
            if material:
                material = self._resolve_material(material)
                formula = getattr(bom, f"{slot_name}_consumption")
                local_qty = self._evaluate(formula)
                total_qty = local_qty * quantity
                if total_qty > 0:
                    bom_result.append({
                        'type': 'material',
                        'section': label,
                        'item': material,
                        'quantity': total_qty,
                        'tag': slot_name  # For backward compatibility or extra identification
                    })

        # 2. Process Hardware M2M Slots
        hardware_slots = [
            ('lock', 'מנעול', 'Lock'),
            ('hinges', 'צירים', 'hinge'),
            ('additional', 'תוספות', 'additional')
        ]
        for slot_name, label, tag in hardware_slots:
            hardware_queryset = getattr(bom, slot_name).all()
            for hw in hardware_queryset:
                bom_result.append({
                    'type': 'hardware',
                    'section': label,
                    'item': hw,
                    'tag': tag,
                    'quantity': 1 * quantity  # Default to 1 per unit
                })

        # 3. Process Nested BOMs
        for nested_bom in bom.nested_boms.all():
            # Recurse using the product of the nested BOM
            nested_results = self.calculate_for_product(nested_bom.product, quantity=quantity)
            bom_result.extend(nested_results)

        return bom_result


class ProductionDataService:
    class ReportType(models.TextChoices):
        PHASE1_FRAMES = 'PHASE1_PRODUCTION', 'משקופים שלב א'
        PHASE2_DOORS = 'PHASE2_DOORS', 'דלתות שלב ב'
        PHASE2_PRESS = 'PHASE2_PRESS', 'פרס'
        PHASE2_FRAMES = 'PHASE2_FRAMES', 'משקופים'
        IN_PRODUCTION = 'IN_PRODUCTION', 'דו"ח ייצור מלא'

    def __init__(self, order):
        self.order = order

    def generate_production_zip(self):
        """
        יוצר ארכיון ZIP של כל קובצי הייצור (CNC XML) והדוחות הטכניים.
        מבצע וולידציה לפני היצירה.
        """
        val_res = OrderValidationService.validate_for_zip(self.order)
        val_res.raise_if_invalid()

        buffer = io.BytesIO()
        has_split = getattr(self.order, 'has_split_installation', False)

        with zipfile.ZipFile(buffer, 'w') as zip_file:
            if has_split and self.order.status == OrderStatus.IN_PRODUCTION_PHASE1:
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
        is_phase_a = self.order.status == OrderStatus.IN_PRODUCTION_PHASE1
        order_data = self._get_order_data()  # Gets all for CNC

        for group_data in order_data:
            for spec in group_data['items_specs']:
                folder_name = f"{self.order.order_number}/{spec.mark}"
                for i in range(1, 5):
                    xml_content = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<root>\n  <order_number>{self.order.order_number}</order_number>\n  <item_mark>{spec.mark}</item_mark>\n  <file_number>{i}</file_number>\n  <status>{'Phase A' if is_phase_a else 'Full Production'}</status>\n</root>"
                    zip_file.writestr(f"{folder_name}/file_{i}.xml", xml_content)

    def generate_cnc_files(self):
        """
        Standalone method to generate CNC files on the server filesystem.
        Создает структуру папок cnc_files/mecal/<order_number>/ и наполняет её XML файлами.
        """
        val_res = OrderValidationService.validate_for_zip(self.order)
        val_res.raise_if_invalid()

        # Пути
        cnc_root = os.path.join(settings.BASE_DIR, 'cnc_files')
        mecal_dir = os.path.join(cnc_root, 'mecal')
        order_dir = os.path.join(mecal_dir, str(self.order.order_number))

        # Создаем базовые директории
        os.makedirs(mecal_dir, exist_ok=True)

        # Очищаем папку заказа, если она есть
        if os.path.exists(order_dir):
            shutil.rmtree(order_dir)
        os.makedirs(order_dir)

        # Создаем основные поддиректории
        frames_root = os.path.join(order_dir, 'frames')
        doors_root = os.path.join(order_dir, 'doors')
        os.makedirs(frames_root)
        os.makedirs(doors_root)

        # Проходим по всем группам и элементам заказа
        for group in self.order.groups.all():
            product_type = None
            if group.product and group.product.product_family and group.product.product_family.product_type:
                product_type = group.product.product_family.product_type

            has_frame = product_type.has_frame if product_type else True
            has_door = product_type.has_door if product_type else True

            for item in group.items.all():
                mark = item.mark or str(item.id)

                if has_frame:
                    item_frame_dir = os.path.join(frames_root, f"frame_{mark}")
                    os.makedirs(item_frame_dir, exist_ok=True)
                    self._write_xml_files(item_frame_dir, item, "frame")

                if has_door:
                    item_door_dir = os.path.join(doors_root, f"door_{mark}")
                    os.makedirs(item_door_dir, exist_ok=True)
                    self._write_xml_files(item_door_dir, item, "door")

    def _write_xml_files(self, target_dir, item, item_type):
        """
        Вспомогательный метод для записи XML файлов в указанную директорию.
        Сделан для будущего расширения логики генерации XML.
        """
        # Генерация hinges.xml
        hinges_content = self._generate_hinges_xml(item, item_type)
        with open(os.path.join(target_dir, 'hinges.xml'), 'w', encoding='utf-8') as f:
            f.write(hinges_content)

        # Генерация lock.xml
        lock_content = self._generate_lock_xml(item, item_type)
        with open(os.path.join(target_dir, 'lock.xml'), 'w', encoding='utf-8') as f:
            f.write(lock_content)

    def _generate_hinges_xml(self, item, item_type):
        """
        Генерирует содержимое для hinges.xml.
        Пока заглушка, в будущем здесь будут правила.
        """
        return '<?xml version="1.0" encoding="UTF-8"?>\n<hinges>\n  <status>placeholder</status>\n</hinges>'

    def _generate_lock_xml(self, item, item_type):
        """
        Генерирует содержимое для lock.xml.
        Пока заглушка, в будущем здесь будут правила.
        """
        return '<?xml version="1.0" encoding="UTF-8"?>\n<lock>\n  <status>placeholder</status>\n</lock>'

    def change_material(self):
        for group in self.order.groups.all():
            print(group.basic_color_frames)

    def generate_report_html(self, report_type=None, station_code=None, validate=True):
        """
        יוצר קובץ HTML עבור הדו"ח הטכני המבוקש.
        מבצע וולידציה לפני היצירה (אלא אם צוין validate=False).
        """
        station = None
        if station_code:
            station = ProductionStation.objects.filter(code=station_code).first()

        # Normalize report_type if it's a string name of the member
        if report_type and isinstance(report_type, str) and report_type not in self.ReportType.values:
            try:
                report_type = self.ReportType[report_type.upper()].value
            except (KeyError, AttributeError):
                pass

        if validate:
            val_res = OrderValidationService.validate_for_report(self.order, report_type, station=station)
            val_res.raise_if_invalid()

        if station:
            label = station.label or station.name
            template = station.template_name or 'production/alum_frames_report.html'
        else:
            label = self.ReportType(report_type).label
            template = 'production/alum_frames_report.html'

            # Adjust label if no split installation in the whole order
            if not getattr(self.order, 'has_split_installation', False):
                if report_type == self.ReportType.PHASE2_DOORS:
                    label = 'דלתות'

        context = {
            'order': self.order,
            'report_type': report_type,
            'station': station,
            'report_label': label,
            'groups_data': self._get_order_data(report_type, station=station),
            'now': timezone.now(),
        }
        return render_to_string(template, context)

    def _get_order_data(self, report_type=None, station=None):
        # 1. Collect all specs
        all_specs = []
        for group in self.order.groups.all():
            is_split = group.is_split_installation
            product_type = None
            if group.product and group.product.product_family and group.product.product_family.product_type:
                product_type = group.product.product_family.product_type
            has_frame = product_type.has_frame if product_type else True
            has_door = product_type.has_door if product_type else True

            # Filter based on report type OR station
            if station:
                # Check if station is in group's route (including customizers)
                group_stations = ProductionRoute.get_stations_for_group(group)
                if station not in group_stations:
                    continue
            elif report_type == self.ReportType.PHASE1_FRAMES:
                if not is_split or not has_frame:
                    continue
            elif report_type == self.ReportType.PHASE2_DOORS:
                if not has_door:
                    continue
            elif report_type == self.ReportType.PHASE2_PRESS:
                if not has_door:
                    continue
            elif report_type == self.ReportType.PHASE2_FRAMES:
                if not has_frame:
                    continue
            # FULL_PRODUCTION or None -> all items

            for item in group.items.all():
                spec = TechnicalSpecService.build_spec(item)
                all_specs.append(spec)

        # 2. Grouping logic
        grouped_specs = {}
        for spec in all_specs:
            # Key for grouping: Product, Series, Front, Colors, and Profiles
            # Removed lock and hinge details from the key as per requirements
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

        # 3. Form result structure
        groups_data = []
        # Sort by product name for consistent output
        sorted_keys = sorted(grouped_specs.keys())

        for key in sorted_keys:
            items_specs = grouped_specs[key]
            first = items_specs[0]

            # Common decorative params
            common_front = first.front_name
            common_color_frames = first.color_frames
            basic_color_frames = first.basic_color_frames
            common_color_panels = first.color_panels

            for s in items_specs[1:]:
                if s.front_name != common_front: common_front = "Различные"
                if s.color_frames != common_color_frames: common_color_frames = "Различные"
                if s.color_panels != common_color_panels: common_color_panels = "Различные"

            group_spec = {
                'product_name': first.product_name,
                'code': first.product_code,
                'front_name': common_front,
                'color_frames': common_color_frames,
                'basic_color_frames': basic_color_frames,
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
    Сервис управления жизненным циклом заказа в производстве.
    Переносит логику запуска и смены статусов из приложения orders в production.
    """

    @staticmethod
    def recalculate_item_marks(order):
        """
        Пересчитывает порядковые номера (mark) для всех изделий в заказе.
        """
        # Импортируем OrderItem локально, чтобы избежать циклического импорта
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
    def validate_for_production(order, validation_type: Optional[str] = None):
        """
        Проверяет готовность заказа к производству.
        Возвращает (is_valid, errors).
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
        Переводит заказ в производство. Обрабатывает этапы при раздельной установке.
        """
        # 1. Валидация перед производством (частичная или полная в зависимости от статуса и has_split_installation)
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
            if order.status == OrderStatus.PHASE1_READY:
                # Переход из "Фаза 1 готова" в полный цикл производства
                order.status = OrderStatus.IN_PRODUCTION
            elif has_split:
                order.status = OrderStatus.IN_PRODUCTION_PHASE1
            else:
                order.status = OrderStatus.IN_PRODUCTION

            order.save()

            # Генерация CNC файлов
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
    def complete_phase1(order, user=None):
        """
        Завершает первый этап производства и переводит заказ в статус PHASE1_READY.
        """
        if order.status != OrderStatus.IN_PRODUCTION_PHASE1:
            raise ValueError("Завершение этапа А возможно только для заказов в статусе 'ייצור שלב א'")

        old_status = order.status
        with transaction.atomic():
            order.status = OrderStatus.PHASE1_READY
            order.save()

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
        Явный запуск Фазы А (производство משקופים).
        """
        # 1. Частичная валидация перед Фазой 1
        val_res = OrderValidationService.validate_partial(order)
        val_res.raise_if_invalid()

        old_status = order.status
        with transaction.atomic():
            order.status = OrderStatus.IN_PRODUCTION_PHASE1
            order.save()

            # Генерация CNC файлов
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
