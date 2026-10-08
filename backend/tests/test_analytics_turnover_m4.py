import pytest
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from django.utils import timezone
from django.test import Client

from core.models import Product, Transaction, TransactionItem
from core.services.analytics import get_inventory_turnover_analytics


@pytest.fixture
def api_client():
    return Client()


@pytest.mark.django_db
def test_inventory_turnover_empty_catalog():
    """Verify stability and clean zero state when catalog has no active products."""
    result = get_inventory_turnover_analytics()

    assert result["fast_moving"] == []
    assert result["dead_stock"] == []
    assert result["all_items"] == []
    assert result["all_skus"] == []
    assert result["fast_moving_count"] == 0
    assert result["dead_stock_count"] == 0
    assert result["dead_stock_tied_capital"] == Decimal("0.00")
    assert isinstance(result["as_of"], datetime)


@pytest.mark.django_db
def test_inventory_turnover_dead_stock_zero_movement():
    """
    Exact requirement: Classify items with 0 movement in 30 days as DEAD_STOCK.
    Verify tied-up capital calculation and sorting by stock_value descending.
    """
    prod_a = Product.objects.create(
        sku="DEAD-001",
        name="Old Stock Sardines",
        wholesale_cost=Decimal("20.00"),
        retail_price=Decimal("25.00"),
        stock_quantity=Decimal("10.0000"),
        category="Canned Goods",
        is_active=True,
    )
    prod_b = Product.objects.create(
        sku="DEAD-002",
        name="Unsold Premium Corned Beef",
        wholesale_cost=Decimal("50.00"),
        retail_price=Decimal("60.00"),
        stock_quantity=Decimal("5.0000"),
        category="Canned Goods",
        is_active=True,
    )
    # Product with 0 stock and 0 sales
    prod_c = Product.objects.create(
        sku="DEAD-003",
        name="Zero Stock Dormant Candy",
        wholesale_cost=Decimal("2.00"),
        retail_price=Decimal("3.00"),
        stock_quantity=Decimal("0.0000"),
        category="Candy",
        is_active=True,
    )

    result = get_inventory_turnover_analytics()

    assert result["dead_stock_count"] == 3
    assert result["fast_moving_count"] == 0

    # Tied-up capital = (10 * 20.00) + (5 * 50.00) + (0 * 2.00) = 200 + 250 + 0 = 450.00
    assert result["dead_stock_tied_capital"] == Decimal("450.00")

    # Sorted by stock_value descending: prod_b (250.00) then prod_a (200.00) then prod_c (0.00)
    dead_skus = [item["sku"] for item in result["dead_stock"]]
    assert dead_skus == ["DEAD-002", "DEAD-001", "DEAD-003"]

    for item in result["dead_stock"]:
        assert item["status"] == "DEAD_STOCK"
        assert item["status_label"] == "Patay na Stock"
        assert item["sales_30d"] == Decimal("0.00")
        assert item["sales_7d"] == Decimal("0.00")


@pytest.mark.django_db
def test_inventory_turnover_inactive_products_excluded():
    """Inactive products (e.g. archived drafts) must be excluded from turnover analytics."""
    Product.objects.create(
        sku="INACTIVE-001",
        name="Archived Cigarettes",
        wholesale_cost=Decimal("100.00"),
        retail_price=Decimal("120.00"),
        stock_quantity=Decimal("20.0000"),
        category="Tobacco",
        is_active=False,
    )
    result = get_inventory_turnover_analytics()
    assert result["all_items"] == []
    assert result["dead_stock_count"] == 0
    assert result["dead_stock_tied_capital"] == Decimal("0.00")


@pytest.mark.django_db
def test_inventory_turnover_velocity_and_fast_moving_classification():
    """
    Verify:
    1. sales_7d and sales_30d quantity aggregation from TransactionItem.
    2. daily_velocity_7d and daily_velocity_30d rates.
    3. Classification rules for FAST_MOVING:
       - sales_7d >= 10
       - sales_30d >= 20
       - turnover_ratio >= 0.5
    """
    now = timezone.now()

    # F1: High 7-day velocity (14 units in last 3 days -> sales_7d >= 10)
    p_fast_7d = Product.objects.create(
        sku="FAST-001",
        name="Lucky Me Kalamansi",
        wholesale_cost=Decimal("12.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("50.0000"),
        category="Instant Noodles",
    )
    tx_recent = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("210.00"),
        created_at=now - timedelta(days=2),
    )
    TransactionItem.objects.create(
        transaction=tx_recent,
        product=p_fast_7d,
        quantity=Decimal("14.0000"),
        unit_price=Decimal("15.00"),
        subtotal=Decimal("210.00"),
    )

    # F2: High 30-day volume (25 units sold 15 days ago -> sales_30d >= 20)
    p_fast_30d = Product.objects.create(
        sku="FAST-002",
        name="San Miguel Pale Pilsen",
        wholesale_cost=Decimal("45.00"),
        retail_price=Decimal("55.00"),
        stock_quantity=Decimal("30.0000"),
        category="Beverages",
    )
    tx_mid = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("1375.00"),
        created_at=now - timedelta(days=15),
    )
    TransactionItem.objects.create(
        transaction=tx_mid,
        product=p_fast_30d,
        quantity=Decimal("25.0000"),
        unit_price=Decimal("55.00"),
        subtotal=Decimal("1375.00"),
    )

    # F3: High turnover ratio (stock = 10, sold = 6 in 30d -> turnover_ratio = 0.6 >= 0.5)
    p_fast_ratio = Product.objects.create(
        sku="FAST-003",
        name="Bear Brand Powdered Milk 33g",
        wholesale_cost=Decimal("11.00"),
        retail_price=Decimal("14.00"),
        stock_quantity=Decimal("10.0000"),
        category="Milk",
    )
    tx_ratio = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("84.00"),
        created_at=now - timedelta(days=10),
    )
    TransactionItem.objects.create(
        transaction=tx_ratio,
        product=p_fast_ratio,
        quantity=Decimal("6.0000"),
        unit_price=Decimal("14.00"),
        subtotal=Decimal("84.00"),
    )

    result = get_inventory_turnover_analytics(as_of=now)

    assert result["fast_moving_count"] == 3
    fast_map = {item["sku"]: item for item in result["fast_moving"]}

    # Verify F1 metrics
    item_f1 = fast_map["FAST-001"]
    assert item_f1["status"] == "FAST_MOVING"
    assert item_f1["status_label"] == "Mabilis Mabenta"
    assert item_f1["sales_7d"] == Decimal("14.00")
    assert item_f1["sales_30d"] == Decimal("14.00")
    assert item_f1["daily_velocity_7d"] == 2.0  # 14 / 7
    assert round(item_f1["daily_velocity_30d"], 2) == 0.47  # 14 / 30

    # Verify F2 metrics
    item_f2 = fast_map["FAST-002"]
    assert item_f2["status"] == "FAST_MOVING"
    assert item_f2["sales_7d"] == Decimal("0.00")
    assert item_f2["sales_30d"] == Decimal("25.00")
    assert item_f2["daily_velocity_7d"] == 0.0
    assert round(item_f2["daily_velocity_30d"], 2) == 0.83  # 25 / 30

    # Verify F3 metrics
    item_f3 = fast_map["FAST-003"]
    assert item_f3["status"] == "FAST_MOVING"
    assert item_f3["turnover_ratio"] == 0.6

    # Verify fast_moving list sorted by sales_30d descending: FAST-002 (25) > FAST-001 (14) > FAST-003 (6)
    assert [it["sku"] for it in result["fast_moving"]] == ["FAST-002", "FAST-001", "FAST-003"]


@pytest.mark.django_db
def test_inventory_turnover_moderate_movement():
    """Verify items with movement but below fast-moving thresholds are classified as MODERATE."""
    now = timezone.now()
    prod_mod = Product.objects.create(
        sku="MOD-001",
        name="Vinegar Bottle 350ml",
        wholesale_cost=Decimal("18.00"),
        retail_price=Decimal("22.00"),
        stock_quantity=Decimal("100.0000"),
        category="Condiments",
    )
    # Sold 3 units 12 days ago:
    # sales_7d = 0 < 10, sales_30d = 3 < 20, turnover_ratio = 3/100 = 0.03 < 0.5
    tx = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("66.00"),
        created_at=now - timedelta(days=12),
    )
    TransactionItem.objects.create(
        transaction=tx,
        product=prod_mod,
        quantity=Decimal("3.0000"),
        unit_price=Decimal("22.00"),
        subtotal=Decimal("66.00"),
    )

    result = get_inventory_turnover_analytics(as_of=now)
    assert result["fast_moving_count"] == 0
    assert result["dead_stock_count"] == 0

    item = result["all_items"][0]
    assert item["status"] == "MODERATE"
    assert item["status_label"] == "Katamtaman"
    assert item["sales_30d"] == Decimal("3.00")


@pytest.mark.django_db
def test_inventory_turnover_deterministic_as_of_window():
    """
    Verify historical simulation determinism:
    - Transactions outside [as_of - 30d, as_of] must be excluded.
    - Transactions outside [as_of - 7d, as_of] must be excluded from 7d.
    - Future transactions relative to as_of must be excluded.
    - Naive datetime is safely converted to timezone aware.
    """
    fixed_as_of = datetime(2026, 6, 15, 12, 0, 0, tzinfo=dt_timezone.utc)

    prod = Product.objects.create(
        sku="DET-001",
        name="Deterministic Coffee Pack",
        wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("12.00"),
        stock_quantity=Decimal("50.0000"),
        category="Beverages",
    )

    # T1: 3 days before as_of (within 7d and 30d) -> 5 units
    tx1 = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("60.00"),
        created_at=fixed_as_of - timedelta(days=3),
    )
    TransactionItem.objects.create(transaction=tx1, product=prod, quantity=Decimal("5.0000"), unit_price=Decimal("12.00"), subtotal=Decimal("60.00"))

    # T2: 20 days before as_of (outside 7d, within 30d) -> 8 units
    tx2 = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("96.00"),
        created_at=fixed_as_of - timedelta(days=20),
    )
    TransactionItem.objects.create(transaction=tx2, product=prod, quantity=Decimal("8.0000"), unit_price=Decimal("12.00"), subtotal=Decimal("96.00"))

    # T3: 40 days before as_of (outside 30d) -> 50 units (MUST NOT BE COUNTED)
    tx3 = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("600.00"),
        created_at=fixed_as_of - timedelta(days=40),
    )
    TransactionItem.objects.create(transaction=tx3, product=prod, quantity=Decimal("50.0000"), unit_price=Decimal("12.00"), subtotal=Decimal("600.00"))

    # T4: 2 days after as_of (in future relative to as_of) -> 30 units (MUST NOT BE COUNTED)
    tx4 = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("360.00"),
        created_at=fixed_as_of + timedelta(days=2),
    )
    TransactionItem.objects.create(transaction=tx4, product=prod, quantity=Decimal("30.0000"), unit_price=Decimal("12.00"), subtotal=Decimal("360.00"))

    # Execute with aware datetime
    result = get_inventory_turnover_analytics(as_of=fixed_as_of)
    item = result["all_items"][0]

    assert item["sales_7d"] == Decimal("5.00")
    assert item["sales_30d"] == Decimal("13.00")  # 5 + 8, excluding 50 and 30

    # Also test with naive datetime
    naive_as_of = datetime(2026, 6, 15, 12, 0, 0)
    result_naive = get_inventory_turnover_analytics(as_of=naive_as_of)
    item_naive = result_naive["all_items"][0]
    assert item_naive["sales_7d"] == Decimal("5.00")
    assert item_naive["sales_30d"] == Decimal("13.00")

    # Also test with date object (normalizes to datetime.min)
    date_as_of = date(2026, 6, 15)
    result_date = get_inventory_turnover_analytics(as_of=date_as_of)
    assert result_date["as_of"] is not None
    assert timezone.is_aware(result_date["as_of"])


@pytest.mark.django_db
def test_analytics_view_renders_turnover_html(client):
    """
    Verify analytics_view context supplies turnover data and
    backend/templates/analytics.html renders required Taglish turnover cards and tables.
    """
    now = timezone.now()

    # Create Fast-moving product
    p_fast = Product.objects.create(
        sku="FM-VIEW-01",
        name="Chippy BBQ 110g",
        wholesale_cost=Decimal("18.00"),
        retail_price=Decimal("24.00"),
        stock_quantity=Decimal("40.0000"),
        category="Snacks",
    )
    tx = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("360.00"),
        created_at=now - timedelta(days=1),
    )
    TransactionItem.objects.create(
        transaction=tx,
        product=p_fast,
        quantity=Decimal("15.0000"),
        unit_price=Decimal("24.00"),
        subtotal=Decimal("360.00"),
    )

    # Create Dead stock product
    p_dead = Product.objects.create(
        sku="DEAD-VIEW-01",
        name="Stale Biscuit Tin",
        wholesale_cost=Decimal("75.00"),
        retail_price=Decimal("95.00"),
        stock_quantity=Decimal("4.0000"),
        category="Biscuits",
    )

    resp = client.get("/analytics/")
    assert resp.status_code == 200

    content = resp.content.decode("utf-8")

    # Section header
    assert "Takbo ng Imbentaryo / Turnover Analytics" in content

    # Cards
    assert "Mabilis Mabenta" in content
    assert "Patay na Stock" in content

    # Tied-up capital highlight
    assert "na nakatenggang puhunan" in content
    assert "300.00" in content  # 4 * 75.00 = 300.00

    # Tables and SKU rows
    assert "FM-VIEW-01" in content
    assert "Chippy BBQ 110g" in content
    assert "DEAD-VIEW-01" in content
    assert "Stale Biscuit Tin" in content

    # Table column headers
    assert "7-Araw" in content
    assert "30-Araw" in content
    assert "Kasalukuyang Stock" in content
    assert "Halaga ng Puhunan" in content


@pytest.mark.django_db
def test_api_analytics_turnover_endpoint(api_client):
    """
    Verify GET /api/analytics/turnover endpoint schema validation and response structure.
    """
    now = timezone.now()

    p_fast = Product.objects.create(
        sku="API-FAST-01",
        name="Coke Mismo 290ml",
        wholesale_cost=Decimal("12.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("48.0000"),
        category="Beverages",
    )
    tx = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("300.00"),
        created_at=now - timedelta(days=2),
    )
    TransactionItem.objects.create(
        transaction=tx,
        product=p_fast,
        quantity=Decimal("20.0000"),
        unit_price=Decimal("15.00"),
        subtotal=Decimal("300.00"),
    )

    p_dead = Product.objects.create(
        sku="API-DEAD-01",
        name="Unsold Vinegar 1L",
        wholesale_cost=Decimal("35.00"),
        retail_price=Decimal("45.00"),
        stock_quantity=Decimal("6.0000"),
        category="Condiments",
    )

    resp = api_client.get("/api/analytics/turnover")
    assert resp.status_code == 200

    data = resp.json()
    assert "fast_moving" in data
    assert "dead_stock" in data
    assert "all_items" in data
    assert "fast_moving_count" in data
    assert "dead_stock_count" in data
    assert "dead_stock_tied_capital" in data
    assert "as_of" in data

    assert data["fast_moving_count"] == 1
    assert data["dead_stock_count"] == 1
    assert Decimal(str(data["dead_stock_tied_capital"])) == Decimal("210.00")  # 6 * 35.00

    fast_item = data["fast_moving"][0]
    assert fast_item["sku"] == "API-FAST-01"
    assert fast_item["status"] == "FAST_MOVING"
    assert fast_item["status_label"] == "Mabilis Mabenta"
    assert Decimal(str(fast_item["sales_30d"])) == Decimal("20.00")

    dead_item = data["dead_stock"][0]
    assert dead_item["sku"] == "API-DEAD-01"
    assert dead_item["status"] == "DEAD_STOCK"
    assert dead_item["status_label"] == "Patay na Stock"
    assert Decimal(str(dead_item["stock_value"])) == Decimal("210.00")

    # Test as_of query param filtering
    past_date_str = (now - timedelta(days=10)).isoformat()
    resp_past = api_client.get(f"/api/analytics/turnover?as_of={past_date_str}")
    assert resp_past.status_code == 200
    data_past = resp_past.json()
    # At 10 days ago, tx from 2 days ago did not exist yet, so both items have 0 sales
    assert data_past["fast_moving_count"] == 0
    assert data_past["dead_stock_count"] == 2


@pytest.mark.django_db
def test_inventory_turnover_contract_all_skus_and_fractional_units():
    """
    Verify:
    1. PROJECT.md interface contract: `all_skus` is present and matches `all_items`.
    2. Fractional inventory quantities (e.g. 2.5 boxes) correctly compute stock_value.
    3. Tie-breaker sorting for fast moving (sales_30d tie broken by sales_7d).
    """
    now = timezone.now()

    # Fractional stock item
    p_frac = Product.objects.create(
        sku="FRAC-001",
        name="Cooking Oil Large Tin",
        wholesale_cost=Decimal("150.00"),
        retail_price=Decimal("180.00"),
        stock_quantity=Decimal("2.5000"),  # 2.5 boxes
        category="Cooking Essentials",
    )

    # Item with same 30d sales as another, but higher 7d sales
    p_tie1 = Product.objects.create(
        sku="TIE-001",
        name="Instant Coffee 3-in-1",
        wholesale_cost=Decimal("6.00"),
        retail_price=Decimal("8.00"),
        stock_quantity=Decimal("50.0000"),
        category="Beverages",
    )
    tx_t1 = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("160.00"),
        created_at=now - timedelta(days=3),
    )
    TransactionItem.objects.create(
        transaction=tx_t1,
        product=p_tie1,
        quantity=Decimal("20.0000"),
        unit_price=Decimal("8.00"),
        subtotal=Decimal("160.00"),
    )

    p_tie2 = Product.objects.create(
        sku="TIE-002",
        name="Choco Drink 24g",
        wholesale_cost=Decimal("6.00"),
        retail_price=Decimal("8.00"),
        stock_quantity=Decimal("50.0000"),
        category="Beverages",
    )
    tx_t2 = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("160.00"),
        created_at=now - timedelta(days=20),
    )
    TransactionItem.objects.create(
        transaction=tx_t2,
        product=p_tie2,
        quantity=Decimal("20.0000"),
        unit_price=Decimal("8.00"),
        subtotal=Decimal("160.00"),
    )

    result = get_inventory_turnover_analytics()

    # 1. Contract alias
    assert "all_skus" in result
    assert result["all_skus"] == result["all_items"]

    # 2. Fractional stock value: 2.5 * 150.00 = 375.00
    dead_map = {item["sku"]: item for item in result["dead_stock"]}
    assert "FRAC-001" in dead_map
    assert dead_map["FRAC-001"]["stock_value"] == Decimal("375.00")

    # 3. Fast-moving tie-breaker: TIE-001 has 20 in 7d; TIE-002 has 0 in 7d.
    # Both have 20 in 30d. TIE-001 should come before TIE-002.
    fast_skus = [it["sku"] for it in result["fast_moving"]]
    assert fast_skus.index("TIE-001") < fast_skus.index("TIE-002")


@pytest.mark.django_db
def test_analytics_view_with_period_and_turnover(client):
    """
    Verify analytics_view works seamlessly with period query parameters (today, week, month)
    while consistently supplying turnover analytics.
    """
    for period in ("today", "week", "month", "all"):
        resp = client.get(f"/analytics/?period={period}")
        assert resp.status_code == 200
        assert "turnover" in resp.context
        assert "fast_moving_count" in resp.context
        assert "dead_stock_count" in resp.context
        assert "dead_stock_tied_capital" in resp.context

