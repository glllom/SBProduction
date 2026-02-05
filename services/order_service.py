from production.models import DBOrder
from production.mappers import map_db_order_to_domain
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
    for item in domain_order.items:
        print(item.width, item.height, item.wall_thickness, item.direction, item.opening)

    # 3. Выполняем расчеты для каждой позиции
    results = []
    for item in domain_order.items:
        calculate(item)
        # Здесь можно собирать результаты, например BOM
        results.append({
            "product": str(item.product),
            "bom": item.bom,
            "dimensions": f"{item.width}x{item.height} {item.wall_thickness}{item.direction} ({item.opening})"
        })

    return {
        "order_number": order_number,
        "customer": domain_order.customer,
        "items": results,
        "status": "calculated"
    }
