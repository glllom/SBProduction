from production.models import Order


def load_order(order_num):
    current_order = Order.objects.get(order_number=order_num)
    print(current_order)
    return None