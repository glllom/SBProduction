from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'group-customizers', views.OrderItemsGroupCustomizerViewSet, basename='group-customizers')

urlpatterns = [
    path('api/', include(router.urls)),
    path('', views.OrderListView.as_view(), name='order-list'),
    path('add/', views.OrderCreateView.as_view(), name='order-add'),
    path('<int:pk>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('<int:pk>/edit-header/', views.OrderHeaderUpdateView.as_view(), name='order-edit-header'),
    path('<int:pk>/delete/', views.OrderDeleteView.as_view(), name='order-delete'),
    
    # Order Items Groups
    path('<int:order_pk>/groups/add/', views.OrderItemsGroupCreateView.as_view(), name='group-add'),
    path('groups/<int:pk>/edit/', views.OrderItemsGroupUpdateView.as_view(), name='group-edit'),
    path('groups/<int:pk>/delete/', views.OrderItemsGroupDeleteView.as_view(), name='group-delete'),
]
