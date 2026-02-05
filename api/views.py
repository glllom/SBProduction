from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from services.order_service import process_order_calculation

@api_view(['GET'])
def run_order(request, order_num):
    """
    Endpoint for initiating the order calculation.
    Uses a service layer to isolate business logic.
    """
    result = process_order_calculation(order_num)
    
    if "error" in result:
        return Response(result, status=status.HTTP_404_NOT_FOUND)
        
    return Response(result, status=status.HTTP_200_OK)
