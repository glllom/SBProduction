"""
Обработчик отчёта облицовок / панелей (apps.production.reports.facing).

Назначение модуля:
    Подтягивает актуальные URL эскизов (OrderItem.sketch) для каждой позиции
    облицовки: формирует facings_data для автономной печати на всю страницу
    и проставляет image_url в station_items для секции Master Print.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from apps.orders.models import OrderItem
from .common import get_field
from .registry import BaseStationReport, ReportContext, register_report


def _extract_sketch_url(db_item: OrderItem) -> Optional[str]:
    """Безопасно извлекает URL загруженного эскиза OrderItem."""
    if getattr(db_item, 'sketch', None):
        try:
            return db_item.sketch.url
        except ValueError:
            return None
    return getattr(db_item, 'sketch_url', None)


@register_report('facing', label='דו"ח חיפויים (עם שרטוטים)', aliases=('cladding', 'facing_report'))
class FacingStationReport(BaseStationReport):
    """Отчёт облицовок с полностраничным выводом эскиза на каждую позицию."""

    template_name = 'production/reports/report_facing.html'
    include_template = 'production/includes/report_facing.html'
    default_label = 'דו"ח חיפויים'

    def get_extra_context(self, ctx: ReportContext) -> Dict[str, Any]:
        # 1. Для Master Print: обогащаем station_items полем image_url из БД одним запросом
        item_ids = [get_field(it, 'item_id') for it in ctx.station_items if get_field(it, 'item_id')]
        db_items_map = {
            db_it.id: db_it
            for db_it in OrderItem.objects.filter(id__in=item_ids).select_related('group')
        } if item_ids else {}

        for it in ctx.station_items:
            it_id = get_field(it, 'item_id')
            url = _extract_sketch_url(db_items_map[it_id]) if it_id in db_items_map else None
            if isinstance(it, dict):
                it['image_url'] = url
            else:
                setattr(it, 'image_url', url)

        # 2. Для автономного отчёта: формируем facings_data по filtered_db_items
        valid_db_items: List[OrderItem] = ctx.filtered_db_items
        if ctx.requested_batches and item_ids:
            allowed_ids = set(item_ids)
            valid_db_items = [it for it in valid_db_items if it.id in allowed_ids]

        facings_data = [
            {
                'item': db_it,
                'group': db_it.group,
                'image_url': _extract_sketch_url(db_it),
            }
            for db_it in valid_db_items
        ]
        return {'facings_data': facings_data}
