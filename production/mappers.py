from core.models import Order, ItemInOrder, Product, Component
from .models import DBOrder, DBOrderItem, DBProductModel, DBComponent


def map_db_component_to_domain(db_component: DBComponent) -> Component:
    return Component(name=db_component.name,
                     width=db_component.width,
                     length=db_component.length,
                     thickness=db_component.thickness,
                     sku=db_component.sku,
                     group=db_component.group,
                     component_type=db_component.component_type,
                     color=db_component.color, )


def map_db_product_to_domain(db_product: DBProductModel) -> Product:
    bom = [map_db_component_to_domain(component) for component in db_product.bom.all()]
    return Product(
        sku=db_product.sku,
        description=db_product.description,
        panel_reduction_width=db_product.panel_reduction_width,
        panel_reduction_height=db_product.panel_reduction_height,
        double_door_gap=db_product.double_door_gap,
        bom=bom)


def map_db_order_to_domain(db_order: DBOrder) -> Order:
    """
    Преобразует модель БД DBOrder в доменный объект Order.
    """
    # В текущей версии DBOrder только order_number. 
    # Остальные данные можно добавить в БД позже или оставить пустыми.
    domain_order = Order(
        customer=db_order.customer,
        date_to_complete=None  # Поле отсутствует в DBOrder
    )

    # Добавляем позиции заказа
    for db_item in db_order.items.all():
        domain_item = map_db_item_to_domain(db_item)
        domain_order.items.append(domain_item)

    return domain_order


def map_db_item_to_domain(db_item: DBOrderItem) -> ItemInOrder:
    """
    Преобразует модель БД DBOrderItem в доменный объект ItemInOrder.
    """
    domain_item = ItemInOrder(
        product=map_db_product_to_domain(db_item.product_model),
        width=db_item.width,
        height=db_item.height,
        direction=db_item.direction,
        undercut=db_item.undercut,
        wall_thickness=db_item.wall,  # Поле в БД называется wall
        opening=db_item.opening,
    )

    # Можно также смапить кастомайзеры, если они нужны в расчетах
    # for customizer in db_item.customizers.all():
    #     domain_item.customizers[customizer.customizer.name] = customizer.value

    return domain_item
