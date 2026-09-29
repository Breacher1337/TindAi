from django.contrib import admin
from django.utils.html import format_html
from .models import Product, Customer, CustomerPayment, Transaction, TransactionItem, RestockRun


admin.site.site_header = "TindAI Sari-Sari Store Management"
admin.site.site_title = "TindAI Admin"
admin.site.index_title = "Store Administration & Inventory Control"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'sku', 'name', 'category', 'wholesale_cost', 'retail_price',
        'margin_display', 'stock_quantity', 'stock_status_badge', 'is_active'
    )
    search_fields = ('sku', 'name', 'barcode', 'category', 'brand')
    list_filter = ('category', 'is_active')
    list_editable = ('retail_price', 'stock_quantity', 'is_active')
    ordering = ('category', 'name')

    @admin.display(description='Margin')
    def margin_display(self, obj):
        if obj.retail_price and obj.retail_price > 0 and obj.wholesale_cost:
            margin = ((obj.retail_price - obj.wholesale_cost) / obj.retail_price) * 100
            return f"{margin:.1f}%"
        return "N/A"

    @admin.display(description='Stock Status')
    def stock_status_badge(self, obj):
        if obj.stock_quantity <= 0:
            return format_html('<span style="color:#ef4444; font-weight:bold;">Out of Stock</span>')
        elif obj.stock_quantity <= obj.reorder_point:
            return format_html('<span style="color:#f59e0b; font-weight:bold;">Low (<= {})</span>', obj.reorder_point)
        return format_html('<span style="color:#10b981;">In Stock</span>')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'nickname', 'phone', 'debt_balance', 'credit_limit', 'debt_status_badge', 'is_active')
    search_fields = ('name', 'nickname', 'phone')
    list_filter = ('is_active',)
    ordering = ('-debt_balance', 'name')

    @admin.display(description='Credit Status')
    def debt_status_badge(self, obj):
        if obj.debt_balance <= 0:
            return format_html('<span style="color:#10b981;">Clean</span>')
        elif obj.debt_balance > obj.credit_limit:
            return format_html('<span style="color:#ef4444; font-weight:bold;">Exceeded Limit</span>')
        return format_html('<span style="color:#f59e0b; font-weight:bold;">Active Utang</span>')


@admin.register(CustomerPayment)
class CustomerPaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'amount', 'created_at')
    search_fields = ('customer__name', 'notes')
    list_filter = ('created_at',)
    date_hierarchy = 'created_at'


class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    extra = 0
    fields = ('product', 'quantity', 'unit_price', 'line_subtotal')
    readonly_fields = ('line_subtotal',)

    @admin.display(description='Subtotal')
    def line_subtotal(self, obj):
        if obj.id:
            return f"₱{obj.quantity * obj.unit_price:.2f}"
        return "₱0.00"


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'transaction_type', 'formatted_total', 'payment_status', 'customer', 'created_at')
    list_filter = ('transaction_type', 'payment_status', 'created_at')
    search_fields = ('id', 'customer__name')
    date_hierarchy = 'created_at'
    inlines = [TransactionItemInline]
    readonly_fields = ('created_at',)

    @admin.display(description='Total Amount', ordering='total_amount')
    def formatted_total(self, obj):
        return f"₱{obj.total_amount:.2f}"


@admin.register(RestockRun)
class RestockRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'formatted_budget', 'formatted_spent', 'created_at')
    list_filter = ('created_at',)
    date_hierarchy = 'created_at'

    @admin.display(description='Budget')
    def formatted_budget(self, obj):
        return f"₱{obj.budget:.2f}"

    @admin.display(description='Total Spent')
    def formatted_spent(self, obj):
        return f"₱{obj.total_spent:.2f}"
