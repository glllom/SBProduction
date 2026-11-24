"""
Универсальный обработчик отчёта станции по умолчанию (apps.production.reports.generic).

Назначение модуля:
    Позволяет подключать новые производственные станции с простыми табличными
    отчётами вообще без написания Python-кода: достаточно положить HTML-шаблон
    в templates/production/reports/ (и фрагмент в includes/) и указать путь в админке.
"""

from __future__ import annotations

from typing import Any, Dict

from .common import enrich_report_doors_spec, enrich_report_frames_spec, prepare_grouped_data
from .registry import BaseStationReport, ReportContext, register_report


@register_report('generic', label='דו"ח טבלאי סטנדרטי (Generic)', aliases=('carpentry', 'glazing'))
class GenericStationReport(BaseStationReport):
    """Передаёт в HTML-шаблон стандартный набор сгруппированных и размеченных позиций."""

    def get_extra_context(self, ctx: ReportContext) -> Dict[str, Any]:
        return {
            'groups_data': prepare_grouped_data(ctx.station_items),
            'enriched_frames_items': enrich_report_frames_spec(ctx.station_items),
            'enriched_doors_items': enrich_report_doors_spec(ctx.station_items),
        }
