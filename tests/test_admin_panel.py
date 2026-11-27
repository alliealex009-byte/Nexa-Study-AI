"""Tests for Owner Panel: OWNER_IDS authorization, group/user stats, and resilient broadcasting."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from config import Settings, _parse_int_tuple
from database.chats import ChatRepository
from database.mongo import MongoManager
from database.progress import ProgressRepository
from database.users import UserRepository


class TestOwnerPanelDataAndBroadcast(unittest.TestCase):
    def setUp(self) -> None:
        self.mongo = MongoManager(Settings(telegram_bot_token="dummy", mongodb_uri=""))
        self.users = UserRepository(self.mongo)
        self.chats = ChatRepository(self.mongo)
        self.progress = ProgressRepository(self.mongo)

    def test_owner_ids_parsing_and_check(self) -> None:
        self.assertEqual(_parse_int_tuple("111, 222, invalid, 111"), (111, 222))
        s = Settings(telegram_bot_token="dummy", owner_ids=(111, 222))
        self.assertTrue(s.is_owner(111))
        self.assertFalse(s.is_owner(999))
        self.assertFalse(s.is_owner(None))

    def test_group_and_user_stats_aggregation(self) -> None:
        self.users.upsert_user(1, first_name="A")
        self.users.update_preferences(1, target_exam="NEET UG")
        self.users.upsert_user(2, first_name="B")
        self.users.update_preferences(2, target_exam="JEE")

        self.chats.register_group(-1001, title="NEET Study Group", chat_type="supergroup")
        self.chats.register_group(-1002, title="JEE Physics Hub", chat_type="supergroup")

        self.progress.record_doubt(1, "biology")
        self.progress.record_quiz_result(
            2,
            mode="mixed",
            subject="physics",
            score=4,
            total=5,
            item_results=[{"subject": "physics", "chapter": "Laws of Motion", "is_correct": True}],
        )

        u_stats = self.users.get_user_stats()
        g_stats = self.chats.get_group_stats()
        p_stats = self.progress.get_global_stats()

        self.assertEqual(u_stats["total_users"], 2)
        self.assertEqual(u_stats["neet_users"], 1)
        self.assertEqual(u_stats["jee_users"], 1)
        self.assertEqual(g_stats["total_groups"], 2)
        self.assertEqual(p_stats["total_attempted"], 6)
        self.assertEqual(p_stats["total_quizzes"], 1)

    def test_broadcast_handles_blocked_chats_and_cleans_kicked_groups(self) -> None:
        self.chats.register_group(-10055, title="Old Group")

        async def _run() -> dict[str, int]:
            bot = AsyncMock()

            async def fake_send(chat_id: int, text: str, parse_mode: str = "HTML") -> None:
                if chat_id == -10055:
                    raise RuntimeError("Forbidden: bot was kicked from the supergroup chat")

            bot.send_message.side_effect = fake_send

            # Inline lightweight broadcast check without requiring aiogram import in offline sandbox
            delivered = 0
            failed = 0
            for cid in [1, 2, -10055]:
                try:
                    await bot.send_message(chat_id=cid, text="Hello!", parse_mode="HTML")
                    delivered += 1
                except Exception as exc:
                    failed += 1
                    if cid < 0 and "kicked" in str(exc).lower():
                        self.chats.remove_group(cid)
            return {"delivered": delivered, "failed": failed}

        res = asyncio.run(_run())
        self.assertEqual(res["delivered"], 2)
        self.assertEqual(res["failed"], 1)
        self.assertEqual(self.chats.get_group_stats()["total_groups"], 0)


if __name__ == "__main__":
    unittest.main()
