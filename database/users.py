"""User profile and preference repository with in-memory fallback."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from database.mongo import MongoManager

logger = logging.getLogger(__name__)


class UserRepository:
    """Stores compact Telegram user profiles and study preferences."""

    def __init__(self, mongo: MongoManager) -> None:
        self._mongo = mongo
        self._memory: dict[int, dict[str, Any]] = {}

    def _default_user(self, user_id: int, first_name: str = "", username: str = "") -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "user_id": user_id,
            "first_name": first_name[:64],
            "username": (username or "")[:64],
            "target_exam": "NEET UG",
            "active_subject": "general",
            "explanation_mode": "standard",
            "created_at": now,
            "last_active_at": now,
        }

    def upsert_user(self, user_id: int, first_name: str = "", username: str = "") -> dict[str, Any]:
        """Register a new user or update last_active_at for an existing user."""
        now = datetime.now(timezone.utc)
        if self._mongo.is_connected:
            coll = self._mongo.db["users"]
            coll.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "first_name": first_name[:64],
                        "username": (username or "")[:64],
                        "last_active_at": now,
                    },
                    "$setOnInsert": {
                        "user_id": user_id,
                        "target_exam": "NEET UG",
                        "active_subject": "general",
                        "explanation_mode": "standard",
                        "created_at": now,
                    },
                },
                upsert=True,
            )
            doc = coll.find_one({"user_id": user_id}, {"_id": 0})
            if doc:
                return doc

        existing = self._memory.get(user_id)
        if existing is None:
            existing = self._default_user(user_id, first_name, username)
            self._memory[user_id] = existing
        else:
            existing["first_name"] = first_name[:64]
            existing["username"] = (username or "")[:64]
            existing["last_active_at"] = now
        return dict(existing)

    def get_user(self, user_id: int) -> dict[str, Any]:
        """Retrieve a user's preferences, creating defaults if missing."""
        if self._mongo.is_connected:
            doc = self._mongo.db["users"].find_one({"user_id": user_id}, {"_id": 0})
            if doc:
                return doc
        if user_id in self._memory:
            return dict(self._memory[user_id])
        return self.upsert_user(user_id)

    def update_preferences(
        self,
        user_id: int,
        *,
        active_subject: str | None = None,
        explanation_mode: str | None = None,
        target_exam: str | None = None,
    ) -> dict[str, Any]:
        """Update user study settings."""
        updates: dict[str, Any] = {"last_active_at": datetime.now(timezone.utc)}
        if active_subject is not None:
            updates["active_subject"] = active_subject
        if explanation_mode is not None:
            updates["explanation_mode"] = explanation_mode
        if target_exam is not None:
            updates["target_exam"] = target_exam

        if self._mongo.is_connected:
            self._mongo.db["users"].update_one(
                {"user_id": user_id},
                {"$set": updates, "$setOnInsert": {"user_id": user_id}},
                upsert=True,
            )
            doc = self._mongo.db["users"].find_one({"user_id": user_id}, {"_id": 0})
            if doc:
                return doc

        user = self._memory.setdefault(user_id, self._default_user(user_id))
        user.update(updates)
        return dict(user)
