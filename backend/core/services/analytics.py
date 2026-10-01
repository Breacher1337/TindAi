from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict
from django.db.models import Q, Sum
from django.utils import timezone
from core.models import Customer, CustomerPayment, Transaction, TransactionItem

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
