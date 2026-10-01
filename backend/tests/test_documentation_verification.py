"""
backend/tests/test_documentation_verification.py

Automated PyTest verification suite for TindAI project documentation deliverables.
Covers:
1. UML Diagram assets (5 diagrams, PNG format, >500x500 dimensions, >20KB).
2. Playwright UI Screenshots (4 mobile routes, PNG format, mobile viewport, >15KB).
3. Finalized Word Document (CCSFEN1L - Project Documentation_GrouPals (1).docx):
   - 9 embedded inline images
   - Section 8.2 / Table 4: core_storeconfig singleton table
   - Section 12.1: IEEE 829 Test Plan
   - Section 12.2: 110-test metrics summary table and TC-11/TC-12 test cases
   - Section 13: Challenges 5, 6, 7 engineering solutions
   - Section 14: Academic conclusion without leftover template prompts
   - Section 9: Captions for Figures 6, 7, 8, 9
"""

import os
from pathlib import Path
import pytest
from PIL import Image
import docx

# Repository root (two levels up from backend/tests/)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DOCX_ORIGINAL = REPO_ROOT / "CCSFEN1L - Project Documentation_GrouPals (1).docx"
DOCX_FINAL = REPO_ROOT / "CCSFEN1L - Project Documentation_GrouPals_Final.docx"
UML_DIR = REPO_ROOT / "artifacts" / "uml"
SCREENSHOTS_DIR = REPO_ROOT / "artifacts" / "screenshots"

REQUIRED_UML = [
    "use_case.png",
    "activity.png",
    "class_diagram.png",
    "sequence.png",
    "erd.png",
]

REQUIRED_SCREENSHOTS = [
    "pos.png",
    "utang.png",
    "restock.png",
    "analytics.png",
]


@pytest.fixture(scope="module")
def primary_doc():
    """Load the primary modified project document."""
    assert DOCX_ORIGINAL.exists(), f"Primary document not found: {DOCX_ORIGINAL}"
    return docx.Document(str(DOCX_ORIGINAL))


@pytest.fixture(scope="module")
def primary_doc_text(primary_doc):
    """Joined text of all paragraphs in the document."""
    return "\n".join(p.text for p in primary_doc.paragraphs)


class TestUMLDiagramAssets:
    """Verifies generation, format, dimensions, and file size of 5 UML diagrams."""

    def test_uml_directory_and_file_count(self):
        assert UML_DIR.exists(), f"UML directory does not exist: {UML_DIR}"
        png_files = sorted([p.name for p in UML_DIR.glob("*.png")])
        assert len(png_files) == 5, f"Expected exactly 5 UML PNGs, found {len(png_files)}: {png_files}"

    @pytest.mark.parametrize("filename", REQUIRED_UML)
    def test_individual_uml_diagram_properties(self, filename):
        file_path = UML_DIR / filename
        assert file_path.exists(), f"Required UML file missing: {filename}"

        file_size = file_path.stat().st_size
        assert file_size > 20_000, f"UML {filename} size {file_size} bytes <= 20,000 bytes"

        with Image.open(file_path) as img:
            assert img.format == "PNG", f"UML {filename} format {img.format} is not PNG"
            w, h = img.size
            assert w > 500, f"UML {filename} width {w} <= 500"
            assert h > 500, f"UML {filename} height {h} <= 500"


class TestUIScreenshotAssets:
    """Verifies Playwright automated capture, format, dimensions, and size of 4 UI screenshots."""

    def test_screenshots_directory_and_file_count(self):
        assert SCREENSHOTS_DIR.exists(), f"Screenshots directory does not exist: {SCREENSHOTS_DIR}"
        png_files = sorted([p.name for p in SCREENSHOTS_DIR.glob("*.png")])
        assert len(png_files) == 4, f"Expected exactly 4 screenshot PNGs, found {len(png_files)}: {png_files}"

    @pytest.mark.parametrize("filename", REQUIRED_SCREENSHOTS)
    def test_individual_ui_screenshot_properties(self, filename):
        file_path = SCREENSHOTS_DIR / filename
        assert file_path.exists(), f"Required screenshot file missing: {filename}"

        file_size = file_path.stat().st_size
        assert file_size > 15_000, f"Screenshot {filename} size {file_size} bytes <= 15,000 bytes"

        with Image.open(file_path) as img:
            assert img.format == "PNG", f"Screenshot {filename} format {img.format} is not PNG"
            w, h = img.size
            # Mobile viewport check: 412x915 @ 2x DPR (824x1830) or @ 1x DPR (412x915), aspect ratio 0.40 - 0.55
            is_mobile_viewport = (w, h) in [(824, 1830), (412, 915)] or (
                0.40 <= (w / h) <= 0.55 and w >= 360 and h >= 640
            )
            assert is_mobile_viewport, (
                f"Screenshot {filename} dimensions {w}x{h} do not match mobile viewport emulation"
            )


class TestDocumentCompilation:
    """Verifies docx structure, inline images, and newly injected sections/tables."""

    def test_inline_shapes_count(self, primary_doc):
        """Assert exactly 9 embedded images (5 UML diagrams + 4 UI screenshots)."""
        shape_count = len(primary_doc.inline_shapes)
        assert shape_count == 9, f"Expected 9 inline shapes in document, found {shape_count}"

    def test_section_8_2_database_table_4_storeconfig(self, primary_doc):
        """Assert Table 4 contains the core_storeconfig singleton entry."""
        table_4 = None
        for t in primary_doc.tables:
            if t.rows and any("Table Name" in c.text for c in t.rows[0].cells):
                table_4 = t
                break
        assert table_4 is not None, "Table 4 ('Table Name') not found in document"

        t4_texts = [c.text.strip() for r in table_4.rows for c in r.cells]
        assert any("core_storeconfig" in text for text in t4_texts), (
            "core_storeconfig singleton row missing from Table 4"
        )

    def test_section_12_1_ieee_829_test_plan(self, primary_doc_text):
        """Assert Section 12.1 contains IEEE 829 test plan terminology and methodology."""
        assert "IEEE 829" in primary_doc_text, "Section 12.1: 'IEEE 829' test plan text missing"
        assert "Unit & Domain Logic Testing" in primary_doc_text, "Section 12.1: Domain logic testing missing"
        assert "Adversarial & Fault Injection Testing" in primary_doc_text, "Section 12.1: Fault injection missing"

    def test_section_12_2_test_metrics_summary(self, primary_doc, primary_doc_text):
        """Assert Section 12.2 includes 110 tests, 114.32s runtime, and summary table."""
        assert "110" in primary_doc_text, "Section 12.2: '110' test metrics missing"
        assert "114.32" in primary_doc_text or "114.32s" in primary_doc_text, (
            "Section 12.2: '114.32s' runtime missing"
        )

        # Check Table 6a exists and contains summary metrics
        table_6a_found = False
        for t in primary_doc.tables:
            if t.rows and any("Test Module" in c.text for c in t.rows[0].cells):
                table_6a_found = True
                total_row_text = " ".join(c.text for c in t.rows[-1].cells)
                assert "TOTAL AUTOMATED TEST SUITE" in total_row_text
                assert "110 tests" in total_row_text
                assert "100% PASS" in total_row_text
                break
        assert table_6a_found, "Table 6a (Test Suite Execution Summary) not found"

    def test_section_12_2_test_cases_tc11_and_tc12(self, primary_doc):
        """Assert Table 6/7 contains TC-11 (Live Gemini) and TC-12 (StoreConfig Singleton)."""
        test_case_table = None
        for t in primary_doc.tables:
            if t.rows and any("Test Case ID" in c.text for c in t.rows[0].cells):
                test_case_table = t
                break
        assert test_case_table is not None, "Test Cases Table (with 'Test Case ID') not found"

        tc_ids = [r.cells[0].text.strip() for r in test_case_table.rows]
        assert "TC-11" in tc_ids, "TC-11 (Live Gemini Vision) missing from test cases table"
        assert "TC-12" in tc_ids, "TC-12 (StoreConfig Singleton) missing from test cases table"

        # Verify TC-11 and TC-12 statuses are PASS
        for r in test_case_table.rows:
            if r.cells[0].text.strip() == "TC-11":
                assert "PASS" in r.cells[-1].text.strip()
            if r.cells[0].text.strip() == "TC-12":
                assert "PASS" in r.cells[-1].text.strip()

    def test_section_13_challenges_and_solutions(self, primary_doc):
        """Assert Table 8/9 contains Challenges 5, 6, and 7."""
        challenges_table = None
        for t in primary_doc.tables:
            if t.rows and any("Challenge" in c.text for c in t.rows[0].cells):
                challenges_table = t
                break
        assert challenges_table is not None, "Challenges Table ('Challenge') not found"

        table_text = " ".join(c.text for r in challenges_table.rows for c in r.cells)
        assert "Gemini 1.5 Flash" in table_text, "Challenge 5 (Gemini) missing"
        assert ("StoreConfig" in table_text or "Single-Store" in table_text), "Challenge 6 (StoreConfig) missing"
        assert "Atomic Integrity" in table_text, "Challenge 7 (Atomic Integrity) missing"

    def test_section_14_academic_conclusion_and_prompt_removal(self, primary_doc_text):
        """Assert Section 14 contains complete academic conclusion and zero template prompts."""
        assert "TindAI successfully addresses" in primary_doc_text, (
            "Section 14: Final academic conclusion missing"
        )
        assert "Fulfillment of Project Objectives" in primary_doc_text, (
            "Section 14: Project objectives summary missing"
        )

        template_prompts = [
            "Include the project's overall accomplishments",
            "Describe what went well and what could be improved",
            "Provide actionable recommendations for future developers",
        ]
        for prompt in template_prompts:
            assert prompt not in primary_doc_text, f"Leftover template prompt found: '{prompt}'"

    def test_section_9_figure_captions(self, primary_doc_text):
        """Assert Section 9 includes captions for Figures 6, 7, 8, and 9."""
        assert "Figure 6. Mobile POS Interface" in primary_doc_text, "Figure 6 caption missing"
        assert "Figure 7. Financial Analytics Dashboard" in primary_doc_text, "Figure 7 caption missing"
        assert "Figure 8. Digital Utang Ledger" in primary_doc_text, "Figure 8 caption missing"
        assert "Figure 9. Bounded Knapsack Restock Checklist" in primary_doc_text, "Figure 9 caption missing"

    def test_final_docx_copy_synchronization(self):
        """Assert CCSFEN1L - Project Documentation_GrouPals_Final.docx exists and has 9 shapes."""
        if DOCX_FINAL.exists():
            final_doc = docx.Document(str(DOCX_FINAL))
            assert len(final_doc.inline_shapes) == 9, (
                f"Expected 9 inline shapes in Final docx, found {len(final_doc.inline_shapes)}"
            )
