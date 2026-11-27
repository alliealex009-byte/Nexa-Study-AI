"""Tests for 10-year (2016-2025) PYQs, Bot API 9.4 colored/premium buttons, and Bot API 10.4 HTML widgets."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from config import Settings
from keyboards.main import main_menu_keyboard
from keyboards.styles import styled_button, tg_emoji
from keyboards.subjects import pyq_exam_keyboard, subject_submenu_keyboard, widget_menu_keyboard
from services.pyq import PYQService
from services.widgets import (
    build_formula_timer_widget_html,
    build_progress_widget_html,
    build_pyq_flashcard_widget_html,
    send_widget_or_fallback,
    validate_widget_html,
)

PYQ_DIR = Path(__file__).resolve().parent.parent / "data" / "pyq"


class TestTenYearPYQsAndPremiumUI(unittest.TestCase):
    def setUp(self) -> None:
        self.pyq = PYQService(PYQ_DIR)
        self.premium_settings = Settings(
            telegram_bot_token="dummy",
            enable_colored_buttons=True,
            enable_premium_emoji=True,
            premium_emoji_ids={"biology": "5368324170671202286", "pyq": "5368324170671202287"},
        )

    def test_ten_year_coverage_2016_to_2025_for_both_neet_and_jee(self) -> None:
        expected_years = list(range(2016, 2026))
        self.assertEqual(self.pyq.list_years(exam="NEET UG"), expected_years)
        self.assertEqual(self.pyq.list_years(exam="JEE"), expected_years)
        self.assertGreaterEqual(len(self.pyq.all_items), 40)

    def test_random_prep_works_for_neet_jee_and_any(self) -> None:
        q_neet = self.pyq.random_question(exam="NEET UG")
        q_jee = self.pyq.random_question(exam="JEE")
        q_any = self.pyq.random_question()
        self.assertIsNotNone(q_neet)
        self.assertIsNotNone(q_jee)
        self.assertIsNotNone(q_any)
        assert q_neet is not None and q_jee is not None
        self.assertEqual(q_neet.exam, "NEET UG")
        self.assertTrue(q_jee.exam.startswith("JEE"))

    def test_colored_button_and_premium_custom_emoji_fields(self) -> None:
        btn = styled_button(
            "Biology",
            callback_data="submenu:subject:biology",
            style="success",
            emoji_key="biology",
            settings=self.premium_settings,
        )
        self.assertEqual(getattr(btn, "style", None), "success")
        self.assertEqual(getattr(btn, "icon_custom_emoji_id", None), "5368324170671202286")
        self.assertEqual(btn.text, "Biology")

        tag = tg_emoji("biology", self.premium_settings)
        self.assertIn('<tg-emoji emoji-id="5368324170671202286">', tag)

    def test_submenus_include_colored_buttons(self) -> None:
        for kb in (
            main_menu_keyboard(self.premium_settings),
            subject_submenu_keyboard("biology", self.premium_settings),
            pyq_exam_keyboard(self.premium_settings),
            widget_menu_keyboard(self.premium_settings),
        ):
            flat = [btn for row in kb.inline_keyboard for btn in row]
            styles = {getattr(btn, "style", None) for btn in flat}
            self.assertTrue({"primary", "success"} & styles)

    def test_all_telegram_html_widgets_pass_bot_api_10_4_zlib_limit(self) -> None:
        sample_item = self.pyq.random_question()
        assert sample_item is not None
        widgets = [
            build_progress_widget_html(
                {
                    "questions_attempted": 25,
                    "questions_solved": 20,
                    "quizzes_completed": 5,
                    "quiz_accuracy": 80.0,
                    "active_days_count": 7,
                    "subjects": [{"subject": "Biology", "accuracy": 85.0, "doubts": 4}],
                    "weak_topics": [{"topic": "Physics: Rotational Motion", "accuracy": 40.0}],
                },
                student_name="Riya",
            ),
            build_pyq_flashcard_widget_html(sample_item),
            build_formula_timer_widget_html(),
        ]
        for w_html in widgets:
            ok, raw_len, comp_len = validate_widget_html(w_html)
            self.assertTrue(ok, msg=f"Widget exceeded Bot API 10.4 limit: raw={raw_len}B, zlib={comp_len}B")
            self.assertLessEqual(comp_len, 4096)


class TestWidgetDeliveryAndFallback(unittest.IsolatedAsyncioTestCase):
    async def test_private_dm_uses_send_widget_and_group_chat_falls_back(self) -> None:
        bot = AsyncMock()
        html_code = build_formula_timer_widget_html()

        used_widget = await send_widget_or_fallback(
            bot=bot,
            chat_id=123,
            chat_type="private",
            widget_html=html_code,
            caption="Formula Widget",
            fallback_text="Fallback",
        )
        self.assertTrue(used_widget)
        bot.send_widget.assert_awaited_once()

        bot.reset_mock()
        used_widget_group = await send_widget_or_fallback(
            bot=bot,
            chat_id=-100123456,
            chat_type="supergroup",
            widget_html=html_code,
            caption="Formula Widget",
            fallback_text="Fallback Group Card",
        )
        self.assertFalse(used_widget_group)
        bot.send_widget.assert_not_awaited()
        bot.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
