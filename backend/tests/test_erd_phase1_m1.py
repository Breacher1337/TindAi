import uuid
from decimal import Decimal
import pytest
from django.urls import reverse
from django.utils import timezone
from core.models import (
    Product, Customer, CustomerPayment, Transaction, TransactionItem,
    RestockRun, RestockInvoice, RestockInvoiceItem, Wholesaler,
    InventoryBatch, StockMovement, StoreConfig
)
from core.services.inventory import deplete_product_inventory_fifo, record_restock_batch
from core.services.knapsack import solve_restock_knapsack


@pytest.fixture
def test_wholesaler(db):
    return Wholesaler.objects.create(
        name="Puregold Price Club",
        branch="Shaw Boulevard, Mandaluyong",
        contact_number="0917-123-4567"
    )


@pytest.fixture
def fmcg_item(db):
    return Product.objects.create(
        sku="SKU-COFF-001",
        name="Kopiko Blanca 3-in-1 Coffee 30g",
        brand="Kopiko",
        category="Beverages",
        wholesale_cost=Decimal("9.50"),
        retail_price=Decimal("13.00"),
        stock_quantity=Decimal("30.0000"),
        reorder_point=10,
        pack_unit="pack of 10",
        tingi_unit="sachet"
    )


@pytest.fixture
def regular_customer(db):
    return Customer.objects.create(
        name="Aling Nena Cruz",
        nickname="Nena",
        phone="0918-987-6543",
        address="14 Interior, Riverside St.",
        credit_limit=Decimal("1500.00"),
        debt_balance=Decimal("350.00")
    )


@pytest.mark.django_db
class TestUUIDPrimaryKeyArchitecture:
    """Validate that all domain entities utilize genuine UUIDField primary keys."""

    def test_domain_models_have_uuid_primary_keys(self, db, test_wholesaler, fmcg_item, regular_customer):
        # Wholesaler
        assert isinstance(test_wholesaler.id, uuid.UUID)

        # Product
        assert isinstance(fmcg_item.id, uuid.UUID)

        # Customer
        assert isinstance(regular_customer.id, uuid.UUID)

        # CustomerPayment
        payment = CustomerPayment.objects.create(
            customer=regular_customer,
            amount=Decimal("100.00"),
            balance_before=Decimal("350.00"),
            balance_after=Decimal("250.00")
        )
        assert isinstance(payment.id, uuid.UUID)

        # Transaction & TransactionItem
        tx = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("26.00"),
            payment_status=Transaction.STATUS_PAID
        )
        assert isinstance(tx.id, uuid.UUID)

        tx_item = TransactionItem.objects.create(
            transaction=tx,
            product=fmcg_item,
            quantity=Decimal("2.0000"),
            unit_price=Decimal("13.00"),
            cost_price=Decimal("9.50"),
            subtotal=Decimal("26.00")
        )
        assert isinstance(tx_item.id, uuid.UUID)

        # RestockInvoice & RestockInvoiceItem
        invoice = RestockInvoice.objects.create(
            wholesaler=test_wholesaler,
            wholesaler_name=test_wholesaler.name,
            invoice_no="INV-2026-9999",
            date=timezone.localdate(),
            total_amount=Decimal("950.00"),
            parse_status=RestockInvoice.PARSE_CONFIRMED
        )
        assert isinstance(invoice.id, uuid.UUID)

        invoice_item = RestockInvoiceItem.objects.create(
            invoice=invoice,
            product=fmcg_item,
            raw_line_text="KOPIKO BLANCA 10S",
            qty_packs=10,
            pack_wholesale_cost=Decimal("95.00"),
            line_total=Decimal("950.00")
        )
        assert isinstance(invoice_item.id, uuid.UUID)

        # RestockRun
        run = RestockRun.objects.create(
            budget=Decimal("5000.00"),
            total_spent=Decimal("4950.00")
        )
        assert isinstance(run.id, uuid.UUID)

        # InventoryBatch
        batch = InventoryBatch.objects.create(
            product=fmcg_item,
            invoice_item=invoice_item,
            initial_tingi_quantity=Decimal("100.0000"),
            remaining_tingi_quantity=Decimal("100.0000"),
            unit_cost_basis=Decimal("9.50")
        )
        assert isinstance(batch.id, uuid.UUID)

        # StockMovement
        movement = StockMovement.objects.create(
            product=fmcg_item,
            movement_type=StockMovement.MOVEMENT_RESTOCK,
            quantity_change=Decimal("100.0000"),
            balance_after=Decimal("130.0000"),
            reference_id=str(invoice.id)
        )
        assert isinstance(movement.id, uuid.UUID)

    def test_store_config_retains_integer_primary_key_one(self, db):
        """StoreConfig singleton MUST retain integer pk=1."""
        config = StoreConfig.get_solo()
        assert config.pk == 1
        assert config.id == 1
        assert isinstance(config.id, int)


@pytest.mark.django_db
class TestEntityAttributesAndConstraints:
    """Validate added entity attributes and auto-generation behaviors."""

    def test_transaction_number_auto_generation_and_uniqueness(self, db):
        tx1 = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("50.00")
        )
        assert tx1.transaction_number is not None
        assert tx1.transaction_number.startswith("TXN-")

        tx2 = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("100.00")
        )
        assert tx2.transaction_number is not None
        assert tx2.transaction_number.startswith("TXN-")
        assert tx1.transaction_number != tx2.transaction_number

    def test_transaction_cogs_and_gross_profit_computation(self, db):
        tx = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("200.00"),
            total_cogs=Decimal("140.00")
        )
        assert tx.gross_profit == Decimal("60.00")
        assert tx.sync_status == Transaction.SYNC_STATUS_SYNCED

    def test_customer_payment_balance_snapshotting(self, db, regular_customer):
        initial_balance = regular_customer.debt_balance
        payment_amount = Decimal("150.00")
        new_balance = initial_balance - payment_amount

        payment = CustomerPayment.objects.create(
            customer=regular_customer,
            amount=payment_amount,
            balance_before=initial_balance,
            balance_after=new_balance,
            notes="Partial payment"
        )
        regular_customer.debt_balance = new_balance
        regular_customer.save()

        assert payment.balance_before == Decimal("350.00")
        assert payment.balance_after == Decimal("200.00")
        assert regular_customer.debt_balance == Decimal("200.00")

    def test_restock_invoice_wholesaler_relationship_and_parse_status(self, db, test_wholesaler):
        invoice = RestockInvoice.objects.create(
            wholesaler=test_wholesaler,
            wholesaler_name=test_wholesaler.name,
            invoice_no="INV-SUPER8-001",
            total_amount=Decimal("1200.00"),
            parse_status=RestockInvoice.PARSE_PARSED
        )
        assert invoice.wholesaler == test_wholesaler
        assert invoice.parse_status == "PARSED"
        assert test_wholesaler.invoices.count() == 1


@pytest.mark.django_db
class TestFIFOBatchDepletionAndStockMovements:
    """Verify genuine FIFO batch depletion arithmetic and StockMovement audit trail."""

    def test_fifo_depletes_oldest_batches_first(self, db, fmcg_item):
        """
        Setup 2 delivery batches:
        Batch 1 (older): 10 sachets @ ₱8.00 unit cost
        Batch 2 (newer): 15 sachets @ ₱10.00 unit cost
        Sell 14 sachets:
        Should consume 10 from Batch 1 (COGS = 10 * 8 = 80)
        and 4 from Batch 2 (COGS = 4 * 10 = 40)
        Total COGS = 120.00, remaining Batch 2 = 11 sachets.
        """
        # Clear any initial stock
        fmcg_item.stock_quantity = Decimal("25.0000")
        fmcg_item.save()

        t_past = timezone.now() - timezone.timedelta(days=2)
        t_recent = timezone.now() - timezone.timedelta(days=1)

        b1 = InventoryBatch.objects.create(
            product=fmcg_item,
            initial_tingi_quantity=Decimal("10.0000"),
            remaining_tingi_quantity=Decimal("10.0000"),
            unit_cost_basis=Decimal("8.00"),
            received_at=t_past
        )
        b2 = InventoryBatch.objects.create(
            product=fmcg_item,
            initial_tingi_quantity=Decimal("15.0000"),
            remaining_tingi_quantity=Decimal("15.0000"),
            unit_cost_basis=Decimal("10.00"),
            received_at=t_recent
        )

        cogs, unit_cost = deplete_product_inventory_fifo(
            product=fmcg_item,
            quantity=Decimal("14.0000"),
            reference_id="TEST-TXN-FIFO"
        )

        b1.refresh_from_db()
        b2.refresh_from_db()
        fmcg_item.refresh_from_db()

        assert b1.remaining_tingi_quantity == Decimal("0.0000")
        assert b2.remaining_tingi_quantity == Decimal("11.0000")
        assert fmcg_item.stock_quantity == Decimal("11.0000")
        assert cogs == Decimal("120.00")
        assert round(unit_cost, 4) == round(Decimal("120.00") / Decimal("14.0000"), 4)

        # Verify StockMovement record
        movements = StockMovement.objects.filter(product=fmcg_item, reference_id="TEST-TXN-FIFO")
        assert movements.count() == 1
        mv = movements.first()
        assert mv.movement_type == StockMovement.MOVEMENT_SALE
        assert mv.quantity_change == Decimal("-14.0000")
        assert mv.balance_after == Decimal("11.0000")

    def test_record_restock_batch_creates_batch_and_movement(self, db, fmcg_item):
        initial_stock = fmcg_item.stock_quantity
        batch = record_restock_batch(
            product=fmcg_item,
            quantity=Decimal("20.0000"),
            unit_cost=Decimal("10.50"),
            reference_id="RESTOCK-REF-001"
        )
        fmcg_item.refresh_from_db()

        assert batch.initial_tingi_quantity == Decimal("20.0000")
        assert batch.remaining_tingi_quantity == Decimal("20.0000")
        assert batch.unit_cost_basis == Decimal("10.50")
        assert fmcg_item.stock_quantity == initial_stock + Decimal("20.0000")
        assert fmcg_item.wholesale_cost == Decimal("10.50")

        movement = StockMovement.objects.get(product=fmcg_item, reference_id="RESTOCK-REF-001")
        assert movement.movement_type == StockMovement.MOVEMENT_RESTOCK
        assert movement.quantity_change == Decimal("20.0000")
        assert movement.balance_after == fmcg_item.stock_quantity


@pytest.mark.django_db
class TestViewAndAPIRouteUUIDCompatibility:
    """Verify views and Ninja API endpoints accept and return UUID types seamlessly."""

    def test_cart_add_and_remove_with_uuid_urls(self, client, fmcg_item):
        # Add to cart via UUID path
        res_add = client.post(reverse('cart_add', args=[fmcg_item.id]))
        assert res_add.status_code == 302
        session = client.session
        cart = session.get('cart', {})
        assert str(fmcg_item.id) in cart
        assert cart[str(fmcg_item.id)]['qty'] == 1

        # Remove from cart via UUID path
        res_rem = client.post(reverse('cart_remove', args=[fmcg_item.id]))
        assert res_rem.status_code == 302
        cart_after = client.session.get('cart', {})
        assert str(fmcg_item.id) not in cart_after

    def test_checkout_action_populates_cogs_profit_and_stock_movements(self, client, fmcg_item):
        # Create a batch
        InventoryBatch.objects.create(
            product=fmcg_item,
            initial_tingi_quantity=Decimal("10.0000"),
            remaining_tingi_quantity=Decimal("10.0000"),
            unit_cost_basis=Decimal("9.50")
        )

        client.post(reverse('cart_add', args=[fmcg_item.id]))
        res_checkout = client.post(reverse('checkout'), {'payment_method': 'CASH'})
        assert res_checkout.status_code == 302

        tx = Transaction.objects.filter(transaction_type='CASH').order_by('-created_at').first()
        assert tx is not None
        assert isinstance(tx.id, uuid.UUID)
        assert tx.transaction_number is not None
        assert tx.total_cogs == Decimal("9.50")
        assert tx.gross_profit == Decimal("13.00") - Decimal("9.50")

        movements = StockMovement.objects.filter(reference_id=str(tx.id))
        assert movements.count() == 1
        assert movements.first().movement_type == StockMovement.MOVEMENT_SALE

    def test_api_checkout_offline_sync_support(self, api_client, fmcg_item, regular_customer):
        """API checkout accepts optional pre-assigned client UUID and sync_status."""
        client_assigned_id = uuid.uuid4()
        payload = {
            "id": str(client_assigned_id),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "UTANG",
            "customer_id": str(regular_customer.id),
            "items": [
                {"product_id": str(fmcg_item.id), "quantity": 2}
            ],
            "notes": "Offline transaction flushed"
        }

        resp = api_client.post(
            "/api/transactions",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["id"] == str(client_assigned_id)
        assert data["sync_status"] == "PENDING_OFFLINE"
        assert data["transaction_number"] is not None
        assert Decimal(str(data["total_amount"])) == Decimal("26.00")
        assert Decimal(str(data["total_cogs"])) > Decimal("0.00")
        assert Decimal(str(data["gross_profit"])) > Decimal("0.00")

    def test_pulp_knapsack_with_uuid_sanitization(self, fmcg_item):
        """Verify knapsack solver handles UUID product keys without variable naming syntax errors."""
        res = solve_restock_knapsack([fmcg_item], budget=Decimal("1000.00"))
        assert res["solver_status"] in ("Optimal", "Integer optimal solution")
        assert res["total_spent"] <= Decimal("1000.00")
        if res["items"]:
            assert res["items"][0]["product_id"] == fmcg_item.id
