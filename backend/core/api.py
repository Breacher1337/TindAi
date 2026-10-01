import json
from decimal import Decimal
from typing import List, Optional
from django.db import transaction as db_transaction
from django.shortcuts import get_object_or_404
from ninja import NinjaAPI
from ninja.errors import HttpError

from .models import Product, Customer, CustomerPayment, Transaction, TransactionItem, RestockRun
from .schemas import (
    ProductIn, ProductOut,
    CustomerIn, CustomerOut,
    CustomerPaymentIn, CustomerPaymentOut,
    TransactionCheckoutIn, TransactionOut, TransactionItemOut,
    RestockOptimizeIn, RestockOptimizeOut, RestockItemResult,
    CounterDetectIn, CounterDetectOut, DetectedProductItem,
    ReceiptOcrIn, ReceiptOcrOut, ParsedReceiptItem,
    AnalyticsOut
)
from .services.knapsack import solve_restock_knapsack
from .services.analytics import get_financial_analytics
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
def list_customer_payments(request, customer_id: int):
    """View payment history for a customer."""
    customer = get_object_or_404(Customer, id=customer_id)
    payments = customer.payments.all()
    return [
        CustomerPaymentOut(
            id=p.id,
            customer_id=customer.id,
            amount=p.amount,
            notes=p.notes,
            created_at=p.created_at,
            new_debt_balance=customer.debt_balance
        )
        for p in payments
    ]


@api.post("/customers/{customer_id}/payments", response=CustomerPaymentOut, tags=["Customers"])
def record_customer_payment(request, customer_id: int, payload: CustomerPaymentIn):
    """Record debt repayment (partial or full) and update ledger balance."""
    if payload.amount <= Decimal("0.00"):
        raise HttpError(400, "Payment amount must be greater than zero.")
    with db_transaction.atomic():
        customer = get_object_or_404(Customer.objects.select_for_update(), id=customer_id)
        new_balance = max(Decimal("0.00"), customer.debt_balance - payload.amount)
        customer.debt_balance = new_balance
        customer.save(update_fields=['debt_balance', 'updated_at'])

        payment = CustomerPayment.objects.create(
            customer=customer,
            amount=payload.amount,
            notes=payload.notes or "Bayad utang"
        )

    return CustomerPaymentOut(
        id=payment.id,
        customer_id=customer.id,
        amount=payment.amount,
        notes=payment.notes,
        created_at=payment.created_at,
        new_debt_balance=customer.debt_balance
    )


# -----------------------------------------------------------------------------
# Transactions (POS Checkout) Endpoints
# -----------------------------------------------------------------------------

@api.post("/transactions", response=TransactionOut, tags=["Transactions"])
def create_transaction(request, payload: TransactionCheckoutIn):
    """Execute a POS checkout transaction (Cash or Utang), decrementing inventory."""
    if not payload.items:
        raise HttpError(400, "Transaction must contain at least one item.")

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
        items_to_create = []

        for item_in in payload.items:
            product = get_object_or_404(Product.objects.select_for_update(), id=item_in.product_id)
            if product.stock_quantity < item_in.quantity:
                raise HttpError(400, "Insufficient stock")
            subtotal = product.retail_price * item_in.quantity
            total_amount += subtotal

            # Decrement stock
            product.stock_quantity = product.stock_quantity - item_in.quantity
            product.save(update_fields=['stock_quantity', 'updated_at'])

            items_to_create.append({
                'product': product,
                'quantity': item_in.quantity,
                'unit_price': product.retail_price,
                'cost_price': product.wholesale_cost,
                'subtotal': subtotal
            })

        # If Utang, check credit limit ceiling and update customer balance
        payment_status = Transaction.STATUS_PAID
        if tx_type == Transaction.TYPE_UTANG:
            if not customer:
                raise HttpError(400, "Customer is required for Utang transactions.")
            if customer.debt_balance + total_amount > customer.credit_limit:
                raise HttpError(400, f"Lagpas sa Credit Limit! Current debt: {customer.debt_balance}, Limit: {customer.credit_limit}")
            payment_status = Transaction.STATUS_UNPAID
            customer.debt_balance += total_amount
            customer.save(update_fields=['debt_balance', 'updated_at'])

        # Create Transaction
        tx = Transaction.objects.create(
            transaction_type=tx_type,
            total_amount=total_amount,
            payment_status=payment_status,
            customer=customer,
            notes=payload.notes or ''
        )

        created_item_outs = []
        for it in items_to_create:
            item_obj = TransactionItem.objects.create(
                transaction=tx,
                product=it['product'],
                quantity=it['quantity'],
                unit_price=it['unit_price'],
                cost_price=it['cost_price'],
                subtotal=it['subtotal']
            )
            created_item_outs.append(TransactionItemOut(
                id=item_obj.id,
                product_id=it['product'].id,
                product_name=it['product'].name,
                product_sku=it['product'].sku,
                quantity=item_obj.quantity,
                unit_price=item_obj.unit_price,
                cost_price=item_obj.cost_price,
                subtotal=item_obj.subtotal
            ))

    return TransactionOut(
        id=tx.id,
        transaction_type=tx.transaction_type,
        total_amount=tx.total_amount,
        payment_status=tx.payment_status,
        customer_id=customer.id if customer else None,
        customer_name=customer.name if customer else None,
        notes=tx.notes,
        items=created_item_outs,
        created_at=tx.created_at
    )


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
    Wholesale receipt OCR using Google Gemini Flash OCR.
    Extracts cryptic supermarket line-items, wholesale costs, and computes suggested retail markup.
    """
    return gemini.ocr_receipt(
        image_base64=payload.image_base64,
        wholesaler_hint=payload.wholesaler_hint
    )


# -----------------------------------------------------------------------------
# Financial Analytics Endpoint
# -----------------------------------------------------------------------------

@api.get("/analytics", response=AnalyticsOut, tags=["Analytics"])
def get_analytics(request, period: str = "all"):
    """Retrieve real-time store financial metrics with strict liquidity isolation."""
    return get_financial_analytics(period=period)

