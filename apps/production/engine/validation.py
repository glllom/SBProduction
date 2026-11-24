"""
Валидатор технологической готовности заказа к производству и печати отчётов.

Назначение модуля:
    Выполняет предпроизводственную проверку шапки заказа, групп и позиций,
    затем делает холостой прогон (dry-run, save_labels=False) через OrderSpecEngine
    для выявления ошибок в фурнитуре, высотах, ЧПУ-макросах, листах и кастомизаторах
    ДО создания снимков и запуска заказа в работу.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from django.db import models

from apps.engineering.models import ProductionStation
from apps.orders.models import OrderItemsGroup, OrderStatus
from .runner import OrderSpecEngine
from .spec_gateway import TechnicalSpecService


class ValidationType(models.TextChoices):
    """Режимы валидации заказа в зависимости от этапа производства."""
    PARTIAL = 'PARTIAL', 'Partial validation (Phase A)'
    FULL = 'FULL', 'Full validation (Phase B / Full production)'
    COMPLETION = 'COMPLETION', 'Completion validation (Unfinished groups only)'


@dataclass
class ValidationResult:
    """Результат проверки заказа (поддерживает распаковку `is_valid, errors = res`)."""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    validation_type: str = ValidationType.FULL

    def __iter__(self):
        return iter((self.is_valid, self.errors))

    def raise_if_invalid(self) -> None:
        if not self.is_valid:
            error_details = "; ".join(self.errors)
            raise ValueError(f"Data validation error ({self.validation_type}): {error_details}")


class OrderValidationService:
    """
    Централизованный сервис валидации заказа перед запуском, отчётами и экспортом.
    """

    @classmethod
    def validate(cls, order, validation_type: str = ValidationType.FULL) -> ValidationResult:
        """Диспетчер режимов валидации (PARTIAL / COMPLETION / FULL)."""
        if validation_type == ValidationType.PARTIAL:
            return cls.validate_partial(order)
        if validation_type == ValidationType.COMPLETION:
            return cls.validate_completion(order)
        return cls.validate_full(order)

    @classmethod
    def validate_partial(cls, order) -> ValidationResult:
        """Частичная проверка (Фаза А — только коробки при раздельном монтаже)."""
        errors = cls._run_validation(order, phase='phase1', is_full=False)
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            validation_type=ValidationType.PARTIAL,
        )

    @classmethod
    def validate_full(cls, order) -> ValidationResult:
        """Полная проверка (Фаза Б или стандартный комплектный заказ)."""
        errors = cls._run_validation(order, phase='phase2', is_full=True)
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            validation_type=ValidationType.FULL,
        )

    @classmethod
    def validate_completion(cls, order) -> ValidationResult:
        """Проверка для дозаказов (только незавершённые группы)."""
        errors = cls._run_validation(order, phase='phase2', is_full=True, completion_only=True)
        return ValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            validation_type=ValidationType.COMPLETION,
        )

    @staticmethod
    def validate_for_production(order, validation_type: Optional[str] = None) -> ValidationResult:
        """Подбирает подходящий режим валидации при переводе заказа в производство."""
        if validation_type:
            return OrderValidationService.validate(order, validation_type)
        if order.has_split_installation and order.status == OrderStatus.NEW:
            return OrderValidationService.validate_partial(order)
        return OrderValidationService.validate_full(order)

    @classmethod
    def validate_for_report(
            cls,
            order,
            report_type: Optional[str] = None,
            station: Optional[ProductionStation] = None,
    ) -> ValidationResult:
        """Подбирает режим валидации для конкретного отчёта или производственной станции."""
        if order.status == OrderStatus.COMPLETION_PRODUCTION:
            return cls.validate_completion(order)
        if station and not station.has_specification:
            return cls.validate_full(order)
        if report_type in ('PHASE1_FRAMES', 'PHASE1_PRODUCTION') or (station and station.is_phase1):
            return cls.validate_partial(order)
        return cls.validate_full(order)

    @classmethod
    def validate_for_phase(cls, order, phase: str) -> ValidationResult:
        """Подбирает режим валидации по строковому коду этапа."""
        if phase == 'phase1':
            return cls.validate_partial(order)
        if phase == 'phase2_completion':
            return cls.validate_completion(order)
        return cls.validate_full(order)

    @classmethod
    def validate_for_zip(cls, order) -> ValidationResult:
        """Подбирает режим валидации перед сборкой производственного ZIP-архива."""
        if order.status == OrderStatus.COMPLETION_PRODUCTION:
            return cls.validate_completion(order)
        if getattr(order, 'has_split_installation', False) and order.status == OrderStatus.PHASE1_PRODUCTION:
            return cls.validate_partial(order)
        return cls.validate_full(order)

    @classmethod
    def _run_validation(
            cls,
            order,
            phase: str = 'phase2',
            is_full: bool = True,
            completion_only: bool = False,
    ) -> List[str]:
        """Выполняет базовые проверки шапки/групп и холостой прогон OrderSpecEngine."""
        errors: List[str] = []

        if not getattr(order, 'order_number', None):
            errors.append("חסר מספר הזמנה")
        if not getattr(order, 'customer', None):
            errors.append("חסר שם לקוח")

        # 1. Выборка активных позиций заказа
        items = TechnicalSpecService.get_rich_order_items(order_id=order.id)
        if completion_only:
            items = [it for it in items if it.group.production_state != OrderItemsGroup.ProductionState.COMPLETED]
        elif phase == 'phase1' and getattr(order, 'has_split_installation', False):
            items = [it for it in items if it.group.is_split_installation]

        if not items:
            errors.append("אין פריטים פעילים בהזמנה לביצוע בדיקה")
            return errors

        # 2. Проверка шапки и групп
        has_any_doors = False
        target_groups = {it.group for it in items}

        for group in target_groups:
            group_label = f"קבוצה #{group.id} ({group.product.name if group.product else 'ללא מוצר'})"

            if not group.product:
                errors.append(f"{group_label}: לא נבחר דגם מוצר")
                continue

            if not (group.series or getattr(order, 'series', None)):
                errors.append(f"{group_label}: לא נבחרה סדרה")

            if not (group.front or getattr(order, 'front', None)):
                errors.append(f"{group_label}: לא נבחרה חזית")

            if is_full:
                if group.panel_paint_option == OrderItemsGroup.PaintOption.SPECIAL_COLOR:
                    if not group.color_panel_outside and not getattr(order, 'color_panel_outside', None):
                        errors.append(f"{group_label}: נבחר צבע מיוחד לכנף אך לא הוזן גוון")
                if group.frame_paint_option == OrderItemsGroup.PaintOption.SPECIAL_COLOR:
                    if not group.color_frames and not getattr(order, 'color_frames', None):
                        errors.append(f"{group_label}: נבחר צבע מיוחד למשקוף אך לא הוזן גוון")

            if group.product.has_door:
                has_any_doors = True

        if is_full and has_any_doors and not getattr(order, 'handle', None):
            errors.append("חובה לבחור דגם ידית להזמנה")

        if errors:
            return errors

        # 3. Холостой прогон через OrderSpecEngine (включая проверку ЧПУ-макросов без записи в БД)
        engine = OrderSpecEngine()
        spec_obj = engine.execute(order=order, items=items, phase=phase, save_labels=False)

        for b_items in spec_obj.batches.values():
            for it in b_items:
                if it.errors:
                    mark_label = f"דלת מס' {it.mark}" if it.mark else f"פריט #{it.item_id}"
                    for err in it.errors:
                        errors.append(f"{mark_label}: {err}")

        return errors
