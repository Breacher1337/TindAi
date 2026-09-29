import pytest
from decimal import Decimal
from django.urls import reverse
from core.models import Product, Customer, Transaction, CustomerPayment


@pytest.fixture
def sample_product(db):
    return Product.objects.create(
        sku="TEST-001",
        name="Lucky Me Pancit Canton",
        wholesale_cost=Decimal("12.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=50,
        reorder_point=10,
        pack_unit="pack of 6",
        tingi_unit="pouch",
        category="Instant Noodles"
    )


@pytest.fixture
def sample_customer(db):
    return Customer.objects.create(
        name="Mang Juan Dela Cruz",
        nickname="Juan",
        phone="09171234567",
        debt_balance=Decimal("250.00"),
        credit_limit=Decimal("1000.00")
    )


@pytest.mark.django_db
def test_pos_view_renders(client, sample_product):
    resp = client.get(reverse('pos'))
    assert resp.status_code == 200
    assert b"TindAI" in resp.content
    assert b"Lucky Me Pancit Canton" in resp.content


@pytest.mark.django_db
def test_cart_add_and_checkout_cash(client, sample_product):
    # Add to cart
    resp = client.post(reverse('cart_add', args=[sample_product.id]))
    assert resp.status_code == 302

    # Checkout cash
    checkout_resp = client.post(reverse('checkout'), {
        'payment_method': 'CASH'
    })
    assert checkout_resp.status_code == 302

    # Verify transaction and stock decrement
    assert Transaction.objects.filter(transaction_type='CASH').count() == 1
    sample_product.refresh_from_db()
    assert sample_product.stock_quantity == 49


@pytest.mark.django_db
def test_inventory_view(client, sample_product):
    resp = client.get(reverse('inventory'))
    assert resp.status_code == 200
    assert b"Lucky Me Pancit Canton" in resp.content

    # Filter by category
    cat_resp = client.get(reverse('inventory') + '?category=Instant+Noodles')
    assert cat_resp.status_code == 200
    assert b"Lucky Me Pancit Canton" in cat_resp.content

    # Filter low stock (current stock 50, reorder 10 -> not low)
    low_resp = client.get(reverse('inventory') + '?status=low')
    assert low_resp.status_code == 200
    assert b"Walang nahanap na produkto" in low_resp.content

    # Now make it low stock
    sample_product.stock_quantity = 5
    sample_product.save()
    low_resp2 = client.get(reverse('inventory') + '?status=low')
    assert low_resp2.status_code == 200
    assert b"Konti na lang" in low_resp2.content


@pytest.mark.django_db
def test_utang_view_and_payment(client, sample_customer):
    resp = client.get(reverse('utang'))
    assert resp.status_code == 200
    assert b"Mang Juan Dela Cruz" in resp.content
    assert b"250.00" in resp.content

    # Pay 100
    pay_resp = client.post(reverse('utang_pay'), {
        'customer_id': sample_customer.id,
        'amount': '100.00'
    })
    assert pay_resp.status_code == 302
    sample_customer.refresh_from_db()
    assert sample_customer.debt_balance == Decimal("150.00")
    assert CustomerPayment.objects.filter(customer=sample_customer).count() == 1


@pytest.mark.django_db
def test_restock_calculate(client, sample_product):
    sample_product.stock_quantity = 2  # Low stock
    sample_product.save()

    resp = client.post(reverse('restock_calculate'), {'budget': '3000'})
    assert resp.status_code == 200
    assert b"Lucky Me Pancit Canton" in resp.content
