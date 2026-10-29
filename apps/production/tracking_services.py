from typing import List, Tuple, Dict, Any, Optional

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.orders.models import OrderItem, OrderItemsGroup
from .models import (
    ItemStationProgress,
    StationStatus,
    StationProgressSource,
    StationScanAuditLog,
    ProductionStation,
    ProductionRoute,
)


class StationTrackingService:
    """
    Core service for station-level tracking, batch lifecycle,
    barcode/agent event processing, and shift backlog generation.
    """

    @classmethod
    @transaction.atomic
    def initialize_items_progress(
            cls,
            items: List[OrderItem],
            phase: str = 'phase2'
    ) -> int:
        """
        Creates ItemStationProgress records for Phase 2 / complete door sets.
        Phase 1 items are ignored by design.
        """
        if not items:
            return 0

        # Load stations grouped by route
        progress_entries: List[ItemStationProgress] = []

        for item in items:
            group = getattr(item, 'group', None)
            if not group:
                continue

            stations = ProductionRoute.get_stations_for_group(group)
            for idx, station in enumerate(stations, start=1):
                # Filter out phase 1 stations if this is pure phase 2 tracking
                if phase == 'phase2' and getattr(station, 'is_phase1', False):
                    continue

                progress_entries.append(
                    ItemStationProgress(
                        item=item,
                        station=station,
                        sequence=idx,
                        status=StationStatus.PENDING,
                        source=StationProgressSource.MANUAL,
                    )
                )

        if progress_entries:
            created = ItemStationProgress.objects.bulk_create(
                progress_entries,
                ignore_conflicts=True
            )
            return len(created)

        return 0

    @classmethod
    @transaction.atomic
    def initialize_batch_progress(cls, group: OrderItemsGroup) -> int:
        """
        Initializes progress for all items in a specific batch group.
        """
        items = list(group.items.all().select_related('group'))
        return cls.initialize_items_progress(items, phase='phase2')

    @classmethod
    @transaction.atomic
    def process_barcode_scan(
            cls,
            raw_code: str,
            user=None,
            source: str = StationProgressSource.SCANNER
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Processes scanned barcode.
        Supported formats:
        1. Batch header: "{order_number};{station_code};{batch_number}"
        2. Legacy header: "{order_number};{station_code}" (applies to all active batches)
        3. Single item label: "{order_number};{mark};{station_code}"
        """
        raw_code = (raw_code or '').strip()
        audit = StationScanAuditLog(
            raw_payload=raw_code,
            source=source,
            created_by=user if (user and user.is_authenticated) else None
        )

        parts = [p.strip() for p in raw_code.split(';') if p.strip()]

        # Validate structure
        if len(parts) not in (2, 3):
            err_msg = f"Некорректный формат QR-кода: '{raw_code}'"
            audit.is_success = False
            audit.message = err_msg
            audit.save()
            return False, err_msg, {}

        order_number = parts[0]
        audit.order_number = order_number

        # Format 1: "{order_number};{station_code};{batch_number}"
        if len(parts) == 3 and parts[2].isdigit():
            station_code = parts[1].upper()
            batch_num = int(parts[2])

            audit.station_code = station_code
            audit.batch_number = batch_num

            success, msg, data = cls._complete_batch_station(
                order_number=order_number,
                station_code=station_code,
                batch_number=batch_num,
                user=user,
                source=source
            )
            audit.is_success = success
            audit.message = msg
            audit.save()
            return success, msg, data

        # Format 3: Single item "{order_number};{mark};{station_code}"
        if len(parts) == 3 and not parts[2].isdigit():
            item_mark = parts[1]
            station_code = parts[2].upper()

            audit.item_mark = item_mark
            audit.station_code = station_code

            success, msg, data = cls._complete_single_item_station(
                order_number=order_number,
                item_mark=item_mark,
                station_code=station_code,
                user=user,
                source=source
            )
            audit.is_success = success
            audit.message = msg
            audit.save()
            return success, msg, data

        # Format 2: Legacy fallback "{order_number};{station_code}"
        station_code = parts[1].upper()
        audit.station_code = station_code

        success, msg, data = cls._complete_batch_station(
            order_number=order_number,
            station_code=station_code,
            batch_number=None,
            user=user,
            source=source
        )
        audit.is_success = success
        audit.message = msg
        audit.save()
        return success, msg, data

    @classmethod
    def _complete_batch_station(
            cls,
            order_number: str,
            station_code: str,
            batch_number: Optional[int],
            user=None,
            source: str = StationProgressSource.SCANNER
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Marks all pending items of an order/batch as completed for the target station.
        """
        station = ProductionStation.objects.filter(code__iexact=station_code).first()
        if not station:
            return False, f"Станция '{station_code}' не найдена в системе.", {}

        filter_kwargs: Dict[str, Any] = {
            'item__group__order__order_number': order_number,
            'station': station,
            'status': StationStatus.PENDING,
        }
        if batch_number is not None:
            filter_kwargs['item__group__batch_number'] = batch_number

        pending_qs = ItemStationProgress.objects.filter(**filter_kwargs)
        count = pending_qs.count()

        if count == 0:
            # Check if already completed
            completed_filter = {k: v for k, v in filter_kwargs.items() if k != 'status'}
            completed_filter['status'] = StationStatus.COMPLETED

            already_done = ItemStationProgress.objects.filter(**completed_filter).exists()
            batch_label = f" (батч #{batch_number})" if batch_number else ""

            if already_done:
                return False, f"Заказ {order_number}{batch_label} на участке {station.code} уже закрыт.", {}
            return False, f"В заказе {order_number}{batch_label} нет открытых позиций для участка {station.code}.", {}

        now = timezone.now()
        pending_qs.update(
            status=StationStatus.COMPLETED,
            completed_at=now,
            completed_by=user if (user and user.is_authenticated) else None,
            source=source
        )

        batch_str = f"батч #{batch_number}" if batch_number else "все батчи"
        msg = f"Заказ {order_number} ({batch_str}) закрыт на участке {station.code}: {count} поз."
        payload = {
            'order_number': order_number,
            'station_code': station.code,
            'batch_number': batch_number,
            'completed_count': count,
        }
        return True, msg, payload

    @classmethod
    def _complete_single_item_station(
            cls,
            order_number: str,
            item_mark: str,
            station_code: str,
            user=None,
            source: str = StationProgressSource.SCANNER
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Marks a single item as completed on a specific station.
        """
        station = ProductionStation.objects.filter(code__iexact=station_code).first()
        if not station:
            return False, f"Станция '{station_code}' не найдена.", {}

        progress = ItemStationProgress.objects.filter(
            item__group__order__order_number=order_number,
            item__mark=item_mark,
            station=station,
            status=StationStatus.PENDING
        ).first()

        if not progress:
            return False, f"Позиция {order_number} поз. {item_mark} на участке {station.code} не найдена или уже закрыта.", {}

        progress.mark_completed(user=user, source=source)
        msg = f"Позиция {order_number} #{item_mark} закрыта на участке {station.code}."
        payload = {
            'order_number': order_number,
            'item_mark': item_mark,
            'station_code': station.code,
            'completed_count': 1,
        }
        return True, msg, payload

    @staticmethod
    def get_station_backlog(station_code: str) -> List[Dict[str, Any]]:
        """
        Aggregates pending work for a specific station, grouped by order and batch,
        ordered by urgency (completion_date).
        """
        groups = (
            OrderItemsGroup.objects.filter(
                items__station_progress__station__code__iexact=station_code,
                items__station_progress__status=StationStatus.PENDING
            )
            .select_related('order')
            .annotate(
                pending_qty=Count(
                    'items__station_progress',
                    filter=Q(
                        items__station_progress__station__code__iexact=station_code,
                        items__station_progress__status=StationStatus.PENDING
                    )
                ),
                total_qty=Count(
                    'items__station_progress',
                    filter=Q(items__station_progress__station__code__iexact=station_code)
                )
            )
            .filter(pending_qty__gt=0)
            .distinct()
            .order_by('order__completion_date', 'order__id', 'batch_number')
        )

        backlog: List[Dict[str, Any]] = []
        for g in groups:
            backlog.append({
                'order_id': g.order.id,
                'order_number': g.order.order_number,
                'batch_number': g.batch_number,
                'customer': g.order.customer,
                'completion_date': g.order.completion_date,
                'pending_qty': g.pending_qty,
                'total_qty': g.total_qty,
                'is_urgent': getattr(g.order, 'is_urgent', False),
            })
        return backlog
