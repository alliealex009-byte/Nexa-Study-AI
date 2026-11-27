"""Regression tests for production fixes: LaTeX/HTML formatting, PYQ fast-match, 79 NCERT chapters, 100 PYQs, and welcome text."""

from __future__ import annotations

import unittest
from pathlib import Path

from ai.formatter import detect_subject_from_text, format_ai_response_for_telegram
from ai.verifier import extract_and_verify
from config import Settings
from services.ncert import NCERTRAGService
from services.pyq import PYQService

REPO = Path(__file__).resolve().parent.parent


class TestProductionFixes(unittest.TestCase):
    def setUp(self) -> None:
        self.ncert = NCERTRAGService(REPO / "data" / "ncert")
        self.pyq = PYQService(REPO / "data" / "pyq")

    def test_all_79_ncert_class_11_and_12_chapters_loaded(self) -> None:
        self.assertEqual(len(self.ncert.list_chapters(subject="physics", class_level=11)), 14)
        self.assertEqual(len(self.ncert.list_chapters(subject="physics", class_level=12)), 14)
        self.assertEqual(len(self.ncert.list_chapters(subject="chemistry", class_level=11)), 9)
        self.assertEqual(len(self.ncert.list_chapters(subject="chemistry", class_level=12)), 10)
        self.assertEqual(len(self.ncert.list_chapters(subject="biology", class_level=11)), 19)
        self.assertEqual(len(self.ncert.list_chapters(subject="biology", class_level=12)), 13)
        self.assertEqual(len(self.ncert.list_chapters()), 79)

    def test_100_verified_10yr_pyqs_loaded(self) -> None:
        self.assertGreaterEqual(len(self.pyq.all_items), 100)
        self.assertEqual(self.pyq.list_years(exam="NEET UG"), list(range(2016, 2026)))
        self.assertEqual(self.pyq.list_years(exam="JEE"), list(range(2016, 2026)))

    def test_latex_and_markdown_cleaned_to_telegram_html(self) -> None:
        raw = r"**Formula**: \[ \Delta_t = \frac{4}{9} \Delta_o \] and \boxed{A. \Delta_t = \frac{4}{9}\Delta_o}"
        formatted = format_ai_response_for_telegram(raw)
        self.assertIn("<b>Formula</b>", formatted)
        self.assertNotIn(r"\[", formatted)
        self.assertNotIn(r"\frac", formatted)
        self.assertNotIn(r"\boxed", formatted)
        self.assertIn("Δt", formatted)
        self.assertIn("(4/9)", formatted)

    def test_auto_subject_detection_and_verified_pyq_match_on_ocr_text(self) -> None:
        ocr_text = (
            "NEET UG 2024 | Chemistry — Coordination Compounds\n"
            "According to Crystal Field Theory, the splitting energy At for tetrahedral "
            "complexes relates to octahedral Ao as: A. At = (4/9) Ao B. At = (9/4) Ao"
        )
        self.assertEqual(detect_subject_from_text(ocr_text, fallback="physics"), "chemistry")
        matched = self.pyq.find_matching_pyq(ocr_text)
        self.assertIsNotNone(matched)
        assert matched is not None
        self.assertEqual(matched.correct_option, "A")
        self.assertEqual(matched.subject, "chemistry")

    def test_sympy_skips_trivial_mcq_option_fractions(self) -> None:
        res = extract_and_verify("Options: A. (4/9)  B. (9/4)  C. (2/3)")
        self.assertFalse(res.verified)

    def test_welcome_text_uses_aakash_ai_and_omits_widgets_line(self) -> None:
        start_src = (REPO / "handlers" / "start.py").read_text(encoding="utf-8")
        self.assertIn("AAKASH AI", start_src)
        self.assertNotIn("Telegram HTML Widgets", start_src)


if __name__ == "__main__":
    unittest.main()
