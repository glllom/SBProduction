from django.shortcuts import render
from django.views.generic import ListView, CreateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from .models import ProductFamily, Series, ProductModel, Customizer, Front
from rest_framework import viewsets, permissions
from .serializers import SeriesSerializer, FrontSerializer, ProductFamilySerializer, ProductModelSerializer

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

class ProductFamilyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductFamily.objects.all()
    serializer_class = ProductFamilySerializer
    permission_classes = [permissions.IsAuthenticated]

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
