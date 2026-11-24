"""
Пакет модульных печатных отчётов производственных станций (apps.production.reports).

Экспортирует реестр ReportRegistry, базовый класс BaseStationReport, контекст
ReportContext и декоратор register_report. Все модули отчётов в этой папке
подгружаются автоматически при старте Django.
"""

from .registry import BaseStationReport, ReportContext, ReportRegistry, register_report

__all__ = [
    'BaseStationReport',
    'ReportContext',
    'ReportRegistry',
    'register_report',
]
