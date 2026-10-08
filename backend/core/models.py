import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models
from django.utils import timezone


class Wholesaler(models.Model):
    """Supplier directory archiving supermarket and distributor details."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    branch = models.CharField(max_length=255, blank=True, default='')
    contact_number = models.CharField(max_length=50, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Wholesaler'
        verbose_name_plural = 'Wholesalers'

    def __str__(self):
        if self.branch:
            return f"{self.name} - {self.branch}"
        return self.name


class Product(models.Model):
    """FMCG inventory item in sari-sari store catalog."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sku = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    brand = models.CharField(max_length=100, blank=True, default='')
    category = models.CharField(max_length=100, db_index=True)
    wholesale_cost = models.DecimalField(max_digits=10, decimal_places=2, help_text="Purchase cost per pack or bulk unit")
    retail_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Tingi / piece retail selling price")
    stock_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal('0.0000'),
        help_text="Available inventory count (supports fractional units e.g. boxes)"
    )
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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    balance_before = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Customer debt balance before this payment"
    )
    balance_after = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Customer debt balance after this payment"
    )
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

    SYNC_STATUS_PENDING = 'PENDING_OFFLINE'
    SYNC_STATUS_SYNCED = 'SYNCED'
    SYNC_STATUS_CHOICES = [
        (SYNC_STATUS_PENDING, 'Pending Offline'),
        (SYNC_STATUS_SYNCED, 'Synced'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_number = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Unique human-readable transaction identifier e.g. TXN-YYYYMMDD-XXXX"
    )
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES, default=TYPE_CASH)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_cogs = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total Cost of Goods Sold"
    )
    gross_profit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Gross profit = total_amount - total_cogs"
    )
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default=STATUS_PAID)
    sync_status = models.CharField(
        max_length=20,
        choices=SYNC_STATUS_CHOICES,
        default=SYNC_STATUS_SYNCED
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    notes = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'

    def save(self, *args, **kwargs):
        if not self.transaction_number:
            today_str = timezone.now().strftime('%Y%m%d')
            prefix = f"TXN-{today_str}-"
            count = Transaction.objects.filter(transaction_number__startswith=prefix).count() + 1
            candidate = f"{prefix}{count:04d}"
            while Transaction.objects.filter(transaction_number=candidate).exists():
                count += 1
                candidate = f"{prefix}{count:04d}"
            self.transaction_number = candidate

        if self.total_amount is not None and self.total_cogs is not None and self.gross_profit == Decimal('0.00'):
            self.gross_profit = self.total_amount - self.total_cogs

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Tx {self.transaction_number or self.id} [{self.transaction_type}] ₱{self.total_amount:.2f}"


class TransactionItem(models.Model):
    """Line item in a checkout transaction."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='transaction_items')
    quantity = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal('1.0000'))
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Wholesale purchase unit cost at time of sale"
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = 'Transaction Item'
        verbose_name_plural = 'Transaction Items'

    def __str__(self):
        return f"{self.product.name} x {self.quantity} = ₱{self.subtotal:.2f}"


class RestockRun(models.Model):
    """Historical record of capital-constrained restocking knapsack optimization."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    budget = models.DecimalField(max_digits=10, decimal_places=2)
    total_spent = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    items_json = models.JSONField(default=list, help_text="Optimized list of packs to buy with SKU, qty, and cost")
    created_at = models.DateTimeField(auto_now_add=True)


class RestockInvoice(models.Model):
    """Historical record of a physical receipt applied to inventory."""
    PARSE_PENDING = 'PENDING'
    PARSE_PARSED = 'PARSED'
    PARSE_CONFIRMED = 'CONFIRMED'
    PARSE_STATUS_CHOICES = [
        (PARSE_PENDING, 'Pending'),
        (PARSE_PARSED, 'Parsed'),
        (PARSE_CONFIRMED, 'Confirmed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wholesaler = models.ForeignKey(
        Wholesaler,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices'
    )
    wholesaler_name = models.CharField(max_length=255)
    invoice_no = models.CharField(max_length=255, blank=True)
    date = models.DateField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    parse_status = models.CharField(
        max_length=20,
        choices=PARSE_STATUS_CHOICES,
        default=PARSE_CONFIRMED
    )
    image_path = models.CharField(max_length=255, blank=True, help_text="Path to raw receipt image if saved")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.wholesaler_name} - {self.invoice_no}"


class RestockInvoiceItem(models.Model):
    """Line item from an applied receipt."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(RestockInvoice, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='restock_history')
    raw_line_text = models.CharField(max_length=255)
    qty_packs = models.IntegerField(default=1)
    pack_wholesale_cost = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.raw_line_text} (x{self.qty_packs})"


class InventoryBatch(models.Model):
    """FIFO unit cost tracking per stock-in delivery batch."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='batches')
    invoice_item = models.ForeignKey(RestockInvoiceItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='batches')
    initial_tingi_quantity = models.DecimalField(max_digits=10, decimal_places=4)
    remaining_tingi_quantity = models.DecimalField(max_digits=10, decimal_places=4)
    unit_cost_basis = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    received_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['received_at']
        verbose_name = 'Inventory Batch'
        verbose_name_plural = 'Inventory Batches'

    def __str__(self):
        return f"Batch for {self.product.name} ({self.remaining_tingi_quantity}/{self.initial_tingi_quantity} @ ₱{self.unit_cost_basis:.2f})"


class StockMovement(models.Model):
    """Append-only audit ledger tracking every stock ingress, egress, spoilage, or adjustment."""
    MOVEMENT_SALE = 'SALE'
    MOVEMENT_RESTOCK = 'RESTOCK'
    MOVEMENT_SPOILAGE = 'SPOILAGE'
    MOVEMENT_AUDIT_ADJUSTMENT = 'AUDIT_ADJUSTMENT'
    MOVEMENT_TYPE_CHOICES = [
        (MOVEMENT_SALE, 'Sale'),
        (MOVEMENT_RESTOCK, 'Restock'),
        (MOVEMENT_SPOILAGE, 'Spoilage'),
        (MOVEMENT_AUDIT_ADJUSTMENT, 'Audit Adjustment'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_movements')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPE_CHOICES)
    quantity_change = models.DecimalField(max_digits=10, decimal_places=4)
    balance_after = models.DecimalField(max_digits=10, decimal_places=4)
    reference_id = models.CharField(max_length=255, blank=True, default='')
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Stock Movement'
        verbose_name_plural = 'Stock Movements'

    def __str__(self):
        sign = "+" if self.quantity_change > 0 else ""
        return f"{self.product.name} [{self.movement_type}] {sign}{self.quantity_change} -> Bal: {self.balance_after}"


class StoreConfig(models.Model):
    """Singleton configuration for store identity, caretaker, and default pricing rules."""
    store_name = models.CharField(
        max_length=255,
        default="TindAI Sari-Sari Store",
        help_text="Official name of the sari-sari store"
    )
    caretaker_identity = models.CharField(
        max_length=255,
        default="Tindero / Tindera",
        help_text="Name or role of current store caretaker"
    )
    default_retail_markup_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        help_text="Default retail markup percentage applied to wholesale cost (e.g. 15.00 for 15%)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Store Configuration"
        verbose_name_plural = "Store Configuration"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(pk=1),
                name="single_store_config_record"
            )
        ]

    def __str__(self):
        return f"{self.store_name} ({self.caretaker_identity})"

    @property
    def caretaker_name(self) -> str:
        return self.caretaker_identity

    @property
    def default_markup_percentage(self) -> Decimal:
        return self.default_retail_markup_percentage

    @classmethod
    def get_solo(cls) -> "StoreConfig":
        """
        Retrieve singleton instance or create with default values if non-existent.
        Guarantees deterministic primary key = 1.
        """
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "store_name": "TindAI Sari-Sari Store",
                "caretaker_identity": "Tindero / Tindera",
                "default_retail_markup_percentage": Decimal("15.00"),
            }
        )
        return obj

    def clean(self):
        super().clean()
        if self.pk is not None and self.pk != 1:
            raise ValidationError("Only one StoreConfig instance is permitted (ID must be 1).")
        if not self.pk and StoreConfig.objects.filter(pk=1).exists():
            raise ValidationError("Only one StoreConfig instance is permitted.")

    def save(self, *args, **kwargs):
        if self.pk is not None and self.pk != 1:
            raise IntegrityError("Only one StoreConfig instance is permitted (ID must be 1).")
        if not self.pk and StoreConfig.objects.filter(pk=1).exists():
            raise IntegrityError("Only one StoreConfig instance is permitted.")
        self.pk = 1
        super().save(*args, **kwargs)
