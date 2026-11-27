"""End-to-end tests for the ARM64 Tesseract OCR pipeline."""

from __future__ import annotations

import io
import unittest

from PIL import Image, ImageDraw, ImageFont

from services.ocr import OCRService


def _render_question_image(text: str) -> bytes:
    """Render a crisp synthetic question image to test real Tesseract OCR."""
    img = Image.new("RGB", (900, 220), color="white")
    draw = ImageDraw.Draw(img)
    font = None
    for font_path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            font = ImageFont.truetype(font_path, 34)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    draw.text((30, 70), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestOCRService(unittest.TestCase):
    def setUp(self) -> None:
        self.ocr = OCRService(min_confidence=45.0, lang="eng")

    def test_reads_clear_printed_physics_question(self) -> None:
        img_bytes = _render_question_image("Find acceleration if Force = 20 N and mass = 4 kg")
        result = self.ocr.extract_text(img_bytes)
        self.assertTrue(result.is_readable, msg=f"OCR failed: {result}")
        self.assertGreaterEqual(result.confidence, 45.0)
        self.assertIn("Force", result.text)
        self.assertIn("20", result.text)

    def test_rejects_blank_unreadable_image(self) -> None:
        img = Image.new("RGB", (400, 200), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = self.ocr.extract_text(buf.getvalue())
        self.assertFalse(result.is_readable)
        self.assertTrue(len(result.reason) > 0)

    def test_rejects_corrupt_bytes(self) -> None:
        result = self.ocr.extract_text(b"not-an-image")
        self.assertFalse(result.is_readable)
        self.assertIn("JPG or PNG", result.reason)


if __name__ == "__main__":
    unittest.main()
