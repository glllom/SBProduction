"""Обработчик отчёта дверных полотен / алюминиевых дверей (apps.production.reports.alum_doors)."""

from __future__ import annotations

from typing import Any, Dict

from .common import enrich_report_doors_spec, prepare_grouped_data
from .registry import BaseStationReport, ReportContext, register_report


@register_report('alum_doors', label='דו"ח כנפיים / דלתות אלומיניום', aliases=('doors', 'phase2_doors'))
class AlumDoorsStationReport(BaseStationReport):
    """Альбомный табличный отчёт дверных полотен с разметкой фурнитуры и кастомизаторов."""

    template_name = 'production/reports/alum_doors_report.html'
    include_template = 'production/includes/report_alum_doors.html'
    default_label = 'דו"ח דלתות'

    def get_extra_context(self, ctx: ReportContext) -> Dict[str, Any]:
        return {
            'groups_data': prepare_grouped_data(ctx.station_items),
            'enriched_doors_items': enrich_report_doors_spec(ctx.station_items),
        }
