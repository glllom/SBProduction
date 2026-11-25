from decimal import Decimal, InvalidOperation

from django.db import migrations

CONSUMPTION_FIELDS = [
    'covering_consumption',
    'base_consumption',
    'filling_consumption',
    'panel_frame_consumption',
    'casing_consumption',
    'frame_consumption',
    'profile1_consumption',
    'profile2_consumption',
    'profile3_consumption',
    'other1_consumption',
    'other2_consumption',
    'other3_consumption',
    'other4_consumption',
    'other5_consumption',
]


def migrate_engineering_and_catalog_data(apps, schema_editor):
    ProductFamily = apps.get_model('catalog', 'ProductFamily')
    ProductModel = apps.get_model('catalog', 'ProductModel')
    Customizer = apps.get_model('catalog', 'Customizer')
    BOM = apps.get_model('engineering', 'BOM')
    ProductEngineeringRule = apps.get_model('engineering', 'ProductEngineeringRule')
    Order = apps.get_model('orders', 'Order')
    OrderSpecificationSnapshot = apps.get_model('production', 'OrderSpecificationSnapshot')

    # 1. ProductFamily -> ProductEngineeringRule (положительные значения в см)
    for pf in ProductFamily.objects.all():
        rules_data = {
            'thickness': abs(float(pf.thickness or 0.0)),
            'frame_inner_height_reduction': abs(float(pf.frame_inner_height_reduction or 0.0)),
            'frame_inner_width_reduction': abs(float(pf.frame_inner_width_reduction or 0.0)),
            'leaf_top_clearance': abs(float(pf.leaf_top_clearance or 0.0)),
            'leaf_bottom_clearance': abs(float(pf.leaf_bottom_clearance or 0.0)),
            'leaf_side_clearance': abs(float(pf.leaf_side_clearance or 0.0)),
            'double_leaf_overlap': float(pf.double_leaf_overlap or 0.0),
        }
        rule_obj, created = ProductEngineeringRule.objects.get_or_create(
            product_family=pf,
            defaults={'rules': rules_data},
        )
        if not created:
            merged = dict(rules_data)
            merged.update(rule_obj.rules or {})
            rule_obj.rules = merged
            rule_obj.save(update_fields=['rules'])

    # 2. BOM -> cut_coefficients, required_customizers, нормализация *_consumption
    for bom in BOM.objects.select_related('product').prefetch_related('required_customizers').all():
        if isinstance(bom.cut_coefficients, dict) and bom.cut_coefficients:
            rule_obj, created = ProductEngineeringRule.objects.get_or_create(
                product_model=bom.product,
                defaults={'rules': {'cut_coefficients': bom.cut_coefficients}},
            )
            if not created:
                merged = dict(rule_obj.rules or {})
                merged.setdefault('cut_coefficients', bom.cut_coefficients)
                rule_obj.rules = merged
                rule_obj.save(update_fields=['rules'])

        bom_req_ids = list(bom.required_customizers.filter(active=True).values_list('id', flat=True))
        if bom_req_ids:
            bom.product.required_customizers.add(*bom_req_ids)

        changed = False
        for fname in CONSUMPTION_FIELDS:
            raw = str(getattr(bom, fname, '') or '').strip().replace(',', '.')
            try:
                val = Decimal(raw) if raw else Decimal('1.00')
            except InvalidOperation:
                val = Decimal('1.00')
            normalized = str(val.quantize(Decimal('0.01')))
            if getattr(bom, fname) != normalized:
                setattr(bom, fname, normalized)
                changed = True
        if changed:
            bom.save(update_fields=CONSUMPTION_FIELDS)

    # 3. Customizer(is_required=True) -> ProductModel.required_customizers
    req_customizers = list(
        Customizer.objects.filter(active=True, hidden_in_sales=False, is_required=True)
        .prefetch_related('product_models', 'product_families', 'product_types')
    )
    if req_customizers:
        all_products = list(ProductModel.objects.select_related('product_family').all())
        for cust in req_customizers:
            m_ids = set(cust.product_models.values_list('id', flat=True))
            f_ids = set(cust.product_families.values_list('id', flat=True))
            t_ids = set(cust.product_types.values_list('id', flat=True))
            is_global = not (m_ids or f_ids or t_ids)

            for prod in all_products:
                matches = (
                        is_global
                        or prod.id in m_ids
                        or (prod.parent_model_id and prod.parent_model_id in m_ids)
                        or prod.product_family_id in f_ids
                        or (prod.product_family and prod.product_family.product_type_id in t_ids)
                )
                if matches:
                    prod.required_customizers.add(cust)

    # 4. Перестраховка: переносим phase1/phase2_spec_cache в OrderSpecificationSnapshot, если снимка ещё нет
    for order in Order.objects.all():
        for field_name, snap_type in (
                ('phase1_spec_cache', 'PHASE1'),
                ('phase2_spec_cache', 'PHASE2'),
        ):
            cache_data = getattr(order, field_name, None)
            if isinstance(cache_data, dict) and cache_data.get('batches'):
                latest = (
                    OrderSpecificationSnapshot.objects.filter(order=order, snapshot_type=snap_type)
                    .order_by('-created_at', '-id')
                    .first()
                )
                if not latest or latest.spec_data != cache_data:
                    OrderSpecificationSnapshot.objects.create(
                        order=order,
                        snapshot_type=snap_type,
                        spec_data=cache_data,
                    )


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0055_machiningfeature_hardware_machining_feature'),
        ('engineering', '0002_move_engineering_models'),
        ('orders', '0052_orderitem_width_bottom_alter_orderitem_height_and_more'),
        ('production', '0044_move_engineering_models'),
    ]

    operations = [
        migrations.RunPython(migrate_engineering_and_catalog_data, migrations.RunPython.noop),
    ]
