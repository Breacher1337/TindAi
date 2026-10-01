import pytest
from decimal import Decimal
from django.urls import reverse
from core.models import Product, Customer, Transaction, TransactionItem


@pytest.mark.django_db
def test_pos_live_cart_crud_lifecycle(api_client, mock_products_20):
    """
    Test live cart CRUD operations:
    1. Add product to cart.
    2. Increment quantity via stepper.
    3. Decrement quantity via stepper.
    4. Decrement to 0 removing the item completely.
    5. Add multiple products and clear the entire cart.
    6. Verify HTMX partial rendering with HX-Request header.
    """
    p1 = mock_products_20[0]  # Pancit Canton Kalamansi (15.00)
    p2 = mock_products_20[1]  # Pancit Canton Chilimansi (15.00)

    # 1. Add p1 to cart
    res = api_client.post(reverse('cart_add', args=[p1.id]))
    assert res.status_code in (200, 302)
    session = api_client.session
    cart = session.get('cart', {})
    assert str(p1.id) in cart
    assert cart[str(p1.id)]['qty'] == 1

    # 2. Increment p1 quantity
    res = api_client.post(reverse('cart_add', args=[p1.id]))
    assert res.status_code in (200, 302)
    cart = api_client.session.get('cart', {})
    assert cart[str(p1.id)]['qty'] == 2

    # 3. Decrement p1 quantity
    res = api_client.post(reverse('cart_remove', args=[p1.id]))
    assert res.status_code in (200, 302)
    cart = api_client.session.get('cart', {})
    assert cart[str(p1.id)]['qty'] == 1

    # 4. Decrement to 0 (removes item from cart)
    res = api_client.post(reverse('cart_remove', args=[p1.id]))
    assert res.status_code in (200, 302)
    cart = api_client.session.get('cart', {})
    assert str(p1.id) not in cart
    assert len(cart) == 0

    # 5. Add multiple items
    api_client.post(reverse('cart_add', args=[p1.id]))
    api_client.post(reverse('cart_add', args=[p2.id]))
    cart = api_client.session.get('cart', {})
    assert len(cart) == 2

    # 6. Clear cart
    res = api_client.post(reverse('cart_clear'))
    assert res.status_code in (200, 302)
    cart = api_client.session.get('cart', {})
    assert len(cart) == 0

    # 7. Test HTMX cart rendering
    res_htmx = api_client.post(
        reverse('cart_add', args=[p1.id]),
        HTTP_HX_REQUEST='true'
    )
    assert res_htmx.status_code == 200
    assert b"Pancit Canton" in res_htmx.content


@pytest.mark.django_db
def test_pos_fractional_tingi_stock_decrement(api_client):
    """
    ORIGINAL_REQUEST.md Acceptance Criteria §POS:
    "Test simulates a checkout with fractional tingi items; verifies stock decrements mathematically correct."
    
    Specification:
    A store carries packaged goods (e.g. 1 box containing 20 units).
    Initial stock: 10.00 boxes.
    Selling 1 tingi piece represents a fractional deduction of:
      1 unit / 20 units_per_box = 0.05 boxes.
    After checkout:
      Expected remaining stock = 10.00 - 0.05 = 9.95 boxes.
    """
    box_product = Product.objects.create(
        sku="TINGI-BOX-001",
        name="Chippy Barbecue 110g Box (20s)",
        brand="Jack n Jill",
        category="Snacks",
        wholesale_cost=Decimal("400.00"),
        retail_price=Decimal("24.00"),
        stock_quantity=Decimal("10.00"),
        reorder_point=2,
        pack_unit="box (20s)",
        tingi_unit="piece",
        is_active=True,
    )

    # Put 1 tingi item into cart with fractional deduction or quantity representation
    # Session cart structure: {pid: {'name': ..., 'price': '24.00', 'qty': Decimal('0.05') or tingi flag}}
    session = api_client.session
    session['cart'] = {
        str(box_product.id): {
            'name': box_product.name,
            'price': '24.00',
            'unit': 'piece',
            'qty': '0.05',
        }
    }
    session.save()

    # Finalize checkout
    res = api_client.post(reverse('checkout'), {'payment_method': 'CASH'})
    assert res.status_code in (200, 302)

    box_product.refresh_from_db()
    # Decrement must be mathematically exact: 10.00 - 0.05 = 9.95
    assert Decimal(str(box_product.stock_quantity)) == Decimal("9.95"), (
        f"Expected stock 9.95 after -0.05 tingi deduction, got {box_product.stock_quantity}"
    )


@pytest.mark.django_db
def test_pos_stock_non_negativity_guard(api_client):
    """
    PROJECT.md § POS Checkout ↔ Inventory & Utang Rule 1:
    "For each item: product.stock_quantity >= quantity."
    Stock must never fall below zero. Attempting to purchase more than available
    stock must be rejected or prevented.
    """
    low_stock_prod = Product.objects.create(
        sku="LOW-STK-001",
        name="Limited Stock Soda Can",
        category="Beverages & Liquor",
        wholesale_cost=Decimal("20.00"),
        retail_price=Decimal("25.00"),
        stock_quantity=2,
        reorder_point=5,
        is_active=True,
    )

    # Exact boundary purchase: buying 2 when stock is 2
    session = api_client.session
    session['cart'] = {
        str(low_stock_prod.id): {
            'name': low_stock_prod.name,
            'price': '25.00',
            'unit': 'can',
            'qty': 2,
        }
    }
    session.save()

    res = api_client.post(reverse('checkout'), {'payment_method': 'CASH'})
    assert res.status_code in (200, 302)
    low_stock_prod.refresh_from_db()
    assert low_stock_prod.stock_quantity == 0

    # Over-purchase attempt: stock is now 0, attempting to purchase 1
    session = api_client.session
    session['cart'] = {
        str(low_stock_prod.id): {
            'name': low_stock_prod.name,
            'price': '25.00',
            'unit': 'can',
            'qty': 1,
        }
    }
    session.save()

    res_over = api_client.post(reverse('checkout'), {'payment_method': 'CASH'})
    low_stock_prod.refresh_from_db()
    # Stock must remain >= 0, never negative
    assert low_stock_prod.stock_quantity >= 0, f"Stock dropped below zero: {low_stock_prod.stock_quantity}"


@pytest.mark.django_db
def test_pos_dual_settlement_cash_and_utang(api_client, mock_products_20, suki_customers):
    """
    Verifies dual settlement at POS:
    - CASH creates transaction with status PAID and records total revenue.
    - UTANG requires customer, sets status to PENDING/UNPAID, and updates ledger.
    - UTANG without customer is rejected.
    """
    p = mock_products_20[0]
    customer = suki_customers['maria']
    initial_debt = customer.debt_balance

    # Case 1: Cash Checkout
    session = api_client.session
    session['cart'] = {
        str(p.id): {
            'name': p.name,
            'price': str(p.retail_price),
            'unit': 'piece',
            'qty': 1,
        }
    }
    session.save()

    res_cash = api_client.post(reverse('checkout'), {'payment_method': 'CASH'})
    assert res_cash.status_code in (200, 302)
    cash_tx = Transaction.objects.filter(transaction_type=Transaction.TYPE_CASH).order_by('-created_at').first()
    assert cash_tx is not None
    assert cash_tx.payment_status == Transaction.STATUS_PAID
    assert cash_tx.total_amount == p.retail_price

    # Case 2: Utang Checkout without customer -> rejected
    session = api_client.session
    session['cart'] = {
        str(p.id): {
            'name': p.name,
            'price': str(p.retail_price),
            'unit': 'piece',
            'qty': 1,
        }
    }
    session.save()

    res_missing_customer = api_client.post(reverse('checkout'), {'payment_method': 'UTANG'})
    # No customer specified: should reject or redirect back without creating UTANG transaction
    utang_invalid = Transaction.objects.filter(transaction_type=Transaction.TYPE_UTANG, customer__isnull=True).first()
    assert utang_invalid is None

    # Case 3: Valid Utang Checkout with customer
    session = api_client.session
    session['cart'] = {
        str(p.id): {
            'name': p.name,
            'price': str(p.retail_price),
            'unit': 'piece',
            'qty': 2,
        }
    }
    session.save()

    res_utang = api_client.post(reverse('checkout'), {
        'payment_method': 'UTANG',
        'customer_id': customer.id,
    })
    assert res_utang.status_code in (200, 302)

    customer.refresh_from_db()
    expected_new_debt = initial_debt + (p.retail_price * 2)
    assert customer.debt_balance == expected_new_debt
