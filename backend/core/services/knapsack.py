from decimal import Decimal
from typing import Any, Dict, Iterable, List
import pulp

TWO_PLACES = Decimal("0.01")


def solve_restock_knapsack(candidates: Iterable[Any], budget: Decimal) -> Dict[str, Any]:
    """
    Capital-constrained Bounded Integer Knapsack optimization using PuLP.
    Maximizes expected profit margin under a strict revolving capital budget constraint.

    Args:
        candidates: List or QuerySet of Product model instances.
        budget: Revolving procurement cash budget (Decimal).

    Returns:
        dict containing:
            - items: List of dicts representing recommended replenishment packs.
            - categorized_items: Dict mapping category name to list of items.
            - total_spent: Total cost of recommended packs (Decimal).
            - remaining_budget: Unspent cash budget (Decimal).
            - expected_profit: Total expected gross profit margin (Decimal).
            - solver_status: Solver status string ("Optimal", "Feasible", etc.).
    """
    if not isinstance(budget, Decimal):
        budget = Decimal(str(budget))

    if budget <= Decimal("0.00"):
        return {
            "items": [],
            "categorized_items": {},
            "total_spent": Decimal("0.00"),
            "remaining_budget": budget,
            "expected_profit": Decimal("0.00"),
            "solver_status": "Infeasible" if budget < 0 else "Optimal",
        }

    prob = pulp.LpProblem("Restock_Knapsack", pulp.LpMaximize)
    var_map = []

    for idx, prod in enumerate(candidates):
        cost = Decimal(str(getattr(prod, "wholesale_cost", 0)))
        if cost <= Decimal("0.00"):
            continue

        price = Decimal(str(getattr(prod, "retail_price", cost)))
        margin = max(Decimal("0.01"), price - cost)

        rop = getattr(prod, "reorder_point", 10) or 10
        stock = getattr(prod, "stock_quantity", 0) or 0
        u_i = min(10, max(1, int(float(rop) * 2 - float(stock))))

        var_id = getattr(prod, "id", None)
        var_name = f"buy_{var_id if var_id is not None else idx}"
        var = pulp.LpVariable(var_name, lowBound=0, upBound=u_i, cat=pulp.LpInteger)
        var_map.append((prod, var, cost, margin))

    if not var_map:
        return {
            "items": [],
            "categorized_items": {},
            "total_spent": Decimal("0.00"),
            "remaining_budget": budget,
            "expected_profit": Decimal("0.00"),
            "solver_status": "Optimal",
        }

    # Objective: Maximize total expected profit margin
    prob += pulp.lpSum([float(margin) * var for _, var, _, margin in var_map])

    # Constraint: Total procurement spend <= budget
    prob += pulp.lpSum([float(cost) * var for _, var, cost, _ in var_map]) <= float(budget)

    # Solve using CBC command-line solver with suppressed logging
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status_str = pulp.LpStatus.get(prob.status, "Optimal")

    items: List[Dict[str, Any]] = []
    for prod, var, cost, margin in var_map:
        val = var.varValue
        packs = int(round(val)) if val is not None else 0
        if packs > 0:
            unit_cost = cost.quantize(TWO_PLACES)
            subtotal = (unit_cost * packs).quantize(TWO_PLACES)
            item_profit = (margin * packs).quantize(TWO_PLACES)
            items.append({
                "product_id": getattr(prod, "id", None),
                "sku": getattr(prod, "sku", ""),
                "name": getattr(prod, "name", ""),
                "category": getattr(prod, "category", "General") or "General",
                "pack_unit": getattr(prod, "pack_unit", "pack") or "pack",
                "packs_to_buy": packs,
                "packs": packs,
                "unit_cost": unit_cost,
                "subtotal": subtotal,
                "line_total": subtotal,
                "expected_profit": item_profit,
            })

    # Strict zero-overrun guard: if floating-point imprecision exceeded budget, trim lowest-yield packs
    total_spent = sum((it["subtotal"] for it in items), Decimal("0.00"))
    while total_spent > budget and items:
        items.sort(key=lambda x: (x["expected_profit"] / x["subtotal"], x["expected_profit"]))
        it = items[0]
        it["packs_to_buy"] -= 1
        it["packs"] = it["packs_to_buy"]
        if it["packs_to_buy"] <= 0:
            items.pop(0)
        else:
            it["subtotal"] = (it["unit_cost"] * it["packs_to_buy"]).quantize(TWO_PLACES)
            it["line_total"] = it["subtotal"]
            it["expected_profit"] = (
                it["expected_profit"] / (it["packs_to_buy"] + 1) * it["packs_to_buy"]
            ).quantize(TWO_PLACES)
        total_spent = sum((i["subtotal"] for i in items), Decimal("0.00"))

    # Order items by category and name for supermarket aisle navigation
    items.sort(key=lambda x: (x["category"], x["name"]))

    # Group into aisle checklist categories
    categorized_items: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        cat = it["category"]
        if cat not in categorized_items:
            categorized_items[cat] = []
        categorized_items[cat].append(it)

    remaining_budget = (budget - total_spent).quantize(TWO_PLACES)
    total_profit = sum((it["expected_profit"] for it in items), Decimal("0.00"))

    return {
        "items": items,
        "categorized_items": categorized_items,
        "total_spent": total_spent,
        "remaining_budget": remaining_budget,
        "expected_profit": total_profit,
        "solver_status": status_str,
    }
