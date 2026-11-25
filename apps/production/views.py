import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.catalog.models import Hardware
from apps.engineering.models import (
    ProductEngineeringRule,
    ProductionStation,
)
from apps.orders.models import (
    Order,
    OrderChangeLog,
    OrderItem,
    OrderItemsGroup,
    OrderStatus,
    OrderWarehouseItem,
)
from apps.production.services import (
    OrderProductionService,
    OrderValidationError,
    OrderValidationService,
    ProductionDataService,
    TechnicalSpecService,
    get_qr_base64,
)
from .models import DoorLabel, OrderStationNote, StationProgressSource
from .tracking_services import StationTrackingService
from .usb_sync import run_usb_sync


def get_station_comment(order, station) -> str:
    if not order or not station:
        return ''
    if hasattr(station, 'note_text'):
        return station.note_text or ''
    note = OrderStationNote.objects.filter(order=order, station=station).first()
    return note.comment if note else ''


def extract_items_from_batches(batches_dict: dict, batch_filter: str = None) -> list:
    """Извлекает плоский список позиций из структуры batches с опциональной фильтрацией."""
    if not batches_dict or not isinstance(batches_dict, dict):
        return []

    items = []
    for b_num, b_items in batches_dict.items():
        if batch_filter is not None and str(b_num) != str(batch_filter):
            continue
        items.extend(b_items)
    return items


# === 1. Production Lifecycle & Status Actions ===

@login_required
def order_transfer_to_production(request, pk):
    """
    Unified entry point for production launch:
    - From PHASE1_READY (GET): displays measurement entry form with gross heights and inner dimensions.
    - From PHASE1_READY (POST): adds frame deltas to inner dimensions, saves nominal kit sizes and starts Phase 2.
    - From NEW / reorder: immediately launches production in 1-click.
    """
    order = get_object_or_404(Order, pk=pk)

    if order.status == OrderStatus.PHASE1_READY:
        try:
            order_spec, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase1')
            valid_groups = order.groups.filter(
                is_split_installation=True,
                batch_number__isnull=False,
                production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION,
            )
            requested_batches = list(valid_groups.values_list('batch_number', flat=True).distinct())

            raw_items, _ = ProductionDataService.extract_report_items(
                order_spec,
                requested_batches=requested_batches,
            )
            raw_items = raw_items if raw_items is not None else []
        except Exception:
            raw_items = []

        item_deltas = {}
        for it in raw_items:
            it_id = it.get('item_id') if isinstance(it, dict) else getattr(it, 'item_id', None)
            nom_w = float(it.get('width') if isinstance(it, dict) else getattr(it, 'width', 0.0) or 0.0)
            nom_h = float(it.get('height') if isinstance(it, dict) else getattr(it, 'height', 0.0) or 0.0)
            inn_w = float(it.get('inner_width') if isinstance(it, dict) else getattr(it, 'inner_width', 0.0) or nom_w)
            inn_h = float(it.get('inner_height') if isinstance(it, dict) else getattr(it, 'inner_height', 0.0) or nom_h)

            item_deltas[it_id] = {
                'delta_w': nom_w - inn_w,
                'delta_h': nom_h - inn_h,
            }

        if request.method == 'POST':
            with transaction.atomic():
                items_by_id = {
                    item.id: item for item in OrderItem.objects.filter(
                        group__order=order
                    ).select_related('group__product__product_family').exclude(
                        group__production_state__in=[
                            OrderItemsGroup.ProductionState.WAITING,
                            OrderItemsGroup.ProductionState.CANCELED,
                        ]
                    )
                }
                change_logs = []
                clearance_cache = {}

                for item_id, order_item in items_by_id.items():
                    modified = False
                    mark = order_item.mark or str(item_id)
                    deltas = item_deltas.get(item_id, {'delta_w': 0.0, 'delta_h': 0.0})

                    top_clearance = 0.3
                    product = order_item.group.product if order_item.group else None
                    if product:
                        if product.id not in clearance_cache:
                            clearance_cache[product.id] = float(
                                ProductEngineeringRule.resolve_for_product(product).leaf_top_clearance
                            )
                        top_clearance = clearance_cache[product.id]

                    for field in ['height', 'width', 'wall']:
                        key = f"item_{item_id}_{field}"
                        inner_key = f"item_{item_id}_inner_{field}"
                        val = request.POST.get(inner_key) if inner_key in request.POST else request.POST.get(key)

                        if val is not None and val.strip() != '':
                            try:
                                measured_val = float(val)

                                if field == 'width':
                                    new_val = round(measured_val + deltas['delta_w'], 1)
                                elif field == 'height':
                                    new_val = round(measured_val + deltas['delta_h'], 1)
                                else:
                                    new_val = measured_val

                                old_val = float(getattr(order_item, field)) if getattr(order_item, field) else None
                                if new_val != old_val:
                                    setattr(order_item, field, new_val)
                                    modified = True
                                    change_logs.append(OrderChangeLog(
                                        order=order,
                                        user=request.user,
                                        field_name=f"Item {mark} {field.capitalize()}",
                                        old_value=str(old_val) if old_val is not None else "None",
                                        new_value=str(new_val) if new_val is not None else "None",
                                    ))
                            except (ValueError, TypeError):
                                pass

                    lh_key = f"item_{item_id}_lock_height"
                    if lh_key in request.POST:
                        try:
                            val = request.POST.get(lh_key)
                            gross_lh = float(val) if val else None
                            new_lh = round(gross_lh - top_clearance, 2) if gross_lh is not None else None
                            old_lh = float(order_item.custom_lock_height) if order_item.custom_lock_height else None
                            if new_lh != old_lh:
                                order_item.custom_lock_height = new_lh
                                modified = True
                                change_logs.append(OrderChangeLog(
                                    order=order,
                                    user=request.user,
                                    field_name=f"Item {mark} Lock Height",
                                    old_value=str(old_lh) if old_lh is not None else "None",
                                    new_value=str(new_lh) if new_lh is not None else "None",
                                ))
                        except (ValueError, TypeError):
                            pass

                    for i in range(1, 6):
                        hh_key = f"item_{item_id}_hinge_height_{i - 1}"
                        field_name = f"custom_hinge{i}"
                        if hh_key in request.POST:
                            try:
                                val = request.POST.get(hh_key)
                                gross_hh = float(val) if val else None
                                new_hh = round(gross_hh - top_clearance, 2) if gross_hh is not None else None
                                old_hh = (
                                    float(getattr(order_item, field_name))
                                    if getattr(order_item, field_name)
                                    else None
                                )
                                if new_hh != old_hh:
                                    setattr(order_item, field_name, new_hh)
                                    modified = True
                                    change_logs.append(OrderChangeLog(
                                        order=order,
                                        user=request.user,
                                        field_name=f"Item {mark} Hinge {i}",
                                        old_value=str(old_hh) if old_hh is not None else "None",
                                        new_value=str(new_hh) if new_hh is not None else "None",
                                    ))
                            except (ValueError, TypeError):
                                pass

                    if modified:
                        order_item.save()

                if change_logs:
                    OrderChangeLog.objects.bulk_create(change_logs)

                launch_errors = OrderProductionService.validate_launch_rules(order)
                if launch_errors:
                    for err in launch_errors:
                        messages.error(request, err)
                    return redirect('order-detail', pk=pk)

                new_groups = list(order.groups.filter(production_state=OrderItemsGroup.ProductionState.NEW))
                if new_groups:
                    released_batch = order.current_batch or 1
                    OrderProductionService._release_groups_to_batch(new_groups, released_batch)
                    order.current_batch = released_batch + 1
                    order.save(update_fields=['current_batch'])

                old_status = order.status
                order.status = OrderStatus.PHASE2_PRODUCTION
                order.save(update_fields=['status'])
                OrderChangeLog.objects.create(
                    order=order,
                    user=request.user,
                    field_name='status',
                    old_value=old_status,
                    new_value=order.status,
                )

                TechnicalSpecService.get_or_build_spec(
                    order, phase='phase2', force_rebuild=True, user=request.user
                )

                active_phase2_groups = order.groups.filter(
                    production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION
                )
                for group in active_phase2_groups:
                    StationTrackingService.initialize_batch_progress(group)

            messages.success(request, "ההזמנה הועברה לשלב ב' בהצלחה.")
            return redirect('order-detail', pk=pk)

        items_data = []

        for item in raw_items:
            item_copy = dict(item) if isinstance(item, dict) else {
                'item_id': getattr(item, 'item_id', None),
                'mark': getattr(item, 'mark', ''),
                'leaf_top_clearance': getattr(item, 'leaf_top_clearance', 0.3),
                'inner_width': getattr(item, 'inner_width', None) or getattr(item, 'width', 0.0),
                'inner_height': getattr(item, 'inner_height', None) or getattr(item, 'height', 0.0),
                'lock_name': getattr(item, 'lock_name', ''),
                'lock_height_on_frame': getattr(item, 'lock_height_on_frame', None),
                'lock_height': getattr(item, 'lock_height', None),
                'hinge_name': getattr(item, 'hinge_name', ''),
                'hinge_heights_on_frame': getattr(item, 'hinge_heights_on_frame', []),
                'hinge_heights': getattr(item, 'hinge_heights', []),
            }

            top_clearance = abs(float(item_copy.get('leaf_top_clearance') or 0.3))

            item_copy['inner_width'] = item_copy.get('inner_width') or 0.0
            item_copy['inner_height'] = item_copy.get('inner_height') or 0.0

            if 'lock_height_on_frame' in item_copy and item_copy['lock_height_on_frame'] is not None:
                item_copy['lock_height'] = item_copy['lock_height_on_frame']
            elif item_copy.get('lock_height') is not None:
                item_copy['lock_height'] = round(float(item_copy['lock_height']) + top_clearance, 2)

            gross_hinges = []
            if item_copy.get('hinge_heights_on_frame'):
                gross_hinges = [h for h in item_copy['hinge_heights_on_frame'] if h is not None]
            elif item_copy.get('hinge_heights'):
                gross_hinges = [
                    round(float(h) + top_clearance, 2)
                    for h in item_copy['hinge_heights']
                    if h is not None
                ]

            item_copy['padded_hinges'] = (list(gross_hinges) + [None] * 5)[:5]
            items_data.append(item_copy)

        return render(request, 'production/transfer_to_phase2_form.html', {
            'order': order,
            'items_data': items_data,
        })

    try:
        OrderProductionService.start_production(order, user=request.user)

        is_ajax = (
                request.headers.get('x-requested-with') == 'XMLHttpRequest'
                or 'application/json' in request.headers.get('Accept', '')
        )
        if is_ajax:
            released_batch = (order.current_batch or 2) - 1
            master_url = f"{reverse('production:station-report', kwargs={'pk': pk})}?station=ALL&batch={released_batch}"
            return JsonResponse({
                'status': 'ok',
                'message': 'The order was successfully transferred to production.',
                'master_report_url': master_url,
            })

        messages.success(request, "The order was successfully transferred to production.")
    except (ValueError, OrderValidationError) as e:
        errors = getattr(e, 'errors', [str(e)])
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'errors': errors}, status=400)
        for err in errors:
            messages.error(request, err)

    return redirect('order-detail', pk=pk)


@login_required
@require_POST
def group_toggle_state(request, pk, group_id):
    """Переключает статус группы (пауза, снятие с паузы, отмена, восстановление) с валидацией фаз."""
    order = get_object_or_404(Order, pk=pk)
    group = get_object_or_404(order.groups, pk=group_id)
    new_state = (request.POST.get('state') or '').strip()

    try:
        msg = OrderProductionService.change_group_state(group, new_state, user=request.user)
        messages.success(request, msg)
    except (ValueError, OrderValidationError) as e:
        for err in getattr(e, 'errors', [str(e)]):
            messages.error(request, err)

    return redirect('order-detail', pk=pk)


@login_required
def order_check_validation(request, pk):
    """Manual validation check triggered from the UI before starting production."""
    order = get_object_or_404(Order, pk=pk)
    is_valid, errors = OrderProductionService.validate_for_production(order)
    if is_valid:
        messages.success(request, "Data is valid. Ready for production transfer.")
    else:
        for error in errors:
            messages.error(request, error)
    return redirect('order-detail', pk=pk)


@login_required
def order_complete_phase1(request, pk):
    """
    Marks Phase 1 production as completed and bakes updated measurements into Phase 1 spec snapshot.
    """
    order = get_object_or_404(Order, pk=pk)

    if order.status != OrderStatus.PHASE1_PRODUCTION:
        messages.error(request, "Order is not in Phase 1 production.")
        return redirect('order-detail', pk=pk)

    if order.groups.filter(production_state=OrderItemsGroup.ProductionState.NEW).exists():
        messages.error(request, "קיימות קבוצות חדשות שטרם הועברו לייצור — העבר אותן או השהה לפני סיום שלב א'.")
        return redirect('order-detail', pk=pk)

    try:
        spec_obj, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase1')
    except Exception as e:
        messages.error(request, f"Error building spec: {e}")
        return redirect('order-detail', pk=pk)

    batches = getattr(spec_obj, 'batches', {}) or {}
    items_raw = [it for b in batches.values() for it in b]
    spec_items = [
        it.model_dump() if hasattr(it, 'model_dump') else (it if isinstance(it, dict) else it.dict())
        for it in items_raw
    ]

    if request.method == 'POST':
        change_logs = []
        items_by_id = {item.id: item for item in OrderItem.objects.filter(group__order=order)}
        any_modified = False

        for item_spec in spec_items:
            item_id = item_spec.get('item_id')
            mark = item_spec.get('number') or item_spec.get('mark') or str(item_id)
            order_item = items_by_id.get(item_id)
            if not order_item:
                continue

            item_modified = False

            lh_key = f"item_{item_id}_lock_height"
            if lh_key in request.POST:
                val = request.POST.get(lh_key)
                try:
                    new_val = float(val) if val else None
                    old_val = float(order_item.custom_lock_height) if order_item.custom_lock_height else None
                    if new_val != old_val:
                        order_item.custom_lock_height = new_val
                        item_modified = True
                        change_logs.append(OrderChangeLog(
                            order=order,
                            user=request.user,
                            field_name=f"Item {mark} Lock Height",
                            old_value=str(old_val) if old_val is not None else "None",
                            new_value=str(new_val) if new_val is not None else "None",
                        ))
                except (ValueError, TypeError):
                    pass

            new_hinge_heights = []
            hinges_in_post = False
            for i in range(5):
                hh_key = f"item_{item_id}_hinge_height_{i}"
                if hh_key in request.POST:
                    hinges_in_post = True
                    val = request.POST.get(hh_key)
                    if val:
                        try:
                            new_hinge_heights.append(float(val))
                        except (ValueError, TypeError):
                            pass

            if hinges_in_post:
                for i in range(5):
                    field_name = f"custom_hinge{i + 1}"
                    new_h = new_hinge_heights[i] if i < len(new_hinge_heights) else None
                    old_h = float(getattr(order_item, field_name)) if getattr(order_item, field_name) else None
                    if new_h != old_h:
                        setattr(order_item, field_name, new_h)
                        item_modified = True
                        change_logs.append(OrderChangeLog(
                            order=order,
                            user=request.user,
                            field_name=f"Item {mark} Hinge {i + 1}",
                            old_value=str(old_h) if old_h is not None else "None",
                            new_value=str(new_h) if new_h is not None else "None",
                        ))

            if item_modified:
                order_item.save()
                any_modified = True

        if change_logs:
            OrderChangeLog.objects.bulk_create(change_logs)

        if any_modified:
            TechnicalSpecService.get_or_build_spec(order, phase='phase1', force_rebuild=True)

        try:
            OrderProductionService.complete_phase1(order, user=request.user)
            messages.success(request, "שלב א' הסתיים בהצלחה והמפרט עודכן.")
            return redirect('order-detail', pk=pk)
        except (ValueError, OrderValidationError) as e:
            messages.error(request, str(e))
            return redirect('order-detail', pk=pk)

    items_data = []
    for item in spec_items:
        hinges = item.get('hinge_heights') or item.get('hinges height') or []
        lock_h = item.get('lock_height') or item.get("lock's height") or ''

        item_copy = item.copy()
        item_copy['lock_height'] = lock_h
        item_copy['padded_hinges'] = (list(hinges) + [None] * 5)[:5]
        items_data.append(item_copy)

    return render(request, 'production/complete_phase1_form.html', {
        'order': order,
        'items_data': items_data,
    })


@login_required
def order_complete_production(request, pk):
    """Completes overall production for the order."""
    order = get_object_or_404(Order, pk=pk)
    try:
        OrderProductionService.complete_production(order, user=request.user)
        messages.success(request, "Production successfully completed.")
    except ValueError or OrderValidationError as e:
        messages.error(request, str(e))
    return redirect('order-detail', pk=pk)


# === 2. Exports and Station Reports ===

@login_required
def order_production_data(request, pk, **kwargs):
    """Generates and downloads the ZIP archive containing CNC machine files and technical reports."""
    order = get_object_or_404(Order, pk=pk)
    service = ProductionDataService(order)
    try:
        buffer = service.generate_production_zip()
        response = HttpResponse(buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="production_data_{order.order_number}.zip"'
        return response
    except Exception as e:
        messages.error(request, f"Production data generation failed: {e}")
        return redirect('order-detail', pk=pk)


@login_required
def spec_json_preview(request, pk):
    """Direct inspection endpoint for the latest JSON specification snapshot."""
    order = get_object_or_404(Order, pk=pk)

    if TechnicalSpecService.has_snapshot(order, 'phase2') or order.status in [
        OrderStatus.PHASE2_PRODUCTION,
        OrderStatus.COMPLETED,
        OrderStatus.IN_PRODUCTION,
    ]:
        active_phase = 'phase2'
    else:
        active_phase = 'phase1'

    spec_obj, spec_cache = TechnicalSpecService.get_or_build_spec(
        order, phase=active_phase
    )

    data = (
        spec_obj.model_dump(by_alias=True)
        if hasattr(spec_obj, 'model_dump')
        else spec_cache
    )

    return JsonResponse(
        data,
        safe=False,
        json_dumps_params={'indent': 2, 'ensure_ascii': False},
    )


@login_required
def order_dev_force_rebuild_spec(request, pk):
    """
    Development-only helper: Forces a full spec rebuild regardless of cache/status
    and redirects to the JSON preview.
    """
    order = get_object_or_404(Order, pk=pk)

    try:
        TechnicalSpecService.get_or_build_spec(order, phase='phase1', force_rebuild=True)
        TechnicalSpecService.get_or_build_spec(order, phase='phase2', force_rebuild=True)
        messages.success(request, f"Spec for Order {order.order_number} was forcefully rebuilt.")
    except Exception as e:
        messages.error(request, f"Rebuild failed: {e}")
        return redirect('order-detail', pk=pk)

    return redirect('production:spec-json-preview', pk=pk)


@login_required
def split_measurer_report(request, pk):
    """
    Report for the measurer before phase 2, specifically for split installations.
    Uses Phase 1 specification data across active split batches (excluding NEW/WAITING/CANCELED).
    """
    order = get_object_or_404(Order, pk=pk)

    if not order.has_split_installation:
        messages.error(request, "This report is only available for split installations.")
        return redirect('order-detail', pk=pk)

    batch_params = request.GET.getlist('batch')
    requested_batches = [int(b) for b in batch_params if b.isdigit()] if batch_params else None

    try:
        order_spec, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase1')

        valid_groups = order.groups.filter(
            is_split_installation=True,
            batch_number__isnull=False,
            production_state__in=(
                OrderItemsGroup.ProductionState.IN_PRODUCTION,
                OrderItemsGroup.ProductionState.COMPLETED,
            ),
        )

        if not requested_batches:
            requested_batches = list(valid_groups.values_list('batch_number', flat=True).distinct())

        flat_items, batches_label = ProductionDataService.extract_report_items(
            order_spec,
            requested_batches=requested_batches,
        )

        allowed_item_ids = set(
            OrderItem.objects.filter(
                group__in=valid_groups,
                state=OrderItem.ItemState.ACTIVE,
            ).values_list('id', flat=True)
        )

        spec_items = [
            it for it in (flat_items or [])
            if (it.get('item_id') if isinstance(it, dict) else getattr(it, 'item_id', None)) in allowed_item_ids
        ]
    except Exception as e:
        errors = getattr(e, 'errors', [str(e)])
        return render(request, 'production/report_validation_error.html', {
            'order': order,
            'errors': errors,
            'phase': 'phase1',
        })

    return render(request, 'production/reports/split_measurer_report.html', {
        'order': order,
        'order_spec': order_spec,
        'spec_items': spec_items,
        'batches_label': batches_label or '',
        'report_label': "דו''ח מדידה לאחר שלב א'",
        'now': timezone.now(),
    })


@login_required
def order_compare_snapshots(request, pk):
    """
    Compares Phase 1 and Phase 2 specification snapshots for administrators.
    Extracts item data directly from OrderSpecificationSnapshot JSON.
    """
    order = get_object_or_404(Order, pk=pk)

    if not request.user.is_admin_user:
        messages.error(request, "Access denied. Admins only.")
        return redirect('order-detail', pk=pk)

    if order.status != OrderStatus.PHASE2_PRODUCTION:
        messages.error(request, "Comparison is only available for orders in Phase 2 Production.")
        return redirect('order-detail', pk=pk)

    phase1_data = TechnicalSpecService.get_latest_spec_data(order, phase='phase1')
    phase2_data = TechnicalSpecService.get_latest_spec_data(order, phase='phase2')
    if not phase1_data or not phase2_data:
        messages.error(request, "Snapshots for comparison are missing.")
        return redirect('order-detail', pk=pk)

    spec_labels = {
        'width': 'רוחב',
        'height': 'גובה',
        'wall': 'עובי קיר',
        'addition_cut': 'קיצור נוסף',
        'direction': 'כיוון פתיחה',
        'opening': 'סוג פתיחה',
        'front_name': 'חזית',
        'color_panel_outside': 'צבע כנף חוץ',
        'color_panel_inside': 'צבע כנף פנים',
        'color_frames': 'צבע משקופים',
        'handle_name': 'ידית',
        'lock_name': 'מנעול',
        'hinge_name': 'צירים',
    }

    batches1 = phase1_data.get('batches', {}) if isinstance(phase1_data, dict) else {}
    batches2 = phase2_data.get('batches', {}) if isinstance(phase2_data, dict) else {}

    items1_list = [it for b in batches1.values() for it in b]
    items2_list = [it for b in batches2.values() for it in b]

    items1 = {item['item_id']: item for item in items1_list if isinstance(item, dict) and 'item_id' in item}
    items2 = {item['item_id']: item for item in items2_list if isinstance(item, dict) and 'item_id' in item}

    comparison_results = []

    for item_id, item1 in items1.items():
        item2 = items2.get(item_id)
        if not item2:
            continue

        changes = []

        lh1 = item1.get('lock_height')
        lh2 = item2.get('lock_height')
        changes.append({
            'label': 'גובה מנעול (Lock Height)',
            'old': lh1 if lh1 is not None else '-',
            'new': lh2 if lh2 is not None else '-',
            'changed': lh1 != lh2,
        })

        hh1 = item1.get('hinge_heights', [])
        hh2 = item2.get('hinge_heights', [])
        changes.append({
            'label': 'גבהי צירים (Hinge Heights)',
            'old': ", ".join(map(str, hh1)) if hh1 else "-",
            'new': ", ".join(map(str, hh2)) if hh2 else "-",
            'changed': hh1 != hh2,
        })

        for field_key, label in spec_labels.items():
            val1 = item1.get(field_key)
            val2 = item2.get(field_key)

            if val1 != val2:
                if field_key not in ('lock_name', 'hinge_name') and val1 in (None, ""):
                    continue

                changes.append({
                    'label': label,
                    'old': val1 if val1 not in (None, "") else "-",
                    'new': val2 if val2 not in (None, "") else "-",
                    'changed': True,
                })

        comparison_results.append({
            'mark': item1.get('mark', f"Item {item_id}"),
            'changes': changes,
        })

    return render(request, 'production/compare_snapshots.html', {
        'order': order,
        'comparison_results': comparison_results,
    })


@require_POST
def sync_usb_view(request):
    result = run_usb_sync()
    if result["success"]:
        messages.success(request, result["message"])
    else:
        messages.error(request, result["message"])
    return redirect(request.META.get("HTTP_REFERER", "/"))


@login_required
def order_sketches_report(request, pk):
    order = get_object_or_404(Order, pk=pk)

    groups_qs = order.groups.exclude(
        production_state__in=[
            OrderItemsGroup.ProductionState.WAITING,
            OrderItemsGroup.ProductionState.CANCELED,
        ]
    )

    if order.status == OrderStatus.COMPLETION_PRODUCTION:
        groups_qs = groups_qs.exclude(
            production_state=OrderItemsGroup.ProductionState.COMPLETED
        )

    items_qs = (
        order.groups.filter(id__in=groups_qs.values_list('id', flat=True))
        .prefetch_related('items')
    )

    all_items = []
    for group in items_qs:
        all_items.extend(list(group.items.all()))

    def parse_mark(it):
        try:
            return int(it.mark)
        except (ValueError, TypeError):
            return 999999

    all_items.sort(key=parse_mark)

    sketches = []
    for it in all_items:
        url = None
        if hasattr(it, 'sketch') and it.sketch:
            try:
                url = it.sketch.url
            except ValueError:
                pass
        elif hasattr(it, 'sketch_url') and it.sketch_url:
            url = it.sketch_url

        if url:
            sketches.append({
                'item_id': it.id,
                'mark': it.mark,
                'place': it.place or '',
                'image_url': url,
            })

    return render(request, 'production/reports/order_sketches_report.html', {
        'order': order,
        'sketches': sketches,
        'now': timezone.now(),
    })


@csrf_exempt
@require_POST
def bartender_confirm_print(request):
    """
    Write-back endpoint for BarTender:
    Accepts label_id or (order_number + item_mark + label_type)
    Increments print_count and updates last_printed_at.
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    label_id = data.get('label_id')
    if label_id:
        labels = DoorLabel.objects.filter(pk=label_id)
    else:
        labels = DoorLabel.objects.filter(
            order_number=data.get('order_number'),
            item_mark=data.get('item_mark'),
            label_type=data.get('label_type'),
        )

    if not labels.exists():
        return JsonResponse({'status': 'error', 'message': 'Label not found'}, status=404)

    updated_count = 0
    now = timezone.now()
    for lbl in labels:
        lbl.print_count += 1
        lbl.last_printed_at = now
        lbl.save(update_fields=['print_count', 'last_printed_at'])
        updated_count += 1

    return JsonResponse({'status': 'ok', 'updated': updated_count})


@login_required
def order_warehouse_setup(request, pk):
    """
    Управление накладной склада:
    - Состояние 0 -> 1: автоподбор из заказа при открытии.
    - Состояние 1: редактирование, сохранение черновика, пересчёт, или 'Утвердить и распечатать' (-> состояние 2).
    - Состояние 2: заблокировано; разблокировка доступна только администратору с повышением версии.
    """
    from .warehouse_service import WarehousePackingSlipService

    order = get_object_or_404(Order, pk=pk)

    is_admin = bool(
        request.user.is_superuser
        or getattr(request.user, 'is_admin_user', False)
        or getattr(request.user, 'role', None) == 'ADMIN'
    )
    is_locked = (order.warehouse_state == Order.WarehouseState.LOCKED)

    if request.method == 'POST':
        action = request.POST.get('action', 'save_draft')

        if action == 'unlock':
            if not is_admin:
                messages.error(request, 'רק מנהל מערכת רשאי לבטל נעילה של תעודת ליקוט.')
                return redirect('production:order-warehouse-setup', pk=pk)

            old_ver = order.warehouse_version
            order.warehouse_state = Order.WarehouseState.DRAFT
            order.warehouse_version = old_ver + 1
            order.warehouse_locked_at = None
            order.warehouse_locked_by = None
            order.save(update_fields=[
                'warehouse_state', 'warehouse_version', 'warehouse_locked_at', 'warehouse_locked_by'
            ])

            OrderChangeLog.objects.create(
                order=order,
                user=request.user,
                field_name='warehouse_state',
                old_value=f'LOCKED (גרסה {old_ver})',
                new_value=f'UNLOCKED -> גרסה {order.warehouse_version}',
            )
            messages.warning(request, f'הנעילה בוטלה. נפתחה גרסה {order.warehouse_version} לעריכה.')
            return redirect('production:order-warehouse-setup', pk=pk)

        if is_locked:
            messages.error(request, 'התעודה נעולה לעריכה.')
            return redirect('production:order-warehouse-setup', pk=pk)

        if action == 'recalculate':
            order.warehouse_notes = request.POST.get('warehouse_notes', '').strip()
            order.save(update_fields=['warehouse_notes'])
            WarehousePackingSlipService.recalculate(order)
            messages.info(request, 'הרשימה חושבה מחדש מתוך ההזמנה.')
            return redirect('production:order-warehouse-setup', pk=pk)

        with transaction.atomic():
            order.warehouse_notes = request.POST.get('warehouse_notes', '').strip()
            order.save(update_fields=['warehouse_notes'])

            validation_errors = []

            for item in order.warehouse_items.all():
                if request.POST.get(f'delete_{item.id}') == '1':
                    item.delete()
                    continue

                qty_raw = request.POST.get(f'qty_{item.id}')
                if qty_raw is not None:
                    try:
                        item.quantity = max(0, float(qty_raw))
                    except ValueError:
                        pass

                item.comment = request.POST.get(f'comment_{item.id}', '').strip()

                if item.is_color_required:
                    hw_id_raw = request.POST.get(f'hw_color_{item.id}')
                    if hw_id_raw and hw_id_raw.isdigit():
                        chosen_hw = Hardware.objects.filter(pk=int(hw_id_raw)).select_related('color').first()
                        if chosen_hw:
                            item.hardware = chosen_hw
                            item.name = chosen_hw.name
                            item.sku = chosen_hw.sku or ''
                            item.color_name = chosen_hw.color.name if chosen_hw.color else ''
                    else:
                        item.hardware = None
                        item.sku = ''
                        item.color_name = ''
                        if action == 'approve_and_print':
                            validation_errors.append(f"חובה לבחור גוון עבור: {item.common_name or item.name}")

                item.save()

            new_name = request.POST.get('new_item_name', '').strip()
            if new_name:
                new_cat = request.POST.get('new_item_category') or OrderWarehouseItem.Category.OTHER
                new_sku = request.POST.get('new_item_sku', '').strip()
                new_color = request.POST.get('new_item_color', '').strip()
                new_comment = request.POST.get('new_item_comment', '').strip()
                try:
                    new_qty = float(request.POST.get('new_item_qty') or 1)
                except ValueError:
                    new_qty = 1

                OrderWarehouseItem.objects.create(
                    order=order,
                    category=new_cat,
                    name=new_name,
                    sku=new_sku,
                    color_name=new_color,
                    quantity=new_qty,
                    comment=new_comment,
                )

            if validation_errors:
                for err in validation_errors:
                    messages.error(request, err)
                return redirect('production:order-warehouse-setup', pk=pk)

            if action == 'approve_and_print':
                order.warehouse_state = Order.WarehouseState.LOCKED
                order.warehouse_locked_at = timezone.now()
                order.warehouse_locked_by = request.user
                order.save(update_fields=['warehouse_state', 'warehouse_locked_at', 'warehouse_locked_by'])

                OrderChangeLog.objects.create(
                    order=order,
                    user=request.user,
                    field_name='warehouse_state',
                    old_value='DRAFT',
                    new_value=f'APPROVED & LOCKED (גרסה {order.warehouse_version})',
                )

        if action == 'approve_and_print':
            return redirect(f"{reverse('production:station-report', kwargs={'pk': pk})}?station=WAREHOUSE")

        messages.success(request, 'הטיוטה נשמרה בהצלחה.')
        return redirect('production:order-warehouse-setup', pk=pk)

    sections, available_colors = WarehousePackingSlipService.get_grouped_items_for_ui(order)

    return render(request, 'production/order_warehouse_setup.html', {
        'order': order,
        'sections': sections,
        'available_colors': available_colors,
        'is_locked': is_locked,
        'is_admin': is_admin,
        'categories': OrderWarehouseItem.Category.choices,
    })


@login_required
def station_backlog_sheet_print(request, station_code):
    """Печатный лист-бегунок очереди заказов на станции."""
    station = get_object_or_404(ProductionStation, code__iexact=station_code)
    backlog = StationTrackingService.get_station_order_backlog(station.code)

    return render(request, 'production/reports/station_backlog_sheet.html', {
        'station': station,
        'backlog': backlog,
        'today': timezone.now(),
    })


@login_required
def station_control_view(request, station_code):
    """Экранная форма менеджера для отметки заказов с листа."""
    station = get_object_or_404(ProductionStation, code__iexact=station_code)

    if request.method == 'POST':
        selected_orders = request.POST.getlist('selected_orders')
        updated_count = 0

        for order_no in selected_orders:
            success, _, _ = StationTrackingService._complete_batch_station(
                order_number=order_no,
                station_code=station.code,
                batch_number=None,
                user=request.user,
                source=StationProgressSource.MANUAL,
            )
            if success:
                updated_count += 1

        if updated_count:
            messages.success(request, f"עודכנו {updated_count} הזמנות בתחנת {station.name}.")
        else:
            messages.info(request, "לא בוצעו שינויים.")

        return redirect('production:station-control', station_code=station.code)

    backlog = StationTrackingService.get_station_order_backlog(station.code)

    return render(request, 'production/tracking/station_control_form.html', {
        'station': station,
        'backlog': backlog,
        'today': timezone.now(),
    })


class StationTrackingDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'production/tracking_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stations = ProductionStation.objects.filter(active=True).order_by('order', 'id')

        selected_code = self.request.GET.get('station')
        selected_station = None
        if selected_code:
            selected_station = stations.filter(code__iexact=selected_code).first()
        if not selected_station and stations.exists():
            selected_station = stations.first()

        stations_data = []
        for st in stations:
            backlog = StationTrackingService.get_station_batch_summary(st.code)
            stations_data.append({
                'station': st,
                'pending_orders_count': len(backlog),
            })

        active_backlog = []
        if selected_station:
            active_backlog = StationTrackingService.get_station_batch_summary(selected_station.code)

        context.update({
            'stations_data': stations_data,
            'selected_station': selected_station,
            'backlog': active_backlog,
        })
        return context

    def post(self, request, *args, **kwargs):
        station_code = request.POST.get('station_code')
        selected_items = request.POST.getlist('completed_batches')

        if selected_items and station_code:
            to_process = []
            for item_str in selected_items:
                parts = item_str.split(':')
                if len(parts) == 2:
                    o_num, b_num = parts[0], parts[1]
                    to_process.append({
                        'order_number': o_num,
                        'batch_number': int(b_num) if b_num.isdigit() else 1,
                        'station_code': station_code,
                    })

            if to_process:
                total_doors = StationTrackingService.complete_multiple_batches(
                    items_to_complete=to_process,
                    user=request.user,
                    source='DASHBOARD_BATCH_SUBMIT',
                )
                messages.success(
                    request,
                    f"עודכנו בהצלחה {len(to_process)} הזמנות/מנות (סה\"כ {total_doors} דלתות) בתחנה זו.",
                )

        next_station = (
                request.POST.get("next_station")
                or request.GET.get("station")
                or station_code
        )
        return redirect(f"{request.path}?station={next_station}")


class ToggleBatchStationAjaxView(LoginRequiredMixin, View):
    """
    AJAX-обработчик для закрытия/отметки порции дверей конкретного заказа на станке.
    """

    def post(self, request, *args, **kwargs):
        order_number = request.POST.get('order_number')
        station_code = request.POST.get('station_code')
        batch_number = request.POST.get('batch_number')

        if not order_number or not station_code:
            return JsonResponse({'success': False, 'message': 'Missing parameters'}, status=400)

        batch_num = int(batch_number) if batch_number and str(batch_number).isdigit() else None

        success, msg, payload = StationTrackingService._complete_batch_station(
            order_number=order_number,
            station_code=station_code,
            batch_number=batch_num,
            user=request.user,
            source='DASHBOARD_UI',
        )

        return JsonResponse({
            'success': success,
            'message': msg,
            'completed_count': payload.get('completed_count', 0) if success else 0,
        })


class StationsBatchDailyPrintView(LoginRequiredMixin, TemplateView):
    """
    Формирует единый документ для печати списков по всем активным участкам.
    При передаче ?station=<code> печатается только указанный участок.
    Пустые станции автоматически пропускаются.
    """
    template_name = 'production/reports/daily_stations_sheets.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stations = ProductionStation.objects.filter(active=True).order_by('order', 'id')

        station_code = self.request.GET.get('station')
        if station_code:
            stations = stations.filter(code__iexact=station_code)

        printable_sheets = []
        for st in stations:
            backlog = StationTrackingService.get_station_batch_summary(st.code)
            if not backlog:
                continue

            printable_sheets.append({
                'station': st,
                'backlog': backlog,
                'total_orders': len(backlog),
                'total_doors': sum(item.get('doors_count', 0) for item in backlog),
            })

        context['sheets'] = printable_sheets
        return context


@login_required
@require_POST
def save_station_note(request, order_id):
    order = get_object_or_404(Order, pk=order_id)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        payload = request.POST

    station_id = payload.get('station_id')
    comment = (payload.get('comment') or '').strip()
    station = get_object_or_404(ProductionStation, pk=station_id)

    if comment:
        note, _ = OrderStationNote.objects.update_or_create(
            order=order,
            station=station,
            defaults={
                'comment': comment,
                'updated_by': request.user,
            },
        )
        saved_comment = note.comment
    else:
        OrderStationNote.objects.filter(order=order, station=station).delete()
        saved_comment = ''

    return JsonResponse({
        'status': 'ok',
        'station_id': station.id,
        'comment': saved_comment,
    })


def _build_station_report_context(order, station, station_code, spec_obj, service, requested_batches, stage_label,
                                  is_master=False):
    """Общий хелпер подготовки ReportContext для одной станции (автономно или в Master Print)."""
    from apps.production.reports import ReportContext

    filtered_db_items = (
        service.get_filtered_items(station=station)
        if station
        else service.get_filtered_items(report_type=station_code)
    )
    filtered_item_ids = {item.id for item in filtered_db_items}

    if spec_obj is not None:
        res = ProductionDataService.extract_report_items(spec_obj, requested_batches)
        report_items, batches_label = (res[0], res[1]) if res[0] is not None else ([], "לא נבחרה אצווה")
        station_items = [
            it for it in report_items
            if (getattr(it, 'item_id', None) if hasattr(it, 'item_id') else it.get('item_id')) in filtered_item_ids
        ]
    else:
        station_items, batches_label = [], ""

    code_for_qr = station.code if station else (station_code or order.status)
    barcode_data = f"{order.order_number};{code_for_qr}"

    return ReportContext(
        order=order,
        order_spec=spec_obj,
        station=station,
        station_code=station_code or '',
        station_items=station_items,
        filtered_db_items=filtered_db_items,
        batches_label=batches_label,
        stage_label=stage_label,
        station_comment=get_station_comment(order, station),
        order_qr=get_qr_base64(barcode_data),
        barcode_text=barcode_data,
        requested_batches=requested_batches,
        is_master=is_master,
    )


def _resolve_stage_label(order) -> str:
    """Возвращает текстовую метку этапа производства для шапки отчёта."""
    if order.status == OrderStatus.PHASE1_PRODUCTION:
        return "שלב א'"
    if order.status in (OrderStatus.PHASE2_PRODUCTION, OrderStatus.PHASE1_READY):
        return "שלב ב'"
    return "קומפלט"


@login_required
def station_report(request, pk):
    """
    Единая точка входа для всех печатных HTML-отчётов станций.
    Поддерживает индивидуальный отчёт (?station=<CODE>) и сводный Master Print (?station=ALL).
    Логика подготовки данных и выбор шаблона делегируются зарегистрированному ReportRegistry.
    """
    from apps.production.reports import ReportRegistry

    order = get_object_or_404(Order, pk=pk)
    station_code = request.GET.get('station') or request.GET.get('type') or 'ALL'
    requested_batches = request.GET.getlist('batch')
    stage_label = _resolve_stage_label(order)
    service = ProductionDataService(order)

    # 1. Master Print Mode (все активные станции заказа в одном документе)
    if station_code.upper() in ('ALL', 'IN_PRODUCTION', 'FULL', 'FULL_PRODUCTION'):
        stations = order.get_production_stations()
        if not stations:
            stations = list(
                ProductionStation.objects.exclude(
                    specification_type=ProductionStation.SpecType.NONE
                ).filter(active=True)
            )

        sections = []
        for station in stations:
            phase = 'phase1' if station.is_phase1 else 'phase2'
            try:
                val_res = OrderValidationService.validate_for_report(order, station=station)
                val_res.raise_if_invalid()
                spec_obj, _ = TechnicalSpecService.get_or_build_spec(order, phase=phase)
            except Exception as e:
                errors = getattr(e, 'errors', [str(e)])
                return render(request, 'production/report_validation_error.html', {
                    'order': order,
                    'errors': errors,
                    'validation_errors': errors,
                    'validation_type': 'PARTIAL' if phase == 'phase1' else 'FULL',
                    'phase': phase,
                    'report_label': station.label or station.name or "דוחות ייצור",
                })

            ctx = _build_station_report_context(
                order, station, station.code, spec_obj, service, requested_batches, stage_label, is_master=True
            )
            if ctx.station_items or not order.groups.exists():
                handler = ReportRegistry.resolve_for_station(station=station, station_code=station.code)
                sections.append(handler.build_master_section(ctx))

        return render(request, 'production/reports/master_report.html', {
            'order': order,
            'sections': sections,
            'stage_label': stage_label,
            'now': timezone.now(),
        })

    # 2. Individual Station Report Mode
    station = ProductionStation.objects.filter(code__iexact=station_code).first()
    if not station:
        if station_code.upper() == 'PHASE1_FRAMES':
            station = ProductionStation.objects.filter(is_phase1=True).first()
        elif station_code.upper() == 'PHASE2_DOORS':
            station = ProductionStation.objects.filter(code__in=['DOORS', 'PRESS']).first()

    handler = ReportRegistry.resolve_for_station(station=station, station_code=station_code)
    phase = 'phase1' if (station and station.is_phase1) or station_code.upper() == 'PHASE1_FRAMES' else 'phase2'

    spec_obj = None
    if handler.requires_spec:
        try:
            val_res = OrderValidationService.validate_for_report(order, report_type=station_code, station=station)
            val_res.raise_if_invalid()
            spec_obj, _ = TechnicalSpecService.get_or_build_spec(order, phase=phase)
        except Exception as e:
            errors = getattr(e, 'errors', [str(e)])
            return render(request, 'production/report_validation_error.html', {
                'order': order,
                'errors': errors,
                'validation_errors': errors,
                'validation_type': 'PARTIAL' if phase == 'phase1' else 'FULL',
                'phase': phase,
                'report_label': (station.label if station else station_code) or "דוח ייצור",
            })

    ctx = _build_station_report_context(
        order, station, station_code, spec_obj, service, requested_batches, stage_label, is_master=False
    )
    return render(request, handler.resolve_template_name(ctx), handler.build_context(ctx))


def _render_named_report(request, pk: int, default_code: str, fallback_codes: tuple[str, ...]):
    """Тонкая обёртка для сохранения обратной совместимости именных URL (press, wood_frames, facing)."""
    from apps.production.reports import ReportRegistry

    order = get_object_or_404(Order, pk=pk)
    station = ProductionStation.objects.filter(code__in=fallback_codes).first()
    handler = ReportRegistry.resolve_for_station(station=station, station_code=default_code)
    spec_obj, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase2')
    service = ProductionDataService(order)

    ctx = _build_station_report_context(
        order=order,
        station=station,
        station_code=default_code,
        spec_obj=spec_obj,
        service=service,
        requested_batches=request.GET.getlist('batch'),
        stage_label=_resolve_stage_label(order),
        is_master=False,
    )
    return render(request, handler.resolve_template_name(ctx), handler.build_context(ctx))


@login_required
def report_cutting_press(request, pk):
    """Автономный отчёт участка пресса (делегирует в PressStationReport)."""
    return _render_named_report(request, pk, 'PRESS', ('PRESS', 'CUTTING_PRESS'))


@login_required
def report_wood_frames(request, pk):
    """Автономный отчёт деревянных коробок (делегирует в WoodFramesStationReport)."""
    return _render_named_report(request, pk, 'WOOD_FRAMES', ('FRAMES', 'WOOD_FRAMES', 'WOODEN_FRAMES'))


@login_required
def report_facing(request, pk):
    """Автономный отчёт облицовок с эскизами (делегирует в FacingStationReport)."""
    return _render_named_report(request, pk, 'FACING', ('FACING', 'CLADDING', 'FACING_REPORT'))


@login_required
def order_tracking_list(request):
    """
    Страница поиска заказа в производстве + список активных заказов с фильтром аномалий.
    """
    from .order_tracking_service import OrderTrackingService

    query = request.GET.get('q', '').strip()
    only_anomalies = request.GET.get('anomalies') == '1'

    orders_overview = OrderTrackingService.get_active_orders_overview(
        query=query,
        only_anomalies=only_anomalies,
        limit=60,
    )

    if query and len(orders_overview) == 1 and str(orders_overview[0]['order'].order_number) == query:
        return redirect('production:order-tracking-detail', pk=orders_overview[0]['order'].pk)

    return render(request, 'production/order_tracking_list.html', {
        'query': query,
        'only_anomalies': only_anomalies,
        'orders_overview': orders_overview,
    })


@login_required
def order_tracking_search_ajax(request):
    """
    JSON-эндпоинт живого поиска заказа (для автокомплита в трекере станций и на странице трекинга заказа).
    """
    from .order_tracking_service import OrderTrackingService

    q = request.GET.get('q', '').strip()
    if len(q) < 1:
        return JsonResponse({'results': []})

    matches = OrderTrackingService.get_active_orders_overview(query=q, limit=10)
    payload = [
        {
            'id': m['order'].id,
            'order_number': str(m['order'].order_number),
            'customer': m['order'].customer or '',
            'progress_pct': m['progress_pct'],
            'batches_count': m['batches_count'],
            'has_anomaly': m['has_anomaly'],
            'bypassed_count': m['bypassed_count'],
            'url': reverse('production:order-tracking-detail', kwargs={'pk': m['order'].id}),
        }
        for m in matches
    ]
    return JsonResponse({'results': payload})


@login_required
def order_tracking_detail(request, pk):
    """
    Отдельная страница детального отслеживания и ручного управления маршрутом заказа и его батчей.
    """
    from .order_tracking_service import OrderTrackingService

    order = get_object_or_404(Order, pk=pk)
    batch_param = request.GET.get('batch')
    selected_batch = int(batch_param) if batch_param and batch_param.isdigit() else None

    ctx = OrderTrackingService.get_order_tracking_context(order, selected_batch=selected_batch)
    return render(request, 'production/order_tracking_detail.html', ctx)


@login_required
@require_POST
def order_tracking_station_action(request, pk):
    """
    Обработчик ручных действий диспетчера по станции батча или отдельной двери.
    """
    from .order_tracking_service import OrderTrackingService

    order = get_object_or_404(Order, pk=pk)
    action = request.POST.get('action', '').strip()
    batch_raw = request.POST.get('batch_number', '1')
    batch_number = int(batch_raw) if str(batch_raw).isdigit() else 1
    station_code = request.POST.get('station_code')
    progress_raw = request.POST.get('progress_id')
    progress_id = int(progress_raw) if progress_raw and str(progress_raw).isdigit() else None

    ok, msg = OrderTrackingService.apply_station_action(
        order=order,
        batch_number=batch_number,
        action=action,
        user=request.user,
        station_code=station_code,
        progress_id=progress_id,
    )

    if ok:
        messages.success(request, msg)
    else:
        messages.warning(request, msg)

    return redirect(f"{reverse('production:order-tracking-detail', kwargs={'pk': order.pk})}?batch={batch_number}")
