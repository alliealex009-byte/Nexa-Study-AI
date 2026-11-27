"""Tests for 45s/60s auto-next timers, NEET/JEE filtering, daily/weekly/monthly stats, PNG graphics, and Add to Group."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import Settings
from database.mongo import MongoManager
from database.progress import ProgressRepository
from database.users import UserRepository
from keyboards.main import main_menu_keyboard
from services.analytics import pick_motivational_quote, render_progress_graphic
from services.cleanup import AUTO_DELETE_SECONDS
from services.pyq import PYQService
from services.quiz import QuizService, question_time_limit_seconds

PYQ_DIR = Path(__file__).resolve().parent.parent / "data" / "pyq"


class TestTimersAnalyticsAndOnboarding(unittest.TestCase):
    def setUp(self) -> None:
        self.mongo = MongoManager(Settings(telegram_bot_token="dummy", mongodb_uri=""))
        self.users = UserRepository(self.mongo)
        self.progress = ProgressRepository(self.mongo)
        self.pyq = PYQService(PYQ_DIR)
        self.quiz = QuizService(self.pyq)

    def test_physics_60s_and_bio_chem_45s_timers(self) -> None:
        self.assertEqual(question_time_limit_seconds("physics"), 60)
        self.assertEqual(question_time_limit_seconds("Physics"), 60)
        self.assertEqual(question_time_limit_seconds("biology"), 45)
        self.assertEqual(question_time_limit_seconds("chemistry"), 45)
        self.assertEqual(AUTO_DELETE_SECONDS, 240)

    def test_quiz_strict_neet_vs_jee_filtering_and_timeout_auto_advance(self) -> None:
        neet_session = self.quiz.start_quiz(10, mode="mixed", exam="NEET UG", num_questions=5)
        self.assertIsNotNone(neet_session)
        assert neet_session is not None
        self.assertTrue(all(q.exam == "NEET UG" for q in neet_session.questions))

        # Timeout auto-advances question index from 0 to 1
        skipped, updated, finished = self.quiz.skip_timed_out_question(10, expected_index=0)
        self.assertTrue(skipped)
        self.assertFalse(finished)
        assert updated is not None
        self.assertEqual(updated.current_index, 1)
        self.assertEqual(updated.answers[0], "Timed Out")

        jee_session = self.quiz.start_quiz(11, mode="mixed", exam="JEE", num_questions=5)
        self.assertIsNotNone(jee_session)
        assert jee_session is not None
        self.assertTrue(all(q.exam.startswith("JEE") for q in jee_session.questions))

    def test_dm_exam_onboarding_flag(self) -> None:
        u = self.users.upsert_user(77, first_name="Jay")
        self.assertFalse(u["exam_selected"])
        updated = self.users.update_preferences(77, target_exam="JEE")
        self.assertTrue(updated["exam_selected"])
        self.assertEqual(updated["target_exam"], "JEE")

    def test_today_weekly_monthly_tracking_and_png_graphic(self) -> None:
        now = datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc)
        doc = self.progress._load(88)
        doc["daily_counts"] = {
            (now - timedelta(days=0)).strftime("%Y-%m-%d"): 4,   # Today
            (now - timedelta(days=3)).strftime("%Y-%m-%d"): 6,   # Within 7 days
            (now - timedelta(days=15)).strftime("%Y-%m-%d"): 10, # Within 30 days
            (now - timedelta(days=34)).strftime("%Y-%m-%d"): 20, # Older than 30 days
        }
        doc["chapters"] = {"Physics: Rotational Motion": {"attempted": 5, "correct": 1, "doubts": 0}}
        doc["subjects"] = {"Physics": {"attempted": 5, "correct": 1, "doubts": 2}}
        self.progress._save(88, doc)

        summary = self.progress.get_summary(88, now=now)
        self.assertEqual(summary["today_questions"], 4)
        self.assertEqual(summary["weekly_questions"], 10)
        self.assertEqual(summary["monthly_questions"], 20)

        png_bytes = render_progress_graphic(summary, student_name="Jay")
        self.assertTrue(png_bytes.startswith(b"\x89PNG"))
        self.assertGreater(len(png_bytes), 5000)
        self.assertTrue(len(pick_motivational_quote(20.0, 4)) > 10)

    def test_add_to_group_button_present_with_bot_username(self) -> None:
        kb = main_menu_keyboard(Settings(telegram_bot_token="dummy"), bot_username="NeetJeeSolverBot")
        urls = [getattr(btn, "url", None) for row in kb.inline_keyboard for btn in row]
        self.assertIn("https://t.me/NeetJeeSolverBot?startgroup=true", urls)


if __name__ == "__main__":
    unittest.main()
