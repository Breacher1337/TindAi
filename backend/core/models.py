from django.db import models
from django.utils import timezone


class Product(models.Model):
    """FMCG inventory item in sari-sari store catalog."""
    sku = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    brand = models.CharField(max_length=100, blank=True, default='')
    category = models.CharField(max_length=100, db_index=True)
    wholesale_cost = models.DecimalField(max_digits=10, decimal_places=2, help_text="Purchase cost per pack or bulk unit")
    retail_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Tingi / piece retail selling price")
    stock_quantity = models.IntegerField(default=0, help_text="Current available inventory count (in tingi units)")
    reorder_point = models.IntegerField(default=10, help_text="Threshold to trigger automated restocking")
    pack_unit = models.CharField(max_length=50, default="pack", help_text="Wholesale purchase unit (e.g. box, bundle, case)")
    tingi_unit = models.CharField(max_length=50, default="piece", help_text="Break-bulk retail sale unit (e.g. piece, sachet, can)")
    barcode = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Product'
        verbose_name_plural = 'Products'

    def __str__(self):
        return f"{self.name} ({self.sku})"


class Customer(models.Model):
    """Customer profile with digital utang (credit) ledger tracking."""
    name = models.CharField(max_length=255)
    nickname = models.CharField(max_length=100, blank=True, default='')
    phone = models.CharField(max_length=50, blank=True, default='')
    address = models.CharField(max_length=255, blank=True, default='')
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=1000.00)
    debt_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'

    def __str__(self):
        display = self.name
        if self.nickname:
            display += f" ({self.nickname})"
        return f"{display} - Utang: ₱{self.debt_balance:.2f}"


class CustomerPayment(models.Model):
    """Record of debt liquidation payment made by customer."""
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Customer Payment'
        verbose_name_plural = 'Customer Payments'

    def __str__(self):
        return f"₱{self.amount:.2f} payment by {self.customer.name} at {self.created_at:%Y-%m-%d %H:%M}"


class Transaction(models.Model):
    """Point-of-sale checkout transaction record."""
    TYPE_CASH = 'CASH'
    TYPE_UTANG = 'UTANG'
    TRANSACTION_TYPE_CHOICES = [
        (TYPE_CASH, 'Cash'),
        (TYPE_UTANG, 'Utang (Credit)'),
    ]

    STATUS_PAID = 'PAID'
    STATUS_UNPAID = 'UNPAID'
    STATUS_PARTIAL = 'PARTIAL'
    PAYMENT_STATUS_CHOICES = [
        (STATUS_PAID, 'Paid'),
        (STATUS_UNPAID, 'Unpaid'),
        (STATUS_PARTIAL, 'Partial'),
    ]

    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES, default=TYPE_CASH)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default=STATUS_PAID)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    notes = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'

    def __str__(self):
        return f"Tx #{self.id} [{self.transaction_type}] ₱{self.total_amount:.2f}"


class TransactionItem(models.Model):
    """Line item in a checkout transaction."""
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='transaction_items')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = 'Transaction Item'
        verbose_name_plural = 'Transaction Items'

    def __str__(self):
        return f"{self.product.name} x {self.quantity} = ₱{self.subtotal:.2f}"


class RestockRun(models.Model):
    """Historical record of capital-constrained restocking knapsack optimization."""
    budget = models.DecimalField(max_digits=10, decimal_places=2)
    total_spent = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    items_json = models.JSONField(default=list, help_text="Optimized list of packs to buy with SKU, qty, and cost")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Restock Run'
        verbose_name_plural = 'Restock Runs'

    def __str__(self):
        return f"Restock Run #{self.id} - Budget: ₱{self.budget:.2f}, Spent: ₱{self.total_spent:.2f}"
