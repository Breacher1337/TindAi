import concurrent.futures
import json
import uuid
from decimal import Decimal
import pytest
from django.test import Client
from django.utils import timezone
from core.models import Product, Customer, Transaction, TransactionItem, StockMovement, InventoryBatch
from core.services.inventory import record_restock_batch


@pytest.fixture
def api_client():
    return Client()


@pytest.fixture
def test_product_with_batches(db):
    """Create a test product with two FIFO InventoryBatch records."""
    prod = Product.objects.create(
        sku="CHALLENGE-M2-BATCH",
        name="San Miguel Pale Pilsen 330ml",
        brand="San Miguel",
        category="Beverages",
        wholesale_cost=Decimal("45.00"),
        retail_price=Decimal("60.00"),
        stock_quantity=Decimal("0.0000"),
        reorder_point=5,
        pack_unit="case",
        tingi_unit="bottle",
        barcode="480000000099"
    )

    # Batch 1: 10 bottles @ 40.00 unit cost (older)
    b1 = record_restock_batch(
        product=prod,
        quantity=Decimal("10.0000"),
        unit_cost=Decimal("40.00"),
        reference_id="BATCH-001"
    )
    b1.received_at = timezone.now() - timezone.timedelta(days=2)
    b1.save(update_fields=['received_at'])

    # Batch 2: 15 bottles @ 45.00 unit cost (newer)
    b2 = record_restock_batch(
        product=prod,
        quantity=Decimal("15.0000"),
        unit_cost=Decimal("45.00"),
        reference_id="BATCH-002"
    )
    b2.received_at = timezone.now() - timezone.timedelta(days=1)
    b2.save(update_fields=['received_at'])

    prod.refresh_from_db()
    return prod, b1, b2


@pytest.fixture
def debtor_customer(db):
    return Customer.objects.create(
        name="Mang Kanor",
        nickname="Kanor",
        phone="09191234567",
        debt_balance=Decimal("150.00"),
        credit_limit=Decimal("1500.00")
    )


def extract_content(response):
    if hasattr(response, 'streaming_content'):
        return b''.join(response.streaming_content).decode('utf-8')
    return response.content.decode('utf-8')


# =============================================================================
# Challenge Suite 1: PWA Manifest & Service Worker Responses
# =============================================================================

@pytest.mark.django_db
class TestPwaResponsesAdversarial:
    """Rigorous verification of PWA manifest, service worker headers, JSON schema, and cache assets."""

    def test_manifest_http_status_content_type_and_headers(self, api_client):
        """Manifest at /manifest.json must return 200 with exact application/json Content-Type."""
        res = api_client.get('/manifest.json')
        assert res.status_code == 200, f"Expected 200 but got {res.status_code}"
        assert 'application/json' in res['Content-Type'], f"Expected application/json Content-Type, got {res.get('Content-Type')}"

    def test_manifest_w3c_schema_compliance(self, api_client):
        """Manifest must satisfy standard PWA installability schema requirements."""
        res = api_client.get('/manifest.json')
        data = res.json()

        # Required fields check
        required_fields = ["name", "short_name", "start_url", "display", "background_color", "theme_color", "icons"]
        for field in required_fields:
            assert field in data, f"Missing required manifest field: {field}"
            assert data[field], f"Manifest field '{field}' must not be empty"

        assert data["display"] in ["standalone", "fullscreen", "minimal-ui", "browser"]
        assert data["start_url"].startswith("/")
        assert isinstance(data["icons"], list)
        assert len(data["icons"]) >= 2, "Manifest must specify at least 192px and 512px icons"

        # Check required icon sizes
        sizes = [icon.get("sizes") for icon in data["icons"]]
        assert "192x192" in sizes, "Manifest must include 192x192 icon"
        assert "512x512" in sizes, "Manifest must include 512x512 icon"

        # Check each icon metadata
        for icon in data["icons"]:
            assert "src" in icon and icon["src"].startswith("/static/"), f"Icon src must be valid: {icon}"
            assert icon.get("type") == "image/png"

    def test_manifest_icons_physical_existence_and_http_serving(self, api_client):
        """All icons referenced in manifest must actually be servable via HTTP with 200 status."""
        res = api_client.get('/manifest.json')
        data = res.json()

        for icon in data["icons"]:
            src = icon["src"]
            icon_res = api_client.get(src)
            assert icon_res.status_code == 200, f"Referenced icon {src} returned HTTP {icon_res.status_code}"
            assert 'image' in icon_res['Content-Type'], f"Icon {src} returned non-image content type: {icon_res['Content-Type']}"
            raw_bytes = b''.join(icon_res.streaming_content) if hasattr(icon_res, 'streaming_content') else icon_res.content
            assert len(raw_bytes) > 100, f"Icon file {src} is suspiciously small or empty"

    def test_service_worker_http_status_and_scope_headers(self, api_client):
        """Service Worker at /sw.js must return HTTP 200, JS Content-Type, and Service-Worker-Allowed: /."""
        res = api_client.get('/sw.js')
        assert res.status_code == 200
        assert 'javascript' in res['Content-Type'].lower()
        # W3C Service Worker scope enforcement header
        assert res.get('Service-Worker-Allowed') == '/', (
            f"Service-Worker-Allowed header must be '/', found: {res.get('Service-Worker-Allowed')}"
        )

    def test_service_worker_precache_assets_integrity(self, api_client):
        """All local URLs declared in sw.js PRECACHE_ASSETS must be valid, reachable endpoints on TindAI."""
        res = api_client.get('/sw.js')
        sw_code = res.content.decode('utf-8')

        # Extract PRECACHE_ASSETS list from JavaScript
        assert 'PRECACHE_ASSETS' in sw_code, "sw.js missing PRECACHE_ASSETS declaration"

        # Verify critical local URLs
        critical_local_urls = [
            '/',
            '/pos/',
            '/manifest.json',
            '/static/manifest.json',
            '/static/js/offline_store.js',
            '/static/icons/icon-192.png',
            '/static/icons/icon-512.png',
        ]

        for url in critical_local_urls:
            assert f"'{url}'" in sw_code or f'"{url}"' in sw_code, f"URL {url} missing from sw.js PRECACHE_ASSETS"
            check_res = api_client.get(url)
            assert check_res.status_code == 200, f"Precached asset {url} returned HTTP {check_res.status_code} on server"

        # Verify critical external CDN libraries are listed
        critical_cdns = ['tailwindcss', 'htmx', 'alpinejs', 'lucide']
        for cdn in critical_cdns:
            assert cdn in sw_code, f"Vendor library {cdn} missing from service worker pre-cache list"

    def test_service_worker_caching_strategies_present(self, api_client):
        """sw.js must implement Cache-First for static/CDNs, Network-First for navigation, and background sync."""
        res = api_client.get('/sw.js')
        sw_code = res.content.decode('utf-8')

        # Check Cache-First logic
        assert 'caches.open' in sw_code
        assert 'caches.match' in sw_code

        # Check Network-First / Navigation logic
        assert '/pos/' in sw_code

        # Check Background Sync listener
        assert "addEventListener('sync'" in sw_code
        assert 'sync-offline-transactions' in sw_code


# =============================================================================
# Challenge Suite 2: Backend API Idempotent Duplicate Absorption
# =============================================================================

@pytest.mark.django_db
class TestApiIdempotentAbsorptionAdversarial:
    """Stress tests backend API idempotency: FIFO batch depletion, COGS calculation, stock movements."""

    def test_fifo_inventory_batch_depleted_strictly_once_under_packet_duplication(self, api_client, test_product_with_batches):
        """
        Simulate network packet duplication with exact client UUID submitted 5 consecutive times:
        - 14 units sold across Batch 1 (10 units @ 40) and Batch 2 (4 units @ 45).
        - Expected COGS: 10*40 + 4*45 = 400 + 180 = 580.00.
        - Batch 1 remaining must be exactly 0.0000.
        - Batch 2 remaining must be exactly 11.0000.
        - Product stock must be exactly 11.0000 (25 - 14).
        - StockMovement count must increase by strictly 1.
        - Duplicate requests must return HTTP 200 with sync_status='SYNCED' and identical totals.
        """
        prod, b1, b2 = test_product_with_batches
        client_tx_id = uuid.uuid4()

        initial_tx_count = Transaction.objects.count()
        initial_item_count = TransactionItem.objects.count()
        initial_movements_count = StockMovement.objects.count()

        payload = {
            "id": str(client_tx_id),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(prod.id), "quantity": 14}
            ],
            "notes": "Adversarial network retry simulation"
        }

        # 1. First transmission: should execute FIFO depletion
        res1 = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert res1.status_code == 200, f"First submission failed: {res1.content}"
        data1 = res1.json()

        assert data1["id"] == str(client_tx_id)
        assert Decimal(str(data1["total_amount"])) == Decimal("840.00")  # 14 * 60 = 840
        assert Decimal(str(data1["total_cogs"])) == Decimal("580.00")    # 10*40 + 4*45 = 580
        assert Decimal(str(data1["gross_profit"])) == Decimal("260.00")  # 840 - 580 = 260

        # Verify DB state after first submission
        prod.refresh_from_db()
        b1.refresh_from_db()
        b2.refresh_from_db()

        assert prod.stock_quantity == Decimal("11.0000")
        assert b1.remaining_tingi_quantity == Decimal("0.0000")
        assert b2.remaining_tingi_quantity == Decimal("11.0000")
        assert StockMovement.objects.count() == initial_movements_count + 1

        sale_movement = StockMovement.objects.filter(reference_id=str(client_tx_id)).first()
        assert sale_movement is not None
        assert sale_movement.quantity_change == Decimal("-14.0000")
        assert sale_movement.balance_after == Decimal("11.0000")

        # 2. Simulate 4 duplicate packet retries (same UUID, same payload)
        for attempt in range(2, 6):
            res_dup = api_client.post("/api/transactions", data=payload, content_type="application/json")
            assert res_dup.status_code == 200, f"Attempt {attempt} failed with {res_dup.status_code}"
            dup_data = res_dup.json()

            # Verify response matches original and marks SYNCED
            assert dup_data["id"] == str(client_tx_id)
            assert dup_data["sync_status"] == "SYNCED", f"Attempt {attempt} returned sync_status={dup_data['sync_status']}"
            assert Decimal(str(dup_data["total_amount"])) == Decimal("840.00")
            assert Decimal(str(dup_data["total_cogs"])) == Decimal("580.00")
            assert Decimal(str(dup_data["gross_profit"])) == Decimal("260.00")
            assert len(dup_data["items"]) == 1

        # 3. EMPIRICAL VERIFICATION OF DATABASE INTEGRITY: Batches, movements, COGS must NOT be double-depleted
        prod.refresh_from_db()
        b1.refresh_from_db()
        b2.refresh_from_db()

        # Batches must remain untouched after first depletion
        assert b1.remaining_tingi_quantity == Decimal("0.0000"), "Batch 1 was depleted below 0 on duplicate!"
        assert b2.remaining_tingi_quantity == Decimal("11.0000"), "Batch 2 was depleted multiple times on duplicate!"
        assert prod.stock_quantity == Decimal("11.0000"), "Product stock was decremented multiple times on duplicate!"

        # Audit ledger count must be strictly 1 movement for this transaction
        assert StockMovement.objects.count() == initial_movements_count + 1
        assert StockMovement.objects.filter(reference_id=str(client_tx_id)).count() == 1

        # Transaction count must be strictly 1
        assert Transaction.objects.count() == initial_tx_count + 1
        assert TransactionItem.objects.count() == initial_item_count + 1

        # Database record must have sync_status='SYNCED'
        db_tx = Transaction.objects.get(id=client_tx_id)
        assert db_tx.sync_status == Transaction.SYNC_STATUS_SYNCED
        assert db_tx.total_cogs == Decimal("580.00")
        assert db_tx.gross_profit == Decimal("260.00")

    def test_multi_product_multi_batch_idempotency_stress(self, api_client, test_product_with_batches):
        """
        Verify multi-item checkout (2 products with multiple batches each) under duplicate packet flood:
        - Both products have independent batch records.
        - Both products are depleted strictly once.
        - Multiple duplicates return identical item arrays and totals.
        """
        prod1, b1_1, b1_2 = test_product_with_batches

        # Product 2
        prod2 = Product.objects.create(
            sku="CHALLENGE-M2-PROD2",
            name="Century Tuna Flakes in Oil 155g",
            brand="Century",
            category="Canned Goods",
            wholesale_cost=Decimal("30.00"),
            retail_price=Decimal("40.00"),
            stock_quantity=Decimal("0.0000"),
            reorder_point=5
        )
        b2_1 = record_restock_batch(prod2, Decimal("20.0000"), Decimal("28.00"), reference_id="TUNA-001")
        prod2.refresh_from_db()

        client_tx_id = uuid.uuid4()
        initial_movements = StockMovement.objects.count()

        payload = {
            "id": str(client_tx_id),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(prod1.id), "quantity": 5},   # from b1_1 (cost 40, price 60) -> cogs 200, rev 300
                {"product_id": str(prod2.id), "quantity": 8}    # from b2_1 (cost 28, price 40) -> cogs 224, rev 320
            ],
            "notes": "Multi-item offline checkout burst"
        }

        # Send initial + 9 duplicates (total 10 transmissions)
        for i in range(10):
            res = api_client.post("/api/transactions", data=payload, content_type="application/json")
            assert res.status_code == 200
            data = res.json()
            assert data["id"] == str(client_tx_id)
            assert Decimal(str(data["total_amount"])) == Decimal("620.00")  # 300 + 320
            assert Decimal(str(data["total_cogs"])) == Decimal("424.00")    # 200 + 224
            assert Decimal(str(data["gross_profit"])) == Decimal("196.00")  # 620 - 424

        # Verify batch states
        b1_1.refresh_from_db()
        b2_1.refresh_from_db()
        prod1.refresh_from_db()
        prod2.refresh_from_db()

        assert b1_1.remaining_tingi_quantity == Decimal("5.0000")  # 10 - 5
        assert prod1.stock_quantity == Decimal("20.0000")          # 25 - 5
        assert b2_1.remaining_tingi_quantity == Decimal("12.0000") # 20 - 8
        assert prod2.stock_quantity == Decimal("12.0000")          # 20 - 8

        # Exactly 2 stock movements (one per product) logged across 10 requests
        assert StockMovement.objects.count() == initial_movements + 2

    def test_utang_duplicate_packet_does_not_multiply_customer_debt(self, api_client, test_product_with_batches, debtor_customer):
        """
        Verify that repeated submissions of an Utang (credit) transaction do not multiply debt:
        - Customer debt balance must increase exactly once by total_amount.
        - Subsequent duplicate requests return sync_status='SYNCED' without increasing debt balance.
        """
        prod, _, _ = test_product_with_batches
        client_tx_id = uuid.uuid4()
        initial_debt = debtor_customer.debt_balance  # 150.00

        payload = {
            "id": str(client_tx_id),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "UTANG",
            "customer_id": str(debtor_customer.id),
            "items": [
                {"product_id": str(prod.id), "quantity": 3}  # 3 * 60 = 180.00
            ],
            "notes": "Adversarial repeated utang sync"
        }

        # Submit 6 times
        for attempt in range(1, 7):
            res = api_client.post("/api/transactions", data=payload, content_type="application/json")
            assert res.status_code == 200
            data = res.json()
            assert data["id"] == str(client_tx_id)
            if attempt > 1:
                assert data["sync_status"] == "SYNCED"

        debtor_customer.refresh_from_db()
        expected_debt = initial_debt + Decimal("180.00")  # 330.00
        assert debtor_customer.debt_balance == expected_debt, (
            f"Debt balance was duplicated! Expected {expected_debt}, got {debtor_customer.debt_balance}"
        )

    def test_idempotent_response_contains_accurate_transaction_items(self, api_client, test_product_with_batches):
        """
        Subsequent idempotent absorption responses must accurately reconstruct TransactionItemOut
        matching the original transaction's item fields.
        """
        prod, _, _ = test_product_with_batches
        client_tx_id = uuid.uuid4()

        payload = {
            "id": str(client_tx_id),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(prod.id), "quantity": 2}
            ],
            "notes": "Reconstruction verification"
        }

        res1 = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert res1.status_code == 200
        first_items = res1.json()["items"]

        # Duplicate request
        res2 = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert res2.status_code == 200
        dup_items = res2.json()["items"]

        assert len(dup_items) == len(first_items) == 1
        assert dup_items[0]["product_id"] == str(prod.id)
        assert dup_items[0]["product_name"] == prod.name
        assert dup_items[0]["product_sku"] == prod.sku
        assert Decimal(str(dup_items[0]["quantity"])) == Decimal("2.0000")
        assert Decimal(str(dup_items[0]["unit_price"])) == Decimal("60.00")
        assert Decimal(str(dup_items[0]["subtotal"])) == Decimal("120.00")
        assert Decimal(str(dup_items[0]["cost_price"])) == Decimal("40.00")

    def test_tampered_payload_on_duplicate_uuid_does_not_corrupt_or_deplete_other_items(self, api_client, test_product_with_batches):
        """
        Adversarial test: If an attacker or corrupted network sends a duplicate UUID but with
        a different product/payload, the backend must return the original transaction without
        executing depletion against the new product.
        """
        prod1, _, _ = test_product_with_batches
        prod2 = Product.objects.create(
            sku="TAMPER-PROD-2",
            name="Century Corned Beef 175g",
            category="Canned Goods",
            wholesale_cost=Decimal("25.00"),
            retail_price=Decimal("35.00"),
            stock_quantity=Decimal("50.0000"),
            reorder_point=5
        )
        record_restock_batch(prod2, Decimal("50.0000"), Decimal("25.00"), reference_id="TAMPER-001")
        prod2.refresh_from_db()
        initial_prod2_stock = prod2.stock_quantity

        client_tx_id = uuid.uuid4()

        # Legitimate first request with prod1
        payload1 = {
            "id": str(client_tx_id),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [{"product_id": str(prod1.id), "quantity": 2}],
            "notes": "Legitimate request"
        }
        res1 = api_client.post("/api/transactions", data=payload1, content_type="application/json")
        assert res1.status_code == 200

        # Tampered duplicate request with same UUID but targeting prod2 for 20 units
        payload_tampered = {
            "id": str(client_tx_id),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [{"product_id": str(prod2.id), "quantity": 20}],
            "notes": "Tampered request attempting to deplete prod2"
        }
        res_tampered = api_client.post("/api/transactions", data=payload_tampered, content_type="application/json")
        assert res_tampered.status_code == 200
        data_tampered = res_tampered.json()

        # Idempotency returns original transaction (prod1), NOT tampered items
        assert data_tampered["id"] == str(client_tx_id)
        assert len(data_tampered["items"]) == 1
        assert data_tampered["items"][0]["product_id"] == str(prod1.id)

        # Crucial check: prod2 was NOT touched or depleted!
        prod2.refresh_from_db()
        assert prod2.stock_quantity == initial_prod2_stock

    def test_missing_sw_or_manifest_returns_clean_404_not_500(self, api_client):
        """Negative test: if static files are missing on disk, endpoints return clean 404, not unhandled 500."""
        from unittest.mock import patch
        from pathlib import Path

        orig_exists = Path.exists

        def fake_exists(self):
            if str(self).endswith('sw.js') or str(self).endswith('manifest.json'):
                return False
            return orig_exists(self)

        with patch.object(Path, 'exists', fake_exists):
            sw_res = api_client.get('/sw.js')
            assert sw_res.status_code == 404
            assert sw_res['Content-Type'] == 'application/javascript'

            manifest_res = api_client.get('/manifest.json')
            assert manifest_res.status_code == 404
            assert manifest_res['Content-Type'] == 'application/json'

    def test_invalid_payloads_strictly_rejected(self, api_client, test_product_with_batches):
        """Boundary test: invalid transaction payloads are rejected without creating orphan transactions."""
        prod, _, _ = test_product_with_batches
        initial_tx_count = Transaction.objects.count()

        # Empty items list
        res_empty = api_client.post("/api/transactions", data={
            "id": str(uuid.uuid4()),
            "transaction_type": "CASH",
            "items": []
        }, content_type="application/json")
        assert res_empty.status_code == 400
        assert Transaction.objects.count() == initial_tx_count

        # Exceeding stock
        res_overstock = api_client.post("/api/transactions", data={
            "id": str(uuid.uuid4()),
            "transaction_type": "CASH",
            "items": [{"product_id": str(prod.id), "quantity": 9999}]
        }, content_type="application/json")
        assert res_overstock.status_code == 400
        assert "Insufficient stock" in res_overstock.json()["detail"]
        assert Transaction.objects.count() == initial_tx_count

        # Utang without customer
        res_no_cust = api_client.post("/api/transactions", data={
            "id": str(uuid.uuid4()),
            "transaction_type": "UTANG",
            "items": [{"product_id": str(prod.id), "quantity": 1}]
        }, content_type="application/json")
        assert res_no_cust.status_code == 400
        assert Transaction.objects.count() == initial_tx_count

