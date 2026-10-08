import pytest
from decimal import Decimal
from datetime import date, datetime, timedelta
from django.core.management import call_command
from django.db.models import Sum, Count, Q
from django.utils import timezone

from core.models import (
    Product, Customer, Transaction, TransactionItem,
    CustomerPayment, InventoryBatch, StockMovement
)
from core.management.commands.generate_synthetic_data import TOP_20_STAPLE_SKUS, SNACK_DRINK_CATEGORIES


@pytest.mark.django_db
def test_cli_argument_parsing_and_defaults():
    """
    Scenario 1: Verify command defaults, flag overrides, and return dictionary structure.
    """
    res = call_command('generate_synthetic_data', days=5, seed=42, reset=True)

    expected_keys = [
        'total_days', 'start_date', 'end_date', 'total_transactions',
        'cash_transactions', 'utang_transactions', 'total_items',
        'total_revenue', 'total_cogs', 'gross_profit',
        'total_customer_payments', 'total_debt_repaid', 'customers_count',
        'payday_volume_ratio', 'weekend_snack_multiplier',
        'pre_payday_credit_multiplier', 'mape_stats', 'top20_mape'
    ]
    for key in expected_keys:
        assert key in res, f"Expected key '{key}' missing from return dictionary"

    assert res['total_days'] == 5
    assert res['customers_count'] >= 15
    assert res['total_transactions'] > 0
    assert res['total_items'] > 0
    assert res['total_revenue'] > Decimal('0.00')
    assert res['gross_profit'] == res['total_revenue'] - res['total_cogs']

    # Verify --days overrides --months
    res_override = call_command('generate_synthetic_data', days=8, months=6, seed=42, reset=True)
    assert res_override['total_days'] == 8


@pytest.mark.django_db
def test_payday_surge_volume_and_debt_settlement():
    """
    Scenario 2: Verify 1.8x volume surge on paydays (15th and 30th) and customer debt liquidation payments.
    """
    res = call_command(
        'generate_synthetic_data',
        days=45,
        start_date='2026-03-01',
        seed=42,
        reset=True
    )

    # Volume ratio verification
    assert 1.50 <= res['payday_volume_ratio'] <= 2.20, (
        f"Payday volume ratio {res['payday_volume_ratio']} outside expected range [1.50, 2.20]"
    )

    # Direct database query verification of payday transactions
    tx_by_date = {}
    for tx in Transaction.objects.all():
        d = timezone.localtime(tx.created_at).date()
        tx_by_date[d] = tx_by_date.get(d, 0) + 1

    payday_vols = [
        count for d, count in tx_by_date.items()
        if d.day in (15, 30) or (d.month == 2 and d.day in (28, 29))
    ]
    non_payday_vols = [
        count for d, count in tx_by_date.items()
        if not (d.day in (15, 30) or (d.month == 2 and d.day in (28, 29)))
    ]

    assert len(payday_vols) > 0
    assert len(non_payday_vols) > 0
    avg_payday = sum(payday_vols) / len(payday_vols)
    avg_non_payday = sum(non_payday_vols) / len(non_payday_vols)
    empirical_ratio = avg_payday / avg_non_payday
    assert 1.50 <= empirical_ratio <= 2.20

    # Debt liquidation verification
    payments = CustomerPayment.objects.all()
    assert payments.count() > 0

    payday_repaid = Decimal('0.00')
    non_payday_repaid = Decimal('0.00')
    for p in payments:
        # Audit balance integrity
        assert p.balance_before - p.amount == p.balance_after, "Payment balance before/after mismatch"
        assert p.amount > Decimal('0.00')
        pay_date = timezone.localtime(p.created_at).date()
        if pay_date.day in (15, 30):
            payday_repaid += p.amount
        else:
            non_payday_repaid += p.amount

    # Paydays account for substantial majority of debt settlement
    total_repaid = payday_repaid + non_payday_repaid
    assert total_repaid > Decimal('0.00')
    payday_pct = payday_repaid / total_repaid
    assert payday_pct >= Decimal('0.60'), f"Payday repayment proportion {payday_pct:.2f} should be >= 0.60"


@pytest.mark.django_db
def test_weekend_sales_spike():
    """
    Scenario 3: Verify 1.5x snack/beverage sales multiplier on Fri/Sat/Sun.
    """
    res = call_command(
        'generate_synthetic_data',
        days=28,
        start_date='2026-03-01',
        seed=42,
        reset=True
    )

    assert 1.35 <= res['weekend_snack_multiplier'] <= 1.65, (
        f"Weekend snack multiplier {res['weekend_snack_multiplier']} outside range [1.35, 1.65]"
    )

    # Database level check on item quantities
    items = TransactionItem.objects.filter(
        product__category__in=SNACK_DRINK_CATEGORIES
    ).select_related('transaction')

    daily_units = {}
    for item in items:
        d = timezone.localtime(item.transaction.created_at).date()
        daily_units[d] = daily_units.get(d, Decimal('0.00')) + item.quantity

    weekend_units = [qty for d, qty in daily_units.items() if d.weekday() in (4, 5, 6)]
    weekday_units = [qty for d, qty in daily_units.items() if d.weekday() in (0, 1, 2, 3)]

    assert len(weekend_units) > 0
    assert len(weekday_units) > 0
    avg_weekend = sum(weekend_units) / len(weekend_units)
    avg_weekday = sum(weekday_units) / len(weekday_units)
    emp_snack_ratio = float(avg_weekend / avg_weekday)
    assert 1.35 <= emp_snack_ratio <= 1.65


@pytest.mark.django_db
def test_pre_payday_credit_borrowing():
    """
    Scenario 4: Verify 1.6x credit checkout proportion on days 12-14 and 27-29,
    strictly enforcing customer credit limits.
    """
    res = call_command(
        'generate_synthetic_data',
        days=35,
        start_date='2026-03-01',
        seed=42,
        reset=True
    )

    assert 1.35 <= res['pre_payday_credit_multiplier'] <= 1.85, (
        f"Pre-payday credit multiplier {res['pre_payday_credit_multiplier']} outside [1.35, 1.85]"
    )

    # Strictly enforce credit limits across all customers
    customers = Customer.objects.all()
    for cust in customers:
        assert cust.debt_balance <= cust.credit_limit, (
            f"Customer {cust.name} exceeded credit limit: {cust.debt_balance} > {cust.credit_limit}"
        )
        assert cust.debt_balance >= Decimal('0.00'), "Customer debt cannot be negative"

    # All UTANG transactions must have an associated customer
    utang_txs = Transaction.objects.filter(transaction_type=Transaction.TYPE_UTANG)
    assert utang_txs.count() > 0
    for tx in utang_txs:
        assert tx.customer is not None, f"Utang tx {tx.transaction_number} has null customer"
        assert tx.payment_status == Transaction.STATUS_UNPAID


@pytest.mark.django_db
def test_inventory_replenishment_and_fifo_integrity():
    """
    Scenario 5: Verify batches exist, stock_quantity >= 0, StockMovement logs match,
    and gross_profit == total_amount - total_cogs.
    """
    call_command(
        'generate_synthetic_data',
        days=25,
        start_date='2026-03-01',
        seed=42,
        reset=True
    )

    # Inventory must NEVER be negative
    for p in Product.objects.all():
        assert p.stock_quantity >= Decimal('0.0000'), f"Product {p.sku} has negative stock: {p.stock_quantity}"

    # Batches and audit ledger verification
    assert InventoryBatch.objects.count() > 0, "No inventory batches created"
    assert StockMovement.objects.filter(movement_type=StockMovement.MOVEMENT_RESTOCK).count() > 0
    assert StockMovement.objects.filter(movement_type=StockMovement.MOVEMENT_SALE).count() > 0

    # Financial ledger consistency
    for tx in Transaction.objects.all():
        assert tx.gross_profit == tx.total_amount - tx.total_cogs, (
            f"Tx {tx.transaction_number} gross profit mismatch: {tx.gross_profit} != {tx.total_amount} - {tx.total_cogs}"
        )
        assert tx.total_cogs >= Decimal('0.00')
        assert tx.total_amount >= Decimal('0.00')

    for item in TransactionItem.objects.all():
        expected_subtotal = (item.quantity * item.unit_price).quantize(Decimal('0.01'))
        assert item.subtotal == expected_subtotal
        assert item.cost_price >= Decimal('0.00')


@pytest.mark.django_db
def test_mape_calculation_threshold_le_20_percent():
    """
    Scenario 6: Run 60-day simulation with --calc-mape, assert top 20 staples average MAPE <= 20.0%.
    """
    res = call_command(
        'generate_synthetic_data',
        days=60,
        start_date='2026-03-01',
        seed=42,
        calc_mape=True,
        reset=True
    )

    mape_stats = res['mape_stats']
    assert mape_stats is not None
    assert mape_stats['passed'] is True, f"Top-20 MAPE benchmark failed: {mape_stats['average_mape']}%"
    assert mape_stats['average_mape'] <= 20.0, f"Average MAPE {mape_stats['average_mape']}% > 20.0%"
    assert len(mape_stats['product_mapes']) == 20
    assert res['top20_mape'] == mape_stats['average_mape']

    # Insufficient burn-in window handling (< 31 days)
    res_short = call_command(
        'generate_synthetic_data',
        days=20,
        start_date='2026-03-01',
        seed=42,
        calc_mape=True,
        reset=True
    )
    assert res_short['mape_stats']['passed'] is False
    assert res_short['mape_stats']['average_mape'] is None


@pytest.mark.django_db
def test_simulation_determinism_and_reset():
    """
    Scenario 7: Verify identical results on the same seed and clean purge on --reset.
    """
    res1 = call_command('generate_synthetic_data', days=15, start_date='2026-03-01', seed=42, reset=True)
    tx_count_1 = Transaction.objects.count()
    rev_1 = Transaction.objects.aggregate(s=Sum('total_amount'))['s']
    items_count_1 = TransactionItem.objects.count()
    first_tx_1 = Transaction.objects.order_by('created_at').first().transaction_number

    # Second execution with identical seed and reset must reproduce identical results
    res2 = call_command('generate_synthetic_data', days=15, start_date='2026-03-01', seed=42, reset=True)
    tx_count_2 = Transaction.objects.count()
    rev_2 = Transaction.objects.aggregate(s=Sum('total_amount'))['s']
    items_count_2 = TransactionItem.objects.count()
    first_tx_2 = Transaction.objects.order_by('created_at').first().transaction_number

    assert tx_count_1 == tx_count_2
    assert rev_1 == rev_2
    assert items_count_1 == items_count_2
    assert first_tx_1 == first_tx_2
    assert res1['total_revenue'] == res2['total_revenue']
    assert res1['total_transactions'] == res2['total_transactions']

    # Verify --reset thoroughly wiped prior data (no doubling of transactions)
    assert tx_count_2 == res2['total_transactions']
