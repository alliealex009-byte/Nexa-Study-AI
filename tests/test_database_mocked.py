"""Tests for user, question history, and student progress repositories."""

from __future__ import annotations

import unittest

from config import Settings
from database.mongo import MongoManager
from database.progress import ProgressRepository
from database.questions import QuestionRepository
from database.users import UserRepository


class TestDatabaseRepositories(unittest.TestCase):
    def setUp(self) -> None:
        # Empty MONGODB_URI exercises deterministic in-memory fallback cleanly
        self.mongo = MongoManager(Settings(telegram_bot_token="dummy", mongodb_uri=""))
        self.users = UserRepository(self.mongo)
        self.questions = QuestionRepository(self.mongo)
        self.progress = ProgressRepository(self.mongo)

    def test_user_registration_and_preferences(self) -> None:
        u = self.users.upsert_user(42, first_name="Aarav", username="aarav_neet")
        self.assertEqual(u["target_exam"], "NEET UG")
        updated = self.users.update_preferences(42, active_subject="physics", explanation_mode="exam")
        self.assertEqual(updated["active_subject"], "physics")
        self.assertEqual(updated["explanation_mode"], "exam")

    def test_question_history_returns_latest(self) -> None:
        self.questions.save_question(42, "biology", "Q1", "A1")
        self.questions.save_question(42, "physics", "Q2", "A2")
        last = self.questions.get_last_question(42)
        self.assertIsNotNone(last)
        assert last is not None
        self.assertEqual(last["question"], "Q2")

    def test_progress_tracks_accuracy_and_weak_topics(self) -> None:
        self.progress.record_doubt(42, "biology", chapter="Cell: The Unit of Life")
        self.progress.record_quiz_result(
            42,
            mode="mixed",
            subject="mixed",
            score=1,
            total=3,
            item_results=[
                {"subject": "physics", "chapter": "Laws of Motion", "is_correct": False},
                {"subject": "physics", "chapter": "Laws of Motion", "is_correct": False},
                {"subject": "biology", "chapter": "Cell: The Unit of Life", "is_correct": True},
            ],
        )
        summary = self.progress.get_summary(42)
        self.assertEqual(summary["quizzes_completed"], 1)
        self.assertEqual(summary["questions_attempted"], 4)
        self.assertEqual(summary["weak_topics"][0]["topic"], "Physics: Laws of Motion")
        self.assertEqual(summary["weak_topics"][0]["accuracy"], 0.0)


if __name__ == "__main__":
    unittest.main()
