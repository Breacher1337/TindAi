import time
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.models import Product, Transaction, TransactionItem
from core.services.analytics import get_inventory_turnover_analytics


@pytest.fixture
def client():
    return Client()


# =============================================================================
# 1. API as_of Query Parameter Permutations Stress Tests
# =============================================================================

@pytest.mark.django_db
class TestApiAsOfPermutations:
    """Stress-test API endpoint GET /api/analytics/turnover with diverse as_of formats."""

    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.ref_time = datetime(2026, 6, 15, 12, 0, 0, tzinfo=dt_timezone.utc)

        # Active product sold near ref_time
        self.prod = Product.objects.create(
            sku="ADV-ASOF-01",
            name="Adversarial Test Noodle",
            wholesale_cost=Decimal("15.00"),
            retail_price=Decimal("20.00"),
            stock_quantity=Decimal("30.0000"),
            category="Instant Food",
            is_active=True,
        )

        # Transaction 2 days before ref_time
        tx_near = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("200.00"),
            created_at=self.ref_time - timedelta(days=2),
        )
        TransactionItem.objects.create(
            transaction=tx_near,
            product=self.prod,
            quantity=Decimal("10.0000"),
            unit_price=Decimal("20.00"),
            subtotal=Decimal("200.00"),
        )

        # Transaction 10 days after ref_time (in future relative to ref_time)
        tx_future = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("300.00"),
            created_at=self.ref_time + timedelta(days=10),
        )
        TransactionItem.objects.create(
            transaction=tx_future,
            product=self.prod,
            quantity=Decimal("15.0000"),
            unit_price=Decimal("20.00"),
            subtotal=Decimal("300.00"),
        )

    def test_as_of_empty_defaults_to_now(self, client):
        """No as_of query parameter should succeed and use current time."""
        resp = client.get("/api/analytics/turnover")
        assert resp.status_code == 200
        data = resp.json()
        assert "as_of" in data
        assert "fast_moving" in data
        assert "dead_stock" in data
        assert "all_items" in data

    def test_as_of_iso_zulu_utc(self, client):
        """ISO timestamp with 'Z' suffix (e.g. 2026-06-15T12:00:00Z)."""
        iso_z = "2026-06-15T12:00:00Z"
        resp = client.get(f"/api/analytics/turnover?as_of={iso_z}")
        assert resp.status_code == 200
        data = resp.json()
        item = data["all_items"][0]
        # At ref_time, only the tx 2 days before is within window (10 units), future tx (15 units) is excluded
        assert Decimal(str(item["sales_7d"])) == Decimal("10.00")
        assert Decimal(str(item["sales_30d"])) == Decimal("10.00")

    def test_as_of_iso_with_plus_offset(self, client):
        """ISO timestamp with +08:00 timezone offset (URL-encoded %2B)."""
        # 2026-06-15T20:00:00+08:00 is exactly 2026-06-15T12:00:00Z
        iso_offset = "2026-06-15T20:00:00%2B08:00"
        resp = client.get(f"/api/analytics/turnover?as_of={iso_offset}")
        assert resp.status_code == 200
        data = resp.json()
        item = data["all_items"][0]
        assert Decimal(str(item["sales_7d"])) == Decimal("10.00")
        assert Decimal(str(item["sales_30d"])) == Decimal("10.00")

    def test_as_of_space_decoded_plus(self, client):
        """
        When clients send literal '+' in query string without %2B,
        WSGI servers decode it to space: '2026-06-15T20:00:00 08:00'.
        The backend must gracefully normalize space back to '+' and parse.
        """
        raw_str = "2026-06-15T20:00:00 08:00"
        resp = client.get("/api/analytics/turnover", {"as_of": raw_str})
        assert resp.status_code == 200
        data = resp.json()
        item = data["all_items"][0]
        assert Decimal(str(item["sales_7d"])) == Decimal("10.00")
        assert Decimal(str(item["sales_30d"])) == Decimal("10.00")

    def test_as_of_date_only_format(self, client):
        """Date-only format: 2026-06-15."""
        resp = client.get("/api/analytics/turnover?as_of=2026-06-15")
        assert resp.status_code == 200
        data = resp.json()
        assert "all_items" in data

    def test_as_of_space_separated_datetime(self, client):
        """Space-separated datetime: '2026-06-15 12:00:00Z'."""
        resp = client.get("/api/analytics/turnover", {"as_of": "2026-06-15 12:00:00Z"})
        assert resp.status_code == 200
        data = resp.json()
        item = data["all_items"][0]
        assert Decimal(str(item["sales_7d"])) == Decimal("10.00")

    @pytest.mark.parametrize(
        "invalid_val",
        [
            "not-a-datetime",
            "99999-99-99",
            "undefined",
            "null",
            "",
            "   ",
            "!!!@@@###",
        ],
    )
    def test_as_of_non_matching_invalid_string_graceful_fallback(self, client, invalid_val):
        """
        Syntactically non-matching invalid as_of parameters gracefully fallback to timezone.now().
        """
        resp = client.get(f"/api/analytics/turnover?as_of={invalid_val}")
        assert resp.status_code == 200
        data = resp.json()
        assert "as_of" in data
        assert "all_items" in data
        assert data["fast_moving_count"] >= 0

    @pytest.mark.parametrize(
        "calendar_invalid_val",
        [
            "2026-02-31T00:00:00Z",  # February 31
            "2026-04-31T12:00:00Z",  # April 31
            "2026-13-01T00:00:00Z",  # Month 13
            "2026-01-01T25:00:00Z",  # Hour 25
            "2026-01-01T12:75:00Z",  # Minute 75
        ],
    )
    def test_as_of_calendar_out_of_range_reproduces_unhandled_500_bug(self, client, calendar_invalid_val):
        """
        Calendar-out-of-range strings match Django's regex in parse_datetime,
        and now gracefully fall back to 200 instead of crashing with HTTP 500.
        """
        c = Client(raise_request_exception=False)
        resp = c.get(f"/api/analytics/turnover?as_of={calendar_invalid_val}")
        assert resp.status_code == 200, f"Expected 200 graceful fallback, got {resp.status_code}"

    @pytest.mark.parametrize(
        "calendar_invalid_val",
        [
            "2026-02-31T00:00:00Z",
            "2026-04-31T12:00:00Z",
            "2026-13-01T00:00:00Z",
        ],
    )
    def test_as_of_calendar_out_of_range_should_gracefully_fallback(self, client, calendar_invalid_val):
        """
        SPEC REQUIREMENT: Dispatch ordered graceful handling of invalid datetime strings.
        Now passes cleanly after wrapping parse_datetime in try/except.
        """
        resp = client.get(f"/api/analytics/turnover?as_of={calendar_invalid_val}")
        assert resp.status_code == 200


# =============================================================================
# 2. Inactive Product Exclusion Tests
# =============================================================================

@pytest.mark.django_db
class TestInactiveProductExclusion:
    """Ensure inactive products are strictly excluded from all turnover analytics metrics and views."""

    def test_inactive_products_excluded_from_service_and_api_and_view(self, client):
        now = timezone.now()

        # Active product with zero sales -> dead stock
        p_active_dead = Product.objects.create(
            sku="ACT-DEAD",
            name="Active Stale Crackers",
            wholesale_cost=Decimal("10.00"),
            retail_price=Decimal("15.00"),
            stock_quantity=Decimal("5.0000"),
            category="Snacks",
            is_active=True,
        )

        # Inactive product with zero sales and high stock value
        p_inact_dead = Product.objects.create(
            sku="INACT-DEAD",
            name="Deactivated Antique Wine",
            wholesale_cost=Decimal("500.00"),
            retail_price=Decimal("700.00"),
            stock_quantity=Decimal("10.0000"),
            category="Wine",
            is_active=False,
        )

        # Inactive product with high transaction sales
        p_inact_active_sales = Product.objects.create(
            sku="INACT-SALES",
            name="Deactivated Hot Cigarettes",
            wholesale_cost=Decimal("80.00"),
            retail_price=Decimal("100.00"),
            stock_quantity=Decimal("50.0000"),
            category="Tobacco",
            is_active=False,
        )
        tx = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("5000.00"),
            created_at=now - timedelta(days=1),
        )
        TransactionItem.objects.create(
            transaction=tx,
            product=p_inact_active_sales,
            quantity=Decimal("50.0000"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("5000.00"),
        )

        # 1. Service check
        res = get_inventory_turnover_analytics()
        all_skus = [it["sku"] for it in res["all_items"]]
        dead_skus = [it["sku"] for it in res["dead_stock"]]
        fast_skus = [it["sku"] for it in res["fast_moving"]]

        assert "ACT-DEAD" in all_skus
        assert "ACT-DEAD" in dead_skus
        assert "INACT-DEAD" not in all_skus
        assert "INACT-DEAD" not in dead_skus
        assert "INACT-SALES" not in all_skus
        assert "INACT-SALES" not in fast_skus

        # Tied capital should only reflect ACT-DEAD (5 * 10 = 50.00), NOT INACT-DEAD (5000.00)
        assert res["dead_stock_tied_capital"] == Decimal("50.00")

        # 2. API check
        api_resp = client.get("/api/analytics/turnover")
        assert api_resp.status_code == 200
        api_data = api_resp.json()
        api_all_skus = [it["sku"] for it in api_data["all_items"]]
        assert "INACT-DEAD" not in api_all_skus
        assert "INACT-SALES" not in api_all_skus
        assert Decimal(str(api_data["dead_stock_tied_capital"])) == Decimal("50.00")

        # 3. HTML View check
        view_resp = client.get("/analytics/")
        assert view_resp.status_code == 200
        assert view_resp.context["turnover"]["dead_stock_tied_capital"] == Decimal("50.00")
        html = view_resp.content.decode("utf-8")
        assert "ACT-DEAD" in html
        assert "INACT-DEAD" not in html
        assert "INACT-SALES" not in html
        assert "₱50.00 na nakatenggang puhunan" in html


# =============================================================================
# 3. Large Catalog Scale & Query Count (No N+1) Stress Tests
# =============================================================================

@pytest.mark.django_db
class TestCatalogScaleAndQueryCount:
    """Empirically verify performance and absence of N+1 query explosion across 150+ products."""

    def test_query_count_is_constant_with_large_catalog(self, client):
        now = timezone.now()

        # Seed 150 active products and 30 inactive products
        products = []
        for i in range(150):
            products.append(
                Product(
                    sku=f"SCALE-ACT-{i:03d}",
                    name=f"Active Catalog Item {i:03d}",
                    wholesale_cost=Decimal("25.00"),
                    retail_price=Decimal("30.00"),
                    stock_quantity=Decimal("15.0000"),
                    category="Bulk Category",
                    is_active=True,
                )
            )
        for i in range(30):
            products.append(
                Product(
                    sku=f"SCALE-INACT-{i:03d}",
                    name=f"Inactive Catalog Item {i:03d}",
                    wholesale_cost=Decimal("50.00"),
                    retail_price=Decimal("60.00"),
                    stock_quantity=Decimal("20.0000"),
                    category="Bulk Category",
                    is_active=False,
                )
            )
        Product.objects.bulk_create(products)

        # Seed transactions for a subset of products (50 transactions)
        all_active = list(Product.objects.filter(is_active=True))
        txs = []
        for i in range(50):
            txs.append(
                Transaction(
                    transaction_type=Transaction.TYPE_CASH,
                    total_amount=Decimal("300.00"),
                    created_at=now - timedelta(days=i % 25),
                )
            )
        Transaction.objects.bulk_create(txs)

        saved_txs = list(Transaction.objects.all()[:50])
        tx_items = []
        for i, tx in enumerate(saved_txs):
            tx_items.append(
                TransactionItem(
                    transaction=tx,
                    product=all_active[i],
                    quantity=Decimal("10.0000"),
                    unit_price=Decimal("30.00"),
                    subtotal=Decimal("300.00"),
                )
            )
        TransactionItem.objects.bulk_create(tx_items)

        # 1. Profile get_inventory_turnover_analytics query count
        with CaptureQueriesContext(connection) as queries_ctx:
            t0 = time.perf_counter()
            res = get_inventory_turnover_analytics()
            t_service = time.perf_counter() - t0

        service_queries = len(queries_ctx.captured_queries)
        # Exactly 3 queries: 7d TransactionItem agg, 30d TransactionItem agg, Product query
        assert service_queries <= 3, f"Expected <= 3 queries, got {service_queries}"
        assert t_service < 0.5, f"Service took too long: {t_service:.3f}s"
        assert len(res["all_items"]) == 150

        # 2. Profile analytics_view query count and render duration
        with CaptureQueriesContext(connection) as queries_view_ctx:
            t0 = time.perf_counter()
            resp = client.get("/analytics/")
            t_view = time.perf_counter() - t0

        assert resp.status_code == 200
        view_queries = len(queries_view_ctx.captured_queries)
        # Even with financial analytics + turnover analytics + session/user checks, queries must be <= 15
        assert view_queries <= 15, f"Suspected N+1 query explosion: executed {view_queries} queries"
        assert t_view < 1.0, f"View render took too long: {t_view:.3f}s"

        content = resp.content.decode("utf-8")
        assert "Takbo ng Imbentaryo / Turnover Analytics" in content


# =============================================================================
# 4. Business Domain Edge Cases & Boundary Precision Tests
# =============================================================================

@pytest.mark.django_db
class TestBusinessDomainEdgeCases:
    """Stress-test numerical boundaries, zero division, negative inventory, and exact timestamps."""

    def test_negative_stock_quantity_tied_capital(self):
        """Negative inventory (e.g. overselling / negative adjustment) must not cause negative tied capital."""
        p = Product.objects.create(
            sku="NEG-001",
            name="Negative Stock Item",
            wholesale_cost=Decimal("50.00"),
            retail_price=Decimal("60.00"),
            stock_quantity=Decimal("-10.0000"),
            is_active=True,
        )
        res = get_inventory_turnover_analytics()
        item = res["all_items"][0]
        assert item["stock_value"] == Decimal("0.00")
        assert res["dead_stock_tied_capital"] == Decimal("0.00")

    def test_zero_stock_with_sales_turnover_ratio(self):
        """Zero stock quantity with positive sales must avoid ZeroDivisionError."""
        now = timezone.now()
        p = Product.objects.create(
            sku="ZERO-STOCK-01",
            name="Sold Out Item",
            wholesale_cost=Decimal("10.00"),
            retail_price=Decimal("15.00"),
            stock_quantity=Decimal("0.0000"),
            is_active=True,
        )
        tx = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("150.00"),
            created_at=now - timedelta(days=5),
        )
        TransactionItem.objects.create(
            transaction=tx,
            product=p,
            quantity=Decimal("10.0000"),
            unit_price=Decimal("15.00"),
            subtotal=Decimal("150.00"),
        )
        res = get_inventory_turnover_analytics()
        item = res["all_items"][0]
        assert item["status"] == "FAST_MOVING"
        assert item["turnover_ratio"] == 1.0

    def test_exact_window_boundary_timestamps(self):
        """
        Verify boundary conditions:
        - Exactly at as_of - 7 days: included in 7d
        - 1 second before as_of - 7 days: excluded from 7d, included in 30d
        - Exactly at as_of - 30 days: included in 30d
        - 1 second before as_of - 30 days: excluded from 30d
        - Exactly at as_of: included in both
        - 1 second after as_of: excluded from both
        """
        fixed_as_of = datetime(2026, 8, 1, 12, 0, 0, tzinfo=dt_timezone.utc)
        p = Product.objects.create(
            sku="BOUND-01",
            name="Boundary Item",
            wholesale_cost=Decimal("10.00"),
            retail_price=Decimal("15.00"),
            stock_quantity=Decimal("100.0000"),
            is_active=True,
        )

        # 1. Exactly at 7d boundary (fixed_as_of - 7d)
        tx_7d_exact = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("15.00"),
            created_at=fixed_as_of - timedelta(days=7),
        )
        TransactionItem.objects.create(transaction=tx_7d_exact, product=p, quantity=Decimal("1.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("15.00"))

        # 2. 1 second before 7d boundary
        tx_7d_minus_1s = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("15.00"),
            created_at=fixed_as_of - timedelta(days=7, seconds=1),
        )
        TransactionItem.objects.create(transaction=tx_7d_minus_1s, product=p, quantity=Decimal("2.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("30.00"))

        # 3. Exactly at 30d boundary (fixed_as_of - 30d)
        tx_30d_exact = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("15.00"),
            created_at=fixed_as_of - timedelta(days=30),
        )
        TransactionItem.objects.create(transaction=tx_30d_exact, product=p, quantity=Decimal("4.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("60.00"))

        # 4. 1 second before 30d boundary
        tx_30d_minus_1s = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("15.00"),
            created_at=fixed_as_of - timedelta(days=30, seconds=1),
        )
        TransactionItem.objects.create(transaction=tx_30d_minus_1s, product=p, quantity=Decimal("8.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("120.00"))

        # 5. Exactly at as_of
        tx_as_of_exact = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("15.00"),
            created_at=fixed_as_of,
        )
        TransactionItem.objects.create(transaction=tx_as_of_exact, product=p, quantity=Decimal("16.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("240.00"))

        # 6. 1 second after as_of (future)
        tx_future = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("15.00"),
            created_at=fixed_as_of + timedelta(seconds=1),
        )
        TransactionItem.objects.create(transaction=tx_future, product=p, quantity=Decimal("32.0000"), unit_price=Decimal("15.00"), subtotal=Decimal("480.00"))

        res = get_inventory_turnover_analytics(as_of=fixed_as_of)
        item = res["all_items"][0]

        # 7d window includes: tx_as_of_exact (16) + tx_7d_exact (1) = 17
        assert item["sales_7d"] == Decimal("17.00")

        # 30d window includes: tx_as_of_exact (16) + tx_7d_exact (1) + tx_7d_minus_1s (2) + tx_30d_exact (4) = 23
        # Excludes: tx_30d_minus_1s (8) and tx_future (32)
        assert item["sales_30d"] == Decimal("23.00")
