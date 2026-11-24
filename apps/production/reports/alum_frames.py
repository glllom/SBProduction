"""Обработчик отчёта алюминиевых коробок (apps.production.reports.alum_frames)."""

from __future__ import annotations

from typing import Any, Dict

from .common import enrich_report_frames_spec, prepare_grouped_data
from .registry import BaseStationReport, ReportContext, register_report


@register_report('alum_frames', label='דו"ח משקופי אלומיניום', aliases=('100', 'frames', 'phase1_frames'))
class AlumFramesStationReport(BaseStationReport):
    """Альбомный табличный отчёт алюминиевых коробок с группировкой фурнитуры."""

    template_name = 'production/reports/alum_frames_report.html'
    include_template = 'production/includes/report_alum_frames.html'
    default_label = 'דו"ח משקופי אלומיניום'

    def get_extra_context(self, ctx: ReportContext) -> Dict[str, Any]:
        return {
            'groups_data': prepare_grouped_data(ctx.station_items),
            'enriched_frames_items': enrich_report_frames_spec(ctx.station_items),
        }
