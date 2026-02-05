
from django.contrib import admin
from django.urls import path, include

from production.views import order_list, order_create, order_edit, order_delete, order_item_customizers

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', order_list, name='order-list'),
    path('add-order/', order_create, name='order-add'),
    path('edit-order/<int:pk>/', order_edit, name='order-edit'),
    path('delete-order/<int:pk>/', order_delete, name='order-delete'),
    path('order-item-customizers/<int:item_id>/', order_item_customizers, name='order-item-customizers'),
    path('api/', include('api.urls')),
]
