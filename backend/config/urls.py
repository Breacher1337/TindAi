"""URL configuration for TindAI project."""

from django.contrib import admin
from django.urls import path
from core.api import api
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', api.urls),
    
    # Customer-facing mobile screens & HTMX endpoints
    path('', views.pos_view, name='pos'),
    path('cart/add/<int:product_id>/', views.cart_add, name='cart_add'),
    path('cart/add-by-id/', views.cart_add_by_id, name='cart_add_by_id'),
    path('cart/remove/<int:product_id>/', views.cart_remove, name='cart_remove'),
    path('cart/clear/', views.cart_clear, name='cart_clear'),
    path('checkout/', views.checkout_action, name='checkout'),
    
    path('inventory/', views.inventory_view, name='inventory'),
    path('utang/', views.utang_view, name='utang'),
    path('utang/pay/', views.utang_pay_action, name='utang_pay'),
    path('restock/', views.restock_view, name='restock'),
    path('restock/calculate/', views.restock_calculate, name='restock_calculate'),
]
