"""
Adversarial Empirical Challenge Test Suite for Milestone 3: Local Fuzzy SKU Matching.
Written by challenger_m3_1 to rigorously challenge:
1. Fuzzy matching accuracy under severe typos, word permutations, mixed casing, extra punctuation, pricing noise.
2. Exact threshold boundary behavior (79.9% rejected vs 80.0% accepted).
3. Batch throughput latency for 50 receipt lines (< 200ms requirement).
4. Edge cases, cross-flavor discrimination, and thousands separator handling.
"""

from decimal import Decimal
import time
import pytest

from core.models import Product
from core.services.fuzzy_matcher import (
    fuzzy_match_sku,
    match_receipt_lines,
    normalize_text,
    parse_receipt_line_metadata,
    _score_candidate,
)


@pytest.fixture
def standard_challenge_catalog():
    """Deterministic in-memory catalog representing typical Philippine sari-sari store SKUs."""
    return [
        {
            "sku": "SKU-NOOD-001",
            "name": "Lucky Me! Pancit Canton Kalamansi 60g",
            "brand": "Lucky Me!",
            "pack_unit": "box (72s)",
            "retail_price": Decimal("15.00"),
        },
        {
            "sku": "SKU-NOOD-002",
            "name": "Lucky Me! Pancit Canton Extra Hot 60g",
            "brand": "Lucky Me!",
            "pack_unit": "box (72s)",
            "retail_price": Decimal("15.00"),
        },
        {
            "sku": "SKU-NOOD-003",
            "name": "Lucky Me! Pancit Canton Original 60g",
            "brand": "Lucky Me!",
            "pack_unit": "box (72s)",
            "retail_price": Decimal("15.00"),
        },
        {
            "sku": "SKU-COFF-001",
            "name": "Kopiko Blanca Coffee Twin Pack 52g",
            "brand": "Kopiko",
            "pack_unit": "bundle (10s)",
            "retail_price": Decimal("16.00"),
        },
        {
            "sku": "SKU-MLK-001",
            "name": "Bear Brand Fortified Powdered Milk 33g",
            "brand": "Bear Brand",
            "pack_unit": "bundle (10s)",
            "retail_price": Decimal("15.00"),
        },
        {
            "sku": "SKU-BEV-001",
            "name": "San Miguel Light Can 330ml",
            "brand": "San Miguel",
            "pack_unit": "case (24s)",
            "retail_price": Decimal("55.00"),
        },
        {
            "sku": "SKU-CAN-001",
            "name": "555 Sardines in Tomato Sauce 155g",
            "brand": "555",
            "pack_unit": "case (50s)",
            "retail_price": Decimal("26.00"),
        },
        {
            "sku": "SKU-HPC-001",
            "name": "Surf Powder Detergent Sun Fresh 55g",
            "brand": "Surf",
            "pack_unit": "bundle (10s)",
            "retail_price": Decimal("9.00"),
        },
    ]


# =============================================================================
# 1. EMPIRICAL VERIFICATION: EXACT THRESHOLD BOUNDARY BEHAVIOR (79.9% vs 80.0%)
# =============================================================================

def test_exact_boundary_rejection_79_9_percent():
    """Verify that an item scoring 79.9% is strictly rejected (returns None)."""
    # 204 chars of 'x' vs (204 - 41) 'x' and 41 'y'
    # token_sort_ratio = (2 * 163) / 408 * 100 = 79.90196% -> rounded to 79.9%
    base_text = "x" * 204
    cand_text = ("x" * 163) + ("y" * 41)

    catalog = [
        {
            "sku": "SKU-BOUNDARY-799",
            "name": base_text,
            "brand": "",
            "pack_unit": "",
            "retail_price": Decimal("10.00"),
        }
    ]

    score = _score_candidate(cand_text, catalog[0])
    assert round(score, 1) == 79.9
    assert round(score, 2) == 79.90

    # Test single item fuzzy matching
    result = fuzzy_match_sku(cand_text, catalog=catalog, threshold=80.0)
    assert result is None, f"Expected None for score {score:.2f}%, got {result}"

    # Test batch matching
    batch_results = match_receipt_lines([cand_text], catalog=catalog, threshold=80.0)
    assert len(batch_results) == 1
    assert batch_results[0]["matched"] is False
    assert batch_results[0]["is_matched"] is False
    assert batch_results[0]["score"] == 79.9
    assert batch_results[0]["product"] is None


def test_exact_boundary_acceptance_80_0_percent():
    """Verify that an item scoring exactly 80.0% is strictly accepted (returns match)."""
    # 20 chars of 'x' vs 16 'x' and 4 'y'
    # token_sort_ratio = (2 * 16) / 40 * 100 = 80.0000%
    base_text = "x" * 20
    cand_text = ("x" * 16) + ("y" * 4)

    catalog = [
        {
            "sku": "SKU-BOUNDARY-800",
            "name": base_text,
            "brand": "",
            "pack_unit": "",
            "retail_price": Decimal("25.00"),
        }
    ]

    score = _score_candidate(cand_text, catalog[0])
    assert round(score, 2) == 80.00

    # Test single item fuzzy matching
    result = fuzzy_match_sku(cand_text, catalog=catalog, threshold=80.0)
    assert result is not None, f"Expected match for score {score:.2f}%, got None"
    assert result["score"] == 80.0
    assert result["matched"] is True
    assert result["matched_sku"] == "SKU-BOUNDARY-800"

    # Test batch matching
    batch_results = match_receipt_lines([cand_text], catalog=catalog, threshold=80.0)
    assert len(batch_results) == 1
    assert batch_results[0]["matched"] is True
    assert batch_results[0]["is_matched"] is True
    assert batch_results[0]["score"] == 80.0
    assert batch_results[0]["matched_sku"] == "SKU-BOUNDARY-800"


def test_sub_80_rejection_for_unrelated_categories():
    """Verify unrelated categories are strictly rejected (< 80%)."""
    catalog = [
        {
            "sku": "SKU-TEST-01",
            "name": "Gold Coast Sardines in Extra Virgin Olive Oil 155g",
            "brand": "Gold Coast",
            "pack_unit": "can",
            "retail_price": Decimal("50.00"),
        }
    ]

    # Queries with low overlap across distinct domain categories
    alien_queries = [
        "Champion Detergent Blue Bar 4s",
        "Ariel Sunrise Fresh Powder 1kg",
        "Pampers Baby Dry Pants XL 40s",
        "Motor Oil 10W-40 Synthetic 1L",
    ]

    for q in alien_queries:
        res = fuzzy_match_sku(q, catalog=catalog, threshold=80.0)
        assert res is None, f"Expected rejection for '{q}', but matched: {res}"


def test_token_set_subset_false_positive_risk():
    """Empirically demonstrate token_set_ratio risk: partial brand overlap scores >80%."""
    catalog = [
        {
            "sku": "SKU-TEST-01",
            "name": "Gold Coast Sardines in Extra Virgin Olive Oil 155g",
            "brand": "Gold Coast",
            "pack_unit": "can",
            "retail_price": Decimal("50.00"),
        }
    ]
    # 'Gold Star' differs from 'Gold Coast' by brand, but shares 5 words ('Gold', 'Sardines', 'in', 'Oil', '155g')
    # Because token_set_ratio is used for multi-token queries, it scores 90.91%
    res = fuzzy_match_sku("Gold Star Sardines in Oil 155g", catalog=catalog, threshold=80.0)
    assert res is not None
    assert res["score"] > 80.0, "Demonstrates that token_set_ratio can yield high scores on brand collisions"


# =============================================================================
# 2. EMPIRICAL VERIFICATION: ACCURACY (TYPOS, PERMUTATIONS, CASING, NOISE)
# =============================================================================

def test_ocr_severe_optical_and_spelling_typos(standard_challenge_catalog):
    """Verify matching accuracy under severe OCR substitutions and spelling errors."""
    typo_test_cases = [
        # Optical character substitutions (0 for O, 1 for I, rn for m)
        ("LUCKY ME PANCIT CANT0N EXTRA H0T 60G", "SKU-NOOD-002", 90.0),
        ("LUCKY ME PANC1T CANTON EXTRA HOT 60G", "SKU-NOOD-002", 95.0),
        ("LUCKY rne PANCIT CANTON EXTRA HOT 60G", "SKU-NOOD-002", 90.0),
        # Severe omissions / dropped vowels
        ("LUKY ME PANCIT CANTON EXTRA HOT 60G", "SKU-NOOD-002", 95.0),
        ("LUCKY ME PANCIT CNTON EXTRA HT 60G", "SKU-NOOD-002", 95.0),
        # Typo in Philippine abbreviations (unmerged tokens)
        ("LKY ME PC EXTR HOT 72S", "SKU-NOOD-002", 90.0),
        ("BER BRND PWD 33G", "SKU-MLK-001", 85.0),
        ("555 SARDNES TOMATO 155G", "SKU-CAN-001", 80.0),
    ]

    for query, expected_sku, min_score in typo_test_cases:
        res = fuzzy_match_sku(query, catalog=standard_challenge_catalog, threshold=80.0)
        assert res is not None, f"Failed to match typo query: '{query}'"
        assert res["matched_sku"] == expected_sku
        assert res["score"] >= min_score, f"Score {res['score']} below expected {min_score} for '{query}'"


def test_token_merge_tie_breaking_behavior(standard_challenge_catalog):
    """Demonstrate empirical behavior when OCR merges flavor tokens into one word ('EXTHOT')."""
    # When 'EXT' and 'HOT' are merged into 'EXTHOT', both Kalamansi and Extra Hot tie at 88.14%
    # First catalog item (Kalamansi SKU-NOOD-001) wins the tie due to strict '>' comparison
    res = fuzzy_match_sku("LKY ME PC EXTHOT 72S", catalog=standard_challenge_catalog, threshold=80.0)
    assert res is not None
    assert res["score"] >= 80.0
    # Demonstrates catalog-order tie-breaker
    assert res["matched_sku"] in ("SKU-NOOD-001", "SKU-NOOD-002")


def test_cross_flavor_discrimination(standard_challenge_catalog):
    """Verify distinct flavors of same brand do not mis-match when abbreviations are present."""
    flavor_cases = [
        ("LKY ME PC KLM 72S", "SKU-NOOD-001"),  # Kalamansi
        ("LKY ME PC EXT HOT 72S", "SKU-NOOD-002"),  # Extra Hot
        ("LKY ME PC ORG 60G", "SKU-NOOD-003"),  # Original
    ]

    for query, expected_sku in flavor_cases:
        res = fuzzy_match_sku(query, catalog=standard_challenge_catalog, threshold=80.0)
        assert res is not None
        assert res["matched_sku"] == expected_sku, f"Query '{query}' matched wrong SKU: {res['matched_sku']}"


def test_word_permutations_and_token_reversals(standard_challenge_catalog):
    """Verify token permutation invariance (RapidFuzz token_sort_ratio / token_set_ratio)."""
    permutations = [
        # Full reversal
        ("72S HOT EXT PC ME LKY", "SKU-NOOD-002"),
        # Shuffled tokens
        ("EXTRA HOT 60G ME CANTON LUCKY PANCIT", "SKU-NOOD-002"),
        # Packaging / unit first
        ("CAN 330ML SAN MIG LIGHT", "SKU-BEV-001"),
        # Flavor before brand
        ("BLANCA KOPIKO 10S", "SKU-COFF-001"),
        # Unit and type before brand
        ("33G PWD BEAR BRND", "SKU-MLK-001"),
    ]

    for query, expected_sku in permutations:
        res = fuzzy_match_sku(query, catalog=standard_challenge_catalog, threshold=80.0)
        assert res is not None, f"Permutation failed for '{query}'"
        assert res["matched_sku"] == expected_sku
        assert res["score"] >= 80.0


def test_mixed_casing_variations(standard_challenge_catalog):
    """Verify case insensitivity across spongecase, alternating case, and camelCase."""
    casing_cases = [
        ("lKy Me pC eXt HoT 72S", "SKU-NOOD-002"),
        ("KoPiKo BlAnCa 10S", "SKU-COFF-001"),
        ("sAn MiG lIgHt CaN 330mL", "SKU-BEV-001"),
        ("BEAR BRAND FORTIFIED POWDERED MILK 33G", "SKU-MLK-001"),
        ("lucky me! pancit canton extra hot 60g", "SKU-NOOD-002"),
    ]

    for query, expected_sku in casing_cases:
        res = fuzzy_match_sku(query, catalog=standard_challenge_catalog, threshold=80.0)
        assert res is not None, f"Casing test failed for '{query}'"
        assert res["matched_sku"] == expected_sku


def test_extra_punctuation_and_delimiter_noise(standard_challenge_catalog):
    """Verify resilience against dense punctuation, brackets, pipes, and symbol noise."""
    punct_cases = [
        ("*** LKY ME, PC - EXT HOT (72S) #1 !!!", "SKU-NOOD-002"),
        ("[[KOPIKO]] // BLANCA \\\\ (10S)::;;", "SKU-COFF-001"),
        ("SAN.MIG.LIGHT.CAN.330ML", "SKU-BEV-001"),
        ("BEAR_BRND_PWD_33G", "SKU-MLK-001"),
        ("555 --- SARDINES *** (TOMATO SAUCE) @@@ 155G", "SKU-CAN-001"),
        ("SURF +++ POWDER %%% SUN FRESH ~~~ 55G", "SKU-HPC-001"),
    ]

    for query, expected_sku in punct_cases:
        res = fuzzy_match_sku(query, catalog=standard_challenge_catalog, threshold=80.0)
        assert res is not None, f"Punctuation test failed for '{query}'"
        assert res["matched_sku"] == expected_sku
        assert res["score"] >= 80.0


def test_pricing_noise_and_currency_symbols(standard_challenge_catalog):
    """Verify pricing notation (@ 900.00, PHP, P, integer amounts) is cleanly stripped."""
    price_cases = [
        ("1x LKY ME PC EXT HOT 72S @ 900.00", "SKU-NOOD-002"),
        ("KOPIKO BLANCA 10S PHP 115.00", "SKU-COFF-001"),
        ("SAN MIG LIGHT CAN 330ML P1104.00", "SKU-BEV-001"),
        ("BEAR BRND PWD 33G 120.00", "SKU-MLK-001"),
        ("555 SARD TOM 50S @1100.00", "SKU-CAN-001"),
        ("LKY ME PC ORG 60G @ 900", "SKU-NOOD-003"),
        ("10x SURF POWDER SUN FRESH 55G @ 68.00 PHP", "SKU-HPC-001"),
    ]

    for query, expected_sku in price_cases:
        res = fuzzy_match_sku(query, catalog=standard_challenge_catalog, threshold=80.0)
        assert res is not None, f"Pricing noise test failed for '{query}'"
        assert res["matched_sku"] == expected_sku
        assert res["score"] >= 80.0


# =============================================================================
# 3. EMPIRICAL VERIFICATION: BATCH THROUGHPUT LATENCY (< 200ms FOR 50 LINES)
# =============================================================================

def test_batch_throughput_50_receipt_lines_standard_catalog(standard_challenge_catalog):
    """Measure batch matching latency for 50 receipt lines on standard catalog (8 products)."""
    base_lines = [
        "1x LKY ME PC EXT HOT 72S @ 900.00",
        "2x KOPIKO BLANCA 10S @ 115.00",
        "1x BEAR BRND PWD 33G @ 120.00",
        "3x SAN MIG LIGHT CAN 330ML @ 1104.00",
        "1x 555 SARD TOM 50S @ 1100.00",
        "2x GT WHT COF 10X30G @ 98.00",
        "5x SURF POWDER SUN FRESH 55G @ 68.00",
        "1x SAFEGUARD WHITE 60G @ 126.00",
        "1x CHAMPION BAR BLU 4S @ 84.00",
        "1x LKY ME PC KLM 72S @ 900.00",
    ]
    lines_50 = base_lines * 5
    assert len(lines_50) == 50

    # Warm-up run
    match_receipt_lines(lines_50, catalog=standard_challenge_catalog, threshold=80.0)

    # 10 execution trials
    trial_durations_ms = []
    for _ in range(10):
        t0 = time.perf_counter()
        results = match_receipt_lines(lines_50, catalog=standard_challenge_catalog, threshold=80.0)
        t1 = time.perf_counter()
        trial_durations_ms.append((t1 - t0) * 1000)

    avg_ms = sum(trial_durations_ms) / len(trial_durations_ms)
    min_ms = min(trial_durations_ms)
    max_ms = max(trial_durations_ms)

    assert len(results) == 50
    # Standard catalog (8 items) must strictly pass < 200ms
    assert max_ms < 200.0, f"Batch latency exceeded 200ms on 8 items: max={max_ms:.2f}ms, avg={avg_ms:.2f}ms"


@pytest.fixture
def seeded_50_product_catalog(db):
    """Seed 50 realistic FMCG products in the test database for throughput stress-testing."""
    categories = ["Instant Noodles", "Coffee & Hot Drinks", "Dairy & Milk", "Canned Goods", "Beverages"]
    products = []
    for i in range(50):
        cat = categories[i % len(categories)]
        prod = Product.objects.create(
            sku=f"FMCG-STRESS-{i:03d}",
            name=f"Philippine Grocery FMCG Brand Product Item Variant {i:03d} 100g",
            brand=f"Brand {i % 10}",
            category=cat,
            wholesale_cost=Decimal("20.00"),
            retail_price=Decimal("25.00"),
            stock_quantity=Decimal("50"),
            pack_unit="box (24s)",
            tingi_unit="piece",
            is_active=True,
        )
        products.append(prod)
    return products


@pytest.mark.django_db
def test_batch_throughput_50_receipt_lines_full_db_catalog(seeded_50_product_catalog):
    """Empirically stress-test batch throughput on 50 products in the database."""
    base_lines = [
        "1x LKY ME PC EXT HOT 72S @ 900.00",
        "2x KOPIKO BLANCA 10S @ 115.00",
        "1x BEAR BRND PWD 33G @ 120.00",
        "3x SAN MIG LIGHT CAN 330ML @ 1104.00",
        "1x 555 SARD TOM 50S @ 1100.00",
        "2x GT WHT COF 10X30G @ 98.00",
        "5x SURF POWDER SUN FRESH 55G @ 68.00",
        "1x SAFEGUARD WHITE 60G @ 126.00",
        "1x CHAMPION BAR BLU 4S @ 84.00",
        "1x LKY ME PC KLM 72S @ 900.00",
    ]
    lines_50 = base_lines * 5

    # Warmup
    match_receipt_lines(lines_50, catalog=seeded_50_product_catalog, threshold=80.0)

    # Benchmark across 10 trials
    trial_durations_ms = []
    for _ in range(10):
        t0 = time.perf_counter()
        results = match_receipt_lines(lines_50, catalog=seeded_50_product_catalog, threshold=80.0)
        t1 = time.perf_counter()
        trial_durations_ms.append((t1 - t0) * 1000)

    avg_ms = sum(trial_durations_ms) / len(trial_durations_ms)
    min_ms = min(trial_durations_ms)
    max_ms = max(trial_durations_ms)

    print(
        f"\n[BENCHMARK] 50 lines on {len(seeded_50_product_catalog)} DB products: "
        f"Avg={avg_ms:.2f}ms, Min={min_ms:.2f}ms, Max={max_ms:.2f}ms"
    )
    assert len(results) == 50


# =============================================================================
# 4. EDGE CASE FINDINGS: PRICE FORMATTING & DELIMITERS
# =============================================================================

def test_price_metadata_thousands_separator_limitation():
    """Demonstrate regex behavior when thousands separator commas are present."""
    # Line with comma in price: 'PHP 1,500.00'
    qty, price, clean = parse_receipt_line_metadata("1x PUREGOLD RICE 25KG PHP 1,500.00")
    # Current regex \d+\.\d{2} matches 500.00, dropping 1,
    assert price == Decimal("500.00")
    assert clean == "PUREGOLD RICE 25KG PHP 1,"
