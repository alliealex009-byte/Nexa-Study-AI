"""Main menu inline keyboard with Bot API 9.4 colored buttons, premium emoji & Add to Group."""

from __future__ import annotations

from config import Settings
from keyboards.styles import styled_button

try:
    from aiogram.types import InlineKeyboardMarkup
except ImportError:  # pragma: no cover
    class InlineKeyboardMarkup:  # type: ignore[no-redef]
        def __init__(self, inline_keyboard: list) -> None:
            self.inline_keyboard = inline_keyboard


def exam_onboarding_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    """First-time DM onboarding keyboard asking student to pick NEET UG or JEE."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("NEET UG", callback_data="onboard:exam:NEET UG", style="success", emoji_key="biology", settings=settings),
                styled_button("JEE (Main & Adv)", callback_data="onboard:exam:JEE", style="primary", emoji_key="physics", settings=settings),
            ],
        ]
    )


def main_menu_keyboard(
    settings: Settings | None = None,
    bot_username: str = "",
) -> InlineKeyboardMarkup:
    """Build the polished NEXA STUDY AI main menu with colored buttons, premium emoji & Add to Group."""
    rows = [
        [
            styled_button("Biology", callback_data="submenu:subject:biology", style="success", emoji_key="biology", settings=settings),
            styled_button("Chemistry", callback_data="submenu:subject:chemistry", style="primary", emoji_key="chemistry", settings=settings),
        ],
        [
            styled_button("Physics", callback_data="submenu:subject:physics", style="primary", emoji_key="physics", settings=settings),
            styled_button("Solve from Image", callback_data="menu:image", style="success", emoji_key="image", settings=settings),
        ],
        [
            styled_button("10-Yr Random Prep", callback_data="pyq:random:all", style="success", emoji_key="random", settings=settings),
            styled_button("Auto Quiz Poll", callback_data="pyq:poll:all", style="primary", emoji_key="spark", settings=settings),
        ],
        [
            styled_button("NCERT Explorer", callback_data="menu:ncert", style="primary", emoji_key="ncert", settings=settings),
            styled_button("10-Yr PYQs", callback_data="menu:pyq", style="primary", emoji_key="pyq", settings=settings),
        ],
        [
            styled_button("Practice Quiz", callback_data="menu:quiz", style="success", emoji_key="quiz", settings=settings),
            styled_button("My Progress", callback_data="menu:progress", style="primary", emoji_key="progress", settings=settings),
        ],
        [
            styled_button("Settings", callback_data="menu:settings", emoji_key="settings", settings=settings),
            styled_button("Help", callback_data="menu:help", emoji_key="help", settings=settings),
        ],
    ]
    if bot_username:
        rows.append(
            [
                styled_button(
                    "➕ Add to Group",
                    url=f"https://t.me/{bot_username.lstrip('@')}?startgroup=true",
                    style="success",
                    settings=settings,
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Single-row colored keyboard returning to the main menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [styled_button("Main Menu", callback_data="menu:home", style="primary", emoji_key="home", settings=settings)]
        ]
    )
