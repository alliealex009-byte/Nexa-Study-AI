"""Lightweight pure-Python BM25 NCERT RAG engine (zero heavy vector DBs)."""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "is", "are", "was", "were", "a", "an", "of", "in", "to", "for", "on", "and", "or",
    "by", "with", "that", "this", "what", "which", "how", "why", "explain", "define", "from",
    "at", "as", "be", "it", "its", "into", "between", "about", "does", "do", "can", "of",
}


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) > 1 and tok not in _STOPWORDS]


@dataclass(frozen=True)
class NCERTPassage:
    """A single verified NCERT textbook passage with strict provenance metadata."""

    passage_id: str
    class_level: int
    subject: str
    chapter_number: int
    chapter_title: str
    section: str
    page: str
    content: str
    verified: bool = True

    def format_citation(self) -> str:
        """Return citation only when verified; never fabricate textbook references."""
        if not self.verified:
            return f"Class {self.class_level} {self.subject.title()} — {self.chapter_title} (Unverified page ref)"
        parts = [f"NCERT Class {self.class_level} {self.subject.title()}"]
        if self.chapter_number:
            parts.append(f"Ch. {self.chapter_number}: {self.chapter_title}")
        else:
            parts.append(self.chapter_title)
        if self.section:
            parts.append(f"Sec. {self.section}")
        if self.page:
            parts.append(f"p. {self.page}")
        return ", ".join(parts)


class NCERTRAGService:
    """In-memory BM25 retriever over local JSON NCERT material (<10 MB RAM)."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._passages: list[NCERTPassage] = []
        self._doc_tokens: list[Counter[str]] = []
        self._doc_lengths: list[int] = []
        self._df: Counter[str] = Counter()
        self._avgdl: float = 1.0
        self.reload()

    def reload(self) -> int:
        """Load all JSON NCERT passage files from data/ncert/."""
        self._passages.clear()
        self._doc_tokens.clear()
        self._doc_lengths.clear()
        self._df.clear()

        if not self._data_dir.exists():
            logger.info("NCERT directory %s does not exist yet.", self._data_dir)
            return 0

        for path in sorted(self._data_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                items = raw if isinstance(raw, list) else raw.get("passages", [])
                for item in items:
                    passage = NCERTPassage(
                        passage_id=str(item.get("id", "")),
                        class_level=int(item.get("class_level", 11)),
                        subject=str(item.get("subject", "biology")).strip().lower(),
                        chapter_number=int(item.get("chapter_number", 0)),
                        chapter_title=str(item.get("chapter_title", "")).strip(),
                        section=str(item.get("section", "")).strip(),
                        page=str(item.get("page", "")).strip(),
                        content=str(item.get("content", "")).strip(),
                        verified=bool(item.get("verified", True)),
                    )
                    if not passage.content:
                        continue
                    self._passages.append(passage)
                    tokens = _tokenize(f"{passage.chapter_title} {passage.section} {passage.content}")
                    counts = Counter(tokens)
                    self._doc_tokens.append(counts)
                    self._doc_lengths.append(len(tokens))
                    for tok in counts:
                        self._df[tok] += 1
            except Exception as exc:
                logger.warning("Failed to load NCERT file %s: %s", path.name, exc)

        if self._doc_lengths:
            self._avgdl = sum(self._doc_lengths) / len(self._doc_lengths)
        return len(self._passages)

    def list_chapters(self, subject: str | None = None, class_level: int | None = None) -> list[dict[str, object]]:
        """List available NCERT chapters filtered by subject and/or class."""
        seen: set[tuple[int, str, int, str]] = set()
        chapters: list[dict[str, object]] = []
        for p in self._passages:
            if subject and p.subject != subject.lower():
                continue
            if class_level and p.class_level != class_level:
                continue
            key = (p.class_level, p.subject, p.chapter_number, p.chapter_title)
            if key not in seen:
                seen.add(key)
                chapters.append(
                    {
                        "class_level": p.class_level,
                        "subject": p.subject,
                        "chapter_number": p.chapter_number,
                        "chapter_title": p.chapter_title,
                    }
                )
        chapters.sort(key=lambda c: (c["class_level"], c["subject"], c["chapter_number"]))
        return chapters

    def retrieve(
        self,
        query: str,
        *,
        subject: str | None = None,
        class_level: int | None = None,
        top_k: int = 2,
    ) -> list[tuple[NCERTPassage, float]]:
        """Retrieve top-k verified NCERT passages using BM25."""
        query_tokens = _tokenize(query)
        if not query_tokens or not self._passages:
            return []

        n_docs = len(self._passages)
        k1, b = 1.5, 0.75
        scored: list[tuple[NCERTPassage, float]] = []

        for idx, passage in enumerate(self._passages):
            if subject and subject != "general" and passage.subject != subject.lower():
                continue
            if class_level and passage.class_level != class_level:
                continue

            doc_counts = self._doc_tokens[idx]
            dl = self._doc_lengths[idx] or 1
            score = 0.0
            for tok in query_tokens:
                tf = doc_counts.get(tok, 0)
                if tf == 0:
                    continue
                df = self._df.get(tok, 0)
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                denom = tf + k1 * (1.0 - b + b * (dl / self._avgdl))
                score += idf * (tf * (k1 + 1.0)) / denom

            if score > 0.0:
                scored.append((passage, round(score, 4)))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    def build_context_block(self, query: str, subject: str | None = None, top_k: int = 2) -> tuple[str, list[str]]:
        """Format retrieved verified passages for injection into Ollama prompts."""
        hits = self.retrieve(query, subject=subject, top_k=top_k)
        if not hits:
            return "", []
        blocks: list[str] = []
        citations: list[str] = []
        for passage, _ in hits:
            citation = passage.format_citation()
            citations.append(citation)
            blocks.append(f"[{citation}]\n{passage.content}")
        return "\n\n".join(blocks), citations
