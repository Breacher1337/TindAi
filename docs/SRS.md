# Software Requirements Specification (SRS)
## TindAI: An AI-Powered Inventory, Sales Logging, and Capital-Constrained Restocking System for Sari-Sari Stores

**Standard**: IEEE Std 830-1998 Compliant
**Course**: CCSFEN1L - Introduction to Software Engineering
**Section**: COM245 | **Group**: GrouPals
**Faculty Evaluator**: Ms. Elsie V. Isip
**Project Leader**: Sapla, Elaijah Angelo A.
**Team Members**:
- Aseoche, Andre Joab L.
- Ojastro, Raven Marielle O.
- Pastrana, Aljean Kervy
- Ventura, Kristine Cate B.

**Version**: 1.0.0
**Date**: September 29, 2026

---

## 1. Introduction

### 1.1 Purpose
This Software Requirements Specification (SRS) establishes the complete functional and non-functional requirements for **TindAI**, a mobile-first Progressive Web Application (PWA) designed for neighborhood micro-retail establishments ("sari-sari stores") in the Philippines. TindAI addresses critical operational bottlenecks in informal retail - specifically unbarcoded portion-retailing ("tingi"), manual credit bookkeeping ("listahan ng utang"), commingled finances, and blind procurement under tight revolving working capital - by integrating Multimodal Large Language Model (VLM) perception, optical character recognition (OCR), dynamic Reorder Point (ROP) inventory algorithms, and bounded knapsack capital budget optimization.

### 1.2 Document Conventions
This document conforms to the IEEE Std 830-1998 specification guidelines.
- Requirement priorities are designated as:
 - **[P0 - Critical]**: Essential for core operation and minimum viable product (MVP).
 - **[P1 - High]**: Required for primary user workflows and core research evaluation.
 - **[P2 - Medium]**: Enhancements that improve usability, reporting, or secondary processes.
- Functional requirements are prefixed with `FR-` followed by two digits.
- Non-functional requirements are prefixed with `NFR-` followed by two digits.
- Mathematical parameters and formal notations follow standard discrete optimization and inventory control conventions.

### 1.3 Intended Audience and Reading Suggestions
This document is prepared for:
1. **Academic Evaluation Committee & Faculty Evaluator (Ms. Elsie V. Isip)**: For assessing software engineering rigor, architectural decisions, and requirement-test traceability.
2. **Software Engineering Development Team (GrouPals)**: As the binding implementation contract for backend developers, frontend engineers, and QA testers.
3. **External Evaluators & Field Researchers**: For understanding socio-technical adaptations to informal Philippine micro-commerce.

### 1.4 Project Scope
TindAI provides an end-to-end operational software suite that:
1. Replaces manual transaction recording with **one-tap camera snapshot checkout** using multimodal vision models.
2. Digitizes informal customer credit (**utang**) with real-time ledgers, repayment tracking, and courteous automated reminder templates.
3. Automates wholesaler inventory replenishment through **receipt OCR parsing** from major supermarkets (e.g., Puregold, Super8), mapping abbreviated entries to store SKUs and establishing automatic 15% profit margins.
4. Solves a **Bounded 0/1 Knapsack Optimization Problem** that ingests the owner's available revolving cash budget (typically ₱3,000 to ₱8,000) and outputs a prioritized, aisle-sorted restocking procurement list that prevents stockouts while maximizing gross margin yield.
5. Ingests a **Culturally Authentic Synthetic Data Generation Engine** simulating 6 to 12 months of Philippine sari-sari retail dynamics (bi-monthly payday cycles on the 15th/30th, weekend beverage surges, and credit borrowing curves) to rigorously benchmark forecasting and procurement algorithms.

**Out of Scope**: Direct automated bank-to-bank electronic fund transfers, hardware cash drawer solenoid triggers, and real-time wholesaler stock API scraping.

### 1.5 Definitions, Acronyms, and Abbreviations
- **COGS**: Cost of Goods Sold.
- **FMCG**: Fast-Moving Consumer Goods (packaged foods, beverages, toiletries).
- **Knapsack Problem**: A combinatorial optimization problem where items with specific weights (costs) and values (margins/velocity) are selected without exceeding a fixed capacity (revolving cash budget).
- **OCR**: Optical Character Recognition.
- **PWA**: Progressive Web Application.
- **ROP**: Reorder Point, the threshold stock level that triggers replenishment: $ROP = (d \times L) + SS$.
- **Safety Stock ($SS$)**: Buffer inventory held to mitigate risk of stockouts caused by demand surges or delivery lead-time delays: $SS = Z \times \sigma_d \times \sqrt{L}$.
- **Sari-Sari Store**: Small, family-run neighborhood convenience store in the Philippines typically operated from a residential window.
- **Suki**: A loyal, regular patron or customer who enjoys reciprocal trust and credit privileges.
- **Tingi**: The Philippine cultural practice of portion-retailing, selling items in single-use sachets, individual cigarettes, or single eggs rather than multi-unit bulk packs.
- **Utang**: Informal short-term consumer credit extended without collateral or formal interest.
- **VLM**: Vision-Language Model (e.g., Google Gemini 1.5 Flash).

### 1.6 References
1. Achiam, J., et al. (2023). *GPT-4 Technical Report*. arXiv preprint arXiv:2303.08774.
2. Banerjee, A. V., & Duflo, E. (2007). *The economic lives of the poor*. Journal of Economic Perspectives, 21(1), 141-168. https://doi.org/10.1257/jep.21.1.141
3. Bonnin, C. (2004). *Sari-sari stores: The household economy and women's micro-enterprises in the urban Philippines*. Department of Sociology, Dalhousie University.
4. Bonnin, C. (2006). *Women’s survival strategies and experiences with support services as home-based micro-entrepreneurs in Metro Manila*. In I. Guérin & J. Palier (Eds.), Microfinance challenges (pp. 165-185). French Institute of Pondicherry.
5. Department of Trade and Industry [DTI]. (2018). *Sari-sari store economic empowerment and micro-enterprise baseline survey*. Republic of the Philippines.
6. Google DeepMind. (2023). *Gemini: A family of highly capable multimodal models*. arXiv preprint arXiv:2312.11805.
7. Hyndman, R. J., & Athanasopoulos, G. (2021). *Forecasting: principles and practice* (3rd ed.). OTexts: Melbourne, Australia.
8. Kantar Philippines. (2022). *Shopper trends and channel dynamics in the Philippine FMCG market*. Kantar Worldpanel.
9. Kellerer, H., Pferschy, U., & Pisinger, D. (2004). *Knapsack problems*. Springer-Verlag Berlin Heidelberg. https://doi.org/10.1007/978-3-540-24777-7
10. Martello, S., & Toth, P. (1990). *Knapsack problems: Algorithms and computer implementations*. John Wiley & Sons.
11. Mendoza, R. U. (2011). *Why do the poor pay more? Exploring the market dynamics of the tingi economy*. Journal of International Development, 23(1), 18-33.
12. NielsenIQ. (2021). *The state of Philippine traditional trade and sari-sari store dynamics*. NIQ Retail Intelligence.
13. Nikolenko, S. I. (2021). *Synthetic data for deep learning*. Springer Optimization and Its Applications.
14. Packworks. (2024). *Sari-sari store transaction index and consumption patterns report*. Packworks Analytics.
15. Prahalad, C. K. (2004). *The fortune at the bottom of the pyramid: Eradicating poverty through profits*. Wharton School Publishing.
16. Schelzig, K. (2005). *Poverty in the Philippines: Income, assets, and access*. Asian Development Bank.

---

## 2. Overall Description

### 2.1 Product Perspective
TindAI is an autonomous, cloud-orchestrated, mobile-first PWA. It interfaces with:
- **Mobile Hardware**: Smartphone camera modules via the HTML5 MediaDevices / Camera API.
- **AI Perception Service**: Google Gemini API (`@google/genai` / `gemini-1.5-flash`) utilizing structured JSON schema output enforcement.
- **Client Cache**: IndexedDB managed via Workbox Service Workers for transparent offline operation during telecommunications outages.
- **Backend Infrastructure**: Python Django Ninja REST framework backed by PostgreSQL.
- **Optimization Engine**: SciPy / PuLP linear programming suite for bounded integer knapsack execution.

```
+-----------------------------------------------------------------------+
| Client Mobile Browser (PWA) |
| [ Camera Capture ] <---> [ Fast Review POS ] <---> [ Offline Cache ] |
| [ Utang Ledger ] <---> [ Budget Restock ] (IndexedDB/SW) |
+-----------------------------------------------------------------------+
 | TLS 1.3 / HTTPS
 v
+-----------------------------------------------------------------------+
| Django Ninja Backend API Gateway |
| [ Auth & Security ] [ Sales Router ] [ Inventory & Stock Router ] |
+-----------------------------------------------------------------------+
 | | |
 v v v
+----------------------+ +----------------------+ +---------------+
| PostgreSQL Database | | Gemini 1.5 Flash | | SciPy / PuLP |
| - Relational Models | | - VLM Item Vision | | Optimization |
| - Audit Log Trajectory| | - Receipt OCR Parser| | (Knapsack) |
+----------------------+ +----------------------+ +---------------+
```

### 2.2 Product Functions
1. **Multimodal Counter Point-of-Sale (POS)**: Image-to-cart generation for unbarcoded packaged goods.
2. **Wholesale Receipt Ingestion (OCR)**: Printed receipt line extraction and catalog cost/price updates.
3. **Digital Utang Ledger**: Debtor tracking, partial balance liquidation, and automated SMS reminder templates.
4. **Capital-Constrained Restocking Optimizer**: Mathematical purchase list optimization bounded by available cash.
5. **Real-Time Financial Analytics**: Profit margin, gross sales, COGS, and physical vs. debt asset tracking.
6. **Synthetic Micro-Retail Generator**: Behavioral simulation engine for algorithmic benchmarking.

### 2.3 User Classes and Characteristics
1. **Primary Operator (Tindero / Tindera)**:
 - *Technical Literacy*: Moderate to low; accustomed to Facebook, TikTok, and GCash, but unfamiliar with complex ERP software.
 - *Operating Context*: One-handed thumb usage, standing in a cramped store doorway, dealing with rapid customer turnover, bright sunlight, or dim 10-watt fluorescent lighting.
 - *Needs*: Minimal typing, fast recognition, zero screen clutter, large touch targets ($\ge 48\text{ dp}$), and bilingual Taglish copy.
2. **Student Caretakers / Family Relievers**:
 - *Technical Literacy*: High; comfortable with modern smartphone interfaces.
 - *Needs*: Clear audit logs to ensure transparent handovers between morning and evening shifts.
3. **Faculty Evaluators & Software Researchers**:
 - *Technical Literacy*: Expert; assessing system architecture, unit test coverage, and benchmark metrics.

### 2.4 Operating Environment
- **Client OS**: Android 9.0 (Pie) or higher, running Chrome Mobile 100+ or Samsung Internet; iOS Safari 15+ (secondary).
- **Display Resolution**: Mobile viewports ranging from $360 \times 640\text{ px}$ to $412 \times 915\text{ px}$.
- **Connectivity**: Variable 3G/4G/5G mobile data with intermittent high-latency or packet drop; offline-capable.
- **Backend Host**: Linux (Ubuntu 22.04 LTS x86_64 or containerized Docker alpine runtime), Python 3.11+, PostgreSQL 15+.

### 2.5 Design and Implementation Constraints
1. **Budget Hardware Performance**: Must execute without client-side lag on entry-level Android devices (e.g., MediaTek Helio P22/G35, 3GB RAM).
2. **Token Economy & API Cost**: Pre-processing must crop and compress images prior to cloud transmission to maintain strict payload boundaries ($\le 1024 \times 1024\text{ px}$, $\le 300\text{ KB}$).
3. **Academic Deliverable Timeline**: One academic semester (CCSFEN1L timeline); requires synthetic benchmark generator to validate predictive algorithms without waiting 12 months for live store accumulation.

### 2.6 User Documentation
- Illustrated Quick-Start Field Guide (`docs/user_manual/STORE_OWNER_GUIDE.md`).
- Git Contribution Guidelines (`CONTRIBUTING.md` and `docs/GIT_WORKFLOW.md`).
- Architecture & Database Schemas (`docs/architecture/erd.md`, `docs/use_cases.md`).

### 2.7 Assumptions and Dependencies
- Google Gemini API service availability $\ge 99.5\%$.
- Device camera equipped with autofocus and minimum 5.0 Megapixel sensor resolution.
- Store owner possesses basic literacy in Filipino and English (Taglish).

---

## 3. Specific Requirements

### 3.1 External Interface Requirements

#### 3.1.1 User Interfaces
- Responsive Mobile-First PWA interface built with high-contrast UI tokens (WCAG AA compliant, $\ge 4.5:1$ contrast ratio).
- Large touch buttons (minimum $48 \times 48\text{ dp}$) positioned within the thumb reach zone (bottom 60% of viewport).
- Bilingual UI labels featuring everyday Filipino retail terminology (*"Benta"*, *"Utang"*, *"Tingi"*, *"Tira / Stock"*, *"Tubo"*).

#### 3.1.2 Hardware Interfaces
- Standard smartphone camera accessible via `navigator.mediaDevices.getUserMedia()`.
- Device vibration hardware accessible via `navigator.vibrate()` for tactile confirmation.

#### 3.1.3 Software Interfaces
- **PostgreSQL 15+ Database**: Accessible via Django ORM using connection pooling.
- **Google Gemini Generative AI SDK**: REST/gRPC client invoking `gemini-1.5-flash` with JSON response schemas.
- **IndexedDB / Service Worker API**: Cache storage interface for offline transaction journaling.

#### 3.1.4 Communications Interfaces
- HTTPS / TLS 1.3 encryption on all REST API endpoints.
- JSON data serialization over HTTP `application/json`.
- Multi-part form data `multipart/form-data` for image payload transmission.

---

### 3.2 System Features / Detailed Functional Requirements

#### 3.2.1 Feature 1: Multimodal Counter Sales Capture & POS (FR-01)
- **FR-01.1 [P0] Camera Snapshot Ingestion**: The system shall provide a continuous viewfinder or single-tap camera shutter to capture items positioned on the store counter.
- **FR-01.2 [P0] VLM Object Detection**: The backend shall transmit compressed images to the Google Gemini 1.5 Flash endpoint with a strict JSON schema prompt instructing the model to output detected items matching catalog SKUs and estimated quantities.
- **FR-01.3 [P0] Fast Review Cart Screen**: The client shall immediately render an editable cart displaying detected items, unit prices, subtotal, and quantity adjustment steppers (`+` and `-` buttons).
- **FR-01.4 [P1] One-Tap Manual Quick-Add Drawer**: The UI shall provide a drawer of unbarcoded, unpackaged goods (e.g., loose eggs, plastic-bagged ice, repacked sugar) that can be added to the cart with one tap.
- **FR-01.5 [P0] Dual Settlement Routing (Cash vs. Utang)**: The checkout bar shall present two distinct action buttons:
 - `Bayad Cash`: Finalizes transaction immediately, decrements inventory stock, and increments physical cash-on-hand.
 - `Utang`: Prompts customer selector modal; upon selection, records transaction, decrements inventory stock, and appends balance to debtor's ledger.
- **FR-01.6 [P0] Ergonomic Tap Boundary**: A standard sales transaction containing detected items shall require no more than three (3) screen taps from photo capture to checkout confirmation.

#### 3.2.2 Feature 2: Wholesaler Receipt OCR & Automated Stock-In (FR-02)
- **FR-02.1 [P1] Invoice Photo Ingestion**: The system shall allow the user to capture or upload photographs of long supermarket or wholesale paper receipts.
- **FR-02.2 [P1] Cryptic Line-Item Entity Extraction**: The OCR parser shall extract line-item abbreviations, wholesale pack quantities, pack wholesale cost, and receipt grand total.
- **FR-02.3 [P1] Fuzzy SKU Matching**: The system shall match parsed text against existing catalog SKUs using Levenshtein distance and token sort matching ($\ge 80\%$ confidence match).
- **FR-02.4 [P1] Automatic Retail Markup Application**: For newly matched items or restocked batches, the system shall apply a configurable retail markup (defaulting to 15% gross margin) to calculate the unit retail selling price:
 $$\text{Retail Price} = \frac{\text{Wholesale Cost per Tingi Unit}}{1 - 0.15}$$
- **FR-02.5 [P1] Batch Stock Increment**: Upon user confirmation of the parsed receipt review screen, the system shall atomically update current stock quantities and create audit logs in the stock movement ledger.

#### 3.2.3 Feature 3: Digital Utang (Credit) Management Ledger (FR-03)
- **FR-03.1 [P0] Customer Debtor Directory**: The system shall maintain customer profiles containing: Full Name, Alias/Nickname, Phone Number, House Address / Landmark, Credit Limit, and Total Outstanding Balance.
- **FR-03.2 [P0] Transactional Audit Trail**: Every credit purchase shall link directly to an itemized receipt record showing timestamp, purchased SKUs, unit prices, and quantities.
- **FR-03.3 [P0] Partial and Full Repayment Logging**: The system shall enable recording cash repayments of any amount, decrementing the outstanding balance and logging cash inflow into daily cash collections.
- **FR-03.4 [P2] Courteous Reminder Generator**: The system shall generate pre-formatted, polite Tagalog/Taglish notification texts that can be copied to clipboard or dispatched via Android Share Sheet to SMS or Messenger.

#### 3.2.4 Feature 4: Capital-Constrained Procurement & Smart Restocking Optimizer (FR-04)
- **FR-04.1 [P1] Dynamic Reorder Point (ROP) Calculation**: The system shall calculate the ROP for each SKU $i$ based on historical average daily demand ($d_i$), supplier lead time in days ($L_i$), and calculated safety stock ($SS_i$):
 $$ROP_i = (d_i \times L_i) + SS_i$$
 where safety stock is defined using service factor $Z = 1.65$ (95% service level):
 $$SS_i = Z \times \sigma_{d,i} \times \sqrt{L_i}$$
- **FR-04.2 [P0] Bounded Knapsack Formulation**: When an owner inputs an available replenishment cash budget $B$ (e.g., ₱3,000 to ₱8,000), the system shall formulate and solve a bounded knapsack optimization problem:
 $$\text{Maximize } \sum_{i=1}^{N} \left( v_i \cdot m_i \cdot x_i \right)$$
 subject to:
 $$\sum_{i=1}^{N} \left( c_i \cdot x_i \right) \le B$$
 $$0 \le x_i \le u_i, \quad x_i \in \mathbb{Z}^+$$
 where:
 - $x_i$: Integer quantity of wholesale packs to purchase for SKU $i$.
 - $c_i$: Wholesale unit purchase cost of pack $i$.
 - $v_i$: Demand velocity weight (derived from normalized sales frequency and stockout urgency).
 - $m_i$: Gross monetary profit margin generated per wholesale pack $i$.
 - $u_i$: Upper bound ceiling preventing overstocking (determined by storage limit and maximum weekly turnover).
 - $B$: Available revolving cash budget in Philippine Pesos (PHP).
- **FR-04.3 [P1] Exportable Checklist Generation**: The resulting optimal restocking bundle shall be formatted into a categorized, printable/shareable checklist organized by supermarket aisle sections (e.g., Canned Goods, Instant Noodles, Beverages, Personal Care).

#### 3.2.5 Feature 5: Financial Analytics & Profit Visibility Dashboard (FR-05)
- **FR-05.1 [P1] Real-Time Gross Revenue and Profit**: The system shall compute and display Gross Daily Revenue, Cost of Goods Sold (COGS), and True Net Gross Profit:
 $$\text{Net Profit} = \sum \text{Revenue} - \sum \text{COGS}$$
- **FR-05.2 [P1] Asset Liquidity Segmentation**: The dashboard shall explicitly separate physical cash-on-hand from outstanding debt receivables (uncollected utang), preventing store owners from conflating unpaid credit with usable cash.
- **FR-05.3 [P2] Fast-Moving vs. Slow-Moving Stock Classification**: The system shall compute 7-day and 30-day inventory turnover rates to flag dead inventory.

#### 3.2.6 Feature 6: Culturally Authentic Synthetic Data Generation Engine (FR-06)
- **FR-06.1 [P1] Longitudinal Micro-Retail Simulation**: The engine shall procedurally synthesize 6 to 12 months of realistic sari-sari transactions incorporating empirical Philippine socio-economic patterns:
 - Payday surges ($15^{\text{th}}$ and $30^{\text{th}}$ of each month) showing a $1.8\times$ baseline volume multiplier and elevated debt settlement rates.
 - Weekend evening beverage and snack peaks ($1.5\times$ baseline).
 - Pre-payday credit spikes ($1.6\times$ credit purchases on days 12-14 and 27-29).
 - Seasonal shifts (rainy season noodle/coffee demand vs. dry summer cold beverage demand).
- **FR-06.2 [P1] Benchmark Verification Framework**: The engine shall output standardized evaluation datasets to calculate the Mean Absolute Percentage Error (MAPE) of demand forecasts:
 $$MAPE = \frac{100\%}{n} \sum_{t=1}^{n} \left| \frac{A_t - F_t}{A_t} \right|$$
 demonstrating compliance with the project defense success threshold of $MAPE \le 20\%$ for top 20 staples.

---

### 3.3 Non-Functional Requirements

#### 3.3.1 Performance and Latency (NFR-01)
- **NFR-01.1**: Cloud VLM perception response (image upload $\rightarrow$ Gemini 1.5 Flash inference $\rightarrow$ JSON cart render) shall complete within **$\le 3.5$ seconds** over a standard 4G mobile network.
- **NFR-01.2**: Local database queries, IndexedDB writes, and screen transition latencies shall execute in **$\le 200$ milliseconds**.
- **NFR-01.3**: The Knapsack Restocking Optimizer shall solve and return recommendations for a catalog of 50 to 200 items in **$\le 1.0$ second**.

#### 3.3.2 Usability and Ergonomics (NFR-02)
- **NFR-02.1**: A standard counter sale of detected items shall require **$\le 3$ taps** on the mobile screen to finalize.
- **NFR-02.2**: All primary interactive buttons shall maintain a minimum touch target size of **$48 \times 48\text{ dp}$** with at least $8\text{ dp}$ spacing.
- **NFR-02.3**: The UI shall support bilingual Taglish terminology, enabling non-technical users to navigate without training.
- **NFR-02.4**: The system shall achieve a System Usability Scale (SUS) score of **$\ge 75$ points** (Grade B+) during user evaluations.

#### 3.3.3 Offline Resilience and Reliability (NFR-03)
- **NFR-03.1**: The PWA shall remain fully functional for recording cash sales and viewing inventory balances when the client device is completely offline.
- **NFR-03.2**: Offline transactions shall be queued sequentially in client-side IndexedDB and synchronized with the backend server via Service Worker background sync immediately upon reconnection.
- **NFR-03.3**: Sync conflict resolution shall employ optimistic concurrency control with monotonic version stamps to prevent duplicate transactions or corrupted inventory states.

#### 3.3.4 Cost-Efficiency and Resource Optimization (NFR-04)
- **NFR-04.1**: Client-side canvas preprocessing shall downscale captured photos to a maximum bounding box of **$1024 \times 1024$ pixels** and compress the image to **80% JPEG quality**, keeping payload sizes under $300\text{ KB}$.
- **NFR-04.2**: API prompt structures shall enforce compact JSON output schemas, maintaining token usage under 400 prompt tokens and 200 completion tokens per transaction scan.

#### 3.3.5 Security and Data Integrity (NFR-05)
- **NFR-05.1**: All client-server communications shall be strictly encrypted using Transport Layer Security (TLS 1.3 / HTTPS).
- **NFR-05.2**: Cloud AI API keys, database credentials, and cryptographic secrets shall remain isolated in backend server environment variables (`.env`) and never exposed to the frontend client.
- **NFR-05.3**: Debtor financial records and sales transaction ledgers shall be tamper-evident with append-only transaction logging.

#### 3.3.6 Maintainability and Testability (NFR-06)
- **NFR-06.1**: The codebase shall follow a clean, decoupled modular architecture separating the frontend PWA, backend REST routers, optimization routines, and synthetic data generator.
- **NFR-06.2**: Automated unit and integration test suites (PyTest / Jest) shall maintain at least **80% code coverage** across core business and optimization logic.

---

## 4. Verification Criteria & Traceability Matrix

| Requirement ID | Verification Method | Acceptance Criteria | Responsible Role |
|:---|:---|:---|:---|
| **FR-01 (Counter POS)** | Demonstration & Test | VLM identifies items $\ge 85\%$ F1-score; checkout $\le 3$ taps; latency $\le 3.5\text{s}$. | Lead / Pastrana |
| **FR-02 (Receipt OCR)** | Test & Inspection | Accurately extracts line items, costs, and totals with $\ge 90\%$ field accuracy. | Ojastro |
| **FR-03 (Utang Ledger)** | Test & Inspection | Correct balance updates upon credit sales and repayments; zero arithmetic leakage. | Ventura |
| **FR-04 (Restock Optimizer)** | Analysis & Test | Restocking bundle total cost $\le B$; gross profit maximized; 0% budget overruns. | Ojastro / Lead |
| **FR-05 (Analytics)** | Demonstration | Correct real-time calculation of revenue, COGS, profit; cash vs. utang separation. | Pastrana |
| **FR-06 (Synthetic Engine)**| Analysis & Test | 12-month synthetic stream exhibits payday surges; forecast benchmark $MAPE \le 20\%$. | Aseoche / Lead |
| **NFR-01 (Performance)** | Measurement | Cloud turnaround $\le 3.5\text{s}$; local UI response $\le 200\text{ms}$; knapsack solve $\le 1.0\text{s}$. | Lead |
| **NFR-02 (Usability)** | User Trial | 10-15 evaluator test trials yielding average System Usability Scale (SUS) $\ge 75$. | Aseoche |
| **NFR-03 (Offline Sync)** | Fault Injection Test | Zero transaction loss during offline disconnection; clean queue flush upon reconnect. | Aseoche |
| **NFR-04 (Optimization)** | Inspection | Images resized to $\le 1024 \times 1024$, payloads $\le 300\text{ KB}$, token bounds respected. | Lead |
| **NFR-05 (Security)** | Security Audit | Zero API keys exposed on client; TLS 1.3 enforced; append-only audit trail intact. | Lead |
| **NFR-06 (Maintainability)**| Static Code Analysis | PyTest coverage $\ge 80\%$ on core modules; clean modular directory structure. | QA Team |

---

## 5. System Evolution & Future Scope
Future iterations beyond the academic semester scope will explore:
1. Direct integration with Philippine electronic payment gateways (GCash and Maya QR Ph merchant APIs).
2. BLE (Bluetooth Low Energy) micro-thermal receipt printer pairing for customers requesting physical slips.
3. Federated edge AI models running lightweight on-device INT8 quantized vision networks to eliminate cloud API costs entirely.
