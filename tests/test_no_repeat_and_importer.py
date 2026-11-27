"""Tests for zero-repeat question engine, option balancing, LaTeX poll cleanup, and 5K importer."""

from __future__ import annotations

import unittest
from pathlib import Path

from ai.formatter import clean_latex_to_unicode
from config import Settings
from database.mongo import MongoManager
from database.progress import ProgressRepository
from scripts.import_opensource_pyqs import normalize_record
from services.pyq import PYQService, shuffle_options_safely

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

        self.assertEqual(len(set(seen_drawn)), pool_size)

        _, wrapped_after = self.pyq.random_question(
            exam="NEET UG",
            exclude_ids=self.progress.get_seen_pyq_ids(500),
        )
        self.assertTrue(wrapped_after)

    def test_option_shuffling_balances_all_a_datasets_and_preserves_positional_options(self) -> None:
        base_opts = {"A": "Correct Value", "B": "Wrong 1", "C": "Wrong 2", "D": "Wrong 3"}
        letters_seen = set()
        for idx in range(40):
            new_opts, new_correct = shuffle_options_safely(f"q-{idx}", base_opts, "A")
            self.assertEqual(new_opts[new_correct], "Correct Value")
            letters_seen.add(new_correct)
        # All 4 answer letters A, B, C, D should appear across 40 questions
        self.assertEqual(letters_seen, {"A", "B", "C", "D"})

        # Positional options like "All of the above" must NOT be shuffled
        pos_opts = {"A": "Opt 1", "B": "Opt 2", "C": "Both A and B", "D": "All of the above"}
        unchanged_opts, unchanged_corr = shuffle_options_safely("pos-1", pos_opts, "D")
        self.assertEqual(unchanged_opts, pos_opts)
        self.assertEqual(unchanged_corr, "D")

    def test_cleans_broken_huggingface_latex_for_polls(self) -> None:
        raw = r"The ionisation constant is $1.77 \times 10^(-5}$ at $298 \mathrm{~K}$."
        cleaned = clean_latex_to_unicode(raw)
        self.assertNotIn("$", cleaned)
        self.assertNotIn(r"\times", cleaned)
        self.assertNotIn(r"\mathrm", cleaned)
        self.assertIn("1.77 × 10⁻⁵", cleaned)
        self.assertIn("298 K", cleaned)

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
