import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.decorators.http import require_POST
from django.views.generic import ListView, CreateView, UpdateView, DetailView, TemplateView, DeleteView
from django.views.generic.base import View
from django.views.generic.edit import FormMixin
from rest_framework import viewsets, permissions

from apps.catalog.models import ProductFamily, Series, ProductType
from .forms import OrderForm, OrderHeaderForm, OrderItemsGroupForm, OrderItemForm
from .models import (
    Order, OrderItemsGroup, OrderItem, OrderChangeLog,
    OrderItemsGroupCustomizer, OrderStatus,
    GroupSpecification
)
from .serializers import (
    OrderItemsGroupCustomizerSerializer,
    GroupSpecificationSerializer
)


# ==========================================
# Helpers (DRY & Typing safeguards)
# ==========================================

def user_is_admin(user) -> bool:
    """Safely check if the user is authenticated and has admin privileges."""
    return bool(user.is_authenticated and getattr(user, 'is_admin_user', False))


def check_order_editable(order: Order, user):
    """Ensure an order can be edited by a current user."""
    if order.status != OrderStatus.NEW and not user_is_admin(user):
        raise PermissionDenied("שינוי הזמנה בייצור מותר למנהל מערכת בלבד.")


def parse_positive_int(raw_value):
    """Safely parse a string into a positive integer or return None."""
    if not raw_value:
        return None
    val_str = str(raw_value).strip()
    return int(val_str) if val_str.isdigit() else None


def json_or_redirect(request, redirect_url: str, data: dict):
    """Helper to return JSON for AJAX requests or redirect otherwise."""
    is_ajax = (
            request.headers.get('x-requested-with') == 'XMLHttpRequest' or
            'application/json' in (request.headers.get('accept') or '')
    )
    if is_ajax:
        return JsonResponse(data)
    return redirect(redirect_url)


def update_order_status_logged(request, pk: int, target_status: str, error_message: str):
    """Helper to transition order status with security checks and change log."""
    if not user_is_admin(request.user):
        raise PermissionDenied(error_message)

    order = get_object_or_404(Order, pk=pk)
    if order.status != target_status:
        old_status = order.status
        order.status = target_status
        order.save()

        OrderChangeLog.objects.create(
            order=order,
            user=request.user,
            field_name='status',
            old_value=old_status,
            new_value=target_status
        )

    return redirect('order-detail', pk=pk)


# ==========================================
# Permissions & Class-Based Views
# ==========================================

class OrderEditPermissionMixin(View):
    def dispatch(self, request, *args, **kwargs):
        order = None
        if hasattr(self, 'get_object'):
            try:
                if not isinstance(self, CreateView):
                    obj = self.get_object()
                    if isinstance(obj, Order):
                        order = obj
                    elif hasattr(obj, 'order'):
                        order = obj.order
                    elif hasattr(obj, 'group'):
                        order = obj.group.order
            except (AttributeError, ObjectDoesNotExist):
                pass

        if not order:
            if 'order_pk' in self.kwargs:
                order = get_object_or_404(Order, pk=self.kwargs.get('order_pk'))
            elif 'pk' in self.kwargs and isinstance(self, (OrderHeaderUpdateView, OrderDeleteView)):
                order = get_object_or_404(Order, pk=self.kwargs.get('pk'))

        if order:
            check_order_editable(order, request.user)

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
        context['saved_specifications'] = GroupSpecification.objects.all().select_related(
            'product', 'product__product_family__product_type', 'product__product_family',
            'series', 'front', 'basic_color_frames', 'created_by'
        ).prefetch_related('customizers__customizer')
        return context


@login_required
def order_reset_to_new(request, pk):
    return update_order_status_logged(
        request=request,
        pk=pk,
        target_status=OrderStatus.NEW,
        error_message="שינוי סטטוס הזמנה מותר למנהל מערכת בלבד."
    )


@login_required
def order_cancel(request, pk):
    return update_order_status_logged(
        request=request,
        pk=pk,
        target_status=OrderStatus.CANCELED,
        error_message="ביטול הזמנה מותר למנהל מערכת בלבד."
    )


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


# ==========================================
# Group Views & Mixins
# ==========================================

class OrderItemsGroupFormMixin(FormMixin):
    """Shared configuration and form handling logic for OrderItemsGroup views."""
    model = OrderItemsGroup
    form_class = OrderItemsGroupForm
    template_name = 'orders/orderitemsgroup_form.html'

    def form_invalid(self, form):
        print(f"Group action failed: {form.errors}")
        return super().form_invalid(form)

    def get_success_url(self):
        base_url = reverse('order-detail', kwargs={'pk': self.object.order.pk})
        if self.request.POST.get('action') == 'customize':
            return f"{base_url}?open_customize={self.object.pk}"
        return base_url


class OrderItemsGroupCreateView(LoginRequiredMixin, OrderEditPermissionMixin, OrderItemsGroupFormMixin, CreateView):
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['order'] = get_object_or_404(Order, pk=self.kwargs.get('order_pk'))
        return kwargs

    def form_valid(self, form):
        form.instance.order = get_object_or_404(Order, pk=self.kwargs.get('order_pk'))
        return super().form_valid(form)


class OrderItemsGroupUpdateView(LoginRequiredMixin, OrderEditPermissionMixin, OrderItemsGroupFormMixin, UpdateView):
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['order'] = self.object.order
        return kwargs


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


# ==========================================
# Item Measurements & Actions
# ==========================================

@login_required
@require_POST
def update_item_measurements(request, pk):
    item = get_object_or_404(OrderItem, pk=pk)
    check_order_editable(item.group.order, request.user)

    fields = [
        'height', 'width', 'wall', 'direction', 'opening', 'mark',
        'place', 'addition_cut', 'comment',
        'custom_lock_height', 'custom_hinge1', 'custom_hinge2',
        'custom_hinge3', 'custom_hinge4', 'custom_hinge5'
    ]
    for field in fields:
        if field in request.POST:
            val = request.POST.get(field)
            setattr(item, field, None if val == '' else val)

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
    check_order_editable(item.group.order, request.user)
    group = item.group

    items_to_update = OrderItem.objects.filter(group=group, id__gte=item.id)
    fields = [
        'height', 'width', 'wall', 'direction', 'opening',
        'place', 'addition_cut', 'comment',
        'custom_lock_height', 'custom_hinge1', 'custom_hinge2',
        'custom_hinge3', 'custom_hinge4', 'custom_hinge5'
    ]
    update_data = {}
    for field in fields:
        if field in request.POST:
            val = request.POST.get(field)
            update_data[field] = None if val == '' else val

    if update_data:
        items_to_update.update(**update_data)
        group.order.invalidate_cache_if_unlocked()

    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def group_duplicate(request, pk):
    group = get_object_or_404(OrderItemsGroup, pk=pk)
    check_order_editable(group.order, request.user)

    new_group = group.duplicate()
    target_url = reverse('order-detail', kwargs={'pk': group.order.pk})
    return json_or_redirect(request, target_url, {
        'status': 'ok',
        'new_group_id': new_group.id,
        'redirect_url': target_url,
        'message': 'הקבוצה שוכפלה בהצלחה'
    })


# ==========================================
# Specifications Management
# ==========================================

@login_required
@require_POST
def save_group_specification(request, pk):
    group = get_object_or_404(OrderItemsGroup, pk=pk)
    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()

    if not name and request.content_type and 'application/json' in request.content_type:
        try:
            data = json.loads(request.body)
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    if not name:
        return JsonResponse({'status': 'error', 'message': 'נא להזין שם למפרט'}, status=400)

    spec = GroupSpecification.create_from_group(
        group=group,
        name=name,
        description=description,
        user=request.user,
    )

    target_url = reverse('order-detail', kwargs={'pk': group.order.pk})
    return json_or_redirect(request, target_url, {
        'status': 'ok',
        'spec_id': spec.id,
        'spec_name': spec.name,
        'message': 'המפרט נשמר בהצלחה'
    })


@login_required
@require_POST
def apply_group_specification(request, pk, spec_pk):
    group = get_object_or_404(OrderItemsGroup, pk=pk)
    check_order_editable(group.order, request.user)

    spec = get_object_or_404(GroupSpecification, pk=spec_pk)
    update_qty = request.POST.get('update_quantity') in ['true', '1', 'on', True]
    new_qty = parse_positive_int(request.POST.get('quantity')) if update_qty else None

    spec.apply_to_group(group, update_quantity=update_qty, new_quantity=new_qty)

    target_url = reverse('order-detail', kwargs={'pk': group.order.pk})
    return json_or_redirect(request, target_url, {
        'status': 'ok',
        'group_id': group.id,
        'redirect_url': target_url,
        'message': 'המפרט הוחל על הקבוצה בהצלחה'
    })


@login_required
@require_POST
def create_group_from_specification(request, order_pk, spec_pk):
    order = get_object_or_404(Order, pk=order_pk)
    check_order_editable(order, request.user)

    spec = get_object_or_404(GroupSpecification, pk=spec_pk)
    qty = parse_positive_int(request.POST.get('quantity'))

    new_group = spec.create_order_group(order, quantity=qty)

    target_url = reverse('order-detail', kwargs={'pk': order.pk})
    return json_or_redirect(request, target_url, {
        'status': 'ok',
        'new_group_id': new_group.id,
        'redirect_url': target_url,
        'message': 'הקבוצה נוספה בהצלחה מתוך המפרט'
    })


@login_required
@require_POST
def delete_group_specification(request, pk):
    spec = get_object_or_404(GroupSpecification, pk=pk)
    spec.delete()
    return json_or_redirect(
        request,
        request.META.get('HTTP_REFERER', '/'),
        {'status': 'ok', 'message': 'המפרט נמחק בהצלחה'}
    )


class GroupSpecificationViewSet(viewsets.ModelViewSet):
    queryset = GroupSpecification.objects.all().select_related(
        'product', 'product__product_family__product_type', 'product__product_family',
        'series', 'front', 'basic_color_frames', 'created_by'
    ).prefetch_related('customizers__customizer')
    serializer_class = GroupSpecificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.query_params.get('q')
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) |
                Q(description__icontains=q) |
                Q(product__name__icontains=q) |
                Q(series__name__icontains=q)
            )
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
