from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'catalog'

router = DefaultRouter()
router.register(r'series', views.SeriesViewSet, basename='series')
router.register(r'fronts', views.FrontViewSet, basename='fronts')
router.register(r'frame-colors', views.FrameColorViewSet, basename='frame-colors')
router.register(r'frame_colors', views.FrameColorViewSet, basename='frame_colors')
router.register(r'families', views.ProductFamilyViewSet, basename='families')
router.register(r'models', views.ProductModelViewSet, basename='models')
router.register(r'customizers', views.CustomizerViewSet, basename='customizers')

urlpatterns = [
    path('api/', include(router.urls)),
    path('family/', views.FamilyListView.as_view(), name='family-list'),
    path('series/', views.SeriesListView.as_view(), name='series-list'),
    path('model/', views.ModelListView.as_view(), name='model-list'),
    path('customizer/', views.CustomizerListView.as_view(), name='customizer-list'),
]
