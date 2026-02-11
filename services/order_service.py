from production.models import DBOrder, DBComponent
from production.mappers import map_db_order_to_domain, map_db_component_to_domain
from core.calculator import calculate

def process_order_calculation(order_number):
    """
    Координирует процесс расчета заказа:
    1. Загрузка из БД
    2. Маппинг в доменные объекты
    3. Выполнение расчетов
    4. Сбор результатов
    """
    # 1. Получаем заказ из БД
    try:
        db_order = DBOrder.objects.prefetch_related('items').get(order_number=order_number)
    except DBOrder.DoesNotExist:
        return {"error": f"Order {order_number} not found"}

    # 2. Маппим в домен (Clean Architecture)

    domain_order = map_db_order_to_domain(db_order)
    components = [map_db_component_to_domain(component) for component in DBComponent.objects.all()]

    # 3. Выполняем расчеты для каждой позиции
    results = []
    for item in domain_order.items:
        calculate(item, components)

        bom_summary = {}
        for entry in item.bom:
            sku = entry['component'].name +'     '+ entry['component'].sku
            qty = entry['qty'] if entry['qty'] is not None else 0
            bom_summary[sku] = bom_summary.get(sku, 0) + qty

        results.append({
            "door number": item.num_in_order,
            "product": str(item.product.sku),
            "dimensions": f"{item.width}x{item.height} {item.wall_thickness}{item.direction} ({item.opening})",
            "panel/s": [item.panel_dimensions, item.second_panel_dimensions if item.second_panel_dimensions else None],
            "bom": bom_summary,
        })
    return {
        "order_number": order_number,
        "customer": domain_order.customer,
        "items": results,
        "status": "calculated"
    }
