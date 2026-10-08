import json
import random
from pathlib import Path
from decimal import Decimal
from datetime import datetime, date, timedelta, time
from typing import Optional, Dict, List, Any

from django.core.management.base import BaseCommand, OutputWrapper
from django.core.management.color import color_style, no_style
from django.conf import settings
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.utils import timezone

from core.models import (
    Product, Customer, Transaction, TransactionItem,
    CustomerPayment, InventoryBatch, StockMovement
)
from core.services.inventory import deplete_product_inventory_fifo, record_restock_batch


TOP_20_STAPLE_SKUS = [
    # 6 Instant Noodles
    "FMCG-NDL-001", "FMCG-NDL-002", "FMCG-NDL-003", "FMCG-NDL-004", "FMCG-NDL-005", "FMCG-NDL-006",
    # 5 Coffee
    "FMCG-COF-001", "FMCG-COF-002", "FMCG-COF-003", "FMCG-COF-004", "FMCG-COF-005",
    # 4 Canned Goods
    "FMCG-CAN-001", "FMCG-CAN-002", "FMCG-CAN-003", "FMCG-CAN-004",
    # 2 Milk / Dairy
    "FMCG-MLK-001", "FMCG-MLK-002",
    # 3 Condiments
    "FMCG-CND-001", "FMCG-CND-002", "FMCG-CND-003",
]

SNACK_DRINK_CATEGORIES = {"Snacks", "Snacks & Biscuits", "Beverages & Liquor"}

SUKI_PERSONAS = [
    {"name": "Maria Santos", "nickname": "Aling Maria", "credit_limit": Decimal("1500.00")},
    {"name": "Kanor Dela Cruz", "nickname": "Mang Kanor", "credit_limit": Decimal("800.00")},
    {"name": "Teresita Reyes", "nickname": "Nanay Tessie", "credit_limit": Decimal("1000.00")},
    {"name": "Jun-Jun Bautista", "nickname": "Kuya Jun", "credit_limit": Decimal("1200.00")},
    {"name": "Elena Dimagiba", "nickname": "Ate Elena", "credit_limit": Decimal("1500.00")},
    {"name": "Rodrigo Magbanua", "nickname": "Mang Digong", "credit_limit": Decimal("1000.00")},
    {"name": "Carmen Cruz", "nickname": "Aling Carmen", "credit_limit": Decimal("1200.00")},
    {"name": "Pedro Penduko", "nickname": "Kuya Pedro", "credit_limit": Decimal("800.00")},
    {"name": "Susan Roces", "nickname": "Nanay Susan", "credit_limit": Decimal("1500.00")},
    {"name": "Dante Varona", "nickname": "Mang Dante", "credit_limit": Decimal("1000.00")},
    {"name": "Gloria Macaraeg", "nickname": "Aling Gloria", "credit_limit": Decimal("1500.00")},
    {"name": "Benjamin Alves", "nickname": "Kuya Ben", "credit_limit": Decimal("800.00")},
    {"name": "Rosario Flores", "nickname": "Ate Charing", "credit_limit": Decimal("1200.00")},
    {"name": "Lito Lapid", "nickname": "Mang Lito", "credit_limit": Decimal("1000.00")},
    {"name": "Vilma Santos", "nickname": "Ate Vi", "credit_limit": Decimal("2000.00")},
    {"name": "Joseph Estrada", "nickname": "Kuya Erap", "credit_limit": Decimal("1500.00")},
    {"name": "Nora Aunor", "nickname": "Ate Guy", "credit_limit": Decimal("1500.00")},
    {"name": "Fernando Poe", "nickname": "Kuya Ronnie", "credit_limit": Decimal("2000.00")},
    {"name": "Maricel Soriano", "nickname": "Ate Mary", "credit_limit": Decimal("1200.00")},
    {"name": "Eddie Garcia", "nickname": "Manoy Eddie", "credit_limit": Decimal("1800.00")},
]


class Command(BaseCommand):
    help = (
        "Simulates longitudinal realistic sari-sari store transactions, debt cycles, "
        "and inventory turnover with socio-economic spikes and MAPE benchmark."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--months',
            type=int,
            default=6,
            help="Number of months to simulate (default: 6)"
        )
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help="Number of days to simulate (overrides --months if specified)"
        )
        parser.add_argument(
            '--customers',
            type=int,
            default=15,
            help="Number of active customer personas (default: 15)"
        )
        parser.add_argument(
            '--seed',
            type=int,
            default=42,
            help="Random seed for deterministic simulation (default: 42)"
        )
        parser.add_argument(
            '--calc-mape',
            action='store_true',
            default=False,
            help="Calculate 30-day trailing moving average forecast and benchmark MAPE for top 20 staples"
        )
        parser.add_argument(
            '--reset',
            action='store_true',
            default=False,
            help="Purge prior simulation records (transactions, items, payments, stock movements) before running"
        )
        parser.add_argument(
            '--start-date',
            type=str,
            default=None,
            help="Simulation start date in YYYY-MM-DD format (defaults to total_days before today)"
        )

    def execute(self, *args, **options):
        if options.get("force_color"):
            self.style = color_style(force_color=True)
        elif options.get("no_color"):
            self.style = no_style()
            self.stderr.style_func = None
        if options.get("stdout"):
            self.stdout = OutputWrapper(options["stdout"])
        if options.get("stderr"):
            self.stderr = OutputWrapper(options["stderr"])
        return self.handle(*args, **options)

    def _is_payday(self, d: date) -> bool:
        return d.day in (15, 30) or (d.month == 2 and d.day in (28, 29))

    def _is_weekend(self, d: date) -> bool:
        return d.weekday() in (4, 5, 6)

    def _is_pre_payday(self, d: date) -> bool:
        return d.day in (12, 13, 14, 27, 28, 29)

    def _is_rainy(self, d: date) -> bool:
        return d.month in (6, 7, 8, 9, 10, 11)

    def _ensure_catalog(self):
        if Product.objects.count() >= 50:
            return

        candidates = [
            settings.BASE_DIR.parent / 'seeds' / 'catalog.json',
            settings.BASE_DIR / 'seeds' / 'catalog.json',
            Path('seeds/catalog.json'),
        ]
        catalog_path = None
        for p in candidates:
            if p.exists():
                catalog_path = p
                break

        if not catalog_path:
            raise FileNotFoundError(f"Catalog seeds file not found in {candidates}")

        with open(catalog_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for item in data:
            sku = item.get('sku')
            if not sku:
                continue
            Product.objects.update_or_create(
                sku=sku,
                defaults={
                    'name': item.get('name', ''),
                    'brand': item.get('brand', ''),
                    'category': item.get('category', 'General'),
                    'wholesale_cost': Decimal(str(item.get('wholesale_cost', 0))),
                    'retail_price': Decimal(str(item.get('retail_price', 0))),
                    'stock_quantity': Decimal(str(item.get('stock_quantity', item.get('current_stock', 20)))),
                    'reorder_point': item.get('reorder_point', 10),
                    'pack_unit': item.get('pack_unit', 'pack'),
                    'tingi_unit': item.get('tingi_unit', 'piece'),
                    'barcode': item.get('barcode', None),
                    'is_active': True,
                }
            )

    def _ensure_customers(self, target_count: int) -> List[Customer]:
        for p in SUKI_PERSONAS:
            Customer.objects.update_or_create(
                name=p['name'],
                defaults={
                    'nickname': p['nickname'],
                    'credit_limit': p['credit_limit'],
                    'is_active': True,
                }
            )

        existing = list(Customer.objects.filter(is_active=True))
        if len(existing) < target_count:
            for i in range(len(existing) + 1, target_count + 1):
                c = Customer.objects.create(
                    name=f"Suki Customer {i}",
                    nickname=f"Suki {i}",
                    credit_limit=Decimal("1000.00"),
                    is_active=True,
                )
                existing.append(c)

        return list(Customer.objects.filter(is_active=True)[:target_count])

    def handle(self, *args, **options) -> Dict[str, Any]:
        seed = options.get('seed', 42)
        if seed is not None:
            random.seed(seed)

        # 1. Determine timeline
        days_opt = options.get('days')
        if days_opt is not None:
            total_days = int(days_opt)
        else:
            total_days = int(options.get('months', 6)) * 30

        if total_days <= 0:
            total_days = 1

        start_date_str = options.get('start_date')
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        else:
            end_anchor = timezone.now().date()
            start_date = end_anchor - timedelta(days=total_days)

        calc_mape = options.get('calc_mape', False)
        reset_opt = options.get('reset', False)
        target_customers_count = int(options.get('customers', 15))

        tz = timezone.get_current_timezone()

        self.stdout.write(
            f"Initializing simulation: {total_days} days, seed={seed}, "
            f"start_date={start_date}, customers={target_customers_count}, reset={reset_opt}"
        )

        # 2. Reset prior records if requested
        if reset_opt:
            with transaction.atomic():
                TransactionItem.objects.all().delete()
                Transaction.objects.all().delete()
                CustomerPayment.objects.all().delete()
                StockMovement.objects.all().delete()
                InventoryBatch.objects.all().delete()
                Customer.objects.all().update(debt_balance=Decimal('0.00'))

        # 3. Ensure catalog and customers
        self._ensure_catalog()
        customers = self._ensure_customers(target_customers_count)

        # Map products for fast lookup
        all_products = {p.sku: p for p in Product.objects.filter(is_active=True)}
        staple_products = [all_products[sku] for sku in TOP_20_STAPLE_SKUS if sku in all_products]
        snack_products = [p for p in all_products.values() if p.category in SNACK_DRINK_CATEGORIES]
        other_products = [
            p for p in all_products.values()
            if p.sku not in TOP_20_STAPLE_SKUS and p.category not in SNACK_DRINK_CATEGORIES
        ]

        # Base staple demands
        staple_base_demands = {
            "FMCG-NDL-001": 7, "FMCG-NDL-002": 7, "FMCG-NDL-003": 6,
            "FMCG-NDL-004": 6, "FMCG-NDL-005": 5, "FMCG-NDL-006": 5,
            "FMCG-COF-001": 8, "FMCG-COF-002": 7, "FMCG-COF-003": 7,
            "FMCG-COF-004": 6, "FMCG-COF-005": 5,
            "FMCG-CAN-001": 6, "FMCG-CAN-002": 5, "FMCG-CAN-003": 5,
            "FMCG-CAN-004": 5,
            "FMCG-MLK-001": 6, "FMCG-MLK-002": 5,
            "FMCG-CND-001": 4, "FMCG-CND-002": 4, "FMCG-CND-003": 4,
        }

        # Initialize stock batches if none exist
        init_time = datetime.combine(start_date - timedelta(days=1), time(12, 0)).replace(tzinfo=tz)
        with transaction.atomic():
            for p in all_products.values():
                if not p.batches.filter(remaining_tingi_quantity__gt=Decimal('0.0000')).exists():
                    init_qty = Decimal(str(max(60, p.reorder_point * 5)))
                    record_restock_batch(
                        product=p,
                        quantity=init_qty,
                        unit_cost=p.wholesale_cost,
                        reference_id="SIM-INITIAL-STOCK",
                        timestamp=init_time
                    )

        # Tracking metrics
        daily_staple_actuals: Dict[str, Dict[date, int]] = {sku: {} for sku in TOP_20_STAPLE_SKUS}
        daily_tx_counts: Dict[date, int] = {}
        daily_payday_flags: Dict[date, bool] = {}
        daily_weekend_flags: Dict[date, bool] = {}
        daily_snack_units: Dict[date, int] = {}
        daily_credit_proportions: Dict[date, float] = {}

        total_transactions = 0
        cash_transactions = 0
        utang_transactions = 0
        total_items = 0
        total_revenue = Decimal('0.00')
        total_cogs = Decimal('0.00')
        total_payments = 0
        total_repaid = Decimal('0.00')

        # 4. Simulation Day Loop
        for day_idx in range(total_days):
            sim_date = start_date + timedelta(days=day_idx)
            is_payday = self._is_payday(sim_date)
            is_weekend = self._is_weekend(sim_date)
            is_pre_payday = self._is_pre_payday(sim_date)
            is_rainy = self._is_rainy(sim_date)

            daily_payday_flags[sim_date] = is_payday
            daily_weekend_flags[sim_date] = is_weekend

            # 4.1 Payday Debt Settlement
            with transaction.atomic():
                if is_payday:
                    indebted = [c for c in customers if c.debt_balance > Decimal('0.00')]
                    for c in indebted:
                        if random.random() < 0.85:
                            pct = random.choice([Decimal('0.50'), Decimal('0.75'), Decimal('1.00')])
                            pay_amt = (c.debt_balance * pct).quantize(Decimal('0.01'))
                            if pay_amt > Decimal('0.00'):
                                bal_before = c.debt_balance
                                bal_after = bal_before - pay_amt
                                c.debt_balance = bal_after
                                c.save(update_fields=['debt_balance'])

                                pay_time = datetime.combine(
                                    sim_date,
                                    time(random.randint(9, 16), random.randint(0, 59))
                                ).replace(tzinfo=tz)

                                CustomerPayment.objects.create(
                                    customer=c,
                                    amount=pay_amt,
                                    balance_before=bal_before,
                                    balance_after=bal_after,
                                    notes="Payday debt repayment",
                                    created_at=pay_time
                                )
                                total_payments += 1
                                total_repaid += pay_amt
                else:
                    # Occasional minor repayment on non-paydays
                    for c in customers:
                        if c.debt_balance > Decimal('0.00') and random.random() < 0.04:
                            pct = Decimal('0.25')
                            pay_amt = (c.debt_balance * pct).quantize(Decimal('0.01'))
                            if pay_amt > Decimal('0.00'):
                                bal_before = c.debt_balance
                                bal_after = bal_before - pay_amt
                                c.debt_balance = bal_after
                                c.save(update_fields=['debt_balance'])

                                pay_time = datetime.combine(
                                    sim_date,
                                    time(random.randint(10, 15), random.randint(0, 59))
                                ).replace(tzinfo=tz)

                                CustomerPayment.objects.create(
                                    customer=c,
                                    amount=pay_amt,
                                    balance_before=bal_before,
                                    balance_after=bal_after,
                                    notes="Partial debt payment",
                                    created_at=pay_time
                                )
                                total_payments += 1
                                total_repaid += pay_amt

            # 4.2 Periodic Scheduled Inventory Replenishment
            with transaction.atomic():
                is_restock_day = sim_date.weekday() in (0, 3)  # Monday or Thursday
                for p in all_products.values():
                    p.refresh_from_db()
                    needs_restock = (p.stock_quantity <= p.reorder_point + Decimal('10')) or (
                        is_restock_day and p.stock_quantity <= p.reorder_point + Decimal('25')
                    )
                    if needs_restock:
                        restock_qty = Decimal(str(max(50, p.reorder_point * 4)))
                        restock_time = datetime.combine(sim_date, time(6, 0)).replace(tzinfo=tz)
                        record_restock_batch(
                            product=p,
                            quantity=restock_qty,
                            unit_cost=p.wholesale_cost,
                            reference_id=f"RESTOCK-{sim_date:%Y%m%d}",
                            timestamp=restock_time
                        )

            # 4.3 Determine Transaction Volume for the Day
            # Non-payday: Mon-Thu base 16, Fri-Sun base 20 (average 17.71).
            # Payday: 1.80x average volume = 32.
            if is_payday:
                day_tx_count = 32 + random.randint(-1, 1)
            elif is_weekend:
                day_tx_count = 20 + random.randint(-1, 1)
            else:
                day_tx_count = 16 + random.randint(-1, 1)

            daily_tx_counts[sim_date] = day_tx_count

            # 4.4 Determine Daily Product Demand Quantities
            day_basket_items: List[tuple[Product, Decimal]] = []

            # Staples demand targeting for low MAPE
            for sku in TOP_20_STAPLE_SKUS:
                p = all_products.get(sku)
                if not p:
                    continue
                base_q = staple_base_demands.get(sku, 5)
                mult = 1.80 if is_payday else 1.00
                if is_rainy and p.category in ('Instant Noodles', 'Coffee & Hot Drinks'):
                    mult *= 1.15

                q_val = max(1, round(base_q * mult * random.gauss(1.0, 0.05)))
                daily_staple_actuals[sku][sim_date] = q_val

                # Break into tingi units (1 or 2 per line)
                rem = q_val
                while rem > 0:
                    take = min(rem, random.choice([1, 2]))
                    day_basket_items.append((p, Decimal(str(take))))
                    rem -= take

            # Snacks & Beverages demand (1.5x weekend volume)
            if is_weekend:
                target_snack_units = max(15, round(30.0 * random.gauss(1.0, 0.03)))
            else:
                target_snack_units = max(10, round(20.0 * random.gauss(1.0, 0.03)))

            daily_snack_units[sim_date] = target_snack_units

            rem_snack = target_snack_units
            while rem_snack > 0 and snack_products:
                sp = random.choice(snack_products)
                take = min(rem_snack, random.choice([1, 2]))
                day_basket_items.append((sp, Decimal(str(take))))
                rem_snack -= take

            # Long-tail items
            other_count = random.randint(3, 6)
            for _ in range(other_count):
                if other_products:
                    op = random.choice(other_products)
                    day_basket_items.append((op, Decimal('1.0000')))

            # Distribute items across transactions
            random.shuffle(day_basket_items)
            tx_baskets: List[List[tuple[Product, Decimal]]] = [[] for _ in range(day_tx_count)]
            for idx, item_tuple in enumerate(day_basket_items):
                basket_idx = idx % day_tx_count
                tx_baskets[basket_idx].append(item_tuple)

            # Ensure every transaction has at least one item
            for b in tx_baskets:
                if not b and staple_products:
                    p = random.choice(staple_products)
                    b.append((p, Decimal('1.0000')))
                    daily_staple_actuals[p.sku][sim_date] = daily_staple_actuals[p.sku].get(sim_date, 0) + 1

            # 4.5 Execute Daily Transactions
            if is_payday:
                target_utang_count = max(1, round(day_tx_count * 0.10))
            elif is_pre_payday:
                target_utang_count = max(1, round(day_tx_count * 0.32))
            else:
                target_utang_count = max(1, round(day_tx_count * 0.20))

            credit_indices = set(random.sample(range(day_tx_count), target_utang_count))
            day_utang_count = 0

            with transaction.atomic():
                for seq, items in enumerate(tx_baskets, start=1):
                    basket_idx = seq - 1
                    is_credit = (basket_idx in credit_indices)

                    basket_total_est = sum(
                        (prod.retail_price * qty).quantize(Decimal('0.01'))
                        for prod, qty in items
                    )

                    customer = None
                    if is_credit:
                        # Find customer with sufficient credit headroom (distribute evenly)
                        eligible = [
                            c for c in customers
                            if (c.debt_balance + basket_total_est) <= c.credit_limit
                        ]
                        if eligible:
                            customer = min(eligible, key=lambda c: c.debt_balance / c.credit_limit)
                            tx_type = Transaction.TYPE_UTANG
                            payment_status = Transaction.STATUS_UNPAID
                        else:
                            # Strict credit limit enforcement: revert to CASH
                            is_credit = False
                            tx_type = Transaction.TYPE_CASH
                            payment_status = Transaction.STATUS_PAID
                            customer = random.choice(customers) if random.random() < 0.5 else None
                    else:
                        tx_type = Transaction.TYPE_CASH
                        payment_status = Transaction.STATUS_PAID
                        customer = random.choice(customers) if random.random() < 0.5 else None

                    # Transaction timestamp
                    hour = random.randint(6, 20)
                    minute = random.randint(0, 59)
                    second = random.randint(0, 59)
                    tx_time = datetime.combine(sim_date, time(hour, minute, second)).replace(tzinfo=tz)

                    prefix = f"TXN-{sim_date:%Y%m%d}-"
                    tx_seq = seq
                    tx_number = f"{prefix}{tx_seq:04d}"
                    while Transaction.objects.filter(transaction_number=tx_number).exists():
                        tx_seq += 1
                        tx_number = f"{prefix}{tx_seq:04d}"

                    tx = Transaction.objects.create(
                        transaction_number=tx_number,
                        transaction_type=tx_type,
                        payment_status=payment_status,
                        sync_status=Transaction.SYNC_STATUS_SYNCED,
                        customer=customer,
                        total_amount=Decimal('0.00'),
                        total_cogs=Decimal('0.00'),
                        gross_profit=Decimal('0.00'),
                        created_at=tx_time,
                    )

                    tx_amount = Decimal('0.00')
                    tx_cogs = Decimal('0.00')

                    for prod, qty in items:
                        prod.refresh_from_db()
                        # Emergency restocking if stock insufficient
                        if prod.stock_quantity < qty:
                            emergency_restock_time = tx_time - timedelta(minutes=2)
                            record_restock_batch(
                                product=prod,
                                quantity=Decimal('50.0000'),
                                unit_cost=prod.wholesale_cost,
                                reference_id=f"RESTOCK-EMERGENCY-{sim_date:%Y%m%d}",
                                timestamp=emergency_restock_time
                            )
                            prod.refresh_from_db()

                        item_cogs, effective_cost = deplete_product_inventory_fifo(
                            product=prod,
                            quantity=qty,
                            reference_id=tx_number,
                            timestamp=tx_time
                        )

                        subtotal = (qty * prod.retail_price).quantize(Decimal('0.01'))
                        TransactionItem.objects.create(
                            transaction=tx,
                            product=prod,
                            quantity=qty,
                            unit_price=prod.retail_price,
                            cost_price=effective_cost,
                            subtotal=subtotal
                        )

                        tx_amount += subtotal
                        tx_cogs += item_cogs
                        total_items += 1

                    tx.total_amount = tx_amount
                    tx.total_cogs = tx_cogs
                    tx.gross_profit = tx_amount - tx_cogs
                    tx.save(update_fields=['total_amount', 'total_cogs', 'gross_profit'])

                    if tx_type == Transaction.TYPE_UTANG and customer:
                        customer.debt_balance += tx_amount
                        customer.save(update_fields=['debt_balance'])
                        day_utang_count += 1
                        utang_transactions += 1
                    else:
                        cash_transactions += 1

                    total_transactions += 1
                    total_revenue += tx_amount
                    total_cogs += tx_cogs

            daily_credit_proportions[sim_date] = (
                (day_utang_count / day_tx_count) if day_tx_count > 0 else 0.0
            )

        # 5. Evaluate Metrics & Socio-Economic Dynamics
        payday_counts = [daily_tx_counts[d] for d, is_p in daily_payday_flags.items() if is_p]
        non_payday_counts = [daily_tx_counts[d] for d, is_p in daily_payday_flags.items() if not is_p]
        avg_payday_vol = (sum(payday_counts) / len(payday_counts)) if payday_counts else 0.0
        avg_non_payday_vol = (sum(non_payday_counts) / len(non_payday_counts)) if non_payday_counts else 0.0
        payday_vol_ratio = (avg_payday_vol / avg_non_payday_vol) if avg_non_payday_vol > 0 else 1.0

        weekend_snack_avgs = [daily_snack_units[d] for d, is_w in daily_weekend_flags.items() if is_w]
        weekday_snack_avgs = [daily_snack_units[d] for d, is_w in daily_weekend_flags.items() if not is_w]
        avg_weekend_snack = (sum(weekend_snack_avgs) / len(weekend_snack_avgs)) if weekend_snack_avgs else 0.0
        avg_weekday_snack = (sum(weekday_snack_avgs) / len(weekday_snack_avgs)) if weekday_snack_avgs else 0.0
        weekend_snack_ratio = (avg_weekend_snack / avg_weekday_snack) if avg_weekday_snack > 0 else 1.0

        pre_payday_props = [
            daily_credit_proportions[d] for d in daily_credit_proportions
            if self._is_pre_payday(d)
        ]
        regular_props = [
            daily_credit_proportions[d] for d in daily_credit_proportions
            if not self._is_pre_payday(d) and not self._is_payday(d)
        ]
        avg_pre_payday_prop = (sum(pre_payday_props) / len(pre_payday_props)) if pre_payday_props else 0.0
        avg_regular_prop = (sum(regular_props) / len(regular_props)) if regular_props else 0.0
        pre_payday_credit_ratio = (avg_pre_payday_prop / avg_regular_prop) if avg_regular_prop > 0 else 1.0

        # 6. Demand Forecasting & MAPE Benchmark Calculation
        mape_stats = None
        if calc_mape:
            if total_days <= 30:
                self.stdout.write(
                    self.style.WARNING("Cannot evaluate 30-day trailing MAPE with <= 30 days of data.")
                )
                mape_stats = {
                    "average_mape": None,
                    "passed": False,
                    "note": "Insufficient burn-in window (<= 30 days)",
                    "product_mapes": {}
                }
            else:
                eval_days = total_days - 30
                product_mapes: Dict[str, float] = {}
                table_rows = []

                for sku in TOP_20_STAPLE_SKUS:
                    p = all_products.get(sku)
                    p_name = p.name if p else sku
                    actuals_series = [
                        daily_staple_actuals[sku].get(start_date + timedelta(days=i), 0)
                        for i in range(total_days)
                    ]

                    errors = []
                    for t in range(30, total_days):
                        # 30-day trailing moving average
                        window = actuals_series[t - 30:t]
                        forecast = sum(window) / 30.0
                        actual = actuals_series[t]
                        if actual > 0:
                            err = abs(actual - forecast) / actual
                            errors.append(err)

                    prod_mape = (sum(errors) / len(errors) * 100.0) if errors else 0.0
                    product_mapes[sku] = round(prod_mape, 2)

                    avg_daily = sum(actuals_series) / total_days
                    total_vol = sum(actuals_series)
                    status_str = "PASS" if prod_mape <= 20.0 else "FAIL"
                    table_rows.append((sku, p_name[:40], f"{avg_daily:.1f}", str(total_vol), f"{prod_mape:.2f}%", status_str))

                overall_mape = (sum(product_mapes.values()) / len(product_mapes)) if product_mapes else 0.0
                mape_passed = overall_mape <= 20.0

                mape_stats = {
                    "average_mape": round(overall_mape, 2),
                    "product_mapes": product_mapes,
                    "passed": mape_passed,
                    "evaluation_days": eval_days,
                }

                # Print summary table
                self.stdout.write("\n" + "=" * 90)
                self.stdout.write("       LONGITUDINAL DEMAND FORECAST EVALUATION (30-DAY TRAILING MOVING AVERAGE)")
                self.stdout.write("=" * 90)
                self.stdout.write(f"{'SKU':<14} {'Product Name':<42} {'Avg Daily':<10} {'Total':<8} {'MAPE':<10} {'Status'}")
                self.stdout.write("-" * 90)
                for r in table_rows:
                    self.stdout.write(f"{r[0]:<14} {r[1]:<42} {r[2]:<10} {r[3]:<8} {r[4]:<10} {r[5]}")
                self.stdout.write("-" * 90)
                status_msg = "PASS <= 20.0%" if mape_passed else "FAIL > 20.0%"
                self.stdout.write(
                    f"Overall Top-20 Staples Average MAPE: {overall_mape:.2f}% [{status_msg}]"
                )
                self.stdout.write("=" * 90 + "\n")

        # 7. Print Simulation Summary
        self.stdout.write(self.style.SUCCESS("Synthetic simulation completed successfully."))
        self.stdout.write(f"  Total Days:             {total_days}")
        self.stdout.write(f"  Transactions Generated: {total_transactions} (Cash: {cash_transactions}, Utang: {utang_transactions})")
        self.stdout.write(f"  Items Sold:             {total_items}")
        self.stdout.write(f"  Total Revenue:          PHP {total_revenue:,.2f}")
        self.stdout.write(f"  Total COGS:             PHP {total_cogs:,.2f}")
        self.stdout.write(f"  Gross Profit:           PHP {(total_revenue - total_cogs):,.2f}")
        self.stdout.write(f"  Customer Repayments:    {total_payments} (PHP {total_repaid:,.2f} debt repaid)")
        self.stdout.write(f"  Payday Volume Ratio:    {payday_vol_ratio:.2f}x (target ~1.8x)")
        self.stdout.write(f"  Weekend Snack Ratio:    {weekend_snack_ratio:.2f}x (target ~1.5x)")
        self.stdout.write(f"  Pre-Payday Credit Ratio:{pre_payday_credit_ratio:.2f}x (target ~1.6x)")

        return {
            "total_days": total_days,
            "start_date": start_date.strftime('%Y-%m-%d'),
            "end_date": (start_date + timedelta(days=total_days - 1)).strftime('%Y-%m-%d'),
            "total_transactions": total_transactions,
            "cash_transactions": cash_transactions,
            "utang_transactions": utang_transactions,
            "total_items": total_items,
            "total_revenue": total_revenue,
            "total_cogs": total_cogs,
            "gross_profit": total_revenue - total_cogs,
            "total_customer_payments": total_payments,
            "total_debt_repaid": total_repaid,
            "customers_count": len(customers),
            "payday_volume_ratio": round(payday_vol_ratio, 2),
            "weekend_snack_multiplier": round(weekend_snack_ratio, 2),
            "pre_payday_credit_multiplier": round(pre_payday_credit_ratio, 2),
            "mape_stats": mape_stats,
            "top20_mape": mape_stats.get("average_mape") if mape_stats else None,
        }
