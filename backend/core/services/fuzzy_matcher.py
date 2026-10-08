"""
Local Algorithmic Fuzzy SKU Matching Service for TindAI.

Provides fast, offline-capable matching of cryptic Philippine supermarket receipt line-items,
abbreviations, and OCR typos against store catalog products using RapidFuzz string similarity
algorithms (token_sort_ratio and token_set_ratio) with domain-specific normalization.
"""

from decimal import Decimal
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from rapidfuzz.fuzz import token_set_ratio, token_sort_ratio

try:
    from core.models import Product
except Exception:
    Product = None  # type: ignore

logger = logging.getLogger(__name__)

# Multi-word supermarket abbreviations frequently encountered on Philippine thermal receipts
PHRASE_REPLACEMENTS: List[Tuple[str, str]] = [
    (r"\bsan\s+mig\b", "san miguel"),
    (r"\blky\s+me\b", "lucky me"),
    (r"\bgt\s+wht\b", "great taste white"),
    (r"\bbear\s+brnd\b", "bear brand"),
    (r"\bbear\s+brd\b", "bear brand"),
    (r"\bred\s+horse\b", "red horse"),
    (r"\bdatu\s+puti\b", "datu puti"),
    (r"\bsilver\s+swan\b", "silver swan"),
    (r"\bmagic\s+sarap\b", "magic sarap"),
    (r"\btwin\s+pack\b", "twin pack"),
    (r"\bwhite\s+sugar\b", "white sugar"),
    (r"\bbrown\s+sugar\b", "brown sugar"),
]

# Single-token supermarket abbreviations
TOKEN_ABBREVIATIONS: Dict[str, str] = {
    # Noodles & Instant
    "lky": "lucky",
    "me": "me",
    "pc": "pancit canton",
    "canton": "canton",
    "pancit": "pancit",
    "ext": "extra",
    "org": "original",
    "orig": "original",
    "klm": "kalamansi",
    "kal": "kalamansi",
    "cal": "kalamansi",
    "chm": "chilimansi",
    "chl": "chilimansi",
    "hot": "hot",
    "spcy": "spicy",
    "mami": "mami",
    "inst": "instant",
    "ndl": "noodles",
    "ndls": "noodles",
    # Coffee, Milk, Beverages
    "kop": "kopiko",
    "blanca": "blanca",
    "blnca": "blanca",
    "blnc": "blanca",
    "cof": "coffee",
    "coff": "coffee",
    "cff": "coffee",
    "wht": "white",
    "brwn": "brown",
    "blk": "black",
    "twin": "twin pack",
    "tp": "twin pack",
    "twnpk": "twin pack",
    "nes": "nescafe",
    "nesc": "nescafe",
    "clas": "classic",
    "gt": "great taste",
    "milo": "milo",
    "pwd": "powdered",
    "powd": "powdered",
    "brnd": "brand",
    "brd": "brand",
    "frt": "fortified",
    "mlk": "milk",
    "alaska": "alaska",
    "evap": "evaporated",
    "cond": "condensed",
    # Beer & Liquor & Soft Drinks
    "mig": "miguel",
    "smb": "san miguel beer",
    "pale": "pale",
    "plsn": "pilsen",
    "rh": "red horse",
    "coke": "coca cola",
    "coca": "coca cola",
    "cola": "cola",
    "roy": "royal",
    "spr": "sprite",
    "gin": "ginebra",
    "bilog": "bilog",
    # Canned & Meat & Fish
    "sard": "sardines",
    "srd": "sardines",
    "tom": "tomato",
    "sau": "sauce",
    "sc": "sauce",
    "crn": "corned",
    "crnd": "corned",
    "bf": "beef",
    "chk": "chicken",
    "chkn": "chicken",
    "tuna": "tuna",
    "flk": "flakes",
    "arg": "argentina",
    # Condiments
    "soysau": "soy sauce",
    "soy": "soy sauce",
    "toyo": "soy sauce",
    "vin": "vinegar",
    "suka": "vinegar",
    "patis": "fish sauce",
    "sarsa": "sarsa",
    "ketch": "ketchup",
    "ktchp": "ketchup",
    "aji": "ajinomoto",
    # Snacks
    "piat": "piattos",
    "chp": "chippy",
    "sky": "skyflakes",
    "oishi": "oishi",
    "prwn": "prawn",
    "crkr": "crackers",
    # Personal & Home Care
    "surf": "surf",
    "tide": "tide",
    "downy": "downy",
    "dtrg": "detergent",
    "det": "detergent",
    "fab": "fabric conditioner",
    "fabcon": "fabric conditioner",
    "shmp": "shampoo",
    "clgt": "colgate",
    "tpst": "toothpaste",
    "sg": "safeguard",
    "soap": "soap",
    # Packaging / Units
    "can": "can",
    "cn": "can",
    "btl": "bottle",
    "bot": "bottle",
    "bndl": "bundle",
    "bdl": "bundle",
    "sacht": "sachet",
    "scht": "sachet",
    "pkt": "packet",
    "cs": "case",
    "bx": "box",
}


def normalize_text(text: Optional[str]) -> str:
    """Normalize raw text: lowercase, strip punctuation, remove pricing noise, expand abbreviations.

    Handles Unicode, strips punctuation, normalizes spacing, and expands common
    Philippine supermarket shorthand terms (e.g. 'LKY ME PC' -> 'lucky me pancit canton').
    """
    if not text or not isinstance(text, str):
        return ""

    cleaned = text.lower().strip()
    if not cleaned:
        return ""

    # Remove multiplier prefix (e.g. '1x ', '2 x ')
    cleaned = re.sub(r"^\d+\s*[xX*]\s+", "", cleaned)

    # Remove price suffix or @ notation (e.g. '@ 900.00', 'PHP 115.00', ' 900.00')
    cleaned = re.sub(r"@\s*\d+(?:\.\d{1,2})?", " ", cleaned)
    cleaned = re.sub(r"\b(?:php|p)?\s*\d+\.\d{2}\b", " ", cleaned)

    # Strip non-alphanumeric punctuation while preserving letters, digits, and spaces
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = cleaned.replace("_", " ")

    # Expand multi-word supermarket abbreviations first
    for pattern, repl in PHRASE_REPLACEMENTS:
        cleaned = re.sub(pattern, repl, cleaned)

    # Expand single token abbreviations
    tokens = cleaned.split()
    expanded = [TOKEN_ABBREVIATIONS.get(t, t) for t in tokens]
    return " ".join(expanded).strip()


def parse_receipt_line_metadata(line: str) -> Tuple[int, Optional[Decimal], str]:
    """Extract quantity, wholesale price/subtotal, and product name string from raw receipt line.

    E.g. '1x LKY ME PC EXT HOT 72S @ 900.00' -> (1, Decimal('900.00'), 'LKY ME PC EXT HOT 72S')
    """
    clean = (line or "").strip()
    qty = 1

    # Extract quantity prefix (e.g. '1x ', '2 x ')
    m_qty = re.match(r"^(\d+)\s*[xX*]\s+(.*)$", clean)
    if m_qty:
        try:
            qty = max(1, int(m_qty.group(1)))
            clean = m_qty.group(2).strip()
        except ValueError:
            pass

    # Extract price suffix or @ notation
    price: Optional[Decimal] = None
    m_price = re.search(r"(?:@\s*|PHP\s*|P\s*)?(\d+\.\d{2})\s*$", clean, re.IGNORECASE)
    if not m_price:
        m_price = re.search(r"(?:@\s*)(\d+)\s*$", clean)

    if m_price:
        try:
            price = Decimal(m_price.group(1))
            clean = clean[: m_price.start()].strip()
        except Exception:
            pass

    return qty, price, clean


def _get_item_attr(item: Any, attr: str, default: Any = "") -> Any:
    """Extract attribute from either a model instance or a dictionary."""
    if isinstance(item, dict):
        return item.get(attr, default)
    return getattr(item, attr, default)


def _score_candidate(norm_raw: str, item: Any) -> float:
    """Calculate maximum RapidFuzz similarity between normalized query and a catalog item."""
    name = str(_get_item_attr(item, "name", ""))
    sku = str(_get_item_attr(item, "sku", ""))
    brand = str(_get_item_attr(item, "brand", ""))
    pack_unit = str(_get_item_attr(item, "pack_unit", ""))

    norm_name = normalize_text(name)
    norm_sku = normalize_text(sku)
    norm_full = normalize_text(f"{brand} {name} {pack_unit}")

    # RapidFuzz similarity scores
    s_sort_name = float(token_sort_ratio(norm_raw, norm_name))
    s_set_name = float(token_set_ratio(norm_raw, norm_name))

    s_sort_sku = float(token_sort_ratio(norm_raw, norm_sku))
    s_set_sku = float(token_set_ratio(norm_raw, norm_sku))

    s_sort_full = float(token_sort_ratio(norm_raw, norm_full))
    s_set_full = float(token_set_ratio(norm_raw, norm_full))

    # Single-token queries (e.g. single generic word) restrict to token_sort_ratio
    # to avoid false 100% subset matches on words like "white" or "can".
    raw_tokens = norm_raw.split()
    if len(raw_tokens) <= 1:
        return max(s_sort_name, s_sort_sku, s_sort_full)

    return max(s_sort_name, s_set_name, s_sort_sku, s_set_sku, s_sort_full, s_set_full)


def fuzzy_match_sku(
    raw_text: str,
    catalog: Optional[Iterable[Any]] = None,
    threshold: float = 80.0,
) -> Optional[Dict[str, Any]]:
    """Fuzzy match a single raw text string against active catalog products.

    Normalizes raw text (lowercases, removes punctuation, expands PH FMCG abbreviations)
    and computes similarity ratios against catalog product names, SKUs, and packaging.

    Args:
        raw_text: Receipt line item text or SKU string.
        catalog: Optional iterable of Product instances or dicts. If None, queries
                 Product.objects.filter(is_active=True).
        threshold: Minimum similarity score (0.0 - 100.0) required to consider a match.
                   Default is 80.0.

    Returns:
        Dict with match details if best score >= threshold, else None:
        {
            "product": Product or item dict,
            "score": float,
            "matched_sku": str,
            "matched_name": str,
            "retail_price": Decimal or value,
            "raw_line": str,
            "raw_text": str,
            "confidence": float,
            "matched": bool,
        }
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    # Check for pure numbers without product context
    if raw_text.strip().isdigit():
        pass  # will be checked against catalog SKUs / names below

    norm_raw = normalize_text(raw_text)
    if not norm_raw:
        return None

    if catalog is None:
        try:
            prod_cls = Product
            if prod_cls is None:
                from core.models import Product as prod_cls
            catalog = list(prod_cls.objects.filter(is_active=True))
        except Exception as exc:
            logger.debug("Failed to query catalog from DB: %s", exc)
            return None
    elif not isinstance(catalog, list):
        catalog = list(catalog)

    if not catalog:
        return None

    best_item: Optional[Any] = None
    best_score: float = -1.0

    for item in catalog:
        score = _score_candidate(norm_raw, item)
        if score > best_score:
            best_score = score
            best_item = item

    final_score = round(best_score, 2)
    if final_score < threshold or best_item is None:
        return None

    sku = str(_get_item_attr(best_item, "sku", ""))
    name = str(_get_item_attr(best_item, "name", ""))
    retail_price = _get_item_attr(best_item, "retail_price", Decimal("0.00"))

    return {
        "product": best_item,
        "score": final_score,
        "matched_sku": sku,
        "matched_name": name,
        "retail_price": retail_price,
        "raw_line": raw_text,
        "raw_text": raw_text,
        "confidence": round(best_score / 100.0, 4),
        "matched": True,
        "is_matched": True,
    }


def match_receipt_lines(
    raw_lines: List[str],
    threshold: float = 80.0,
    catalog: Optional[Iterable[Any]] = None,
    only_matches: bool = False,
) -> List[Dict[str, Any]]:
    """Batch fuzzy match a list of receipt lines against the product catalog.

    Optimized to pre-load catalog items once across the entire batch for high throughput (<200ms).

    Args:
        raw_lines: List of raw receipt lines.
        threshold: Score threshold (default 80.0).
        catalog: Optional catalog iterable. If None, queries Product.objects.filter(is_active=True).
        only_matches: If True, returns only lines with score >= threshold.
                      If False (default), returns a dict for each line indicating
                      matched status and score for downstream routing.

    Returns:
        List of dicts representing match results.
    """
    if catalog is None:
        try:
            prod_cls = Product
            if prod_cls is None:
                from core.models import Product as prod_cls
            catalog = list(prod_cls.objects.filter(is_active=True))
        except Exception as exc:
            logger.debug("Failed to query catalog from DB: %s", exc)
            catalog = []
    elif not isinstance(catalog, list):
        catalog = list(catalog)

    results: List[Dict[str, Any]] = []

    for line in raw_lines:
        norm_line = normalize_text(line)
        if not norm_line:
            if not only_matches:
                results.append({
                    "raw_line": line,
                    "raw_text": line,
                    "product": None,
                    "score": 0.0,
                    "confidence": 0.0,
                    "matched_sku": None,
                    "matched_name": None,
                    "retail_price": None,
                    "matched": False,
                    "is_matched": False,
                })
            continue

        best_item: Optional[Any] = None
        best_score: float = -1.0

        for item in catalog:
            score = _score_candidate(norm_line, item)
            if score > best_score:
                best_score = score
                best_item = item

        final_score = round(best_score, 2)
        if best_item is not None and final_score >= threshold:
            sku = str(_get_item_attr(best_item, "sku", ""))
            name = str(_get_item_attr(best_item, "name", ""))
            retail_price = _get_item_attr(best_item, "retail_price", Decimal("0.00"))
            results.append({
                "raw_line": line,
                "raw_text": line,
                "product": best_item,
                "score": final_score,
                "confidence": round(final_score / 100.0, 4),
                "matched_sku": sku,
                "matched_name": name,
                "retail_price": retail_price,
                "matched": True,
                "is_matched": True,
            })
        else:
            if not only_matches:
                results.append({
                    "raw_line": line,
                    "raw_text": line,
                    "product": None,
                    "score": round(max(0.0, best_score), 2),
                    "confidence": round(max(0.0, best_score) / 100.0, 4),
                    "matched_sku": None,
                    "matched_name": None,
                    "retail_price": None,
                    "matched": False,
                    "is_matched": False,
                })

    return results
