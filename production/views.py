from django.shortcuts import render

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from production.models import Order
from calculator import calculate

@api_view(['GET'])
def run_order_mock(request, order_num):
    """
    Mock endpoint for running an order.
    Returns a simple JSON response for testing.
    """
    order = Order.objects.get(order_number=order_num)
    for item in order.items.all():
        # calculate(item)
        pass
    data = {
        "status": "success",
        "order_number": order_num,
        "message": f"Order {order_num} has been received by the mock system",
        "stage": "development_mock"
    }
    return Response(data, status=status.HTTP_200_OK)
