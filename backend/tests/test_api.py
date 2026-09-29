import pytest
from decimal import Decimal
from django.test import Client
from core.models import Product, Customer, Transaction, CustomerPayment


@pytest.fixture
def api_client():
    return Client()


@pytest.fixture
def sample_product(db):
    return Product.objects.create(
        sku="TEST-SKU-001",
        name="Test Noodles Kalamansi 60g",
        brand="Lucky Me!",
        category="Instant Noodles",
        wholesale_cost=Decimal("12.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=20,
        reorder_point=5,
        pack_unit="box",
        tingi_unit="piece",
        barcode="480000000001"
    )


@pytest.fixture
def sample_customer(db):
    return Customer.objects.create(
        name="Juan Dela Cruz",
        nickname="Kuya Juan",
        phone="09170001122",
        debt_balance=Decimal("200.00"),
        credit_limit=Decimal("1000.00")
    )


@pytest.mark.django_db
def test_list_products(api_client, sample_product):
    res = api_client.get("/api/products")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert data[0]["sku"] == sample_product.sku


@pytest.mark.django_db
def test_create_product(api_client):
    payload = {
        "sku": "NEW-PROD-002",
        "name": "Nescafe Classic Twin Pack",
        "brand": "Nescafe",
        "category": "Coffee & Hot Drinks",
        "wholesale_cost": 13.50,
        "retail_price": 16.00,
        "stock_quantity": 50,
        "reorder_point": 10,
        "pack_unit": "bundle",
        "tingi_unit": "sachet"
    }
    res = api_client.post("/api/products", data=payload, content_type="application/json")
    assert res.status_code == 200
    data = res.json()
    assert data["sku"] == "NEW-PROD-002"
    assert Product.objects.filter(sku="NEW-PROD-002").exists()


@pytest.mark.django_db
def test_customers_and_payments(api_client, sample_customer):
    # List customers
    res = api_client.get("/api/customers")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert data[0]["name"] == sample_customer.name

    # Post payment
    pay_res = api_client.post(
        f"/api/customers/{sample_customer.id}/payments",
        data={"amount": 50.00, "notes": "Bayad 50 pesos"},
        content_type="application/json"
    )
    assert pay_res.status_code == 200
    pay_data = pay_res.json()
    assert float(pay_data["new_debt_balance"]) == 150.00

    sample_customer.refresh_from_db()
    assert sample_customer.debt_balance == Decimal("150.00")


@pytest.mark.django_db
def test_transaction_cash_checkout(api_client, sample_product):
    initial_stock = sample_product.stock_quantity
    payload = {
        "transaction_type": "CASH",
        "items": [
            {"product_id": sample_product.id, "quantity": 2}
        ]
    }
    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 200
    data = res.json()
    assert data["transaction_type"] == "CASH"
    assert data["payment_status"] == "PAID"
    assert float(data["total_amount"]) == 30.00

    sample_product.refresh_from_db()
    assert sample_product.stock_quantity == initial_stock - 2


@pytest.mark.django_db
def test_transaction_utang_checkout(api_client, sample_product, sample_customer):
    initial_debt = sample_customer.debt_balance
    payload = {
        "transaction_type": "UTANG",
        "customer_id": sample_customer.id,
        "items": [
            {"product_id": sample_product.id, "quantity": 3}
        ]
    }
    res = api_client.post("/api/transactions", data=payload, content_type="application/json")
    assert res.status_code == 200
    data = res.json()
    assert data["transaction_type"] == "UTANG"
    assert data["payment_status"] == "UNPAID"
    assert float(data["total_amount"]) == 45.00

    sample_customer.refresh_from_db()
    assert sample_customer.debt_balance == initial_debt + Decimal("45.00")


@pytest.mark.django_db
def test_restock_optimize_endpoint(api_client, sample_product):
    payload = {
        "budget": 2000.00
    }
    res = api_client.post("/api/restock/optimize", data=payload, content_type="application/json")
    assert res.status_code == 200
    data = res.json()
    assert "budget" in data
    assert "total_spent" in data
    assert "items" in data


@pytest.mark.django_db
def test_vision_counter_detect_stub(api_client):
    payload = {
        "image_base64": "dummy-data",
        "prompt_hint": "Detect counter goods"
    }
    res = api_client.post("/api/vision/counter-detect", data=payload, content_type="application/json")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert len(data["detected_items"]) > 0


@pytest.mark.django_db
def test_ocr_receipt_stub(api_client):
    payload = {
        "image_base64": "dummy-data",
        "wholesaler_hint": "Puregold"
    }
    res = api_client.post("/api/ocr/receipt", data=payload, content_type="application/json")
    assert res.status_code == 200
    data = res.json()
    assert "wholesaler_name" in data
    assert len(data["items"]) > 0
