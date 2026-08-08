from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, CreateView, UpdateView, DetailView, TemplateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from rest_framework import viewsets, permissions
from .serializers import OrderItemsGroupCustomizerSerializer
from .models import Order, OrderItemsGroup, OrderItem, OrderChangeLog, OrderItemsGroupCustomizer, OpeningDirection, OpeningSide
from .forms import OrderForm, OrderHeaderForm, OrderItemsGroupForm, OrderItemForm
from apps.catalog.models import ProductFamily, Series, Front, ProductType

class OrderItemUpdateView(LoginRequiredMixin, UpdateView):
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


class OrderHeaderUpdateView(LoginRequiredMixin, UpdateView):
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
            if field in ['series', 'front'] and old_val:
                old_val = str(old_val)
            if field in ['series', 'front'] and new_val:
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


class OrderDeleteView(LoginRequiredMixin, DeleteView):
    model = Order
    success_url = reverse_lazy('order-list')


class OrderItemsGroupCreateView(LoginRequiredMixin, CreateView):
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


class OrderItemsGroupUpdateView(LoginRequiredMixin, UpdateView):
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


class OrderItemsGroupDeleteView(LoginRequiredMixin, DeleteView):
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
    # Fields that measurer can update
    fields = ['height', 'width', 'wall', 'direction', 'opening', 'mark']
    for field in fields:
        if field in request.POST:
            val = request.POST.get(field)
            if val == '':
                val = None
            setattr(item, field, val)
    item.save()
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def duplicate_item_measurements(request, pk):
    item = get_object_or_404(OrderItem, pk=pk)
    group = item.group
    
    # Get all items in the same group that come AFTER the current item (by ID)
    items_to_update = OrderItem.objects.filter(group=group, id__gt=item.id)
    
    # Fields to duplicate
    fields = ['height', 'width', 'wall', 'direction', 'opening']
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
