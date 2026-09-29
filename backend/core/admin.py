from django.contrib import admin
from .models import Product, Customer, CustomerPayment, Transaction, TransactionItem, RestockRun


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'category', 'wholesale_cost', 'retail_price', 'stock_quantity', 'reorder_point', 'is_active')
    search_fields = ('sku', 'name', 'barcode', 'category', 'brand')
    list_filter = ('category', 'is_active')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'nickname', 'phone', 'debt_balance', 'credit_limit', 'is_active')
    search_fields = ('name', 'nickname', 'phone')
    list_filter = ('is_active',)


@admin.register(CustomerPayment)
class CustomerPaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'amount', 'created_at')
    search_fields = ('customer__name', 'notes')
    list_filter = ('created_at',)


class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    extra = 0


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'transaction_type', 'total_amount', 'payment_status', 'customer', 'created_at')
    list_filter = ('transaction_type', 'payment_status', 'created_at')
    search_fields = ('id', 'customer__name')
    inlines = [TransactionItemInline]


@admin.register(RestockRun)
class RestockRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'budget', 'total_spent', 'created_at')
    list_filter = ('created_at',)
