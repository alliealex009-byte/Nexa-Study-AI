"""Per-user sliding-window rate limiting and input sanitization utilities."""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

try:
    from aiogram import BaseMiddleware
    from aiogram.types import CallbackQuery, Message, TelegramObject
except ImportError:  # pragma: no cover - allows offline unit testing without aiogram
    BaseMiddleware = object  # type: ignore[assignment,misc]
    CallbackQuery = object  # type: ignore[assignment,misc]
    Message = object  # type: ignore[assignment,misc]
    TelegramObject = object  # type: ignore[assignment,misc]

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_user_text(text: str, max_chars: int = 1500) -> tuple[str, str | None]:
    """Validate and sanitize Telegram text input.

    Returns (cleaned_text, error_message_or_none).
    """
    if not text or not text.strip():
        return "", "Please enter a non-empty question or command."

    cleaned = _CONTROL_CHARS_RE.sub("", text).strip()
    if len(cleaned) < 2:
        return "", "Your message is too short. Please share a complete question."
    if len(cleaned) > max_chars:
        return (
            "",
            f"Your message is too long ({len(cleaned)} characters). "
            f"Please keep questions under {max_chars} characters.",
        )
    return cleaned, None


class SlidingWindowRateLimiter:
    """In-memory per-user sliding-window rate limiter."""

    def __init__(self, max_requests: int = 8, window_seconds: int = 60) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def check(self, user_id: int, now: float | None = None) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        ts = time.monotonic() if now is None else now
        bucket = self._hits[user_id]
        cutoff = ts - self._window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self._max_requests:
            retry_after = max(1, int(self._window_seconds - (ts - bucket[0])) + 1)
            return False, retry_after

        bucket.append(ts)
        return True, 0


class RateLimitMiddleware(BaseMiddleware):
    """aiogram 3.x middleware that enforces per-user rate limits."""

    def __init__(self, limiter: SlidingWindowRateLimiter) -> None:
        super().__init__()
        self._limiter = limiter

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is not None:
            allowed, retry_after = self._limiter.check(user.id)
            if not allowed:
                notice = (
                    f"⏳ You're sending requests a bit fast for our 2-CPU server. "
                    f"Please wait {retry_after}s and try again."
                )
                if isinstance(event, Message):
                    await event.answer(notice)
                elif isinstance(event, CallbackQuery):
                    await event.answer(notice, show_alert=True)
                return None
        return await handler(event, data)
