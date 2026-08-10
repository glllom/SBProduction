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
    path('<int:pk>/measurements/', views.OrderMeasurementsView.as_view(), name='order-measurements'),
    path('<int:pk>/edit-header/', views.OrderHeaderUpdateView.as_view(), name='order-edit-header'),
    path('<int:pk>/transfer-to-production/', views.order_transfer_to_production, name='order-transfer-to-production'),
    path('<int:pk>/transfer-to-phase1/', views.order_transfer_to_phase1, name='order-transfer-to-phase1'),
    path('<int:pk>/production-data/', views.order_production_data, name='order-production-data'),
    path('<int:pk>/production-report/', views.order_production_report, name='order-production-report'),
    path('<int:pk>/delete/', views.OrderDeleteView.as_view(), name='order-delete'),
    
    # Order Items Groups
    path('<int:order_pk>/groups/add/', views.OrderItemsGroupCreateView.as_view(), name='group-add'),
    path('groups/<int:pk>/edit/', views.OrderItemsGroupUpdateView.as_view(), name='group-edit'),
    path('groups/<int:pk>/delete/', views.OrderItemsGroupDeleteView.as_view(), name='group-delete'),
    
    # Order Items
    path('items/<int:pk>/edit/', views.OrderItemUpdateView.as_view(), name='order-item-edit'),
    path('items/<int:pk>/update-measurements/', views.update_item_measurements, name='order-item-update-measurements'),
    path('items/<int:pk>/duplicate-measurements/', views.duplicate_item_measurements, name='order-item-duplicate-measurements'),
]
