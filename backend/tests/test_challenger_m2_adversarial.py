import json
import uuid
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import pytest
from django.test import Client
from django.db import connection, connections
from playwright.sync_api import sync_playwright
from core.models import Product, Customer, Transaction, TransactionItem, StockMovement, InventoryBatch


@pytest.fixture
def fmcg_item(db):
    Product.objects.all().delete()
    StockMovement.objects.all().delete()
    Transaction.objects.all().delete()
    return Product.objects.create(
        sku="TEST-CHALLENGER-M2-01",
        name="San Miguel Pale Pilsen 330ml",
        brand="San Miguel",
        category="Beverages",
        wholesale_cost=Decimal("45.00"),
        retail_price=Decimal("60.00"),
        stock_quantity=Decimal("20.0000"),
        reorder_point=5,
        pack_unit="case",
        tingi_unit="bottle",
        barcode="480000099991"
    )


@pytest.fixture
def test_customer(db):
    Customer.objects.all().delete()
    return Customer.objects.create(
        name="Mang Boyet",
        nickname="Boyet",
        phone="09171234567",
        debt_balance=Decimal("200.00"),
        credit_limit=Decimal("1500.00")
    )


# =============================================================================
# 1. Real Chromium Browser Tests: IndexedDB & Offline Interception
# =============================================================================

@pytest.mark.django_db(transaction=True)
def test_browser_offline_store_indexeddb_lifecycle(live_server, fmcg_item):
    """
    Empirically tests TindAIDB IndexedDB operations in a real Chromium browser context:
    - DB initialization
    - saveOfflineTransaction
    - getPendingOfflineTransactions
    - markTransactionSynced
    - deleteOfflineTransaction
    - UUID generation format
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"{live_server.url}/pos/")
        page.wait_for_selector("#pos-split-layout")

        # 1. Verify TindAIOfflineStore global object is available
        has_store = page.evaluate("() => typeof window.TindAIOfflineStore === 'object'")
        assert has_store, "window.TindAIOfflineStore is not defined in browser"

        # 2. Test UUID generation format (RFC 4122 v4)
        uuid_str = page.evaluate("() => window.TindAIOfflineStore.generateUUID()")
        parsed_uuid = uuid.UUID(uuid_str, version=4)
        assert str(parsed_uuid) == uuid_str, f"Generated UUID '{uuid_str}' is not a valid v4 UUID"

        # 3. Test saving an offline transaction into IndexedDB
        test_tx_id = str(uuid.uuid4())
        save_result = page.evaluate(f"""
            async () => {{
                const tx = {{
                    id: '{test_tx_id}',
                    transaction_type: 'CASH',
                    items: [
                        {{ product_id: '{str(fmcg_item.id)}', quantity: 2, unit_price: 60 }}
                    ],
                    total_amount: '120.00',
                    notes: 'Empirical Challenger Test TX'
                }};
                return await window.TindAIOfflineStore.saveOfflineTransaction(tx);
            }}
        """)
        assert save_result["id"] == test_tx_id
        assert save_result["sync_status"] == "PENDING_OFFLINE"
        assert save_result["total_amount"] == "120.00"

        # 4. Verify record directly inside browser IndexedDB
        db_record = page.evaluate(f"""
            () => new Promise((resolve, reject) => {{
                const req = indexedDB.open('TindAIDB', 1);
                req.onsuccess = (e) => {{
                    const db = e.target.result;
                    const tx = db.transaction(['offline_transactions'], 'readonly');
                    const store = tx.objectStore('offline_transactions');
                    const getReq = store.get('{test_tx_id}');
                    getReq.onsuccess = () => resolve(getReq.result);
                    getReq.onerror = () => reject(getReq.error);
                }};
                req.onerror = () => reject(req.error);
            }})
        """)
        assert db_record is not None, "Record was not persisted in TindAIDB objectStore 'offline_transactions'"
        assert db_record["id"] == test_tx_id
        assert db_record["sync_status"] == "PENDING_OFFLINE"

        # 5. Test getPendingOfflineTransactions
        pending = page.evaluate("async () => await window.TindAIOfflineStore.getPendingOfflineTransactions()")
        assert any(item["id"] == test_tx_id for item in pending), "getPendingOfflineTransactions did not return test tx"

        # 6. Test markTransactionSynced
        synced_res = page.evaluate(f"async () => await window.TindAIOfflineStore.markTransactionSynced('{test_tx_id}')")
        assert synced_res["sync_status"] == "SYNCED"

        # Verify it no longer appears in pending list
        pending_after = page.evaluate("async () => await window.TindAIOfflineStore.getPendingOfflineTransactions()")
        assert not any(item["id"] == test_tx_id for item in pending_after), "Synced tx still appears in pending list"

        # 7. Test deleteOfflineTransaction
        del_res = page.evaluate(f"async () => await window.TindAIOfflineStore.deleteOfflineTransaction('{test_tx_id}')")
        assert del_res is True

        # Verify record is completely removed from IndexedDB
        db_record_after_del = page.evaluate(f"""
            () => new Promise((resolve, reject) => {{
                const req = indexedDB.open('TindAIDB', 1);
                req.onsuccess = (e) => {{
                    const db = e.target.result;
                    const tx = db.transaction(['offline_transactions'], 'readonly');
                    const store = tx.objectStore('offline_transactions');
                    const getReq = store.get('{test_tx_id}');
                    getReq.onsuccess = () => resolve(getReq.result);
                    getReq.onerror = () => reject(getReq.error);
                }};
            }})
        """)
        assert db_record_after_del is None or db_record_after_del == {} or not db_record_after_del

        browser.close()


@pytest.mark.django_db(transaction=True)
def test_browser_offline_banner_and_form_interception(live_server, fmcg_item):
    """
    Tests DOM indicators and offline form submission interception in Chromium:
    - Banner shows on offline event and hides on online event
    - Intercepts checkout form when navigator.onLine is false
    - Empties cart UI and queues to IndexedDB
    - Shows sync notification toast upon completion
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"{live_server.url}/pos/")
        page.wait_for_selector("#pos-split-layout")

        banner = page.locator("#offline-status-banner")
        toast = page.locator("#sync-toast-notification")

        # 1. When online initially, banner and toast should have class 'hidden'
        assert "hidden" in banner.get_attribute("class")
        assert "hidden" in toast.get_attribute("class")

        # 2. Trigger offline event
        page.evaluate("""() => {
            Object.defineProperty(navigator, 'onLine', { value: false, configurable: true });
            window.dispatchEvent(new Event('offline'));
        }""")
        page.wait_for_timeout(200)

        # Banner should now be visible (not hidden)
        assert "hidden" not in banner.get_attribute("class"), "Offline status banner should be visible when offline"
        banner_text = banner.locator("#offline-status-text").inner_text()
        assert "Offline Mode - Naka-save sa Phone" in banner_text

        # 3. Add item to cart via tingi button
        page.locator(f"#tingi-btn-{fmcg_item.id}").click()
        page.wait_for_selector(".cart-item-row")

        cart_row = page.locator(".cart-item-row").first
        assert cart_row.get_attribute("data-id") == str(fmcg_item.id)
        assert cart_row.get_attribute("data-price") == str(fmcg_item.retail_price)

        # 4. Attempt checkout submission while offline
        page.locator("#checkout-submit-btn").click()
        page.wait_for_timeout(500)

        # Cart should show offline confirmation badge
        cart_html = page.locator("#cart-container").inner_html()
        assert "Naka-save sa Phone!" in cart_html, "Offline badge did not appear in cart-container"

        # 5. IndexedDB should contain the queued transaction
        pending = page.evaluate("async () => await window.TindAIOfflineStore.getPendingOfflineTransactions()")
        assert len(pending) >= 1
        queued_tx = pending[-1]
        assert queued_tx["sync_status"] == "PENDING_OFFLINE"
        assert queued_tx["items"][0]["product_id"] == str(fmcg_item.id)

        # 6. Reconnect to online
        page.evaluate("""() => {
            Object.defineProperty(navigator, 'onLine', { value: true, configurable: true });
            window.dispatchEvent(new Event('online'));
        }""")
        page.wait_for_timeout(500)

        # Banner should be hidden again
        assert "hidden" in banner.get_attribute("class"), "Offline banner should hide when online"

        browser.close()


# =============================================================================
# 2. Template DOM Attributes & HTMX Integrity
# =============================================================================

@pytest.mark.django_db
def test_dom_elements_and_htmx_handlers_integrity(fmcg_item):
    """
    Inspects pos.html and partials/cart.html:
    - #offline-status-banner exists with exact required text
    - #sync-toast-notification exists
    - .cart-item-row contains data-id, data-name, data-price, data-qty
    - HTMX targets and swaps remain valid (#cart-container, outerHTML)
    """
    client = Client()
    # Add an item so partials/cart.html renders the checkout-form and cart-item-row
    client.post(f'/cart/add/{fmcg_item.id}/')
    res = client.get('/pos/')
    assert res.status_code == 200
    html = res.content.decode('utf-8')

    assert 'id="offline-status-banner"' in html
    assert 'Offline Mode - Naka-save sa Phone' in html
    assert 'id="sync-toast-notification"' in html
    assert 'id="checkout-form"' in html
    assert 'cart-item-row' in html
    assert 'hx-target="#cart-container"' in html
    assert 'hx-swap="outerHTML"' in html


# =============================================================================
# 3. Stress-Testing: Sequential & Concurrent Checkout Idempotency
# =============================================================================

@pytest.mark.django_db
def test_sequential_duplicate_cash_checkout_idempotency(fmcg_item):
    """
    Verifies that identical client UUID sent sequentially absorbs idempotently
    without double decrementing stock or duplicating transactions.
    """
    client = Client()
    client_uuid = uuid.uuid4()
    initial_stock = fmcg_item.stock_quantity
    initial_movements = StockMovement.objects.count()

    payload = {
        "id": str(client_uuid),
        "sync_status": "PENDING_OFFLINE",
        "transaction_type": "CASH",
        "items": [{"product_id": str(fmcg_item.id), "quantity": 2}],
        "notes": "Challenger sequential cash test"
    }

    # First attempt
    res1 = client.post("/api/transactions", data=payload, content_type="application/json")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["id"] == str(client_uuid)

    fmcg_item.refresh_from_db()
    assert fmcg_item.stock_quantity == initial_stock - Decimal("2.0000")
    assert StockMovement.objects.count() == initial_movements + 1

    # Second attempt (same UUID)
    res2 = client.post("/api/transactions", data=payload, content_type="application/json")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["id"] == str(client_uuid)
    assert data2["sync_status"] == "SYNCED"

    # Stock must NOT be decremented again
    fmcg_item.refresh_from_db()
    assert fmcg_item.stock_quantity == initial_stock - Decimal("2.0000")
    assert StockMovement.objects.count() == initial_movements + 1
    assert Transaction.objects.filter(id=client_uuid).count() == 1


@pytest.mark.django_db
def test_sequential_duplicate_utang_checkout_idempotency(fmcg_item, test_customer):
    """
    Verifies that identical client UUID for UTANG absorbs idempotently sequentially
    without double incrementing customer debt balance.
    """
    client = Client()
    client_uuid = uuid.uuid4()
    initial_debt = test_customer.debt_balance
    initial_stock = fmcg_item.stock_quantity

    payload = {
        "id": str(client_uuid),
        "sync_status": "PENDING_OFFLINE",
        "transaction_type": "UTANG",
        "customer_id": str(test_customer.id),
        "items": [{"product_id": str(fmcg_item.id), "quantity": 1}],  # 1 x 60 = 60
        "notes": "Challenger sequential utang test"
    }

    res1 = client.post("/api/transactions", data=payload, content_type="application/json")
    assert res1.status_code == 200

    test_customer.refresh_from_db()
    assert test_customer.debt_balance == initial_debt + Decimal("60.00")

    # Second push with duplicate UUID
    res2 = client.post("/api/transactions", data=payload, content_type="application/json")
    assert res2.status_code == 200
    assert res2.json()["sync_status"] == "SYNCED"

    test_customer.refresh_from_db()
    assert test_customer.debt_balance == initial_debt + Decimal("60.00")


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_cash_checkout(fmcg_item):
    """
    Stress-test: Multiple concurrent threads submitting the EXACT SAME client UUID
    for CASH checkout at the same time.
    Verifies that only 1 transaction is created and inventory is decremented exactly once.
    """
    client_uuid = uuid.uuid4()
    initial_stock = fmcg_item.stock_quantity
    payload = {
        "id": str(client_uuid),
        "sync_status": "PENDING_OFFLINE",
        "transaction_type": "CASH",
        "items": [{"product_id": str(fmcg_item.id), "quantity": 2}],
        "notes": "Concurrent Cash Test"
    }

    results = []

    def send_req():
        c = Client()
        connections.close_all()
        r = c.post("/api/transactions", data=payload, content_type="application/json")
        return r.status_code, r.json()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(send_req) for _ in range(4)]
        for f in futures:
            results.append(f.result())

    # All requests should return 200 (either created or absorbed)
    status_codes = [r[0] for r in results]
    assert all(code == 200 for code in status_codes), f"Not all returned 200: {status_codes}"

    # Exactly 1 Transaction record in database
    tx_count = Transaction.objects.filter(id=client_uuid).count()
    assert tx_count == 1, f"Expected 1 transaction, got {tx_count}"

    # Stock should be decremented exactly once (2.0000 units, not 8 units)
    fmcg_item.refresh_from_db()
    expected_stock = initial_stock - Decimal("2.0000")
    assert fmcg_item.stock_quantity == expected_stock, (
        f"Inventory corrupted! Expected {expected_stock}, got {fmcg_item.stock_quantity}"
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_utang_checkout(fmcg_item, test_customer):
    """
    Stress-test: Multiple concurrent threads submitting the EXACT SAME client UUID
    for UTANG checkout at the same time.
    Verifies that only 1 transaction is created and debtor debt balance is incremented
    EXACTLY ONCE, never double-incremented.
    """
    client_uuid = uuid.uuid4()
    initial_debt = test_customer.debt_balance
    initial_stock = fmcg_item.stock_quantity
    payload = {
        "id": str(client_uuid),
        "sync_status": "PENDING_OFFLINE",
        "transaction_type": "UTANG",
        "customer_id": str(test_customer.id),
        "items": [{"product_id": str(fmcg_item.id), "quantity": 1}],  # 1 x 60 = 60
        "notes": "Concurrent Utang Test"
    }

    results = []

    def send_req():
        c = Client()
        connections.close_all()
        r = c.post("/api/transactions", data=payload, content_type="application/json")
        return r.status_code, r.json()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(send_req) for _ in range(4)]
        for f in futures:
            results.append(f.result())

    status_codes = [r[0] for r in results]
    assert all(code == 200 for code in status_codes), f"Not all returned 200: {status_codes}"

    tx_count = Transaction.objects.filter(id=client_uuid).count()
    assert tx_count == 1, f"Expected 1 transaction, got {tx_count}"

    test_customer.refresh_from_db()
    expected_debt = initial_debt + Decimal("60.00")
    assert test_customer.debt_balance == expected_debt, (
        f"Customer debt corrupted! Expected {expected_debt}, got {test_customer.debt_balance}"
    )

    fmcg_item.refresh_from_db()
    assert fmcg_item.stock_quantity == initial_stock - Decimal("1.0000")


@pytest.mark.django_db(transaction=True)
def test_concurrent_novel_uuid_stock_depletion(fmcg_item):
    """
    Stress-test: 5 concurrent threads submitting NOVEL client UUIDs competing
    for limited stock (stock = 4 units, each requests 2 units).
    Exactly 2 transactions should succeed (4 units total), and 3 should fail
    with HTTP 400 Insufficient stock. Stock must not become negative.
    """
    fmcg_item.stock_quantity = Decimal("4.0000")
    fmcg_item.save()

    results = []

    def send_novel_req():
        c = Client()
        connections.close_all()
        req_payload = {
            "id": str(uuid.uuid4()),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [{"product_id": str(fmcg_item.id), "quantity": 2}],
            "notes": "Novel UUID race test"
        }
        r = c.post("/api/transactions", data=req_payload, content_type="application/json")
        return r.status_code

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(send_novel_req) for _ in range(5)]
        for f in futures:
            results.append(f.result())

    success_count = sum(1 for code in results if code == 200)
    failed_count = sum(1 for code in results if code == 400)

    assert success_count == 2, f"Expected 2 successful checkouts, got {success_count}. Codes: {results}"
    assert failed_count == 3, f"Expected 3 rejected checkouts, got {failed_count}. Codes: {results}"

    fmcg_item.refresh_from_db()
    assert fmcg_item.stock_quantity == Decimal("0.0000"), f"Stock was oversold: {fmcg_item.stock_quantity}"


@pytest.mark.django_db
def test_sequential_novel_uuid_stock_depletion_exhaustion(fmcg_item):
    """
    Verifies that sequential submissions of novel client UUIDs deplete stock accurately
    and reject once stock reaches zero (preventing overselling).
    """
    client = Client()
    fmcg_item.stock_quantity = Decimal("4.0000")
    fmcg_item.save()

    results = []
    for _ in range(5):
        req_payload = {
            "id": str(uuid.uuid4()),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [{"product_id": str(fmcg_item.id), "quantity": 2}],
            "notes": "Sequential novel UUID test"
        }
        r = client.post("/api/transactions", data=req_payload, content_type="application/json")
        results.append(r.status_code)

    assert results == [200, 200, 400, 400, 400]
    fmcg_item.refresh_from_db()
    assert fmcg_item.stock_quantity == Decimal("0.0000")
