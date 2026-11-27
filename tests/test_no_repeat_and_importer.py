"""Tests for zero-repeat question engine and 5K HuggingFace chat-MCQ importer."""

from __future__ import annotations

import unittest
from pathlib import Path

from config import Settings
from database.mongo import MongoManager
from database.progress import ProgressRepository
from scripts.import_opensource_pyqs import normalize_record
from services.pyq import PYQService

PYQ_DIR = Path(__file__).resolve().parent.parent / "data" / "pyq"


class TestNoRepeatAndImporter(unittest.TestCase):
    def setUp(self) -> None:
        self.pyq = PYQService(PYQ_DIR)
        self.mongo = MongoManager(Settings(telegram_bot_token="dummy", mongodb_uri=""))
        self.progress = ProgressRepository(self.mongo)

    def test_zero_repeats_across_entire_neet_pool(self) -> None:
        neet_pool = self.pyq.query(exam="NEET UG", limit=1000)
        pool_size = len(neet_pool)
        self.assertGreaterEqual(pool_size, 50)

        seen_drawn: list[str] = []
        for _ in range(pool_size):
            seen = self.progress.get_seen_pyq_ids(500)
            item, wrapped = self.pyq.random_question(exam="NEET UG", exclude_ids=seen)
            self.assertIsNotNone(item)
            self.assertFalse(wrapped)
            assert item is not None
            seen_drawn.append(item.pyq_id)
            self.progress.mark_pyq_seen(500, item.pyq_id)

        # Every single question drawn across the entire pool is strictly unique!
        self.assertEqual(len(set(seen_drawn)), pool_size)

        # Next draw signals pool wrap-around cleanly instead of crashing
        _, wrapped_after = self.pyq.random_question(
            exam="NEET UG",
            exclude_ids=self.progress.get_seen_pyq_ids(500),
        )
        self.assertTrue(wrapped_after)

    def test_parses_huggingface_chat_formatted_mcq_row(self) -> None:
        hf_row = {
            "messages": [
                {"role": "system", "content": "You are an expert NEET tutor."},
                {
                    "role": "user",
                    "content": (
                        "[NEET PYQ | Chemistry]\n\n"
                        "What is the hybridisation of carbon in methane (CH4)?\n"
                        "A. sp\n"
                        "B. sp2\n"
                        "C. sp3\n"
                        "D. sp3d"
                    ),
                },
                {"role": "assistant", "content": "Methane has 4 sigma bonds, so carbon is sp3 hybridised. Correct answer is C."},
            ],
            "metadata": {
                "subject": "Chemistry",
                "chapter": "['Chemistry', 'Chemical Bonding', 'NEET']",
                "year": "2023",
                "correct_answer": "C",
                "source": "HuggingFace/catchshubham",
            },
        }
        rec = normalize_record(hf_row, idx=1, default_exam="NEET UG")
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["correct_option"], "C")
        self.assertEqual(rec["subject"], "chemistry")
        self.assertEqual(rec["year"], 2023)
        self.assertEqual(len(rec["options"]), 4)


if __name__ == "__main__":
    unittest.main()
