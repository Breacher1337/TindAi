import json
from decimal import Decimal
from pathlib import Path
import pytest
from django.conf import settings
from django.test import Client
from core.models import Product, Customer, CustomerPayment, Transaction, TransactionItem


@pytest.fixture
def api_client():
    """Django test client for API and view testing."""
    return Client()


@pytest.fixture
def fmcg_catalog_50(db):
    """Loads all 50 authentic FMCG products from seeds/catalog.json into test database."""
    candidates = [
        settings.BASE_DIR.parent / 'seeds' / 'catalog.json',
        settings.BASE_DIR / 'seeds' / 'catalog.json',
        Path('seeds/catalog.json'),
    ]
    catalog_path = next((p for p in candidates if p.exists()), None)
    if not catalog_path:
        raise FileNotFoundError(f"seeds/catalog.json not found in candidates: {candidates}")

    with open(catalog_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    products = []
    for item in data:
        sku = item.get('sku')
        if not sku:
            continue
        p = Product.objects.create(
            sku=sku,
            name=item.get('name', ''),
            brand=item.get('brand', ''),
            category=item.get('category', 'General'),
            wholesale_cost=Decimal(str(item.get('wholesale_cost', 0))),
            retail_price=Decimal(str(item.get('retail_price', 0))),
            stock_quantity=item.get('stock_quantity', 20),
            reorder_point=item.get('reorder_point', 10),
            pack_unit=item.get('pack_unit', 'pack'),
            tingi_unit=item.get('tingi_unit', 'piece'),
            barcode=item.get('barcode', None),
            is_active=True,
        )
        products.append(p)

    return products


@pytest.fixture
def mock_products_20(db):
    """
    Curated 20 items across 6 FMCG categories with explicit wholesale pack costs,
    retail tingi prices, stock levels, and reorder points for the ₱5,000 Knapsack benchmark.
    """
    definitions = [
        # Instant Noodles
        ("KNAP-NDL-001", "Lucky Me Pancit Canton Kalamansi", "Lucky Me!", "Instant Noodles", "12.50", "15.00", 5, 20, "box (72s)", "piece"),
        ("KNAP-NDL-002", "Lucky Me Pancit Canton Chilimansi", "Lucky Me!", "Instant Noodles", "12.50", "15.00", 8, 20, "box (72s)", "piece"),
        ("KNAP-NDL-003", "Payless Pancit Canton Extra Big", "Payless", "Instant Noodles", "14.00", "17.00", 4, 15, "box (48s)", "piece"),
        ("KNAP-NDL-004", "Nissin Cup Noodles Seafood", "Nissin", "Instant Noodles", "25.00", "30.00", 3, 12, "box (24s)", "cup"),
        # Coffee & Hot Drinks
        ("KNAP-COF-001", "Kopiko Blanca 3in1 30g", "Kopiko", "Coffee & Hot Drinks", "10.00", "12.50", 6, 25, "bag (30s)", "sachet"),
        ("KNAP-COF-002", "Great Taste White 3in1 30g", "Great Taste", "Coffee & Hot Drinks", "9.50", "12.00", 5, 25, "bag (30s)", "sachet"),
        ("KNAP-COF-003", "Nescafe Classic Twin Pack 56g", "Nescafe", "Coffee & Hot Drinks", "13.50", "16.00", 7, 20, "bundle (20s)", "twin pack"),
        ("KNAP-COF-004", "Milo Chocolate Malt Drink 24g", "Milo", "Coffee & Hot Drinks", "11.00", "14.00", 4, 20, "bundle (24s)", "sachet"),
        # Dairy & Milk
        ("KNAP-MLK-001", "Bear Brand Fortified Powder 33g", "Bear Brand", "Dairy & Milk", "13.00", "16.00", 8, 25, "pack (32s)", "sachet"),
        ("KNAP-MLK-002", "Alaska Evaporada 370ml", "Alaska", "Dairy & Milk", "28.00", "34.00", 4, 12, "case (48s)", "can"),
        ("KNAP-MLK-003", "Birch Tree Full Cream 33g", "Birch Tree", "Dairy & Milk", "12.50", "15.50", 3, 15, "pack (32s)", "sachet"),
        # Canned Goods
        ("KNAP-CAN-001", "555 Sardines in Tomato Sauce 155g", "555", "Canned Goods", "20.00", "24.00", 5, 20, "case (50s)", "can"),
        ("KNAP-CAN-002", "Mega Sardines Red 155g", "Mega", "Canned Goods", "21.00", "25.00", 6, 20, "case (50s)", "can"),
        ("KNAP-CAN-003", "Argentina Corned Beef 150g", "Argentina", "Canned Goods", "35.00", "42.00", 4, 15, "case (48s)", "can"),
        ("KNAP-CAN-004", "CDO Meat Loaf 150g", "CDO", "Canned Goods", "22.00", "27.00", 5, 15, "case (48s)", "can"),
        # Condiments & Cooking
        ("KNAP-CND-001", "Silver Swan Soy Sauce 385ml", "Silver Swan", "Condiments", "18.00", "22.00", 6, 15, "box (24s)", "bottle"),
        ("KNAP-CND-002", "Datu Puti White Vinegar 385ml", "Datu Puti", "Condiments", "17.00", "21.00", 5, 15, "box (24s)", "bottle"),
        ("KNAP-CND-003", "Golden Fiesta Cooking Oil 250ml", "Golden Fiesta", "Condiments", "25.00", "30.00", 4, 12, "pouch (24s)", "pouch"),
        # Snacks & Personal Care
        ("KNAP-SNK-001", "Piattos Cheese 40g", "Jack n Jill", "Snacks", "15.00", "18.00", 6, 18, "pack (20s)", "bag"),
        ("KNAP-SNK-002", "Safeguard Pure White Soap 60g", "Safeguard", "Personal Care", "22.00", "26.00", 3, 12, "box (36s)", "bar"),
    ]

    products = []
    for sku, name, brand, category, cost, price, stock, rop, pack_unit, tingi_unit in definitions:
        p = Product.objects.create(
            sku=sku,
            name=name,
            brand=brand,
            category=category,
            wholesale_cost=Decimal(cost),
            retail_price=Decimal(price),
            stock_quantity=stock,
            reorder_point=rop,
            pack_unit=pack_unit,
            tingi_unit=tingi_unit,
            is_active=True,
        )
        products.append(p)
    return products


@pytest.fixture
def suki_customers(db):
    """Standard customer profiles with varied credit limits and debt balances."""
    customers = {
        'maria': Customer.objects.create(
            name='Maria Santos',
            nickname='Aling Maria',
            phone='09171234567',
            address='Blk 12 Lot 4, Riverside',
            debt_balance=Decimal("345.50"),
            credit_limit=Decimal("1500.00")
        ),
        'kanor': Customer.objects.create(
            name='Kanor Dela Cruz',
            nickname='Mang Kanor',
            phone='09189876543',
            address='House #22, Purok 3',
            debt_balance=Decimal("180.00"),
            credit_limit=Decimal("800.00")
        ),
        'teresita': Customer.objects.create(
            name='Teresita Reyes',
            nickname='Nanay Tessie',
            phone='09221112233',
            address='Zone 1, Crossing',
            debt_balance=Decimal("0.00"),
            credit_limit=Decimal("1000.00")
        ),
        'junjun': Customer.objects.create(
            name='Jun-Jun Bautista',
            nickname='Jun',
            phone='09334445566',
            address='Brgy. Sto. Nino',
            debt_balance=Decimal("520.00"),
            credit_limit=Decimal("1200.00")
        ),
        'carding': Customer.objects.create(
            name='Ricardo Carding Ramos',
            nickname='Tito Carding',
            phone='09195556677',
            address='Purok 5',
            debt_balance=Decimal("450.00"),
            credit_limit=Decimal("500.00")
        ),
        'nena': Customer.objects.create(
            name='Elena Nena Roxas',
            nickname='Aling Nena',
            phone='09207778899',
            address='Tabing Ilog',
            debt_balance=Decimal("0.00"),
            credit_limit=Decimal("1000.00")
        ),
    }
    return customers


@pytest.fixture
def mixed_sales_day(db, suki_customers):
    """
    Seeds a realistic business sales day with Cash and Utang transactions,
    line items with known cost prices for COGS, and customer repayments.

    Totals:
      Cash Sales: ₱1,200.00 (COGS: ₱900.00)
      Utang Sales: ₱400.00 (COGS: ₱300.00)
      Gross Revenue: ₱1,600.00
      Total COGS: ₱1,200.00
      Net Profit: ₱400.00 (25.0% margin)
      Customer Repayments: ₱150.00 cash
      Physical Cash-on-Hand: ₱1,200.00 + ₱150.00 = ₱1,350.00
      Uncollected Utang: Aling Nena owes ₱400.00 - ₱150.00 = ₱250.00 (+ other customers)
    """
    prod_a = Product.objects.create(
        sku="SALE-PROD-A",
        name="Pancit Canton Standard",
        category="Instant Noodles",
        wholesale_cost=Decimal("10.00"),
        retail_price=Decimal("15.00"),
        stock_quantity=100,
        reorder_point=20,
    )
    prod_b = Product.objects.create(
        sku="SALE-PROD-B",
        name="Coffee 3in1 Standard",
        category="Coffee & Hot Drinks",
        wholesale_cost=Decimal("20.00"),
        retail_price=Decimal("25.00"),
        stock_quantity=100,
        reorder_point=20,
    )
    prod_c = Product.objects.create(
        sku="SALE-PROD-C",
        name="Canned Meat Standard",
        category="Canned Goods",
        wholesale_cost=Decimal("40.00"),
        retail_price=Decimal("50.00"),
        stock_quantity=100,
        reorder_point=20,
    )

    # 1. Cash Tx 1: 20x Prod A (₱300, cost ₱200) + 10x Prod B (₱250, cost ₱200) = ₱550
    tx_cash_1 = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("550.00"),
        payment_status=Transaction.STATUS_PAID,
    )
    TransactionItem.objects.create(
        transaction=tx_cash_1, product=prod_a, quantity=20,
        unit_price=Decimal("15.00"), subtotal=Decimal("300.00")
    )
    TransactionItem.objects.create(
        transaction=tx_cash_1, product=prod_b, quantity=10,
        unit_price=Decimal("25.00"), subtotal=Decimal("250.00")
    )

    # 2. Cash Tx 2: 10x Prod A (₱150, cost ₱100) + 10x Prod C (₱500, cost ₱400) = ₱650
    tx_cash_2 = Transaction.objects.create(
        transaction_type=Transaction.TYPE_CASH,
        total_amount=Decimal("650.00"),
        payment_status=Transaction.STATUS_PAID,
    )
    TransactionItem.objects.create(
        transaction=tx_cash_2, product=prod_a, quantity=10,
        unit_price=Decimal("15.00"), subtotal=Decimal("150.00")
    )
    TransactionItem.objects.create(
        transaction=tx_cash_2, product=prod_c, quantity=10,
        unit_price=Decimal("50.00"), subtotal=Decimal("500.00")
    )

    # 3. Utang Tx: Aling Nena buys 10x Prod A (₱150, cost ₱100) + 10x Prod B (₱250, cost ₱200) = ₱400
    nena = suki_customers['nena']
    nena.debt_balance += Decimal("400.00")
    nena.save(update_fields=['debt_balance'])

    tx_utang = Transaction.objects.create(
        transaction_type=Transaction.TYPE_UTANG,
        customer=nena,
        total_amount=Decimal("400.00"),
        payment_status=Transaction.STATUS_UNPAID,
    )
    TransactionItem.objects.create(
        transaction=tx_utang, product=prod_a, quantity=10,
        unit_price=Decimal("15.00"), subtotal=Decimal("150.00")
    )
    TransactionItem.objects.create(
        transaction=tx_utang, product=prod_b, quantity=10,
        unit_price=Decimal("25.00"), subtotal=Decimal("250.00")
    )

    # 4. Customer Repayment: Aling Nena pays ₱150.00 cash towards her debt
    payment = CustomerPayment.objects.create(
        customer=nena,
        amount=Decimal("150.00"),
        notes="Partial debt payment",
    )
    nena.debt_balance -= Decimal("150.00")
    nena.save(update_fields=['debt_balance'])

    return {
        'products': [prod_a, prod_b, prod_c],
        'customer': nena,
        'cash_transactions': [tx_cash_1, tx_cash_2],
        'utang_transactions': [tx_utang],
        'payments': [payment],
        'expected_cash_sales': Decimal("1200.00"),
        'expected_utang_sales': Decimal("400.00"),
        'expected_gross_revenue': Decimal("1600.00"),
        'expected_cogs': Decimal("1200.00"),
        'expected_net_profit': Decimal("400.00"),
        'expected_profit_margin_pct': 25.0,
        'expected_repayments': Decimal("150.00"),
        'expected_cash_on_hand': Decimal("1350.00"),
        'expected_nena_debt': Decimal("250.00"),
    }
