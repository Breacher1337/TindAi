"""
Automated PyTest Suite for Milestone 3: Local Fuzzy SKU Matching (Phase 3).

Verifies RapidFuzz token_sort_ratio and token_set_ratio matching, Philippine supermarket
abbreviation normalization, high-confidence matching (>= 80%), rejection (< 80%),
edge cases, batch performance (< 200ms), and integration with receipt parsing endpoints.
"""

from decimal import Decimal
import time
import pytest
from django.test import Client

from core.models import Product, Wholesaler, RestockInvoice
from core.schemas import ReceiptOcrOut
from core.services.fuzzy_matcher import (
    fuzzy_match_sku,
    match_receipt_lines,
    normalize_text,
    parse_receipt_line_metadata,
)
from core.services import gemini


@pytest.fixture
def fmcg_catalog(db):
    """Seed representative Philippine supermarket FMCG catalog in the test database."""
    products = [
        Product.objects.create(
            sku="SKU-NOOD-001",
            name="Lucky Me! Pancit Canton Kalamansi 60g",
            brand="Lucky Me!",
            category="Instant Noodles",
            wholesale_cost=Decimal("12.50"),
            retail_price=Decimal("15.00"),
            stock_quantity=Decimal("50"),
            pack_unit="box (72s)",
            tingi_unit="piece",
        ),
        Product.objects.create(
            sku="SKU-NOOD-002",
            name="Lucky Me! Pancit Canton Extra Hot 60g",
            brand="Lucky Me!",
            category="Instant Noodles",
            wholesale_cost=Decimal("12.50"),
            retail_price=Decimal("15.00"),
            stock_quantity=Decimal("40"),
            pack_unit="box (72s)",
            tingi_unit="piece",
        ),
        Product.objects.create(
            sku="SKU-NOOD-003",
            name="Lucky Me! Pancit Canton Original 60g",
            brand="Lucky Me!",
            category="Instant Noodles",
            wholesale_cost=Decimal("12.50"),
            retail_price=Decimal("15.00"),
            stock_quantity=Decimal("30"),
            pack_unit="box (72s)",
            tingi_unit="piece",
        ),
        Product.objects.create(
            sku="SKU-COFF-001",
            name="Kopiko Blanca Coffee Twin Pack 52g",
            brand="Kopiko",
            category="Coffee & Hot Drinks",
            wholesale_cost=Decimal("13.50"),
            retail_price=Decimal("16.00"),
            stock_quantity=Decimal("40"),
            pack_unit="bundle (10s)",
            tingi_unit="sachet",
        ),
        Product.objects.create(
            sku="SKU-COFF-002",
            name="Great Taste White 3in1 Coffee 30g",
            brand="Great Taste",
            category="Coffee & Hot Drinks",
            wholesale_cost=Decimal("9.80"),
            retail_price=Decimal("12.00"),
            stock_quantity=Decimal("60"),
            pack_unit="bundle (10s)",
            tingi_unit="sachet",
        ),
        Product.objects.create(
            sku="SKU-MLK-001",
            name="Bear Brand Fortified Powdered Milk 33g",
            brand="Bear Brand",
            category="Dairy & Milk",
            wholesale_cost=Decimal("12.00"),
            retail_price=Decimal("15.00"),
            stock_quantity=Decimal("45"),
            pack_unit="bundle (10s)",
            tingi_unit="sachet",
        ),
        Product.objects.create(
            sku="SKU-BEV-001",
            name="San Miguel Light Can 330ml",
            brand="San Miguel",
            category="Beverages & Liquor",
            wholesale_cost=Decimal("46.00"),
            retail_price=Decimal("55.00"),
            stock_quantity=Decimal("24"),
            pack_unit="case (24s)",
            tingi_unit="can",
        ),
        Product.objects.create(
            sku="SKU-CAN-001",
            name="555 Sardines in Tomato Sauce 155g",
            brand="555",
            category="Canned Goods",
            wholesale_cost=Decimal("22.00"),
            retail_price=Decimal("26.00"),
            stock_quantity=Decimal("36"),
            pack_unit="case (50s)",
            tingi_unit="can",
        ),
        Product.objects.create(
            sku="SKU-HPC-001",
            name="Surf Powder Detergent Sun Fresh 55g",
            brand="Surf",
            category="Personal & Home Care",
            wholesale_cost=Decimal("6.80"),
            retail_price=Decimal("9.00"),
            stock_quantity=Decimal("60"),
            pack_unit="bundle (10s)",
            tingi_unit="sachet",
        ),
        Product.objects.create(
            sku="SKU-HPC-002",
            name="Safeguard Pure White Bar Soap 60g",
            brand="Safeguard",
            category="Personal & Home Care",
            wholesale_cost=Decimal("21.00"),
            retail_price=Decimal("26.00"),
            stock_quantity=Decimal("30"),
            pack_unit="bundle (6s)",
            tingi_unit="bar",
        ),
    ]
    return products


# -----------------------------------------------------------------------------
# Unit Tests: Normalization & Pre-Processing
# -----------------------------------------------------------------------------

def test_normalize_text_philippine_supermarket_abbreviations():
    """Verify expansion of Philippine supermarket shorthand terms."""
    assert "lucky me pancit canton extra hot 72s" == normalize_text("LKY ME PC EXT HOT 72S")
    assert "lucky me pancit canton original 60g" == normalize_text("LKY ME PC ORG 60G")
    assert "kopiko blanca 10s" == normalize_text("KOPIKO BLANCA 10S")
    assert "bear brand powdered 33g" == normalize_text("BEAR BRND PWD 33G")
    assert "san miguel light can 330ml" == normalize_text("SAN MIG LIGHT CAN 330ML")
    assert "great taste white coffee" in normalize_text("GT WHT COF")
    assert "555 sardines tomato" in normalize_text("555 SARD TOM")


def test_normalize_text_strips_punctuation_and_pricing_noise():
    """Verify punctuation and price metadata (@ 900.00, PHP 115.00) are cleanly stripped."""
    raw = "1x LKY ME PC EXT HOT 72S @ 900.00"
    assert normalize_text(raw) == "lucky me pancit canton extra hot 72s"

    raw_price = "KOPIKO BLANCA 10S PHP 115.00"
    assert normalize_text(raw_price) == "kopiko blanca 10s"

    raw_punct = "Lucky Me! - Pancit Canton (Original) & Chili..."
    norm = normalize_text(raw_punct)
    assert "lucky me" in norm
    assert "pancit canton" in norm
    assert "original" in norm
    assert "!" not in norm
    assert "(" not in norm


def test_parse_receipt_line_metadata_extraction():
    """Verify extraction of quantity, wholesale cost, and product name text."""
    qty, price, clean = parse_receipt_line_metadata("1x LKY ME PC EXT HOT 72S @ 900.00")
    assert qty == 1
    assert price == Decimal("900.00")
    assert clean == "LKY ME PC EXT HOT 72S"

    qty2, price2, clean2 = parse_receipt_line_metadata("2x KOPIKO BLANCA 10S 115.00")
    assert qty2 == 2
    assert price2 == Decimal("115.00")
    assert clean2 == "KOPIKO BLANCA 10S"

    qty3, price3, clean3 = parse_receipt_line_metadata("BEAR BRND PWD 33G")
    assert qty3 == 1
    assert price3 is None
    assert clean3 == "BEAR BRND PWD 33G"


# -----------------------------------------------------------------------------
# Core Algorithmic Tests: Philippine Abbreviations (>= 80% matches)
# -----------------------------------------------------------------------------

@pytest.mark.django_db
def test_fuzzy_match_sku_philippine_abbreviations_all_cases(fmcg_catalog):
    """Verify all 5 target Philippine supermarket abbreviations resolve with >= 80% score."""
    targets = [
        ("LKY ME PC EXT HOT 72S", "SKU-NOOD-002", "Lucky Me! Pancit Canton Extra Hot 60g"),
        ("LKY ME PC ORG 60G", "SKU-NOOD-003", "Lucky Me! Pancit Canton Original 60g"),
        ("KOPIKO BLANCA 10S", "SKU-COFF-001", "Kopiko Blanca Coffee Twin Pack 52g"),
        ("BEAR BRND PWD 33G", "SKU-MLK-001", "Bear Brand Fortified Powdered Milk 33g"),
        ("SAN MIG LIGHT CAN 330ML", "SKU-BEV-001", "San Miguel Light Can 330ml"),
    ]

    for raw_query, expected_sku, expected_name in targets:
        result = fuzzy_match_sku(raw_query, threshold=80.0)
        assert result is not None, f"Expected match for '{raw_query}', got None"
        assert result["score"] >= 80.0, f"Score {result['score']} < 80.0 for '{raw_query}'"
        assert result["matched_sku"] == expected_sku, f"Expected SKU {expected_sku}, got {result['matched_sku']}"
        assert result["matched_name"] == expected_name
        assert result["retail_price"] > Decimal("0.00")
        assert result["matched"] is True
        assert isinstance(result["product"], Product)


@pytest.mark.django_db
def test_fuzzy_match_direct_sku_query(fmcg_catalog):
    """Verify exact or near-exact SKU code matching resolves with 100% confidence."""
    result = fuzzy_match_sku("SKU-NOOD-001", threshold=80.0)
    assert result is not None
    assert result["score"] == 100.0
    assert result["matched_sku"] == "SKU-NOOD-001"
    assert result["matched_name"] == "Lucky Me! Pancit Canton Kalamansi 60g"


# -----------------------------------------------------------------------------
# Rejection Tests: Novel / Unrecognized Items (< 80% score)
# -----------------------------------------------------------------------------

@pytest.mark.django_db
def test_fuzzy_match_sku_rejection_champion_bar_blue(fmcg_catalog):
    """Verify novel line item 'CHAMPION BAR BLU 4S' is rejected (< 80% score -> None)."""
    result = fuzzy_match_sku("CHAMPION BAR BLU 4S", threshold=80.0)
    assert result is None, f"Expected rejection (None) for CHAMPION BAR BLU 4S, but matched: {result}"


@pytest.mark.django_db
def test_match_receipt_lines_rejection_confidence(fmcg_catalog):
    """Verify batch matcher flags 'CHAMPION BAR BLU 4S' as unmatched with confidence < 0.80."""
    lines = ["CHAMPION BAR BLU 4S"]
    results = match_receipt_lines(lines, threshold=80.0)
    assert len(results) == 1
    res = results[0]
    assert res["matched"] is False
    assert res["is_matched"] is False
    assert res["matched_sku"] is None
    assert res["product"] is None
    assert res["score"] < 80.0
    assert res["confidence"] < 0.80


@pytest.mark.django_db
def test_fuzzy_match_rejection_arbitrary_unrelated_items(fmcg_catalog):
    """Verify completely alien items are strictly rejected."""
    alien_items = [
        "IPHONE 16 PRO MAX 256GB DESERT TITANIUM",
        "MOTOR OIL 10W-40 FULL SYNTHETIC 1L",
        "CONCRETE HOLLOW BLOCKS 4 INCH",
        "RANDOM UNKNOWN GIZMO 999",
    ]
    for item in alien_items:
        res = fuzzy_match_sku(item, threshold=80.0)
        assert res is None, f"Expected None for alien item '{item}', got {res}"


# -----------------------------------------------------------------------------
# Edge Cases: Boundaries, Empty Inputs, Unicode, Numbers
# -----------------------------------------------------------------------------

@pytest.mark.django_db
def test_edge_cases_empty_and_whitespace(fmcg_catalog):
    """Verify empty strings and whitespace return None without exception."""
    assert fuzzy_match_sku("") is None
    assert fuzzy_match_sku("   ") is None
    assert fuzzy_match_sku(None) is None  # type: ignore


@pytest.mark.django_db
def test_edge_cases_pure_numbers(fmcg_catalog):
    """Verify pure numbers not matching any SKU/barcode return None."""
    assert fuzzy_match_sku("123456789") is None
    assert fuzzy_match_sku("999999999999") is None


@pytest.mark.django_db
def test_edge_cases_unicode_and_symbols(fmcg_catalog):
    """Verify unicode characters (Philippine peso sign, accent marks) do not crash or corrupt matching."""
    res = fuzzy_match_sku("Lucky Me! Pancit Canton Kalamansi 60g ₱ ñ", threshold=80.0)
    assert res is not None
    assert res["matched_sku"] == "SKU-NOOD-001"
    assert res["score"] >= 80.0


def test_edge_cases_case_insensitivity(fmcg_catalog):
    """Verify case-insensitivity: lowercase, uppercase, and titlecase yield identical matching."""
    res_lower = fuzzy_match_sku("lucky me! pancit canton kalamansi 60g", catalog=fmcg_catalog)
    res_upper = fuzzy_match_sku("LUCKY ME! PANCIT CANTON KALAMANSI 60G", catalog=fmcg_catalog)
    res_mixed = fuzzy_match_sku("LuCkY mE! pAnCiT cAnToN kAlAmAnSi 60g", catalog=fmcg_catalog)

    assert res_lower is not None and res_upper is not None and res_mixed is not None
    assert res_lower["matched_sku"] == res_upper["matched_sku"] == res_mixed["matched_sku"]
    assert res_lower["score"] == res_upper["score"] == res_mixed["score"] == 100.0


def test_edge_cases_threshold_boundary():
    """Verify exact threshold boundary behavior: >= threshold passes, < threshold returns None."""
    mock_catalog = [
        {"sku": "TEST-01", "name": "Apple Banana Cherry", "retail_price": Decimal("10.00")}
    ]
    # Exact match gives score 100
    res_exact = fuzzy_match_sku("Apple Banana Cherry", catalog=mock_catalog, threshold=100.0)
    assert res_exact is not None
    assert res_exact["score"] == 100.0

    # Slight variation
    query = "Apple Banana Cherr"  # near match
    res_check = fuzzy_match_sku(query, catalog=mock_catalog, threshold=50.0)
    assert res_check is not None
    actual_score = res_check["score"]

    # Test threshold just at or below actual score
    assert fuzzy_match_sku(query, catalog=mock_catalog, threshold=actual_score) is not None
    # Test threshold just above actual score
    assert fuzzy_match_sku(query, catalog=mock_catalog, threshold=actual_score + 0.1) is None


# -----------------------------------------------------------------------------
# Batch Matcher & Performance Verification (< 200ms)
# -----------------------------------------------------------------------------

@pytest.mark.django_db
def test_match_receipt_lines_batch_structure_and_filtering(fmcg_catalog):
    """Verify match_receipt_lines processes mixed batches correctly."""
    lines = [
        "LKY ME PC EXT HOT 72S",
        "CHAMPION BAR BLU 4S",
        "KOPIKO BLANCA 10S",
        "UNKNOWN ITEM 999",
    ]

    # Default include_unmatched=False returns all 4 lines with matched flags
    results = match_receipt_lines(lines, threshold=80.0)
    assert len(results) == 4
    assert results[0]["matched"] is True
    assert results[0]["matched_sku"] == "SKU-NOOD-002"

    assert results[1]["matched"] is False
    assert results[1]["matched_sku"] is None

    assert results[2]["matched"] is True
    assert results[2]["matched_sku"] == "SKU-COFF-001"

    assert results[3]["matched"] is False

    # With only_matches=True, unmatched lines are filtered out
    filtered = match_receipt_lines(lines, threshold=80.0, only_matches=True)
    assert len(filtered) == 2
    assert {it["matched_sku"] for it in filtered} == {"SKU-NOOD-002", "SKU-COFF-001"}


@pytest.mark.django_db
def test_match_receipt_lines_performance_under_200ms(fmcg_catalog):
    """Verify execution speed is well under 200ms per batch of 20 receipt lines."""
    lines = [
        "LKY ME PC EXT HOT 72S @ 900.00",
        "LKY ME PC ORG 60G @ 900.00",
        "KOPIKO BLANCA 10S @ 115.00",
        "BEAR BRND PWD 33G @ 120.00",
        "SAN MIG LIGHT CAN 330ML @ 1104.00",
        "555 SARD TOM 50S @ 1100.00",
        "GT WHT COF 10X30G @ 98.00",
        "SURF POWDER SUN FRESH 55G @ 68.00",
        "SAFEGUARD WHITE 60G @ 126.00",
        "CHAMPION BAR BLU 4S @ 84.00",
        "LKY ME PC KLM 72S @ 900.00",
        "LKY ME PC EXT HOT 72S @ 900.00",
        "KOPIKO BLANCA 10S @ 115.00",
        "BEAR BRND PWD 33G @ 120.00",
        "SAN MIG LIGHT CAN 330ML @ 1104.00",
        "555 SARD TOM 50S @ 1100.00",
        "GT WHT COF 10X30G @ 98.00",
        "SURF POWDER SUN FRESH 55G @ 68.00",
        "SAFEGUARD WHITE 60G @ 126.00",
        "CHAMPION BAR BLU 4S @ 84.00",
    ]

    t0 = time.perf_counter()
    results = match_receipt_lines(lines, threshold=80.0)
    t1 = time.perf_counter()

    elapsed_ms = (t1 - t0) * 1000
    assert len(results) == 20
    assert elapsed_ms < 200.0, f"Batch matching took {elapsed_ms:.2f}ms (threshold is 200ms)"


# -----------------------------------------------------------------------------
# Integration Tests: Receipt Parsing Pipeline & API Endpoints
# -----------------------------------------------------------------------------

@pytest.mark.django_db
def test_ocr_receipt_local_fuzzy_matching_pre_llm(fmcg_catalog):
    """Verify gemini.ocr_receipt resolves raw lines via local fuzzy matcher before LLM."""
    raw_lines = [
        "1x LKY ME PC EXT HOT 72S @ 900.00",
        "1x KOPIKO BLANCA 10S @ 115.00",
        "1x CHAMPION BAR BLU 4S @ 84.00",
    ]

    out = gemini.ocr_receipt(
        image_base64=None,
        wholesaler_hint="Puregold Price Club Inc.",
        raw_lines=raw_lines,
    )

    assert isinstance(out, ReceiptOcrOut)
    assert len(out.items) == 3

    # First item matched Lucky Me Extra Hot
    item0 = out.items[0]
    assert item0.matched_sku == "SKU-NOOD-002"
    assert item0.confidence >= 0.80
    assert item0.pack_wholesale_cost == Decimal("900.00")
    assert item0.suggested_retail_price == Decimal("15.00")  # catalog retail price

    # Second item matched Kopiko Blanca
    item1 = out.items[1]
    assert item1.matched_sku == "SKU-COFF-001"
    assert item1.confidence >= 0.80
    assert item1.pack_wholesale_cost == Decimal("115.00")

    # Third item is unrecognized (< 80%)
    item2 = out.items[2]
    assert item2.matched_sku is None
    assert item2.confidence < 0.80
    # 15% markup applied to 84.00 = 96.60
    assert item2.suggested_retail_price == Decimal("96.60")

    assert out.total_amount == Decimal("900.00") + Decimal("115.00") + Decimal("84.00")


@pytest.mark.django_db
def test_api_post_ocr_receipt_endpoint_with_raw_lines(fmcg_catalog):
    """Acceptance Test: POST /api/ocr/receipt with raw_lines resolves via local fuzzy matching."""
    client = Client()
    payload = {
        "image_base64": None,
        "wholesaler_hint": "Puregold Price Club Inc.",
        "raw_lines": [
            "LKY ME PC ORG 60G @ 900.00",
            "SAN MIG LIGHT CAN 330ML @ 1104.00",
        ],
    }

    resp = client.post("/api/ocr/receipt", data=payload, content_type="application/json")
    assert resp.status_code == 200

    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 2

    skus = {it["matched_sku"] for it in data["items"]}
    assert "SKU-NOOD-003" in skus
    assert "SKU-BEV-001" in skus
    for it in data["items"]:
        assert it["confidence"] >= 0.80


@pytest.mark.django_db
def test_api_apply_receipt_fuzzy_resolves_unlinked_items(fmcg_catalog):
    """Acceptance Test: POST /api/ocr/receipt/apply uses fuzzy matching to resolve unlinked items."""
    client = Client()
    payload = {
        "wholesaler_name": "Puregold Price Club Inc.",
        "invoice_no": "INV-TEST-2026-001",
        "date": "2026-10-07",
        "total_amount": "900.00",
        "items": [
            {
                "raw_line_text": "LKY ME PC EXT HOT 72S",
                "matched_sku": None,  # Not linked yet by client
                "matched_name": "LKY ME PC EXT HOT",
                "qty_packs": 1,
                "pack_wholesale_cost": "900.00",
                "line_total": "900.00",
                "confidence": 0.90,
                "suggested_retail_price": "15.00",
            }
        ],
    }

    resp = client.post("/api/ocr/receipt/apply", data=payload, content_type="application/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True

    # Verify that the created invoice item linked to the existing Lucky Me product instead of creating a draft
    invoice = RestockInvoice.objects.get(invoice_no="INV-TEST-2026-001")
    invoice_item = invoice.items.first()
    assert invoice_item.product.sku == "SKU-NOOD-002"
    assert invoice_item.product.is_active is True
