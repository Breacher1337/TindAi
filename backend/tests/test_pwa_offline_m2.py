import json
import uuid
from decimal import Decimal
import pytest
from django.test import Client
from django.urls import reverse
from core.models import Product, Customer, Transaction, TransactionItem, StockMovement


@pytest.fixture
def api_client():
    return Client()


@pytest.fixture
def fmcg_noodle(db):
    return Product.objects.create(
        sku="M2-TEST-NDL",
        name="Lucky Me Pancit Canton Kalamansi",
        brand="Lucky Me!",
        category="Noodles",
        wholesale_cost=Decimal("12.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("30.0000"),
        reorder_point=5,
        pack_unit="box",
        tingi_unit="piece",
        barcode="480000000001"
    )


@pytest.fixture
def debtor_suki(db):
    return Customer.objects.create(
        name="Aling Marites",
        nickname="Marites",
        phone="09181234567",
        debt_balance=Decimal("100.00"),
        credit_limit=Decimal("1000.00")
    )


def get_response_text(response):
    """Retrieve string content from standard or streaming FileResponse."""
    if hasattr(response, 'streaming_content'):
        return b''.join(response.streaming_content).decode('utf-8')
    return response.content.decode('utf-8')


# =============================================================================
# 1. Web App Manifest Verification
# =============================================================================

@pytest.mark.django_db
class TestPwaManifest:
    """Verifies PWA web app manifest metadata and URL availability."""

    def test_manifest_root_endpoint_status_and_json(self, api_client):
        """GET /manifest.json returns 200 with valid application/json content."""
        response = api_client.get('/manifest.json')
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "TindAI"
        assert data["short_name"] == "TindAI"
        assert data["start_url"] == "/pos/"
        assert data["display"] == "standalone"
        assert data["theme_color"] == "#0f172a"
        assert data["background_color"] == "#ffffff"
        assert "icons" in data and len(data["icons"]) >= 2

    def test_manifest_static_url_status_and_json(self, api_client):
        """GET /static/manifest.json is accessible via static asset route."""
        response = api_client.get('/static/manifest.json')
        assert response.status_code == 200
        text = get_response_text(response)
        data = json.loads(text)
        assert data["short_name"] == "TindAI"
        assert data["start_url"] == "/pos/"


# =============================================================================
# 2. Service Worker Root Scope and Strategy Verification
# =============================================================================

@pytest.mark.django_db
class TestServiceWorker:
    """Verifies root-scoped service worker serving, headers, and caching logic."""

    def test_sw_root_endpoint_headers(self, api_client):
        """GET /sw.js returns 200 with application/javascript and Service-Worker-Allowed: /."""
        response = api_client.get('/sw.js')
        assert response.status_code == 200
        assert 'javascript' in response['Content-Type'].lower()
        assert response['Service-Worker-Allowed'] == '/'

    def test_sw_content_caching_and_sync_logic(self, api_client):
        """Service worker implements Cache-First, Network-First for /pos/, and background sync."""
        response = api_client.get('/sw.js')
        content = response.content.decode('utf-8')

        # Cache-First for static/CDN assets
        assert 'tailwindcss' in content
        assert 'htmx' in content
        assert 'alpinejs' in content
        assert 'lucide' in content

        # Network-First for /pos/
        assert '/pos/' in content
        assert 'caches.match' in content

        # Background sync
        assert "addEventListener('sync'" in content
        assert 'sync-offline-transactions' in content


# =============================================================================
# 3. Client IndexedDB Module Verification
# =============================================================================

@pytest.mark.django_db
class TestOfflineStoreModule:
    """Verifies offline IndexedDB store script availability and API contracts."""

    def test_offline_store_js_served(self, api_client):
        """GET /static/js/offline_store.js returns 200 with javascript."""
        response = api_client.get('/static/js/offline_store.js')
        assert response.status_code == 200
        assert 'javascript' in response['Content-Type'].lower()

    def test_offline_store_js_methods_contract(self, api_client):
        """offline_store.js provides required methods and IndexedDB store contracts."""
        response = api_client.get('/static/js/offline_store.js')
        content = get_response_text(response)

        assert 'TindAIDB' in content
        assert 'offline_transactions' in content
        assert 'saveOfflineTransaction' in content
        assert 'getPendingOfflineTransactions' in content
        assert 'markTransactionSynced' in content
        assert 'deleteOfflineTransaction' in content
        assert 'syncOfflineTransactions' in content
        assert 'PENDING_OFFLINE' in content


# =============================================================================
# 4. Template Rendering: Manifest, Meta Tags, and Offline UI Indicators
# =============================================================================

@pytest.mark.django_db
class TestPwaTemplatesAndUi:
    """Verifies base.html and pos.html render PWA tags and offline status indicators."""

    def test_base_template_renders_manifest_and_meta(self, api_client):
        """GET /pos/ includes manifest link, theme meta tags, and service worker registration."""
        response = api_client.get('/pos/')
        assert response.status_code == 200
        html = response.content.decode('utf-8')

        # Manifest & mobile meta tags
        assert 'rel="manifest"' in html
        assert 'name="theme-color"' in html
        assert 'content="#0f172a"' in html
        assert 'name="apple-mobile-web-app-capable"' in html

        # Service Worker registration script
        assert 'serviceWorker.register' in html
        assert '/sw.js' in html

        # Offline store script inclusion
        assert 'offline_store.js' in html

    def test_pos_template_renders_offline_indicators(self, api_client):
        """GET /pos/ contains offline status banner and sync toast markup."""
        response = api_client.get('/pos/')
        assert response.status_code == 200
        html = response.content.decode('utf-8')

        # Visual offline badge/banner
        assert 'id="offline-status-banner"' in html
        assert 'Offline Mode - Naka-save sa Phone' in html
        assert 'id="sync-toast-notification"' in html


# =============================================================================
# 5. Backend Idempotency & Acceptance Verification
# =============================================================================

@pytest.mark.django_db
class TestApiOfflineIdempotency:
    """Verifies POST /api/transactions accepts client UUIDs and syncs idempotently."""

    def test_accepts_client_uuid_and_pending_offline(self, api_client, fmcg_noodle):
        """API accepts client-assigned UUID and sync_status='PENDING_OFFLINE'."""
        client_uuid = uuid.uuid4()
        initial_stock = fmcg_noodle.stock_quantity
        initial_movements = StockMovement.objects.count()

        payload = {
            "id": str(client_uuid),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(fmcg_noodle.id), "quantity": 2}
            ],
            "notes": "Queued from IndexedDB"
        }

        response = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == str(client_uuid)
        assert data["sync_status"] == "PENDING_OFFLINE"
        assert Decimal(str(data["total_amount"])) == Decimal("30.00")

        # Database verification
        tx = Transaction.objects.get(id=client_uuid)
        assert tx.id == client_uuid
        assert tx.sync_status == Transaction.SYNC_STATUS_PENDING
        fmcg_noodle.refresh_from_db()
        assert fmcg_noodle.stock_quantity == initial_stock - Decimal("2.0000")
        assert StockMovement.objects.count() == initial_movements + 1

    def test_idempotent_absorption_on_duplicate_client_uuid(self, api_client, fmcg_noodle):
        """Submitting duplicate client UUID returns 200 with sync_status='SYNCED' without double deduction."""
        client_uuid = uuid.uuid4()
        initial_stock = fmcg_noodle.stock_quantity
        initial_tx_count = Transaction.objects.count()
        initial_item_count = TransactionItem.objects.count()
        initial_movements = StockMovement.objects.count()

        payload = {
            "id": str(client_uuid),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(fmcg_noodle.id), "quantity": 3}
            ],
            "notes": "Offline transaction to duplicate"
        }

        # First submission succeeds
        res1 = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["id"] == str(client_uuid)

        fmcg_noodle.refresh_from_db()
        expected_stock_after_first = initial_stock - Decimal("3.0000")
        assert fmcg_noodle.stock_quantity == expected_stock_after_first
        assert Transaction.objects.count() == initial_tx_count + 1
        assert TransactionItem.objects.count() == initial_item_count + 1
        assert StockMovement.objects.count() == initial_movements + 1

        # Second submission (duplicate UUID sync retry)
        res2 = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert res2.status_code == 200
        data2 = res2.json()

        # Idempotent absorption checks
        assert data2["id"] == str(client_uuid)
        assert data2["sync_status"] == "SYNCED"
        assert Decimal(str(data2["total_amount"])) == Decimal("45.00")

        # Crucial: inventory must NOT be decremented again
        fmcg_noodle.refresh_from_db()
        assert fmcg_noodle.stock_quantity == expected_stock_after_first, "Stock was erroneously depleted twice!"
        assert Transaction.objects.count() == initial_tx_count + 1, "Duplicate Transaction record created!"
        assert TransactionItem.objects.count() == initial_item_count + 1, "Duplicate TransactionItems created!"
        assert StockMovement.objects.count() == initial_movements + 1, "Duplicate StockMovement logged!"

    def test_idempotent_absorption_on_duplicate_utang_transaction(self, api_client, fmcg_noodle, debtor_suki):
        """Duplicate utang submission does not double customer debt balance."""
        client_uuid = uuid.uuid4()
        initial_debt = debtor_suki.debt_balance
        fmcg_noodle.stock_quantity = Decimal("50.0000")
        fmcg_noodle.save()

        payload = {
            "id": str(client_uuid),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "UTANG",
            "customer_id": str(debtor_suki.id),
            "items": [
                {"product_id": str(fmcg_noodle.id), "quantity": 4}  # 4 x 15 = 60
            ],
            "notes": "Offline Utang transaction"
        }

        # 1. First push
        res1 = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert res1.status_code == 200
        debtor_suki.refresh_from_db()
        assert debtor_suki.debt_balance == initial_debt + Decimal("60.00")

        # 2. Second push with same UUID
        res2 = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["id"] == str(client_uuid)
        assert data2["sync_status"] == "SYNCED"

        # Debtor debt balance must remain at initial_debt + 60, not + 120
        debtor_suki.refresh_from_db()
        assert debtor_suki.debt_balance == initial_debt + Decimal("60.00"), "Customer debt balance was doubled on duplicate sync!"
