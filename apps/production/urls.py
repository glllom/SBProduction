from django.urls import path

from . import views

app_name = 'production'

urlpatterns = [
    path('order/<int:pk>/transfer-to-production/', views.order_transfer_to_production,
         name='order-transfer-to-production'),
    path('order/<int:pk>/check-validation/', views.order_check_validation, name='order-check-validation'),
    path('order/<int:pk>/transfer-to-phase1/', views.order_transfer_to_phase1, name='order-transfer-to-phase1'),
    path('order/<int:pk>/complete-phase1/', views.order_complete_phase1, name='order-complete-phase1'),
    path('order/<int:pk>/complete-production/', views.order_complete_production, name='order-complete-production'),
    path('order/<int:pk>/production-data/', views.order_production_data, name='order-production-data'),
    path('order/<int:pk>/station-report/', views.station_report, name='station-report'),
    path('order/<int:pk>/spec-json/', views.spec_json_preview, name='spec-json-preview'),
]
