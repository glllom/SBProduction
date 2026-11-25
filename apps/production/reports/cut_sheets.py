"""Обработчик отчёта раскроя листов и панелей (apps.production.reports.cut_sheets)."""

from __future__ import annotations

from typing import Any, Dict

from .common import prepare_grouped_data
from .registry import BaseStationReport, ReportContext, register_report


@register_report('cut_sheets', label='דו"ח חיתוך לוחות (Cut Sheets)', aliases=('sheets',))
class CutSheetsStationReport(BaseStationReport):
    """Отчёт раскроя алюкобонда, наружных/внутренних панелей и реек."""

    template_name = 'production/reports/cut_sheets_report.html'
    include_template = 'production/includes/report_cut_sheets.html'
    default_label = 'דו"ח חיתוך לוחות'

    def get_extra_context(self, ctx: ReportContext) -> Dict[str, Any]:
        return {
            'groups_data': prepare_grouped_data(ctx.station_items),
        }
