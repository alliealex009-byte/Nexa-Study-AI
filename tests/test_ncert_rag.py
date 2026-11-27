"""Tests for pure-Python BM25 NCERT RAG service."""

from __future__ import annotations

import unittest
from pathlib import Path

from services.ncert import NCERTPassage, NCERTRAGService

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "ncert"


class TestNCERTRAG(unittest.TestCase):
    def setUp(self) -> None:
        self.rag = NCERTRAGService(DATA_DIR)

    def test_retrieves_mitochondria_passage_for_biology_query(self) -> None:
        hits = self.rag.retrieve("What are cristae and 70S ribosomes in mitochondria?", subject="biology")
        self.assertGreaterEqual(len(hits), 1)
        top_passage, score = hits[0]
        self.assertGreater(score, 0.0)
        self.assertEqual(top_passage.subject, "biology")
        self.assertIn("Cell: The Unit of Life", top_passage.chapter_title)

    def test_lists_chapters_by_subject(self) -> None:
        phy_chapters = self.rag.list_chapters(subject="physics")
        self.assertGreaterEqual(len(phy_chapters), 2)
        self.assertTrue(all(c["subject"] == "physics" for c in phy_chapters))

    def test_unverified_passage_does_not_claim_verified_page(self) -> None:
        p = NCERTPassage(
            passage_id="test",
            class_level=11,
            subject="biology",
            chapter_number=1,
            chapter_title="The Living World",
            section="1.1",
            page="12",
            content="Sample content",
            verified=False,
        )
        self.assertIn("Unverified", p.format_citation())


if __name__ == "__main__":
    unittest.main()
