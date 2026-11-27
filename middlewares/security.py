"""Per-user sliding-window rate limiting and input sanitization utilities.

Navigation button taps use a generous limit (45/min) so students never hit false
rate-limit popups while browsing menus, while heavy AI/OCR requests enforce a
stricter 2-CPU server limit.
"""

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


def _is_heavy_ai_event(event: TelegramObject) -> bool:
    """Return True only for events that actually invoke Ollama AI or Tesseract OCR."""
    if isinstance(event, CallbackQuery):
        data = (getattr(event, "data", "") or "")
        # Only re-explain buttons invoke Ollama; menu/PYQ/quiz/NCERT taps are instant!
        return data.startswith("mode:")
    if isinstance(event, Message):
        if getattr(event, "photo", None) or getattr(event, "document", None):
            return True
        text = (getattr(event, "text", "") or "").strip()
        if text.startswith("/ask"):
            return True
        if text and not text.startswith("/"):
            return True
    return False


class RateLimitMiddleware(BaseMiddleware):
    """aiogram 3.x middleware with separate AI/OCR and light-navigation rate limits."""

    def __init__(
        self,
        ai_limiter: SlidingWindowRateLimiter,
        nav_limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        super().__init__()
        self._ai_limiter = ai_limiter
        self._nav_limiter = nav_limiter or SlidingWindowRateLimiter(max_requests=45, window_seconds=60)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is not None:
            is_ai = _is_heavy_ai_event(event)
            limiter = self._ai_limiter if is_ai else self._nav_limiter
            allowed, retry_after = limiter.check(user.id)
            if not allowed:
                notice = (
                    f"⏳ Please wait {retry_after}s before sending another AI question."
                    if is_ai
                    else f"⏳ Slow down a little — try again in {retry_after}s."
                )
                if isinstance(event, Message):
                    await event.answer(notice)
                elif isinstance(event, CallbackQuery):
                    await event.answer(notice, show_alert=True)
                return None
        return await handler(event, data)
