"""Middleware that automatically tracks active groups and DM users for Owner Panel stats."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from database.chats import ChatRepository
from database.users import UserRepository

try:
    from aiogram import BaseMiddleware
    from aiogram.types import CallbackQuery, Message, TelegramObject
except ImportError:  # pragma: no cover
    BaseMiddleware = object  # type: ignore[assignment,misc]
    CallbackQuery = object  # type: ignore[assignment,misc]
    Message = object  # type: ignore[assignment,misc]
    TelegramObject = object  # type: ignore[assignment,misc]


class ActivityTrackingMiddleware(BaseMiddleware):
    """Registers every active group/supergroup and DM user transparently."""

    def __init__(self, users: UserRepository, chats: ChatRepository) -> None:
        super().__init__()
        self._users = users
        self._chats = chats

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        chat = getattr(event, "chat", None)
        if chat is None and isinstance(event, CallbackQuery) and event.message:
            chat = event.message.chat

        if chat is not None and getattr(chat, "type", "") in {"group", "supergroup"}:
            self._chats.register_group(
                chat_id=chat.id,
                title=getattr(chat, "title", "") or "",
                chat_type=chat.type,
            )
        elif user is not None and not getattr(user, "is_bot", False):
            self._users.upsert_user(
                user_id=user.id,
                first_name=getattr(user, "first_name", "") or "",
                username=getattr(user, "username", "") or "",
            )

        return await handler(event, data)
