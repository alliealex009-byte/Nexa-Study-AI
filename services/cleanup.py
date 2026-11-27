"""Background auto-delete helper for cleaning up previous questions after 4 minutes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

AUTO_DELETE_SECONDS = 240  # 4 minutes
_PENDING_TASKS: set[asyncio.Task[Any]] = set()


async def _delete_after_delay(bot: Any, chat_id: int, message_id: int, delay_seconds: int) -> None:
    try:
        await asyncio.sleep(delay_seconds)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except asyncio.CancelledError:
        return
    except Exception as exc:
        # Ignore if message was already deleted or bot lacks delete permission in a group
        logger.debug("Auto-delete skipped for chat=%s msg=%s: %s", chat_id, message_id, exc)


def schedule_auto_delete(
    bot: Any,
    chat_id: int,
    message_id: int,
    delay_seconds: int = AUTO_DELETE_SECONDS,
) -> asyncio.Task[Any]:
    """Schedule deletion of a sent question or poll message after `delay_seconds` (default 4 min)."""
    task = asyncio.create_task(_delete_after_delay(bot, chat_id, message_id, delay_seconds))
    _PENDING_TASKS.add(task)
    task.add_done_callback(_PENDING_TASKS.discard)
    return task
