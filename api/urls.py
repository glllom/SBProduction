from django.urls import path
from .views import run_order

urlpatterns = [
    path('run-order/<str:order_num>/', run_order, name='run-order'),
]
