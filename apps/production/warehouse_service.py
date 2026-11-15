import math
from collections import defaultdict

from django.db import transaction

from apps.catalog.models import Hardware
from apps.orders.models import Order, OrderItemsGroup, OrderItem, OrderWarehouseItem


class WarehousePackingSlipService:
    CATEGORY_ORDER = [
        OrderWarehouseItem.Category.LOCKS,
        OrderWarehouseItem.Category.HANDLES,
        OrderWarehouseItem.Category.HINGES,
        OrderWarehouseItem.Category.OTHER,
    ]
    PERIMETER_RESERVE_METERS = 2.0  # Технологический запас уплотнителя на заказ (в метрах)

    @classmethod
    def ensure_initialized(cls, order: Order):
        if order.warehouse_state == Order.WarehouseState.UNINITIALIZED:
            cls.recalculate(order)

    @staticmethod
    def _calc_net_dimensions(item: OrderItem, group: OrderItemsGroup) -> tuple[float | None, float | None]:
        """Возвращает (чистая_ширина_полотна, чистая_высота_полотна) в см."""
        family = group.product.product_family if group.product else None
        w = float(item.width) if item.width is not None else None
        h = float(item.height) if item.height is not None else None

        if not family:
            return (round(w, 1) if w is not None else None, round(h, 1) if h is not None else None)

        if w is not None:
            w = round(
                w - abs(float(family.frame_inner_width_reduction or 0)) - abs(float(family.leaf_side_clearance or 0)),
                1
            )
        if h is not None:
            h = round(
                h
                - abs(float(family.frame_inner_height_reduction or 0))
                - abs(float(family.leaf_top_clearance or 0))
                - abs(float(family.leaf_bottom_clearance or 0)),
                1
            )

        return w, h

    @staticmethod
    def _fmt_num(val: float) -> str:
        return str(int(val)) if float(val).is_integer() else f"{val:.1f}"

    @classmethod
    @transaction.atomic
    def recalculate(cls, order: Order):
        if order.warehouse_state == Order.WarehouseState.LOCKED:
            raise ValueError("התעודה נעולה — לא ניתן לחשב מחדש.")

        order.warehouse_items.all().delete()

        groups = (
            order.groups.exclude(production_state=OrderItemsGroup.ProductionState.CANCELED)
            .select_related(
                'product',
                'product__product_family__product_type',
                'product__bom',
                'product__bom__lock',
                'product__bom__hinges',
            )
            .prefetch_related(
                'items',
                'product__bom__additional',
                'customizers__customizer__hardware__components',
            )
        )

        color_variants_map = cls._get_color_variants_map()

        # Размерная сетка по common_name для стратегий MATCH_LEAF_WIDTH / MATCH_LEAF_HEIGHT (из par1_value)
        sized_qs = (
            Hardware.objects.filter(active=True)
            .exclude(common_name='')
            .exclude(par1_value='')
            .select_related('color')
        )
        sized_variants_map = defaultdict(list)
        for h in sized_qs:
            num_val = h.get_numeric_par(1)
            if num_val is not None:
                sized_variants_map[h.common_name.strip()].append((num_val, h))

        for c_name in sized_variants_map:
            sized_variants_map[c_name].sort(key=lambda pair: (pair[0], pair[1].id))

        aggregated = defaultdict(lambda: {
            'category': OrderWarehouseItem.Category.OTHER,
            'common_name': '',
            'hardware': None,
            'name': '',
            'sku': '',
            'qty': 0.0,
            'comment': '',
            'is_color_required': False,
            'is_perimeter': False,
        })

        def process_hardware(
                hw: Hardware,
                category: str,
                qty: float,
                group: OrderItemsGroup,
                item: OrderItem | None = None,
                visited=None
        ):
            if not hw or qty <= 0:
                return
            if visited is None:
                visited = set()
            if hw.id in visited:
                return
            visited.add(hw.id)

            rule = hw.rule_tag or Hardware.RuleTag.STANDARD

            # 1. Фильтрация по покраске (вкручиваемые петли pipe мама/папа)
            if rule == Hardware.RuleTag.ONLY_IF_PANEL_PAINTED:
                if group.panel_paint_option == OrderItemsGroup.PaintOption.NO_PAINT:
                    for comp in hw.components.filter(active=True):
                        process_hardware(comp, category, qty, group, item, visited.copy())
                    return

            if rule == Hardware.RuleTag.ONLY_IF_FRAME_PAINTED:
                if group.frame_paint_option == OrderItemsGroup.PaintOption.NO_PAINT:
                    for comp in hw.components.filter(active=True):
                        process_hardware(comp, category, qty, group, item, visited.copy())
                    return

            c_name = (hw.common_name or '').strip()

            # 2. Подбор по ширине или высоте полотна через par1_value
            if rule in (Hardware.RuleTag.MATCH_LEAF_WIDTH, Hardware.RuleTag.MATCH_LEAF_HEIGHT) and item is not None:
                net_w, net_h = cls._calc_net_dimensions(item, group)
                target_dim = net_w if rule == Hardware.RuleTag.MATCH_LEAF_WIDTH else net_h
                dim_label = 'רוחב כנף' if rule == Hardware.RuleTag.MATCH_LEAF_WIDTH else 'גובה כנף'
                size_pool = sized_variants_map.get(c_name, [])

                if size_pool and target_dim is not None:
                    suitable = [(sz, h) for sz, h in size_pool if sz >= target_dim]
                    if suitable:
                        chosen_size = suitable[0][0]
                        note = f"מידת פריט: {cls._fmt_num(chosen_size)} | {dim_label}: {cls._fmt_num(target_dim)}"
                    else:
                        chosen_size = size_pool[-1][0]
                        note = f"חריג מידה! מקס' במלאי: {cls._fmt_num(chosen_size)} | {dim_label}: {cls._fmt_num(target_dim)}"

                    same_size_items = [h for sz, h in size_pool if sz == chosen_size]
                    has_color_choices = len({h.color_id for h in same_size_items if h.color_id}) > 1

                    key = (category, f"sized_{c_name}_{chosen_size}_{target_dim}")
                    entry = aggregated[key]
                    entry['category'] = category
                    entry['common_name'] = c_name
                    entry['comment'] = note
                    entry['qty'] += qty

                    if has_color_choices:
                        entry['name'] = f"{c_name} ({cls._fmt_num(chosen_size)})"
                        entry['is_color_required'] = True
                    else:
                        chosen_hw = same_size_items[0]
                        entry['hardware'] = chosen_hw
                        entry['name'] = chosen_hw.name
                        entry['sku'] = chosen_hw.sku or ''

                    for comp in hw.components.filter(active=True):
                        process_hardware(comp, category, qty, group, item, visited.copy())
                    return

            # 3. Расчёт погонажа уплотнителя по периметру (в метрах)
            if rule == Hardware.RuleTag.PERIMETER_METERS and item is not None:
                raw_w = float(item.width or 80)
                raw_h = float(item.height or 210)
                meters = ((2 * raw_h) + raw_w) / 100.0 * qty

                has_color_choices = bool(c_name and len(color_variants_map.get((c_name, None), [])) > 1)
                key = (category, f"perim_{c_name}" if has_color_choices else f"perim_hw_{hw.id}")
                entry = aggregated[key]
                entry['category'] = category
                entry['common_name'] = c_name
                entry['name'] = c_name if has_color_choices else hw.name
                entry['is_color_required'] = has_color_choices
                entry['is_perimeter'] = True
                if not has_color_choices:
                    entry['hardware'] = hw
                    entry['sku'] = hw.sku or ''
                entry['qty'] += meters
                return

            # 4. Стандартная позиция
            has_color_choices = bool(c_name and len(color_variants_map.get((c_name, None), [])) > 1)
            key = (category, c_name if has_color_choices else f"hw_{hw.id}")

            entry = aggregated[key]
            entry['category'] = category
            entry['common_name'] = c_name
            entry['name'] = c_name if has_color_choices else hw.name
            entry['is_color_required'] = has_color_choices
            if not has_color_choices:
                entry['hardware'] = hw
                entry['sku'] = hw.sku or ''
            entry['qty'] += qty

            for comp in hw.components.filter(active=True):
                process_hardware(comp, category, qty, group, item, visited.copy())

        for group in groups:
            active_items = [it for it in group.items.all() if it.state != OrderItem.ItemState.CANCELED]
            items_count = len(active_items)
            if items_count == 0:
                continue

            has_door = group.product.has_door if group.product else True
            bom = group.product.effective_bom if group.product else None

            # 1. Ручки
            if has_door and order.handle:
                h_key = (OrderWarehouseItem.Category.HANDLES, f"handle_{order.handle.id}")
                aggregated[h_key]['category'] = OrderWarehouseItem.Category.HANDLES
                aggregated[h_key]['name'] = order.handle.name
                aggregated[h_key]['sku'] = order.handle.code or ''
                aggregated[h_key]['qty'] += items_count

            # 2. Замки
            if bom and getattr(bom, 'lock', None):
                for it in active_items:
                    process_hardware(bom.lock, OrderWarehouseItem.Category.LOCKS, 1, group, it)

            # 3. Петли (поштучно для каждой двери с учётом custom_hinge1..5 и режима покраски)
            if bom and getattr(bom, 'hinges', None):
                for it in active_items:
                    custom_h = [
                        getattr(it, f'custom_hinge{i}', None)
                        for i in range(1, 6)
                        if getattr(it, f'custom_hinge{i}', None) is not None
                    ]
                    hinges_per_door = len(custom_h) if custom_h else 3
                    process_hardware(bom.hinges, OrderWarehouseItem.Category.HINGES, hinges_per_door, group, it)

            # 4. Доп. аксессуары и уплотнители из BOM
            if bom and hasattr(bom, 'additional'):
                for add_item in bom.additional.all():
                    if isinstance(add_item, Hardware):
                        for it in active_items:
                            process_hardware(add_item, OrderWarehouseItem.Category.OTHER, 1, group, it)
                    else:
                        m_key = (OrderWarehouseItem.Category.OTHER, f"mat_{add_item.id}")
                        aggregated[m_key]['category'] = OrderWarehouseItem.Category.OTHER
                        aggregated[m_key]['common_name'] = getattr(add_item, 'common_name', '') or ''
                        aggregated[m_key]['name'] = add_item.name
                        aggregated[m_key]['sku'] = getattr(add_item, 'sku', '') or ''
                        aggregated[m_key]['qty'] += items_count

            # 5. Кастомизаторы группы
            for gc in group.customizers.all():
                cust = gc.customizer
                target_cat = cls._guess_category_by_tag(cust.tag)

                if cust.hardware:
                    for it in active_items:
                        process_hardware(cust.hardware, target_cat, 1, group, it)

                for i in range(1, 6):
                    raw_val = getattr(gc, f'par{i}', '') or ''
                    if raw_val.upper().startswith('SKU='):
                        sku_code = raw_val.split('=', 1)[1].strip()
                        hw_obj = Hardware.objects.filter(sku=sku_code, active=True).first()
                        if hw_obj:
                            for it in active_items:
                                process_hardware(hw_obj, target_cat, 1, group, it)

        items_to_create = []
        for idx, (_, data) in enumerate(aggregated.items()):
            hw_obj = data['hardware']
            color_str = hw_obj.color.name if (hw_obj and hw_obj.color) else ''
            final_qty = data['qty']
            comment_str = data['comment']

            if data['is_perimeter']:
                final_qty = math.ceil(final_qty + cls.PERIMETER_RESERVE_METERS)
                if not comment_str:
                    comment_str = f'מטר רץ (כולל {int(cls.PERIMETER_RESERVE_METERS)} מ\' רזרבה)'

            items_to_create.append(OrderWarehouseItem(
                order=order,
                category=data['category'],
                common_name=data['common_name'],
                hardware=hw_obj,
                name=data['name'],
                sku=data['sku'],
                color_name=color_str,
                is_color_required=data['is_color_required'],
                quantity=final_qty,
                comment=comment_str,
                sort_order=idx,
            ))

        OrderWarehouseItem.objects.bulk_create(items_to_create)

        if order.warehouse_state == Order.WarehouseState.UNINITIALIZED:
            order.warehouse_state = Order.WarehouseState.DRAFT
            order.save(update_fields=['warehouse_state'])

    @staticmethod
    def _guess_category_by_tag(tag: str) -> str:
        t = (tag or '').lower()
        if 'handle' in t:
            return OrderWarehouseItem.Category.HANDLES
        if 'lock' in t or 'cylinder' in t:
            return OrderWarehouseItem.Category.LOCKS
        if 'hinge' in t:
            return OrderWarehouseItem.Category.HINGES
        return OrderWarehouseItem.Category.OTHER

    @staticmethod
    def _get_color_variants_map() -> dict:
        qs = Hardware.objects.filter(
            active=True,
            color__isnull=False
        ).exclude(common_name='').select_related('color').order_by('color__id')

        mapping = defaultdict(list)
        for h in qs:
            len_key = h.get_numeric_par(1)
            mapping[(h.common_name.strip(), len_key)].append(h)
        return mapping

    @classmethod
    def get_grouped_items_for_ui(cls, order: Order):
        cls.ensure_initialized(order)
        variants_map = cls._get_color_variants_map()

        sections = {cat: [] for cat in cls.CATEGORY_ORDER}
        all_colors = set()

        for item in order.warehouse_items.select_related('hardware__color').all():
            options = []
            if item.common_name:
                item_len = item.hardware.get_numeric_par(1) if item.hardware else None
                matched_variants = variants_map.get((item.common_name, item_len), [])
                if not matched_variants and item_len is None:
                    for (c_name_key, _), hw_list in variants_map.items():
                        if c_name_key == item.common_name:
                            matched_variants.extend(hw_list)

                for opt_hw in matched_variants:
                    c_name = opt_hw.color.name if opt_hw.color else ''
                    if c_name:
                        all_colors.add(c_name)
                    options.append({
                        'id': opt_hw.id,
                        'name': opt_hw.name,
                        'sku': opt_hw.sku,
                        'color_name': c_name,
                    })

            sections[item.category].append({
                'obj': item,
                'color_options': options,
            })

        return [
            {
                'code': cat,
                'label': OrderWarehouseItem.Category(cat).label,
                'rows': sections[cat],
            }
            for cat in cls.CATEGORY_ORDER
        ], sorted(all_colors)
