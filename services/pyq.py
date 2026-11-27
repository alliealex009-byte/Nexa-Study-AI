"""Verified 10-Year (2016–2025) NEET UG, JEE Main, and JEE Advanced PYQ service."""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


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


class PYQService:
    """Loads and queries verified PYQ JSON files without ever fabricating exam metadata."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._items: list[PYQItem] = []
        self._by_id: dict[str, PYQItem] = {}
        self.reload()

    def reload(self) -> int:
        """Load verified PYQs from data/pyq/*.json (deduplicated by pyq_id)."""
        self._items.clear()
        self._by_id.clear()
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
                    item = PYQItem(
                        pyq_id=str(entry["id"]),
                        exam=str(entry["exam"]).strip(),
                        year=int(entry["year"]),
                        subject=str(entry["subject"]).strip().lower(),
                        chapter=str(entry["chapter"]).strip(),
                        question=str(entry["question"]).strip(),
                        options={str(k).upper(): str(v).strip() for k, v in entry["options"].items()},
                        correct_option=str(entry["correct_option"]).strip().upper(),
                        explanation=str(entry["explanation"]).strip(),
                        source=str(entry["source"]).strip(),
                        verified=True,
                    )
                    if item.correct_option not in item.options or item.pyq_id in self._by_id:
                        continue
                    self._items.append(item)
                    self._by_id[item.pyq_id] = item
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
        """List distinct available exam years (e.g. 2016–2025)."""
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
    ) -> list[PYQItem]:
        """Filter verified PYQs by exam, subject, chapter, and/or year."""
        results = [
            item
            for item in self._items
            if self._exam_matches(item.exam, exam)
            and (not subject or subject.lower() in {"all", "mixed", "any"} or item.subject == subject.lower())
            and (not chapter or item.chapter.lower() == chapter.lower())
            and (not year or item.year == year)
        ]
        if shuffle:
            random.shuffle(results)
        return results[:limit]

    def random_question(
        self,
        *,
        exam: str | None = None,
        subject: str | None = None,
        year: int | None = None,
    ) -> PYQItem | None:
        """Pick a single random prep question matching optional exam/subject/year filters."""
        pool = self.query(exam=exam, subject=subject, year=year, limit=len(self._items) or 1, shuffle=True)
        return pool[0] if pool else None
