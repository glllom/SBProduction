
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from django.templatetags.static import static
from apps.orders.views import DashboardView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('favicon.ico', RedirectView.as_view(url=static('logo.svg'), permanent=True)),
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('orders/', include('apps.orders.urls')),
    path('catalog/', include('apps.catalog.urls', namespace='catalog')),
    path('', DashboardView.as_view(), name='dashboard'),
]
