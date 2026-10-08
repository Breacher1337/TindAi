import uuid
import re
from decimal import Decimal
import pytest
from django.db import IntegrityError, transaction as db_transaction
from django.urls import reverse
from django.utils import timezone
from core.models import (
    Product, Customer, CustomerPayment, Transaction, TransactionItem,
    InventoryBatch, StockMovement
)
from core.services.inventory import deplete_product_inventory_fifo, record_restock_batch


@pytest.fixture
def test_product(db):
    return Product.objects.create(
        sku="TEST-SKU-CHALLENGER-01",
        name="Lucky Me Pancit Canton Original",
        brand="Monde Nissin",
        category="Instant Noodles",
        wholesale_cost=Decimal("11.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=Decimal("100.0000"),
        reorder_point=20,
        pack_unit="box",
        tingi_unit="pouch"
    )


@pytest.fixture
def debtor_customer(db):
    return Customer.objects.create(
        name="Mang Juan Reyes",
        nickname="Juan",
        phone="0919-876-5432",
        address="Zone 3, Sitio Ilaya",
        credit_limit=Decimal("2000.00"),
        debt_balance=Decimal("800.00")
    )


# =============================================================================
# 1. Transaction Numbering Generation and Uniqueness
# =============================================================================

@pytest.mark.django_db
class TestTransactionNumberingEmpirical:
    """Empirical challenge on transaction numbering format, sequencing, custom handling, and uniqueness."""

    def test_sequential_50_transactions_unique_numbering(self, db):
        """Verify sequential creation of 50 transactions produces 50 unique formatted IDs."""
        today_str = timezone.now().strftime("%Y%m%d")
        created_numbers = []

        for i in range(50):
            tx = Transaction.objects.create(
                transaction_type=Transaction.TYPE_CASH,
                total_amount=Decimal("50.00")
            )
            assert tx.transaction_number is not None
            created_numbers.append(tx.transaction_number)

        # 1. Uniqueness check
        assert len(set(created_numbers)) == 50, "Duplicate transaction numbers generated!"

        # 2. Strict format check: TXN-YYYYMMDD-XXXX
        pattern = re.compile(rf"^TXN-{today_str}-\d{{4}}$")
        for num in created_numbers:
            assert pattern.match(num), f"Transaction number '{num}' violates TXN-YYYYMMDD-XXXX pattern"

        # 3. Suffix monotonicity / sequencing check
        suffixes = [int(num.split("-")[2]) for num in created_numbers]
        # Should be strictly monotonically increasing
        for idx in range(len(suffixes) - 1):
            assert suffixes[idx] < suffixes[idx + 1], f"Non-increasing suffix: {suffixes[idx]} >= {suffixes[idx+1]}"

    def test_custom_transaction_number_preserved(self, db):
        """Verify custom transaction number is NOT overwritten by save() auto-generation."""
        custom_id_1 = "CUSTOM-TXN-OFFLINE-999"
        tx1 = Transaction.objects.create(
            transaction_number=custom_id_1,
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("100.00")
        )
        assert tx1.transaction_number == custom_id_1

        # Even with TXN format prefix
        custom_id_2 = "TXN-20261001-9999"
        tx2 = Transaction.objects.create(
            transaction_number=custom_id_2,
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("150.00")
        )
        assert tx2.transaction_number == custom_id_2

    def test_auto_generation_skips_existing_custom_numbers(self, db):
        """
        Verify auto-generation loop detects collisions with pre-existing numbers and advances:
        If TXN-YYYYMMDD-0002 is pre-seeded, auto-generating txns must pick 0001, then skip 0002 to 0003.
        """
        today_str = timezone.now().strftime("%Y%m%d")
        pre_seeded = f"TXN-{today_str}-0002"
        Transaction.objects.create(
            transaction_number=pre_seeded,
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("10.00")
        )

        # Generate two transactions
        tx_a = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("20.00")
        )
        tx_b = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("30.00")
        )

        all_numbers = {tx_a.transaction_number, tx_b.transaction_number, pre_seeded}
        assert len(all_numbers) == 3, f"Collision occurred when skipping pre-seeded number: {all_numbers}"
        assert tx_a.transaction_number != pre_seeded
        assert tx_b.transaction_number != pre_seeded

    def test_duplicate_custom_transaction_number_raises_integrity_error(self, db):
        """DB unique constraint on transaction_number must strictly raise IntegrityError on duplicate."""
        Transaction.objects.create(
            transaction_number="TXN-DUPLICATE-001",
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("25.00")
        )
        with pytest.raises(IntegrityError):
            Transaction.objects.create(
                transaction_number="TXN-DUPLICATE-001",
                transaction_type=Transaction.TYPE_CASH,
                total_amount=Decimal("50.00")
            )

    def test_concurrent_transaction_creation_race_behavior(self, db):
        """
        Adversarial test: Verify collision behavior when two transactions generate the same candidate number.
        In Transaction.save(), if count() + 1 generates an already-existing candidate,
        the while exists() loop advances to avoid collision; if an exact duplicate candidate is forced
        (as in a concurrent race condition), the DB unique constraint strictly raises IntegrityError.
        """
        today_str = timezone.now().strftime("%Y%m%d")
        candidate = f"TXN-{today_str}-0099"

        # First transaction with candidate
        tx1 = Transaction.objects.create(
            transaction_number=candidate,
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("25.00")
        )
        assert tx1.transaction_number == candidate

        # Second transaction attempting exact same candidate (simulating simultaneous save race)
        with pytest.raises(IntegrityError):
            Transaction.objects.create(
                transaction_number=candidate,
                transaction_type=Transaction.TYPE_CASH,
                total_amount=Decimal("35.00")
            )

    def test_transaction_cogs_and_profit_edge_cases(self, db):
        """Verify gross profit calculation when cogs == total_amount, cogs == 0, and cogs > total_amount."""
        # 1. Total amount == COGS -> gross_profit == 0.00
        tx1 = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("100.00"),
            total_cogs=Decimal("100.00")
        )
        assert tx1.gross_profit == Decimal("0.00")

        # 2. Total amount > COGS
        tx2 = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("100.00"),
            total_cogs=Decimal("70.00")
        )
        assert tx2.gross_profit == Decimal("30.00")

        # 3. Total amount < COGS (selling at loss)
        tx3 = Transaction.objects.create(
            transaction_type=Transaction.TYPE_CASH,
            total_amount=Decimal("80.00"),
            total_cogs=Decimal("100.00")
        )
        assert tx3.gross_profit == Decimal("-20.00")


# =============================================================================
# 2. CustomerPayment Balance Auditing
# =============================================================================

@pytest.mark.django_db
class TestCustomerPaymentBalanceAuditingEmpirical:
    """Empirical challenge on CustomerPayment balance_before and balance_after integrity."""

    def test_api_full_repayment_balance_snapshot(self, api_client, debtor_customer):
        """Full debt repayment via API accurately sets balance_after to 0.00 and updates customer."""
        initial_debt = debtor_customer.debt_balance
        assert initial_debt == Decimal("800.00")

        payload = {"amount": 800.00, "notes": "Full settlement"}
        resp = api_client.post(
            f"/api/customers/{debtor_customer.id}/payments",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.json()

        assert Decimal(str(data["amount"])) == Decimal("800.00")
        assert Decimal(str(data["balance_before"])) == Decimal("800.00")
        assert Decimal(str(data["balance_after"])) == Decimal("0.00")
        assert Decimal(str(data["new_debt_balance"])) == Decimal("0.00")

        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("0.00")

        # Verify persisted record
        payment = CustomerPayment.objects.get(id=data["id"])
        assert payment.balance_before == Decimal("800.00")
        assert payment.balance_after == Decimal("0.00")

    def test_api_partial_repayment_balance_snapshot(self, api_client, debtor_customer):
        """Partial repayment accurately computes balance_before and balance_after."""
        payload = {"amount": 250.50, "notes": "Partial bayad"}
        resp = api_client.post(
            f"/api/customers/{debtor_customer.id}/payments",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.json()

        assert Decimal(str(data["amount"])) == Decimal("250.50")
        assert Decimal(str(data["balance_before"])) == Decimal("800.00")
        assert Decimal(str(data["balance_after"])) == Decimal("549.50")
        assert Decimal(str(data["new_debt_balance"])) == Decimal("549.50")

        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("549.50")

    def test_api_multi_step_audit_chain_continuity(self, api_client, debtor_customer):
        """
        Sequential repayments form an unbroken audit chain:
        payment[i].balance_after MUST equal payment[i+1].balance_before.
        """
        payments_amounts = [Decimal("100.00"), Decimal("250.00"), Decimal("150.00"), Decimal("300.00")]
        recorded_payments = []

        for amt in payments_amounts:
            resp = api_client.post(
                f"/api/customers/{debtor_customer.id}/payments",
                data={"amount": float(amt), "notes": f"Chain test {amt}"},
                content_type="application/json"
            )
            assert resp.status_code == 200
            recorded_payments.append(resp.json())

        # Audit continuity check
        for i in range(len(recorded_payments) - 1):
            prev_after = Decimal(str(recorded_payments[i]["balance_after"]))
            next_before = Decimal(str(recorded_payments[i + 1]["balance_before"]))
            assert prev_after == next_before, (
                f"Broken audit chain at step {i}: prev_after={prev_after} != next_before={next_before}"
            )

        # Final balance check
        final_after = Decimal(str(recorded_payments[-1]["balance_after"]))
        assert final_after == Decimal("0.00")
        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("0.00")

    def test_api_overpayment_clamps_balance_to_zero(self, api_client, debtor_customer):
        """Overpayment amount > debt clamps balance_after to 0.00 and does NOT allow negative debt."""
        payload = {"amount": 1000.00, "notes": "Overpaying debt of 800"}
        resp = api_client.post(
            f"/api/customers/{debtor_customer.id}/payments",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.json()

        assert Decimal(str(data["balance_before"])) == Decimal("800.00")
        assert Decimal(str(data["balance_after"])) == Decimal("0.00")
        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("0.00")

    def test_api_zero_payment_rejected(self, api_client, debtor_customer):
        """Zero amount repayment is strictly rejected with 422 or 400."""
        payload = {"amount": 0.00, "notes": "Zero bayad"}
        resp = api_client.post(
            f"/api/customers/{debtor_customer.id}/payments",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code in (400, 422)
        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("800.00")

    def test_api_negative_payment_rejected(self, api_client, debtor_customer):
        """Negative amount repayment is strictly rejected with 422 or 400."""
        payload = {"amount": -100.00, "notes": "Negative payment"}
        resp = api_client.post(
            f"/api/customers/{debtor_customer.id}/payments",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code in (400, 422)
        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("800.00")

    def test_api_payment_nonexistent_customer_returns_404(self, api_client):
        """Payment to non-existent UUID returns 404."""
        non_existent_id = uuid.uuid4()
        resp = api_client.post(
            f"/api/customers/{non_existent_id}/payments",
            data={"amount": 50.00, "notes": "Test"},
            content_type="application/json"
        )
        assert resp.status_code == 404

    def test_view_utang_pay_balance_auditing(self, client, debtor_customer):
        """Standard Django view POST /utang/pay/ correctly snapshots balance_before and balance_after."""
        response = client.post(reverse("utang_pay"), {
            "customer_id": str(debtor_customer.id),
            "amount": "300.00",
            "notes": "Counter cash payment"
        })
        assert response.status_code == 302

        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("500.00")

        payment = CustomerPayment.objects.filter(customer=debtor_customer).latest("created_at")
        assert payment.amount == Decimal("300.00")
        assert payment.balance_before == Decimal("800.00")
        assert payment.balance_after == Decimal("500.00")

    def test_view_utang_pay_zero_and_negative_rejected(self, client, debtor_customer):
        """View strictly rejects zero, negative, or invalid amounts with 400."""
        # 1. Zero amount
        res_zero = client.post(reverse("utang_pay"), {
            "customer_id": str(debtor_customer.id),
            "amount": "0.00"
        })
        assert res_zero.status_code == 400

        # 2. Negative amount
        res_neg = client.post(reverse("utang_pay"), {
            "customer_id": str(debtor_customer.id),
            "amount": "-50.00"
        })
        assert res_neg.status_code == 400

        # 3. Non-numeric amount
        res_invalid = client.post(reverse("utang_pay"), {
            "customer_id": str(debtor_customer.id),
            "amount": "invalid_number"
        })
        assert res_invalid.status_code == 400

        # Customer debt balance must remain unchanged
        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("800.00")


# =============================================================================
# 3. Offline Transaction Client ID and Sync Status Insertion via /api/transactions
# =============================================================================

@pytest.mark.django_db
class TestOfflineTransactionSyncEmpirical:
    """Empirical challenge on client-assigned UUIDs, sync_status, FIFO batch deduction, and error paths."""

    def test_api_offline_cash_transaction_with_client_uuid(self, api_client, test_product):
        """Verify API accepts pre-assigned client UUID and sync_status=PENDING_OFFLINE."""
        client_uuid = uuid.uuid4()
        payload = {
            "id": str(client_uuid),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(test_product.id), "quantity": 3}
            ],
            "notes": "Offline POS sale from device storage"
        }

        resp = api_client.post(
            "/api/transactions",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.json()

        # 1. Exact client UUID preserved
        assert data["id"] == str(client_uuid)
        assert data["sync_status"] == "PENDING_OFFLINE"
        assert data["transaction_type"] == "CASH"
        assert Decimal(str(data["total_amount"])) == Decimal("45.00")
        assert data["transaction_number"] is not None
        assert data["transaction_number"].startswith("TXN-")

        # 2. DB verification
        tx = Transaction.objects.get(id=client_uuid)
        assert tx.id == client_uuid
        assert tx.sync_status == Transaction.SYNC_STATUS_PENDING
        assert tx.total_amount == Decimal("45.00")
        assert tx.payment_status == Transaction.STATUS_PAID

    def test_api_offline_utang_transaction_with_customer(self, api_client, test_product, debtor_customer):
        """Verify offline UTANG transaction properly increments debtor balance and sets payment_status=UNPAID."""
        client_uuid = uuid.uuid4()
        initial_debt = debtor_customer.debt_balance
        assert initial_debt == Decimal("800.00")

        payload = {
            "id": str(client_uuid),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "UTANG",
            "customer_id": str(debtor_customer.id),
            "items": [
                {"product_id": str(test_product.id), "quantity": 4}
            ],
            "notes": "Offline credit sale"
        }

        resp = api_client.post(
            "/api/transactions",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["id"] == str(client_uuid)
        assert data["sync_status"] == "PENDING_OFFLINE"
        assert data["payment_status"] == "UNPAID"
        assert Decimal(str(data["total_amount"])) == Decimal("60.00")

        # Customer debt balance updated
        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == initial_debt + Decimal("60.00")

    def test_api_offline_transaction_depletes_fifo_batches_and_creates_stock_movement(self, api_client, test_product):
        """Verify offline checkout depletes InventoryBatch records and logs StockMovement with client reference."""
        client_uuid = uuid.uuid4()

        # Create two batches with different received_at and cost basis
        t_batch1 = timezone.now() - timezone.timedelta(days=3)
        t_batch2 = timezone.now() - timezone.timedelta(days=1)

        b1 = InventoryBatch.objects.create(
            product=test_product,
            initial_tingi_quantity=Decimal("5.0000"),
            remaining_tingi_quantity=Decimal("5.0000"),
            unit_cost_basis=Decimal("10.00"),
            received_at=t_batch1
        )
        b2 = InventoryBatch.objects.create(
            product=test_product,
            initial_tingi_quantity=Decimal("10.0000"),
            remaining_tingi_quantity=Decimal("10.0000"),
            unit_cost_basis=Decimal("12.00"),
            received_at=t_batch2
        )
        test_product.stock_quantity = Decimal("15.0000")
        test_product.save()

        # Buy 8 items (5 from b1 @ 10.00 = 50.00; 3 from b2 @ 12.00 = 36.00; total COGS = 86.00)
        payload = {
            "id": str(client_uuid),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(test_product.id), "quantity": 8}
            ]
        }

        resp = api_client.post(
            "/api/transactions",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.json()

        assert Decimal(str(data["total_cogs"])) == Decimal("86.00")
        # Revenue = 8 * 15 = 120.00; gross profit = 120.00 - 86.00 = 34.00
        assert Decimal(str(data["gross_profit"])) == Decimal("34.00")

        # Batches depleted
        b1.refresh_from_db()
        b2.refresh_from_db()
        assert b1.remaining_tingi_quantity == Decimal("0.0000")
        assert b2.remaining_tingi_quantity == Decimal("7.0000")

        # StockMovement created with reference_id = client_uuid
        movements = StockMovement.objects.filter(product=test_product, reference_id=str(client_uuid))
        assert movements.count() == 1
        mv = movements.first()
        assert mv.movement_type == StockMovement.MOVEMENT_SALE
        assert mv.quantity_change == Decimal("-8.0000")
        assert mv.balance_after == Decimal("7.0000")

    def test_api_transaction_without_client_id_generates_uuid_and_defaults_synced(self, api_client, test_product):
        """When id and sync_status are omitted, server assigns fresh UUID and defaults to SYNCED."""
        payload = {
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(test_product.id), "quantity": 1}
            ]
        }
        resp = api_client.post(
            "/api/transactions",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.json()

        assigned_id = uuid.UUID(data["id"])
        assert isinstance(assigned_id, uuid.UUID)
        assert data["sync_status"] == "SYNCED"

    def test_api_transaction_insufficient_stock_fails_and_rolls_back(self, api_client, test_product):
        """Transaction requesting more stock than available fails with 400 and creates no records."""
        test_product.stock_quantity = Decimal("2.0000")
        test_product.save()

        client_uuid = uuid.uuid4()
        payload = {
            "id": str(client_uuid),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(test_product.id), "quantity": 10}
            ]
        }

        resp = api_client.post(
            "/api/transactions",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 400

        # Verify rollback: no transaction created, stock untouched
        assert not Transaction.objects.filter(id=client_uuid).exists()
        test_product.refresh_from_db()
        assert test_product.stock_quantity == Decimal("2.0000")

    def test_api_transaction_utang_exceeds_credit_limit_fails_and_rolls_back(self, api_client, test_product, debtor_customer):
        """Utang transaction exceeding customer credit limit fails with 400 and creates no records."""
        debtor_customer.credit_limit = Decimal("500.00")
        debtor_customer.debt_balance = Decimal("480.00")
        debtor_customer.save()

        client_uuid = uuid.uuid4()
        # Item price 15 * 2 = 30; 480 + 30 = 510 > 500
        payload = {
            "id": str(client_uuid),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "UTANG",
            "customer_id": str(debtor_customer.id),
            "items": [
                {"product_id": str(test_product.id), "quantity": 2}
            ]
        }

        resp = api_client.post(
            "/api/transactions",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 400

        assert not Transaction.objects.filter(id=client_uuid).exists()
        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("480.00")

    def test_api_transaction_malformed_client_uuid_rejected(self, api_client, test_product):
        """Malformed client UUID string in payload is rejected with 422 by Ninja schema validator."""
        payload = {
            "id": "not-a-valid-uuid-string",
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(test_product.id), "quantity": 1}
            ]
        }
        resp = api_client.post(
            "/api/transactions",
            data=payload,
            content_type="application/json"
        )
        assert resp.status_code == 422

    def test_api_transaction_duplicate_client_id_empirical(self, api_client, test_product):
        """
        Adversarial test: Re-submitting the exact same client UUID.
        In M1, the endpoint does not yet do idempotent duplicate absorption;
        sending duplicate UUID raises IntegrityError in Django.
        We verify the empirical behavior to document for M2.
        """
        client_uuid = uuid.uuid4()
        payload = {
            "id": str(client_uuid),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "CASH",
            "items": [
                {"product_id": str(test_product.id), "quantity": 1}
            ]
        }

        # First push succeeds
        resp1 = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert resp1.status_code == 200

        # Second push with duplicate client_uuid:
        # In M2, idempotent absorption returns HTTP 200 with existing transaction and sync_status="SYNCED"
        resp2 = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert resp2.status_code == 200
        assert resp2.json()["id"] == str(client_uuid)
        assert resp2.json()["sync_status"] == "SYNCED"
        # Verify stock was only decremented once
        test_product.refresh_from_db()
        assert test_product.stock_quantity == Decimal("99.0000")


    def test_fifo_depletion_with_mixed_batched_and_unbatched_stock(self, db, test_product):
        """
        Verify FIFO service when stock is partially batched and partially unbatched.
        Product wholesale_cost = 11.00.
        One batch has 4 units @ 9.00.
        Sell 7 units: 4 from batch (36.00) + 3 unbatched remainder @ 11.00 (33.00) = 69.00 total COGS.
        """
        test_product.stock_quantity = Decimal("10.0000")
        test_product.wholesale_cost = Decimal("11.00")
        test_product.save()

        b = InventoryBatch.objects.create(
            product=test_product,
            initial_tingi_quantity=Decimal("4.0000"),
            remaining_tingi_quantity=Decimal("4.0000"),
            unit_cost_basis=Decimal("9.00"),
            received_at=timezone.now()
        )

        cogs, unit_cost = deplete_product_inventory_fifo(
            product=test_product,
            quantity=Decimal("7.0000"),
            reference_id="TEST-MIXED-FIFO"
        )

        assert cogs == Decimal("69.00")
        b.refresh_from_db()
        assert b.remaining_tingi_quantity == Decimal("0.0000")
        test_product.refresh_from_db()
        assert test_product.stock_quantity == Decimal("3.0000")

    def test_offline_utang_transaction_exact_credit_limit_boundary(self, api_client, test_product, debtor_customer):
        """
        Boundary condition: Utang checkout at EXACT credit limit boundary succeeds,
        but 1 cent over fails.
        """
        debtor_customer.credit_limit = Decimal("1000.00")
        debtor_customer.debt_balance = Decimal("970.00")
        debtor_customer.save()
        test_product.retail_price = Decimal("15.00")
        test_product.stock_quantity = Decimal("10.0000")
        test_product.save()

        # Buy 2 items @ 15.00 = 30.00; total debt = 970 + 30 = 1000.00 (exactly at limit)
        tx_id_1 = uuid.uuid4()
        payload1 = {
            "id": str(tx_id_1),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "UTANG",
            "customer_id": str(debtor_customer.id),
            "items": [{"product_id": str(test_product.id), "quantity": 2}]
        }
        resp1 = api_client.post("/api/transactions", data=payload1, content_type="application/json")
        assert resp1.status_code == 200
        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("1000.00")

        # Now debt is 1000.00 (limit is 1000.00); attempting any further utang must fail
        tx_id_2 = uuid.uuid4()
        payload2 = {
            "id": str(tx_id_2),
            "sync_status": "PENDING_OFFLINE",
            "transaction_type": "UTANG",
            "customer_id": str(debtor_customer.id),
            "items": [{"product_id": str(test_product.id), "quantity": 1}]
        }
        resp2 = api_client.post("/api/transactions", data=payload2, content_type="application/json")
        assert resp2.status_code == 400
        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("1000.00")

    def test_api_empty_items_rejected(self, api_client):
        """API checkout with empty items list must return 400."""
        payload = {
            "transaction_type": "CASH",
            "items": []
        }
        resp = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert resp.status_code == 400

    def test_customer_repayment_repeated_overpayment_maintains_zero_balance(self, api_client, debtor_customer):
        """Sequential overpayments on an already-zero balance customer strictly stay at 0.00."""
        debtor_customer.debt_balance = Decimal("0.00")
        debtor_customer.save()

        for amt in [100.00, 250.00]:
            resp = api_client.post(
                f"/api/customers/{debtor_customer.id}/payments",
                data={"amount": amt, "notes": "Overpayment"},
                content_type="application/json"
            )
            assert resp.status_code == 200
            data = resp.json()
            assert Decimal(str(data["balance_before"])) == Decimal("0.00")
            assert Decimal(str(data["balance_after"])) == Decimal("0.00")

        debtor_customer.refresh_from_db()
        assert debtor_customer.debt_balance == Decimal("0.00")
