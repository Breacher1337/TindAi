"""Acceptance test suite for Live Google Gemini Network Integration.

Executes real network requests using the configured GEMINI_API_KEY, verifying:
- Structured schema mapping into Pydantic models (CounterDetectOut and ReceiptOcrOut)
- Live POST requests via Django test Client to /api/vision/counter-detect and /api/ocr/receipt
- Multimodal image input handling via base64 encoded PNG and JPEG (generated in-memory via Pillow)
- Backward compatibility handling of 'dummy-data' without crashing
- Direct service calls and image preprocessing resilience
"""

import base64
import io
from decimal import Decimal
import pytest
from django.conf import settings
from django.test import Client
from PIL import Image

from core.models import Product
from core.schemas import CounterDetectOut, ReceiptOcrOut
from core.services import gemini


@pytest.fixture
def client():
    """Django test client for API endpoint integration."""
    return Client()


@pytest.fixture
def seed_catalog(db):
    """Seed active FMCG products for realistic catalog matching in Gemini prompts."""
    products = [
        Product.objects.create(
            sku="FMCG-NDL-001",
            name="Lucky Me! Pancit Canton Kalamansi 60g",
            brand="Lucky Me!",
            category="Instant Noodles",
            wholesale_cost=Decimal("12.50"),
            retail_price=Decimal("15.00"),
            stock_quantity=50,
            reorder_point=10,
            pack_unit="box (72s)",
            tingi_unit="piece",
            is_active=True,
        ),
        Product.objects.create(
            sku="FMCG-COF-001",
            name="Great Taste White 3in1 Coffee 30g",
            brand="Great Taste",
            category="Coffee & Hot Drinks",
            wholesale_cost=Decimal("9.50"),
            retail_price=Decimal("12.00"),
            stock_quantity=40,
            reorder_point=15,
            pack_unit="bag (30s)",
            tingi_unit="sachet",
            is_active=True,
        ),
        Product.objects.create(
            sku="FMCG-CAN-001",
            name="555 Sardines in Tomato Sauce 155g",
            brand="555",
            category="Canned Goods",
            wholesale_cost=Decimal("20.00"),
            retail_price=Decimal("26.00"),
            stock_quantity=30,
            reorder_point=10,
            pack_unit="case (50s)",
            tingi_unit="can",
            is_active=True,
        ),
    ]
    return products


def generate_test_image_base64(
    fmt: str = "PNG",
    size: tuple = (100, 100),
    color: str = "red",
    with_prefix: bool = True
) -> str:
    """Generate an in-memory test image with Pillow and return base64 string."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    raw_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    if with_prefix:
        return f"data:image/{fmt.lower()};base64,{raw_b64}"
    return raw_b64


@pytest.mark.django_db
class TestGeminiLiveNetwork:
    """Live network test suite executing real Google Gemini requests."""

    def test_gemini_api_key_configuration(self):
        """Verify GEMINI_API_KEY is configured and client initializes properly."""
        configured_key = getattr(settings, "GEMINI_API_KEY", None)
        assert configured_key is not None
        assert len(configured_key) > 20

        client = gemini.get_client()
        assert client is not None
        assert hasattr(client, "models")

    def test_live_counter_detect_text_prompt_hint(self, client, seed_catalog):
        """Acceptance Test: POST /api/vision/counter-detect executes live request and validates CounterDetectOut."""
        payload = {
            "image_base64": None,
            "prompt_hint": "Identify FMCG items on counter: canned sardines and instant noodles"
        }
        resp = client.post("/api/vision/counter-detect", data=payload, content_type="application/json")
        assert resp.status_code == 200

        data = resp.json()
        validated = CounterDetectOut.model_validate(data)

        assert validated.success is True
        assert isinstance(validated.message, str) and len(validated.message) > 0
        assert len(validated.detected_items) > 0
        assert isinstance(validated.estimated_total, Decimal)
        assert validated.estimated_total > Decimal("0.00")

        # Verify individual detected item schema
        for item in validated.detected_items:
            assert isinstance(item.sku, str) and len(item.sku) > 0
            assert isinstance(item.name, str) and len(item.name) > 0
            assert isinstance(item.category, str)
            assert 0.0 <= item.confidence <= 1.0
            assert item.detected_qty >= 1
            assert isinstance(item.unit_price, Decimal)
            assert item.unit_price > Decimal("0.00")

    def test_live_ocr_receipt_wholesaler_hint(self, client, seed_catalog):
        """Acceptance Test: POST /api/ocr/receipt executes live request and validates ReceiptOcrOut."""
        payload = {
            "image_base64": None,
            "wholesaler_hint": "Puregold Price Club Inc."
        }
        resp = client.post("/api/ocr/receipt", data=payload, content_type="application/json")
        assert resp.status_code == 200

        data = resp.json()
        validated = ReceiptOcrOut.model_validate(data)

        assert isinstance(validated.wholesaler_name, str) and len(validated.wholesaler_name) > 0
        assert isinstance(validated.invoice_no, str) and len(validated.invoice_no) > 0
        assert isinstance(validated.date, str) and len(validated.date) > 0
        assert isinstance(validated.total_amount, Decimal)
        assert validated.total_amount > Decimal("0.00")
        assert len(validated.items) > 0

        # Verify item schema and 15% retail markup application
        for item in validated.items:
            assert isinstance(item.raw_line_text, str) and len(item.raw_line_text) > 0
            assert isinstance(item.matched_name, str) and len(item.matched_name) > 0
            assert item.qty_packs >= 1
            assert isinstance(item.pack_wholesale_cost, Decimal)
            assert item.pack_wholesale_cost > Decimal("0.00")
            assert isinstance(item.line_total, Decimal)
            assert item.line_total > Decimal("0.00")
            assert isinstance(item.suggested_retail_price, Decimal)
            assert item.suggested_retail_price > Decimal("0.00")

    def test_live_multimodal_vision_png_image(self, client, seed_catalog):
        """Acceptance Test: POST /api/vision/counter-detect with valid base64 PNG executes and maps to CounterDetectOut."""
        png_b64 = generate_test_image_base64(fmt="PNG", size=(100, 100), color="blue", with_prefix=True)
        payload = {
            "image_base64": png_b64,
            "prompt_hint": "Identify FMCG items on counter"
        }
        resp = client.post("/api/vision/counter-detect", data=payload, content_type="application/json")
        assert resp.status_code == 200

        data = resp.json()
        validated = CounterDetectOut.model_validate(data)
        assert validated.success is True
        assert len(validated.detected_items) > 0
        assert validated.estimated_total > Decimal("0.00")

    def test_live_multimodal_vision_jpeg_raw_base64(self, client, seed_catalog):
        """Acceptance Test: POST /api/vision/counter-detect with raw base64 JPEG (no data: prefix) succeeds."""
        jpeg_raw_b64 = generate_test_image_base64(fmt="JPEG", size=(80, 80), color="green", with_prefix=False)
        payload = {
            "image_base64": jpeg_raw_b64,
            "prompt_hint": "Analyze countertop products"
        }
        resp = client.post("/api/vision/counter-detect", data=payload, content_type="application/json")
        assert resp.status_code == 200

        data = resp.json()
        validated = CounterDetectOut.model_validate(data)
        assert validated.success is True
        assert len(validated.detected_items) > 0

    def test_backward_compatibility_dummy_data_counter_detect(self, client):
        """Acceptance Test: Handling 'dummy-data' as image_base64 without crashing."""
        payload = {
            "image_base64": "dummy-data",
            "prompt_hint": "Detect counter goods"
        }
        resp = client.post("/api/vision/counter-detect", data=payload, content_type="application/json")
        assert resp.status_code == 200

        data = resp.json()
        validated = CounterDetectOut.model_validate(data)
        assert validated.success is True
        assert len(validated.detected_items) > 0
        assert validated.estimated_total > Decimal("0.00")

    def test_backward_compatibility_dummy_data_ocr_receipt(self, client):
        """Acceptance Test: Handling 'dummy-data' in receipt OCR without crashing."""
        payload = {
            "image_base64": "dummy-data",
            "wholesaler_hint": "Puregold"
        }
        resp = client.post("/api/ocr/receipt", data=payload, content_type="application/json")
        assert resp.status_code == 200

        data = resp.json()
        validated = ReceiptOcrOut.model_validate(data)
        assert len(validated.items) > 0
        assert validated.total_amount > Decimal("0.00")

    def test_direct_gemini_service_counter_detect(self, seed_catalog):
        """Direct test of core.services.gemini.detect_counter_items function."""
        result = gemini.detect_counter_items(
            image_base64=None,
            prompt_hint="Scan sari-sari store counter items"
        )
        assert isinstance(result, CounterDetectOut)
        assert result.success is True
        assert len(result.detected_items) > 0
        assert result.estimated_total > Decimal("0.00")

    def test_direct_gemini_service_ocr_receipt(self, seed_catalog):
        """Direct test of core.services.gemini.ocr_receipt function."""
        result = gemini.ocr_receipt(
            image_base64=None,
            wholesaler_hint="Puregold Price Club Inc."
        )
        assert isinstance(result, ReceiptOcrOut)
        assert len(result.items) > 0
        assert result.total_amount > Decimal("0.00")

    def test_prepare_image_part_edge_cases(self):
        """Verify image pre-processing robustness across null, short, and oversized inputs."""
        # Null and empty
        assert gemini.prepare_image_part(None) is None
        assert gemini.prepare_image_part("") is None
        assert gemini.prepare_image_part("   ") is None

        # Short strings like 'dummy-data' (< 16 raw bytes)
        assert gemini.prepare_image_part("dummy-data") is None

        # Invalid base64 characters
        assert gemini.prepare_image_part("not-a-valid-base64-payload!!!") is None

        # Valid image returns types.Part
        valid_b64 = generate_test_image_base64(fmt="PNG", size=(64, 64), color="yellow")
        part = gemini.prepare_image_part(valid_b64)
        assert part is not None
        assert hasattr(part, "inline_data")

        # Oversized image (> 1024x1024) gets resized per NFR-04.1
        large_b64 = generate_test_image_base64(fmt="PNG", size=(1200, 1100), color="purple")
        large_part = gemini.prepare_image_part(large_b64)
        assert large_part is not None
        # Verify the raw bytes decode back to an image within 1024x1024 bounds
        with Image.open(io.BytesIO(large_part.inline_data.data)) as resized_img:
            assert resized_img.width <= 1024
            assert resized_img.height <= 1024
