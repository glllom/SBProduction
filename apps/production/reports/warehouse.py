"""
Обработчик отчёта склада / комплектации фурнитуры (apps.production.reports.warehouse).

Назначение модуля:
    - Для автономной накладной склада возвращает структурированные секции
      OrderWarehouseItem через WarehousePackingSlipService.
    - Для сводного Master Print дополнительно рассчитывает краткую сводку
      hardware_summary (замки, ручки, петли) по выбранному батчу.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from apps.production.warehouse_service import WarehousePackingSlipService
from .common import get_field
from .registry import BaseStationReport, ReportContext, register_report


def build_warehouse_hardware_summary(items: List[Any]) -> List[Dict[str, Any]]:
    """Собирает краткую количественную сводку фурнитуры (замки, ручки, петли) по позициям."""
    locks = defaultdict(int)
    handles = defaultdict(int)
    hinges = defaultdict(int)

    for item in items:
        lock = get_field(item, 'lock_name')
        if lock:
            locks[lock] += 1

        handle = get_field(item, 'handle_name')
        if handle:
            handles[handle] += 1

        hinge = get_field(item, 'hinge_name')
        if hinge:
            raw_hinges = get_field(item, 'hinge_heights', []) or []
            count = len([h for h in raw_hinges if h is not None])
            hinges[hinge] += count if count > 0 else 3

    summary: List[Dict[str, Any]] = []
    for name, qty in sorted(locks.items()):
        summary.append({'category': 'מנעולים (Замки)', 'name': name, 'quantity': qty})
    for name, qty in sorted(handles.items()):
        summary.append({'category': 'ידיות (Ручки)', 'name': name, 'quantity': qty})
    for name, qty in sorted(hinges.items()):
        summary.append({'category': 'צירים (Петли)', 'name': name, 'quantity': qty})
    return summary


@register_report('warehouse', label='דו"ח מחסן / ליקוט פרזול', aliases=('hardware', 'pick_list'))
class WarehouseStationReport(BaseStationReport):
    """Отчёт комплектации фурнитуры на складе."""

    template_name = 'production/reports/report_warehouse_hardware.html'
    include_template = 'production/includes/report_warehouse_hardware.html'
    default_label = 'דו"ח פירזולים / ליקוט מחסן'
    requires_spec = False

    def get_extra_context(self, ctx: ReportContext) -> Dict[str, Any]:
        sections, _ = WarehousePackingSlipService.get_grouped_items_for_ui(ctx.order)
        return {
            'sections': sections,
            'hardware_summary': build_warehouse_hardware_summary(ctx.station_items),
        }
