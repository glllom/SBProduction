import json
from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Q
from django.http import JsonResponse, HttpRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.decorators.http import require_POST
from django.views.generic import ListView, CreateView, UpdateView, DetailView, TemplateView, DeleteView
from django.views.generic.base import View
from django.views.generic.edit import FormMixin
from rest_framework import viewsets, permissions

from apps.catalog.models import ProductFamily, Series, ProductType
from .forms import OrderForm, OrderItemsGroupForm, OrderItemForm
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
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_superuser or getattr(user, 'role', None) == 'ADMIN')


def check_order_editable(order: Order, user):
    """Ensure an order can be edited by a current user."""
    if not order.is_editable_by(user):
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
            elif 'pk' in self.kwargs and isinstance(self, OrderDeleteView):
                order = get_object_or_404(Order, pk=self.kwargs.get('pk'))

        if order:
            check_order_editable(order, request.user)

        return super().dispatch(request, *args, **kwargs)


class OrderItemUpdateView(LoginRequiredMixin, UpdateView):
    model = OrderItem
    form_class = OrderItemForm

    def dispatch(self, request, *args, **kwargs):
        item = self.get_object()
        if item.state == OrderItem.ItemState.CANCELED:
            raise PermissionDenied("פריט מבוטל אינו ניתן לעריכה.")
        if not item.group.is_editable_by(request.user):
            raise PermissionDenied("עריכת פריט זה נעולה.")
        return super().dispatch(request, *args, **kwargs)

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
        order = self.object
        user = self.request.user

        context['can_edit_order'] = order.is_editable_by(user)
        context['is_admin_user'] = user_is_admin(user)

        context['families'] = ProductFamily.objects.all()
        context['series'] = Series.objects.all()
        context['product_types'] = ProductType.objects.filter(active=True)
        context['header_form'] = OrderForm(instance=order, user=user)
        context['group_form'] = OrderItemsGroupForm(order=order, user=user)

        # Annotate edit permission per group
        groups = list(
            order.groups.all().select_related(
                'product__product_family__product_type', 'product__product_family',
                'series', 'front', 'basic_color_frames'
            ).prefetch_related('items', 'customizers__customizer')
        )
        for g in groups:
            g.can_edit = g.is_editable_by(user)
        context['groups'] = groups

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

        user = self.request.user
        groups = list(
            self.object.groups.all().select_related(
                'product__product_family__product_type'
            ).prefetch_related('items', 'customizers__customizer')
        )
        for g in groups:
            g.can_edit = g.is_editable_by(user)

        context['groups'] = groups
        return context


class OrderHeaderUpdateView(LoginRequiredMixin, UpdateView):
    model = Order
    form_class = OrderForm
    template_name = 'orders/order_form.html'
    context_object_name = 'order'

    def dispatch(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status == OrderStatus.CANCELED:
            raise PermissionDenied("הזמנה מבוטלת אינה ניתנת לעריכה.")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

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
    request: HttpRequest
    object: OrderItemsGroup

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
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.order = get_object_or_404(Order, pk=self.kwargs.get('order_pk'))
        return super().form_valid(form)


class OrderItemsGroupUpdateView(LoginRequiredMixin, OrderItemsGroupFormMixin, UpdateView):
    def dispatch(self, request, *args, **kwargs):
        group = self.get_object()
        if group.production_state == OrderItemsGroup.ProductionState.CANCELED:
            raise PermissionDenied("קבוצה מבוטלת אינה ניתנת לעריכה.")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['order'] = self.object.order
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        old_instance = OrderItemsGroup.objects.get(pk=self.object.pk)
        response = super().form_valid(form)
        new_instance = self.object

        changed_fields = form.changed_data
        for field in changed_fields:
            old_val = getattr(old_instance, field)
            new_val = getattr(new_instance, field)
            OrderChangeLog.objects.create(
                order=new_instance.order,
                user=self.request.user,
                field_name=f"group_{new_instance.id}_{field}",
                old_value=str(old_val) if old_val is not None else None,
                new_value=str(new_val) if new_val is not None else None
            )
        return response


class OrderItemsGroupDeleteView(LoginRequiredMixin, DeleteView):
    model = OrderItemsGroup

    def dispatch(self, request, *args, **kwargs):
        group = self.get_object()
        if not group.is_editable_by(request.user):
            raise PermissionDenied("לא ניתן למחוק קבוצה בייצור. יש להשתמש בביטול קבוצה (פורס-מז'ור).")
        return super().dispatch(request, *args, **kwargs)

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

    def perform_create(self, serializer):
        group = serializer.validated_data.get('group')
        if group and not group.is_editable_by(self.request.user):
            raise PermissionDenied("קבוצה זו נעולה לעריכה.")
        serializer.save()

    def perform_update(self, serializer):
        group = serializer.instance.group
        if not group.is_editable_by(self.request.user):
            raise PermissionDenied("קבוצה זו נעולה לעריכה.")
        serializer.save()

    def perform_destroy(self, instance: OrderItemsGroupCustomizer):
        if not instance.group.is_editable_by(self.request.user):
            raise PermissionDenied("קבוצה זו נעולה לעריכה.")
        instance.delete()


# ==========================================
# Item Measurements & Actions
# ==========================================

@login_required
@require_POST
def update_item_measurements(request, pk):
    item = get_object_or_404(OrderItem.objects.select_related('group__order'), pk=pk)

    if item.state == OrderItem.ItemState.CANCELED:
        return JsonResponse({'status': 'error', 'message': 'פריט מבוטל אינו ניתן לעריכה'}, status=400)

    if not item.group.is_editable_by(request.user):
        return JsonResponse({'status': 'error', 'message': 'עריכת פריט זה נעולה'}, status=403)

    fields = [
        'height', 'width', 'wall', 'direction', 'opening', 'mark',
        'place', 'bottom_correction', 'comment',
        'custom_lock_height', 'custom_hinge1', 'custom_hinge2',
        'custom_hinge3', 'custom_hinge4', 'custom_hinge5'
    ]

    changes = []
    for field in fields:
        if field in request.POST:
            val = request.POST.get(field)
            val = None if val == '' or val is None else val
            old_val = getattr(item, field)

            old_str = str(old_val) if old_val is not None else ''
            new_str = str(val) if val is not None else ''

            if old_str != new_str:
                setattr(item, field, val)
                changes.append(
                    OrderChangeLog(
                        order=item.group.order,
                        user=request.user,
                        field_name=f"door_{item.mark or item.id}_{field}",
                        old_value=old_str or None,
                        new_value=new_str or None,
                    )
                )

    if 'sketch' in request.FILES:
        old_sketch = item.sketch.name if item.sketch else None
        uploaded_sketch = cast(UploadedFile, request.FILES['sketch'])
        item.sketch = uploaded_sketch
        changes.append(
            OrderChangeLog(
                order=item.group.order,
                user=request.user,
                field_name=f"door_{item.mark or item.id}_sketch",
                old_value=old_sketch,
                new_value=item.sketch.name,
            )
        )
    elif request.POST.get('delete_sketch') == 'true' and item.sketch:
        old_sketch = item.sketch.name
        item.sketch.delete(save=False)
        item.sketch = None
        changes.append(
            OrderChangeLog(
                order=item.group.order,
                user=request.user,
                field_name=f"door_{item.mark or item.id}_sketch",
                old_value=old_sketch,
                new_value=None,
            )
        )

    item.save()

    if changes:
        OrderChangeLog.objects.bulk_create(changes)

    return JsonResponse({
        'status': 'ok',
        'sketch_url': item.sketch.url if item.sketch else None
    })


@login_required
@require_POST
def duplicate_item_measurements(request, pk):
    item = get_object_or_404(OrderItem.objects.select_related('group__order'), pk=pk)

    if not item.group.is_editable_by(request.user):
        return JsonResponse({'status': 'error', 'message': 'עריכת פריט זה נעולה'}, status=403)

    group = item.group
    items_to_update = OrderItem.objects.filter(
        group=group,
        id__gte=item.id
    ).exclude(state=OrderItem.ItemState.CANCELED)

    numeric_fields = [
        'height', 'width', 'wall', 'bottom_correction',
        'custom_lock_height', 'custom_hinge1', 'custom_hinge2',
        'custom_hinge3', 'custom_hinge4', 'custom_hinge5'
    ]
    char_fields = ['direction', 'opening', 'place', 'comment']
    update_data = {}

    for field in numeric_fields:
        if field in request.POST:
            val = request.POST.get(field, '').strip()
            if val == '':
                update_data[field] = None
            else:
                try:
                    update_data[field] = float(val)
                except (ValueError, TypeError):
                    update_data[field] = None

    for field in char_fields:
        if field in request.POST:
            val = request.POST.get(field, '')
            update_data[field] = val.strip() if val else ''

    if update_data:
        items_to_update.update(**update_data)
        OrderChangeLog.objects.create(
            order=group.order,
            user=request.user,
            field_name=f"group_{group.id}_duplicate_measurements",
            old_value=f"From door #{item.mark or item.id}",
            new_value=json.dumps(update_data, ensure_ascii=False)
        )

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
    if not group.is_editable_by(request.user):
        raise PermissionDenied("קבוצה זו נעולה לעריכה.")

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


@login_required
@require_POST
def order_item_cancel(request, pk):
    """Force-majeure door cancellation."""
    item = get_object_or_404(OrderItem.objects.select_related('group__order'), pk=pk)

    if item.group.order.status in [OrderStatus.COMPLETED, OrderStatus.CANCELED]:
        return JsonResponse({'status': 'error', 'message': 'לא ניתן לבטל בהזמנה שהסתיימה או בוטלה'}, status=400)

    if item.state != OrderItem.ItemState.CANCELED:
        item.state = OrderItem.ItemState.CANCELED
        item.save(update_fields=['state'])

        OrderChangeLog.objects.create(
            order=item.group.order,
            user=request.user,
            field_name=f"door_{item.mark or item.id}_state",
            old_value=OrderItem.ItemState.ACTIVE,
            new_value=OrderItem.ItemState.CANCELED
        )

    return JsonResponse({'status': 'ok', 'message': f'דלת מס {item.mark} בוטלה בהצלחה'})


@login_required
@require_POST
def order_group_cancel(request, pk):
    """Force-majeure group cancellation."""
    group = get_object_or_404(OrderItemsGroup.objects.select_related('order'), pk=pk)

    if group.order.status in [OrderStatus.COMPLETED, OrderStatus.CANCELED]:
        return JsonResponse({'status': 'error', 'message': 'לא ניתן לבטל בהזמנה שהסתיימה או בוטלה'}, status=400)

    if group.production_state != OrderItemsGroup.ProductionState.CANCELED:
        old_state = group.production_state
        group.production_state = OrderItemsGroup.ProductionState.CANCELED
        group.save(update_fields=['production_state'])

        group.items.filter(state=OrderItem.ItemState.ACTIVE).update(state=OrderItem.ItemState.CANCELED)

        OrderChangeLog.objects.create(
            order=group.order,
            user=request.user,
            field_name=f"group_{group.id}_production_state",
            old_value=old_state,
            new_value=OrderItemsGroup.ProductionState.CANCELED
        )

    target_url = reverse('order-detail', kwargs={'pk': group.order.pk})
    return json_or_redirect(request, target_url, {
        'status': 'ok',
        'message': f'קבוצה מס #{group.id} בוטלה בהצלחה'
    })


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
