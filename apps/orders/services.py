from apps.orders.models import OrderItem


def recalculate_item_marks(order) -> None:
    """Пересчитывает сквозную нумерацию (mark) всех позиций заказа."""
    all_items = OrderItem.objects.filter(group__order=order).order_by('group__id', 'id')
    items_to_update = []
    for idx, item in enumerate(all_items, start=1):
        new_mark = str(idx)
        if item.mark != new_mark:
            item.mark = new_mark
            items_to_update.append(item)

    if items_to_update:
        OrderItem.objects.bulk_update(items_to_update, ['mark'])


def sync_group_items(group) -> None:
    """Синхронизирует количество записей OrderItem с полем group.quantity."""
    if not group.product or group.quantity is None:
        return

    existing_items = list(group.items.all().order_by('id'))
    current_count = len(existing_items)

    if current_count < group.quantity:
        existing_marks = (
            OrderItem.objects.filter(group__order=group.order)
            .exclude(mark='')
            .values_list('mark', flat=True)
        )
        max_mark = 0
        for m in existing_marks:
            try:
                max_mark = max(max_mark, int(m))
            except (ValueError, TypeError):
                continue

        product_family = getattr(group.product, 'product_family', None)
        has_door = product_family.has_door if product_family else True
        has_frame = product_family.has_frame if product_family else True

        wall_default = None
        raw_wall = getattr(product_family, 'default_value_for_frame', None)
        if raw_wall is not None and str(raw_wall).strip() != '':
            try:
                wall_default = float(str(raw_wall).strip())
            except (ValueError, TypeError):
                wall_default = None

        items_to_create = []
        for i in range(1, (group.quantity - current_count) + 1):
            item_kwargs = {
                'group': group,
                'mark': str(max_mark + i),
                'wall': wall_default if has_frame else None,
            }
            if not has_door:
                item_kwargs['direction'] = None
                item_kwargs['opening'] = None
            items_to_create.append(OrderItem(**item_kwargs))

        OrderItem.objects.bulk_create(items_to_create)

    elif current_count > group.quantity:
        ids_to_delete = [item.id for item in existing_items[group.quantity:]]
        OrderItem.objects.filter(id__in=ids_to_delete).delete()
