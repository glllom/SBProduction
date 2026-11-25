from django.urls import path

from . import views, cnc_views

app_name = 'production'

urlpatterns = [
    # Единая точка запуска волны/батча/фазы в производство
    path('order/<int:pk>/transfer-to-production/', views.order_transfer_to_production,
         name='order-transfer-to-production'),

    # Жизненный цикл и завершение этапов
    path('order/<int:pk>/complete-phase1/', views.order_complete_phase1, name='order-complete-phase1'),
    path('order/<int:pk>/complete-production/', views.order_complete_production, name='order-complete-production'),
    path('order/<int:pk>/group/<int:group_id>/toggle-state/', views.group_toggle_state, name='group-toggle-state'),
    path('order/<int:pk>/check-validation/', views.order_check_validation, name='order-check-validation'),
    path('orders/<int:order_id>/station-note/', views.save_station_note, name='save-station-note'),

    # Отчеты и документы
    path('order/<int:pk>/station-report/', views.station_report, name='station-report'),
    path('order/<int:pk>/split-measurer-report/', views.split_measurer_report, name='split-measurer-report'),
    path('orders/<int:pk>/reports/sketches/', views.order_sketches_report, name='order-sketches-report'),
    path('order/<int:pk>/compare-snapshots/', views.order_compare_snapshots, name='order-compare-snapshots'),

    # ЧПУ, файлы и выгрузки
    path('sync-usb/', views.sync_usb_view, name='sync_usb'),
    path('order/<int:pk>/production-data/', views.order_production_data, name='order-production-data'),
    path('api/bartender/confirm-print/', views.bartender_confirm_print, name='bartender-confirm-print'),
    path('order/<int:pk>/warehouse-setup/', views.order_warehouse_setup, name='order-warehouse-setup'),

    # Dev Tools / Режим бога (инспекция и принудительный пересчет батча)
    path('order/<int:pk>/spec-json/', views.spec_json_preview, name='spec-json-preview'),
    path('order/<int:pk>/rebuild-batch-spec/', views.order_dev_force_rebuild_spec, name='order-rebuild-batch-spec'),

    path('stations/<str:station_code>/sheet/', views.station_backlog_sheet_print, name='station-sheet-print'),
    path('stations/<str:station_code>/control/', views.station_control_view, name='station-control'),

    path('tracking/', views.StationTrackingDashboardView.as_view(), name='station_tracking_dashboard'),
    path('tracking/toggle-batch/', views.ToggleBatchStationAjaxView.as_view(), name='toggle_batch_station_ajax'),
    path('tracking/print-all/', views.StationsBatchDailyPrintView.as_view(), name='tracking_print_all'),

    path('tracking/orders/', views.order_tracking_list, name='order-tracking-list'),
    path('tracking/orders/search-api/', views.order_tracking_search_ajax, name='order-tracking-search-api'),
    path('tracking/orders/<int:pk>/', views.order_tracking_detail, name='order-tracking-detail'),
    path('tracking/orders/<int:pk>/action/', views.order_tracking_station_action, name='order-tracking-action'),

    path('cnc-library/', cnc_views.cnc_library_builder_view, name='cnc-library-builder'),

]
