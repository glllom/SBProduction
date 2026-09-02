from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'group-customizers', views.OrderItemsGroupCustomizerViewSet, basename='group-customizers')
router.register(r'specifications', views.GroupSpecificationViewSet, basename='specifications')

urlpatterns = [
    path('api/', include(router.urls)),
    path('', views.OrderListView.as_view(), name='order-list'),
    path('add/', views.OrderCreateView.as_view(), name='order-add'),
    path('<int:pk>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('<int:pk>/measurements/', views.OrderMeasurementsView.as_view(), name='order-measurements'),
    path('<int:pk>/edit-header/', views.OrderHeaderUpdateView.as_view(), name='order-edit-header'),
    path('<int:pk>/reset-to-new/', views.order_reset_to_new, name='order-reset-to-new'),
    path('<int:pk>/delete/', views.OrderDeleteView.as_view(), name='order-delete'),

    # Order Items Groups
    path('<int:order_pk>/groups/add/', views.OrderItemsGroupCreateView.as_view(), name='group-add'),
    path('groups/<int:pk>/edit/', views.OrderItemsGroupUpdateView.as_view(), name='group-edit'),
    path('groups/<int:pk>/delete/', views.OrderItemsGroupDeleteView.as_view(), name='group-delete'),
    path('groups/<int:pk>/duplicate/', views.group_duplicate, name='group-duplicate'),
    path('groups/<int:pk>/save-specification/', views.save_group_specification, name='group-save-specification'),
    path('groups/<int:pk>/apply-specification/<int:spec_pk>/', views.apply_group_specification,
         name='group-apply-specification'),
    path('<int:order_pk>/groups/create-from-specification/<int:spec_pk>/', views.create_group_from_specification,
         name='group-create-from-specification'),
    path('specifications/<int:pk>/delete/', views.delete_group_specification, name='specification-delete'),

    # Order Items
    path('items/<int:pk>/edit/', views.OrderItemUpdateView.as_view(), name='order-item-edit'),
    path('items/<int:pk>/update-measurements/', views.update_item_measurements, name='order-item-update-measurements'),
    path('items/<int:pk>/duplicate-measurements/', views.duplicate_item_measurements,
         name='order-item-duplicate-measurements'),
]
