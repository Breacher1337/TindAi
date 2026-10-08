from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional
from django.db.models import Q, Sum
from django.utils import timezone
from core.models import Customer, CustomerPayment, Product, Transaction, TransactionItem

TWO_PLACES = Decimal("0.01")


def get_financial_analytics(period: str = "all") -> Dict[str, Any]:
    """
    Calculate real-time financial analytics with strict isolation between
    physical cash-on-hand (drawer liquidity) and uncollected credit (utang receivables).

    Args:
        period: Time window filter ('today', 'week', 'month', 'all').

    Returns:
        dict matching PROJECT.md § core.services.analytics:
            - gross_revenue: Decimal (Cash sales + Utang sales)
            - cogs: Decimal (Sum of item qty * cost_price or wholesale_cost)
            - net_profit: Decimal (gross_revenue - cogs)
            - profit_margin_pct: float ((net_profit / gross_revenue) * 100 or 0.0)
            - cash_on_hand: Decimal (Cash sales + customer debt repayments)
            - uncollected_utang: Decimal (Outstanding balance of active customers)
            - cash_sales_total: Decimal
            - utang_sales_total: Decimal
            - repayments_total: Decimal
            - total_transactions_count: int
            - period: str
    """
    period_key = (period or "all").strip().lower()
    now = timezone.now()

    tx_filter = Q()
    payment_filter = Q()

    if period_key == "today":
        today_date = timezone.localdate()
        tx_filter = Q(created_at__date=today_date)
        payment_filter = Q(created_at__date=today_date)
    elif period_key == "week":
        start_time = now - timedelta(days=7)
        tx_filter = Q(created_at__gte=start_time)
        payment_filter = Q(created_at__gte=start_time)
    elif period_key == "month":
        start_time = now - timedelta(days=30)
        tx_filter = Q(created_at__gte=start_time)
        payment_filter = Q(created_at__gte=start_time)
    elif period_key == "all":
        pass
    else:
        # Default unrecognized period to 'all'
        period_key = "all"

    # Filtered transactions
    tx_qs = Transaction.objects.filter(tx_filter)
    total_transactions_count = tx_qs.count()

    # Cash and Utang sales breakdown
    cash_sales_agg = tx_qs.filter(transaction_type=Transaction.TYPE_CASH).aggregate(total=Sum("total_amount"))["total"]
    cash_sales_total = (cash_sales_agg or Decimal("0.00")).quantize(TWO_PLACES)

    utang_sales_agg = tx_qs.filter(transaction_type=Transaction.TYPE_UTANG).aggregate(total=Sum("total_amount"))["total"]
    utang_sales_total = (utang_sales_agg or Decimal("0.00")).quantize(TWO_PLACES)

    # Gross Revenue = Cash Sales + Utang Sales
    gross_revenue = (cash_sales_total + utang_sales_total).quantize(TWO_PLACES)

    # Cost of Goods Sold (COGS)
    items_qs = TransactionItem.objects.filter(transaction__in=tx_qs).select_related("product")
    cogs_total = Decimal("0.00")
    for item in items_qs:
        qty = Decimal(str(item.quantity))
        # Fallback to product wholesale_cost if item cost_price is 0 or unrecorded
        if item.cost_price and item.cost_price > Decimal("0.00"):
            unit_cost = Decimal(str(item.cost_price))
        elif item.product and item.product.wholesale_cost:
            unit_cost = Decimal(str(item.product.wholesale_cost))
        else:
            unit_cost = Decimal("0.00")
        cogs_total += qty * unit_cost

    cogs = cogs_total.quantize(TWO_PLACES)

    # Net Profit = Gross Revenue - COGS
    net_profit = (gross_revenue - cogs).quantize(TWO_PLACES)

    # Profit Margin % (Zero-division resilience)
    if gross_revenue > Decimal("0.00"):
        profit_margin_pct = round(float((net_profit / gross_revenue) * Decimal("100.0")), 2)
    else:
        profit_margin_pct = 0.0

    # Debt repayments collected in period
    repayments_agg = CustomerPayment.objects.filter(payment_filter).aggregate(total=Sum("amount"))["total"]
    repayments_total = (repayments_agg or Decimal("0.00")).quantize(TWO_PLACES)

    # STRICT LIQUIDITY ISOLATION:
    # Physical Cash-on-Hand = Cash sales + Cash repayments collected into register drawer.
    # Uncollected credit / utang is strictly excluded from cash drawer liquidity.
    cash_on_hand = (cash_sales_total + repayments_total).quantize(TWO_PLACES)

    # Total outstanding debt owed by active customers
    uncollected_agg = Customer.objects.filter(is_active=True).aggregate(total=Sum("debt_balance"))["total"]
    uncollected_utang = (uncollected_agg or Decimal("0.00")).quantize(TWO_PLACES)

    return {
        "gross_revenue": gross_revenue,
        "cogs": cogs,
        "net_profit": net_profit,
        "profit_margin_pct": profit_margin_pct,
        "cash_on_hand": cash_on_hand,
        "uncollected_utang": uncollected_utang,
        "cash_sales_total": cash_sales_total,
        "utang_sales_total": utang_sales_total,
        "repayments_total": repayments_total,
        "total_transactions_count": total_transactions_count,
        "period": period_key,
    }


def get_inventory_turnover_analytics(as_of: Optional[Any] = None) -> Dict[str, Any]:
    """
    Calculate inventory movement velocity over 7-day and 30-day windows and classify
    items as FAST_MOVING, MODERATE, or DEAD_STOCK with tied-up capital calculation.

    Args:
        as_of: Optional reference datetime or ISO string (defaults to timezone.now()) for historical/deterministic testing.

    Returns:
        dict matching PROJECT.md § Interface Contracts:
            - fast_moving: list of product turnover dicts sorted by sales_30d descending
            - dead_stock: list of product turnover dicts with sales_30d == 0 sorted by stock_value descending
            - all_items: list of all active items with turnover metrics
            - all_skus: alias of all_items
            - fast_moving_count: int
            - dead_stock_count: int
            - dead_stock_tied_capital: Decimal
            - as_of: datetime
    """
    if as_of is not None and isinstance(as_of, str):
        from django.utils.dateparse import parse_datetime, parse_date
        clean_str = as_of.strip()
        parsed = None
        try:
            parsed = parse_datetime(clean_str)
            if not parsed and " " in clean_str:
                parsed = parse_datetime(clean_str.replace(" ", "+"))
            if not parsed:
                d = parse_date(clean_str)
                if d:
                    parsed = datetime.combine(d, datetime.min.time())
        except (ValueError, TypeError, OverflowError):
            parsed = None
        as_of = parsed

    if as_of is not None and isinstance(as_of, date) and not isinstance(as_of, datetime):
        as_of = datetime.combine(as_of, datetime.min.time())

    if as_of is None:
        as_of = timezone.now()
    elif timezone.is_naive(as_of):
        as_of = timezone.make_aware(as_of)

    start_7d = as_of - timedelta(days=7)
    start_30d = as_of - timedelta(days=30)

    # 1. Aggregate TransactionItem quantities for 7d and 30d windows
    # Window filters: [start, as_of]
    items_7d_agg = (
        TransactionItem.objects.filter(
            transaction__created_at__gte=start_7d,
            transaction__created_at__lte=as_of,
        )
        .values("product_id")
        .annotate(total_qty=Sum("quantity"))
    )
    qty_7d_map = {row["product_id"]: row["total_qty"] for row in items_7d_agg}

    items_30d_agg = (
        TransactionItem.objects.filter(
            transaction__created_at__gte=start_30d,
            transaction__created_at__lte=as_of,
        )
        .values("product_id")
        .annotate(total_qty=Sum("quantity"))
    )
    qty_30d_map = {row["product_id"]: row["total_qty"] for row in items_30d_agg}

    # 2. Iterate through all active products
    active_products = Product.objects.filter(is_active=True).order_by("name")
    all_items = []

    for product in active_products:
        raw_7d = qty_7d_map.get(product.id) or Decimal("0.00")
        raw_30d = qty_30d_map.get(product.id) or Decimal("0.00")

        sales_7d = Decimal(str(raw_7d)).quantize(TWO_PLACES)
        sales_30d = Decimal(str(raw_30d)).quantize(TWO_PLACES)

        daily_velocity_7d = round(float(sales_7d) / 7.0, 2)
        daily_velocity_30d = round(float(sales_30d) / 30.0, 2)

        current_stock = product.stock_quantity
        wholesale_cost = product.wholesale_cost or Decimal("0.00")
        retail_price = product.retail_price or Decimal("0.00")

        # Puhunan tied up in current stock
        stock_value = (max(Decimal("0.00"), current_stock) * wholesale_cost).quantize(TWO_PLACES)

        # Turnover ratio: 30-day sales relative to current stock
        if current_stock > Decimal("0.00"):
            turnover_ratio = round(float(sales_30d / current_stock), 2)
        else:
            turnover_ratio = 1.0 if sales_30d > Decimal("0.00") else 0.0

        # Classification rule:
        # - DEAD_STOCK: exactly 0 movement in 30 days
        # - FAST_MOVING: sales_30d > 0 and (sales_7d >= 10 or sales_30d >= 20 or turnover_ratio >= 0.5)
        # - MODERATE: otherwise
        if sales_30d == Decimal("0.00"):
            status = "DEAD_STOCK"
            status_label = "Patay na Stock"
        elif sales_30d > Decimal("0.00") and (
            sales_7d >= Decimal("10.00") or sales_30d >= Decimal("20.00") or turnover_ratio >= 0.5
        ):
            status = "FAST_MOVING"
            status_label = "Mabilis Mabenta"
        else:
            status = "MODERATE"
            status_label = "Katamtaman"

        item_data = {
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "sales_7d": sales_7d,
            "sales_30d": sales_30d,
            "daily_velocity_7d": daily_velocity_7d,
            "daily_velocity_30d": daily_velocity_30d,
            "current_stock": current_stock,
            "wholesale_cost": wholesale_cost,
            "retail_price": retail_price,
            "stock_value": stock_value,
            "turnover_ratio": turnover_ratio,
            "status": status,
            "status_label": status_label,
        }
        all_items.append(item_data)

    # 3. Categorize and sort lists
    fast_moving = [it for it in all_items if it["status"] == "FAST_MOVING"]
    fast_moving.sort(key=lambda x: (x["sales_30d"], x["sales_7d"]), reverse=True)

    dead_stock = [it for it in all_items if it["status"] == "DEAD_STOCK"]
    dead_stock.sort(key=lambda x: (x["stock_value"], x["current_stock"]), reverse=True)

    dead_stock_tied_capital = sum(
        (it["stock_value"] for it in dead_stock), Decimal("0.00")
    ).quantize(TWO_PLACES)

    return {
        "fast_moving": fast_moving,
        "dead_stock": dead_stock,
        "all_items": all_items,
        "all_skus": all_items,
        "fast_moving_count": len(fast_moving),
        "dead_stock_count": len(dead_stock),
        "dead_stock_tied_capital": dead_stock_tied_capital,
        "as_of": as_of,
    }

