from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, CreateView, UpdateView, DetailView, TemplateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from rest_framework import viewsets, permissions
from .serializers import OrderItemsGroupCustomizerSerializer
from django.core.exceptions import PermissionDenied
from .models import Order, OrderItemsGroup, OrderItem, OrderChangeLog, OrderItemsGroupCustomizer, OrderStatus
from .forms import OrderForm, OrderHeaderForm, OrderItemsGroupForm, OrderItemForm
from apps.catalog.models import ProductFamily, Series, Front, ProductType

class OrderEditPermissionMixin:
    def dispatch(self, request, *args, **kwargs):
        order = None
        # Try to get order from the object being edited
        if hasattr(self, 'get_object'):
            try:
                # We need to be careful not to trigger get_object if it's not needed or fails
                # For CreateView, get_object might not be what we want
                if not isinstance(self, CreateView):
                    obj = self.get_object()
                    if isinstance(obj, Order):
                        order = obj
                    elif hasattr(obj, 'order'):
                        order = obj.order
                    elif hasattr(obj, 'group'):
                        order = obj.group.order
            except:
                pass
        
        # Try to get order from URL kwargs if not found yet
        if not order:
            if 'order_pk' in self.kwargs:
                order = get_object_or_404(Order, pk=self.kwargs.get('order_pk'))
            elif 'pk' in self.kwargs and isinstance(self, (OrderHeaderUpdateView, OrderDeleteView)):
                order = get_object_or_404(Order, pk=self.kwargs.get('pk'))

        if order and order.status == OrderStatus.IN_PRODUCTION and not request.user.is_admin_user:
            raise PermissionDenied("שינוי הזמנה בייצור מותר למנהל מערכת בלבד.")
        return super().dispatch(request, *args, **kwargs)

class OrderItemUpdateView(LoginRequiredMixin, OrderEditPermissionMixin, UpdateView):
    model = OrderItem
    form_class = OrderItemForm

    def get_success_url(self):
        return reverse_lazy('order-detail', kwargs={'pk': self.object.group.order.pk})

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'

class OrderListView(LoginRequiredMixin, ListView):
    model = Order
    template_name = 'orders/order_list.html'
    context_object_name = 'orders'
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(
                Q(order_number__icontains=q) |
                Q(customer__icontains=q)
            )
        return queryset[:10]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        return context

class OrderCreateView(LoginRequiredMixin, CreateView):
    model = Order
    form_class = OrderForm
    template_name = 'orders/order_form.html'

    def get_success_url(self):
        return reverse_lazy('order-detail', kwargs={'pk': self.object.pk})

class OrderDetailView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = 'orders/order_detail.html'
    context_object_name = 'order'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['families'] = ProductFamily.objects.all()
        context['series'] = Series.objects.all()
        context['product_types'] = ProductType.objects.filter(active=True)
        context['header_form'] = OrderHeaderForm(instance=self.object)
        context['group_form'] = OrderItemsGroupForm(order=self.object)
        return context


class OrderMeasurementsView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = 'orders/order_measurements.html'
    context_object_name = 'order'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['product_types'] = ProductType.objects.filter(active=True)
        return context


class OrderHeaderUpdateView(LoginRequiredMixin, OrderEditPermissionMixin, UpdateView):
    model = Order
    form_class = OrderHeaderForm

    def form_valid(self, form):
        order = self.get_object()
        old_instance = Order.objects.get(pk=order.pk)
        response = super().form_valid(form)
        new_instance = self.object

        changed_fields = form.changed_data
        for field in changed_fields:
            old_val = getattr(old_instance, field)
            new_val = getattr(new_instance, field)
            
            # For ForeignKeys, we might want the __str__ or name
            if field in ['series', 'front', 'handle'] and old_val:
                old_val = str(old_val)
            if field in ['series', 'front', 'handle'] and new_val:
                new_val = str(new_val)

            OrderChangeLog.objects.create(
                order=new_instance,
                user=self.request.user,
                field_name=field,
                old_value=str(old_val) if old_val is not None else None,
                new_value=str(new_val) if new_val is not None else None
            )
        return response

    def get_success_url(self):
        return reverse_lazy('order-detail', kwargs={'pk': self.object.pk})


class OrderDeleteView(LoginRequiredMixin, OrderEditPermissionMixin, DeleteView):
    model = Order
    success_url = reverse_lazy('order-list')


class OrderItemsGroupCreateView(LoginRequiredMixin, OrderEditPermissionMixin, CreateView):
    model = OrderItemsGroup
    form_class = OrderItemsGroupForm
    template_name = 'orders/orderitemsgroup_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['order'] = get_object_or_404(Order, pk=self.kwargs.get('order_pk'))
        return kwargs

    def form_valid(self, form):
        form.instance.order = get_object_or_404(Order, pk=self.kwargs.get('order_pk'))
        return super().form_valid(form)
    
    def form_invalid(self, form):
        # Log errors for debugging
        print(f"Group Create failed: {form.errors}")
        return super().form_invalid(form)

    def get_success_url(self):
        base_url = reverse_lazy('order-detail', kwargs={'pk': self.object.order.pk})
        if self.request.POST.get('action') == 'customize':
            return f"{base_url}?open_customize={self.object.pk}"
        return base_url


class OrderItemsGroupUpdateView(LoginRequiredMixin, OrderEditPermissionMixin, UpdateView):
    model = OrderItemsGroup
    form_class = OrderItemsGroupForm
    template_name = 'orders/orderitemsgroup_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['order'] = self.object.order
        return kwargs

    def form_invalid(self, form):
        # Log errors for debugging
        print(f"Group Update failed: {form.errors}")
        return super().form_invalid(form)

    def get_success_url(self):
        base_url = reverse_lazy('order-detail', kwargs={'pk': self.object.order.pk})
        if self.request.POST.get('action') == 'customize':
            return f"{base_url}?open_customize={self.object.pk}"
        return base_url


class OrderItemsGroupDeleteView(LoginRequiredMixin, OrderEditPermissionMixin, DeleteView):
    model = OrderItemsGroup

    def get_success_url(self):
        return reverse_lazy('order-detail', kwargs={'pk': self.object.order.pk})


class OrderItemsGroupCustomizerViewSet(viewsets.ModelViewSet):
    queryset = OrderItemsGroupCustomizer.objects.all()
    serializer_class = OrderItemsGroupCustomizerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        group_id = self.request.query_params.get('group_id')
        if group_id:
            queryset = queryset.filter(group_id=group_id)
        return queryset


@login_required
@require_POST
def update_item_measurements(request, pk):
    item = get_object_or_404(OrderItem, pk=pk)
    if item.group.order.status == OrderStatus.IN_PRODUCTION and not request.user.is_admin_user:
        raise PermissionDenied("שינוי הזמנה בייצור מותר למנהל מערכת בלבד.")
    # Fields that measurer can update
    fields = [
        'height', 'width', 'wall', 'direction', 'opening', 'mark',
        'place', 'addition_cut', 'comment',
        'custom_lock_height', 'custom_hinge1', 'custom_hinge2',
        'custom_hinge3', 'custom_hinge4', 'custom_hinge5'
    ]
    for field in fields:
        if field in request.POST:
            val = request.POST.get(field)
            if val == '':
                val = None
            setattr(item, field, val)
    
    if 'sketch' in request.FILES:
        item.sketch = request.FILES['sketch']
    elif request.POST.get('delete_sketch') == 'true':
        item.sketch.delete(save=False)
        item.sketch = None

    item.save()
    return JsonResponse({
        'status': 'ok',
        'sketch_url': item.sketch.url if item.sketch else None
    })


@login_required
@require_POST
def duplicate_item_measurements(request, pk):
    item = get_object_or_404(OrderItem, pk=pk)
    if item.group.order.status == OrderStatus.IN_PRODUCTION and not request.user.is_admin_user:
        raise PermissionDenied("שינוי הזמנה בייצור מותר למנהל מערכת בלבד.")
    group = item.group
    
    # Get all items in the same group that come AFTER the current item (by ID)
    items_to_update = OrderItem.objects.filter(group=group, id__gt=item.id)
    
    # Fields to duplicate
    fields = ['height', 'width', 'wall', 'direction', 'opening', 'place', 'addition_cut', 'comment']
    update_data = {}
    for field in fields:
        if field in request.POST:
            val = request.POST.get(field)
            if val == '':
                val = None
            update_data[field] = val
            
    if update_data:
        # We also need to consider if fields are disabled (has_door, has_frame)
        # But for now, we apply to all as per user request "она все данные из текущей строки должна продублировать"
        # The frontend handles disabling, so if a field was empty/null it stays so.
        items_to_update.update(**update_data)
        
    return JsonResponse({'status': 'ok'})


@login_required
def order_transfer_to_production(request, pk):
    order = get_object_or_404(Order, pk=pk)
    
    is_valid, errors = order.validate_for_production()
    if not is_valid:
        # We could use messages framework here
        from django.contrib import messages
        for error in errors:
            messages.error(request, error)
        return redirect('order-detail', pk=pk)

    order.start_production(user=request.user)
    
    return redirect('order-detail', pk=pk)


@login_required
def order_transfer_to_phase1(request, pk):
    order = get_object_or_404(Order, pk=pk)
    
    # We use the same validation as for production, 
    # but validate_for_production already handles split installation logic.
    is_valid, errors = order.validate_for_production()
    if not is_valid:
        from django.contrib import messages
        for error in errors:
            messages.error(request, error)
        return redirect('order-detail', pk=pk)

    order.start_phase1(user=request.user)
    
    return redirect('order-detail', pk=pk)


@login_required
def order_production_data(request, pk):
    from apps.production.services import ProductionDataService
    order = get_object_or_404(Order, pk=pk)
    
    service = ProductionDataService(order)
    zip_buffer = service.generate_production_zip()
    
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="production_data_{order.order_number}.zip"'
    return response


@login_required
def order_production_report(request, pk):
    from apps.production.services import ProductionDataService
    order = get_object_or_404(Order, pk=pk)
    service = ProductionDataService(order)
    
    report_type = request.GET.get('type')
    
    # If no type specified, try to determine best default
    if not report_type:
        has_split = order.groups.filter(is_split_installation=True).exists()
        if has_split and order.status == OrderStatus.PHASE1_PRODUCTION:
            report_type = ProductionDataService.ReportType.PHASE1_FRAMES
        else:
            report_type = ProductionDataService.ReportType.FULL_PRODUCTION
    
    report_html = service.generate_report_html(report_type)
    return HttpResponse(report_html)
