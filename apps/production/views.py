import base64
import json
from io import BytesIO

import qrcode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from qrcode.image.svg import SvgPathImage

from apps.orders.models import OrderChangeLog, OrderItem, OrderItemsGroup, OrderStatus
from .label_services import DoorLabelService
from .models import DoorLabel, ProductionStation
from .services import (
    OrderProductionService,
    OrderValidationError,
    OrderValidationService,
    ProductionDataService,
)
from .usb_sync import run_usb_sync


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
        item.model_dump() if hasattr(item, 'model_dump') else item
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
        item.model_dump() if hasattr(item, 'model_dump') else item
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
    Единая точка запуска в производство:
    - Из PHASE1_READY (GET): показывает форму ввода замеров второй фазы.
    - Из PHASE1_READY (POST): сохраняет замеры и запускает Фазу 2.
    - Из NEW / дозаказ: сразу запускает производство в один клик.
    """
    order = get_object_or_404(Order, pk=pk)

    if order.status == OrderStatus.PHASE1_READY:
        if request.method == 'POST':
            items_by_id = {
                item.id: item for item in OrderItem.objects.filter(
                    group__order=order
                ).exclude(
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
                                    order=order, user=request.user,
                                    field_name=f"Item {mark} - {field.capitalize()}",
                                    old_value=str(old_val) if old_val is not None else "None",
                                    new_value=str(new_val) if new_val is not None else "None"
                                ))
                        except (ValueError, TypeError):
                            pass

                lh_key = f"item_{item_id}_lock_height"
                if lh_key in request.POST:
                    try:
                        val = request.POST.get(lh_key)
                        new_lh = float(val) if val else None
                        old_lh = float(order_item.custom_lock_height) if order_item.custom_lock_height else None
                        if new_lh != old_lh:
                            order_item.custom_lock_height = new_lh
                            modified = True
                            change_logs.append(OrderChangeLog(
                                order=order, user=request.user,
                                field_name=f"Item {mark} - Lock Height",
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
                            new_hh = float(val) if val else None
                            old_hh = float(getattr(order_item, field_name)) if getattr(order_item, field_name) else None
                            if new_hh != old_hh:
                                setattr(order_item, field_name, new_hh)
                                modified = True
                                change_logs.append(OrderChangeLog(
                                    order=order, user=request.user,
                                    field_name=f"Item {mark} - Hinge {i}",
                                    old_value=str(old_hh) if old_hh is not None else "None",
                                    new_value=str(new_hh) if new_hh is not None else "None"
                                ))
                        except (ValueError, TypeError):
                            pass

                if modified:
                    order_item.save()

            if change_logs:
                OrderChangeLog.objects.bulk_create(change_logs)

            try:
                OrderProductionService.start_production(order, user=request.user)
                messages.success(request, "ההזמנה הועברה לשלב ב' בהצלחה.")
                return redirect('order-detail', pk=pk)
            except (ValueError, OrderValidationError) as e:
                errors = getattr(e, 'errors', [str(e)])
                for err in errors:
                    messages.error(request, err)
                return redirect('order-detail', pk=pk)

        spec_items = TechnicalSpecService.get_batch_items(order, phase='phase1')
        return render(request, 'production/transfer_to_phase2_form.html', {
            'order': order,
            'items_data': spec_items,
        })

    try:
        OrderProductionService.start_production(order, user=request.user)

        is_ajax = (
                request.headers.get('x-requested-with') == 'XMLHttpRequest' or
                'application/json' in request.headers.get('Accept', '')
        )
        if is_ajax:
            from django.urls import reverse
            master_url = f"{reverse('production:station-report', kwargs={'pk': pk})}?station=ALL"
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
    """
    Toggles or sets the production state of an OrderItemsGroup.
    """
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
    """
    Manual validation check triggered from the UI before starting production.
    """
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
    Marks Phase 1 production as completed.
    """
    order = get_object_or_404(Order, pk=pk)

    if order.status != OrderStatus.PHASE1_PRODUCTION:
        messages.error(request, "Order is not in Phase 1 production.")
        return redirect('order-detail', pk=pk)

    try:
        spec_obj, spec_cache = TechnicalSpecService.get_or_build_spec(order, phase='phase1')
    except Exception as e:
        messages.error(request, f"Error building spec: {str(e)}")
        return redirect('order-detail', pk=pk)

    spec_items = [item.model_dump() for item in spec_obj.items]

    if request.method == 'POST':
        modified_cache = False
        change_logs = []
        items_by_id = {item.id: item for item in OrderItem.objects.filter(group__order=order)}

        target_batch_dict = spec_cache.get('batch_1', spec_cache)
        cached_items_map = {
            item['item_id']: item for item in target_batch_dict.get('items', [])
        }

        for item_spec in spec_items:
            item_id = item_spec.get('item_id')
            mark = item_spec.get('mark', str(item_id))
            order_item = items_by_id.get(item_id)
            if not order_item:
                continue

            item_modified = False
            cached_item = cached_items_map.get(item_id)

            lh_key = f"item_{item_id}_lock_height"
            if lh_key in request.POST:
                val = request.POST.get(lh_key)
                try:
                    new_val = float(val) if val else None
                    order_item.custom_lock_height = new_val
                    item_modified = True

                    old_cache_val = item_spec.get('lock_height')
                    if new_val != old_cache_val:
                        if cached_item:
                            cached_item['lock_height'] = new_val
                        modified_cache = True
                        change_logs.append(OrderChangeLog(
                            order=order,
                            user=request.user,
                            field_name=f"Item {mark} - Lock Height",
                            old_value=str(old_cache_val),
                            new_value=str(new_val)
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
                    val = new_hinge_heights[i] if i < len(new_hinge_heights) else None
                    setattr(order_item, field_name, val)
                item_modified = True

                old_hinges = item_spec.get('hinge_heights', [])
                if new_hinge_heights != old_hinges:
                    if cached_item:
                        cached_item['hinge_heights'] = new_hinge_heights
                    modified_cache = True
                    change_logs.append(OrderChangeLog(
                        order=order,
                        user=request.user,
                        field_name=f"Item {mark} - Hinge Heights",
                        old_value=str(old_hinges),
                        new_value=str(new_hinge_heights)
                    ))

            if item_modified:
                order_item.save()

        if modified_cache:
            order.phase1_spec_cache = spec_cache
            order.save(update_fields=['phase1_spec_cache'])
            if change_logs:
                OrderChangeLog.objects.bulk_create(change_logs)

        try:
            OrderProductionService.complete_phase1(order, user=request.user)
            messages.success(request, "Phase 1 successfully completed and specification updated.")
            return redirect('order-detail', pk=pk)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('order-detail', pk=pk)

    items_data = []
    for item in spec_items:
        hinges = item.get('hinge_heights', []) or []
        padded_hinges = (hinges + [None] * 5)[:5]
        item_copy = item.copy()
        item_copy['padded_hinges'] = padded_hinges
        items_data.append(item_copy)

    return render(request, 'production/complete_phase1_form.html', {
        'order': order,
        'items_data': items_data,
    })


@login_required
def order_complete_production(request, pk):
    """
    Completes overall production for the order.
    """
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
    """
    Generates and downloads the ZIP archive containing CNC machine files and technical reports.
    """
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
    """
    order = get_object_or_404(Order, pk=pk)
    station_code = request.GET.get('station') or request.GET.get('type')

    if station_code and station_code.upper() in ['PRESS', 'CUTTING_PRESS']:
        return report_cutting_press(request, pk)

    if not station_code:
        station_code = 'ALL'

    if order.status in [OrderStatus.PHASE1_PRODUCTION]:
        stage_label = "שלב א'"
    elif order.status in [OrderStatus.PHASE2_PRODUCTION, OrderStatus.PHASE1_READY]:
        stage_label = "שלב ב'"
    else:
        stage_label = "קומפלט"

    service = ProductionDataService(order)
    barcode_data = f"{order.order_number};{order.status}"

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

            filtered_items = service.get_filtered_items(station=station)
            filtered_item_ids = [item.id for item in filtered_items]

            station_spec = spec_obj.model_copy()
            station_spec.items = [item for item in spec_obj.items if item.item_id in filtered_item_ids]

            if station_spec.items or not order.groups.exists():
                include_template = None
                code_lower = station.code.lower() if station.code else ''
                if code_lower in ['frames', 'alum_frames']:
                    include_template = 'production/includes/report_alum_frames.html'
                elif code_lower in ['doors', 'alum_doors']:
                    include_template = 'production/includes/report_alum_doors.html'
                elif code_lower in ['cut_sheets', 'sheets']:
                    include_template = 'production/includes/report_cut_sheets.html'
                elif station.template_name:
                    base_name = station.template_name.split('/')[-1].replace('_report.html', '')
                    include_template = f'production/includes/report_{base_name}.html'

                if not include_template:
                    include_template = 'production/includes/report_alum_frames.html'

                enriched_frames = enrich_report_frames_spec(station_spec.items)
                enriched_doors = enrich_report_doors_spec(station_spec.items)

                sections.append({
                    'station': station,
                    'station_code': station.code,
                    'report_label': station.label or station.name,
                    'order_spec': station_spec,
                    'groups_data': service.prepare_grouped_data(station_spec),
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

    if station_code and station_code.upper() in ['WOODEN_FRAMES', 'WOOD_FRAMES']:
        frames_data = service.get_wooden_frames_data(spec_obj)
        return render(request, 'production/reports/report_wooden_frames.html', {
            'order': order,
            'order_spec': spec_obj,
            'frames_data': frames_data,
            'report_label': 'דוח משקופי עץ',
            'now': timezone.now(),
            'order_qr': get_qr_base64(barcode_data),
        })

    if station_code and station_code.upper() in ['WAREHOUSE', 'HARDWARE', 'PICK_LIST']:
        hardware_summary = service.get_warehouse_hardware_summary(spec_obj)
        return render(request, 'production/reports/report_warehouse_hardware.html', {
            'order': order,
            'order_spec': spec_obj,
            'hardware_summary': hardware_summary,
            'report_label': 'דוח ליקוט פירזול',
            'now': timezone.now(),
            'order_qr': get_qr_base64(barcode_data),
        })

    if station:
        filtered_items = service.get_filtered_items(station=station)
        template_name = station.template_name
        report_label = station.label or station.name
    else:
        filtered_items = service.get_filtered_items(report_type=station_code)
        template_name = 'production/reports/alum_frames_report.html'
        report_label = station_code

    filtered_item_ids = [item.id for item in filtered_items]
    spec_obj.items = [item for item in spec_obj.items if item.item_id in filtered_item_ids]

    enriched_doors_items = enrich_report_doors_spec(spec_obj.items)
    enriched_frames_items = enrich_report_frames_spec(spec_obj.items)

    return render(request, template_name, {
        'order': order,
        'order_spec': spec_obj,
        'spec_json': spec_obj.model_dump(by_alias=True),
        'station': station,
        'report_label': report_label,
        'groups_data': service.prepare_grouped_data(spec_obj),
        'stage_label': stage_label,
        'now': timezone.now(),
        'enriched_doors_items': enriched_doors_items,
        'enriched_frames_items': enriched_frames_items,
        'order_qr': get_qr_base64(barcode_data),
        'barcode_text': barcode_data
    })


# production/views.py

@login_required
def spec_json_preview(request, pk):
    """
    Direct inspection endpoint for the JSON specification snapshot.
    """
    order = get_object_or_404(Order, pk=pk)

    # Получаем или строим спецификацию (phase1 или phase2)
    spec_obj, spec_cache = TechnicalSpecService.get_or_build_spec(order, phase='phase1')

    data = spec_obj.model_dump(by_alias=True) if hasattr(spec_obj, 'model_dump') else spec_cache

    return JsonResponse(
        data,
        safe=False,
        json_dumps_params={'indent': 2, 'ensure_ascii': False}
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
    Uses Phase 1 specification data.
    """
    order = get_object_or_404(Order, pk=pk)

    # Strictly for split installation
    if not order.has_split_installation:
        messages.error(request, "This report is only available for split installations.")
        return redirect('order-detail', pk=pk)

    if order.status not in [OrderStatus.PHASE1_READY, OrderStatus.PHASE2_PRODUCTION]:
        # We can be strict or lose here. Let's be helpful but follow the prompt logic for the button visibility later.
        pass

    try:
        # Get Phase 1 spec (it should be already built and "baked" after phase 1 completion)
        spec_obj, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase1')
    except Exception as e:
        errors = getattr(e, 'errors', [str(e)])
        return render(request, 'production/report_validation_error.html', {
            'order': order,
            'errors': errors,
            'phase': 'phase1'
        })

    return render(request, 'production/reports/split_measurer_report.html', {
        'order': order,
        'order_spec': spec_obj,
        'report_label': "דו''ח מדידה לאחר שלב א'",
        'now': timezone.now(),
    })


@login_required
def order_compare_snapshots(request, pk):
    """
    Compares Phase 1 and Phase 2 specification snapshots for administrators.
    Shows mandatory fields (lock/hinge heights) and any changed fields.
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

    items1 = {item['item_id']: item for item in order.phase1_spec_cache.get('items', [])}
    items2 = {item['item_id']: item for item in order.phase2_spec_cache.get('items', [])}

    comparison_results = []

    for item_id, item1 in items1.items():
        item2 = items2.get(item_id)
        if not item2:
            continue

        changes = []

        # 1. Mandatory fields (Lock Height)
        lh1 = item1.get('lock_height')
        lh2 = item2.get('lock_height')
        changes.append({
            'label': 'גובה מנעול (Lock Height)',
            'old': lh1 if lh1 is not None else '-',
            'new': lh2 if lh2 is not None else '-',
            'changed': lh1 != lh2
        })

        # 2. Mandatory fields (Hinge Heights)
        hh1 = item1.get('hinge_heights', [])
        hh2 = item2.get('hinge_heights', [])
        changes.append({
            'label': 'גבהי צירים (Hinge Heights)',
            'old': ", ".join(map(str, hh1)) if hh1 else "-",
            'new': ", ".join(map(str, hh2)) if hh2 else "-",
            'changed': hh1 != hh2
        })

        # 3. Changed fields in Phase 1
        for field_key, label in spec_labels.items():
            val1 = item1.get(field_key)
            val2 = item2.get(field_key)

            if val1 != val2:
                # Requirement: data that does NOT relate to locks/hinges should only be shown
                # if they were specified in Phase 1 and changed.
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

    # Исключаем группы в статусах WAITING и CANCELED
    groups_qs = order.groups.exclude(
        production_state__in=[
            OrderItemsGroup.ProductionState.WAITING,
            OrderItemsGroup.ProductionState.CANCELED,
        ]
    )

    # Если это дозаказ (השלמות), исключаем уже закрытые группы
    if order.status == OrderStatus.COMPLETION_PRODUCTION:
        groups_qs = groups_qs.exclude(
            production_state=OrderItemsGroup.ProductionState.COMPLETED
        )

    # Собираем позиции строго с чертежами, сортируя по номеру позиции
    sketches = []
    items_qs = (
        order.groups.filter(id__in=groups_qs.values_list('id', flat=True))
        .prefetch_related('items')
    )

    all_items = []
    for group in items_qs:
        all_items.extend(list(group.items.all()))

    # Сортируем по числовому значению mark (или по ID)
    def parse_mark(it):
        try:
            return int(it.mark)
        except (ValueError, TypeError):
            return 999999

    all_items.sort(key=parse_mark)

    for it in all_items:
        # Проверяем наличие файла: либо поле ImageField/FileField, либо sketch_url
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


from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from apps.orders.models import Order
from .services import TechnicalSpecService


@login_required
def report_cutting_press(request, pk):
    order = get_object_or_404(Order, pk=pk)

    # 1. Спецификация всегда типизирована (Pydantic OrderSpec)
    order_spec, _ = TechnicalSpecService.get_or_build_spec(order, phase='phase2')

    # 2. Агрегация размеров и групп заготовок делегирована сервису
    service = ProductionDataService(order)
    panel_groups = service.prepare_press_groups_data(order_spec)

    return render(request, 'production/reports/report_press.html', {
        'order': order,
        'order_spec': order_spec,
        'panel_groups': panel_groups,
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
