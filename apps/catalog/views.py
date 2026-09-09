from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.views.generic import ListView
from rest_framework import viewsets, permissions

from .models import ProductFamily, Series, ProductModel, Customizer, Front, Color, Material
from .serializers import (
    SeriesSerializer,
    FrontSerializer,
    FrameColorSerializer,
    MaterialSerializer,
    ProductFamilySerializer,
    ProductModelSerializer,
    CustomizerSerializer
)


class SeriesViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Series.objects.filter(active=True).order_by('name')
    serializer_class = SeriesSerializer
    permission_classes = [permissions.IsAuthenticated]


class FrontViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Front.objects.filter(active=True)
    serializer_class = FrontSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        series_id = self.request.query_params.get('series')
        if series_id:
            queryset = queryset.filter(series_id=series_id)
        return queryset.order_by('name')


class FrameColorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Material.objects.all()
    serializer_class = MaterialSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        product_id = self.request.query_params.get('product') or self.request.query_params.get('product_id')
        series_id = self.request.query_params.get('series')
        family_id = self.request.query_params.get('family')

        if product_id:
            try:
                product = ProductModel.objects.get(id=product_id)
                return product.available_frames
            except ProductModel.DoesNotExist:
                return Material.objects.none()

        if series_id and family_id:
            try:
                product = ProductModel.objects.get(series_id=series_id, product_family_id=family_id)
                return product.available_frames
            except (ProductModel.DoesNotExist, ProductModel.MultipleObjectsReturned):
                pass

        if series_id:
            try:
                series = Series.objects.get(id=series_id)
                return series.available_frames
            except Series.DoesNotExist:
                return Material.objects.none()

        return Material.objects.none()


class ProductFamilyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductFamily.objects.all()
    serializer_class = ProductFamilySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        type_id = self.request.query_params.get('type')
        if type_id:
            queryset = queryset.filter(product_type_id=type_id)
        return queryset.order_by('name')


class ProductModelViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductModel.objects.filter(active=True)
    serializer_class = ProductModelSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        series_id = self.request.query_params.get('series')
        family_id = self.request.query_params.get('family')
        if series_id:
            queryset = queryset.filter(series_id=series_id)
        if family_id:
            queryset = queryset.filter(product_family_id=family_id)
        return queryset.order_by('name')


class CustomizerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Customizer.objects.filter(active=True)
    serializer_class = CustomizerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search')
        product_model = self.request.query_params.get('product_model')
        product_family = self.request.query_params.get('product_family')
        product_type = self.request.query_params.get('product_type')

        # Filter by hierarchy if provided
        if product_model or product_family or product_type:
            hierarchy_filter = models.Q(
                product_models__isnull=True,
                product_families__isnull=True,
                product_types__isnull=True
            )
            if product_model:
                try:
                    pm = ProductModel.objects.get(id=product_model)
                    hierarchy_filter |= models.Q(product_models=pm)
                    hierarchy_filter |= models.Q(product_families=pm.product_family)
                    hierarchy_filter |= models.Q(product_types=pm.product_family.product_type)
                except ProductModel.DoesNotExist:
                    pass
            elif product_family:
                hierarchy_filter |= models.Q(product_families_id=product_family)
                try:
                    pf = ProductFamily.objects.get(id=product_family)
                    hierarchy_filter |= models.Q(product_types=pf.product_type)
                except ProductFamily.DoesNotExist:
                    pass
            elif product_type:
                hierarchy_filter |= models.Q(product_types_id=product_type)
            
            queryset = queryset.filter(hierarchy_filter).distinct()

        if search:
            queryset = queryset.filter(
                models.Q(name__icontains=search) | models.Q(code__icontains=search)
            )
        return queryset.order_by('tag', 'code')


class FamilyListView(LoginRequiredMixin, ListView):
    model = ProductFamily
    template_name = 'catalog/family_list.html'
    context_object_name = 'families'


class SeriesListView(LoginRequiredMixin, ListView):
    model = Series
    template_name = 'catalog/series_list.html'
    context_object_name = 'series'


class ModelListView(LoginRequiredMixin, ListView):
    model = ProductModel
    template_name = 'catalog/model_list.html'
    context_object_name = 'models'


class CustomizerListView(LoginRequiredMixin, ListView):
    model = Customizer
    template_name = 'catalog/customizer_list.html'
    context_object_name = 'customizers'
