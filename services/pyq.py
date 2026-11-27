"""Verified 10-Year (2016–2025) NEET UG, JEE Main, and JEE Advanced PYQ service with LaTeX cleaning, option shuffling & no-repeat."""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path

from ai.formatter import clean_latex_to_unicode

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")
_DUP_OPT_PREFIX_RE = re.compile(r"^\(?[A-D]\)?[\.\):]?\s*", re.IGNORECASE)
_TRAILING_OPT_TAG_RE = re.compile(r"\s+[A-D]$")
_POSITIONAL_OPT_RE = re.compile(
    r"(?i)\b(all\s+of\s+the\s+above|none\s+of\s+the\s+above|both\s+\(?[a-d]\)?\s+and\s+\(?[a-d]\)?|both\s+a\s+and\s+b)\b"
)
_STOP = {
    "the", "of", "in", "is", "are", "to", "for", "a", "an", "and", "or", "which",
    "following", "with", "from", "by", "as", "at", "on", "that", "this", "what",
}


def _norm_tokens(text: str) -> set[str]:
    return {t for t in _WORD_RE.findall(text.lower()) if len(t) > 2 and t not in _STOP}


def _clean_option_value(raw_val: str) -> str:
    cleaned = clean_latex_to_unicode(str(raw_val))
    cleaned = _DUP_OPT_PREFIX_RE.sub("", cleaned).strip()
    cleaned = _TRAILING_OPT_TAG_RE.sub("", cleaned).strip()
    return cleaned


def shuffle_options_safely(
    seed_key: str,
    options: dict[str, str],
    correct_option: str,
) -> tuple[dict[str, str], str]:
    """Deterministically shuffle A/B/C/D options and remap correct_option so 'A' isn't always right.

    Skips shuffling when any option references positions like 'Both A and B' or 'All of the above'.
    """
    keys = sorted(options.keys())
    if len(keys) < 2 or correct_option not in options:
        return options, correct_option

    if any(_POSITIONAL_OPT_RE.search(val) for val in options.values()):
        return options, correct_option

    pairs = [(k, options[k]) for k in keys]
    rng = random.Random(seed_key)
    rng.shuffle(pairs)

    new_options: dict[str, str] = {}
    new_correct = correct_option
    for new_key, (old_key, val) in zip(keys, pairs):
        new_options[new_key] = val
        if old_key == correct_option:
            new_correct = new_key
    return new_options, new_correct


@dataclass(frozen=True)
class PYQItem:
    """A verified previous-year exam question."""

    pyq_id: str
    exam: str
    year: int
    subject: str
    chapter: str
    question: str
    options: dict[str, str]
    correct_option: str
    explanation: str
    source: str
    verified: bool = True
    image_url: str = ""


class PYQService:
    """Loads, sanitizes, balances options, and queries verified PYQ JSON files."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._items: list[PYQItem] = []
        self._by_id: dict[str, PYQItem] = {}
        self._question_tokens: list[tuple[PYQItem, set[str]]] = []
        self.reload()

    def reload(self) -> int:
        """Load verified PYQs from data/pyq/*.json, auto-cleaning LaTeX and balancing A/B/C/D answers."""
        self._items.clear()
        self._by_id.clear()
        self._question_tokens.clear()
        if not self._data_dir.exists():
            logger.info("PYQ directory %s does not exist yet.", self._data_dir)
            return 0

        for path in sorted(self._data_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                entries = raw if isinstance(raw, list) else raw.get("questions", [])
                for entry in entries:
                    if not entry.get("verified", False):
                        continue
                    cleaned_opts = {
                        str(k).upper(): _clean_option_value(v)
                        for k, v in entry.get("options", {}).items()
                    }
                    if len(cleaned_opts) < 2 or any(len(v) < 1 for v in cleaned_opts.values()):
                        continue

                    pyq_id = str(entry["id"])
                    raw_correct = str(entry["correct_option"]).strip().upper()
                    if raw_correct not in cleaned_opts or pyq_id in self._by_id:
                        continue

                    # Shuffle options deterministically for imported datasets where 'A' is always correct
                    balanced_opts, balanced_correct = shuffle_options_safely(pyq_id, cleaned_opts, raw_correct)

                    item = PYQItem(
                        pyq_id=pyq_id,
                        exam=str(entry["exam"]).strip(),
                        year=int(entry["year"]),
                        subject=str(entry["subject"]).strip().lower(),
                        chapter=clean_latex_to_unicode(str(entry["chapter"])),
                        question=clean_latex_to_unicode(str(entry["question"])),
                        options=balanced_opts,
                        correct_option=balanced_correct,
                        explanation=clean_latex_to_unicode(str(entry["explanation"])),
                        source=str(entry["source"]).strip(),
                        verified=True,
                        image_url=str(entry.get("image_url", "")).strip(),
                    )
                    self._items.append(item)
                    self._by_id[item.pyq_id] = item
                    self._question_tokens.append((item, _norm_tokens(item.question)))
            except Exception as exc:
                logger.warning("Failed to load PYQ file %s: %s", path.name, exc)
        return len(self._items)

    @property
    def all_items(self) -> list[PYQItem]:
        return list(self._items)

    def get_by_id(self, pyq_id: str) -> PYQItem | None:
        return self._by_id.get(pyq_id)

    def list_exams(self) -> list[str]:
        return sorted({item.exam for item in self._items})

    @staticmethod
    def _exam_matches(item_exam: str, requested_exam: str | None) -> bool:
        if not requested_exam or requested_exam.lower() in {"all", "any", "mixed"}:
            return True
        req = requested_exam.strip().lower()
        actual = item_exam.strip().lower()
        if req == "jee":
            return actual.startswith("jee")
        if req == "neet":
            return actual.startswith("neet")
        return actual == req

    def list_years(self, exam: str | None = None) -> list[int]:
        return sorted({item.year for item in self._items if self._exam_matches(item.exam, exam)})

    def list_chapters(self, subject: str | None = None, exam: str | None = None) -> list[str]:
        chapters = {
            item.chapter
            for item in self._items
            if (not subject or subject in {"all", "mixed"} or item.subject == subject.lower())
            and self._exam_matches(item.exam, exam)
        }
        return sorted(chapters)

    def query(
        self,
        *,
        exam: str | None = None,
        subject: str | None = None,
        chapter: str | None = None,
        year: int | None = None,
        limit: int = 10,
        shuffle: bool = False,
        exclude_ids: set[str] | None = None,
    ) -> list[PYQItem]:
        all_matches = [
            item
            for item in self._items
            if self._exam_matches(item.exam, exam)
            and (not subject or subject.lower() in {"all", "mixed", "any"} or item.subject == subject.lower())
            and (not chapter or item.chapter.lower() == chapter.lower())
            and (not year or item.year == year)
        ]
        if not all_matches:
            return []

        if exclude_ids:
            unseen = [item for item in all_matches if item.pyq_id not in exclude_ids]
            if len(unseen) >= limit:
                pool = unseen
            elif unseen:
                seen_pool = [item for item in all_matches if item.pyq_id in exclude_ids]
                if shuffle:
                    random.shuffle(unseen)
                    random.shuffle(seen_pool)
                return (unseen + seen_pool)[:limit]
            else:
                pool = list(all_matches)
        else:
            pool = list(all_matches)

        if shuffle:
            random.shuffle(pool)
        return pool[:limit]

    def random_question(
        self,
        *,
        exam: str | None = None,
        subject: str | None = None,
        year: int | None = None,
        exclude_ids: set[str] | None = None,
    ) -> tuple[PYQItem | None, bool]:
        all_matches = self.query(exam=exam, subject=subject, year=year, limit=len(self._items) or 1, shuffle=False)
        if not all_matches:
            return None, False

        if exclude_ids:
            unseen = [item for item in all_matches if item.pyq_id not in exclude_ids]
            if unseen:
                return random.choice(unseen), False
            return random.choice(all_matches), True

        return random.choice(all_matches), False

    def find_matching_pyq(self, text: str, min_overlap: float = 0.65) -> PYQItem | None:
        query_tokens = _norm_tokens(text)
        if len(query_tokens) < 4:
            return None

        best_item: PYQItem | None = None
        best_ratio = 0.0
        for item, q_tokens in self._question_tokens:
            if not q_tokens:
                continue
            overlap = len(query_tokens & q_tokens) / len(q_tokens)
            if overlap >= min_overlap and overlap > best_ratio:
                best_ratio = overlap
                best_item = item
        return best_item
