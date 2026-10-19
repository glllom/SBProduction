import base64
import csv
import json
from datetime import date
from io import BytesIO

import qrcode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from qrcode.image.svg import SvgPathImage

from apps.catalog.models import Hardware
from apps.orders.models import (
    Order, OrderChangeLog, OrderItem, OrderItemsGroup, OrderStatus, OrderComponentSelection
)
from .label_services import DoorLabelService
from .models import DoorLabel, ProductionStation, SvgPattern
from .services import (
    OrderProductionService,
    OrderValidationService,
    ProductionDataService,
    OrderValidationError,
    TechnicalSpecService,
)
from .usb_sync import run_usb_sync


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


def enrich_report_doors_spec(items):
    """
    Размечает элементы для вывода в таблице дверей:
    1. Помечает элементы сменившейся фурнитуры (show_hardware_subhead).
    2. Вычисляет addons_rowspan для одинаковых идущих подряд кастомизаторов/комментариев.
    """

    def get_addons_signature(item_dict):
        cmz = item_dict.get('doors_report_customizers', []) or []
        comment = item_dict.get('comment', '') or ''
        return json.dumps({
            'c': str(comment),
            'cmz': cmz
        }, sort_keys=True, default=str)

    items_data = [
        item.model_dump() if hasattr(item, 'model_dump') else (item if isinstance(item, dict) else item.dict())
        for item in items
    ]
    n = len(items_data)

    current_key = None
    for item in items_data:
        group_key = (item.get('product_family'), item.get('series'))
        hw_key = (item.get('lock_name'), item.get('hinge_name'))

        if current_key is None or current_key[0] != group_key or current_key[1] != hw_key:
            item['show_hardware_subhead'] = True
            current_key = (group_key, hw_key)
        else:
            item['show_hardware_subhead'] = False

    i = 0
    while i < n:
        sig = get_addons_signature(items_data[i])
        curr_group = (items_data[i].get('product_family'), items_data[i].get('series'))
        curr_hw = (items_data[i].get('lock_name'), items_data[i].get('hinge_name'))

        run_len = 1
        while i + run_len < n:
            next_group = (items_data[i + run_len].get('product_family'), items_data[i + run_len].get('series'))
            next_hw = (items_data[i + run_len].get('lock_name'), items_data[i + run_len].get('hinge_name'))

            if (next_group != curr_group or
                    next_hw != curr_hw or
                    get_addons_signature(items_data[i + run_len]) != sig):
                break
            run_len += 1

        items_data[i]['addons_rowspan'] = run_len
        for j in range(1, run_len):
            items_data[i + j]['addons_rowspan'] = 0

        i += run_len

    return items_data


def enrich_report_frames_spec(items):
    """
    Размечает элементы для вывода в таблице коробок:
    1. Помечает элементы сменившейся фурнитуры (show_hardware_subhead) внутри группы профиля.
    2. Вычисляет addons_rowspan для одинаковых идущих подряд кастомизаторов/комментариев с учетом FRAMES_REPORT.
    """

    def get_addons_signature(item_dict):
        cmz = item_dict.get('frames_report_customizers', []) or []
        comment = item_dict.get('comment', '') or ''
        return json.dumps({
            'c': str(comment),
            'cmz': cmz
        }, sort_keys=True, default=str)

    items_data = [
        item.model_dump() if hasattr(item, 'model_dump') else (item if isinstance(item, dict) else item.dict())
        for item in items
    ]
    n = len(items_data)

    current_key = None
    for item in items_data:
        group_key = (item.get('product_family'), item.get('series'), item.get('frame'))
        hw_key = (item.get('lock_name'), item.get('hinge_name'))

        if current_key is None or current_key[0] != group_key or current_key[1] != hw_key:
            item['show_hardware_subhead'] = True
            current_key = (group_key, hw_key)
        else:
            item['show_hardware_subhead'] = False

    i = 0
    while i < n:
        sig = get_addons_signature(items_data[i])
        curr_group = (items_data[i].get('product_family'), items_data[i].get('series'), items_data[i].get('frame'))
        curr_hw = (items_data[i].get('lock_name'), items_data[i].get('hinge_name'))

        run_len = 1
        while i + run_len < n:
            next_group = (items_data[i + run_len].get('product_family'), items_data[i + run_len].get('series'),
                          items_data[i + run_len].get('frame'))
            next_hw = (items_data[i + run_len].get('lock_name'), items_data[i + run_len].get('hinge_name'))

            if (next_group != curr_group or
                    next_hw != curr_hw or
                    get_addons_signature(items_data[i + run_len]) != sig):
                break
            run_len += 1

        items_data[i]['addons_rowspan'] = run_len
        for j in range(1, run_len):
            items_data[i + j]['addons_rowspan'] = 0

        i += run_len

    return items_data


def get_qr_base64(data: str) -> str:
    """Генерирует QR-код в формате Base64 SVG."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)

    buffer = BytesIO()
    img = qr.make_image(image_factory=SvgPathImage)
    img.save(buffer)

    return base64.b64encode(buffer.getvalue()).decode('utf-8')


# === 1. Production Lifecycle & Status Actions ===

@login_required
def order_transfer_to_production(request, pk):
    """
    Unified entry point for production launch:
    - From PHASE1_READY (GET): displays measurement entry form with gross heights.
    - From PHASE1_READY (POST): converts input gross heights to net values, saves and starts Phase 2.
    - From NEW / reorder: immediately launches production in 1-click.
    """
    order = get_object_or_404(Order, pk=pk)

    if order.status == OrderStatus.PHASE1_READY:
        if order.status == OrderStatus.PHASE1_READY:
            if request.method == 'POST':
                with transaction.atomic():
                    # 1. Сохраняем правки по существующим позициям из формы
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

                    for item_id, order_item in items_by_id.items():
                        modified = False
                        mark = order_item.mark or str(item_id)

                        top_clearance = 0.3
                        if order_item.group and order_item.group.product and order_item.group.product.product_family:
                            raw_cl = order_item.group.product.product_family.leaf_top_clearance
                            if raw_cl is not None:
                                top_clearance = abs(float(raw_cl))

                        for field in ['height', 'width', 'wall']:
                            key = f"item_{item_id}_{field}"
                            if key in request.POST:
                                try:
                                    val = request.POST.get(key)
                                    new_val = float(val) if val else None
                                    old_val = float(getattr(order_item, field)) if getattr(order_item, field) else None
                                    if new_val != old_val:
                                        setattr(order_item, field, new_val)
                                        modified = True
                                        change_logs.append(OrderChangeLog(
                                            order=order,
                                            user=request.user,
                                            field_name=f"Item {mark} {field.capitalize()}",
                                            old_value=str(old_val) if old_val is not None else "None",
                                            new_value=str(new_val) if new_val is not None else "None"
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
                                        new_value=str(new_lh) if new_lh is not None else "None"
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
                                    old_hh = float(getattr(order_item, field_name)) if getattr(order_item,
                                                                                               field_name) else None
                                    if new_hh != old_hh:
                                        setattr(order_item, field_name, new_hh)
                                        modified = True
                                        change_logs.append(OrderChangeLog(
                                            order=order,
                                            user=request.user,
                                            field_name=f"Item {mark} Hinge {i}",
                                            old_value=str(old_hh) if old_hh is not None else "None",
                                            new_value=str(new_hh) if new_hh is not None else "None"
                                        ))
                                except (ValueError, TypeError):
                                    pass

                        if modified:
                            order_item.save()

                    if change_logs:
                        OrderChangeLog.objects.bulk_create(change_logs)

                    # 2. Обрабатываем новые группы (если менеджер добавил их в статус NEW перед переходом)
                    new_groups = order.groups.filter(production_state=OrderItemsGroup.ProductionState.NEW)
                    if new_groups.exists():
                        released_batch = order.current_batch
                        new_groups.update(
                            batch_number=released_batch,
                            production_state=OrderItemsGroup.ProductionState.IN_PRODUCTION,
                            batch_date=date.today(),
                        )
                        order.current_batch = released_batch + 1
                        order.save(update_fields=['current_batch'])

                    # 3. Переводим заказ в статус PHASE2_PRODUCTION и перестраиваем кэш спецификации Фазы 2
                    order.status = OrderStatus.PHASE2_PRODUCTION
                    order.save(update_fields=['status'])

                    TechnicalSpecService.get_or_build_spec(
                        order, phase='phase2', force_rebuild=True, user=request.user
                    )

                messages.success(request, "ההזמנה הועברה לשלב ב' בהצלחה.")
                return redirect('order-detail', pk=pk)

        # --- GET-запрос: формируем список позиций для формы перевода во вторую фазу ---
        try:
            order_spec, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase1')

            # Собираем все активные батчи первой фазы (точно так же, как в דוח מדידה)
            valid_groups = order.groups.filter(
                is_split_installation=True,
                batch_number__isnull=False
            ).exclude(
                production_state=OrderItemsGroup.ProductionState.CANCELED
            )
            requested_batches = list(valid_groups.values_list('batch_number', flat=True).distinct())

            # Извлекаем плоский отсортированный список позиций
            raw_items, _ = ProductionDataService.extract_report_items(
                order_spec,
                requested_batches=requested_batches
            )
            raw_items = raw_items if raw_items is not None else []

        except Exception:
            raw_items = []

        items_data = []

        for item in raw_items:
            # Превращаем объект/словарь в словарь для удобства шаблона
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
                gross_hinges = [round(float(h) + top_clearance, 2) for h in item_copy['hinge_heights'] if
                                h is not None]

            item_copy['padded_hinges'] = (list(gross_hinges) + [None] * 5)[:5]
            items_data.append(item_copy)

        return render(request, 'production/transfer_to_phase2_form.html', {
            'order': order,
            'items_data': items_data,
        })

    try:
        OrderProductionService.start_production(order, user=request.user)

        is_ajax = (
                request.headers.get('x-requested-with') == 'XMLHttpRequest' or
                'application/json' in request.headers.get('Accept', '')
        )
        if is_ajax:
            released_batch = order.current_batch - 1
            master_url = f"{reverse('production:station-report', kwargs={'pk': pk})}?station=ALL&batch={released_batch}"
            return JsonResponse({
                'status': 'ok',
                'message': 'The order was successfully transferred to production.',
                'master_report_url': master_url
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
def group_toggle_state(request, pk, group_id):
    """Toggles or sets the production state of an OrderItemsGroup."""
    order = get_object_or_404(Order, pk=pk)
    group = get_object_or_404(order.groups, pk=group_id)
    new_state = request.POST.get('state') or request.GET.get('state')

    if new_state in [OrderItemsGroup.ProductionState.WAITING, OrderItemsGroup.ProductionState.IN_PRODUCTION,
                     OrderItemsGroup.ProductionState.COMPLETED]:
        old_state = group.production_state
        group.production_state = new_state
        group.save(update_fields=['production_state'])
        messages.success(request, f"סטטוס קבוצה #{group.id} עודכן ל-{group.get_production_state_display()}.")
        OrderChangeLog.objects.create(
            order=order,
            user=request.user,
            field_name=f"Group #{group.id} production_state",
            old_value=old_state,
            new_value=new_state
        )
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

    try:
        spec_obj, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase1')
    except Exception as e:
        messages.error(request, f"Error building spec: {str(e)}")
        return redirect('order-detail', pk=pk)

    # Получаем элементы из структуры batches
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
                            new_value=str(new_val) if new_val is not None else "None"
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
                            new_value=str(new_h) if new_h is not None else "None"
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
    except ValueError as e:
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
        messages.error(request, f"Production data generation failed: {str(e)}")
        return redirect('order-detail', pk=pk)


@login_required
def station_report(request, pk):
    """
    Single entry point for all station HTML reports.
    Supports individual station reports (e.g. ?station=FRAMES) and master print (?station=ALL).
    Uses 'batch' URL parameters to filter by production batch.
    """
    order = get_object_or_404(Order, pk=pk)
    station_code = request.GET.get('station') or request.GET.get('type')
    requested_batches = request.GET.getlist('batch')

    # 1. Спец-отчет по прессу (нарезка панелей)
    if station_code and station_code.upper() in ['PRESS', 'CUTTING_PRESS']:
        return report_cutting_press(request, pk)

    # 2. Спец-отчет по облицовке (חיפוי)
    if station_code and station_code.upper() in ['FACING', 'CLADDING', 'FACING_REPORT']:
        return report_facing(request, pk)

    if not station_code:
        station_code = 'ALL'

    # Определение метки этапа заказа
    if order.status in [OrderStatus.PHASE1_PRODUCTION]:
        stage_label = "שלב א'"
    elif order.status in [OrderStatus.PHASE2_PRODUCTION, OrderStatus.PHASE1_READY]:
        stage_label = "שלב ב'"
    else:
        stage_label = "קומפלט"

    service = ProductionDataService(order)
    barcode_data = f"{order.order_number};{order.status}"

    # ==========================================
    # Master Print Mode (ALL stations)
    # ==========================================
    if station_code.upper() in ['ALL', 'IN_PRODUCTION', 'FULL', 'FULL_PRODUCTION']:
        stations = order.get_production_stations()
        if not stations:
            stations = list(ProductionStation.objects.filter(has_specification=True, active=True))

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
                    'report_label': station.label or station.name or "דוחות ייצור"
                })

            # СИСТЕМНАЯ ФИЛЬТРАЦИЯ ПО СТАНЦИЯМ
            filtered_items = service.get_filtered_items(station=station)
            filtered_item_ids = {item.id for item in filtered_items}

            res = ProductionDataService.extract_report_items(spec_obj, requested_batches)
            if res[0] is None:
                report_items = []
                batches_label = "לא נבחרה אצווה"
            else:
                report_items, batches_label = res

            station_items = [
                it for it in report_items
                if (getattr(it, 'item_id', None) if hasattr(it, 'item_id') else it.get('item_id')) in filtered_item_ids
            ]

            if station_items or not order.groups.exists():
                include_template = None
                code_lower = station.code.lower() if station.code else ''

                # Подбор шаблона секции для Мастер-отчета
                if code_lower in ['frames', 'alum_frames']:
                    include_template = 'production/includes/report_alum_frames.html'
                elif code_lower in ['doors', 'alum_doors']:
                    include_template = 'production/includes/report_alum_doors.html'
                elif code_lower in ['cut_sheets', 'sheets']:
                    include_template = 'production/includes/report_cut_sheets.html'

                # --- ПОДДЕРЖКА ОБЛИЦОВКИ В МАСТЕР-ОТЧЕТЕ ---
                elif code_lower in ['facing', 'cladding', 'facing_report']:
                    include_template = 'production/includes/report_facing.html'

                    # Подтягиваем URL картинок из БД для словарей снапшота
                    item_ids = [it.get('item_id') if isinstance(it, dict) else getattr(it, 'item_id') for it in
                                station_items]
                    db_items = OrderItem.objects.filter(id__in=item_ids)
                    img_map = {}
                    for db_it in db_items:
                        url = None
                        if getattr(db_it, 'sketch', None):
                            try:
                                url = db_it.sketch.url
                            except ValueError:
                                pass
                        elif getattr(db_it, 'sketch_url', None):
                            url = db_it.sketch_url
                        img_map[db_it.id] = url

                    for it in station_items:
                        it_id = it.get('item_id') if isinstance(it, dict) else getattr(it, 'item_id')
                        if isinstance(it, dict):
                            it['image_url'] = img_map.get(it_id)
                        else:
                            it.image_url = img_map.get(it_id)
                # -------------------------------------------

                elif station.template_name:
                    base_name = station.template_name.split('/')[-1].replace('_report.html', '')
                    include_template = f'production/includes/report_{base_name}.html'

                if not include_template:
                    include_template = 'production/includes/report_alum_frames.html'

                enriched_frames = enrich_report_frames_spec(station_items)
                enriched_doors = enrich_report_doors_spec(station_items)

                sections.append({
                    'station': station,
                    'station_code': station.code,
                    'report_label': station.label or station.name,
                    'batches_label': batches_label,
                    'order_spec': spec_obj,
                    'groups_data': service.prepare_grouped_data(station_items),
                    'enriched_frames_items': enriched_frames,
                    'enriched_doors_items': enriched_doors,
                    'include_template': include_template,
                })

        return render(request, 'production/reports/master_report.html', {
            'order': order,
            'sections': sections,
            'stage_label': stage_label,
            'now': timezone.now(),
        })

    # ==========================================
    # Individual Station Report Mode
    # ==========================================
    station = ProductionStation.objects.filter(code=station_code).first()
    if not station:
        if station_code == 'PHASE1_FRAMES':
            station = ProductionStation.objects.filter(is_phase1=True).first()
        elif station_code == 'PHASE2_DOORS':
            station = ProductionStation.objects.filter(code__in=['DOORS', 'PRESS']).first()

    phase = 'phase1' if (station and station.is_phase1) or station_code == 'PHASE1_FRAMES' else 'phase2'

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
            'report_label': (station.label if station else (station.name if station else station_code)) or "דוח ייצור"
        })

    # ПРОСЛОЙКА ОТЧЕТОВ
    res = ProductionDataService.extract_report_items(spec_obj, requested_batches)
    if res[0] is None:
        report_items = []
        batches_label = "לא נבחרה אצווה"
    else:
        report_items, batches_label = res

    is_wood_frames_station = (
            (station_code and station_code.upper() in ['FRAMES', 'WOOD_FRAMES', 'WOODEN_FRAMES']) or
            (station and 'report_wood_frames.html' in (station.template_name or ''))
    )

    if is_wood_frames_station:
        frame_groups = service.prepare_wood_frames_report_data(report_items)
        template_name = station.template_name if (
                station and station.template_name) else 'production/reports/report_wood_frames.html'
        report_label = (station.label if station else None) or 'דו"ח משקופי עץ'

        return render(request, template_name, {
            'order': order,
            'order_spec': spec_obj,
            'batches_label': batches_label,
            'frame_groups': frame_groups,
            'station': station,
            'report_label': report_label,
            'now': timezone.now(),
            'order_qr': get_qr_base64(barcode_data),
            'barcode_text': barcode_data,
        })

    if station_code and station_code.upper() in ['WAREHOUSE', 'HARDWARE', 'PICK_LIST']:
        hardware_summary = service.get_warehouse_hardware_summary(report_items)
        return render(request, 'production/reports/report_warehouse_hardware.html', {
            'order': order,
            'order_spec': spec_obj,
            'batches_label': batches_label,
            'hardware_summary': hardware_summary,
            'report_label': 'דוח ליקוט פירזול',
            'now': timezone.now(),
            'order_qr': get_qr_base64(barcode_data),
        })

    # СИСТЕМНАЯ ФИЛЬТРАЦИЯ ПО СТАНЦИЯМ ДЛЯ ОБЫЧНЫХ ОТЧЕТОВ
    if station:
        filtered_items = service.get_filtered_items(station=station)
        template_name = station.template_name
        report_label = station.label or station.name
    else:
        filtered_items = service.get_filtered_items(report_type=station_code)
        template_name = 'production/reports/alum_frames_report.html'
        report_label = station_code

    filtered_item_ids = {item.id for item in filtered_items}

    station_items = [
        it for it in report_items
        if (getattr(it, 'item_id', None) if hasattr(it, 'item_id') else it.get('item_id')) in filtered_item_ids
    ]

    enriched_doors_items = enrich_report_doors_spec(station_items)
    enriched_frames_items = enrich_report_frames_spec(station_items)

    return render(request, template_name, {
        'order': order,
        'order_spec': spec_obj,
        'spec_json': spec_obj.model_dump(by_alias=True) if hasattr(spec_obj, 'model_dump') else spec_obj,
        'station': station,
        'report_label': report_label,
        'batches_label': batches_label,
        'groups_data': service.prepare_grouped_data(station_items),
        'stage_label': stage_label,
        'now': timezone.now(),
        'enriched_doors_items': enriched_doors_items,
        'enriched_frames_items': enriched_frames_items,
        'order_qr': get_qr_base64(barcode_data),
        'barcode_text': barcode_data,
        'spec_items': station_items,
        'panel_groups': service.prepare_press_groups_data(station_items),
    })


@login_required
def report_cutting_press(request, pk):
    order = get_object_or_404(Order, pk=pk)
    order_spec, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase2')

    requested_batches = request.GET.getlist('batch')
    res = ProductionDataService.extract_report_items(order_spec, requested_batches)
    if res[0] is None:
        report_items = []
        batches_label = "לא נבחרה אצווה"
    else:
        report_items, batches_label = res

    service = ProductionDataService(order)

    # ==== СИСТЕМНАЯ ФИЛЬТРАЦИЯ: Исключаем облицовки из пресса ====
    station = ProductionStation.objects.filter(code__in=['PRESS', 'CUTTING_PRESS']).first()
    if station:
        filtered_items = service.get_filtered_items(station=station)
        valid_ids = {item.id for item in filtered_items}
        # Оставляем только те позиции, чей маршрут включает станцию Пресс
        report_items = [
            it for it in report_items
            if (it.get('item_id') if isinstance(it, dict) else getattr(it, 'item_id')) in valid_ids
        ]

    panel_groups = service.prepare_press_groups_data(report_items)

    return render(request, 'production/reports/report_press.html', {
        'order': order,
        'order_spec': order_spec,
        'batches_label': batches_label,
        'panel_groups': panel_groups,
        'svg_patterns': SvgPattern.objects.all(),
        'now': timezone.now(),
    })


@login_required
def export_door_labels_csv(request, pk):
    order = get_object_or_404(Order, pk=pk)

    phase = 'phase2' if (order.phase2_spec_cache or order.status != OrderStatus.PHASE1_PRODUCTION) else 'phase1'
    spec_obj, _ = TechnicalSpecService.get_or_build_spec(order, phase=phase)

    # ПРОСЛОЙКА ДЛЯ НАКЛЕЕК CSV
    requested_batches = request.GET.getlist('batch')
    res = ProductionDataService.extract_report_items(spec_obj, requested_batches)
    if res[0] is None:
        items_raw = []
    else:
        items_raw, _ = res

    # Возвращаем элементы в стандартные словари для CSV логики
    items = [
        it.model_dump() if hasattr(it, 'model_dump') else (it if isinstance(it, dict) else it.dict())
        for it in items_raw
    ]

    door_items = [it for it in items if it.get('has_door', True)]
    total_doors = len(door_items)

    hardware_ids = set()
    for it in door_items:
        if it.get('lock_id'):
            hardware_ids.add(it['lock_id'])
        for b in it.get('bom_items', []) or []:
            if str(b.get('tag', '')).lower() == 'hinge' and b.get('item_id'):
                hardware_ids.add(b['item_id'])

    hw_map = Hardware.objects.in_bulk(hardware_ids) if hardware_ids else {}

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="labels_{order.order_number}.csv"'

    writer = csv.writer(response)
    customer = getattr(order, 'customer', '') or ''

    for it in door_items:
        door_mark = it.get('number') or it.get('mark') or str(it.get('item_id', ''))
        direction = it.get('direction') or it.get('direction_code') or ''

        family_name = it.get('product_family') or ''
        series_name = it.get('series') or ''
        model_code = it.get('model') or ''

        panel_dims = it.get('panel_dimensions') or []
        first_panel = panel_dims[0] if panel_dims else {}
        panel_w = first_panel.get('width', '')
        panel_h = first_panel.get('height', '')

        lock_name = it.get('lock') or ''
        lock_id = it.get('lock_id')
        lock_sku = hw_map[lock_id].sku if lock_id in hw_map else ''
        lock_h = it.get("lock's height", '')

        hinge_name = it.get('hinges') or ''
        hinge_id = None
        for b in it.get('bom_items', []) or []:
            if str(b.get('tag', '')).lower() == 'hinge' and b.get('item_id'):
                hinge_id = b['item_id']
                break
        hinge_sku = hw_map[hinge_id].sku if hinge_id in hw_map else ''

        raw_hinges = it.get('hinges height') or []
        hinges = [(h if h is not None else '') for h in (list(raw_hinges) + [''] * 5)[:5]]

        base_data = [
            order.order_number,
            customer,
            door_mark,
            total_doors,
            family_name,
            series_name,
            model_code,
            direction,
            panel_w,
            panel_h,
            lock_name,
            lock_sku,
            lock_h,
            hinge_name,
            hinge_sku,
            hinges[0],
            hinges[1],
            hinges[2],
            hinges[3],
            hinges[4],
        ]

        writer.writerow(base_data + [1])
        writer.writerow(base_data + [2])

    return response


@login_required
def spec_json_preview(request, pk):
    """Direct inspection endpoint for the latest JSON specification snapshot."""
    order = get_object_or_404(Order, pk=pk)

    if order.phase2_spec_cache or order.status in [
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
        spec_obj, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase2', force_rebuild=True)
        DoorLabelService.generate_labels_for_order(order, spec_obj)
        messages.success(request, f"Spec for Order {order.order_number} was forcefully rebuilt.")
    except Exception as e:
        messages.error(request, f"Rebuild failed: {str(e)}")
        return redirect('order-detail', pk=pk)

    return redirect('production:spec-json-preview', pk=pk)


@login_required
def split_measurer_report(request, pk):
    """
    Report for the measurer before phase 2, specifically for split installations.
    Uses Phase 1 specification data across active batches.
    """
    order = get_object_or_404(Order, pk=pk)

    if not order.has_split_installation:
        messages.error(request, "This report is only available for split installations.")
        return redirect('order-detail', pk=pk)

    # Подхватываем список батчей (поддерживает ?batch=1&batch=2&batch=3)
    batch_params = request.GET.getlist('batch')
    requested_batches = [int(b) for b in batch_params if b.isdigit()] if batch_params else None

    try:
        # 1. Берем спецификацию первой фазы
        order_spec, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase1')

        # 2. Если батчи явно не переданы в GET, собираем все активные батчи первой фазы
        if not requested_batches:
            valid_groups = order.groups.filter(
                is_split_installation=True,
                batch_number__isnull=False
            ).exclude(
                production_state=OrderItemsGroup.ProductionState.CANCELED
            )
            requested_batches = list(valid_groups.values_list('batch_number', flat=True).distinct())

        # 3. Извлекаем позиции через нашу проверенную прослойку
        flat_items, batches_label = ProductionDataService.extract_report_items(
            order_spec,
            requested_batches=requested_batches
        )

        spec_items = flat_items if flat_items is not None else []

    except Exception as e:
        errors = getattr(e, 'errors', [str(e)])
        return render(request, 'production/report_validation_error.html', {
            'order': order,
            'errors': errors,
            'phase': 'phase1'
        })

    return render(request, 'production/reports/split_measurer_report.html', {
        'order': order,
        'order_spec': order_spec,
        'spec_items': spec_items,
        'batches_label': batches_label,
        'report_label': "דו''ח מדידה לאחר שלב א'",
        'now': timezone.now(),
    })


@login_required
def order_compare_snapshots(request, pk):
    """
    Compares Phase 1 and Phase 2 specification snapshots for administrators.
    Extracts item data directly from JSON batches structure.
    """
    order = get_object_or_404(Order, pk=pk)

    if not request.user.is_admin_user:
        messages.error(request, "Access denied. Admins only.")
        return redirect('order-detail', pk=pk)

    if order.status != OrderStatus.PHASE2_PRODUCTION:
        messages.error(request, "Comparison is only available for orders in Phase 2 Production.")
        return redirect('order-detail', pk=pk)

    if not order.phase1_spec_cache or not order.phase2_spec_cache:
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
        'color_panels': 'צבע כנפיים',
        'color_frames': 'צבע משקופים',
        'handle_name': 'ידית',
        'lock_name': 'מנעול',
        'hinge_name': 'צירים',
    }

    batches1 = order.phase1_spec_cache.get('batches', {}) if isinstance(order.phase1_spec_cache, dict) else {}
    batches2 = order.phase2_spec_cache.get('batches', {}) if isinstance(order.phase2_spec_cache, dict) else {}

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
            'changed': lh1 != lh2
        })

        hh1 = item1.get('hinge_heights', [])
        hh2 = item2.get('hinge_heights', [])
        changes.append({
            'label': 'גבהי צירים (Hinge Heights)',
            'old': ", ".join(map(str, hh1)) if hh1 else "-",
            'new': ", ".join(map(str, hh2)) if hh2 else "-",
            'changed': hh1 != hh2
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
                    'changed': True
                })

        comparison_results.append({
            'mark': item1.get('mark', f"Item {item_id}"),
            'changes': changes
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
            label_type=data.get('label_type')
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
def report_wood_frames(request, pk):
    order = get_object_or_404(Order, pk=pk)
    order_spec, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase2')

    service = ProductionDataService(order)
    frame_groups = service.prepare_wood_frames_report_data(order_spec)
    barcode_data = f"{order.order_number};FRAMES"

    return render(request, 'production/reports/report_wood_frames.html', {
        'order': order,
        'order_spec': order_spec,
        'batches': order_spec.batches,
        'frame_groups': frame_groups,
        'order_qr': get_qr_base64(barcode_data),
        'now': timezone.now(),
    })


@login_required
def order_warehouse_setup(request, pk):
    """Form for editing warehouse instructions and choosing color-specific hardware variants."""
    order = get_object_or_404(Order, pk=pk)
    phase = 'phase2' if (order.phase2_spec_cache or order.status != OrderStatus.PHASE1_PRODUCTION) else 'phase1'
    spec_obj, _ = TechnicalSpecService.get_or_build_spec(order, phase=phase)

    customizable_hardware = ProductionDataService.get_order_customizable_hardware(order, spec_obj)

    if request.method == 'POST':
        order.warehouse_notes = request.POST.get('warehouse_notes', '').strip()
        order.press_notes = request.POST.get('press_notes', '').strip()
        order.frames_notes = request.POST.get('frames_notes', '').strip()
        order.save(update_fields=['warehouse_notes', 'press_notes', 'frames_notes'])

        for item in customizable_hardware:
            field_name = f"comp_{item['common_name']}"
            chosen_val = request.POST.get(field_name)

            if chosen_val:
                try:
                    chosen_id = int(chosen_val)
                    OrderComponentSelection.objects.update_or_create(
                        order=order,
                        common_name=item['common_name'],
                        defaults={'selected_hardware_id': chosen_id}
                    )
                except (ValueError, TypeError):
                    pass
            else:
                OrderComponentSelection.objects.filter(
                    order=order,
                    common_name=item['common_name']
                ).delete()

        messages.success(request, 'הגדרות המחסן נשמרו בהצלחה.')

        if 'save_and_print' in request.POST:
            return redirect(f"{reverse('production:station-report', kwargs={'pk': pk})}?station=WAREHOUSE")

        return redirect('order-detail', pk=pk)

    return render(request, 'production/order_warehouse_setup.html', {
        'order': order,
        'customizable_hardware': customizable_hardware,
    })


# --- ДОБАВЛЯЕМ ВЕРХУ НОВУЮ ФУНКЦИЮ ДЛЯ ОТЧЕТА ОБЛИЦОВКИ ---
@login_required
def report_facing(request, pk):
    """Специализированный отчет для облицовок (חיפויים) с выводом эскиза на всю страницу."""
    order = get_object_or_404(Order, pk=pk)
    station = ProductionStation.objects.filter(code__in=['FACING', 'CLADDING', 'FACING_REPORT']).first()

    order_spec, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase2')
    requested_batches = request.GET.getlist('batch')
    res = ProductionDataService.extract_report_items(order_spec, requested_batches)
    report_items, batches_label = res if res[0] is not None else ([], "לא נבחרה אצווה")

    report_item_ids = {(it.get('item_id') if isinstance(it, dict) else getattr(it, 'item_id')) for it in report_items}

    service = ProductionDataService(order)
    # 1. СИСТЕМНАЯ ФИЛЬТРАЦИЯ: Получаем только позиции, в маршруте которых ЕСТЬ станция облицовки
    if station:
        filtered_items = service.get_filtered_items(station=station)
    else:
        filtered_items = []

    valid_items = [item for item in filtered_items if
                   item.id in report_item_ids] if requested_batches else filtered_items

    # 2. Формируем данные для рендера (позиция + картинка из БД)
    facings_data = []
    for item in valid_items:
        url = None
        if hasattr(item, 'sketch') and item.sketch:
            try:
                url = item.sketch.url
            except ValueError:
                pass
        elif hasattr(item, 'sketch_url') and item.sketch_url:
            url = item.sketch_url

        facings_data.append({
            'item': item,
            'group': item.group,
            'image_url': url,
        })

    barcode_data = f"{order.order_number};FACING"

    return render(request, 'production/reports/report_facing.html', {
        'order': order,
        'facings_data': facings_data,
        'station': station,
        'report_label': (station.label if station else "דוח חיפויים"),
        'batches_label': batches_label,
        'order_qr': get_qr_base64(barcode_data),
        'now': timezone.now(),
    })
