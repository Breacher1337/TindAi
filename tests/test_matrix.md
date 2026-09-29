# Functional Test Case Matrix (IEEE 829 Aligned)
## TindAI: An AI-Powered Inventory, Sales Logging, and Restocking System

**Document ID**: TEST-MAT-01
**Course**: CCSFEN1L - Introduction to Software Engineering
**Section**: COM245 | **Group**: GrouPals
**Faculty Evaluator**: Ms. Elsie V. Isip
**QA Lead**: Pastrana, Aljean Kervy
**Testing Team**: Aseoche, Andre Joab L.; Ojastro, Raven Marielle O.; Sapla, Elaijah Angelo A.; Ventura, Kristine Cate B.
**Version**: 1.0.0
**Date**: September 29, 2026

---

## 1. Test Suite Overview

This Functional Test Matrix is structured in compliance with the **IEEE 829 Standard for Software and System Test Documentation**. It systematically verifies the core functional requirements (**FR-01 to FR-06**) and key non-functional constraints (**NFR-01 to NFR-03**).

### Scope and Test Types:
- **Positive / Happy Path**: Validates expected operations under standard conditions.
- **Negative Path**: Validates error handling, rejection of invalid inputs, and boundary guards.
- **Boundary Condition**: Validates system resilience at numeric extremes (zero balance, exact budget match, capacity caps).
- **Resilience / Fault Injection**: Validates offline network dropouts, retry queues, and background sync.

---

## 2. Test Execution Matrix

| Test Case ID | Req ID | Test Description & Class | Preconditions | Test Steps | Test Input Data | Expected Result | Status | Assigned Tester |
|:---|:---|:---|:---|:---|:---|:---|:---|:---|
| **TC-POS-01** | `FR-01`<br>`NFR-02` | **Standard Multi-Item Counter Scan**<br>*(Positive)* | Camera accessible; catalog seeded with FMCG SKUs. | 1. Open POS camera.<br>2. Point at counter containing 3 items.<br>3. Tap shutter.<br>4. Inspect Fast Review cart.<br>5. Tap "Bayad Cash". | Photo of 1x Kopiko Blanca sachet, 1x Lucky Me Pancit Canton Kalamansi, 1x 555 Sardines. | VLM detects all 3 SKUs with quantity = 1; cart renders in $\le 3.5\text{s}$; total = ₱55.00; cash balance increments by ₱55.00; inventory decrements by 1 each. Completed in 2 taps after snapshot. | `Ready to Test` | Pastrana, A. |
| **TC-POS-02** | `FR-01` | **Manual Quick-Add for Loose Tingi Item**<br>*(Positive)* | Store catalog contains unbarcoded loose egg SKU (`SKU-EGG-001`). | 1. Navigate to Fast Review screen.<br>2. Swipe open "Quick Add" drawer.<br>3. Tap "Fresh Egg" 3 times.<br>4. Tap "Bayad Cash". | 3x Fresh Chicken Egg @ ₱9.50 each. | Cart subtotal updates from ₱0.00 to ₱28.50 immediately ($< 200\text{ms}$); checkout records cash sale; egg inventory decrements by 3. | `Ready to Test` | Pastrana, A. |
| **TC-POS-03** | `FR-01` | **Quantity Stepper Adjustment & Item Deletion**<br>*(Positive/Boundary)* | Cart contains detected items from snapshot. | 1. On Fast Review, tap `+` on Lucky Me.<br>2. Tap `-` twice to reduce quantity to zero.<br>3. Confirm removal prompt. | Initial cart: 1x Lucky Me Original @ ₱15.00. | On first `-`, quantity = 0; item highlights red or prompts deletion; cart subtotal updates to ₱0.00; checkout button disables until item count $> 0$. | `Ready to Test` | Aseoche, A. |
| **TC-POS-04** | `FR-01`<br>`FR-03` | **Credit Checkout (Utang) Flow**<br>*(Positive)* | Customer profile "Nanay Tessie" exists with balance ₱150.00, credit limit ₱1,000. | 1. Scan 2x Bear Brand 33g.<br>2. On Fast Review, tap "Utang".<br>3. Search and select "Nanay Tessie".<br>4. Confirm credit sale. | 2x Bear Brand 33g @ ₱16.00 = ₱32.00 total. | Physical cash remains unchanged; Nanay Tessie balance updates to ₱182.00; itemized transaction appended to her credit ledger. | `Ready to Test` | Ventura, K. |
| **TC-POS-05** | `FR-01`<br>`FR-03` | **Exceeding Customer Credit Limit Guard**<br>*(Negative)* | Customer "Tito Carding" has current balance ₱450.00, credit limit ₱500.00. | 1. Add 1x Red Horse 1000ml (₱130.00) to cart.<br>2. Tap "Utang".<br>3. Select "Tito Carding".<br>4. Attempt to finalize. | Cart total: ₱130.00. (₱450 + ₱130 = ₱580 > ₱500 limit). | Modal error triggers: *"Lagpas sa Credit Limit! (Max: ₱500.00)"*; transaction blocked unless store owner enters override PIN or customer pays difference in cash. | `Ready to Test` | Ventura, K. |
| **TC-POS-06** | `FR-01` | **Empty Counter / Blurry Unrecognizable Image**<br>*(Negative/Degraded)* | POS camera active in low-light setting. | 1. Capture photo of a blank wooden counter with no merchandise.<br>2. Observe VLM response. | Image: Flat counter with zero items. | System displays friendly Taglish notification: *"Walang paninda na nakita. Subukang itapat ulit o mag-add gamit ang Quick Add"* without crashing or throwing 500 error. | `Ready to Test` | Pastrana, A. |
| **TC-OCR-01** | `FR-02` | **Puregold Thermal Receipt Automated Stock-In**<br>*(Positive)* | Receipt scanner active; sample Puregold receipt ready. | 1. Upload photo of Puregold invoice.<br>2. Trigger OCR parsing.<br>3. Inspect extracted line items and unit costs.<br>4. Confirm stock-in. | Receipt with: 1x `LKY ME PC EXT HOT 72S` @ ₱900.00, 1x `KOPIKO BLANCA 10S` @ ₱115.00. | OCR extracts 2 line items; maps to `SKU-NOOD-002` and `SKU-COFF-001`; calculates wholesale unit cost (₱12.50 and ₱11.50); updates stock quantities (+72 and +10); applies 15% markup to retail price. | `Ready to Test` | Ojastro, R. |
| **TC-OCR-02** | `FR-02` | **Unrecognized Abbreviated Line Item Onboarding**<br>*(Boundary/Negative)* | Receipt contains new brand not present in store catalog. | 1. Upload receipt containing unfamiliar item.<br>2. Review OCR extraction list. | Raw line: `CHAMPION BAR BLU 4S` @ ₱84.00. | OCR flags item with high confidence match $< 80\%$; prompts owner: *"Bagong Paninda! Ilagay ang Tingi Price"*; allows 1-tap product creation with default 15% markup. | `Ready to Test` | Ojastro, R. |
| **TC-OCR-03** | `FR-02` | **Crumpled / Severely Faded Receipt Fallback**<br>*(Degraded)* | Faded supermarket receipt with thermal illegibility. | 1. Upload crumpled receipt where 40% of characters are unreadable. | Degraded receipt image. | System extracts readable headers; highlights ambiguous rows with yellow warning tag; prompts store owner to manually verify unit cost before inventory commit. | `Ready to Test` | Ojastro, R. |
| **TC-UTG-01** | `FR-03` | **Partial Utang Repayment Flow**<br>*(Positive)* | Debtor "Aling Nena" has outstanding balance ₱650.00. | 1. Open Utang Ledger.<br>2. Select "Aling Nena".<br>3. Tap "Magbayad".<br>4. Enter cash amount ₱300.00.<br>5. Confirm payment. | Repayment amount: ₱300.00 Cash. | Outstanding balance decreases from ₱650.00 to ₱350.00; cash-on-hand increases by ₱300.00; repayment entry logged with timestamp. | `Ready to Test` | Ventura, K. |
| **TC-UTG-02** | `FR-03` | **Full Debt Liquidation & Zero Balance Audit**<br>*(Boundary)* | Debtor "Mang Ben" owes ₱240.00. | 1. Open Mang Ben profile.<br>2. Tap "Full Payment" (₱240.00).<br>3. Submit. | Repayment: ₱240.00. | Balance updates to exactly ₱0.00; customer status toggles to "Settled" (Bayad na); congratulatory badge displayed; debtor remains in contacts. | `Ready to Test` | Ventura, K. |
| **TC-UTG-03** | `FR-03` | **Negative / Zero Repayment Validation**<br>*(Negative)* | Customer profile open with balance ₱500.00. | 1. Tap "Magbayad".<br>2. Enter `-₱50.00` or `₱0.00`.<br>3. Tap submit. | Input: `-50` and `0`. | Form validation blocks submission; renders message: *"Dapat mas mataas sa ₱0 ang bayad"*; balance remains ₱500.00. | `Ready to Test` | Ventura, K. |
| **TC-OPT-01** | `FR-04` | **Knapsack Optimizer Under Standard Budget (₱5,000)**<br>*(Positive)* | Catalog populated; multiple items below reorder point. | 1. Navigate to Restocking Optimizer.<br>2. Input budget: `₱5,000.00`.<br>3. Tap "I-optimize ang Restock". | Budget $B = 5,000.00$; 8 items flagged below ROP. | Optimizer outputs bundle of wholesale packs satisfying $\sum (c_i \cdot x_i) \le 5,000.00$; zero budget overruns; items prioritized by sales velocity and margin; returns aisle-sorted list in $< 1.0\text{s}$. | `Ready to Test` | Ojastro, R. |
| **TC-OPT-02** | `FR-04` | **Extremely Low Working Capital Budget (₱500)**<br>*(Boundary)* | Budget input set to ₱500.00 where lowest pack cost is ₱115.00. | 1. Input budget: `₱500.00`.<br>2. Run optimizer. | Budget $B = 500.00$. | Optimizer selects maximum affordable high-priority packs (e.g. 3x Kopiko Blanca @ ₱115 + 1x Great Taste @ ₱110 = ₱455); remaining cash ₱45 displayed as unallocated buffer. | `Ready to Test` | Ojastro, R. |
| **TC-OPT-03** | `FR-04` | **Zero / Negative Restocking Budget Input**<br>*(Negative)* | Restocking page open. | 1. Input budget: `0` or `-1000`.<br>2. Attempt to run optimization. | Input: `0` or `-1000`. | Input field displays red error state: *"Maglagay ng tamang puhunan (Minimum ₱500)"*; optimization solver not invoked. | `Ready to Test` | Sapla, E. |
| **TC-ANL-01** | `FR-05` | **Financial Dashboard Margin & Liquidity Separation**<br>*(Positive)* | Day recorded: ₱1,200 cash sales, ₱400 utang sales, COGS = ₱1,280. | 1. Navigate to Dashboard.<br>2. Inspect Total Sales, COGS, Net Profit, and Liquidity breakdown. | Cash: ₱1,200; Utang: ₱400; Total Revenue: ₱1,600; COGS: ₱1,280. | Gross Sales displays ₱1,600.00; Net Gross Profit displays ₱320.00 (20% margin); Cash-on-hand shows ₱1,200.00; Uncollected Utang shows ₱400.00; clear visual distinction prevents commingling. | `Ready to Test` | Pastrana, A. |
| **TC-SYN-01** | `FR-06` | **Synthetic Payday Cycle Generation Verification**<br>*(Positive/Analysis)* | Synthetic generation script executed for 365 days. | 1. Run synthetic simulation engine.<br>2. Filter sales on the 15th and 30th.<br>3. Calculate sales volume multiplier. | Seed: 365 days simulation, 15 suki profiles. | Sales on 15th and 30th show a statistically significant surge ($1.8\times \pm 0.2\times$ average weekday baseline); utang settlements spike by $\ge 2.5\times$ on payday dates; confirms cultural authenticity. | `Ready to Test` | Aseoche, A. |
| **TC-OFF-01** | `NFR-03` | **Offline Cash Sale and Service Worker Background Sync**<br>*(Resilience)* | PWA installed; store internet disconnected (DevTools Offline mode). | 1. Disconnect Wi-Fi/4G.<br>2. Add 2 items to cart on POS.<br>3. Tap "Bayad Cash".<br>4. Reconnect network.<br>5. Inspect server DB. | Offline state: 2x Silver Swan Pouch (₱26.00). | POS displays badge: *"Offline Mode - Naka-save sa Phone"*; cart clears; IndexedDB records pending transaction; upon network reconnection, Service Worker auto-syncs payload; backend DB records sale without duplicates. | `Ready to Test` | Aseoche, A. |

---

## 3. Test Reporting Guidelines & Defect Classification

When executing tests from this matrix, defects must be documented using the following standard severity classifications:

1. **Blocker (Severity 1)**: System crashes, complete transaction data loss, database corruption, or security key exposure.
2. **Critical (Severity 2)**: Core functional failure with no workaround (e.g., checkout button unresponsive, Knapsack optimizer exceeds allocated budget).
3. **Major (Severity 3)**: Core function operates with workaround (e.g., VLM misidentifies package, but manual correction works).
4. **Minor / Cosmetic (Severity 4)**: UI styling defect, minor Taglish typographical error, or slight alignment flaw.
