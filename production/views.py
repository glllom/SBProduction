from django.shortcuts import render, redirect, get_object_or_404

from production.models import DBOrder, DBOrderItem
from .forms import OrderForm, OrderItemFormSet, OrderItemCustomizerFormSet

def order_list(request):
    orders = DBOrder.objects.all()
    return render(request, 'production/order_list.html', {'orders': orders})

def order_create(request):
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            order = form.save()
            return redirect('order-edit', pk=order.pk)
    else:
        form = OrderForm()
    return render(request, 'production/order_form.html', {'form': form, 'title': 'Add Order'})

def order_edit(request, pk):
    order = get_object_or_404(DBOrder, pk=pk)
    if request.method == 'POST':
        form = OrderForm(request.POST, instance=order)
        formset = OrderItemFormSet(request.POST, instance=order)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            return redirect('order-list')
    else:
        form = OrderForm(instance=order)
        formset = OrderItemFormSet(instance=order)

    # Добавляем кастомайзеры для каждой формы
    for item_form in formset:
        if item_form.instance.pk:
            item_form.customizer_list = item_form.instance.customizers.select_related('customizer')
        else:
            item_form.customizer_list = []

    return render(request, 'production/order_edit.html', {
        'form': form,
        'formset': formset,
        'order': order,
        'title': f'Edit Order {order.order_number}'
    })

def order_delete(request, pk):
    order = get_object_or_404(DBOrder, pk=pk)
    if request.method == 'POST':
        order.delete()
        return redirect('order-list')
    return render(request, 'production/order_confirm_delete.html', {'order': order})

def order_item_customizers(request, item_id):
    item = get_object_or_404(DBOrderItem, pk=item_id)
    if request.method == 'POST':
        formset = OrderItemCustomizerFormSet(request.POST, instance=item)
        if formset.is_valid():
            formset.save()
            return redirect('order-edit', pk=item.order.pk)
    else:
        formset = OrderItemCustomizerFormSet(instance=item)
    return render(request, 'production/order_item_customizers.html', {
        'formset': formset,
        'item': item
    })
