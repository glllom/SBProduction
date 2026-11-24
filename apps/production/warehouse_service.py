import math
from collections import defaultdict

from django.db import transaction

from apps.catalog.models import Hardware
from apps.orders.models import Order, OrderItemsGroup, OrderItem, OrderWarehouseItem
from apps.production.engine import OrderSpecEngine


class WarehousePackingSlipService:
    CATEGORY_ORDER = [
        OrderWarehouseItem.Category.LOCKS,
        OrderWarehouseItem.Category.HANDLES,
        OrderWarehouseItem.Category.HINGES,
        OrderWarehouseItem.Category.OTHER,
    ]
    PERIMETER_RESERVE_RATIO = 0.02

    @classmethod
    def ensure_initialized(cls, order: Order):
        if order.warehouse_state == Order.WarehouseState.UNINITIALIZED:
            cls.recalculate(order)

    @staticmethod
    def _fmt_num(val: float) -> str:
        rounded = round(float(val), 2)
        return f"{rounded:g}"

    @staticmethod
    def _get_effective_specs_by_item_id(order: Order, rich_items: list) -> dict:
        """
        Холостой прогон OrderSpecPipeline для получения эффективного BOM,
        высот петель и чистых размеров полотен без сохранения снимков в БД.
        """
        if not rich_items:
            return {}
        try:
            engine = OrderSpecEngine()
            spec_obj = engine.execute(order, items=rich_items, phase='phase2', save_labels=False)
            result = {}
            for b_items in spec_obj.batches.values():
                for sp in b_items:
                    result[sp.item_id] = sp
            return result
        except Exception:
            return {}

    @classmethod
    @transaction.atomic
    def recalculate(cls, order: Order):
        if order.warehouse_state == Order.WarehouseState.LOCKED:
            raise ValueError("התעודה נעולה — לא ניתן לחשב מחדש.")

        order.warehouse_items.all().delete()

        # Берём все активные позиции заказа (включая WAITING при раздельном монтаже, исключая только CANCELED)
        rich_items = list(
            OrderItem.objects.filter(group__order_id=order.id)
            .exclude(group__production_state=OrderItemsGroup.ProductionState.CANCELED)
            .exclude(state=OrderItem.ItemState.CANCELED)
            .select_related(
                'group',
                'group__order',
                'group__order__series',
                'group__order__front',
                'group__order__handle',
                'group__product',
                'group__product__product_family',
                'group__product__product_family__product_type',
                'group__product__series',
                'group__product__bom',
                'group__product__bom__frame',
                'group__product__bom__covering',
                'group__product__bom__base',
                'group__product__bom__filling',
                'group__product__bom__lock',
                'group__product__bom__hinges',
                'group__front',
                'group__series',
                'group__basic_color_frames',
            )
            .prefetch_related(
                'group__customizers__customizer__hardware__components',
                'group__product__bom__additional',
            )
            .order_by('group__id', 'id')
        )

        effective_specs = cls._get_effective_specs_by_item_id(order, rich_items)
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

        # Предзагружаем справочник Hardware для быстрого доступа по ID из bom_items
        hw_cache = {
            h.id: h
            for h in Hardware.objects.filter(active=True)
            .select_related('color')
            .prefetch_related('components', 'product_types', 'product_families', 'product_models')
        }

        aggregated = defaultdict(lambda: {
            'category': OrderWarehouseItem.Category.OTHER,
            'common_name': '',
            'hardware': None,
            'name': '',
            'sku': '',
            'qty': 0.0,
            'comment': '',
            'cut_dims': [],
            'is_color_required': False,
            'is_perimeter': False,
            'is_half_meter': False,
        })

        def process_hardware(
                hw: Hardware,
                category: str,
                qty: float,
                group: OrderItemsGroup,
                item: OrderItem | None = None,
                panel_dims: list | None = None,
                visited=None,
                force_unconditional: bool = False,
        ):
            if not hw or not hw.active or qty <= 0:
                return
            if not getattr(hw, 'is_warehouse_item', True):
                return
            # Фильтрация по применимости к типу, семейству и модели двери
            if group and group.product:
                prod = group.product
                fam = getattr(prod, 'product_family', None)
                prod_type_id = getattr(prod, 'product_type_id', None) or getattr(fam, 'product_type_id', None)
                prod_fam_id = getattr(prod, 'product_family_id', None)
                prod_model_id = getattr(prod, 'product_model_id', None) or getattr(prod, 'model_id', None)

                allowed_types = {t.id for t in hw.product_types.all()}
                if allowed_types and prod_type_id not in allowed_types:
                    return

                allowed_families = {f.id for f in hw.product_families.all()}
                if allowed_families and prod_fam_id not in allowed_families:
                    return

                allowed_models = {m.id for m in hw.product_models.all()}
                if allowed_models and prod_model_id not in allowed_models:
                    return

            if visited is None:
                visited = set()
            if hw.id in visited:
                return
            visited.add(hw.id)

            rule = hw.rule_tag or Hardware.RuleTag.STANDARD
            # Если позиция пришла в OTHER (например, из bom.additional), но у неё есть явная роль (HINGE/LOCK/HANDLE)
            if category == OrderWarehouseItem.Category.OTHER and getattr(hw, 'role', None):
                role_to_cat = {
                    'HINGE': OrderWarehouseItem.Category.HINGES,
                    'LOCK': OrderWarehouseItem.Category.LOCKS,
                    'CYLINDER': OrderWarehouseItem.Category.LOCKS,
                    'HANDLE': OrderWarehouseItem.Category.HANDLES,
                }
                category = role_to_cat.get(hw.role, category)

            has_frame = group.product.has_frame if (group and group.product) else True
            item_sp = effective_specs.get(item.id) if item is not None else None
            is_double_door = bool(getattr(item_sp, 'is_double_door', False))

            # 0. Виртуальные комплекты (сам комплект в накладную не попадает, выдаются только его components)
            if rule == Hardware.RuleTag.BUNDLE:
                mult = hw.get_numeric_par(1) or 1.0
                for comp in hw.components.filter(active=True):
                    process_hardware(
                        comp, category, qty * mult, group, item, panel_dims,
                        visited.copy(), force_unconditional=True,
                    )
                return

            if rule == Hardware.RuleTag.CONDITIONAL_BUNDLE:
                for comp in hw.components.filter(active=True):
                    process_hardware(
                        comp, category, qty, group, item, panel_dims,
                        visited.copy(), force_unconditional=False,
                    )
                return

            # 1. Фильтрация по покраске и наличию коробки
            if not force_unconditional:
                if rule == Hardware.RuleTag.ONLY_IF_HAS_FRAME:
                    if not has_frame:
                        for comp in hw.components.filter(active=True):
                            process_hardware(comp, category, qty, group, item, panel_dims, visited.copy())
                        return

                if rule == Hardware.RuleTag.ONLY_IF_PANEL_PAINTED:
                    if group.panel_paint_option == OrderItemsGroup.PaintOption.NO_PAINT:
                        for comp in hw.components.filter(active=True):
                            process_hardware(comp, category, qty, group, item, panel_dims, visited.copy())
                        return

                if rule == Hardware.RuleTag.ONLY_IF_FRAME_PAINTED:
                    if not has_frame or group.frame_paint_option == OrderItemsGroup.PaintOption.NO_PAINT:
                        for comp in hw.components.filter(active=True):
                            process_hardware(comp, category, qty, group, item, panel_dims, visited.copy())
                        return

            c_name = (hw.common_name or '').strip()
            num_par1 = hw.get_numeric_par(1)
            mode_key = '' if num_par1 is not None else (hw.par1_value or '').strip().upper()

            # 2. Подбор по ширине или высоте полотна через par1_value
            if rule in (Hardware.RuleTag.MATCH_LEAF_WIDTH, Hardware.RuleTag.MATCH_LEAF_HEIGHT) and item is not None:
                size_pool = sized_variants_map.get(c_name, [])
                dims_to_check = panel_dims if panel_dims else [{'width': item.width, 'height': item.height}]

                # Проверяем наличие фальца (из spec.edge_shape или напрямую из PerimeterRoutingFile)
                item_sp = effective_specs.get(item.id)
                if item_sp is not None:
                    has_rebate = bool(getattr(item_sp, 'edge_shape', False))
                else:
                    from apps.engineering.models import PerimeterRoutingFile
                    fam = getattr(group.product, 'product_family', None) if group.product else None
                    routing_obj = PerimeterRoutingFile.objects.filter(doors=fam).first() if fam else None
                    has_rebate = bool(routing_obj and routing_obj.edge_shape)

                if size_pool:
                    for idx_dim, dim in enumerate(dims_to_check):
                        raw_target = dim.get('width') if rule == Hardware.RuleTag.MATCH_LEAF_WIDTH else dim.get(
                            'height')
                        if raw_target is None:
                            continue

                        target_dim = float(raw_target)
                        if rule == Hardware.RuleTag.MATCH_LEAF_WIDTH:
                            is_passive_leaf = (idx_dim > 0) or (dim.get('leaf_role') == 'passive')
                            if is_passive_leaf:
                                rebate_deduction = 0.0 if has_rebate else 1.0
                            else:
                                rebate_deduction = 2.0 if has_rebate else 0.0

                            cut_dim = round(target_dim - rebate_deduction - 0.2, 2)
                            dim_label = 'מידת חיתוך'
                        else:
                            cut_dim = round(target_dim, 2)
                            dim_label = 'גובה כנף'

                        suitable = [(sz, h) for sz, h in size_pool if sz >= cut_dim]
                        is_oversize = not bool(suitable)
                        chosen_size = suitable[0][0] if suitable else size_pool[-1][0]

                        same_size_items = [h for sz, h in size_pool if sz == chosen_size]
                        has_color_choices = len({h.color_id for h in same_size_items if h.color_id}) > 1

                        # Группируем по категории и размеру заготовки (без cut_dim в ключе!)
                        key = (category, f"sized_{c_name}_{chosen_size}")
                        entry = aggregated[key]
                        entry['category'] = category
                        entry['common_name'] = c_name
                        entry['qty'] += qty

                        dim_entry = f"{'חריג! ' if is_oversize else ''}{cls._fmt_num(cut_dim)}"
                        # Добавляем размер пиления с учётом количества (если qty > 1)
                        for _ in range(int(round(qty))):
                            entry['cut_dims'].append((cut_dim, dim_entry))

                        if has_color_choices:
                            entry['name'] = f"{c_name} ({cls._fmt_num(chosen_size)})"
                            entry['is_color_required'] = True
                        else:
                            chosen_hw = same_size_items[0]
                            entry['hardware'] = chosen_hw
                            entry['name'] = chosen_hw.name
                            entry['sku'] = chosen_hw.sku or ''

                    for comp in hw.components.filter(active=True):
                        process_hardware(comp, category, qty, group, item, panel_dims, visited.copy())
                    return

            # 3. Расчёт погонажа уплотнителя по периметру (в метрах)
            if rule in (Hardware.RuleTag.PERIMETER_METERS,
                        Hardware.RuleTag.HEIGHT_METERS) and item is not None:
                if rule == Hardware.RuleTag.HEIGHT_METERS and not is_double_door:
                    return

                raw_w = float(item.width or 80)
                raw_h = float(item.height or 210)
                is_half = (rule == Hardware.RuleTag.HEIGHT_METERS)

                meters = ((raw_h / 100.0) * qty) if is_half else ((((2 * raw_h) + raw_w) / 100.0) * qty)

                has_color_choices = bool(c_name and len(color_variants_map.get((c_name, None, mode_key), [])) > 1)
                prefix_key = 'half_perim' if is_half else 'perim'
                key = (category, f"{prefix_key}_{c_name}" if has_color_choices else f"{prefix_key}_hw_{hw.id}")
                entry = aggregated[key]
                entry['category'] = category
                entry['common_name'] = c_name
                entry['name'] = c_name if has_color_choices else hw.name
                entry['is_color_required'] = has_color_choices
                if is_half:
                    entry['is_half_meter'] = True
                else:
                    entry['is_perimeter'] = True
                if not has_color_choices:
                    entry['hardware'] = hw
                    entry['sku'] = hw.sku or ''
                entry['qty'] += meters
                return

            # 4. Стандартная позиция
            has_color_choices = bool(c_name and len(color_variants_map.get((c_name, None, mode_key), [])) > 1)
            slot_key = f"{c_name}_{mode_key}" if (has_color_choices and mode_key) else (
                c_name if has_color_choices else f"hw_{hw.id}"
            )
            key = (category, slot_key)

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
                process_hardware(comp, category, qty, group, item, panel_dims, visited.copy())

        # Проход по каждой двери с использованием рассчитанного OrderSpec
        for item in rich_items:
            group = item.group
            sp = effective_specs.get(item.id)
            has_door = sp.has_door if sp else (group.product.has_door if group.product else True)
            panel_dims = sp.panel_dimensions if (sp and sp.panel_dimensions) else None

            # Извлекаем главные позиции слотов из bom_items пайплайна
            eff_handle_hw = None
            eff_lock_hw = None
            eff_cyl_hw = None
            eff_hinge_hw = None

            if sp and sp.bom_items:
                for b_it in sp.bom_items:
                    if b_it.type != 'hardware' or not b_it.item_id:
                        continue
                    tag_low = (b_it.tag or '').lower()
                    if tag_low == 'handle' and eff_handle_hw is None:
                        eff_handle_hw = hw_cache.get(b_it.item_id) or Hardware.objects.filter(pk=b_it.item_id).first()
                    elif tag_low == 'lock' and eff_lock_hw is None:
                        eff_lock_hw = hw_cache.get(b_it.item_id) or Hardware.objects.filter(pk=b_it.item_id).first()
                    elif tag_low == 'cylinder' and eff_cyl_hw is None:
                        eff_cyl_hw = hw_cache.get(b_it.item_id) or Hardware.objects.filter(pk=b_it.item_id).first()
                    elif tag_low in ('hinge', 'hinges') and eff_hinge_hw is None:
                        eff_hinge_hw = hw_cache.get(b_it.item_id) or Hardware.objects.filter(pk=b_it.item_id).first()

            # 1. Ручки (из эффективного BOM пайплайна — с учётом подмены WC <-> CYLINDER)
            has_handle = sp.has_handle if sp is not None else getattr(group, 'has_handle', True)
            if has_door and has_handle:
                target_handle = eff_handle_hw if sp is not None else order.handle
                if target_handle:
                    process_hardware(target_handle, OrderWarehouseItem.Category.HANDLES, 1, group, item, panel_dims)

            # Fallback на базовый BOM только если пайплайн не вернул результат (sp is None)
            if sp is None and group.product and group.product.effective_bom:
                eff_lock_hw = eff_lock_hw or group.product.effective_bom.lock
                eff_hinge_hw = eff_hinge_hw or group.product.effective_bom.hinges

            # 2. Эффективный замок и цилиндр
            if eff_lock_hw:
                process_hardware(eff_lock_hw, OrderWarehouseItem.Category.LOCKS, 1, group, item, panel_dims)
            if eff_cyl_hw:
                process_hardware(eff_cyl_hw, OrderWarehouseItem.Category.LOCKS, 1, group, item, panel_dims)

            # 3. Эффективные петли (на одном уровне с блоком 2, НЕ внутри if eff_cyl_hw!)
            if eff_hinge_hw:
                if sp and sp.hinge_heights:
                    hinges_per_door = len([h for h in sp.hinge_heights if h is not None]) or 3
                else:
                    custom_h = [
                        getattr(item, f'custom_hinge{i}', None)
                        for i in range(1, 6)
                        if getattr(item, f'custom_hinge{i}', None) is not None
                    ]
                    hinges_per_door = len(custom_h) if custom_h else 3

                if sp and getattr(sp, 'is_double_door', False):
                    hinges_per_door *= 2

                process_hardware(
                    eff_hinge_hw, OrderWarehouseItem.Category.HINGES,
                    hinges_per_door, group, item, panel_dims,
                )

            # 4. Доп. аксессуары и уплотнители из BOM
            bom = group.product.effective_bom if group.product else None
            if bom and hasattr(bom, 'additional'):
                for add_item in bom.additional.all():
                    if isinstance(add_item, Hardware):
                        process_hardware(add_item, OrderWarehouseItem.Category.OTHER, 1, group, item, panel_dims)
                    else:
                        m_key = (OrderWarehouseItem.Category.OTHER, f"mat_{add_item.id}")
                        aggregated[m_key]['category'] = OrderWarehouseItem.Category.OTHER
                        aggregated[m_key]['common_name'] = getattr(add_item, 'common_name', '') or ''
                        aggregated[m_key]['name'] = add_item.name
                        aggregated[m_key]['sku'] = getattr(add_item, 'sku', '') or ''
                        aggregated[m_key]['qty'] += 1

            # 5. Дополнительные кастомизаторы группы (исключая основные слоты, уже учтённые выше)
            for gc in group.customizers.all():
                cust = gc.customizer
                tag_low = (cust.tag or '').lower()

                if any(k in tag_low for k in ('hinge', 'lock', 'cylinder', 'handle')):
                    continue

                target_cat = cls._guess_category_by_tag(cust.tag)

                if cust.hardware:
                    process_hardware(cust.hardware, target_cat, 1, group, item, panel_dims)

                for i in range(1, 6):
                    raw_val = getattr(gc, f'par{i}', '') or ''
                    if raw_val.upper().startswith('SKU='):
                        sku_code = raw_val.split('=', 1)[1].strip()
                        hw_obj = Hardware.objects.filter(sku=sku_code, active=True).first()
                        if hw_obj:
                            process_hardware(hw_obj, target_cat, 1, group, item, panel_dims)

        items_to_create = []
        for idx, (_, data) in enumerate(aggregated.items()):
            hw_obj = data['hardware']
            color_str = hw_obj.color.name if (hw_obj and hw_obj.color) else ''
            final_qty = data['qty']
            comment_str = data['comment']

            if data['is_perimeter']:
                final_qty = math.ceil(round(final_qty * (1.0 + cls.PERIMETER_RESERVE_RATIO), 4))
                if not comment_str:
                    comment_str = ''
            elif data['is_half_meter']:
                # 2.4 * 2 = 4.8 -> math.ceil(4.8) = 5 -> 5 / 2.0 = 2.5
                final_qty = math.ceil(final_qty * 2.0) / 2.0
                if float(final_qty).is_integer():
                    final_qty = int(final_qty)
                if not comment_str:
                    comment_str = ''

            if data['cut_dims']:
                from collections import Counter

                total_cuts = len(data['cut_dims'])
                counts = Counter(data['cut_dims'])
                # Сортируем уникальные пары (числовой_размер, текстовая_метка) от меньшего к большему
                formatted_parts = []
                for (_, label), cnt in sorted(counts.items(), key=lambda x: x[0][0]):
                    if cnt > 1:
                        formatted_parts.append(f"{label} [{cnt} יח']")
                    else:
                        formatted_parts.append(label)

                prefix = 'מידות חיתוך' if total_cuts > 1 else 'מידת חיתוך'
                comment_str = f"{prefix}: {' ; '.join(formatted_parts)}"

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
            mode_key = '' if len_key is not None else (h.par1_value or '').strip().upper()
            mapping[(h.common_name.strip(), len_key, mode_key)].append(h)
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
                item_mode = (
                    '' if (not item.hardware or item_len is not None)
                    else (item.hardware.par1_value or '').strip().upper()
                )
                matched_variants = variants_map.get((item.common_name, item_len, item_mode), [])
                if not matched_variants and item_len is None:
                    for (c_name_key, _, m_key), hw_list in variants_map.items():
                        if c_name_key == item.common_name and (not item_mode or m_key == item_mode):
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

        for cat in cls.CATEGORY_ORDER:
            sections[cat].sort(
                key=lambda r: (
                    not bool((r['obj'].sku or '').strip()),
                    (r['obj'].sku or '').strip().lower(),
                    (r['obj'].name or '').strip().lower(),
                )
            )

        return [
            {
                'code': cat,
                'label': OrderWarehouseItem.Category(cat).label,
                'rows': sections[cat],
            }
            for cat in cls.CATEGORY_ORDER
        ], sorted(all_colors)
