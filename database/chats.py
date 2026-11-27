"""Group & supergroup chat registry for Owner Panel stats and group broadcasts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database.mongo import MongoManager


class ChatRepository:
    """Tracks Telegram groups and supergroups where the bot is active."""

    def __init__(self, mongo: MongoManager) -> None:
        self._mongo = mongo
        self._memory: dict[int, dict[str, Any]] = {}

    def register_group(self, chat_id: int, title: str = "", chat_type: str = "supergroup") -> dict[str, Any]:
        """Record or update a group/supergroup chat."""
        now = datetime.now(timezone.utc)
        clean_title = (title or "Unnamed Group")[:100]
        if self._mongo.is_connected:
            self._mongo.db["chats"].update_one(
                {"chat_id": chat_id},
                {
                    "$set": {
                        "title": clean_title,
                        "chat_type": chat_type,
                        "last_active_at": now,
                    },
                    "$setOnInsert": {
                        "chat_id": chat_id,
                        "added_at": now,
                    },
                },
                upsert=True,
            )
            doc = self._mongo.db["chats"].find_one({"chat_id": chat_id}, {"_id": 0})
            if doc:
                return doc

        existing = self._memory.get(chat_id)
        if existing is None:
            existing = {
                "chat_id": chat_id,
                "title": clean_title,
                "chat_type": chat_type,
                "added_at": now,
                "last_active_at": now,
            }
            self._memory[chat_id] = existing
        else:
            existing["title"] = clean_title
            existing["chat_type"] = chat_type
            existing["last_active_at"] = now
        return dict(existing)

    def remove_group(self, chat_id: int) -> None:
        """Remove a group if the bot was kicked or chat no longer exists."""
        self._memory.pop(chat_id, None)
        if self._mongo.is_connected:
            self._mongo.db["chats"].delete_one({"chat_id": chat_id})

    def get_all_group_ids(self) -> list[int]:
        """Return all registered group/supergroup chat IDs."""
        if self._mongo.is_connected:
            cursor = self._mongo.db["chats"].find({}, {"chat_id": 1, "_id": 0})
            return [int(doc["chat_id"]) for doc in cursor if "chat_id" in doc]
        return list(self._memory.keys())

    def get_group_stats(self) -> dict[str, Any]:
        """Return total group count and recent group titles."""
        if self._mongo.is_connected:
            total = self._mongo.db["chats"].count_documents({})
            recent_cursor = (
                self._mongo.db["chats"]
                .find({}, {"_id": 0, "chat_id": 1, "title": 1})
                .sort("last_active_at", -1)
                .limit(5)
            )
            recent = list(recent_cursor)
            return {"total_groups": int(total), "recent_groups": recent}

        groups = sorted(
            self._memory.values(),
            key=lambda g: g.get("last_active_at", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
        return {
            "total_groups": len(groups),
            "recent_groups": [{"chat_id": g["chat_id"], "title": g["title"]} for g in groups[:5]],
        }
