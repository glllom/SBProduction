from django.urls import path
from . import views

urlpatterns = [
    path('', views.OrderListView.as_view(), name='order-list'),
    path('add/', views.OrderCreateView.as_view(), name='order-add'),
    path('<int:pk>/', views.OrderDetailView.as_view(), name='order-detail'),
]
