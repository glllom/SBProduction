
from django.contrib import admin
from django.urls import path

from production.views import run_order_mock
urlpatterns = [
    path('admin/', admin.site.urls),
    path('run-order/<str:order_num>/',run_order_mock, name='run-order'),
]
