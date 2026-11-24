"""
Пакет расчётного ядра производства (apps.production.engine).

Экспортирует единый публичный API:
    - OrderSpecEngine: линейный расчёт спецификации заказа.
    - TechnicalSpecService: чтение/кэширование снимков OrderSpecificationSnapshot.
    - OrderValidationService / ValidationResult / ValidationType: валидация заказа.
    - OrderValidationError: исключение ошибок расчёта и валидации.
    - OrderSpec, ProductionSpec: Pydantic-схемы спецификации.
"""

from .runner import OrderSpecEngine
from .schemas import OrderSpec, ProductionSpec
from .spec_gateway import OrderValidationError, TechnicalSpecService
from .validation import OrderValidationService, ValidationResult, ValidationType

__all__ = [
    'OrderSpec',
    'OrderSpecEngine',
    'OrderValidationError',
    'OrderValidationService',
    'ProductionSpec',
    'TechnicalSpecService',
    'ValidationResult',
    'ValidationType',
]
