import pytest
from decimal import Decimal

try:
    from core.services.analytics import get_financial_analytics
except (ImportError, ModuleNotFoundError):
    get_financial_analytics = None


@pytest.mark.django_db
def test_financial_dashboard_strict_liquidity_isolation(mixed_sales_day):
    """
    ORIGINAL_REQUEST.md Acceptance Criteria §Analytics:
    "Test seeds mixed Cash and Utang sales; verifies the dashboard
    strictly isolates cash liquidity from debt."

    Interface Contract (PROJECT.md § core.services.analytics):
    get_financial_analytics(period='all') -> dict:
      gross_revenue: Decimal       # Cash Sales + Utang Sales
      cogs: Decimal                # Sum of (quantity * cost_price)
      net_profit: Decimal          # Gross Revenue - COGS
      profit_margin_pct: float     # (Net Profit / Gross Revenue) * 100
      cash_on_hand: Decimal        # Physical cash: Cash Sales + Customer Repayments
      uncollected_utang: Decimal   # Total outstanding customer debt balance
      cash_sales_total: Decimal
      utang_sales_total: Decimal
      repayments_total: Decimal
      total_transactions_count: int
    """
    if get_financial_analytics is None:
        pytest.fail("core.services.analytics.get_financial_analytics is not implemented yet (Milestone M4)")

    data = get_financial_analytics(period='all')
    expected = mixed_sales_day

    gross_revenue = Decimal(str(data["gross_revenue"]))
    cogs = Decimal(str(data["cogs"]))
    net_profit = Decimal(str(data["net_profit"]))
    cash_on_hand = Decimal(str(data["cash_on_hand"]))
    uncollected_utang = Decimal(str(data["uncollected_utang"]))
    cash_sales = Decimal(str(data["cash_sales_total"]))
    utang_sales = Decimal(str(data["utang_sales_total"]))
    repayments = Decimal(str(data["repayments_total"]))

    # 1. Gross Revenue = Cash Sales + Utang Sales
    assert gross_revenue == expected['expected_gross_revenue']  # ₱1,600.00
    assert gross_revenue == cash_sales + utang_sales
    assert cash_sales == Decimal("1200.00")
    assert utang_sales == Decimal("400.00")

    # 2. COGS = Sum(quantity * wholesale_cost)
    assert cogs == expected['expected_cogs']  # ₱1,200.00

    # 3. Net Profit = Gross Revenue - COGS
    assert net_profit == expected['expected_net_profit']  # ₱400.00
    assert net_profit == gross_revenue - cogs

    # 4. Profit Margin %
    assert abs(data["profit_margin_pct"] - 25.0) < 0.01

    # 5. Strict Liquidity Isolation: Physical Cash-on-Hand vs Uncollected Utang
    # Physical Cash-on-Hand = Cash Sales (₱1,200) + Cash Repayments (₱150) = ₱1,350.00
    assert repayments == Decimal("150.00")
    assert cash_on_hand == Decimal("1350.00"), (
        f"Expected cash-on-hand ₱1,350.00, got {cash_on_hand}"
    )

    # CRITICAL: Cash-on-Hand must NOT equal Gross Revenue (uncollected credit is NOT cash)
    assert cash_on_hand != gross_revenue, (
        "LIQUIDITY COMMINGLING DETECTED: Physical cash-on-hand was confused with gross sales!"
    )

    # Uncollected Utang must isolate customer debt
    assert uncollected_utang >= Decimal("250.00")


@pytest.mark.django_db
def test_analytics_cogs_exact_sum(mixed_sales_day):
    """
    Verifies that Cost of Goods Sold (COGS) is calculated strictly as
    sum(quantity * cost_price) for all line items sold.
    """
    if get_financial_analytics is None:
        pytest.fail("core.services.analytics.get_financial_analytics is not implemented yet (Milestone M4)")

    data = get_financial_analytics(period='all')
    expected_cogs = mixed_sales_day['expected_cogs']
    actual_cogs = Decimal(str(data["cogs"]))
    assert actual_cogs == expected_cogs


@pytest.mark.django_db
def test_empty_store_zero_division_resilience(db):
    """
    Verifies system stability when store has zero transactions, zero sales,
    and zero customer debt. Must return clean zeros without ZeroDivisionError.
    """
    if get_financial_analytics is None:
        pytest.fail("core.services.analytics.get_financial_analytics is not implemented yet (Milestone M4)")

    data = get_financial_analytics(period='all')

    assert Decimal(str(data["gross_revenue"])) == Decimal("0.00")
    assert Decimal(str(data["cogs"])) == Decimal("0.00")
    assert Decimal(str(data["net_profit"])) == Decimal("0.00")
    assert float(data["profit_margin_pct"]) == 0.0
    assert Decimal(str(data["cash_on_hand"])) == Decimal("0.00")
    assert Decimal(str(data["uncollected_utang"])) == Decimal("0.00")
    assert data["total_transactions_count"] == 0


@pytest.mark.django_db
def test_analytics_period_filtering(mixed_sales_day):
    """
    Verifies analytics service handles all required period scopes:
    'today', 'week', 'month', 'all' without SQL errors.
    """
    if get_financial_analytics is None:
        pytest.fail("core.services.analytics.get_financial_analytics is not implemented yet (Milestone M4)")

    for period in ('today', 'week', 'month', 'all'):
        data = get_financial_analytics(period=period)
        assert "gross_revenue" in data
        assert "cash_on_hand" in data
        assert "uncollected_utang" in data
