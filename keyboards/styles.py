"""Bot API 9.4+ Premium Emoji & Colored Inline Button helpers.

Supports:
- `InlineKeyboardButton.style`: "primary" (blue), "success" (green), "danger" (red)
- `InlineKeyboardButton.icon_custom_emoji_id`: Telegram Premium custom emoji icon
- `<tg-emoji emoji-id="...">fallback</tg-emoji>` HTML tags in messages
"""

from __future__ import annotations

from typing import Any

from config import Settings

try:
    from aiogram.types import InlineKeyboardButton
except ImportError:  # pragma: no cover - allows offline unit tests without aiogram
    class InlineKeyboardButton:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

VALID_STYLES = {"primary", "success", "danger"}

FALLBACK_EMOJI: dict[str, str] = {
    "biology": "🧬",
    "chemistry": "⚗️",
    "physics": "📐",
    "image": "📸",
    "ncert": "📚",
    "pyq": "📝",
    "quiz": "🎯",
    "progress": "📊",
    "settings": "⚙️",
    "help": "ℹ️",
    "random": "🎲",
    "widget": "🧩",
    "home": "🏠",
    "spark": "✨",
    "check": "✅",
    "cancel": "🛑",
}


def tg_emoji(key: str, settings: Settings | None = None) -> str:
    """Return a Telegram Premium <tg-emoji> HTML tag if configured, else standard Unicode emoji."""
    fallback = FALLBACK_EMOJI.get(key, "✨")
    if settings and settings.enable_premium_emoji:
        emoji_id = settings.premium_emoji_ids.get(key, "").strip()
        if emoji_id:
            return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback


def styled_button(
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    style: str | None = None,
    emoji_key: str | None = None,
    settings: Settings | None = None,
) -> InlineKeyboardButton:
    """Build an InlineKeyboardButton with Bot API 9.4 color `style` and `icon_custom_emoji_id`.

    - If `settings.premium_emoji_ids[emoji_key]` is configured and `enable_premium_emoji` is True,
      sets `icon_custom_emoji_id` cleanly (so Telegram renders the animated Premium emoji before text).
    - Otherwise prefixes the label with the matching Unicode fallback emoji so every user gets a crisp icon.
    - Sets `style` ("primary", "success", or "danger") when `enable_colored_buttons` is enabled.
    """
    kwargs: dict[str, Any] = {}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url

    use_color = True if settings is None else settings.enable_colored_buttons
    if use_color and style in VALID_STYLES:
        kwargs["style"] = style

    custom_id = ""
    if emoji_key and settings and settings.enable_premium_emoji:
        custom_id = settings.premium_emoji_ids.get(emoji_key, "").strip()

    if custom_id:
        kwargs["icon_custom_emoji_id"] = custom_id
        kwargs["text"] = text
    else:
        prefix = FALLBACK_EMOJI.get(emoji_key or "", "")
        kwargs["text"] = f"{prefix} {text}".strip() if prefix and not text.startswith(prefix) else text

    return InlineKeyboardButton(**kwargs)
