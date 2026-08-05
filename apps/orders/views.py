from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, CreateView, UpdateView, DetailView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.db.models import Q
from django.http import JsonResponse
from .models import Order, OrderItemsGroup, OrderItem
from .forms import OrderForm
from apps.catalog.models import ProductFamily, Series, Front

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'

class OrderListView(LoginRequiredMixin, ListView):
    model = Order
    template_name = 'orders/order_list.html'
    context_object_name = 'orders'
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(
                Q(order_number__icontains=q) |
                Q(customer__icontains=q)
            )
        return queryset[:10]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        return context

class OrderCreateView(LoginRequiredMixin, CreateView):
    model = Order
    form_class = OrderForm
    template_name = 'orders/order_form.html'

    def get_success_url(self):
        return reverse_lazy('order-detail', kwargs={'pk': self.object.pk})

class OrderDetailView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = 'orders/order_detail.html'
    context_object_name = 'order'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['families'] = ProductFamily.objects.all()
        context['series'] = Series.objects.all()
        return context
