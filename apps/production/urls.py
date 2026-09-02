from django.urls import path
from . import views

app_name = 'production'

urlpatterns = [
    path('order/<int:pk>/transfer-to-production/', views.order_transfer_to_production, name='order-transfer-to-production'),
    path('order/<int:pk>/check-validation/', views.order_check_validation, name='order-check-validation'),
    path('order/<int:pk>/transfer-to-phase1/', views.order_transfer_to_phase1, name='order-transfer-to-phase1'),
    path('order/<int:pk>/complete-phase1/', views.order_complete_phase1, name='order-complete-phase1'),
    path('order/<int:pk>/production-data/', views.order_production_data, name='order-production-data'),
    path('order/<int:pk>/production-report/', views.order_production_report, name='order-production-report'),
    path('order/<int:pk>/alum-frames-report/', views.order_production_report, name='alum-frames-report'),
]
