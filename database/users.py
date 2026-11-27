"""User profile and preference repository with NEET/JEE onboarding & owner stats."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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
            "exam_selected": False,
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
                        "exam_selected": False,
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
        exam_selected: bool | None = None,
    ) -> dict[str, Any]:
        """Update user study settings."""
        updates: dict[str, Any] = {"last_active_at": datetime.now(timezone.utc)}
        if active_subject is not None:
            updates["active_subject"] = active_subject
        if explanation_mode is not None:
            updates["explanation_mode"] = explanation_mode
        if target_exam is not None:
            updates["target_exam"] = target_exam
            if exam_selected is None:
                updates["exam_selected"] = True
        if exam_selected is not None:
            updates["exam_selected"] = exam_selected

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

    def get_all_user_ids(self) -> list[int]:
        """Return all registered DM user IDs for owner broadcasts."""
        if self._mongo.is_connected:
            cursor = self._mongo.db["users"].find({}, {"user_id": 1, "_id": 0})
            return [int(doc["user_id"]) for doc in cursor if "user_id" in doc]
        return list(self._memory.keys())

    def get_user_stats(self, now: datetime | None = None) -> dict[str, int]:
        """Return Owner Panel user counts: total, NEET, JEE, active today, active 7d."""
        dt = now or datetime.now(timezone.utc)
        day_cutoff = dt - timedelta(days=1)
        week_cutoff = dt - timedelta(days=7)

        if self._mongo.is_connected:
            coll = self._mongo.db["users"]
            total = int(coll.count_documents({}))
            neet = int(coll.count_documents({"target_exam": {"$regex": "^neet", "$options": "i"}}))
            jee = int(coll.count_documents({"target_exam": {"$regex": "^jee", "$options": "i"}}))
            active_24h = int(coll.count_documents({"last_active_at": {"$gte": day_cutoff}}))
            active_7d = int(coll.count_documents({"last_active_at": {"$gte": week_cutoff}}))
            return {
                "total_users": total,
                "neet_users": neet,
                "jee_users": jee,
                "active_24h": active_24h,
                "active_7d": active_7d,
            }

        docs = list(self._memory.values())
        return {
            "total_users": len(docs),
            "neet_users": sum(1 for d in docs if str(d.get("target_exam", "")).lower().startswith("neet")),
            "jee_users": sum(1 for d in docs if str(d.get("target_exam", "")).lower().startswith("jee")),
            "active_24h": sum(1 for d in docs if d.get("last_active_at", dt) >= day_cutoff),
            "active_7d": sum(1 for d in docs if d.get("last_active_at", dt) >= week_cutoff),
        }
