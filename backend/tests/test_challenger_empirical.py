"""
Adversarial Code Challenger Empirical Test Suite.
Verifies:
1. Concurrency and Atomicity (transaction rollbacks on stock failure & credit limit breach).
2. PuLP Knapsack optimality, diversity, and stress testing across random product subsets.
3. Financial Analytics integrity (empty store resilience, zero division guards, period filtering).
"""

import random
from datetime import timedelta
from decimal import Decimal
import pytest
from django.urls import reverse
from django.utils import timezone
from core.models import Product, Customer, CustomerPayment, Transaction, TransactionItem
from core.services.knapsack import solve_restock_knapsack
from core.services.analytics import get_financial_analytics


# =============================================================================
# 1. Concurrency and Atomicity: Transaction Rollbacks & Limit Guards
# =============================================================================

@pytest.mark.django_db
def test_atomicity_multi_item_stock_failure_rollback_api(api_client):
    """
    Empirical Challenge: In a multi-item checkout where item 1 has sufficient stock
    but item 2 fails stock validation, the entire transaction MUST roll back.
    Item 1 stock MUST NOT be decremented.
    """
    prod_a = Product.objects.create(
        sku="CHAL-STK-001",
        name="Product A Sufficient Stock",
        wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("10.00"),
        reorder_point=2,
    )
    prod_b = Product.objects.create(
        sku="CHAL-STK-002",
        name="Product B Insufficient Stock",
        wholesale_cost=Decimal("20.00"),
        retail_price=Decimal("25.00"),
        stock_quantity=Decimal("1.00"),
        reorder_point=2,
    )

    initial_tx_count = Transaction.objects.count()
    initial_item_count = TransactionItem.objects.count()

    # Payload: Buy 3 of A (sufficient: 10 >= 3), and 5 of B (insufficient: 1 < 5)
    payload = {
        "transaction_type": "CASH",
        "items": [
            {"product_id": prod_a.id, "quantity": 3},
            {"product_id": prod_b.id, "quantity": 5},
        ],
        "notes": "Adversarial partial stock failure"
    }

    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 400
    assert "Insufficient stock" in res.json().get("detail", "")

    # Verification of Atomicity: Prod A must remain 10.00, NOT 7.00!
    prod_a.refresh_from_db()
    prod_b.refresh_from_db()
    assert prod_a.stock_quantity == Decimal("10.00"), (
        f"DATA CORRUPTION: Product A stock was decremented to {prod_a.stock_quantity} on failed transaction!"
    )
    assert prod_b.stock_quantity == Decimal("1.00")

    # No transactions or items should have been committed
    assert Transaction.objects.count() == initial_tx_count
    assert TransactionItem.objects.count() == initial_item_count


@pytest.mark.django_db
def test_atomicity_utang_credit_limit_breach_rollback_api(api_client):
    """
    Empirical Challenge: When an Utang transaction causes customer debt to exceed
    the credit limit, stock decrement MUST be rolled back, customer balance
    MUST NOT change, and no Transaction or items should be created.
    """
    customer = Customer.objects.create(
        name="Adversarial Utang Customer",
        credit_limit=Decimal("500.00"),
        debt_balance=Decimal("450.00"),
        is_active=True,
    )
    prod = Product.objects.create(
        sku="CHAL-UTG-001",
        name="Premium Coffee Box",
        wholesale_cost=Decimal("80.00"),
        retail_price=Decimal("100.00"),
        stock_quantity=Decimal("10.00"),
        reorder_point=2,
    )

    initial_tx_count = Transaction.objects.count()

    # Debt would become 450 + 100 = 550 > 500 (credit limit)
    payload = {
        "transaction_type": "UTANG",
        "customer_id": customer.id,
        "items": [
            {"product_id": prod.id, "quantity": 1}
        ],
        "notes": "Attempt to breach credit ceiling"
    }

    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 400
    assert "Credit Limit" in res.json().get("detail", "")

    # Verify rollback: stock and debt balance must be completely unchanged
    prod.refresh_from_db()
    customer.refresh_from_db()

    assert prod.stock_quantity == Decimal("10.00"), (
        f"DATA CORRUPTION: Product stock decremented to {prod.stock_quantity} despite credit rejection!"
    )
    assert customer.debt_balance == Decimal("450.00"), (
        f"DATA CORRUPTION: Customer debt altered to {customer.debt_balance} despite credit rejection!"
    )
    assert Transaction.objects.count() == initial_tx_count


@pytest.mark.django_db
def test_atomicity_utang_credit_limit_breach_rollback_view(api_client):
    """
    Empirical Challenge: Test credit limit rejection in the UI checkout view (/pos/checkout).
    Ensures stock is not decremented and customer balance is not modified.
    """
    customer = Customer.objects.create(
        name="UI Debt Customer",
        credit_limit=Decimal("300.00"),
        debt_balance=Decimal("250.00"),
        is_active=True,
    )
    prod = Product.objects.create(
        sku="CHAL-POS-001",
        name="Sack of Sugar 1kg",
        wholesale_cost=Decimal("50.00"),
        retail_price=Decimal("70.00"),
        stock_quantity=Decimal("15.00"),
        reorder_point=3,
    )

    # Setup session cart: 1 unit = ₱70.00. 250 + 70 = 320 > 300
    session = api_client.session
    session['cart'] = {
        str(prod.id): {
            'name': prod.name,
            'price': '70.00',
            'unit': 'kg',
            'qty': 1,
        }
    }
    session.save()

    res = api_client.post(reverse('checkout'), {
        'payment_method': 'UTANG',
        'customer_id': customer.id,
    })
    assert res.status_code == 400
    assert b"Lagpas sa Credit Limit" in res.content

    prod.refresh_from_db()
    customer.refresh_from_db()
    assert prod.stock_quantity == Decimal("15.00")
    assert customer.debt_balance == Decimal("250.00")
    assert Transaction.objects.filter(customer=customer).count() == 0


@pytest.mark.django_db
def test_atomicity_multi_item_tingi_and_pack_rollback(api_client):
    """
    Empirical Challenge: Cart with 1 packaged item and 1 fractional tingi item.
    Third item fails stock guard. Fractional stock deduction on tingi item must roll back.
    """
    pack_prod = Product.objects.create(
        sku="CHAL-TNG-001",
        name="Coffee Box (20s)",
        wholesale_cost=Decimal("160.00"),
        retail_price=Decimal("10.00"),
        stock_quantity=Decimal("5.0000"),
        reorder_point=1,
    )
    tingi_prod = Product.objects.create(
        sku="CHAL-TNG-002",
        name="Cigarette Pack (20s)",
        wholesale_cost=Decimal("150.00"),
        retail_price=Decimal("10.00"),
        stock_quantity=Decimal("3.0000"),
        reorder_point=1,
    )
    out_prod = Product.objects.create(
        sku="CHAL-TNG-003",
        name="Out of Stock Soda",
        wholesale_cost=Decimal("20.00"),
        retail_price=Decimal("25.00"),
        stock_quantity=Decimal("0.0000"),
        reorder_point=1,
    )

    payload = {
        "transaction_type": "CASH",
        "items": [
            {"product_id": pack_prod.id, "quantity": 1},
            {"product_id": tingi_prod.id, "quantity": 0.05},  # Fractional tingi deduction
            {"product_id": out_prod.id, "quantity": 1},       # Will fail!
        ],
        "notes": "Fractional tingi rollback challenge"
    }

    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 400

    pack_prod.refresh_from_db()
    tingi_prod.refresh_from_db()
    out_prod.refresh_from_db()

    assert pack_prod.stock_quantity == Decimal("5.0000")
    assert tingi_prod.stock_quantity == Decimal("3.0000")
    assert out_prod.stock_quantity == Decimal("0.0000")


@pytest.mark.django_db
def test_atomicity_sequential_race_and_limit_exhaustion(api_client):
    """
    Empirical Challenge: Verify transaction atomicity and race prevention during
    sequential stock exhaustion and credit limit exhaustion.
    1. Product with stock=1.0000:
       - Purchase 1 succeeds (stock -> 0.0000).
       - Immediate subsequent purchase fails (HTTP 400), stock stays 0.0000.
    2. Multi-item cart containing another item (stock=5) + exhausted product:
       - Must fail with HTTP 400.
       - Other item's stock must remain 5.0000 (atomic rollback).
    3. Credit limit exhaustion:
       - Customer with ₱500 limit, ₱480 balance.
       - ₱20 purchase brings balance to exact ceiling ₱500.
       - Subsequent ₱0.01 purchase must fail (HTTP 400).
       - Stock of requested product must NOT be decremented.
    """
    prod_single = Product.objects.create(
        sku="CHAL-RACE-001",
        name="Last Can of Soda",
        wholesale_cost=Decimal("15.00"),
        retail_price=Decimal("20.00"),
        stock_quantity=Decimal("1.0000"),
        reorder_point=1,
    )
    prod_other = Product.objects.create(
        sku="CHAL-RACE-002",
        name="Abundant Snack Pack",
        wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("5.0000"),
        reorder_point=1,
    )
    customer = Customer.objects.create(
        name="Limit Exhaustion Customer",
        credit_limit=Decimal("500.00"),
        debt_balance=Decimal("480.00"),
        is_active=True,
    )

    # Step 1: First purchase drains the single item to exactly 0
    res1 = api_client.post("/api/transactions", data={
        "transaction_type": "CASH",
        "items": [{"product_id": prod_single.id, "quantity": 1}],
        "notes": "Drain to zero"
    }, content_type="application/json")
    assert res1.status_code == 200
    prod_single.refresh_from_db()
    assert prod_single.stock_quantity == Decimal("0.0000")

    # Step 2: Immediate follow-up purchase attempt must be rejected
    res2 = api_client.post("/api/transactions", data={
        "transaction_type": "CASH",
        "items": [{"product_id": prod_single.id, "quantity": 1}],
        "notes": "Attempt over-drain"
    }, content_type="application/json")
    assert res2.status_code == 400
    assert "Insufficient stock" in res2.json().get("detail", "")
    prod_single.refresh_from_db()
    assert prod_single.stock_quantity == Decimal("0.0000")

    # Step 3: Multi-item bundle containing abundant item + exhausted item
    res3 = api_client.post("/api/transactions", data={
        "transaction_type": "CASH",
        "items": [
            {"product_id": prod_other.id, "quantity": 2},
            {"product_id": prod_single.id, "quantity": 1},
        ],
        "notes": "Bundle failure rollback"
    }, content_type="application/json")
    assert res3.status_code == 400
    prod_other.refresh_from_db()
    assert prod_other.stock_quantity == Decimal("5.0000"), (
        f"ROLLBACK FAILURE: prod_other stock was not restored! Got {prod_other.stock_quantity}"
    )

    # Step 4: Utang credit exact boundary fill (480 + 20 = 500)
    prod_filler = Product.objects.create(
        sku="CHAL-RACE-003",
        name="Exact 20 Peso Item",
        wholesale_cost=Decimal("15.00"),
        retail_price=Decimal("20.00"),
        stock_quantity=Decimal("10.0000"),
        reorder_point=1,
    )
    res4 = api_client.post("/api/transactions", data={
        "transaction_type": "UTANG",
        "customer_id": customer.id,
        "items": [{"product_id": prod_filler.id, "quantity": 1}],
        "notes": "Fill to exact limit"
    }, content_type="application/json")
    assert res4.status_code == 200
    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("500.00")

    # Step 5: Utang purchase when already at ceiling -> must reject and roll back stock
    res5 = api_client.post("/api/transactions", data={
        "transaction_type": "UTANG",
        "customer_id": customer.id,
        "items": [{"product_id": prod_filler.id, "quantity": 1}],
        "notes": "Attempt beyond limit"
    }, content_type="application/json")
    assert res5.status_code == 400
    assert "Credit Limit" in res5.json().get("detail", "")

    # Invariant: debt balance remains 500.00, prod_filler stock remains 9.0000 (decremented only by res4)
    customer.refresh_from_db()
    prod_filler.refresh_from_db()
    assert customer.debt_balance == Decimal("500.00")
    assert prod_filler.stock_quantity == Decimal("9.0000")






# =============================================================================
# 2. PuLP Knapsack Optimality and Diversity Stress Harness
# =============================================================================

@pytest.mark.django_db
def test_knapsack_fuzz_random_subsets_and_budgets(fmcg_catalog_50):
    """
    Empirical Challenge: Stress-test PuLP solver with 50 randomized trials:
    - Random subsets of 1 to 50 FMCG products from catalog.json
    - Random capital budgets ranging from ₱50.00 to ₱15,000.00
    - Verify integer pack outputs, budget non-overrun, status optimality,
      and categorized groupings integrity.
    """
    rng = random.Random(42)  # Deterministic seed for reproducible stress test
    all_products = list(fmcg_catalog_50)
    assert len(all_products) >= 20

    trials_count = 50
    for trial_idx in range(trials_count):
        # Pick random subset size between 1 and len(all_products)
        subset_size = rng.randint(1, len(all_products))
        candidates = rng.sample(all_products, subset_size)

        # Random budget between ₱50.00 and ₱15,000.00
        budget_val = round(rng.uniform(50.0, 15000.0), 2)
        budget = Decimal(str(budget_val))

        result = solve_restock_knapsack(candidates, budget=budget)

        # 1. Total spent must NEVER exceed budget
        total_spent = Decimal(str(result["total_spent"]))
        remaining_budget = Decimal(str(result["remaining_budget"]))
        assert total_spent <= budget, (
            f"Trial {trial_idx}: Budget overrun! Spent {total_spent} > budget {budget}"
        )
        assert total_spent + remaining_budget == budget, (
            f"Trial {trial_idx}: Budget accounting mismatch! {total_spent} + {remaining_budget} != {budget}"
        )

        # 2. Solver status must be Optimal or Feasible
        assert result["solver_status"] in ("Optimal", "Feasible")

        items = result["items"]
        categorized = result["categorized_items"]

        # 3. Integer pack counts & mathematical consistency
        computed_spent = Decimal("0.00")
        computed_profit = Decimal("0.00")
        for it in items:
            packs = it["packs_to_buy"]
            assert isinstance(packs, int), f"Trial {trial_idx}: Non-integer pack count {packs}"
            assert packs > 0, f"Trial {trial_idx}: Zero or negative packs recommended {packs}"
            assert it["packs"] == packs

            unit_cost = Decimal(str(it["unit_cost"]))
            subtotal = Decimal(str(it["subtotal"]))
            assert subtotal == (unit_cost * packs).quantize(Decimal("0.01")), (
                f"Trial {trial_idx}: Subtotal mismatch for {it['name']}: {subtotal} != {unit_cost * packs}"
            )
            computed_spent += subtotal
            computed_profit += Decimal(str(it["expected_profit"]))

        assert computed_spent == total_spent

        # 4. Diversity & Categorized grouping partition
        total_in_categories = sum(len(cat_items) for cat_items in categorized.values())
        assert total_in_categories == len(items), (
            f"Trial {trial_idx}: Categorized items count {total_in_categories} != total items {len(items)}"
        )

        # Verify each item is placed into its proper category key
        for cat_name, cat_items in categorized.items():
            assert len(cat_items) > 0
            for item in cat_items:
                assert item["category"] == cat_name


@pytest.mark.django_db
def test_knapsack_unaffordable_tight_budget():
    """
    Empirical Challenge: When available revolving budget is strictly less than
    the wholesale cost of any available candidate, solver must cleanly return 0 items
    without crashing or spending anything.
    """
    expensive_prod = Product.objects.create(
        sku="CHAL-EXP-001",
        name="Case of Premium Powder 50s",
        wholesale_cost=Decimal("1200.00"),
        retail_price=Decimal("1500.00"),
        stock_quantity=1,
        reorder_point=5,
        category="Dairy & Milk",
    )

    budget = Decimal("500.00")  # Less than 1200.00 cost
    result = solve_restock_knapsack([expensive_prod], budget=budget)

    assert result["total_spent"] == Decimal("0.00")
    assert result["remaining_budget"] == Decimal("500.00")
    assert result["expected_profit"] == Decimal("0.00")
    assert len(result["items"]) == 0
    assert result["categorized_items"] == {}
    assert result["solver_status"] == "Optimal"


@pytest.mark.django_db
def test_knapsack_empty_candidates_resilience():
    """
    Empirical Challenge: Passing an empty list or queryset of products to
    the knapsack optimizer should cleanly return empty results without error.
    """
    result = solve_restock_knapsack([], budget=Decimal("3000.00"))
    assert result["total_spent"] == Decimal("0.00")
    assert result["remaining_budget"] == Decimal("3000.00")
    assert result["expected_profit"] == Decimal("0.00")
    assert len(result["items"]) == 0
    assert result["categorized_items"] == {}


@pytest.mark.django_db
def test_knapsack_upper_bound_constraint_honored():
    """
    Empirical Challenge: PuLP bounded knapsack has an upper bound u_i = min(10, max(1, 2*rop - stock)).
    Even with an enormous budget (e.g. ₱1,000,000), solver must not recommend buying infinite packs.
    """
    prod = Product.objects.create(
        sku="CHAL-BOUND-001",
        name="Instant Coffee Sachet Pack",
        wholesale_cost=Decimal("50.00"),
        retail_price=Decimal("70.00"),
        stock_quantity=2,
        reorder_point=4,  # 2*4 - 2 = 6 max packs
        category="Coffee & Hot Drinks",
    )

    huge_budget = Decimal("1000000.00")
    result = solve_restock_knapsack([prod], budget=huge_budget)

    assert len(result["items"]) == 1
    recommended_packs = result["items"][0]["packs_to_buy"]
    assert recommended_packs <= 10, f"Exceeded maximum upper bound of 10: {recommended_packs}"
    assert recommended_packs == 6, f"Expected upper bound 6 (2*4 - 2), got {recommended_packs}"


# =============================================================================
# 3. Financial Analytics Integrity: Empty Store & Period Filtering
# =============================================================================

@pytest.mark.django_db
def test_analytics_completely_empty_store_endpoints(api_client):
    """
    Empirical Challenge: In a brand-new store with:
    - 0 Products
    - 0 Customers
    - 0 Transactions
    - 0 Customer Payments
    Verify:
    1. get_financial_analytics does not raise ZeroDivisionError for any period.
    2. API /api/analytics returns HTTP 200 with clean zeros.
    3. View /analytics/ renders HTML template cleanly with HTTP 200.
    """
    # 1. Direct service call
    for period in ("today", "week", "month", "all"):
        data = get_financial_analytics(period=period)
        assert data["gross_revenue"] == Decimal("0.00")
        assert data["cogs"] == Decimal("0.00")
        assert data["net_profit"] == Decimal("0.00")
        assert data["profit_margin_pct"] == 0.0
        assert data["cash_on_hand"] == Decimal("0.00")
        assert data["uncollected_utang"] == Decimal("0.00")
        assert data["total_transactions_count"] == 0
        assert data["period"] == period

    # 2. REST API endpoint
    api_res = api_client.get("/api/analytics?period=all")
    assert api_res.status_code == 200
    res_json = api_res.json()
    assert Decimal(str(res_json["gross_revenue"])) == Decimal("0.00")
    assert res_json["profit_margin_pct"] == 0.0

    # 3. UI Web View
    view_res = api_client.get(reverse('analytics'))
    assert view_res.status_code == 200
    assert b"Malinis na Tubo (Net Profit)" in view_res.content
    assert b"0.00" in view_res.content


@pytest.mark.django_db
def test_analytics_period_filtering_time_windows():
    """
    Empirical Challenge: Verify time-based filtering for 'today', 'week', 'month', 'all'.
    Transactions and repayments seeded at:
      - T1: Today (0 days ago) -> ₱500 cash sale, ₱50 repayment
      - T2: 3 days ago (within week) -> ₱300 cash sale, ₱30 repayment
      - T3: 14 days ago (within month, outside week) -> ₱200 cash sale, ₱20 repayment
      - T4: 45 days ago (outside month, only in 'all') -> ₱100 cash sale, ₱10 repayment
    """
    now = timezone.now()
    customer = Customer.objects.create(
        name="Period Test Customer",
        credit_limit=Decimal("5000.00"),
        debt_balance=Decimal("500.00"),
        is_active=True,
    )
    prod = Product.objects.create(
        sku="CHAL-TIME-001",
        name="Time Test Item",
        wholesale_cost=Decimal("5.00"),
        retail_price=Decimal("10.00"),
        stock_quantity=1000,
        reorder_point=10,
    )

    time_offsets = [
        (0, Decimal("500.00"), Decimal("50.00")),   # Today
        (3, Decimal("300.00"), Decimal("30.00")),   # 3 days ago
        (14, Decimal("200.00"), Decimal("20.00")),  # 14 days ago
        (45, Decimal("100.00"), Decimal("10.00")),  # 45 days ago
    ]

    for days_ago, sale_amt, rep_amt in time_offsets:
        target_time = now - timedelta(days=days_ago)

        # Create transaction
        tx = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=sale_amt,
            payment_status=Transaction.STATUS_PAID,
        )
        # Update created_at to past time
        Transaction.objects.filter(id=tx.id).update(created_at=target_time)

        # Create line item
        TransactionItem.objects.create(
            transaction=tx,
            product=prod,
            quantity=sale_amt / Decimal("10.00"),
            unit_price=Decimal("10.00"),
            cost_price=Decimal("5.00"),
            subtotal=sale_amt,
        )

        # Create repayment
        payment = CustomerPayment.objects.create(
            customer=customer,
            amount=rep_amt,
            created_at=target_time,
        )

    # 1. Filter: 'today' -> only T1 (₱500 sale, ₱50 rep)
    analytics_today = get_financial_analytics(period="today")
    assert analytics_today["gross_revenue"] == Decimal("500.00")
    assert analytics_today["repayments_total"] == Decimal("50.00")
    assert analytics_today["cash_on_hand"] == Decimal("550.00")
    assert analytics_today["total_transactions_count"] == 1

    # 2. Filter: 'week' -> T1 + T2 (₱500 + ₱300 = ₱800, rep: ₱50 + ₱30 = ₱80)
    analytics_week = get_financial_analytics(period="week")
    assert analytics_week["gross_revenue"] == Decimal("800.00")
    assert analytics_week["repayments_total"] == Decimal("80.00")
    assert analytics_week["cash_on_hand"] == Decimal("880.00")
    assert analytics_week["total_transactions_count"] == 2

    # 3. Filter: 'month' -> T1 + T2 + T3 (₱800 + ₱200 = ₱1000, rep: ₱80 + ₱20 = ₱100)
    analytics_month = get_financial_analytics(period="month")
    assert analytics_month["gross_revenue"] == Decimal("1000.00")
    assert analytics_month["repayments_total"] == Decimal("100.00")
    assert analytics_month["cash_on_hand"] == Decimal("1100.00")
    assert analytics_month["total_transactions_count"] == 3

    # 4. Filter: 'all' -> All 4 transactions (₱1000 + ₱100 = ₱1100, rep: ₱100 + ₱10 = ₱110)
    analytics_all = get_financial_analytics(period="all")
    assert analytics_all["gross_revenue"] == Decimal("1100.00")
    assert analytics_all["repayments_total"] == Decimal("110.00")
    assert analytics_all["cash_on_hand"] == Decimal("1210.00")
    assert analytics_all["total_transactions_count"] == 4


@pytest.mark.django_db
def test_analytics_unrecognized_period_fallback():
    """
    Empirical Challenge: Unrecognized period values ('bogus', '', None) must
    fallback safely to 'all' without raising exceptions.
    """
    for bad_period in ("bogus", "", "   ", None, "yearly"):
        data = get_financial_analytics(period=bad_period)
        assert data["period"] == "all"
        assert "gross_revenue" in data
        assert "profit_margin_pct" in data


@pytest.mark.django_db
def test_analytics_loss_making_store_profit_margin():
    """
    Empirical Challenge: When goods are sold at a loss (cost > price),
    net profit is negative. Verify that profit margin percentage is correctly
    computed as negative and does not crash or raise errors.
    """
    prod_loss = Product.objects.create(
        sku="CHAL-LOSS-001",
        name="Loss Leader Promo Item",
        wholesale_cost=Decimal("20.00"),
        retail_price=Decimal("15.00"),  # Sold at ₱5 loss per unit
        stock_quantity=100,
        reorder_point=5,
    )

    tx = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("150.00"),
        payment_status=Transaction.STATUS_PAID,
    )
    TransactionItem.objects.create(
        transaction=tx,
        product=prod_loss,
        quantity=Decimal("10"),
        unit_price=Decimal("15.00"),
        cost_price=Decimal("20.00"),
        subtotal=Decimal("150.00"),
    )

    data = get_financial_analytics(period="all")
    # Gross revenue: 150.00, COGS: 200.00, Net profit: -50.00
    assert data["gross_revenue"] == Decimal("150.00")
    assert data["cogs"] == Decimal("200.00")
    assert data["net_profit"] == Decimal("-50.00")
    # Margin %: (-50 / 150) * 100 = -33.33%
    assert data["profit_margin_pct"] == -33.33
