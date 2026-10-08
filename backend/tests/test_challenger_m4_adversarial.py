"""
Milestone 4 Adversarial Verification Test Suite
Authored by: challenger_m4_1

Adversarial Stress-Testing:
1. Exact boundary conditions: 29-day sale vs 30-day boundary vs 31-day sale for DEAD_STOCK.
2. 7-day velocity window boundaries (Day 6, Day 7, Day 7+1m, Day 8).
3. Tied-up capital arithmetic with fractional stock, zero stock, negative stock, zero cost.
4. Daily velocity calculation precision and recurring fraction rounding.
5. Fast-moving threshold boundary checks (9.99 vs 10.00, 19.99 vs 20.00, 0.49 vs 0.50).
6. Out-of-stock items (stock=0 with/without sales).
7. Inactive product exclusion and zero leakage.
8. Deterministic string parsing of `as_of` timestamps (ISO, UTC, space-offset, date-only).
"""

import pytest
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from django.utils import timezone
from django.test import Client

from core.models import Product, Transaction, TransactionItem
from core.services.analytics import get_inventory_turnover_analytics


@pytest.fixture
def api_client():
    return Client()


@pytest.mark.django_db
def test_adversarial_dead_stock_30d_exact_boundary():
    """
    Stress-test exact DEAD_STOCK boundary:
    - 29-day sale MUST NOT be DEAD_STOCK.
    - 29 days, 23 hours, 59 mins sale MUST NOT be DEAD_STOCK.
    - Exactly 30-day sale MUST NOT be DEAD_STOCK (__gte start_30d).
    - 30 days + 1 second sale MUST be DEAD_STOCK.
    - 31-day sale MUST be DEAD_STOCK.
    - 45-day sale MUST be DEAD_STOCK.
    - Never sold MUST be DEAD_STOCK.
    - Future sale relative to as_of MUST be DEAD_STOCK (future tx not in [start, as_of]).
    """
    as_of = datetime(2026, 8, 15, 12, 0, 0, tzinfo=dt_timezone.utc)

    # 1. Day 29 sale
    p_29 = Product.objects.create(
        sku="TEST-29D",
        name="Day 29 Sale Item",
        wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("5.0000"),
        category="Test",
    )
    tx_29 = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("15.00"),
        created_at=as_of - timedelta(days=29),
    )
    TransactionItem.objects.create(transaction=tx_29, product=p_29, quantity=Decimal("1.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("15.00"))

    # 2. Day 29 + 23h59m sale (just before 30d cutoff)
    p_29_edge = Product.objects.create(
        sku="TEST-29D-EDGE",
        name="Day 29.99 Sale Item",
        wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("5.0000"),
        category="Test",
    )
    tx_29_edge = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("15.00"),
        created_at=as_of - timedelta(days=29, hours=23, minutes=59),
    )
    TransactionItem.objects.create(transaction=tx_29_edge, product=p_29_edge, quantity=Decimal("1.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("15.00"))

    # 3. Exact 30-day sale
    p_30_exact = Product.objects.create(
        sku="TEST-30D-EXACT",
        name="Day 30.00 Exact Sale Item",
        wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("5.0000"),
        category="Test",
    )
    tx_30_exact = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("15.00"),
        created_at=as_of - timedelta(days=30),
    )
    TransactionItem.objects.create(transaction=tx_30_exact, product=p_30_exact, quantity=Decimal("1.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("15.00"))

    # 4. 30 days + 1 second sale (outside 30-day window)
    p_30_plus_1s = Product.objects.create(
        sku="TEST-30D-1S",
        name="Day 30 + 1s Sale Item",
        wholesale_cost=Decimal("20.00"),
        retail_price=Decimal("25.00"),
        stock_quantity=Decimal("4.0000"),
        category="Test",
    )
    tx_30_plus_1s = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("25.00"),
        created_at=as_of - timedelta(days=30, seconds=1),
    )
    TransactionItem.objects.create(transaction=tx_30_plus_1s, product=p_30_plus_1s, quantity=Decimal("1.0000"), unit_price=Decimal("25.00"), subtotal=Decimal("25.00"))

    # 5. Day 31 sale
    p_31 = Product.objects.create(
        sku="TEST-31D",
        name="Day 31 Sale Item",
        wholesale_cost=Decimal("30.00"),
        retail_price=Decimal("35.00"),
        stock_quantity=Decimal("3.0000"),
        category="Test",
    )
    tx_31 = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("35.00"),
        created_at=as_of - timedelta(days=31),
    )
    TransactionItem.objects.create(transaction=tx_31, product=p_31, quantity=Decimal("1.0000"), unit_price=Decimal("35.00"), subtotal=Decimal("35.00"))

    # 6. Never sold
    p_never = Product.objects.create(
        sku="TEST-NEVER",
        name="Never Sold Item",
        wholesale_cost=Decimal("40.00"),
        retail_price=Decimal("50.00"),
        stock_quantity=Decimal("2.0000"),
        category="Test",
    )

    # 7. Future sale relative to as_of
    p_future = Product.objects.create(
        sku="TEST-FUTURE",
        name="Future Sale Item",
        wholesale_cost=Decimal("50.00"),
        retail_price=Decimal("60.00"),
        stock_quantity=Decimal("1.0000"),
        category="Test",
    )
    tx_future = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("60.00"),
        created_at=as_of + timedelta(days=1),
    )
    TransactionItem.objects.create(transaction=tx_future, product=p_future, quantity=Decimal("1.0000"), unit_price=Decimal("60.00"), subtotal=Decimal("60.00"))

    # Execute analytics
    result = get_inventory_turnover_analytics(as_of=as_of)

    dead_map = {item["sku"]: item for item in result["dead_stock"]}
    all_map = {item["sku"]: item for item in result["all_items"]}

    # Non-dead stock items (within 30 days)
    assert all_map["TEST-29D"]["sales_30d"] == Decimal("1.00")
    assert all_map["TEST-29D"]["status"] != "DEAD_STOCK"
    assert "TEST-29D" not in dead_map

    assert all_map["TEST-29D-EDGE"]["sales_30d"] == Decimal("1.00")
    assert all_map["TEST-29D-EDGE"]["status"] != "DEAD_STOCK"
    assert "TEST-29D-EDGE" not in dead_map

    assert all_map["TEST-30D-EXACT"]["sales_30d"] == Decimal("1.00")
    assert all_map["TEST-30D-EXACT"]["status"] != "DEAD_STOCK"
    assert "TEST-30D-EXACT" not in dead_map

    # Dead stock items (outside 30 days or zero movement)
    assert all_map["TEST-30D-1S"]["sales_30d"] == Decimal("0.00")
    assert all_map["TEST-30D-1S"]["status"] == "DEAD_STOCK"
    assert "TEST-30D-1S" in dead_map

    assert all_map["TEST-31D"]["sales_30d"] == Decimal("0.00")
    assert all_map["TEST-31D"]["status"] == "DEAD_STOCK"
    assert "TEST-31D" in dead_map

    assert all_map["TEST-NEVER"]["sales_30d"] == Decimal("0.00")
    assert all_map["TEST-NEVER"]["status"] == "DEAD_STOCK"
    assert "TEST-NEVER" in dead_map

    assert all_map["TEST-FUTURE"]["sales_30d"] == Decimal("0.00")
    assert all_map["TEST-FUTURE"]["status"] == "DEAD_STOCK"
    assert "TEST-FUTURE" in dead_map

    assert result["dead_stock_count"] == 4


@pytest.mark.django_db
def test_adversarial_7d_velocity_boundary():
    """
    Stress-test 7-day velocity window:
    - Day 6 sale: in 7d and 30d
    - Day 7 exact sale: in 7d and 30d
    - Day 7 + 1 minute sale: NOT in 7d, but in 30d
    - Day 8 sale: NOT in 7d, but in 30d
    """
    as_of = datetime(2026, 9, 1, 10, 0, 0, tzinfo=dt_timezone.utc)

    p_d6 = Product.objects.create(sku="V-D6", name="D6 Item", stock_quantity=Decimal("10.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_d6 = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("15.00"), created_at=as_of - timedelta(days=6))
    TransactionItem.objects.create(transaction=tx_d6, product=p_d6, quantity=Decimal("7.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("105.00"))

    p_d7 = Product.objects.create(sku="V-D7", name="D7 Item", stock_quantity=Decimal("10.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_d7 = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("15.00"), created_at=as_of - timedelta(days=7))
    TransactionItem.objects.create(transaction=tx_d7, product=p_d7, quantity=Decimal("7.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("105.00"))

    p_d7_plus = Product.objects.create(sku="V-D7-PLUS", name="D7+1m Item", stock_quantity=Decimal("10.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_d7_plus = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("15.00"), created_at=as_of - timedelta(days=7, minutes=1))
    TransactionItem.objects.create(transaction=tx_d7_plus, product=p_d7_plus, quantity=Decimal("7.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("105.00"))

    p_d8 = Product.objects.create(sku="V-D8", name="D8 Item", stock_quantity=Decimal("10.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_d8 = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("15.00"), created_at=as_of - timedelta(days=8))
    TransactionItem.objects.create(transaction=tx_d8, product=p_d8, quantity=Decimal("7.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("105.00"))

    result = get_inventory_turnover_analytics(as_of=as_of)
    item_map = {it["sku"]: it for it in result["all_items"]}

    # D6: within 7d
    assert item_map["V-D6"]["sales_7d"] == Decimal("7.00")
    assert item_map["V-D6"]["sales_30d"] == Decimal("7.00")
    assert item_map["V-D6"]["daily_velocity_7d"] == 1.0

    # D7 exact: within 7d (__gte start_7d)
    assert item_map["V-D7"]["sales_7d"] == Decimal("7.00")
    assert item_map["V-D7"]["sales_30d"] == Decimal("7.00")
    assert item_map["V-D7"]["daily_velocity_7d"] == 1.0

    # D7 + 1m: strictly older than start_7d
    assert item_map["V-D7-PLUS"]["sales_7d"] == Decimal("0.00")
    assert item_map["V-D7-PLUS"]["sales_30d"] == Decimal("7.00")
    assert item_map["V-D7-PLUS"]["daily_velocity_7d"] == 0.0

    # D8: older than 7d
    assert item_map["V-D8"]["sales_7d"] == Decimal("0.00")
    assert item_map["V-D8"]["sales_30d"] == Decimal("7.00")
    assert item_map["V-D8"]["daily_velocity_7d"] == 0.0


@pytest.mark.django_db
def test_adversarial_tied_capital_arithmetic_and_edge_stocks():
    """
    Stress-test tied-up capital arithmetic with edge cases:
    - Fractional stock & odd wholesale cost
    - Zero stock
    - Negative stock (must not produce negative capital)
    - Zero wholesale cost (promo / donation)
    - Standard positive stock
    - Verifies dead_stock_tied_capital equals exact sum of dead stock stock_values.
    - Verifies sorting of dead_stock list strictly by stock_value descending.
    """
    now = timezone.now()

    # 1. Fractional stock: 15.5 units @ 24.50 cost = 379.75
    p1 = Product.objects.create(sku="TC-FRAC", name="Item 1", stock_quantity=Decimal("15.5000"), wholesale_cost=Decimal("24.50"), retail_price=Decimal("30.00"))

    # 2. High cost fractional: 0.33 units @ 1250.75 cost = 412.7475 -> 412.75
    p2 = Product.objects.create(sku="TC-HIGH", name="Item 2", stock_quantity=Decimal("0.3300"), wholesale_cost=Decimal("1250.75"), retail_price=Decimal("1500.00"))

    # 3. Zero stock: 0 units @ 99.99 cost = 0.00
    p3 = Product.objects.create(sku="TC-ZERO", name="Item 3", stock_quantity=Decimal("0.0000"), wholesale_cost=Decimal("99.99"), retail_price=Decimal("120.00"))

    # 4. Negative stock (ledger discrepancy): -10.0 units @ 50.00 cost = 0.00 (NOT -500.00)
    p4 = Product.objects.create(sku="TC-NEG", name="Item 4", stock_quantity=Decimal("-10.0000"), wholesale_cost=Decimal("50.00"), retail_price=Decimal("60.00"))

    # 5. Zero wholesale cost: 100 units @ 0.00 cost = 0.00
    p5 = Product.objects.create(sku="TC-FREE", name="Item 5", stock_quantity=Decimal("100.0000"), wholesale_cost=Decimal("0.00"), retail_price=Decimal("5.00"))

    # 6. Standard integer: 12 units @ 10.00 cost = 120.00
    p6 = Product.objects.create(sku="TC-STD", name="Item 6", stock_quantity=Decimal("12.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))

    # No transactions created -> all 6 are DEAD_STOCK

    result = get_inventory_turnover_analytics(as_of=now)
    assert result["dead_stock_count"] == 6

    dead_items = {it["sku"]: it for it in result["dead_stock"]}
    assert dead_items["TC-FRAC"]["stock_value"] == Decimal("379.75")
    assert dead_items["TC-HIGH"]["stock_value"] == Decimal("412.75")
    assert dead_items["TC-ZERO"]["stock_value"] == Decimal("0.00")
    assert dead_items["TC-NEG"]["stock_value"] == Decimal("0.00")
    assert dead_items["TC-FREE"]["stock_value"] == Decimal("0.00")
    assert dead_items["TC-STD"]["stock_value"] == Decimal("120.00")

    # Sum: 379.75 + 412.75 + 0.00 + 0.00 + 0.00 + 120.00 = 912.50
    expected_tied_capital = Decimal("912.50")
    assert result["dead_stock_tied_capital"] == expected_tied_capital

    # Verify descending ordering by stock_value
    stock_values = [it["stock_value"] for it in result["dead_stock"]]
    assert stock_values == sorted(stock_values, reverse=True)
    assert [it["sku"] for it in result["dead_stock"]][:3] == ["TC-HIGH", "TC-FRAC", "TC-STD"]


@pytest.mark.django_db
def test_adversarial_daily_velocity_precision_and_rounding():
    """
    Stress-test recurring decimal division precision for daily_velocity_7d and 30d:
    - 1 / 7 = 0.142857... -> 0.14
    - 2 / 7 = 0.285714... -> 0.29
    - 1 / 30 = 0.033333... -> 0.03
    - 2 / 30 = 0.066666... -> 0.07
    - 20 / 30 = 0.666666... -> 0.67
    - 29 / 30 = 0.966666... -> 0.97
    """
    as_of = datetime(2026, 7, 1, 12, 0, 0, tzinfo=dt_timezone.utc)

    # Product with 1 sale in 7d (and 30d)
    p1 = Product.objects.create(sku="V-REC-1", name="Rec 1", stock_quantity=Decimal("10.0000"), wholesale_cost=Decimal("1.00"), retail_price=Decimal("10.00"))
    tx1 = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("10.00"), created_at=as_of - timedelta(days=2))
    TransactionItem.objects.create(transaction=tx1, product=p1, quantity=Decimal("1.0000"), unit_price=Decimal("10.00"), subtotal=Decimal("10.00"))

    # Product with 2 sales in 7d (and 30d)
    p2 = Product.objects.create(sku="V-REC-2", name="Rec 2", stock_quantity=Decimal("10.0000"), wholesale_cost=Decimal("1.00"), retail_price=Decimal("10.00"))
    tx2 = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("20.00"), created_at=as_of - timedelta(days=3))
    TransactionItem.objects.create(transaction=tx2, product=p2, quantity=Decimal("2.0000"), unit_price=Decimal("10.00"), subtotal=Decimal("20.00"))

    # Product with 20 sales in 30d, 0 in 7d
    p20 = Product.objects.create(sku="V-REC-20", name="Rec 20", stock_quantity=Decimal("50.0000"), wholesale_cost=Decimal("1.00"), retail_price=Decimal("10.00"))
    tx20 = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("200.00"), created_at=as_of - timedelta(days=15))
    TransactionItem.objects.create(transaction=tx20, product=p20, quantity=Decimal("20.0000"), unit_price=Decimal("10.00"), subtotal=Decimal("200.00"))

    result = get_inventory_turnover_analytics(as_of=as_of)
    item_map = {it["sku"]: it for it in result["all_items"]}

    # p1: 1 unit in 7d and 30d
    assert item_map["V-REC-1"]["daily_velocity_7d"] == 0.14
    assert item_map["V-REC-1"]["daily_velocity_30d"] == 0.03

    # p2: 2 units in 7d and 30d
    assert item_map["V-REC-2"]["daily_velocity_7d"] == 0.29
    assert item_map["V-REC-2"]["daily_velocity_30d"] == 0.07

    # p20: 0 in 7d, 20 in 30d
    assert item_map["V-REC-20"]["daily_velocity_7d"] == 0.0
    assert item_map["V-REC-20"]["daily_velocity_30d"] == 0.67


@pytest.mark.django_db
def test_adversarial_fast_moving_boundaries():
    """
    Stress-test thresholds for FAST_MOVING vs MODERATE:
    1. sales_7d boundary: 9.99 (MODERATE) vs 10.00 (FAST_MOVING)
    2. sales_30d boundary: 19.99 (MODERATE) vs 20.00 (FAST_MOVING)
    3. turnover_ratio boundary: 0.49 (MODERATE) vs 0.50 (FAST_MOVING)
    4. Out of stock item with sales (stock=0, sales=1): turnover_ratio=1.0 -> FAST_MOVING
    """
    as_of = datetime(2026, 7, 20, 12, 0, 0, tzinfo=dt_timezone.utc)

    # 1a. sales_7d = 9.99, current_stock = 100 -> ratio = 0.0999 -> MODERATE
    p_7d_sub = Product.objects.create(sku="FM-7D-SUB", name="Sub 10 7D", stock_quantity=Decimal("100.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_7d_sub = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("99.90"), created_at=as_of - timedelta(days=2))
    TransactionItem.objects.create(transaction=tx_7d_sub, product=p_7d_sub, quantity=Decimal("9.9900"), unit_price=Decimal("10.00"), subtotal=Decimal("99.90"))

    # 1b. sales_7d = 10.00, current_stock = 100 -> FAST_MOVING
    p_7d_hit = Product.objects.create(sku="FM-7D-HIT", name="Hit 10 7D", stock_quantity=Decimal("100.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_7d_hit = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("100.00"), created_at=as_of - timedelta(days=2))
    TransactionItem.objects.create(transaction=tx_7d_hit, product=p_7d_hit, quantity=Decimal("10.0000"), unit_price=Decimal("10.00"), subtotal=Decimal("100.00"))

    # 2a. sales_30d = 19.99 (all outside 7d), current_stock = 100 -> ratio = 0.1999 -> MODERATE
    p_30d_sub = Product.objects.create(sku="FM-30D-SUB", name="Sub 20 30D", stock_quantity=Decimal("100.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_30d_sub = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("199.90"), created_at=as_of - timedelta(days=12))
    TransactionItem.objects.create(transaction=tx_30d_sub, product=p_30d_sub, quantity=Decimal("19.9900"), unit_price=Decimal("10.00"), subtotal=Decimal("199.90"))

    # 2b. sales_30d = 20.00 (all outside 7d), current_stock = 100 -> FAST_MOVING
    p_30d_hit = Product.objects.create(sku="FM-30D-HIT", name="Hit 20 30D", stock_quantity=Decimal("100.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_30d_hit = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("200.00"), created_at=as_of - timedelta(days=12))
    TransactionItem.objects.create(transaction=tx_30d_hit, product=p_30d_hit, quantity=Decimal("20.0000"), unit_price=Decimal("10.00"), subtotal=Decimal("200.00"))

    # 3a. turnover_ratio = 4.90 / 10 = 0.49 -> MODERATE
    p_ratio_sub = Product.objects.create(sku="FM-RATIO-SUB", name="Sub 0.50 Ratio", stock_quantity=Decimal("10.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_ratio_sub = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("49.00"), created_at=as_of - timedelta(days=10))
    TransactionItem.objects.create(transaction=tx_ratio_sub, product=p_ratio_sub, quantity=Decimal("4.9000"), unit_price=Decimal("10.00"), subtotal=Decimal("49.00"))

    # 3b. turnover_ratio = 5.00 / 10 = 0.50 -> FAST_MOVING
    p_ratio_hit = Product.objects.create(sku="FM-RATIO-HIT", name="Hit 0.50 Ratio", stock_quantity=Decimal("10.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_ratio_hit = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("50.00"), created_at=as_of - timedelta(days=10))
    TransactionItem.objects.create(transaction=tx_ratio_hit, product=p_ratio_hit, quantity=Decimal("5.0000"), unit_price=Decimal("10.00"), subtotal=Decimal("50.00"))

    # 4. Out of stock item that had 1 sale in 30d
    p_oos = Product.objects.create(sku="FM-OOS", name="Sold Out Item", stock_quantity=Decimal("0.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))
    tx_oos = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("10.00"), created_at=as_of - timedelta(days=10))
    TransactionItem.objects.create(transaction=tx_oos, product=p_oos, quantity=Decimal("1.0000"), unit_price=Decimal("10.00"), subtotal=Decimal("10.00"))

    result = get_inventory_turnover_analytics(as_of=as_of)
    item_map = {it["sku"]: it for it in result["all_items"]}

    assert item_map["FM-7D-SUB"]["status"] == "MODERATE"
    assert item_map["FM-7D-HIT"]["status"] == "FAST_MOVING"

    assert item_map["FM-30D-SUB"]["status"] == "MODERATE"
    assert item_map["FM-30D-HIT"]["status"] == "FAST_MOVING"

    assert item_map["FM-RATIO-SUB"]["status"] == "MODERATE"
    assert item_map["FM-RATIO-HIT"]["status"] == "FAST_MOVING"

    assert item_map["FM-OOS"]["turnover_ratio"] == 1.0
    assert item_map["FM-OOS"]["status"] == "FAST_MOVING"


@pytest.mark.django_db
def test_adversarial_inactive_isolation_and_no_leakage():
    """
    Ensure inactive products do not leak into:
    1. fast_moving
    2. dead_stock
    3. all_items
    4. dead_stock_tied_capital
    Even when transactions exist for inactive products.
    """
    now = timezone.now()

    # Inactive product with high sales (would otherwise be FAST_MOVING)
    p_inact_sales = Product.objects.create(
        sku="INACT-SALES",
        name="Discontinued Cola",
        stock_quantity=Decimal("50.0000"),
        wholesale_cost=Decimal("100.00"),
        retail_price=Decimal("120.00"),
        is_active=False,
    )
    tx = Transaction.objects.create(transaction_type=Transaction.TYPE_CASH, total_amount=Decimal("500.00"), created_at=now - timedelta(days=1))
    TransactionItem.objects.create(transaction=tx, product=p_inact_sales, quantity=Decimal("50.0000"), unit_price=Decimal("10.00"), subtotal=Decimal("500.00"))

    # Inactive product with 0 sales and high stock value (would otherwise be huge DEAD_STOCK tied capital)
    p_inact_dead = Product.objects.create(
        sku="INACT-DEAD",
        name="Archived Antique",
        stock_quantity=Decimal("10.0000"),
        wholesale_cost=Decimal("5000.00"),
        retail_price=Decimal("6000.00"),
        is_active=False,
    )

    result = get_inventory_turnover_analytics(as_of=now)
    assert result["all_items"] == []
    assert result["fast_moving"] == []
    assert result["dead_stock"] == []
    assert result["fast_moving_count"] == 0
    assert result["dead_stock_count"] == 0
    assert result["dead_stock_tied_capital"] == Decimal("0.00")


@pytest.mark.django_db
def test_adversarial_as_of_string_parsing_formats():
    """
    Stress-test as_of string parsing with various valid and tricky formats:
    - ISO 8601 with '+08:00'
    - Space-encoded '+08:00' (query param decode '2026-06-15 12:00:00+08:00')
    - UTC 'Z' format
    - Date-only string '2026-06-15'
    - None (defaults to current time)
    """
    prod = Product.objects.create(sku="PARSE-01", name="Parse Product", stock_quantity=Decimal("10.0000"), wholesale_cost=Decimal("10.00"), retail_price=Decimal("15.00"))

    # 1. ISO with offset
    r1 = get_inventory_turnover_analytics(as_of="2026-06-15T12:00:00+08:00")
    assert r1["as_of"].year == 2026
    assert r1["as_of"].month == 6

    # 2. Query param space decode
    r2 = get_inventory_turnover_analytics(as_of="2026-06-15 12:00:00+08:00")
    assert r2["as_of"].year == 2026
    assert r2["as_of"].month == 6

    # 3. UTC format
    r3 = get_inventory_turnover_analytics(as_of="2026-06-15T12:00:00Z")
    assert r3["as_of"].year == 2026
    assert r3["as_of"].tzinfo is not None

    # 4. Date only
    r4 = get_inventory_turnover_analytics(as_of="2026-06-15")
    assert r4["as_of"].year == 2026
    assert r4["as_of"].month == 6
    assert r4["as_of"].day == 15

    # 5. None
    r5 = get_inventory_turnover_analytics(as_of=None)
    assert isinstance(r5["as_of"], datetime)


@pytest.mark.django_db
def test_adversarial_multi_transaction_aggregation_and_tingi(api_client):
    """
    Stress-test aggregation across multiple transactions with tingi quantities:
    - 5 small transactions within 7 days: 0.25, 0.50, 0.75, 1.50, 2.00 = 5.00 units
    - 3 transactions between day 8 and day 28: 5.00, 7.50, 2.50 = 15.00 units
    Total 7d = 5.00, total 30d = 20.00.
    Since sales_30d >= 20.00, product must be FAST_MOVING.
    """
    as_of = datetime(2026, 8, 1, 12, 0, 0, tzinfo=dt_timezone.utc)
    prod = Product.objects.create(
        sku="TINGI-01",
        name="Repacked Cooking Oil 100ml",
        stock_quantity=Decimal("15.0000"),
        wholesale_cost=Decimal("8.00"),
        retail_price=Decimal("12.00"),
    )

    # 5 transactions in 7d
    qtys_7d = [Decimal("0.2500"), Decimal("0.5000"), Decimal("0.7500"), Decimal("1.5000"), Decimal("2.0000")]
    for i, q in enumerate(qtys_7d):
        tx = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=q * Decimal("12.00"),
            created_at=as_of - timedelta(days=i + 1),
        )
        TransactionItem.objects.create(transaction=tx, product=prod, quantity=q, unit_price=Decimal("12.00"), subtotal=q * Decimal("12.00"))

    # 3 transactions between 8d and 28d
    qtys_mid = [(10, Decimal("5.0000")), (18, Decimal("7.5000")), (25, Decimal("2.5000"))]
    for days_ago, q in qtys_mid:
        tx = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=q * Decimal("12.00"),
            created_at=as_of - timedelta(days=days_ago),
        )
        TransactionItem.objects.create(transaction=tx, product=prod, quantity=q, unit_price=Decimal("12.00"), subtotal=q * Decimal("12.00"))

    result = get_inventory_turnover_analytics(as_of=as_of)
    assert len(result["all_items"]) == 1
    item = result["all_items"][0]

    assert item["sales_7d"] == Decimal("5.00")
    assert item["sales_30d"] == Decimal("20.00")
    assert item["daily_velocity_7d"] == round(5.0 / 7.0, 2)  # 0.71
    assert item["daily_velocity_30d"] == round(20.0 / 30.0, 2)  # 0.67
    assert item["status"] == "FAST_MOVING"
    assert item["turnover_ratio"] == round(20.0 / 15.0, 2)  # 1.33


@pytest.mark.django_db
def test_adversarial_api_turnover_with_as_of_permutations(api_client):
    """
    Test API endpoint /api/analytics/turnover handling of:
    - as_of with ISO date
    - as_of with URL encoded space
    - verify serialized output keys and types
    """
    now = timezone.now()
    p = Product.objects.create(
        sku="API-TEST-PERM",
        name="Permutation Cookie",
        stock_quantity=Decimal("20.0000"),
        wholesale_cost=Decimal("5.00"),
        retail_price=Decimal("8.00"),
    )

    # Call with standard ISO
    iso_time = now.isoformat()
    resp = api_client.get(f"/api/analytics/turnover?as_of={iso_time}")
    assert resp.status_code == 200
    data = resp.json()
    assert "fast_moving" in data
    assert "dead_stock" in data
    assert "all_items" in data
    assert "all_skus" in data
    assert data["dead_stock_count"] == 1

    # Call with space-decoded offset "+00:00" -> " 00:00"
    space_time = iso_time.replace("+", "%20")
    resp_space = api_client.get(f"/api/analytics/turnover?as_of={space_time}")
    assert resp_space.status_code == 200
    assert resp_space.json()["dead_stock_count"] == 1

