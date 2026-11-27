"""Tests for verified PYQ repository and interactive quiz engine."""

from __future__ import annotations

import unittest
from pathlib import Path

from services.pyq import PYQService
from services.quiz import QuizService

PYQ_DIR = Path(__file__).resolve().parent.parent / "data" / "pyq"


class TestPYQAndQuiz(unittest.TestCase):
    def setUp(self) -> None:
        self.pyq = PYQService(PYQ_DIR)
        self.quiz = QuizService(self.pyq)

    def test_pyq_filters_by_exam_and_subject(self) -> None:
        neet_bio = self.pyq.query(exam="NEET UG", subject="biology")
        self.assertGreaterEqual(len(neet_bio), 2)
        self.assertTrue(all(item.exam == "NEET UG" and item.subject == "biology" for item in neet_bio))

    def test_quiz_full_lifecycle_and_scoring(self) -> None:
        session = self.quiz.start_quiz(user_id=999, mode="mixed", num_questions=3)
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(len(session.questions), 3)

        # Answer first two correctly, third wrongly
        for idx, q in enumerate(session.questions):
            choice = q.correct_option if idx < 2 else ("A" if q.correct_option != "A" else "B")
            accepted, _, finished = self.quiz.submit_answer(999, choice)
            self.assertTrue(accepted)
            self.assertEqual(finished, idx == 2)

        report = self.quiz.finalize_session(999)
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report["score"], 2)
        self.assertEqual(report["total"], 3)
        self.assertAlmostEqual(report["accuracy"], 66.7, places=1)
        self.assertEqual(len(report["items"]), 3)


if __name__ == "__main__":
    unittest.main()
