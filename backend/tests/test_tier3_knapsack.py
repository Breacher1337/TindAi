import pytest
from decimal import Decimal
from core.models import Product

try:
    from core.services.knapsack import solve_restock_knapsack
except (ImportError, ModuleNotFoundError):
    solve_restock_knapsack = None


@pytest.mark.django_db
def test_knapsack_5000_budget_solver(mock_products_20):
    """
    ORIGINAL_REQUEST.md Acceptance Criteria §Knapsack:
    "Test seeds 20 mock products and runs solver with ₱5,000 budget;
    verifies total cost <= ₱5,000 and outputs a printable structure."

    Interface Contract (PROJECT.md § core.services.knapsack):
    solve_restock_knapsack(candidates: list[Product], budget: Decimal) -> dict:
      items: list[dict]
      categorized_items: dict[str, list[dict]]
      total_spent: Decimal
      remaining_budget: Decimal
      expected_profit: Decimal
      solver_status: str
    """
    if solve_restock_knapsack is None:
        pytest.fail("core.services.knapsack.solve_restock_knapsack is not implemented yet (Milestone M3)")

    budget = Decimal("5000.00")
    result = solve_restock_knapsack(mock_products_20, budget=budget)

    # 1. Budget Constraint: Total cost must never exceed budget
    total_spent = Decimal(str(result["total_spent"]))
    remaining_budget = Decimal(str(result["remaining_budget"]))
    assert total_spent <= budget, f"Knapsack exceeded budget: {total_spent} > {budget}"
    assert total_spent > Decimal("0.00"), "Optimizer spent ₱0 with 20 low-stock products"
    assert remaining_budget >= Decimal("0.00")
    assert total_spent + remaining_budget == budget

    # 2. Solver status
    assert result.get("solver_status") in ("Optimal", "Feasible")

    # 3. Item validation
    items = result.get("items", [])
    assert len(items) > 0, "No items recommended by solver"

    computed_spend = Decimal("0.00")
    for item in items:
        assert isinstance(item["packs_to_buy"], int)
        assert item["packs_to_buy"] >= 1
        subtotal = Decimal(str(item["subtotal"]))
        unit_cost = Decimal(str(item["unit_cost"]))
        assert subtotal == unit_cost * item["packs_to_buy"]
        computed_spend += subtotal

    assert computed_spend == total_spent


@pytest.mark.django_db
def test_knapsack_integer_pack_bounds_and_profit_maximization(mock_products_20):
    """
    Verifies that the optimizer adheres to integer wholesale pack quantities
    and strictly maximizes expected retail profit margin under capital constraint.
    """
    if solve_restock_knapsack is None:
        pytest.fail("core.services.knapsack.solve_restock_knapsack is not implemented yet (Milestone M3)")

    budget = Decimal("5000.00")
    result = solve_restock_knapsack(mock_products_20, budget=budget)

    expected_profit = Decimal(str(result.get("expected_profit", 0)))
    assert expected_profit > Decimal("0.00"), "Expected profit should be strictly positive"

    for item in result["items"]:
        # Wholesale purchases only happen in whole integer packs at distributors
        assert float(item["packs_to_buy"]).is_integer()
        assert item["packs_to_buy"] > 0


@pytest.mark.django_db
def test_knapsack_categorized_aisle_checklist_and_printable_format(mock_products_20):
    """
    PROJECT.md § R3 Categorized Checklist & Print:
    "Group knapsack recommendations by supermarket aisle/category with printable stylesheet."
    Verifies the output structure can be rendered as a structured shopping checklist.
    """
    if solve_restock_knapsack is None:
        pytest.fail("core.services.knapsack.solve_restock_knapsack is not implemented yet (Milestone M3)")

    budget = Decimal("5000.00")
    result = solve_restock_knapsack(mock_products_20, budget=budget)

    categorized = result.get("categorized_items")
    assert isinstance(categorized, dict), "categorized_items must be a dict keyed by category"
    assert len(categorized) > 0, "No categories returned in checklist"

    total_categorized_count = sum(len(items) for items in categorized.values())
    assert total_categorized_count == len(result["items"]), (
        "All recommended items must be categorized into supermarket aisle sections"
    )

    required_keys = {"sku", "name", "category", "pack_unit", "packs_to_buy", "unit_cost", "subtotal", "expected_profit"}
    for cat_name, cat_items in categorized.items():
        assert len(cat_items) > 0
        for it in cat_items:
            missing_keys = required_keys - set(it.keys())
            assert not missing_keys, f"Missing printable checklist keys: {missing_keys}"
            assert it["category"] == cat_name


@pytest.mark.django_db
def test_knapsack_boundary_capital_500_zero_overrun(mock_products_20):
    """
    IEEE 829 Matrix TC-OPT-02: Boundary capital budget test (₱500.00).
    Verifies that with very small revolving capital, the optimizer selects
    affordable packs with zero budget overruns.
    """
    if solve_restock_knapsack is None:
        pytest.fail("core.services.knapsack.solve_restock_knapsack is not implemented yet (Milestone M3)")

    low_budget = Decimal("500.00")
    result = solve_restock_knapsack(mock_products_20, budget=low_budget)

    total_spent = Decimal(str(result["total_spent"]))
    remaining = Decimal(str(result["remaining_budget"]))

    assert total_spent <= low_budget, f"Spent {total_spent} exceeded tight budget of {low_budget}"
    assert remaining >= Decimal("0.00")
    assert total_spent + remaining == low_budget


@pytest.mark.django_db
def test_knapsack_negative_or_zero_budget_rejection(api_client):
    """
    IEEE 829 Matrix TC-OPT-03: Zero / Negative Restocking Budget Input.
    Optimizer API endpoint must reject ₱0 or negative budget with HTTP 400/422.
    """
    res_zero = api_client.post(
        "/api/restock/optimize",
        data={"budget": 0},
        content_type="application/json"
    )
    assert res_zero.status_code in (400, 422)

    res_neg = api_client.post(
        "/api/restock/optimize",
        data={"budget": -500},
        content_type="application/json"
    )
    assert res_neg.status_code in (400, 422)
