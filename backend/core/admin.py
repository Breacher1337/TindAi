from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display
from .models import Product, Customer, CustomerPayment, Transaction, TransactionItem, RestockRun


admin.site.site_header = "TindAI Sari-Sari Store Management"
admin.site.site_title = "TindAI Admin"
admin.site.index_title = "Store Administration & Inventory Control"


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = (
        'sku', 'name', 'category', 'wholesale_cost', 'retail_price',
        'margin_display', 'stock_quantity', 'stock_status_badge', 'is_active'
    )
    search_fields = ('sku', 'name', 'barcode', 'category', 'brand')
    list_filter = ('category', 'is_active')
    list_filter_submit = True
    list_editable = ('retail_price', 'stock_quantity', 'is_active')
    ordering = ('category', 'name')

    @display(description='Margin')
    def margin_display(self, obj):
        if obj.retail_price and obj.retail_price > 0 and obj.wholesale_cost:
            margin = ((obj.retail_price - obj.wholesale_cost) / obj.retail_price) * 100
            return f"{margin:.1f}%"
        return "N/A"

    @display(
        description='Stock Status',
        label={
            'OUT': 'danger',
            'LOW': 'warning',
            'OK': 'success',
        },
    )
    def stock_status_badge(self, obj):
        if obj.stock_quantity <= 0:
            return 'OUT', 'Out of Stock'
        elif obj.stock_quantity <= obj.reorder_point:
            return 'LOW', f'Low (<= {obj.reorder_point})'
        return 'OK', 'In Stock'


@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    list_display = (
        'name', 'nickname', 'phone', 'formatted_debt_balance',
        'formatted_credit_limit', 'debt_status_badge', 'is_active'
    )
    search_fields = ('name', 'nickname', 'phone')
    list_filter = ('is_active',)
    list_filter_submit = True
    ordering = ('-debt_balance', 'name')

    @display(description='Utang Balance', ordering='debt_balance')
    def formatted_debt_balance(self, obj):
        return f"₱{obj.debt_balance:.2f}"

    @display(description='Credit Limit', ordering='credit_limit')
    def formatted_credit_limit(self, obj):
        return f"₱{obj.credit_limit:.2f}"

    @display(
        description='Credit Status',
        label={
            'CLEAN': 'success',
            'OVER_LIMIT': 'danger',
            'ACTIVE': 'warning',
        },
    )
    def debt_status_badge(self, obj):
        if obj.debt_balance <= 0:
            return 'CLEAN', 'Clean'
        elif obj.debt_balance > obj.credit_limit:
            return 'OVER_LIMIT', 'Exceeded Limit'
        return 'ACTIVE', 'Active Utang'


@admin.register(CustomerPayment)
class CustomerPaymentAdmin(ModelAdmin):
    list_display = ('id', 'customer', 'formatted_amount', 'created_at')
    search_fields = ('customer__name', 'notes')
    list_filter = ('created_at',)
    list_filter_submit = True
    date_hierarchy = 'created_at'

    @display(description='Amount', ordering='amount')
    def formatted_amount(self, obj):
        return f"₱{obj.amount:.2f}"


class TransactionItemInline(TabularInline):
    model = TransactionItem
    extra = 0
    fields = ('product', 'quantity', 'unit_price', 'line_subtotal')
    readonly_fields = ('line_subtotal',)

    @display(description='Subtotal')
    def line_subtotal(self, obj):
        if obj.id:
            return f"₱{obj.quantity * obj.unit_price:.2f}"
        return "₱0.00"


@admin.register(Transaction)
class TransactionAdmin(ModelAdmin):
    list_display = (
        'id', 'transaction_type_badge', 'formatted_total',
        'payment_status_badge', 'customer', 'created_at'
    )
    list_filter = ('transaction_type', 'payment_status', 'created_at')
    list_filter_submit = True
    search_fields = ('id', 'customer__name')
    date_hierarchy = 'created_at'
    inlines = [TransactionItemInline]
    readonly_fields = ('created_at',)

    @display(
        description='Type',
        ordering='transaction_type',
        label={
            Transaction.TYPE_CASH: 'success',
            Transaction.TYPE_UTANG: 'warning',
        },
    )
    def transaction_type_badge(self, obj):
        return obj.transaction_type, obj.get_transaction_type_display()

    @display(
        description='Payment Status',
        ordering='payment_status',
        label={
            Transaction.STATUS_PAID: 'success',
            Transaction.STATUS_PARTIAL: 'warning',
            Transaction.STATUS_UNPAID: 'danger',
        },
    )
    def payment_status_badge(self, obj):
        return obj.payment_status, obj.get_payment_status_display()

    @display(description='Total Amount', ordering='total_amount')
    def formatted_total(self, obj):
        return f"₱{obj.total_amount:.2f}"


@admin.register(RestockRun)
class RestockRunAdmin(ModelAdmin):
    list_display = ('id', 'formatted_budget', 'formatted_spent', 'created_at')
    list_filter = ('created_at',)
    list_filter_submit = True
    date_hierarchy = 'created_at'

    @display(description='Budget', ordering='budget')
    def formatted_budget(self, obj):
        return f"₱{obj.budget:.2f}"

    @display(description='Total Spent', ordering='total_spent')
    def formatted_spent(self, obj):
        return f"₱{obj.total_spent:.2f}"
