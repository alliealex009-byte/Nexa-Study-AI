"""Compact question history storage designed for 500 MB MongoDB free tier."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from database.mongo import DESCENDING, MongoManager

MAX_QUESTION_CHARS = 600
MAX_ANSWER_PREVIEW_CHARS = 800


class QuestionRepository:
    """Stores recent student doubts with compact previews for follow-up context."""

    def __init__(self, mongo: MongoManager, max_memory_per_user: int = 20) -> None:
        self._mongo = mongo
        self._max_memory_per_user = max_memory_per_user
        self._memory: dict[int, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=max_memory_per_user)
        )

    def save_question(
        self,
        user_id: int,
        subject: str,
        question: str,
        answer: str,
        source: str = "text",
        chapter: str = "",
    ) -> dict[str, Any]:
        """Store a compact question/answer record."""
        record = {
            "user_id": user_id,
            "subject": subject.lower(),
            "chapter": chapter[:80],
            "source": source,
            "question": question.strip()[:MAX_QUESTION_CHARS],
            "answer_preview": answer.strip()[:MAX_ANSWER_PREVIEW_CHARS],
            "created_at": datetime.now(timezone.utc),
        }
        if self._mongo.is_connected:
            self._mongo.db["questions"].insert_one(dict(record))
        self._memory[user_id].appendleft(record)
        return record

    def get_last_question(self, user_id: int) -> dict[str, Any] | None:
        """Fetch the most recent question for follow-up, simpler, or exam-mode re-explanations."""
        if self._memory[user_id]:
            return dict(self._memory[user_id][0])
        if self._mongo.is_connected:
            doc = self._mongo.db["questions"].find_one(
                {"user_id": user_id},
                {"_id": 0},
                sort=[("created_at", DESCENDING)],
            )
            if doc:
                return doc
        return None

    def get_recent_questions(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        """Return recent questions for a user."""
        if self._mongo.is_connected:
            cursor = (
                self._mongo.db["questions"]
                .find({"user_id": user_id}, {"_id": 0})
                .sort("created_at", DESCENDING)
                .limit(limit)
            )
            return list(cursor)
        return list(self._memory[user_id])[:limit]
