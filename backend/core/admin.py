from decimal import Decimal
from django.contrib import admin
from django.db.models import Sum, F
from django.utils import timezone
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display
from .models import (
    Product, Customer, CustomerPayment, Transaction, TransactionItem,
    RestockRun, StoreConfig, Wholesaler, InventoryBatch, StockMovement,
    RestockInvoice, RestockInvoiceItem
)


admin.site.site_header = "TindAI Sari-Sari Store Management"
admin.site.site_title = "TindAI Admin"
admin.site.index_title = "Store Administration & Inventory Control"


@admin.register(Wholesaler)
class WholesalerAdmin(ModelAdmin):
    list_display = ('name', 'branch', 'contact_number', 'created_at')
    search_fields = ('name', 'branch', 'contact_number')
    ordering = ('name',)


@admin.register(InventoryBatch)
class InventoryBatchAdmin(ModelAdmin):
    list_display = ('product', 'remaining_tingi_quantity', 'initial_tingi_quantity', 'unit_cost_basis', 'received_at')
    list_filter = ('received_at',)
    search_fields = ('product__name', 'product__sku')
    date_hierarchy = 'received_at'


@admin.register(StockMovement)
class StockMovementAdmin(ModelAdmin):
    list_display = ('product', 'movement_type', 'quantity_change', 'balance_after', 'reference_id', 'timestamp')
    list_filter = ('movement_type', 'timestamp')
    search_fields = ('product__name', 'product__sku', 'reference_id')
    date_hierarchy = 'timestamp'


class RestockInvoiceItemInline(TabularInline):
    model = RestockInvoiceItem
    extra = 0


@admin.register(RestockInvoice)
class RestockInvoiceAdmin(ModelAdmin):
    list_display = ('invoice_no', 'wholesaler', 'wholesaler_name', 'total_amount', 'parse_status', 'date', 'created_at')
    list_filter = ('parse_status', 'date')
    search_fields = ('invoice_no', 'wholesaler_name')
    inlines = [RestockInvoiceItemInline]


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
    list_display = ('id', 'customer', 'formatted_amount', 'balance_before', 'balance_after', 'created_at')
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
        'transaction_number', 'id', 'transaction_type_badge', 'formatted_total',
        'total_cogs', 'gross_profit', 'sync_status', 'payment_status_badge',
        'customer', 'created_at'
    )
    list_filter = ('transaction_type', 'payment_status', 'sync_status', 'created_at')
    list_filter_submit = True
    search_fields = ('id', 'transaction_number', 'customer__name')
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


@admin.register(StoreConfig)
class StoreConfigAdmin(ModelAdmin):
    list_display = ('store_name', 'caretaker_identity', 'default_retail_markup_percentage', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')

    def has_add_permission(self, request):
        return not StoreConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


def dashboard_callback(request, context):
    """Callback providing key store performance metrics for Unfold dashboard."""
    today = timezone.localdate()

    daily_revenue = Transaction.objects.filter(
        created_at__date=today
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')

    utang_balances = Customer.objects.filter(
        is_active=True
    ).aggregate(Sum('debt_balance'))['debt_balance__sum'] or Decimal('0.00')

    low_stock_count = Product.objects.filter(
        is_active=True,
        stock_quantity__lte=F('reorder_point')
    ).count()

    out_of_stock_count = Product.objects.filter(
        is_active=True,
        stock_quantity__lte=0
    ).count()

    total_products_count = Product.objects.filter(is_active=True).count()
    daily_transactions_count = Transaction.objects.filter(created_at__date=today).count()
    debtors_count = Customer.objects.filter(is_active=True, debt_balance__gt=0).count()

    context.update({
        'kpi_metrics': [
            {
                'title': 'Daily Revenue',
                'value': f"₱{daily_revenue:,.2f}",
                'description': f"{daily_transactions_count} transactions recorded today",
                'icon': 'payments',
            },
            {
                'title': 'Utang Balances',
                'value': f"₱{utang_balances:,.2f}",
                'description': f"{debtors_count} customers with outstanding credit",
                'icon': 'account_balance_wallet',
            },
            {
                'title': 'Low Stock',
                'value': str(low_stock_count),
                'description': f"{out_of_stock_count} out of stock ({total_products_count} total SKUs)",
                'icon': 'inventory_2',
            },
        ],
        'daily_revenue': f"₱{daily_revenue:,.2f}",
        'utang_balances': f"₱{utang_balances:,.2f}",
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'daily_transactions_count': daily_transactions_count,
    })
    return context
