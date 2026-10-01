import pytest
from decimal import Decimal
from django.urls import reverse
from core.models import Product, Customer, CustomerPayment, Transaction, TransactionItem


@pytest.mark.django_db
def test_utang_acceptance_500_debt_and_200_payment(api_client, mock_products_20):
    """
    ORIGINAL_REQUEST.md Acceptance Criteria §Utang:
    "Test simulates a ₱500 debt and ₱200 payment; verifies atomic balance updates and limit ceilings."

    Test Scenario:
    1. Customer 'Nanay Tessie' starts with ₱0.00 debt and ₱1,000.00 credit limit.
    2. Customer purchases items on credit totaling exactly ₱500.00.
       Verifies customer debt_balance updates atomically to ₱500.00.
    3. Customer makes a cash repayment of ₱200.00.
       Verifies customer debt_balance decrements to exactly ₱300.00.
    4. Verifies CustomerPayment audit record is persisted with exact amount.
    """
    customer = Customer.objects.create(
        name="Nanay Tessie Acceptance",
        nickname="Tessie",
        credit_limit=Decimal("1000.00"),
        debt_balance=Decimal("0.00"),
        is_active=True,
    )

    # 1. Simulate ₱500.00 Utang purchase via API checkout
    prod = Product.objects.create(
        sku="TEST-UTG-500",
        name="Bulk Rice Sack 10kg",
        category="Staples",
        wholesale_cost=Decimal("420.00"),
        retail_price=Decimal("500.00"),
        stock_quantity=10,
        reorder_point=2,
    )

    payload = {
        "transaction_type": "UTANG",
        "customer_id": customer.id,
        "items": [
            {"product_id": prod.id, "quantity": 1}
        ],
        "notes": "500 Pesos Utang Acceptance Test"
    }

    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 200, f"Checkout failed: {res.content}"

    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("500.00"), (
        f"Expected debt ₱500.00, got ₱{customer.debt_balance}"
    )

    # 2. Simulate ₱200.00 cash repayment via API
    pay_payload = {
        "amount": 200.00,
        "notes": "Partial bayad utang (Acceptance Test)"
    }
    pay_res = api_client.post(
        f"/api/customers/{customer.id}/payments",
        data=pay_payload,
        content_type="application/json"
    )
    assert pay_res.status_code == 200, f"Payment failed: {pay_res.content}"

    customer.refresh_from_db()
    # 500.00 - 200.00 = 300.00
    assert customer.debt_balance == Decimal("300.00"), (
        f"Expected remaining debt ₱300.00, got ₱{customer.debt_balance}"
    )

    # 3. Verify CustomerPayment audit trail
    payment = CustomerPayment.objects.filter(customer=customer).first()
    assert payment is not None
    assert payment.amount == Decimal("200.00")
    assert payment.created_at is not None


@pytest.mark.django_db
def test_utang_credit_limit_ceiling_guard(api_client, mock_products_20):
    """
    ORIGINAL_REQUEST.md § R2 & Acceptance Criteria:
    Limit ceiling guard: Over-limit transaction (debt + amount > credit_limit)
    must be rejected with an error and atomicity rolled back.

    Scenario:
    Customer 'Tito Carding':
      credit_limit = ₱500.00
      current debt_balance = ₱400.00
    Customer attempts to buy item worth ₱150.00 on UTANG:
      400.00 + 150.00 = ₱550.00 > ₱500.00 credit limit!
    Expected Result:
      Transaction rejected (HTTP 400).
      Customer debt remains unchanged at ₱400.00.
      No transaction or line items committed.
    """
    customer = Customer.objects.create(
        name="Tito Carding Ceiling",
        credit_limit=Decimal("500.00"),
        debt_balance=Decimal("400.00"),
        is_active=True,
    )

    prod = Product.objects.create(
        sku="TEST-EXPENSIVE-01",
        name="Red Horse 1000ml Case",
        category="Beverages & Liquor",
        wholesale_cost=Decimal("120.00"),
        retail_price=Decimal("150.00"),
        stock_quantity=10,
        reorder_point=2,
    )

    payload = {
        "transaction_type": "UTANG",
        "customer_id": customer.id,
        "items": [
            {"product_id": prod.id, "quantity": 1}
        ],
        "notes": "Attempt to breach credit limit"
    }

    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    
    # Must reject over-limit credit transaction
    assert res.status_code == 400, (
        f"Expected HTTP 400 Credit Limit Exceeded, but got {res.status_code}: {res.content}"
    )

    # Atomicity check: balance must remain exactly ₱400.00
    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("400.00"), (
        f"Customer debt balance should remain 400.00 on rejection, got {customer.debt_balance}"
    )


@pytest.mark.django_db
def test_utang_negative_and_zero_payment_validation(api_client):
    """
    IEEE 829 Matrix TC-UTG-03: Negative / Zero Repayment Validation.
    Attempts to submit ₱0.00 or negative repayment (-₱50.00) must be rejected
    by validation without altering debt balance.
    """
    customer = Customer.objects.create(
        name="Validation Customer",
        credit_limit=Decimal("1000.00"),
        debt_balance=Decimal("500.00"),
        is_active=True,
    )

    # 1. Zero payment attempt
    res_zero = api_client.post(
        f"/api/customers/{customer.id}/payments",
        data={"amount": 0.00, "notes": "Zero payment"},
        content_type="application/json"
    )
    assert res_zero.status_code in (400, 422), (
        f"Expected HTTP 400/422 for zero payment, got {res_zero.status_code}"
    )

    # 2. Negative payment attempt
    res_neg = api_client.post(
        f"/api/customers/{customer.id}/payments",
        data={"amount": -50.00, "notes": "Negative payment"},
        content_type="application/json"
    )
    assert res_neg.status_code in (400, 422), (
        f"Expected HTTP 400/422 for negative payment, got {res_neg.status_code}"
    )

    # Balance must remain unaffected
    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("500.00")
    assert CustomerPayment.objects.filter(customer=customer).count() == 0


@pytest.mark.django_db
def test_utang_full_debt_liquidation_and_flooring(api_client):
    """
    IEEE 829 Matrix TC-UTG-02: Full Debt Liquidation & Zero Balance Audit.
    Verifies full debt liquidation floors debt_balance cleanly at ₱0.00.
    Even in overpayment scenario (e.g. paying ₱300 on ₱240 debt),
    balance must floor at ₱0.00 and never turn into negative debt.
    """
    customer = Customer.objects.create(
        name="Mang Ben Liquidation",
        credit_limit=Decimal("1000.00"),
        debt_balance=Decimal("240.00"),
        is_active=True,
    )

    # Full payment of exact balance
    res = api_client.post(
        f"/api/customers/{customer.id}/payments",
        data={"amount": 240.00, "notes": "Full liquidation"},
        content_type="application/json"
    )
    assert res.status_code == 200

    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("0.00"), (
        f"Expected clean ₱0.00 balance, got ₱{customer.debt_balance}"
    )

    # Overpayment scenario: customer owes ₱50, pays ₱100
    customer.debt_balance = Decimal("50.00")
    customer.save(update_fields=['debt_balance'])

    res_over = api_client.post(
        f"/api/customers/{customer.id}/payments",
        data={"amount": 100.00, "notes": "Overpayment"},
        content_type="application/json"
    )
    assert res_over.status_code == 200

    customer.refresh_from_db()
    assert customer.debt_balance == Decimal("0.00"), (
        f"Expected balance floored at ₱0.00, got {customer.debt_balance}"
    )
