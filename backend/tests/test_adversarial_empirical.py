import random
import pytest
from decimal import Decimal
from django.urls import reverse
from core.models import Product, Customer, CustomerPayment, Transaction, TransactionItem
from core.services.knapsack import solve_restock_knapsack
from core.services.analytics import get_financial_analytics


# =============================================================================
# R1: POS & TINGI FRACTIONAL STOCK & BOUNDARY STRESS TESTS
# =============================================================================

@pytest.mark.django_db
def test_pos_repeated_fractional_purchases_to_exact_zero(api_client):
    """
    R1 Stress Test:
    Initial stock: 1.0000 box (20 units/box -> 0.0500 box per tingi piece).
    Simulate 20 consecutive tingi purchases of 0.0500 box each.
    Verify:
    1. Each purchase decrements stock by exactly 0.0500 without floating-point drift.
    2. At step 20, stock reaches exactly Decimal('0.0000').
    3. Step 21 (attempt to buy 0.0500 or 0.0001 when stock is 0.0000) is REJECTED.
    4. Stock remains strictly non-negative (>= 0.0000).
    """
    box_product = Product.objects.create(
        sku="TINGI-STRESS-01",
        name="Chippy Barbecue 110g Box",
        wholesale_cost=Decimal("400.00"),
        retail_price=Decimal("24.00"),
        stock_quantity=Decimal("1.0000"),
        reorder_point=2,
        pack_unit="box (20s)",
        tingi_unit="piece",
        is_active=True,
    )

    fraction = Decimal("0.0500")

    # 20 consecutive checkouts
    for step in range(1, 21):
        session = api_client.session
        session['cart'] = {
            str(box_product.id): {
                'name': box_product.name,
                'price': '24.00',
                'unit': 'piece',
                'qty': '0.0500',
            }
        }
        session.save()

        res = api_client.post(reverse('checkout'), {'payment_method': 'CASH'})
        assert res.status_code in (200, 302), f"Checkout failed at step {step}"

        box_product.refresh_from_db()
        expected_remaining = Decimal("1.0000") - (fraction * step)
        assert box_product.stock_quantity == expected_remaining, (
            f"Step {step}: Expected {expected_remaining}, got {box_product.stock_quantity}"
        )

    # Verify final stock is exactly 0.0000
    assert box_product.stock_quantity == Decimal("0.0000")

    # Step 21: Attempt 21st checkout when stock is 0.0000
    session = api_client.session
    session['cart'] = {
        str(box_product.id): {
            'name': box_product.name,
            'price': '24.00',
            'unit': 'piece',
            'qty': '0.0500',
        }
    }
    session.save()

    res_21 = api_client.post(reverse('checkout'), {'payment_method': 'CASH'})
    box_product.refresh_from_db()
    # Must remain 0.0000, never drop negative
    assert box_product.stock_quantity == Decimal("0.0000"), (
        f"Stock dropped below zero: {box_product.stock_quantity}"
    )


@pytest.mark.django_db
def test_pos_sub_tingi_precision_and_exact_boundary(api_client):
    """
    R1 Stress Test: 4 decimal place precision boundary.
    Product stock = Decimal('0.0003').
    Buy 0.0001 -> stock becomes 0.0002.
    Buy 0.0002 -> stock becomes 0.0000.
    Attempt buy 0.0001 -> blocked.
    """
    prod = Product.objects.create(
        sku="TINGI-PREC-01",
        name="Micro Precision Item",
        wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("0.0003"),
        reorder_point=1,
    )

    # Purchase 0.0001 via API
    payload = {
        "transaction_type": "CASH",
        "items": [{"product_id": prod.id, "quantity": "0.0001"}]
    }
    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 200
    prod.refresh_from_db()
    assert prod.stock_quantity == Decimal("0.0002")

    # Purchase 0.0002 via API -> exact zero
    payload["items"] = [{"product_id": prod.id, "quantity": "0.0002"}]
    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 200
    prod.refresh_from_db()
    assert prod.stock_quantity == Decimal("0.0000")

    # Attempt purchase 0.0001 when stock is 0.0000 -> HTTP 400
    payload["items"] = [{"product_id": prod.id, "quantity": "0.0001"}]
    res_fail = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res_fail.status_code == 400
    prod.refresh_from_db()
    assert prod.stock_quantity == Decimal("0.0000")


@pytest.mark.django_db
def test_pos_negative_and_zero_quantity_rejection(api_client):
    """
    R1 Stress Test: Hostile checkout payloads with zero or negative quantity.
    Must be rejected with 400 or 422.
    """
    prod = Product.objects.create(
        sku="TEST-QTY-VAL",
        name="Quantity Validation Item",
        wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("20.00"),
        stock_quantity=Decimal("100.0000"),
    )

    # 1. Zero quantity
    res_zero = api_client.post(
        "/api/transactions",
        data={"transaction_type": "CASH", "items": [{"product_id": prod.id, "quantity": "0"}]},
        content_type="application/json"
    )
    assert res_zero.status_code in (400, 422)

    # 2. Negative quantity
    res_neg = api_client.post(
        "/api/transactions",
        data={"transaction_type": "CASH", "items": [{"product_id": prod.id, "quantity": "-5.0000"}]},
        content_type="application/json"
    )
    assert res_neg.status_code in (400, 422)

    # Stock unaffected
    prod.refresh_from_db()
    assert prod.stock_quantity == Decimal("100.0000")


# =============================================================================
# R2: UTANG CREDIT LIMIT & REPAYMENT STRESS TESTS
# =============================================================================

@pytest.mark.django_db
def test_utang_exact_credit_limit_boundary(api_client):
    """
    R2 Stress Test:
    Customer limit = ₱1,000.00, debt = ₱0.00.
    1. Purchase item of ₱1,000.00 on UTANG -> SUCCESS (debt == ₱1,000.00).
    2. Attempt purchase of ₱0.01 on UTANG -> REJECTED (exceeds limit 1000.01 > 1000.00).
    3. Make micro-repayment of ₱0.01 -> SUCCESS (debt becomes ₱999.99).
    4. Attempt purchase of ₱0.01 on UTANG -> SUCCESS (debt returns to ₱1,000.00).
    5. Attempt purchase of ₱0.01 on UTANG -> REJECTED.
    """
    customer = Customer.objects.create(
        name="Exact Limit Customer",
        credit_limit=Decimal("1000.00"),
        debt_balance=Decimal("0.00"),
        is_active=True,
    )
    prod_1000 = Product.objects.create(
        sku="TEST-LIMIT-1000",
        name="Bulk Sack Rice 25kg",
        wholesale_cost=Decimal("850.00"),
        retail_price=Decimal("1000.00"),
        stock_quantity=Decimal("5.0000"),
    )
    prod_cent = Product.objects.create(
        sku="TEST-LIMIT-CENT",
        name="Candy 1c",
        wholesale_cost=Decimal("0.00"),
        retail_price=Decimal("0.01"),
        stock_quantity=Decimal("100.0000"),
    )

    # 1. Exact limit purchase
    res1 = api_client.post(
        "/api/transactions",
        data={
            "transaction_type": "UTANG",
            "customer_id": customer.id,
            "items": [{"product_id": prod_1000.id, "quantity": 1}],
        },
        content_type="application/json"
    )
    assert res1.status_code == 200
    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("1000.00")

    # 2. Exceed limit by ₱0.01
    res2 = api_client.post(
        "/api/transactions",
        data={
            "transaction_type": "UTANG",
            "customer_id": customer.id,
            "items": [{"product_id": prod_cent.id, "quantity": 1}],
        },
        content_type="application/json"
    )
    assert res2.status_code == 400
    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("1000.00")

    # 3. Micro-repayment of ₱0.01
    res3 = api_client.post(
        f"/api/customers/{customer.id}/payments",
        data={"amount": "0.01", "notes": "Cent repayment"},
        content_type="application/json"
    )
    assert res3.status_code == 200
    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("999.99")

    # 4. Now ₱0.01 purchase fits exact limit again
    res4 = api_client.post(
        "/api/transactions",
        data={
            "transaction_type": "UTANG",
            "customer_id": customer.id,
            "items": [{"product_id": prod_cent.id, "quantity": 1}],
        },
        content_type="application/json"
    )
    assert res4.status_code == 200
    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("1000.00")

    # 5. Over limit again
    res5 = api_client.post(
        "/api/transactions",
        data={
            "transaction_type": "UTANG",
            "customer_id": customer.id,
            "items": [{"product_id": prod_cent.id, "quantity": 1}],
        },
        content_type="application/json"
    )
    assert res5.status_code == 400


@pytest.mark.django_db
def test_utang_100_consecutive_micro_repayments(api_client):
    """
    R2 Stress Test:
    Customer starts with ₱100.00 debt.
    Execute 100 consecutive ₱1.00 repayments.
    Verify:
    1. Balance decrements monotonically by ₱1.00 every time.
    2. At end, balance is exactly ₱0.00.
    3. Exactly 100 payment audit records created.
    4. 101st payment of ₱5.00 floors cleanly at ₱0.00 without negative balance.
    """
    customer = Customer.objects.create(
        name="Micro Repayer",
        credit_limit=Decimal("500.00"),
        debt_balance=Decimal("100.00"),
        is_active=True,
    )

    for i in range(1, 101):
        res = api_client.post(
            f"/api/customers/{customer.id}/payments",
            data={"amount": "1.00", "notes": f"Repayment #{i}"},
            content_type="application/json"
        )
        assert res.status_code == 200
        customer.refresh_from_db()
        expected = Decimal("100.00") - Decimal(str(i))
        assert customer.debt_balance == expected, f"Step {i}: expected {expected}, got {customer.debt_balance}"

    assert customer.debt_balance == Decimal("0.00")
    assert CustomerPayment.objects.filter(customer=customer).count() == 100

    # 101st payment when debt is 0.00
    res_extra = api_client.post(
        f"/api/customers/{customer.id}/payments",
        data={"amount": "5.00", "notes": "Overpayment"},
        content_type="application/json"
    )
    assert res_extra.status_code == 200
    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("0.00")


@pytest.mark.django_db
def test_utang_form_view_negative_and_zero_repayment(api_client):
    """
    R2 Stress Test: Test views.py utang_pay_action reject non-positive amounts.
    """
    customer = Customer.objects.create(
        name="Form Repay Customer",
        credit_limit=Decimal("500.00"),
        debt_balance=Decimal("200.00"),
        is_active=True,
    )

    # 1. Zero payment
    res_zero = api_client.post(reverse('utang_pay'), {'customer_id': customer.id, 'amount': '0.00'})
    assert res_zero.status_code == 400

    # 2. Negative payment
    res_neg = api_client.post(reverse('utang_pay'), {'customer_id': customer.id, 'amount': '-50.00'})
    assert res_neg.status_code == 400

    # 3. Invalid string
    res_inv = api_client.post(reverse('utang_pay'), {'customer_id': customer.id, 'amount': 'invalid_num'})
    assert res_inv.status_code == 400

    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("200.00")


# =============================================================================
# R3: RESTOCKING KNAPSACK SOLVER EXTREME BUDGET STRESS TESTS
# =============================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("budget_val", [
    Decimal("500.00"),
    Decimal("1000.00"),
    Decimal("25000.00"),
    Decimal("50000.00"),
])
def test_knapsack_extreme_budgets_invariants(mock_products_20, budget_val):
    """
    R3 Stress Test (Parent Orchestrator Mandate):
    "Stress-test PuLP solver with extreme budgets (₱500, ₱1,000, ₱25,000, ₱50,000)
    and verify total_spent <= budget is NEVER violated in any run."
    """
    result = solve_restock_knapsack(mock_products_20, budget=budget_val)

    total_spent = Decimal(str(result["total_spent"]))
    remaining = Decimal(str(result["remaining_budget"]))
    expected_profit = Decimal(str(result["expected_profit"]))

    # Core Invariant 1: total_spent <= budget
    assert total_spent <= budget_val, (
        f"VIOLATION: total_spent ({total_spent}) exceeded budget ({budget_val})!"
    )

    # Core Invariant 2: total_spent + remaining == budget
    assert total_spent + remaining == budget_val, (
        f"Sum mismatch: {total_spent} + {remaining} != {budget_val}"
    )

    # Core Invariant 3: remaining >= 0
    assert remaining >= Decimal("0.00")

    # Core Invariant 4: non-negative expected profit
    assert expected_profit >= Decimal("0.00")

    # Item consistency checks
    calc_spent = Decimal("0.00")
    for item in result["items"]:
        packs = item["packs_to_buy"]
        assert isinstance(packs, int)
        assert packs > 0
        cost = Decimal(str(item["unit_cost"]))
        subtotal = Decimal(str(item["subtotal"]))
        assert subtotal == (cost * packs).quantize(Decimal("0.01"))
        calc_spent += subtotal

    assert calc_spent == total_spent


@pytest.mark.django_db
def test_knapsack_unaffordable_low_budget(mock_products_20):
    """
    R3 Stress Test: Budget is ₱1.00 (cheapest wholesale cost in mock products is ₱9.50).
    Verify solver handles it gracefully: 0 items bought, 0 spent, remaining = ₱1.00.
    """
    result = solve_restock_knapsack(mock_products_20, budget=Decimal("1.00"))
    assert result["total_spent"] == Decimal("0.00")
    assert result["remaining_budget"] == Decimal("1.00")
    assert len(result["items"]) == 0
    assert result["expected_profit"] == Decimal("0.00")


@pytest.mark.django_db
def test_knapsack_monte_carlo_budget_stress_test(mock_products_20):
    """
    R3 Stress Test: 50 randomized budget levels between ₱50 and ₱60,000.
    Verify total_spent <= budget NEVER violated across any random run.
    """
    random.seed(42)
    for _ in range(50):
        # Generate random float budget with 2 decimals
        random_budget = Decimal(str(round(random.uniform(50.0, 60000.0), 2)))
        res = solve_restock_knapsack(mock_products_20, budget=random_budget)
        spent = Decimal(str(res["total_spent"]))
        assert spent <= random_budget, (
            f"FAILED on randomized budget {random_budget}: spent {spent}"
        )
        assert Decimal(str(res["remaining_budget"])) >= Decimal("0.00")
        assert spent + Decimal(str(res["remaining_budget"])) == random_budget


# =============================================================================
# R4: FINANCIAL ANALYTICS MATHEMATICAL INVARIANTS STRESS TESTS
# =============================================================================

@pytest.mark.django_db
def test_analytics_mathematical_invariants_across_complex_cycles(suki_customers):
    """
    R4 Stress Test:
    Verify strict invariants across multi-step transactions:
    1. Gross Revenue == Cash Sales + Utang Sales
    2. Net Profit == Gross Revenue - COGS
    3. Cash-on-Hand strictly independent of unpaid Utang debt
    4. Repayments increase Cash-on-Hand and decrease Uncollected Utang without modifying Gross Revenue.
    """
    # Create products with known margins
    p1 = Product.objects.create(
        sku="AN-P1", name="Product 1", wholesale_cost=Decimal("70.00"), retail_price=Decimal("100.00"), stock_quantity=100
    )
    p2 = Product.objects.create(
        sku="AN-P2", name="Product 2", wholesale_cost=Decimal("30.00"), retail_price=Decimal("50.00"), stock_quantity=100
    )

    c1 = suki_customers['maria']
    c1.debt_balance = Decimal("0.00")
    c1.credit_limit = Decimal("50000.00")
    c1.save()

    # Base check at zero state
    stats0 = get_financial_analytics('all')
    base_cash = stats0['cash_on_hand']

    # Step 1: Cash sale of 5x P1 (₱500, COGS ₱350)
    tx_cash = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("500.00"),
        payment_status=Transaction.STATUS_PAID,
    )
    TransactionItem.objects.create(
        transaction=tx_cash, product=p1, quantity=Decimal("5.0000"),
        unit_price=Decimal("100.00"), cost_price=Decimal("70.00"), subtotal=Decimal("500.00")
    )

    stats1 = get_financial_analytics('all')
    assert stats1['cash_sales_total'] == Decimal("500.00")
    assert stats1['utang_sales_total'] == Decimal("0.00")
    assert stats1['gross_revenue'] == Decimal("500.00")
    assert stats1['cogs'] == Decimal("350.00")
    assert stats1['net_profit'] == Decimal("150.00")  # 500 - 350
    assert stats1['cash_on_hand'] == base_cash + Decimal("500.00")
    expected_cash = stats1['cash_on_hand']

    # Step 2: Massive Utang sale of 100x P2 (₱5,000, COGS ₱3,000)
    # INVARIANT CHECK: Cash-on-Hand MUST NOT change!
    c1.debt_balance += Decimal("5000.00")
    c1.save()
    tx_utang = Transaction.objects.create(
        transaction_type=Transaction.TYPE_UTANG,
        customer=c1,
        total_amount=Decimal("5000.00"),
        payment_status=Transaction.STATUS_UNPAID,
    )
    TransactionItem.objects.create(
        transaction=tx_utang, product=p2, quantity=Decimal("100.0000"),
        unit_price=Decimal("50.00"), cost_price=Decimal("30.00"), subtotal=Decimal("5000.00")
    )

    stats2 = get_financial_analytics('all')

    # INVARIANT 1: Gross Revenue == Cash Sales + Utang Sales
    assert stats2['gross_revenue'] == stats2['cash_sales_total'] + stats2['utang_sales_total']
    assert stats2['gross_revenue'] == Decimal("5500.00")
    assert stats2['cash_sales_total'] == Decimal("500.00")
    assert stats2['utang_sales_total'] == Decimal("5000.00")

    # INVARIANT 2: Net Profit == Gross Revenue - COGS
    assert stats2['cogs'] == Decimal("3350.00")  # 350 + 3000
    assert stats2['net_profit'] == stats2['gross_revenue'] - stats2['cogs']
    assert stats2['net_profit'] == Decimal("2150.00")

    # INVARIANT 3: Cash-on-Hand strictly independent of unpaid Utang debt!
    # Unpaid ₱5,000 credit sale must NOT increase cash-on-hand!
    assert stats2['cash_on_hand'] == expected_cash, (
        f"LIQUIDITY LEAK: Cash-on-hand changed from {expected_cash} to {stats2['cash_on_hand']} "
        f"due to unpaid utang transaction!"
    )

    # Step 3: Customer pays ₱1,200 towards debt
    CustomerPayment.objects.create(customer=c1, amount=Decimal("1200.00"), notes="Partial bayad")
    c1.debt_balance -= Decimal("1200.00")
    c1.save()

    stats3 = get_financial_analytics('all')

    # Repayment increases Cash-on-Hand by exactly ₱1,200
    assert stats3['cash_on_hand'] == expected_cash + Decimal("1200.00")
    # Repayment does NOT increase Gross Revenue (it is not a new sale)
    assert stats3['gross_revenue'] == Decimal("5500.00")
    # Repayment total tracked
    assert stats3['repayments_total'] == Decimal("1200.00")
    # Invariant 1 and 2 still strictly hold
    assert stats3['gross_revenue'] == stats3['cash_sales_total'] + stats3['utang_sales_total']
    assert stats3['net_profit'] == stats3['gross_revenue'] - stats3['cogs']


# =============================================================================
# ATOMICITY & DEEP CORNER-CASE TESTS
# =============================================================================

@pytest.mark.django_db
def test_pos_multi_item_insufficient_stock_atomic_rollback(api_client):
    """
    R1 Stress Test: Cart with Item 1 (sufficient stock: 10) and Item 2 (insufficient: stock 1, requested 5).
    Checkout MUST fail atomically: Item 1 stock MUST NOT decrement.
    """
    p1 = Product.objects.create(
        sku="ATOMIC-P1", name="Atomic Product 1", wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("15.00"), stock_quantity=Decimal("10.0000"),
    )
    p2 = Product.objects.create(
        sku="ATOMIC-P2", name="Atomic Product 2", wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("15.00"), stock_quantity=Decimal("1.0000"),
    )

    # API multi-item checkout
    payload = {
        "transaction_type": "CASH",
        "items": [
            {"product_id": p1.id, "quantity": "5.0000"},
            {"product_id": p2.id, "quantity": "5.0000"},  # exceeds p2 stock
        ]
    }
    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 400

    p1.refresh_from_db()
    p2.refresh_from_db()
    assert p1.stock_quantity == Decimal("10.0000"), "Atomicity failed: p1 stock decremented despite failed order!"
    assert p2.stock_quantity == Decimal("1.0000")
    assert Transaction.objects.filter(items__product=p1).count() == 0


@pytest.mark.django_db
def test_utang_credit_limit_breach_atomic_rollback(api_client):
    """
    R2 Stress Test: Utang transaction with multiple items that together breach credit limit.
    Customer limit = ₱500, debt = ₱400.
    Items: ₱60 + ₱50 = ₱110 (400 + 110 = ₱510 > ₱500).
    Verify:
    1. Checkout rejected (HTTP 400).
    2. Customer debt balance remains ₱400.
    3. Product stocks are NOT decremented.
    4. No transaction or transaction items created.
    """
    customer = Customer.objects.create(
        name="Near Limit Customer",
        credit_limit=Decimal("500.00"),
        debt_balance=Decimal("400.00"),
        is_active=True,
    )
    p1 = Product.objects.create(
        sku="UTG-ROLL-1", name="Rollback P1", wholesale_cost=Decimal("40.00"),
        retail_price=Decimal("60.00"), stock_quantity=Decimal("10.0000"),
    )
    p2 = Product.objects.create(
        sku="UTG-ROLL-2", name="Rollback P2", wholesale_cost=Decimal("30.00"),
        retail_price=Decimal("50.00"), stock_quantity=Decimal("10.0000"),
    )

    payload = {
        "transaction_type": "UTANG",
        "customer_id": customer.id,
        "items": [
            {"product_id": p1.id, "quantity": 1},
            {"product_id": p2.id, "quantity": 1},
        ]
    }
    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 400

    customer.refresh_from_db()
    p1.refresh_from_db()
    p2.refresh_from_db()

    assert customer.debt_balance == Decimal("400.00"), "Debt changed on rejected transaction!"
    assert p1.stock_quantity == Decimal("10.0000"), "p1 stock decremented on rejected utang!"
    assert p2.stock_quantity == Decimal("10.0000"), "p2 stock decremented on rejected utang!"
    assert Transaction.objects.filter(customer=customer, transaction_type="UTANG", total_amount=Decimal("110.00")).count() == 0


@pytest.mark.django_db
def test_utang_zero_credit_limit_customer_rejection(api_client):
    """
    R2 Stress Test: Customer with credit_limit = ₱0.00 (cash-only customer).
    Any UTANG purchase must be rejected immediately.
    """
    customer = Customer.objects.create(
        name="Zero Limit Customer",
        credit_limit=Decimal("0.00"),
        debt_balance=Decimal("0.00"),
        is_active=True,
    )
    prod = Product.objects.create(
        sku="ZERO-LIM-P", name="Cheap Candy", wholesale_cost=Decimal("1.00"),
        retail_price=Decimal("2.00"), stock_quantity=Decimal("10.0000")
    )

    payload = {
        "transaction_type": "UTANG",
        "customer_id": customer.id,
        "items": [{"product_id": prod.id, "quantity": 1}]
    }
    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 400
    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("0.00")


@pytest.mark.django_db
@pytest.mark.parametrize("budget_val", [
    Decimal("500.00"),
    Decimal("1000.00"),
    Decimal("25000.00"),
    Decimal("50000.00"),
    Decimal("100000.00"),
])
def test_knapsack_catalog_50_extreme_budgets(fmcg_catalog_50, budget_val):
    """
    R3 Stress Test: Run Knapsack optimizer with the full 50-item FMCG catalog
    across extreme budgets (₱500, ₱1,000, ₱25,000, ₱50,000, ₱100,000).
    Verify:
    1. total_spent <= budget is strictly observed.
    2. remaining_budget >= 0 and total_spent + remaining == budget.
    3. All items belong to categorized aisle groups.
    """
    res = solve_restock_knapsack(fmcg_catalog_50, budget=budget_val)
    spent = Decimal(str(res["total_spent"]))
    remaining = Decimal(str(res["remaining_budget"]))

    assert spent <= budget_val, f"Budget overrun with 50 products: {spent} > {budget_val}"
    assert remaining >= Decimal("0.00")
    assert spent + remaining == budget_val

    # Aisle categorization verification
    categorized = res["categorized_items"]
    assert isinstance(categorized, dict)
    items_count = len(res["items"])
    cat_items_count = sum(len(v) for v in categorized.values())
    assert items_count == cat_items_count


@pytest.mark.django_db
def test_analytics_pure_utang_day_liquidity_isolation():
    """
    R4 Stress Test: Day with 100% Utang sales and ₱0.00 Cash sales.
    Verify:
    - Gross Revenue > 0
    - Cash Sales == 0
    - Cash-on-Hand == 0
    - Uncollected Utang == Gross Revenue
    """
    prod = Product.objects.create(
        sku="PURE-UTG", name="Pure Utang Prod", wholesale_cost=Decimal("50.00"),
        retail_price=Decimal("80.00"), stock_quantity=100
    )
    customer = Customer.objects.create(
        name="Credit Only Customer", credit_limit=Decimal("5000.00"), debt_balance=Decimal("0.00")
    )

    customer.debt_balance = Decimal("800.00")
    customer.save()
    tx = Transaction.objects.create(
        transaction_type=Transaction.TYPE_UTANG,
        customer=customer,
        total_amount=Decimal("800.00"),
        payment_status=Transaction.STATUS_UNPAID
    )
    TransactionItem.objects.create(
        transaction=tx, product=prod, quantity=Decimal("10.0000"),
        unit_price=Decimal("80.00"), cost_price=Decimal("50.00"), subtotal=Decimal("800.00")
    )

    analytics = get_financial_analytics('all')

    assert analytics['gross_revenue'] == Decimal("800.00")
    assert analytics['cash_sales_total'] == Decimal("0.00")
    assert analytics['utang_sales_total'] == Decimal("800.00")
    assert analytics['cash_on_hand'] == Decimal("0.00"), (
        "LIQUIDITY ERROR: Cash-on-hand is non-zero on a 100% credit sales day!"
    )
    assert analytics['uncollected_utang'] == Decimal("800.00")
    assert analytics['cogs'] == Decimal("500.00")
    assert analytics['net_profit'] == Decimal("300.00")


@pytest.mark.django_db
def test_analytics_loss_making_sale_resilience():
    """
    R4 Stress Test: Net negative profit scenario (distress sale below wholesale cost).
    Wholesale: ₱100.00, Retail: ₱60.00 (selling at loss of ₱40).
    Verify Net Profit is negative (-₱40.00) and profit_margin_pct is negative without crashing.
    """
    prod_loss = Product.objects.create(
        sku="LOSS-PROD", name="Loss Leader Prod", wholesale_cost=Decimal("100.00"),
        retail_price=Decimal("60.00"), stock_quantity=10
    )
    tx = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("60.00"),
        payment_status=Transaction.STATUS_PAID
    )
    TransactionItem.objects.create(
        transaction=tx, product=prod_loss, quantity=Decimal("1.0000"),
        unit_price=Decimal("60.00"), cost_price=Decimal("100.00"), subtotal=Decimal("60.00")
    )

    analytics = get_financial_analytics('all')

    assert analytics['gross_revenue'] == Decimal("60.00")
    assert analytics['cogs'] == Decimal("100.00")
    assert analytics['net_profit'] == Decimal("-40.00")
    # Margin % = (-40 / 60) * 100 = -66.67%
    assert analytics['profit_margin_pct'] == -66.67
    assert analytics['cash_on_hand'] == Decimal("60.00")

