"""MongoDB connection manager optimized for 500 MB free-tier storage."""

from __future__ import annotations

import logging
from typing import Any

from config import Settings

logger = logging.getLogger(__name__)

try:
    from pymongo import ASCENDING, DESCENDING, MongoClient
    from pymongo.errors import PyMongoError
except ImportError:  # pragma: no cover - allows offline unit testing without pymongo
    ASCENDING = 1
    DESCENDING = -1
    MongoClient = None  # type: ignore[assignment]
    PyMongoError = Exception  # type: ignore[assignment,misc]


class MongoManager:
    """Manages external MongoDB connection, timeouts, and storage-efficient indexes."""

    def __init__(self, settings: Settings) -> None:
        self._uri = settings.mongodb_uri
        self._db_name = settings.mongodb_db_name
        self._timeout_ms = settings.mongodb_timeout_ms
        self._question_ttl_days = settings.question_ttl_days
        self._client: Any = None
        self._db: Any = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._db is not None

    @property
    def db(self) -> Any:
        return self._db

    def connect(self) -> bool:
        """Connect to external MongoDB with strict timeouts and create compact indexes."""
        if not self._uri:
            logger.info("MONGODB_URI not set; running in memory-only mode (Phase 1 compatible).")
            return False

        if MongoClient is None:
            logger.warning("pymongo is not installed; running in memory-only mode.")
            return False

        try:
            self._client = MongoClient(
                self._uri,
                serverSelectionTimeoutMS=self._timeout_ms,
                connectTimeoutMS=self._timeout_ms,
                socketTimeoutMS=self._timeout_ms * 2,
                maxPoolSize=5,
                retryWrites=True,
            )
            self._client.admin.command("ping")
            self._db = self._client[self._db_name]
            self._ensure_indexes()
            self._connected = True
            logger.info("Connected to MongoDB database '%s'.", self._db_name)
            return True
        except PyMongoError as exc:
            logger.warning("MongoDB connection failed; falling back to in-memory mode: %s", exc)
            self._connected = False
            self._db = None
            return False

    def _ensure_indexes(self) -> None:
        """Create minimal, high-value indexes to keep 500 MB storage lean."""
        if self._db is None:
            return
        self._db["users"].create_index([("user_id", ASCENDING)], unique=True)
        self._db["chats"].create_index([("chat_id", ASCENDING)], unique=True)
        self._db["questions"].create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
        self._db["questions"].create_index(
            [("created_at", ASCENDING)],
            expireAfterSeconds=self._question_ttl_days * 86400,
        )
        self._db["progress"].create_index([("user_id", ASCENDING)], unique=True)

    def close(self) -> None:
        """Close the MongoDB client cleanly."""
        if self._client is not None:
            self._client.close()
        self._connected = False
        self._db = None
