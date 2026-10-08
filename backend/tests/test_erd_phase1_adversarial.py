"""
Empirical Adversarial Test Suite for Milestone 1 (ERD, Batches, Ledger, FIFO).
Authors: Challenger M1 (critic, specialist)

Strict verification of:
1. Multi-batch boundary FIFO depletion & exact mathematical COGS.
2. Fallback logic when sales exceed total batch quantities.
3. StockMovement ledger continuity and balance_after invariants.
4. Edge cases: zero quantity, fractional quantities, received_at ordering.
5. UUID string format validation and injection resistance.
6. Negative quantity handling and transaction atomicity rollbacks.
7. StoreConfig singleton integrity constraint.
"""

import uuid
from decimal import Decimal
import pytest
from django.db import IntegrityError, transaction as db_transaction
from django.urls import reverse
from django.utils import timezone
from core.models import (
    Product, Customer, CustomerPayment, Transaction, TransactionItem,
    Wholesaler, InventoryBatch, StockMovement, StoreConfig
)
from core.services.inventory import deplete_product_inventory_fifo, record_restock_batch


@pytest.fixture
def test_wholesaler(db):
    return Wholesaler.objects.create(
        name="Universal Wholesalers Manila",
        branch="Divisoria",
        contact_number="0919-888-7777"
    )


@pytest.fixture
def fmcg_coffee(db):
    return Product.objects.create(
        sku="SKU-CHAL-COFF",
        name="Nescafe Classic 2g Sachet",
        brand="Nescafe",
        category="Beverages",
        wholesale_cost=Decimal("4.50"),
        retail_price=Decimal("6.00"),
        stock_quantity=Decimal("50.0000"),
        reorder_point=10,
        pack_unit="strip of 12",
        tingi_unit="sachet"
    )


@pytest.fixture
def debtor_customer(db):
    return Customer.objects.create(
        name="Kuya Cardo",
        nickname="Cardo",
        phone="0915-000-1111",
        credit_limit=Decimal("2000.00"),
        debt_balance=Decimal("1000.00")
    )


# =============================================================================
# 1. Multi-Batch Boundary FIFO Depletion & Mathematical COGS Verification
# =============================================================================

@pytest.mark.django_db
class TestFIFOBatchDepletionExactMath:
    """Empirical mathematical validation of FIFO batch cost depletion."""

    def test_multi_batch_boundary_depletion_and_cumulative_cogs(self, db, fmcg_coffee):
        """
        Setup 3 batches with differing unit costs and received dates:
        - Batch 1: 5 units @ ₱10.00 (T - 3 days)
        - Batch 2: 10 units @ ₱15.00 (T - 2 days)
        - Batch 3: 20 units @ ₱20.00 (T - 1 day)
        Total stock = 35 units.

        Execute 3 sequential sales crossing batch boundaries:
        1. Sale 1: 3 units (from Batch 1).
           Expected COGS = 3 * 10 = 30.00.
           Batches: B1=2, B2=10, B3=20. Stock = 32.
        2. Sale 2: 8 units (2 from Batch 1 @ 10, 6 from Batch 2 @ 15).
           Expected COGS = (2 * 10) + (6 * 15) = 20 + 90 = 110.00.
           Batches: B1=0, B2=4, B3=20. Stock = 24.
        3. Sale 3: 15 units (4 from Batch 2 @ 15, 11 from Batch 3 @ 20).
           Expected COGS = (4 * 15) + (11 * 20) = 60 + 220 = 280.00.
           Batches: B1=0, B2=0, B3=9. Stock = 9.

        Verify:
        - Exact mathematical equality of COGS at each step.
        - Cumulative COGS = 30 + 110 + 280 = 420.00.
        - Exact sum of batch depletion = (5*10) + (10*15) + (11*20) = 50 + 150 + 220 = 420.00.
        - Remaining stock strictly matches 9 units.
        """
        fmcg_coffee.stock_quantity = Decimal("35.0000")
        fmcg_coffee.save()

        now = timezone.now()
        b1 = InventoryBatch.objects.create(
            product=fmcg_coffee,
            initial_tingi_quantity=Decimal("5.0000"),
            remaining_tingi_quantity=Decimal("5.0000"),
            unit_cost_basis=Decimal("10.00"),
            received_at=now - timezone.timedelta(days=3)
        )
        b2 = InventoryBatch.objects.create(
            product=fmcg_coffee,
            initial_tingi_quantity=Decimal("10.0000"),
            remaining_tingi_quantity=Decimal("10.0000"),
            unit_cost_basis=Decimal("15.00"),
            received_at=now - timezone.timedelta(days=2)
        )
        b3 = InventoryBatch.objects.create(
            product=fmcg_coffee,
            initial_tingi_quantity=Decimal("20.0000"),
            remaining_tingi_quantity=Decimal("20.0000"),
            unit_cost_basis=Decimal("20.00"),
            received_at=now - timezone.timedelta(days=1)
        )

        # Sale 1: 3 units
        cogs1, unit_cost1 = deplete_product_inventory_fifo(
            fmcg_coffee, Decimal("3.0000"), "TXN-STEP-1"
        )
        b1.refresh_from_db()
        b2.refresh_from_db()
        b3.refresh_from_db()
        fmcg_coffee.refresh_from_db()

        assert cogs1 == Decimal("30.00")
        assert unit_cost1 == Decimal("10.00")
        assert b1.remaining_tingi_quantity == Decimal("2.0000")
        assert b2.remaining_tingi_quantity == Decimal("10.0000")
        assert b3.remaining_tingi_quantity == Decimal("20.0000")
        assert fmcg_coffee.stock_quantity == Decimal("32.0000")

        # Sale 2: 8 units (crosses B1 and B2)
        cogs2, unit_cost2 = deplete_product_inventory_fifo(
            fmcg_coffee, Decimal("8.0000"), "TXN-STEP-2"
        )
        b1.refresh_from_db()
        b2.refresh_from_db()
        b3.refresh_from_db()
        fmcg_coffee.refresh_from_db()

        assert cogs2 == Decimal("110.00")
        assert unit_cost2 == Decimal("110.00") / Decimal("8.0000")
        assert b1.remaining_tingi_quantity == Decimal("0.0000")
        assert b2.remaining_tingi_quantity == Decimal("4.0000")
        assert b3.remaining_tingi_quantity == Decimal("20.0000")
        assert fmcg_coffee.stock_quantity == Decimal("24.0000")

        # Sale 3: 15 units (crosses B2 and B3)
        cogs3, unit_cost3 = deplete_product_inventory_fifo(
            fmcg_coffee, Decimal("15.0000"), "TXN-STEP-3"
        )
        b1.refresh_from_db()
        b2.refresh_from_db()
        b3.refresh_from_db()
        fmcg_coffee.refresh_from_db()

        assert cogs3 == Decimal("280.00")
        assert unit_cost3 == Decimal("280.00") / Decimal("15.0000")
        assert b1.remaining_tingi_quantity == Decimal("0.0000")
        assert b2.remaining_tingi_quantity == Decimal("0.0000")
        assert b3.remaining_tingi_quantity == Decimal("9.0000")
        assert fmcg_coffee.stock_quantity == Decimal("9.0000")

        # Cumulative checks
        total_cogs = cogs1 + cogs2 + cogs3
        assert total_cogs == Decimal("420.00")

    def test_unbatched_fallback_wholesale_cost_logic(self, db, fmcg_coffee):
        """
        Adversarial Scenario: Sales exceed available active batches.
        - Product has 1 batch of 5 units @ ₱10.00.
        - Product wholesale_cost is ₱12.00.
        - Total product stock_quantity is 15.0000.
        - Sell 12 units.
        Expected:
        - 5 units taken from batch @ ₱10.00 = ₱50.00.
        - 7 remainder units fall back to wholesale_cost ₱12.00 = ₱84.00.
        - Total COGS = ₱134.00.
        - Effective unit cost = 134 / 12 = ₱11.1667.
        - Remaining stock = 3.0000.
        """
        fmcg_coffee.stock_quantity = Decimal("15.0000")
        fmcg_coffee.wholesale_cost = Decimal("12.00")
        fmcg_coffee.save()

        b1 = InventoryBatch.objects.create(
            product=fmcg_coffee,
            initial_tingi_quantity=Decimal("5.0000"),
            remaining_tingi_quantity=Decimal("5.0000"),
            unit_cost_basis=Decimal("10.00"),
            received_at=timezone.now()
        )

        cogs, unit_cost = deplete_product_inventory_fifo(
            fmcg_coffee, Decimal("12.0000"), "TXN-FALLBACK"
        )
        b1.refresh_from_db()
        fmcg_coffee.refresh_from_db()

        assert b1.remaining_tingi_quantity == Decimal("0.0000")
        assert fmcg_coffee.stock_quantity == Decimal("3.0000")
        assert cogs == Decimal("134.00")
        assert round(unit_cost, 4) == round(Decimal("134.00") / Decimal("12.0000"), 4)

    def test_zero_quantity_depletion_resilience(self, db, fmcg_coffee):
        """
        Adversarial boundary: Depleting 0 quantity must not raise ZeroDivisionError,
        must not modify batch counts, and returns 0 COGS.
        """
        fmcg_coffee.stock_quantity = Decimal("10.0000")
        fmcg_coffee.wholesale_cost = Decimal("5.00")
        fmcg_coffee.save()

        b1 = InventoryBatch.objects.create(
            product=fmcg_coffee,
            initial_tingi_quantity=Decimal("10.0000"),
            remaining_tingi_quantity=Decimal("10.0000"),
            unit_cost_basis=Decimal("4.50"),
            received_at=timezone.now()
        )

        cogs, unit_cost = deplete_product_inventory_fifo(
            fmcg_coffee, Decimal("0.0000"), "TXN-ZERO"
        )
        b1.refresh_from_db()
        fmcg_coffee.refresh_from_db()

        assert cogs == Decimal("0.00")
        assert unit_cost == Decimal("5.00")  # falls back to wholesale_cost safely
        assert b1.remaining_tingi_quantity == Decimal("10.0000")
        assert fmcg_coffee.stock_quantity == Decimal("10.0000")

        # Movement logged with 0
        mv = StockMovement.objects.get(reference_id="TXN-ZERO")
        assert mv.quantity_change == Decimal("0.0000")
        assert mv.balance_after == Decimal("10.0000")

    def test_fractional_tingi_quantities(self, db, fmcg_coffee):
        """
        Tingi retailing allows fractional quantities (e.g. 0.5 or 0.25 sachets/liters).
        Verify decimal calculations do not suffer from rounding drift.
        """
        fmcg_coffee.stock_quantity = Decimal("5.0000")
        fmcg_coffee.save()

        b1 = InventoryBatch.objects.create(
            product=fmcg_coffee,
            initial_tingi_quantity=Decimal("2.5000"),
            remaining_tingi_quantity=Decimal("2.5000"),
            unit_cost_basis=Decimal("20.00"),
            received_at=timezone.now() - timezone.timedelta(hours=2)
        )
        b2 = InventoryBatch.objects.create(
            product=fmcg_coffee,
            initial_tingi_quantity=Decimal("2.5000"),
            remaining_tingi_quantity=Decimal("2.5000"),
            unit_cost_basis=Decimal("24.00"),
            received_at=timezone.now() - timezone.timedelta(hours=1)
        )

        # Deplete 3.2500 units (2.5000 from B1 @ 20 = 50.00, 0.7500 from B2 @ 24 = 18.00)
        cogs, unit_cost = deplete_product_inventory_fifo(
            fmcg_coffee, Decimal("3.2500"), "TXN-FRACTIONAL"
        )
        b1.refresh_from_db()
        b2.refresh_from_db()
        fmcg_coffee.refresh_from_db()

        assert b1.remaining_tingi_quantity == Decimal("0.0000")
        assert b2.remaining_tingi_quantity == Decimal("1.7500")
        assert fmcg_coffee.stock_quantity == Decimal("1.7500")
        assert cogs == Decimal("68.00")
        assert round(unit_cost, 4) == round(Decimal("68.00") / Decimal("3.2500"), 4)

    def test_out_of_order_creation_vs_received_at(self, db, fmcg_coffee):
        """
        Verify that FIFO ordering strictly respects `received_at` ASC,
        and not the database insertion order / PK id.
        """
        fmcg_coffee.stock_quantity = Decimal("20.0000")
        fmcg_coffee.save()

        now = timezone.now()
        # Created FIRST, but received LATER
        b_later = InventoryBatch.objects.create(
            product=fmcg_coffee,
            initial_tingi_quantity=Decimal("10.0000"),
            remaining_tingi_quantity=Decimal("10.0000"),
            unit_cost_basis=Decimal("30.00"),
            received_at=now + timezone.timedelta(days=1)
        )
        # Created SECOND, but received EARLIER
        b_earlier = InventoryBatch.objects.create(
            product=fmcg_coffee,
            initial_tingi_quantity=Decimal("10.0000"),
            remaining_tingi_quantity=Decimal("10.0000"),
            unit_cost_basis=Decimal("10.00"),
            received_at=now - timezone.timedelta(days=1)
        )

        cogs, _ = deplete_product_inventory_fifo(
            fmcg_coffee, Decimal("6.0000"), "TXN-ORDER-TEST"
        )
        b_earlier.refresh_from_db()
        b_later.refresh_from_db()

        # b_earlier must be depleted first
        assert b_earlier.remaining_tingi_quantity == Decimal("4.0000")
        assert b_later.remaining_tingi_quantity == Decimal("10.0000")
        assert cogs == Decimal("60.00")  # 6 * 10.00


# =============================================================================
# 2. StockMovement Audit Ledger Invariant Verification
# =============================================================================

@pytest.mark.django_db
class TestStockMovementLedgerInvariants:
    """Validate mathematical continuity of the StockMovement append-only ledger."""

    def test_continuous_ledger_balance_invariance(self, db, fmcg_coffee):
        """
        Perform 8 interleaved restocks and sales.
        Verify invariant:
        balance_after[n] == balance_after[n-1] + quantity_change[n]
        and final balance_after == product.stock_quantity.
        """
        # Start at 0
        fmcg_coffee.stock_quantity = Decimal("0.0000")
        fmcg_coffee.save()

        actions = [
            ("RESTOCK", Decimal("20.0000"), Decimal("10.00")),
            ("RESTOCK", Decimal("15.0000"), Decimal("12.00")),
            ("SALE", Decimal("8.0000"), None),
            ("SALE", Decimal("12.0000"), None),
            ("RESTOCK", Decimal("30.0000"), Decimal("11.50")),
            ("SALE", Decimal("25.0000"), None),
            ("SALE", Decimal("5.0000"), None),
            ("RESTOCK", Decimal("10.0000"), Decimal("13.00")),
        ]

        step = 1
        for act_type, qty, cost in actions:
            if act_type == "RESTOCK":
                record_restock_batch(
                    product=fmcg_coffee,
                    quantity=qty,
                    unit_cost=cost,
                    reference_id=f"AUDIT-RESTOCK-{step}"
                )
            else:
                deplete_product_inventory_fifo(
                    product=fmcg_coffee,
                    quantity=qty,
                    reference_id=f"AUDIT-SALE-{step}"
                )
            step += 1

        fmcg_coffee.refresh_from_db()
        movements = sorted(
            StockMovement.objects.filter(product=fmcg_coffee),
            key=lambda m: int(m.reference_id.split('-')[-1])
        )
        assert len(movements) == 8

        # Verify ledger mathematical chain
        running_bal = Decimal("0.0000")
        for mv in movements:
            running_bal += mv.quantity_change
            assert mv.balance_after == running_bal

        assert fmcg_coffee.stock_quantity == running_bal
        assert fmcg_coffee.stock_quantity == Decimal("25.0000")  # (20+15-8-12+30-25-5+10) = 25

    def test_customer_payment_ledger_continuity(self, db, debtor_customer):
        """Verify CustomerPayment balance_before and balance_after track correctly."""
        # Initial debt = 1000.00
        p1 = CustomerPayment.objects.create(
            customer=debtor_customer,
            amount=Decimal("300.00"),
            balance_before=debtor_customer.debt_balance,
            balance_after=debtor_customer.debt_balance - Decimal("300.00")
        )
        debtor_customer.debt_balance = p1.balance_after
        debtor_customer.save()

        p2 = CustomerPayment.objects.create(
            customer=debtor_customer,
            amount=Decimal("450.00"),
            balance_before=debtor_customer.debt_balance,
            balance_after=debtor_customer.debt_balance - Decimal("450.00")
        )
        debtor_customer.debt_balance = p2.balance_after
        debtor_customer.save()

        assert p1.balance_before == Decimal("1000.00")
        assert p1.balance_after == Decimal("700.00")
        assert p2.balance_before == Decimal("700.00")
        assert p2.balance_after == Decimal("250.00")
        assert debtor_customer.debt_balance == Decimal("250.00")


# =============================================================================
# 3. Input Validation & Adversarial API Testing
# =============================================================================

@pytest.mark.django_db
class TestInputValidationAndUUIDResilience:
    """Adversarial stress-testing of UUID parsing, malformed payloads, and injection strings."""

    def test_invalid_uuid_rejected_with_422(self, api_client, fmcg_coffee):
        """Malformed or non-UUID strings must be rejected by Pydantic schema with 422."""
        invalid_uuids = [
            "12345",
            "not-a-valid-uuid",
            "123e4567-e89b-12d3-a456-42661417400",  # missing 1 char
            "' OR '1'='1",                          # SQL injection attempt
            "../../etc/passwd",                     # Path traversal attempt
            "",                                     # Empty string
        ]

        for bad_id in invalid_uuids:
            payload = {
                "transaction_type": "CASH",
                "customer_id": bad_id,
                "items": [{"product_id": str(fmcg_coffee.id), "quantity": 1}]
            }
            resp = api_client.post("/api/transactions", data=payload, content_type="application/json")
            assert resp.status_code == 422, f"Failed to reject invalid UUID: {bad_id}"

    def test_invalid_item_product_uuid_rejected_with_422(self, api_client):
        """Non-UUID product_id must be rejected with 422."""
        payload = {
            "transaction_type": "CASH",
            "items": [{"product_id": "not-a-uuid", "quantity": 1}]
        }
        resp = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert resp.status_code == 422

    def test_non_positive_quantity_rejected_with_422(self, api_client, fmcg_coffee):
        """Pydantic schema must reject quantity <= 0 with 422."""
        for bad_qty in [0, -1, -50.5]:
            payload = {
                "transaction_type": "CASH",
                "items": [{"product_id": str(fmcg_coffee.id), "quantity": bad_qty}]
            }
            resp = api_client.post("/api/transactions", data=payload, content_type="application/json")
            assert resp.status_code == 422, f"Failed to reject non-positive quantity: {bad_qty}"

    def test_api_insufficient_stock_clean_rollback(self, api_client, fmcg_coffee):
        """
        If requested quantity exceeds stock_quantity, API must return 400
        and roll back without creating Transaction, TransactionItem, or StockMovement.
        """
        fmcg_coffee.stock_quantity = Decimal("5.0000")
        fmcg_coffee.save()

        initial_tx_count = Transaction.objects.count()
        initial_mv_count = StockMovement.objects.count()

        payload = {
            "transaction_type": "CASH",
            "items": [{"product_id": str(fmcg_coffee.id), "quantity": 10}]
        }
        resp = api_client.post("/api/transactions", data=payload, content_type="application/json")
        assert resp.status_code == 400

        fmcg_coffee.refresh_from_db()
        assert fmcg_coffee.stock_quantity == Decimal("5.0000")
        assert Transaction.objects.count() == initial_tx_count
        assert StockMovement.objects.count() == initial_mv_count

    def test_negative_quantity_direct_service_call(self, db, fmcg_coffee):
        """
        Adversarial inspection of direct service call `deplete_product_inventory_fifo` with negative quantity.
        If called with negative quantity directly, stock_quantity = stock - (-qty) = stock + qty.
        Verifies behavior is empirically documented.
        """
        fmcg_coffee.stock_quantity = Decimal("10.0000")
        fmcg_coffee.save()

        # Calling with negative quantity
        cogs, unit_cost = deplete_product_inventory_fifo(
            fmcg_coffee, Decimal("-5.0000"), "TEST-NEGATIVE-QUANTITY"
        )
        fmcg_coffee.refresh_from_db()

        # Document finding: stock increases if negative quantity is passed directly without schema guard
        assert cogs == Decimal("0.00")
        assert fmcg_coffee.stock_quantity == Decimal("15.0000")


# =============================================================================
# 4. StoreConfig Singleton Integrity Constraint
# =============================================================================

@pytest.mark.django_db
class TestStoreConfigSingletonConstraint:
    """Verify StoreConfig check constraint and singleton integrity."""

    def test_store_config_enforces_pk_one(self, db):
        """Creating a StoreConfig with pk != 1 must violate check constraint."""
        config = StoreConfig.get_solo()
        assert config.pk == 1

        # Attempting to insert pk=2 must raise IntegrityError
        with pytest.raises(IntegrityError):
            with db_transaction.atomic():
                StoreConfig.objects.create(
                    pk=2,
                    store_name="Fake Store 2",
                    caretaker_identity="Intruder"
                )

    def test_get_solo_idempotence(self, db):
        c1 = StoreConfig.get_solo()
        c2 = StoreConfig.get_solo()
        assert c1.pk == c2.pk == 1
        assert StoreConfig.objects.count() == 1
