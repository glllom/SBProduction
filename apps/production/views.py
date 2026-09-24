from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.orders.models import Order, OrderStatus, OrderChangeLog, OrderItem, OrderItemsGroup
from .decorators import require_order_spec
from .models import ProductionStation
from .services import (
    OrderProductionService,
    ProductionDataService,
    TechnicalSpecService,
    OrderValidationError,
    OrderValidationService,
)
from .usb_sync import run_usb_sync


# === 1. Production Lifecycle & Status Actions ===

@login_required
def order_transfer_to_production(request, pk):
    """
    Transfers the entire order to production status.
    """
    order = get_object_or_404(Order, pk=pk)

    # Form for Phase 2 transition (if starting from Phase 1 Ready)
    if order.status == OrderStatus.PHASE1_READY:
        try:
            # We use Phase 1 spec to pre-fill values and show info (like lock/hinge names)
            spec_obj, spec_cache = TechnicalSpecService.get_or_build_spec(order, phase='phase1')
        except Exception as e:
            messages.error(request, f"Error building spec: {str(e)}")
            return redirect('order-detail', pk=pk)

        # Extract items directly from Pydantic spec_obj
        spec_items = [item.model_dump() for item in spec_obj.items]

        if request.method == 'POST':
            change_logs = []
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

            for item_spec in spec_items:
                item_id = item_spec.get('item_id')
                order_item = items_by_id.get(item_id)
                if not order_item:
                    continue

                modified = False
                mark = item_spec.get('mark', str(item_id))

                # 1. Width / Height / Wall (Input is Inner/Gross, save External)
                reduction_h = float(item_spec.get('frame_inner_height_reduction') or 0)
                reduction_w = float(item_spec.get('frame_inner_width_reduction') or 0)

                for field, reduction, label in [('height', reduction_h, 'Height'), ('width', reduction_w, 'Width'),
                                                ('wall', 0, 'Wall')]:
                    key = f"item_{item_id}_{field}"
                    if key in request.POST:
                        try:
                            val = request.POST.get(key)
                            new_inner = float(val) if val else None
                            new_val_to_save = (new_inner - reduction) if new_inner is not None else None

                            old_val_saved = float(getattr(order_item, field)) if getattr(order_item, field) else None
                            if new_val_to_save != old_val_saved:
                                setattr(order_item, field, new_val_to_save)
                                modified = True
                                log_label = f"{label} (Inner)" if field != 'wall' else label
                                change_logs.append(OrderChangeLog(
                                    order=order, user=request.user,
                                    field_name=f"Item {mark} - {log_label}",
                                    old_value=str(
                                        round(old_val_saved + reduction, 1)) if old_val_saved is not None else "None",
                                    new_value=str(round(new_inner, 1)) if new_inner is not None else "None"
                                ))
                        except (ValueError, TypeError):
                            pass

                # 2. Lock Height (Input is Gross, save Net)
                clearance = float(item_spec.get('leaf_top_clearance') or 0)
                lh_key = f"item_{item_id}_lock_height"
                if lh_key in request.POST:
                    val = request.POST.get(lh_key)
                    try:
                        new_gross = float(val) if val else None
                        new_net = new_gross + clearance if new_gross is not None else None

                        old_net = float(order_item.custom_lock_height) if order_item.custom_lock_height else None
                        effective_old_net = old_net if old_net is not None else item_spec.get('lock_height')

                        if new_net != effective_old_net:
                            order_item.custom_lock_height = new_net
                            modified = True
                            change_logs.append(OrderChangeLog(
                                order=order, user=request.user,
                                field_name=f"Item {mark} - Lock Height (Gross)",
                                old_value=str(round(effective_old_net - clearance,
                                                    1)) if effective_old_net is not None else "None",
                                new_value=str(round(new_gross, 1)) if new_gross is not None else "None"
                            ))
                    except (ValueError, TypeError):
                        pass

                # 3. Hinge Heights (Input is Gross, save Net)
                spec_hinges_net = item_spec.get('hinge_heights', []) or []
                for i in range(5):
                    hh_key = f"item_{item_id}_hinge_height_{i}"
                    field_name = f"custom_hinge{i + 1}"
                    if hh_key in request.POST:
                        val = request.POST.get(hh_key)
                        try:
                            new_gross = float(val) if val else None
                            new_net = new_gross + clearance if new_gross is not None else None

                            old_net = float(getattr(order_item, field_name)) if getattr(order_item,
                                                                                        field_name) else None
                            effective_old_net = old_net if old_net is not None else (
                                spec_hinges_net[i] if len(spec_hinges_net) > i else None)

                            if new_net != effective_old_net:
                                setattr(order_item, field_name, new_net)
                                modified = True
                                change_logs.append(OrderChangeLog(
                                    order=order, user=request.user,
                                    field_name=f"Item {mark} - Hinge {i + 1} (Gross)",
                                    old_value=str(round(effective_old_net - clearance,
                                                        1)) if effective_old_net is not None else "None",
                                    new_value=str(round(new_gross, 1)) if new_gross is not None else "None"
                                ))
                        except (ValueError, TypeError):
                            pass

                if modified:
                    order_item.save()

            if change_logs:
                OrderChangeLog.objects.bulk_create(change_logs)

            # Reset Phase 2 validation to force rebuild
            order.phase2_validated = False
            order.phase2_spec_cache = None
            order.save(update_fields=['phase2_validated', 'phase2_spec_cache'])

            try:
                OrderProductionService.start_production(order, user=request.user)
                messages.success(request, "The order was successfully transferred to Phase 2 production.")
                return redirect('order-detail', pk=pk)
            except (ValueError, OrderValidationError) as e:
                errors = getattr(e, 'errors', [str(e)])
                for err in errors:
                    messages.error(request, err)
                return redirect('order-detail', pk=pk)

        # GET logic
        items_data = []
        items_by_id = {item.id: item for item in OrderItem.objects.filter(group__order=order)}
        for item_spec in spec_items:
            item_id = item_spec.get('item_id')
            order_item = items_by_id.get(item_id)
            if not order_item:
                continue

            item_data = item_spec.copy()
            # Show Inner dimensions (Gross)
            reduction_h = float(item_spec.get('frame_inner_height_reduction') or 0)
            reduction_w = float(item_spec.get('frame_inner_width_reduction') or 0)
            item_data['width'] = (float(order_item.width) + reduction_w) if order_item.width else item_spec.get(
                'inner_width')
            item_data['height'] = (float(order_item.height) + reduction_h) if order_item.height else item_spec.get(
                'inner_height')
            item_data['wall'] = float(order_item.wall or item_spec.get('wall') or 0)

            # Show Lock Height (Gross)
            clearance = float(item_spec.get('leaf_top_clearance') or 0)
            lock_h_net = order_item.custom_lock_height
            if lock_h_net is not None:
                item_data['lock_height'] = float(lock_h_net) - clearance
            else:
                item_data['lock_height'] = item_spec.get('lock_height_on_frame')

            # Show Hinge Heights (Gross)
            hinge_heights_gross = []
            spec_hinges_gross = item_spec.get('hinge_heights_on_frame', []) or []
            for i in range(1, 6):
                val_net = getattr(order_item, f"custom_hinge{i}")
                if val_net is not None:
                    hinge_heights_gross.append(float(val_net) - clearance)
                else:
                    val_gross = spec_hinges_gross[i - 1] if len(spec_hinges_gross) >= i else None
                    hinge_heights_gross.append(val_gross)
            item_data['padded_hinges'] = hinge_heights_gross

            items_data.append(item_data)

        return render(request, 'production/transfer_to_phase2_form.html', {
            'order': order,
            'items_data': items_data,
        })

    try:
        OrderProductionService.start_production(order, user=request.user)
        messages.success(request, "The order was successfully transferred to production.")
    except (ValueError, OrderValidationError) as e:
        errors = getattr(e, 'errors', [str(e)])
        for err in errors:
            messages.error(request, err)
    return redirect('order-detail', pk=pk)


@login_required
def order_transfer_to_completion_production(request, pk):
    """
    Transfers order to completion production (ייצור השלמות) for new / waiting groups.
    """
    order = get_object_or_404(Order, pk=pk)
    try:
        OrderProductionService.start_completion_production(order, user=request.user)
        messages.success(request, "ההזמנה הועברה לייצור השלמות בהצלחה.")
    except (ValueError, OrderValidationError) as e:
        errors = getattr(e, 'errors', [str(e)])
        for err in errors:
            messages.error(request, err)
    return redirect('order-detail', pk=pk)


@login_required
def group_toggle_state(request, pk, group_id):
    """
    Toggles or sets the production state of an OrderItemsGroup (unfreezing the completed group back to WAITING).
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
def order_transfer_to_phase1(request, pk):
    """
    Transfers Phase 1 (aluminum frames) to production.
    """
    order = get_object_or_404(Order, pk=pk)
    try:
        OrderProductionService.start_phase1(order, user=request.user)
        messages.success(request, "Phase 1 (Frames) successfully transferred to production.")
    except (ValueError, OrderValidationError) as e:
        errors = getattr(e, 'errors', [str(e)])
        for err in errors:
            messages.error(request, err)
    return redirect('order-detail', pk=pk)


@login_required
def order_complete_phase1(request, pk):
    """
    Marks Phase 1 production as completed.
    Form to adjust spec values before transitioning to PHASE1_READY.
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

    # Extract flat items list from Pydantic spec_obj
    spec_items = [item.model_dump() for item in spec_obj.items]

    if request.method == 'POST':
        modified_cache = False
        change_logs = []
        items_by_id = {item.id: item for item in OrderItem.objects.filter(group__order=order)}

        # Locate the batch dictionary to update cache properly
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

            # Lock height
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

            # Hinge heights (up to 5)
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

    # Prepare data for template (padded hinges)
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

    if not station_code:
        station_code = 'ALL'

    # Determine stage label based on order status
    if order.status in [OrderStatus.PHASE1_PRODUCTION]:
        stage_label = "שלב א'"
    elif order.status in [OrderStatus.PHASE2_PRODUCTION, OrderStatus.PHASE1_READY]:
        stage_label = "שלב ב'"
    else:
        stage_label = "קומפלט"

    service = ProductionDataService(order)

    if station_code.upper() in ['ALL', 'IN_PRODUCTION', 'FULL', 'FULL_PRODUCTION']:
        # Master print mode: aggregate all stations
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

                sections.append({
                    'station': station,
                    'station_code': station.code,
                    'report_label': station.label or station.name,
                    'order_spec': station_spec,
                    'groups_data': service.prepare_grouped_data(station_spec),
                    'include_template': include_template,
                })

        return render(request, 'production/master_report.html', {
            'order': order,
            'sections': sections,
            'stage_label': stage_label,
            'now': timezone.now(),
        })

    # Single station report
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

    if station:
        filtered_items = service.get_filtered_items(station=station)
        template_name = station.template_name or 'production/alum_frames_report.html'
        report_label = station.label or station.name
    else:
        filtered_items = service.get_filtered_items(report_type=station_code)
        template_name = 'production/alum_frames_report.html'
        report_label = station_code

    filtered_item_ids = [item.id for item in filtered_items]
    spec_obj.items = [item for item in spec_obj.items if item.item_id in filtered_item_ids]

    return render(request, template_name, {
        'order': order,
        'order_spec': spec_obj,
        'spec_json': spec_obj.model_dump(by_alias=True),
        'station': station,
        'report_label': report_label,
        'groups_data': service.prepare_grouped_data(spec_obj),
        'stage_label': stage_label,
        'now': timezone.now(),
    })


@login_required
@require_order_spec(phase='phase1')
def spec_json_preview(request, spec_json_dict, **kwargs):
    """
    Direct inspection endpoint for the cached JSON specification snapshot.
    """
    return JsonResponse(
        spec_json_dict,
        json_dumps_params={'indent': 2, 'ensure_ascii': False}
    )


@login_required
def order_dev_force_rebuild_spec(request, pk):
    """
    Development-only helper: Forces a full spec rebuild regardless of cache/status
    and redirects to the JSON preview.
    """
    order = get_object_or_404(Order, pk=pk)

    # 1. Reset everything
    order.reset_validation()
    order.save()

    # 2. Rebuild spec (phase1 is default for now)
    try:
        TechnicalSpecService.get_or_build_spec(order, phase='phase1')
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

    return render(request, 'production/split_measurer_report.html', {
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
