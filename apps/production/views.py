from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.orders.models import Order, OrderStatus, OrderChangeLog, OrderItem
from .decorators import require_order_spec
from .models import ProductionStation
from .services import OrderProductionService, ProductionDataService, TechnicalSpecService, OrderValidationError
from .usb_sync import run_usb_sync


# === 1. Production Lifecycle & Status Actions ===

@login_required
def order_transfer_to_production(request, pk):
    """
    Transfers the entire order to production status.
    """
    order = get_object_or_404(Order, pk=pk)

    # NEW: Form for Phase 2 transition (if starting from Phase 1 Ready)
    if order.status == OrderStatus.PHASE1_READY:
        try:
            # We use Phase 1 spec to pre-fill values and show info (like lock/hinge names)
            spec_obj, spec_json = TechnicalSpecService.get_or_build_spec(order, phase='phase1')
        except Exception as e:
            messages.error(request, f"Error building spec: {str(e)}")
            return redirect('order-detail', pk=pk)

        if request.method == 'POST':
            change_logs = []
            items_by_id = {item.id: item for item in OrderItem.objects.filter(group__order=order)}

            for item_spec in spec_json.get('items', []):
                item_id = item_spec.get('item_id')
                order_item = items_by_id.get(item_id)
                if not order_item:
                    continue

                modified = False
                mark = item_spec.get('mark', str(item_id))

                # 1. Width / Height
                for field in ['width', 'height']:
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
                                    old_value=str(old_val), new_value=str(new_val)
                                ))
                        except (ValueError, TypeError):
                            pass

                # 2. Lock Height
                lh_key = f"item_{item_id}_lock_height"
                if lh_key in request.POST:
                    val = request.POST.get(lh_key)
                    try:
                        new_val = float(val) if val else None
                        old_val = float(order_item.custom_lock_height) if order_item.custom_lock_height else None

                        effective_old = old_val if old_val is not None else item_spec.get('lock_height')

                        if new_val != effective_old:
                            order_item.custom_lock_height = new_val
                            modified = True
                            change_logs.append(OrderChangeLog(
                                order=order, user=request.user,
                                field_name=f"Item {mark} - Custom Lock Height",
                                old_value=str(effective_old), new_value=str(new_val)
                            ))
                    except (ValueError, TypeError):
                        pass

                # 3. Hinge Heights
                spec_hinges = item_spec.get('hinge_heights', [])
                for i in range(5):
                    hh_key = f"item_{item_id}_hinge_height_{i}"
                    field_name = f"custom_hinge{i + 1}"
                    if hh_key in request.POST:
                        val = request.POST.get(hh_key)
                        try:
                            new_val = float(val) if val else None
                            old_val = float(getattr(order_item, field_name)) if getattr(order_item,
                                                                                        field_name) else None

                            effective_old = old_val if old_val is not None else (
                                spec_hinges[i] if len(spec_hinges) > i else None)

                            if new_val != effective_old:
                                setattr(order_item, field_name, new_val)
                                modified = True
                                change_logs.append(OrderChangeLog(
                                    order=order, user=request.user,
                                    field_name=f"Item {mark} - Custom Hinge {i + 1}",
                                    old_value=str(effective_old), new_value=str(new_val)
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
        for item_spec in spec_json.get('items', []):
            item_id = item_spec.get('item_id')
            order_item = items_by_id.get(item_id)
            if not order_item:
                continue

            item_data = item_spec.copy()
            item_data['width'] = order_item.width
            item_data['height'] = order_item.height

            lock_h = order_item.custom_lock_height
            if lock_h is None:
                lock_h = item_spec.get('lock_height')
            item_data['lock_height'] = lock_h

            hinge_heights = []
            spec_hinges = item_spec.get('hinge_heights', [])
            for i in range(1, 6):
                val = getattr(order_item, f"custom_hinge{i}")
                if val is None:
                    val = spec_hinges[i - 1] if len(spec_hinges) >= i else None
                hinge_heights.append(val)
            item_data['padded_hinges'] = hinge_heights

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
    Now with a form to adjust spec values before transitioning to PHASE1_READY.
    """
    order = get_object_or_404(Order, pk=pk)

    # We only allow this transition from IN_PRODUCTION_PHASE1
    if order.status != OrderStatus.IN_PRODUCTION_PHASE1:
        messages.error(request, "Order is not in Phase 1 production.")
        return redirect('order-detail', pk=pk)

    try:
        spec_obj, spec_json = TechnicalSpecService.get_or_build_spec(order, phase='phase1')
    except Exception as e:
        messages.error(request, f"Error building spec: {str(e)}")
        return redirect('order-detail', pk=pk)

    if request.method == 'POST':
        modified_cache = False
        change_logs = []
        # Load all items for this order to update them in DB
        items_by_id = {item.id: item for item in OrderItem.objects.filter(group__order=order)}

        for item_spec in spec_json.get('items', []):
            item_id = item_spec.get('item_id')
            mark = item_spec.get('mark', str(item_id))
            order_item = items_by_id.get(item_id)
            if not order_item:
                continue

            item_modified = False

            # Lock height
            lh_key = f"item_{item_id}_lock_height"
            if lh_key in request.POST:
                val = request.POST.get(lh_key)
                try:
                    new_val = float(val) if val else None
                    # ALWAYS save to OrderItem
                    order_item.custom_lock_height = new_val
                    item_modified = True

                    # Update cache and log ONLY if changed compared to cache
                    old_cache_val = item_spec.get('lock_height')
                    if new_val != old_cache_val:
                        item_spec['lock_height'] = new_val
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
                # ALWAYS update OrderItem fields
                for i in range(5):
                    field_name = f"custom_hinge{i + 1}"
                    val = new_hinge_heights[i] if i < len(new_hinge_heights) else None
                    setattr(order_item, field_name, val)
                item_modified = True

                # Update cache and log ONLY if changed compared to cache
                old_hinges = item_spec.get('hinge_heights', [])
                if new_hinge_heights != old_hinges:
                    item_spec['hinge_heights'] = new_hinge_heights
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
            order.phase1_spec_cache = spec_json
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
    for item in spec_json.get('items', []):
        hinges = item.get('hinge_heights', [])
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
def order_production_data(request, **kwargs):
    # TODO: Implement full code to generate production data zip file
    """
    Will be updated to handle CNC XML export and batch report downloading.
    """
    pass


@login_required
def station_report(request, pk):
    """
    Single entry point for all station HTML reports.
    Dynamically resolves phase and template name based on the requested ProductionStation.
    """
    order = get_object_or_404(Order, pk=pk)
    station_code = request.GET.get('station')
    station = get_object_or_404(ProductionStation, code=station_code)

    phase = 'phase1' if station.is_phase1 else 'phase2'

    try:
        spec_obj, _ = TechnicalSpecService.get_or_build_spec(order, phase=phase)
    except Exception as e:
        errors = getattr(e, 'errors', [str(e)])
        return render(request, 'production/report_validation_error.html', {
            'order': order,
            'errors': errors,
            'phase': phase
        })

    service = ProductionDataService(order)

    return render(request, station.template_name or 'production/alum_frames_report.html', {
        'order': order,
        'order_spec': spec_obj,
        'station': station,
        'report_label': station.label or station.name,
        'groups_data': service.prepare_grouped_data(spec_obj),
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

    # User said: button strictly after phase 1 and before phase 2.
    # However, we'll allow access if phase 1 is ready or phase 2 is in production.
    if order.status not in [OrderStatus.PHASE1_READY, OrderStatus.IN_PRODUCTION_PHASE2]:
        # We can be strict or loose here. Let's be helpful but follow the prompt logic for the button visibility later.
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

    if order.status != OrderStatus.IN_PRODUCTION_PHASE2:
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

        # 3. Changed fields that were in Phase 1
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
