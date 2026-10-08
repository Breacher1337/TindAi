"""URL configuration for TindAI project."""

from django.contrib import admin
from django.urls import path, include
from core.api import api
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', api.urls),
    path('i18n/', include('django.conf.urls.i18n')),
    
    # Customer-facing mobile screens & HTMX endpoints
    path('', views.pos_view, name='pos'),
    path('pos/', views.pos_view, name='pos_page'),
    path('cart/add/<uuid:product_id>/', views.cart_add, name='cart_add'),
    path('cart/add-by-id/', views.cart_add_by_id, name='cart_add_by_id'),
    path('cart/remove/<uuid:product_id>/', views.cart_remove, name='cart_remove'),
    path('cart/clear/', views.cart_clear, name='cart_clear'),
    path('checkout/', views.checkout_action, name='checkout'),
    
    path('inventory/', views.inventory_view, name='inventory'),
    path('utang/', views.utang_view, name='utang'),
    path('utang/pay/', views.utang_pay_action, name='utang_pay'),
    path('restock/', views.restock_view, name='restock'),
    path('restock/calculate/', views.restock_calculate, name='restock_calculate'),
    path('restock/receipt/', views.receipt_upload_view, name='receipt_upload'),
    path('analytics/', views.analytics_view, name='analytics'),
    path('settings/', views.settings_view, name='settings'),
    path('set-language/<str:lang_code>/', views.switch_language_view, name='switch_language'),
    
    # PWA Service Worker & Web App Manifest
    path('sw.js', views.service_worker_view, name='service_worker'),
    path('manifest.json', views.manifest_view, name='manifest'),
]

# Static files serving (supports tests with Client and development)
from django.contrib.staticfiles.views import serve as static_serve
from django.urls import re_path

urlpatterns += [
    re_path(r'^static/(?P<path>.*)$', static_serve, {'insecure': True}),
]

