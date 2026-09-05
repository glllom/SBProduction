from functools import wraps
from django.shortcuts import get_object_or_404, render
from apps.orders.models import Order
from .services import TechnicalSpecService, OrderValidationError

def require_order_spec(phase='phase1'):
    """
    Decorator for views that require a technical specification.
    Injects 'order', 'spec_obj' (Pydantic), and 'spec_json_dict' (raw dict) into the view.
    Handles OrderValidationError by rendering an error page.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Intercept pk or order argument
            pk = kwargs.get('pk') or kwargs.get('order_id')
            order = kwargs.get('order')
            
            if not order and pk:
                order = get_object_or_404(Order, pk=pk)
            
            if not order:
                # Try to find order in args if not in kwargs
                for arg in args:
                    if isinstance(arg, Order):
                        order = arg
                        break
            
            if not order:
                # Cannot proceed without order
                from django.http import HttpResponseBadRequest
                return HttpResponseBadRequest("Order ID or Order object required")
            
            try:
                spec_obj, spec_json_dict = TechnicalSpecService.get_or_build_spec(order, phase=phase)
            except OrderValidationError as e:
                return render(request, 'production/report_validation_error.html', {
                    'order': order,
                    'errors': e.errors,
                    'phase': phase
                })
            
            # Inject arguments into the wrapped view
            kwargs['order'] = order
            kwargs['spec_obj'] = spec_obj
            kwargs['spec_json_dict'] = spec_json_dict
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
