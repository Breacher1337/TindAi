import uuid
from datetime import datetime
from typing import List, Optional
from decimal import Decimal
from ninja import Schema
from pydantic import Field


# -------------------------------------------------------------
# Product Schemas
# -------------------------------------------------------------

class ProductIn(Schema):
    sku: str
    name: str
    brand: Optional[str] = ""
    category: str
    wholesale_cost: Decimal
    retail_price: Decimal
    stock_quantity: Decimal = Decimal("0.0000")
    reorder_point: int = 10
    pack_unit: str = "pack"
    tingi_unit: str = "piece"
    barcode: Optional[str] = None


class ProductOut(Schema):
    id: uuid.UUID
    sku: str
    name: str
    brand: str
    category: str
    wholesale_cost: Decimal
    retail_price: Decimal
    stock_quantity: Decimal
    reorder_point: int
    pack_unit: str
    tingi_unit: str
    barcode: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# -------------------------------------------------------------
# Customer Schemas & Payments
# -------------------------------------------------------------

class CustomerIn(Schema):
    name: str
    nickname: Optional[str] = ""
    phone: Optional[str] = ""
    address: Optional[str] = ""
    credit_limit: Decimal = Decimal("1000.00")


class CustomerOut(Schema):
    id: uuid.UUID
    name: str
    nickname: str
    phone: str
    address: str
    credit_limit: Decimal
    debt_balance: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerPaymentIn(Schema):
    amount: Decimal = Field(..., gt=0)
    notes: Optional[str] = "Bayad utang"


class CustomerPaymentOut(Schema):
    id: uuid.UUID
    customer_id: uuid.UUID
    amount: Decimal
    balance_before: Optional[Decimal] = Decimal("0.00")
    balance_after: Optional[Decimal] = Decimal("0.00")
    notes: str
    created_at: datetime
    new_debt_balance: Decimal


# -------------------------------------------------------------
# Transaction & Checkout Schemas
# -------------------------------------------------------------

class TransactionItemIn(Schema):
    product_id: uuid.UUID
    quantity: Decimal = Field(default=Decimal("1.0000"), gt=0)


class TransactionItemOut(Schema):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    quantity: Decimal
    unit_price: Decimal
    cost_price: Decimal = Decimal("0.00")
    subtotal: Decimal


class TransactionCheckoutIn(Schema):
    id: Optional[uuid.UUID] = None
    sync_status: Optional[str] = "SYNCED"
    transaction_type: str = "CASH"  # CASH or UTANG
    customer_id: Optional[uuid.UUID] = None
    items: List[TransactionItemIn]
    notes: Optional[str] = ""


class TransactionOut(Schema):
    id: uuid.UUID
    transaction_number: Optional[str] = None
    transaction_type: str
    total_amount: Decimal
    total_cogs: Decimal = Decimal("0.00")
    gross_profit: Decimal = Decimal("0.00")
    payment_status: str
    sync_status: str = "SYNCED"
    customer_id: Optional[uuid.UUID] = None
    customer_name: Optional[str] = None
    notes: str
    items: List[TransactionItemOut]
    created_at: datetime


# -------------------------------------------------------------
# PuLP Restocking Optimizer Schemas
# -------------------------------------------------------------

class RestockItemRequest(Schema):
    sku: str
    name: str
    category: str
    wholesale_cost: Decimal
    retail_price: Decimal
    current_stock: int
    reorder_point: int
    max_packs: Optional[int] = 10


class RestockOptimizeIn(Schema):
    budget: Decimal = Field(..., gt=0)
    sku_filter: Optional[List[str]] = None


class RestockItemResult(Schema):
    sku: str
    name: str
    category: str
    wholesale_cost: Decimal
    retail_price: Decimal
    recommended_packs: int
    line_cost: Decimal
    expected_profit: Decimal


class RestockOptimizeOut(Schema):
    budget: Decimal
    total_spent: Decimal
    remaining_budget: Decimal
    total_packs: int
    expected_gross_profit: Decimal
    status: str
    items: List[RestockItemResult]


# -------------------------------------------------------------
# Multimodal Vision (Gemini Counter Detect) Schemas
# -------------------------------------------------------------

class CounterDetectIn(Schema):
    image_base64: Optional[str] = None
    prompt_hint: Optional[str] = "Identify FMCG items on counter"


class DetectedProductItem(Schema):
    sku: str
    name: str
    category: str
    confidence: float
    detected_qty: int
    unit_price: Decimal


class CounterDetectOut(Schema):
    success: bool
    message: str
    detected_items: List[DetectedProductItem]
    estimated_total: Decimal


# -------------------------------------------------------------
# Wholesaler Receipt OCR Schemas
# -------------------------------------------------------------

class ReceiptOcrIn(Schema):
    image_base64: Optional[str] = None
    wholesaler_hint: Optional[str] = "Puregold / Super8 / SM Supermarket"
    raw_lines: Optional[List[str]] = None
    raw_text: Optional[str] = None


class ParsedReceiptItem(Schema):
    raw_line_text: str
    matched_sku: Optional[str] = None
    matched_name: str
    qty_packs: int
    pack_wholesale_cost: Decimal
    line_total: Decimal
    confidence: float
    suggested_retail_price: Decimal


class ReceiptOcrOut(Schema):
    wholesaler_name: str
    invoice_no: str
    date: str
    total_amount: Decimal
    items: List[ParsedReceiptItem]


# -------------------------------------------------------------
# Financial Analytics Schemas
# -------------------------------------------------------------

class AnalyticsOut(Schema):
    gross_revenue: Decimal
    cogs: Decimal
    net_profit: Decimal
    profit_margin_pct: float
    cash_on_hand: Decimal
    uncollected_utang: Decimal
    cash_sales_total: Decimal
    utang_sales_total: Decimal
    repayments_total: Decimal
    total_transactions_count: int
    period: Optional[str] = "all"


# -------------------------------------------------------------
# Inventory Turnover Schemas
# -------------------------------------------------------------

class ProductTurnoverItem(Schema):
    product_id: uuid.UUID
    sku: str
    name: str
    category: str
    sales_7d: Decimal
    sales_30d: Decimal
    daily_velocity_7d: float
    daily_velocity_30d: float
    current_stock: Decimal
    wholesale_cost: Decimal = Decimal("0.00")
    retail_price: Decimal = Decimal("0.00")
    stock_value: Decimal
    turnover_ratio: float
    status: str
    status_label: str


class InventoryTurnoverOut(Schema):
    fast_moving: List[ProductTurnoverItem]
    dead_stock: List[ProductTurnoverItem]
    all_items: List[ProductTurnoverItem]
    all_skus: Optional[List[ProductTurnoverItem]] = None
    fast_moving_count: int
    dead_stock_count: int
    dead_stock_tied_capital: Decimal
    as_of: datetime


