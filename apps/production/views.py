from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

from apps.orders.models import Order, OrderStatus
from .services import OrderProductionService, OrderValidationService, ProductionDataService


@login_required
def order_transfer_to_production(request, pk):
    order = get_object_or_404(Order, pk=pk)

    try:
        OrderProductionService.start_production(order, user=request.user)
        messages.success(request, "ההזמנה הועברה לייצור בהצלחה")
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('order-detail', pk=pk)


@login_required
def order_check_validation(request, pk):
    order = get_object_or_404(Order, pk=pk)
    
    # Use the same logic as in start_production
    is_valid, errors = OrderProductionService.validate_for_production(order)
    
    if is_valid:
        messages.success(request, "הנתונים תקינים. ניתן להעביר לייצור.")
    else:
        for error in errors:
            messages.error(request, error)
            
    return redirect('order-detail', pk=pk)


@login_required
def order_transfer_to_phase1(request, pk):
    order = get_object_or_404(Order, pk=pk)

    try:
        OrderProductionService.start_phase1(order, user=request.user)
        messages.success(request, "שלב א' (משקופים) הועבר לייצור בהצלחה")
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('order-detail', pk=pk)


@login_required
def order_complete_phase1(request, pk):
    order = get_object_or_404(Order, pk=pk)

    try:
        OrderProductionService.complete_phase1(order, user=request.user)
        messages.success(request, "שלב א' הושלם בהצלחה")
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('order-detail', pk=pk)


@login_required
def order_production_data(request, pk):
    order = get_object_or_404(Order, pk=pk)

    val_res = OrderValidationService.validate_for_zip(order)
    if not val_res.is_valid:
        for error in val_res.errors:
            messages.error(request, f"לא ניתן להפיק קובצי ייצור: {error}")
        return redirect('order-detail', pk=pk)

    try:
        service = ProductionDataService(order)
        zip_buffer = service.generate_production_zip()
    except ValueError as e:
        messages.error(request, f"שגיאה בהפקת קובצי ייצור: {str(e)}")
        return redirect('order-detail', pk=pk)

    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="production_data_{order.order_number}.zip"'
    return response


@login_required
def order_production_report(request, pk):
    order = get_object_or_404(Order, pk=pk)
    service = ProductionDataService(order)

    report_type = request.GET.get('type')
    station_code = request.GET.get('station')

    # If no type/station specified, try to determine best default
    if not report_type and not station_code:
        has_split = order.groups.filter(is_split_installation=True).exists()
        if has_split and order.status == OrderStatus.IN_PRODUCTION_PHASE1:
            report_type = ProductionDataService.ReportType.PHASE1_FRAMES
        else:
            report_type = ProductionDataService.ReportType.IN_PRODUCTION

    # Pre-fetch station if provided to get its label for the error page
    station = None
    if station_code:
        from .models import ProductionStation
        station = ProductionStation.objects.filter(code=station_code).first()

    val_res = OrderValidationService.validate_for_report(order, report_type, station=station)
    if not val_res.is_valid:
        label = report_type or (station.label if station else "דו\"ח")
        if report_type in ProductionDataService.ReportType.values:
            label = ProductionDataService.ReportType(report_type).label

        context = {
            'order': order,
            'report_type': report_type,
            'station': station,
            'report_label': label,
            'validation_errors': val_res.errors,
            'validation_type': val_res.validation_type,
        }
        return render(request, 'production/report_validation_error.html', context)

    try:
        report_html = service.generate_report_html(report_type, station_code=station_code)
    except ValueError as e:
        context = {
            'order': order,
            'report_type': report_type,
            'report_label': report_type or (station.label if station else "שגיאה"),
            'validation_errors': [str(e)],
        }
        return render(request, 'production/report_validation_error.html', context)

    return HttpResponse(report_html)


alum_frames_report = order_production_report
