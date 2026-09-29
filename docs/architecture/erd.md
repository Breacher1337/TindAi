# Entity Relationship Diagram (ERD) & Data Architecture
## TindAI: An AI-Powered Inventory, Sales Logging, and Restocking System

**Course**: CCSFEN1L - Introduction to Software Engineering
**Section**: COM245 | **Group**: GrouPals
**Faculty Evaluator**: Ms. Elsie V. Isip
**Author**: Sapla, Elaijah Angelo A. & GrouPals
**Version**: 1.0.0
**Date**: September 29, 2026

---

## 1. System Conceptual Data Model

The TindAI database architecture models the micro-economic realities of Philippine sari-sari store operations:
1. **Catalog & Dual-Unit Inventory**: Products are purchased in wholesale bulk packs (`pack_unit`) but portion-retailed in single servings (`tingi_unit`).
2. **Sales & Flexible Tender**: Every counter transaction links to itemized lines, supporting instant Cash settlement or attribution to a Customer Utang ledger.
3. **Wholesaler Invoices & Cost Tracking**: Invoices record procurement from wholesale grocers (e.g., Puregold), preserving batch costs to dynamically calculate true margins.
4. **Utang Ledger & Audit Integrity**: Debtor accounts track balance changes and repayment streams without destructive updates.

---

## 2. Mermaid Entity Relationship Diagram

```mermaid
erDiagram
 WHOLESALER ||--o{ INVOICE : issues
 INVOICE ||--|{ INVOICE_ITEM : contains
 PRODUCT ||--o{ INVOICE_ITEM : maps_to
 PRODUCT ||--o{ INVENTORY_BATCH : replenishes
 PRODUCT ||--o{ TRANSACTION_ITEM : sold_in
 PRODUCT ||--o{ STOCK_MOVEMENT : tracks

 SALES_TRANSACTION ||--|{ TRANSACTION_ITEM : includes
 CUSTOMER ||--o{ SALES_TRANSACTION : incurs_credit
 CUSTOMER ||--o{ UTANG_PAYMENT : settles

 WHOLESALER {
 uuid id PK
 string name "e.g. Puregold, Super8, SM"
 string branch "e.g. Shaw Blvd, Pasig"
 string contact_number
 timestamp created_at
 }

 PRODUCT {
 uuid id PK
 string sku UK "e.g. SKU-NOOD-001"
 string name "Product title"
 string brand "Brand manufacturer"
 string category "Instant Noodles, Coffee, etc."
 decimal wholesale_cost "Cost per tingi unit (PHP)"
 decimal retail_price "Selling price (PHP)"
 integer current_stock "In tingi units"
 integer reorder_point "ROP threshold"
 string pack_unit "e.g. box of 72, tie of 10"
 string tingi_unit "sachet, bottle, piece"
 string barcode "EAN-13 (optional)"
 boolean is_active
 timestamp updated_at
 }

 INVOICE {
 uuid id PK
 uuid wholesaler_id FK
 string invoice_number "Wholesaler receipt number"
 date invoice_date
 decimal total_amount "Receipt gross total"
 string receipt_image_url
 string parse_status "pending, parsed, confirmed"
 timestamp created_at
 }

 INVOICE_ITEM {
 uuid id PK
 uuid invoice_id FK
 uuid product_id FK "Nullable if unmatched"
 string raw_line_text "Cryptic line item string"
 integer quantity_packs "Number of bulk packs"
 decimal pack_cost "Total cost per pack"
 integer units_per_pack "Conversion multiplier"
 decimal unit_cost "Derived cost per tingi unit"
 timestamp created_at
 }

 INVENTORY_BATCH {
 uuid id PK
 uuid product_id FK
 uuid invoice_item_id FK
 integer initial_tingi_quantity
 integer remaining_tingi_quantity
 decimal unit_cost_basis "FIFO cost tracking"
 timestamp received_at
 }

 STOCK_MOVEMENT {
 uuid id PK
 uuid product_id FK
 string movement_type "SALE, RESTOCK, SPOILAGE, AUDIT_ADJUSTMENT"
 integer quantity_change "Positive for restock, negative for sale"
 integer balance_after
 string reference_id "Transaction or Invoice UUID"
 timestamp timestamp
 }

 CUSTOMER {
 uuid id PK
 string full_name "Full name of debtor"
 string nickname "Barangay alias / tawag"
 string contact_number "Mobile number for SMS"
 string address "House # or landmark"
 decimal credit_limit "Max allowable debt"
 decimal current_balance "Cumulative outstanding utang"
 boolean is_active
 timestamp created_at
 }

 SALES_TRANSACTION {
 uuid id PK
 string transaction_number UK "e.g. TXN-20260929-001"
 uuid customer_id FK "Nullable for cash sales"
 string tender_type "CASH, UTANG, SPLIT"
 decimal gross_total "Total selling price"
 decimal total_cogs "Cost of Goods Sold"
 decimal gross_profit "gross_total minus total_cogs"
 string sync_status "PENDING_OFFLINE, SYNCED"
 timestamp transaction_time
 }

 TRANSACTION_ITEM {
 uuid id PK
 uuid transaction_id FK
 uuid product_id FK
 string product_name_snapshot "Historical name lock"
 decimal unit_retail_price "Price at time of sale"
 decimal unit_cost_basis "Cost at time of sale"
 integer quantity "Quantity sold (tingi units)"
 decimal subtotal "unit_retail_price * quantity"
 }

 UTANG_PAYMENT {
 uuid id PK
 uuid customer_id FK
 decimal amount_paid "Cash amount liquidated"
 decimal balance_before
 decimal balance_after
 string notes "e.g. Bayad sa sahod"
 timestamp payment_time
 }
```

---

## 3. Core Entity Specifications & Schema Dictionary

### 3.1 `PRODUCT` (Catalog Master)
- **Role**: Master dictionary of all FMCG and unbarcoded goods retailed by the store.
- **Key Fields**:
 - `sku`: Unique machine-readable identifier (e.g., `SKU-NOOD-001`).
 - `wholesale_cost`: Unit cost base in PHP, updated dynamically when wholesale receipts are ingested.
 - `retail_price`: Selling price in PHP, defaulting to $15\%$ gross profit markup.
 - `current_stock`: Live counter of remaining portion servings (`tingi_unit`).
 - `reorder_point`: Computed threshold trigger for restocking notifications.

### 3.2 `WHOLESALER` & `INVOICE` (Procurement & OCR Records)
- **Role**: Archives supplier information and stores scanned wholesale paper receipts.
- **Integrity**: `INVOICE.wholesaler_id` links to the vendor. If an invoice line item cannot be matched to an existing catalog SKU, `INVOICE_ITEM.product_id` is set to `NULL` until the store owner onboards the new item.

### 3.3 `INVENTORY_BATCH` & `STOCK_MOVEMENT` (Stock Tracking & FIFO Costing)
- **Role**: Provides an immutable ledger of every stock ingress and egress.
- **FIFO Profit Margin Precision**: When sales occur, COGS is calculated against the active batch unit cost basis, ensuring true gross margin accuracy even across supplier price fluctuations.

### 3.4 `SALES_TRANSACTION` & `TRANSACTION_ITEM` (POS Transactions)
- **Role**: Captures all checkout events initiated from the mobile Fast Review screen.
- **Offline Resilience**: Transactions created while offline receive `sync_status = 'PENDING_OFFLINE'` with client-generated UUIDs. Upon reconnect, they are persisted without collision.
- **Tender Segmentation**: If `tender_type = 'CASH'`, `customer_id` is null. If `tender_type = 'UTANG'`, `customer_id` points to the customer profile.

### 3.5 `CUSTOMER` & `UTANG_PAYMENT` (Digital Credit Ledger)
- **Role**: Implements the informal credit ledger (*listahan ng utang*).
- **Integrity Guarantee**: `CUSTOMER.current_balance` is updated atomically inside a database transaction whenever a credit sale is finalized or an `UTANG_PAYMENT` is logged.

---

## 4. Database Indexing & Performance Strategy

To satisfy **NFR-01** (local response times $\le 200\text{ms}$):
1. **B-Tree Indexes**:
 - `PRODUCT(sku)`: Instant lookup during VLM schema mapping.
 - `PRODUCT(category)`: Fast grouping for catalog views.
 - `SALES_TRANSACTION(transaction_time)`: Real-time daily analytics aggregation.
 - `CUSTOMER(current_balance)`: Instant sorting of highest outstanding balances.
2. **Trigram / GIN Indexing**:
 - `PRODUCT USING gin(name gin_trgm_ops)`: Enables sub-millisecond fuzzy matching against cryptic supermarket receipt OCR line items.
