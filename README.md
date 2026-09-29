# TindAI: Inventory, Point-of-Sale, and Procurement Optimization System

Course: CCSFEN1L (Introduction to Software Engineering) | Section: COM245 | Group: GrouPals  
Project Title: TindAI: An AI-Powered Inventory, Sales Logging, and Capital-Constrained Restocking System for Sari-Sari Stores  
Stack: Django 5 (Python 3.12) + HTMX + Tailwind CSS + SQLite + Google Gemini VLM/OCR + PuLP Knapsack Optimizer.

---

## Quickstart (Single Server)

TindAI runs as a single-stack Python application. Zero Node.js or npm dependencies required.

```powershell
# 1. Create and activate Python virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Apply database migrations and seed realistic store catalog
python backend/manage.py migrate
python backend/manage.py seed_catalog

# 4. Start application server
python backend/manage.py runserver
```

- Mobile Web Application: `http://127.0.0.1:8000/`
- Django Admin Portal: `http://127.0.0.1:8000/admin/`
- REST API Documentation: `http://127.0.0.1:8000/api/docs`

---

## Mobile Application Screens

1. **Benta (Counter POS)**: Camera snapshot button, quick-add tingi buttons (loose eggs, ice, candies), cart quantity steppers, and Cash vs Utang settlement routing.
2. **Tira (Stocks & Inventory)**: Real-time inventory levels, low-stock warnings when `stock <= reorder_point`, and wholesale receipt OCR scanner.
3. **Lista ng Utang (Credit Ledger)**: Debtor directory, total store receivables summary, cash payment recording modal, and polite Taglish SMS payment reminder generator.
4. **Bili (Restock AI)**: Revolving capital budget input (₱3,000 to ₱8,000) running bounded knapsack procurement optimization, outputting an aisle-by-aisle shopping checklist with browser print support.

---

## Repository Directory Layout

```
TindAI/
├── backend/
│   ├── config/                     # Django project settings and URL routing
│   ├── core/
│   │   ├── models.py               # Product, Customer, Transaction, RestockRun
│   │   ├── views.py                # Mobile views and HTMX action endpoints
│   │   ├── api.py                  # Django Ninja REST API endpoints
│   │   ├── admin.py                # Django Admin configurations
│   │   └── management/commands/    # Database seeding command
│   ├── templates/                  # Mobile-first HTML templates (Tailwind + HTMX)
│   │   ├── base.html               # 430px mobile frame and bottom navigation
│   │   ├── pos.html                # Benta checkout interface
│   │   ├── inventory.html          # Tira stock monitoring interface
│   │   ├── utang.html              # Customer debt ledger interface
│   │   ├── restock.html            # Smart replenishment checklist
│   │   └── partials/               # HTMX dynamic component partials
│   ├── tests/                      # Automated test suite
│   │   ├── test_api.py             # Ninja REST API endpoint tests
│   │   └── test_views.py           # Mobile view and checkout workflow tests
│   ├── requirements.txt            # Python dependencies
│   ├── pytest.ini
│   └── manage.py
├── seeds/
│   └── catalog.json                # 50 verified Philippine FMCG retail products
├── docs/                           # Software Requirements Specifications (SRS)
├── tests/                          # Quality assurance matrices
├── .github/
│   └── ISSUE_TEMPLATE/             # Standard task ticket template
├── .gitignore
└── README.md
```

---

## Running Automated Tests

Run the test suite to verify models, transactions, debt liquidation, and views:

```powershell
python -m pytest backend/tests/
```
