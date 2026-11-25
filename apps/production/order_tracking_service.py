from collections import defaultdict

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.engineering.models import ProductionStation
from apps.orders.models import Order, OrderItem, OrderItemsGroup
from apps.production.models import (
    ItemStationProgress,
    StationProgressSource,
    StationScanAuditLog,
    StationStatus,
)


class OrderTrackingService:
    """
    Сервис отслеживания и ручной корректировки маршрута на уровне заказа, батча и отдельной двери.
    """

    @classmethod
    def _base_progress_qs(cls):
        return (
            ItemStationProgress.objects
            .exclude(item__state=OrderItem.ItemState.CANCELED)
            .exclude(item__group__production_state=OrderItemsGroup.ProductionState.CANCELED)
            .select_related(
                'item',
                'item__group',
                'item__group__product',
                'item__group__order',
                'station',
                'completed_by',
            )
        )

    @classmethod
    def get_active_orders_overview(cls, query: str = '', only_anomalies: bool = False, limit: int = 40):
        """
        Возвращает список заказов, по которым есть записи трекинга, с прогрессом и флагом пропусков.
        Используется на главной странице поиска и в живом поиске.
        """
        qs = cls._base_progress_qs()

        if query:
            q_clean = query.strip()
            qs = qs.filter(
                Q(item__group__order__order_number__icontains=q_clean)
                | Q(item__group__order__customer__icontains=q_clean)
            )

        # Группируем прогресс по (order_id, item_id) для точного расчёта пропусков
        orders_map = {}
        per_order_items = defaultdict(lambda: defaultdict(list))

        for prog in qs.order_by('-item__group__order_id', 'sequence', 'id'):
            order = prog.item.group.order
            if order.id not in orders_map:
                orders_map[order.id] = {
                    'order': order,
                    'batches': set(),
                    'total_steps': 0,
                    'done_steps': 0,
                    'bypassed_stations': set(),
                    'last_activity': None,
                }
            rec = orders_map[order.id]
            rec['batches'].add(prog.item.group.batch_number or 1)
            rec['total_steps'] += 1
            if prog.status in (StationStatus.COMPLETED, StationStatus.SKIPPED):
                rec['done_steps'] += 1
            if prog.completed_at and (rec['last_activity'] is None or prog.completed_at > rec['last_activity']):
                rec['last_activity'] = prog.completed_at

            per_order_items[order.id][prog.item_id].append(prog)

        results = []
        for order_id, rec in orders_map.items():
            # Проверяем пропуски по каждой двери
            for item_progs in per_order_items[order_id].values():
                max_active_seq = max(
                    (
                        p.sequence for p in item_progs
                        if p.status in (StationStatus.COMPLETED, StationStatus.IN_PROGRESS)
                    ),
                    default=-1,
                )
                for p in item_progs:
                    if p.status == StationStatus.PENDING and p.sequence < max_active_seq:
                        rec['bypassed_stations'].add(p.station.name)

            total = rec['total_steps']
            done = rec['done_steps']
            pct = int(round((done / total) * 100)) if total else 0
            bypassed_list = sorted(rec['bypassed_stations'])

            if only_anomalies and not bypassed_list:
                continue

            results.append({
                'order': rec['order'],
                'batches_count': len(rec['batches']),
                'batches_sorted': sorted(rec['batches']),
                'total_steps': total,
                'done_steps': done,
                'progress_pct': pct,
                'is_finished': total > 0 and done == total,
                'has_anomaly': bool(bypassed_list),
                'bypassed_count': len(bypassed_list),
                'bypassed_names': bypassed_list,
                'last_activity': rec['last_activity'],
            })

        # Сначала заказы с пропусками, затем незавершённые, затем по свежести
        results.sort(
            key=lambda r: (
                not r['has_anomaly'],
                r['is_finished'],
                -(r['order'].id),
            )
        )
        return results[:limit]

    @classmethod
    def get_order_tracking_context(cls, order: Order, selected_batch: int | None = None):
        """
        Собирает полную структуру трекинга для конкретного заказа и выбранного батча.
        """
        progress_list = list(
            cls._base_progress_qs()
            .filter(item__group__order=order)
            .order_by('sequence', 'station__order', 'station_id', 'item_id')
        )

        # Определяем все батчи заказа (из трекинга + из активных групп заказа)
        batch_progress_map = defaultdict(list)
        for p in progress_list:
            b_num = p.item.group.batch_number or 1
            batch_progress_map[b_num].append(p)

        batches_summary = []
        total_order_steps = len(progress_list)
        done_order_steps = sum(
            1 for p in progress_list if p.status in (StationStatus.COMPLETED, StationStatus.SKIPPED)
        )

        for b_num in sorted(batch_progress_map.keys()):
            b_progs = batch_progress_map[b_num]
            b_items_map = defaultdict(list)
            b_doors = set()
            for p in b_progs:
                b_items_map[p.item_id].append(p)
                b_doors.add(p.item_id)

            b_bypassed_stations = set()
            for item_progs in b_items_map.values():
                max_seq = max(
                    (
                        p.sequence for p in item_progs
                        if p.status in (StationStatus.COMPLETED, StationStatus.IN_PROGRESS)
                    ),
                    default=-1,
                )
                for p in item_progs:
                    if p.status == StationStatus.PENDING and p.sequence < max_seq:
                        b_bypassed_stations.add(p.station_id)

            b_total = len(b_progs)
            b_done = sum(1 for p in b_progs if p.status in (StationStatus.COMPLETED, StationStatus.SKIPPED))
            b_pct = int(round((b_done / b_total) * 100)) if b_total else 0

            batches_summary.append({
                'batch_number': b_num,
                'doors_count': len(b_doors),
                'total_steps': b_total,
                'done_steps': b_done,
                'progress_pct': b_pct,
                'is_finished': b_total > 0 and b_done == b_total,
                'bypassed_count': len(b_bypassed_stations),
            })

        # Выбор активного батча
        available_batches = [b['batch_number'] for b in batches_summary]
        if selected_batch not in available_batches:
            selected_batch = available_batches[0] if available_batches else None

        station_rows = []
        bypassed_rows = []

        if selected_batch is not None:
            active_progs = batch_progress_map[selected_batch]

            # 1. Вычисляем per-item флаги: "пропущено" (bypassed) и "следующая текущая станция" (is_current)
            per_item = defaultdict(list)
            for p in active_progs:
                per_item[p.item_id].append(p)

            bypassed_prog_ids = set()
            current_prog_ids = set()

            for item_progs in per_item.values():
                item_progs.sort(key=lambda x: (x.sequence, x.id))
                max_active_seq = max(
                    (
                        p.sequence for p in item_progs
                        if p.status in (StationStatus.COMPLETED, StationStatus.IN_PROGRESS)
                    ),
                    default=-1,
                )
                first_pending_found = False
                for p in item_progs:
                    if p.status == StationStatus.PENDING and p.sequence < max_active_seq:
                        bypassed_prog_ids.add(p.id)
                    if not first_pending_found and p.status in (StationStatus.PENDING, StationStatus.IN_PROGRESS):
                        current_prog_ids.add(p.id)
                        first_pending_found = True

            # 2. Группируем по станции в порядке маршрута
            by_station = {}
            for p in active_progs:
                st = p.station
                if st.id not in by_station:
                    by_station[st.id] = {
                        'station': st,
                        'min_sequence': p.sequence,
                        'progress_items': [],
                    }
                else:
                    by_station[st.id]['min_sequence'] = min(by_station[st.id]['min_sequence'], p.sequence)
                by_station[st.id]['progress_items'].append(p)

            sorted_stations = sorted(
                by_station.values(),
                key=lambda x: (x['min_sequence'], x['station'].order, x['station'].id),
            )

            for idx, st_data in enumerate(sorted_stations, start=1):
                progs = st_data['progress_items']
                progs.sort(key=lambda p: (int(p.item.mark) if str(p.item.mark).isdigit() else 999999, p.item_id))

                total_cnt = len(progs)
                completed_cnt = sum(1 for p in progs if p.status == StationStatus.COMPLETED)
                skipped_cnt = sum(1 for p in progs if p.status == StationStatus.SKIPPED)
                in_prog_cnt = sum(1 for p in progs if p.status == StationStatus.IN_PROGRESS)
                pending_cnt = sum(1 for p in progs if p.status == StationStatus.PENDING)

                bypassed_items = [p for p in progs if p.id in bypassed_prog_ids]
                is_current_any = any(p.id in current_prog_ids for p in progs)

                # Итоговый статус строки станции
                if completed_cnt == total_cnt:
                    row_state = 'COMPLETED'
                    state_label = 'הושלם'
                    badge_class = 'sb-success'
                elif (completed_cnt + skipped_cnt) == total_cnt and skipped_cnt > 0:
                    row_state = 'SKIPPED'
                    state_label = 'דולג ידנית' if completed_cnt == 0 else f'הושלם ({skipped_cnt} דולגו)'
                    badge_class = 'sb-neutral'
                elif bypassed_items:
                    row_state = 'BYPASSED'
                    state_label = 'דולג / חריג'
                    badge_class = 'sb-warning'
                elif completed_cnt > 0 or in_prog_cnt > 0:
                    row_state = 'PARTIAL'
                    state_label = f'חלקי ({completed_cnt}/{total_cnt})'
                    badge_class = 'sb-primary'
                elif is_current_any:
                    row_state = 'CURRENT'
                    state_label = 'בתור כעת'
                    badge_class = 'sb-primary'
                else:
                    row_state = 'PENDING'
                    state_label = 'ממתין'
                    badge_class = 'sb-neutral'

                # Последняя запись о закрытии на станции
                completed_progs = [p for p in progs if p.completed_at]
                last_prog = max(completed_progs, key=lambda p: p.completed_at) if completed_progs else None

                doors_detail = []
                for p in progs:
                    doors_detail.append({
                        'progress': p,
                        'item': p.item,
                        'mark': p.item.mark or str(p.item_id),
                        'place': p.item.place or '',
                        'product_name': p.item.group.product.name if p.item.group.product else '',
                        'is_bypassed': p.id in bypassed_prog_ids,
                        'is_current': p.id in current_prog_ids,
                    })

                row_obj = {
                    'step_index': idx,
                    'station': st_data['station'],
                    'row_state': row_state,
                    'state_label': state_label,
                    'badge_class': badge_class,
                    'total_cnt': total_cnt,
                    'completed_cnt': completed_cnt,
                    'skipped_cnt': skipped_cnt,
                    'pending_cnt': pending_cnt + in_prog_cnt,
                    'has_pending': (pending_cnt + in_prog_cnt) > 0,
                    'has_done': (completed_cnt + skipped_cnt) > 0,
                    'is_bypassed': bool(bypassed_items),
                    'bypassed_marks': [p.item.mark or str(p.item_id) for p in bypassed_items],
                    'last_completed_at': last_prog.completed_at if last_prog else None,
                    'last_completed_by': last_prog.completed_by if last_prog else None,
                    'last_source_display': last_prog.get_source_display() if last_prog else '',
                    'doors_detail': doors_detail,
                }
                station_rows.append(row_obj)
                if row_obj['is_bypassed']:
                    bypassed_rows.append(row_obj)

        # Журнал последних событий сканирования и ручных правок по заказу
        audit_qs = StationScanAuditLog.objects.filter(
            order_number=str(order.order_number)
        ).select_related('created_by')
        if selected_batch is not None:
            audit_qs = audit_qs.filter(Q(batch_number=selected_batch) | Q(batch_number__isnull=True))
        audit_logs = list(audit_qs[:25])

        order_progress_pct = int(round((done_order_steps / total_order_steps) * 100)) if total_order_steps else 0

        return {
            'order': order,
            'batches_summary': batches_summary,
            'selected_batch': selected_batch,
            'station_rows': station_rows,
            'bypassed_rows': bypassed_rows,
            'total_order_steps': total_order_steps,
            'done_order_steps': done_order_steps,
            'order_progress_pct': order_progress_pct,
            'audit_logs': audit_logs,
        }

    @classmethod
    @transaction.atomic
    def apply_station_action(
            cls,
            order: Order,
            batch_number: int,
            action: str,
            user,
            station_code: str | None = None,
            progress_id: int | None = None,
    ) -> tuple[bool, str]:
        """
        Выполняет ручное действие диспетчера по батчу/станции или по одной двери
        с обязательной записью в StationScanAuditLog.
        """
        now = timezone.now()

        # 1. Действие по одной конкретной двери (ItemStationProgress)
        if progress_id:
            prog = (
                cls._base_progress_qs()
                .filter(pk=progress_id, item__group__order=order)
                .first()
            )
            if not prog:
                return False, 'רשומת התקדמות לא נמצאה.'

            if action == 'complete_item':
                prog.mark_completed(user=user, source=StationProgressSource.MANUAL)
                msg = f"דלת #{prog.item.mark} סומנה כהושלמה בתחנת {prog.station.name}."
            elif action == 'skip_item':
                prog.status = StationStatus.SKIPPED
                prog.completed_at = now
                prog.completed_by = user
                prog.source = StationProgressSource.MANUAL
                prog.save(update_fields=['status', 'completed_at', 'completed_by', 'source'])
                msg = f"דלת #{prog.item.mark} סומנה כדולגה בתחנת {prog.station.name}."
            elif action == 'reset_item':
                prog.reset_status()
                msg = f"דיווח דלת #{prog.item.mark} בתחנת {prog.station.name} אופס להמתנה."
            else:
                return False, 'פעולה לא חוקית.'

            StationScanAuditLog.objects.create(
                raw_payload=f"ORDER_TRACK:{action}:{order.order_number}:B{batch_number}:{prog.station.code}:#{prog.item.mark}",
                station_code=prog.station.code,
                order_number=str(order.order_number),
                batch_number=batch_number,
                item_mark=str(prog.item.mark or ''),
                source=StationProgressSource.MANUAL,
                is_success=True,
                message=msg,
                created_by=user,
            )
            return True, msg

        # 2. Закрыть все "проскочившие" станции в батче одним действием
        if action == 'complete_all_bypassed':
            ctx = cls.get_order_tracking_context(order, selected_batch=batch_number)
            updated = 0
            for row in ctx['bypassed_rows']:
                for d in row['doors_detail']:
                    if d['is_bypassed']:
                        d['progress'].mark_completed(user=user, source=StationProgressSource.MANUAL)
                        updated += 1

            if not updated:
                return False, 'אין תחנות שדולגו לסגירה.'

            msg = f"נסגרו בדיעבד {updated} שלבים שדולגו במנה [{batch_number}]."
            StationScanAuditLog.objects.create(
                raw_payload=f"ORDER_TRACK:complete_all_bypassed:{order.order_number}:B{batch_number}",
                station_code='MULTIPLE',
                order_number=str(order.order_number),
                batch_number=batch_number,
                source=StationProgressSource.MANUAL,
                is_success=True,
                message=msg,
                created_by=user,
            )
            return True, msg

        # 3. Действие по станции для всего батча
        station = ProductionStation.objects.filter(code=station_code).first()
        if not station:
            return False, 'תחנה לא נמצאה.'

        progs = list(
            cls._base_progress_qs().filter(
                item__group__order=order,
                item__group__batch_number=batch_number,
                station=station,
            )
        )
        if not progs:
            return False, 'לא נמצאו פריטים בתחנה זו עבור המנה שנבחרה.'

        changed = 0
        if action == 'complete_station':
            for p in progs:
                if p.status != StationStatus.COMPLETED:
                    p.mark_completed(user=user, source=StationProgressSource.MANUAL)
                    changed += 1
            msg = f"תחנת {station.name} במנה [{batch_number}] סומנה כהושלמה ({changed} יח')."
        elif action == 'skip_station':
            for p in progs:
                if p.status in (StationStatus.PENDING, StationStatus.IN_PROGRESS):
                    p.status = StationStatus.SKIPPED
                    p.completed_at = now
                    p.completed_by = user
                    p.source = StationProgressSource.MANUAL
                    p.save(update_fields=['status', 'completed_at', 'completed_by', 'source'])
                    changed += 1
            msg = f"תחנת {station.name} במנה [{batch_number}] סומנה כדולגה ידנית ({changed} יח')."
        elif action == 'reset_station':
            for p in progs:
                if p.status != StationStatus.PENDING:
                    p.reset_status()
                    changed += 1
            msg = f"דיווח תחנת {station.name} במנה [{batch_number}] בוטל והוחזר לתור ({changed} יח')."
        else:
            return False, 'פעולה לא מזוהה.'

        if changed:
            StationScanAuditLog.objects.create(
                raw_payload=f"ORDER_TRACK:{action}:{order.order_number}:B{batch_number}:{station.code}",
                station_code=station.code,
                order_number=str(order.order_number),
                batch_number=batch_number,
                source=StationProgressSource.MANUAL,
                is_success=True,
                message=msg,
                created_by=user,
            )
        return changed > 0, (msg if changed else 'לא בוצעו שינויים.')
