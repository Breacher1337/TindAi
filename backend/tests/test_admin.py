import pytest
from decimal import Decimal
from django.contrib.auth.models import User
from django.urls import reverse
from core.models import Product, Customer, Transaction


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin",
        email="admin@tindai.local",
        password="adminpassword123"
    )


@pytest.fixture
def store_data(db):
    product = Product.objects.create(
        sku="TEST-SKU-001",
        name="Lucky Me Pancit Canton",
        wholesale_cost=Decimal("12.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=5,
        reorder_point=10,
        category="Instant Noodles"
    )
    customer = Customer.objects.create(
        name="Mang Juan",
        debt_balance=Decimal("250.00"),
        credit_limit=Decimal("1000.00")
    )
    transaction = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("15.00"),
        payment_status=Transaction.STATUS_PAID,
        customer=customer
    )
    return product, customer, transaction


@pytest.mark.django_db
def test_admin_login_renders(client):
    url = reverse("admin:login")
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"TindAI" in resp.content


@pytest.mark.django_db
def test_admin_index_renders(client, admin_user):
    client.force_login(admin_user)
    url = reverse("admin:index")
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"TindAI" in resp.content
    assert b"POS &amp; Checkout" in resp.content or b"POS & Checkout" in resp.content


@pytest.mark.django_db
def test_product_changelist_unfold_badges(client, admin_user, store_data):
    client.force_login(admin_user)
    url = reverse("admin:core_product_changelist")
    resp = client.get(url)
    assert resp.status_code == 200
    # Reorder point is 10 and stock is 5 -> Low
    assert b"Low (&lt;= 10)" in resp.content or b"Low" in resp.content


@pytest.mark.django_db
def test_customer_changelist_unfold(client, admin_user, store_data):
    client.force_login(admin_user)
    url = reverse("admin:core_customer_changelist")
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"Active Utang" in resp.content


@pytest.mark.django_db
def test_transaction_changelist_unfold(client, admin_user, store_data):
    client.force_login(admin_user)
    url = reverse("admin:core_transaction_changelist")
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"Cash" in resp.content
    assert b"Paid" in resp.content
