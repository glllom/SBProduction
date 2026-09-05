from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

from apps.orders.models import Order
from .decorators import require_order_spec
from .models import ProductionStation
from .services import OrderProductionService, ProductionDataService, TechnicalSpecService


# === 1. Production Lifecycle & Status Actions ===

@login_required
def order_transfer_to_production(request, pk):
    """
    Transfers the entire order to production status.
    """
    order = get_object_or_404(Order, pk=pk)
    try:
        OrderProductionService.start_production(order, user=request.user)
        messages.success(request, "The order was successfully transferred to production.")
    except ValueError as e:
        messages.error(request, str(e))
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
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('order-detail', pk=pk)


@login_required
def order_complete_phase1(request, pk):
    """
    Marks Phase 1 production as completed.
    """
    order = get_object_or_404(Order, pk=pk)
    try:
        OrderProductionService.complete_phase1(order, user=request.user)
        messages.success(request, "Phase 1 successfully completed.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('order-detail', pk=pk)


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
