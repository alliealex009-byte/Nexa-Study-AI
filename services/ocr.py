"""Lightweight ARM64-compatible OCR pipeline using Pillow and Tesseract."""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageOps

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from pytesseract import Output
except ImportError:  # pragma: no cover
    pytesseract = None  # type: ignore[assignment]
    Output = None  # type: ignore[assignment]


@dataclass(frozen=True)
class OCRResult:
    """Structured OCR output with explicit readability status."""

    text: str
    confidence: float
    is_readable: bool
    reason: str = ""
    word_count: int = 0


class OCRService:
    """Extracts printed/clear handwritten questions, equations, and diagram labels on ARM64 CPU."""

    def __init__(self, min_confidence: float = 45.0, lang: str = "eng") -> None:
        self._min_confidence = min_confidence
        self._lang = lang

    @staticmethod
    def _prepare_variants(image_bytes: bytes) -> list[Image.Image]:
        """Create two lightweight preprocessed variants (grayscale contrast + thresholded)."""
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            gray = img.convert("L")

            # Upscale small/mobile screenshots for sharper Tesseract character segmentation
            width, height = gray.size
            if width < 1000 and width > 0:
                scale = min(2.0, 1000.0 / width)
                gray = gray.resize(
                    (int(width * scale), int(height * scale)),
                    Image.Resampling.LANCZOS,
                )
            elif width > 2400:
                scale = 2400.0 / width
                gray = gray.resize(
                    (int(width * scale), int(height * scale)),
                    Image.Resampling.LANCZOS,
                )

            enhanced = ImageOps.autocontrast(gray, cutoff=2)
            enhanced = enhanced.filter(ImageFilter.SHARPEN)

            # Simple adaptive-like binarization via mean brightness threshold
            hist = enhanced.histogram()
            total_px = sum(hist) or 1
            mean_val = sum(i * c for i, c in enumerate(hist)) / total_px
            thresh = max(90, min(195, int(mean_val * 0.85)))
            binary = enhanced.point(lambda p: 255 if p > thresh else 0, mode="1").convert("L")

            return [enhanced, binary]

    @staticmethod
    def _clean_text(raw: str) -> str:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        non_empty = [line for line in lines if line]
        return "\n".join(non_empty).strip()

    def _run_tesseract(self, image: Image.Image, psm: int = 6) -> tuple[str, float, int]:
        if pytesseract is None or Output is None:
            raise RuntimeError("pytesseract is not installed.")
        config = f"--oem 3 --psm {psm}"
        data = pytesseract.image_to_data(
            image,
            lang=self._lang,
            config=config,
            output_type=Output.DICT,
        )
        words: list[str] = []
        confidences: list[float] = []
        for text_item, conf_raw in zip(data.get("text", []), data.get("conf", [])):
            token = (text_item or "").strip()
            try:
                conf = float(conf_raw)
            except (TypeError, ValueError):
                conf = -1.0
            if token and conf >= 0:
                words.append(token)
                confidences.append(conf)

        raw_text = pytesseract.image_to_string(image, lang=self._lang, config=config)
        cleaned = self._clean_text(raw_text)
        avg_conf = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
        return cleaned, avg_conf, len(words)

    def extract_text(self, image_bytes: bytes) -> OCRResult:
        """Run OCR on image bytes and refuse unreadable/low-confidence images honestly."""
        if not image_bytes:
            return OCRResult(
                text="",
                confidence=0.0,
                is_readable=False,
                reason="Empty image data received.",
            )

        if pytesseract is None:
            return OCRResult(
                text="",
                confidence=0.0,
                is_readable=False,
                reason="OCR engine (pytesseract/tesseract-ocr) is not installed on this server.",
            )

        try:
            variants = self._prepare_variants(image_bytes)
        except Exception as exc:
            logger.warning("Failed to decode uploaded image: %s", exc)
            return OCRResult(
                text="",
                confidence=0.0,
                is_readable=False,
                reason="Could not open this image file. Please send a standard JPG or PNG photo.",
            )

        best_text = ""
        best_conf = 0.0
        best_words = 0

        for variant in variants:
            try:
                text, conf, word_count = self._run_tesseract(variant, psm=6)
                # Score combines confidence and presence of readable alphanumeric tokens
                alnum_len = len(re.findall(r"[A-Za-z0-9]", text))
                best_alnum = len(re.findall(r"[A-Za-z0-9]", best_text))
                if (conf > best_conf and alnum_len >= 6) or (best_alnum < 6 and alnum_len > best_alnum):
                    best_text, best_conf, best_words = text, conf, word_count
            except Exception as exc:
                logger.warning("Tesseract pass failed: %s", exc)

        alnum_chars = len(re.findall(r"[A-Za-z0-9]", best_text))
        if alnum_chars < 6 or best_words < 2:
            return OCRResult(
                text=best_text,
                confidence=best_conf,
                is_readable=False,
                reason=(
                    "I could not read enough clear text from this image. "
                    "Please crop tightly around the question, use good lighting, and send a sharper photo."
                ),
                word_count=best_words,
            )

        if best_conf < self._min_confidence:
            return OCRResult(
                text=best_text,
                confidence=best_conf,
                is_readable=False,
                reason=(
                    f"OCR confidence was too low ({best_conf:.0f}%). I don't want to guess your question "
                    "incorrectly — please upload a clearer, straight-on photo or type the question."
                ),
                word_count=best_words,
            )

        return OCRResult(
            text=best_text,
            confidence=best_conf,
            is_readable=True,
            word_count=best_words,
        )
