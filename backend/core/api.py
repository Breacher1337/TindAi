import json
import random
import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from django.db import transaction as db_transaction, IntegrityError, OperationalError
from django.shortcuts import get_object_or_404
from ninja import NinjaAPI
from ninja.errors import HttpError

from .models import (
    Product, Customer, CustomerPayment, Transaction, TransactionItem,
    RestockRun, RestockInvoice, RestockInvoiceItem, Wholesaler,
    InventoryBatch, StockMovement
)
from .schemas import (
    ProductIn, ProductOut,
    CustomerIn, CustomerOut,
    CustomerPaymentIn, CustomerPaymentOut,
    TransactionCheckoutIn, TransactionOut, TransactionItemOut,
    RestockOptimizeIn, RestockOptimizeOut, RestockItemResult,
    CounterDetectIn, CounterDetectOut, DetectedProductItem,
    ReceiptOcrIn, ReceiptOcrOut, ParsedReceiptItem,
    AnalyticsOut, InventoryTurnoverOut, ProductTurnoverItem
)
from .services.knapsack import solve_restock_knapsack
from .services.analytics import get_financial_analytics, get_inventory_turnover_analytics
from .services.inventory import deplete_product_inventory_fifo, record_restock_batch
from .services import gemini

api = NinjaAPI(
    title="TindAI API",
    version="1.0.0",
    description="Intelligent Sari-Sari Store Inventory, POS & Restocking Gateway"
)


# -----------------------------------------------------------------------------
# Products Endpoints
# -----------------------------------------------------------------------------

@api.get("/products", response=List[ProductOut], tags=["Products"])
def list_products(request, q: Optional[str] = None, category: Optional[str] = None):
    """Retrieve all store catalog items with optional search and category filters."""
    qs = Product.objects.filter(is_active=True)
    if category:
        qs = qs.filter(category__iexact=category)
    if q:
        qs = qs.filter(name__icontains=q) | qs.filter(sku__icontains=q) | qs.filter(barcode__icontains=q)
    return list(qs)


@api.post("/products", response=ProductOut, tags=["Products"])
def create_product(request, payload: ProductIn):
    """Create a new product in the store catalog."""
    if Product.objects.filter(sku=payload.sku).exists():
        raise HttpError(400, f"Product with SKU '{payload.sku}' already exists.")
    product = Product.objects.create(**payload.dict())
    return product


# -----------------------------------------------------------------------------
# Customers & Utang Endpoints
# -----------------------------------------------------------------------------

@api.get("/customers", response=List[CustomerOut], tags=["Customers"])
def list_customers(request, q: Optional[str] = None):
    """List customer profiles and their current debt (utang) balances."""
    qs = Customer.objects.filter(is_active=True)
    if q:
        qs = qs.filter(name__icontains=q) | qs.filter(nickname__icontains=q) | qs.filter(phone__icontains=q)
    return list(qs)


@api.post("/customers", response=CustomerOut, tags=["Customers"])
def create_customer(request, payload: CustomerIn):
    """Register a new customer profile."""
    customer = Customer.objects.create(**payload.dict())
    return customer


@api.get("/customers/{customer_id}/payments", response=List[CustomerPaymentOut], tags=["Customers"])
def list_customer_payments(request, customer_id: uuid.UUID):
    """View payment history for a customer."""
    customer = get_object_or_404(Customer, id=customer_id)
    payments = customer.payments.all()
    return [
        CustomerPaymentOut(
            id=p.id,
            customer_id=customer.id,
            amount=p.amount,
            balance_before=p.balance_before,
            balance_after=p.balance_after,
            notes=p.notes,
            created_at=p.created_at,
            new_debt_balance=customer.debt_balance
        )
        for p in payments
    ]


@api.post("/customers/{customer_id}/payments", response=CustomerPaymentOut, tags=["Customers"])
def record_customer_payment(request, customer_id: uuid.UUID, payload: CustomerPaymentIn):
    """Record debt repayment (partial or full) and update ledger balance."""
    if payload.amount <= Decimal("0.00"):
        raise HttpError(400, "Payment amount must be greater than zero.")
    with db_transaction.atomic():
        customer = get_object_or_404(Customer.objects.select_for_update(), id=customer_id)
        balance_before = customer.debt_balance
        balance_after = max(Decimal("0.00"), customer.debt_balance - payload.amount)
        customer.debt_balance = balance_after
        customer.save(update_fields=['debt_balance', 'updated_at'])

        payment = CustomerPayment.objects.create(
            customer=customer,
            amount=payload.amount,
            balance_before=balance_before,
            balance_after=balance_after,
            notes=payload.notes or "Bayad utang"
        )

    return CustomerPaymentOut(
        id=payment.id,
        customer_id=customer.id,
        amount=payment.amount,
        balance_before=payment.balance_before,
        balance_after=payment.balance_after,
        notes=payment.notes,
        created_at=payment.created_at,
        new_debt_balance=customer.debt_balance
    )


# -----------------------------------------------------------------------------
# Transactions (POS Checkout) Endpoints
# -----------------------------------------------------------------------------

def _execute_transaction(payload: TransactionCheckoutIn) -> TransactionOut:
    """Core transaction execution logic with FIFO depletion and Utang debt tracking."""
    # Idempotent absorption: if transaction with this client UUID was already persisted, return it
    if payload.id:
        existing_tx = Transaction.objects.filter(id=payload.id).first()
        if existing_tx:
            if existing_tx.sync_status != Transaction.SYNC_STATUS_SYNCED:
                existing_tx.sync_status = Transaction.SYNC_STATUS_SYNCED
                existing_tx.save(update_fields=['sync_status'])

            items_out = [
                TransactionItemOut(
                    id=item.id,
                    product_id=item.product.id,
                    product_name=item.product.name,
                    product_sku=item.product.sku,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    cost_price=item.cost_price,
                    subtotal=item.subtotal
                )
                for item in existing_tx.items.select_related('product').all()
            ]
            return TransactionOut(
                id=existing_tx.id,
                transaction_number=existing_tx.transaction_number,
                transaction_type=existing_tx.transaction_type,
                total_amount=existing_tx.total_amount,
                total_cogs=existing_tx.total_cogs,
                gross_profit=existing_tx.gross_profit,
                payment_status=existing_tx.payment_status,
                sync_status=Transaction.SYNC_STATUS_SYNCED,
                customer_id=existing_tx.customer.id if existing_tx.customer else None,
                customer_name=existing_tx.customer.name if existing_tx.customer else None,
                notes=existing_tx.notes,
                items=items_out,
                created_at=existing_tx.created_at
            )

    tx_type = payload.transaction_type.upper()
    if tx_type not in (Transaction.TYPE_CASH, Transaction.TYPE_UTANG):
        raise HttpError(400, f"Invalid transaction type: {payload.transaction_type}. Must be CASH or UTANG.")

    customer = None
    if tx_type == Transaction.TYPE_UTANG:
        if not payload.customer_id:
            raise HttpError(400, "Customer is required for Utang transactions.")
        try:
            customer = Customer.objects.get(id=payload.customer_id)
        except Customer.DoesNotExist:
            raise HttpError(400, "Customer is required for Utang transactions.")
    elif payload.customer_id:
        customer = Customer.objects.filter(id=payload.customer_id).first()

    with db_transaction.atomic():
        if tx_type == Transaction.TYPE_UTANG:
            customer = Customer.objects.select_for_update().get(id=customer.id)
            if not customer:
                raise HttpError(400, "Customer is required for Utang transactions.")

        # Lock products and validate quantities
        total_amount = Decimal("0.00")
        items_to_process = []

        for item_in in payload.items:
            product = get_object_or_404(Product.objects.select_for_update(), id=item_in.product_id)
            if product.stock_quantity < item_in.quantity:
                raise HttpError(400, "Insufficient stock")
            subtotal = product.retail_price * item_in.quantity
            total_amount += subtotal
            items_to_process.append((product, item_in.quantity, product.retail_price, subtotal))

        # If Utang, check credit limit ceiling
        payment_status = Transaction.STATUS_PAID
        if tx_type == Transaction.TYPE_UTANG:
            if not customer:
                raise HttpError(400, "Customer is required for Utang transactions.")
            if customer.debt_balance + total_amount > customer.credit_limit:
                raise HttpError(400, f"Lagpas sa Credit Limit! Current debt: {customer.debt_balance}, Limit: {customer.credit_limit}")
            payment_status = Transaction.STATUS_UNPAID

        # Create Transaction
        tx_kwargs = {
            'transaction_type': tx_type,
            'total_amount': total_amount,
            'payment_status': payment_status,
            'sync_status': payload.sync_status or Transaction.SYNC_STATUS_SYNCED,
            'customer': customer,
            'notes': payload.notes or ''
        }
        if payload.id:
            tx_kwargs['id'] = payload.id

        if payload.id:
            try:
                with db_transaction.atomic():
                    tx = Transaction.objects.create(**tx_kwargs)
            except IntegrityError:
                existing_tx = Transaction.objects.filter(id=payload.id).first()
                if existing_tx:
                    if existing_tx.sync_status != Transaction.SYNC_STATUS_SYNCED:
                        existing_tx.sync_status = Transaction.SYNC_STATUS_SYNCED
                        existing_tx.save(update_fields=['sync_status'])
                    items_out = [
                        TransactionItemOut(
                            id=item.id,
                            product_id=item.product.id,
                            product_name=item.product.name,
                            product_sku=item.product.sku,
                            quantity=item.quantity,
                            unit_price=item.unit_price,
                            cost_price=item.cost_price,
                            subtotal=item.subtotal
                        )
                        for item in existing_tx.items.select_related('product').all()
                    ]
                    return TransactionOut(
                        id=existing_tx.id,
                        transaction_number=existing_tx.transaction_number,
                        transaction_type=existing_tx.transaction_type,
                        total_amount=existing_tx.total_amount,
                        total_cogs=existing_tx.total_cogs,
                        gross_profit=existing_tx.gross_profit,
                        payment_status=existing_tx.payment_status,
                        sync_status=Transaction.SYNC_STATUS_SYNCED,
                        customer_id=existing_tx.customer.id if existing_tx.customer else None,
                        customer_name=existing_tx.customer.name if existing_tx.customer else None,
                        notes=existing_tx.notes,
                        items=items_out,
                        created_at=existing_tx.created_at
                    )
                raise
        else:
            tx = Transaction.objects.create(**tx_kwargs)

        if tx_type == Transaction.TYPE_UTANG and customer:
            customer.debt_balance += total_amount
            customer.save(update_fields=['debt_balance', 'updated_at'])

        total_cogs = Decimal("0.00")
        created_item_outs = []
        for prod, qty, price, sub in items_to_process:
            item_cogs, effective_cost = deplete_product_inventory_fifo(prod, qty, reference_id=str(tx.id))
            total_cogs += item_cogs

            item_obj = TransactionItem.objects.create(
                transaction=tx,
                product=prod,
                quantity=qty,
                unit_price=price,
                cost_price=effective_cost,
                subtotal=sub
            )
            created_item_outs.append(TransactionItemOut(
                id=item_obj.id,
                product_id=prod.id,
                product_name=prod.name,
                product_sku=prod.sku,
                quantity=item_obj.quantity,
                unit_price=item_obj.unit_price,
                cost_price=item_obj.cost_price,
                subtotal=item_obj.subtotal
            ))

        tx.total_cogs = total_cogs
        tx.gross_profit = tx.total_amount - total_cogs
        tx.save(update_fields=['total_cogs', 'gross_profit'])

    return TransactionOut(
        id=tx.id,
        transaction_number=tx.transaction_number,
        transaction_type=tx.transaction_type,
        total_amount=tx.total_amount,
        total_cogs=tx.total_cogs,
        gross_profit=tx.gross_profit,
        payment_status=tx.payment_status,
        sync_status=tx.sync_status,
        customer_id=customer.id if customer else None,
        customer_name=customer.name if customer else None,
        notes=tx.notes,
        items=created_item_outs,
        created_at=tx.created_at
    )


@api.post("/transactions", response=TransactionOut, tags=["Transactions"])
def create_transaction(request, payload: TransactionCheckoutIn):
    """Execute a POS checkout transaction (Cash or Utang), decrementing inventory via FIFO with lock retry."""
    if not payload.items:
        raise HttpError(400, "Transaction must contain at least one item.")

    max_retries = 10
    for attempt in range(max_retries):
        try:
            return _execute_transaction(payload)
        except OperationalError as exc:
            if "locked" in str(exc).lower() and attempt < max_retries - 1:
                time.sleep(0.05 * (attempt + 1))
                continue
            raise


# -----------------------------------------------------------------------------
# PuLP Restocking Optimizer
# -----------------------------------------------------------------------------

@api.post("/restock/optimize", response=RestockOptimizeOut, tags=["Restocking"])
def optimize_restock(request, payload: RestockOptimizeIn):
    """
    Capital-constrained bounded knapsack restocking optimization using PuLP.
    Selects optimal replenishment wholesale packs within available cash budget.
    """
    budget = payload.budget
    products_qs = Product.objects.filter(is_active=True)
    if payload.sku_filter:
        products_qs = products_qs.filter(sku__in=payload.sku_filter)

    # Candidate products: active items where stock <= reorder_point * 2; fallback to all active
    candidates = [p for p in products_qs if p.stock_quantity <= p.reorder_point * 2]
    if not candidates:
        candidates = list(products_qs)

    knapsack_res = solve_restock_knapsack(candidates, budget)

    recommended_items: List[RestockItemResult] = []
    total_packs = 0
    prod_map = {p.sku: p for p in candidates}

    for it in knapsack_res["items"]:
        prod = prod_map.get(it["sku"])
        retail_p = prod.retail_price if prod else it["unit_cost"]
        recommended_items.append(RestockItemResult(
            sku=it["sku"],
            name=it["name"],
            category=it["category"],
            wholesale_cost=it["unit_cost"],
            retail_price=retail_p,
            recommended_packs=it["packs_to_buy"],
            line_cost=it["subtotal"],
            expected_profit=it["expected_profit"],
        ))
        total_packs += it["packs_to_buy"]

    # Record historical RestockRun
    RestockRun.objects.create(
        budget=budget,
        total_spent=knapsack_res["total_spent"],
        items_json=[item.model_dump(mode="json") for item in recommended_items]
    )

    return RestockOptimizeOut(
        budget=budget,
        total_spent=knapsack_res["total_spent"],
        remaining_budget=knapsack_res["remaining_budget"],
        total_packs=total_packs,
        expected_gross_profit=knapsack_res["expected_profit"],
        status=f"Optimal bounded knapsack solution ({knapsack_res['solver_status']})",
        items=recommended_items
    )


# -----------------------------------------------------------------------------
# Multimodal VLM Counter Detection
# -----------------------------------------------------------------------------

@api.post("/vision/counter-detect", response=CounterDetectOut, tags=["AI Perception"])
def counter_detect(request, payload: CounterDetectIn):
    """
    Multimodal Counter Snapshot Detection using Google Gemini Flash.
    Returns detected sari-sari store items with catalog SKU matching and estimated count.
    """
    return gemini.detect_counter_items(
        image_base64=payload.image_base64,
        prompt_hint=payload.prompt_hint
    )


# -----------------------------------------------------------------------------
# Wholesaler Receipt OCR
# -----------------------------------------------------------------------------

@api.post("/ocr/receipt", response=ReceiptOcrOut, tags=["AI Perception"])
def parse_receipt(request, payload: ReceiptOcrIn):
    """
    Wholesale receipt OCR using Google Gemini Flash OCR with Local Fuzzy SKU Matching.
    Extracts cryptic supermarket line-items, wholesale costs, and computes suggested retail markup.
    High-confidence matches (>=80%) resolve locally before LLM fallback.
    """
    return gemini.ocr_receipt(
        image_base64=payload.image_base64,
        wholesaler_hint=payload.wholesaler_hint,
        raw_lines=payload.raw_lines,
        raw_text=payload.raw_text,
    )


# -----------------------------------------------------------------------------
# Financial Analytics Endpoint
# -----------------------------------------------------------------------------

@api.get("/analytics", response=AnalyticsOut, tags=["Analytics"])
def get_analytics(request, period: str = "all"):
    """Retrieve real-time store financial metrics with strict liquidity isolation."""
    return get_financial_analytics(period=period)


@api.get("/analytics/turnover", response=InventoryTurnoverOut, tags=["Analytics"])
def get_inventory_turnover(request, as_of: Optional[str] = None):
    """
    Calculate inventory velocity over 7d and 30d windows, classifying items
    into FAST_MOVING, MODERATE, or DEAD_STOCK with tied-up capital calculation.
    """
    return get_inventory_turnover_analytics(as_of=as_of)



@api.post("/ocr/receipt/apply", tags=["AI Perception"])
def apply_receipt(request, payload: ReceiptOcrOut):
    """
    Applies a parsed receipt to the database:
    1. Saves the receipt history linked to Wholesaler.
    2. Increments stock quantity for items and creates InventoryBatch / StockMovement.
    3. Auto-creates inactive draft products for unknown items.
    4. Updates wholesale costs to match the new receipt.
    """
    from datetime import datetime

    invoice_date = None
    if payload.date:
        try:
            invoice_date = datetime.strptime(payload.date, "%Y-%m-%d").date()
        except ValueError:
            pass

    with db_transaction.atomic():
        wholesaler = None
        if payload.wholesaler_name:
            wholesaler, _ = Wholesaler.objects.get_or_create(
                name=payload.wholesaler_name.strip()
            )

        invoice = RestockInvoice.objects.create(
            wholesaler=wholesaler,
            wholesaler_name=payload.wholesaler_name,
            invoice_no=payload.invoice_no,
            date=invoice_date,
            total_amount=payload.total_amount,
            parse_status=RestockInvoice.PARSE_CONFIRMED,
        )
        
        for item in payload.items:
            product = None
            if item.matched_sku:
                product = Product.objects.filter(sku=item.matched_sku).first()
            
            if not product and item.raw_line_text:
                from core.services.fuzzy_matcher import fuzzy_match_sku
                fuzzy = fuzzy_match_sku(item.raw_line_text)
                if fuzzy and fuzzy["product"]:
                    product = fuzzy["product"]
                    item.matched_sku = fuzzy["matched_sku"]
                    item.matched_name = fuzzy["matched_name"]

            if not product:
                temp_sku = item.matched_sku if item.matched_sku else f"DRAFT-{invoice.id}-{item.matched_name[:5].upper()}"
                if Product.objects.filter(sku=temp_sku).exists():
                    temp_sku = f"{temp_sku}-{random.randint(1000,9999)}"

                product = Product.objects.create(
                    sku=temp_sku,
                    name=item.matched_name,
                    category="Uncategorized",
                    wholesale_cost=item.pack_wholesale_cost,
                    retail_price=item.suggested_retail_price,
                    stock_quantity=Decimal("0.0000"),
                    is_active=False
                )

            invoice_item = RestockInvoiceItem.objects.create(
                invoice=invoice,
                product=product,
                raw_line_text=item.raw_line_text,
                qty_packs=item.qty_packs,
                pack_wholesale_cost=item.pack_wholesale_cost,
                line_total=item.line_total
            )

            record_restock_batch(
                product=product,
                quantity=Decimal(str(item.qty_packs)),
                unit_cost=item.pack_wholesale_cost,
                invoice_item=invoice_item,
                reference_id=str(invoice.id)
            )

    return {"success": True, "message": f"Successfully applied receipt. {len(payload.items)} items processed.", "invoice_id": invoice.id}

