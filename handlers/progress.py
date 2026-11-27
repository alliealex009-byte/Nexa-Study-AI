"""Student progress analytics handler with Bot API 10.4 Progress Widget button."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from config import Settings
from database.progress import ProgressRepository
from keyboards.styles import styled_button, tg_emoji

router = Router(name="progress")


def _progress_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("Open Progress Widget", callback_data="widget:progress", style="success", emoji_key="widget", settings=settings),
            ],
            [
                styled_button("Random 10-Yr Prep", callback_data="pyq:random:all", style="primary", emoji_key="random", settings=settings),
                styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings),
            ],
        ]
    )


def _render_progress_report(summary: dict, settings: Settings | None = None) -> str:
    icon = tg_emoji("progress", settings)
    lines = [
        f"{icon} <b>Your NEXA STUDY AI Progress</b>\n",
        f"• Questions Attempted: <b>{summary['questions_attempted']}</b>",
        f"• Questions Solved: <b>{summary['questions_solved']}</b>",
        f"• Quizzes Completed: <b>{summary['quizzes_completed']}</b>",
        f"• Overall Quiz Accuracy: <b>{summary['quiz_accuracy']:.1f}%</b>",
        f"• Active Study Days: <b>{summary['active_days_count']}</b>",
    ]

    if summary["subjects"]:
        lines.append("\n📚 <b>Subject-wise Performance:</b>")
        for s in summary["subjects"]:
            acc_str = f"{s['accuracy']:.1f}% ({s['correct']}/{s['attempted']})" if s["accuracy"] is not None else "No MCQs yet"
            lines.append(f"• {s['subject']}: {acc_str} | Doubts solved: {s['doubts']}")

    if summary["weak_topics"]:
        lines.append("\n⚠️ <b>Weak Topics (&lt;60% accuracy — focus here):</b>")
        for topic in summary["weak_topics"]:
            lines.append(f"• {topic['topic']}: {topic['accuracy']:.1f}% ({topic['correct']}/{topic['attempted']})")
    else:
        lines.append("\n✅ No weak topics flagged yet — keep practicing quizzes!")

    if summary["recent_quizzes"]:
        lines.append("\n🕒 <b>Recent Quizzes:</b>")
        for q in reversed(summary["recent_quizzes"][-3:]):
            lines.append(f"• {q['date']} ({q['mode']}): {q['score']}/{q['total']} ({q['accuracy']:.1f}%)")

    return "\n".join(lines)


@router.message(Command("progress"))
async def cmd_progress(message: Message, progress: ProgressRepository, settings: Settings) -> None:
    """Show progress report via /progress command."""
    if not message.from_user:
        return
    summary = progress.get_summary(message.from_user.id)
    await message.answer(
        _render_progress_report(summary, settings),
        reply_markup=_progress_keyboard(settings),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:progress")
async def cb_progress(callback: CallbackQuery, progress: ProgressRepository, settings: Settings) -> None:
    """Show progress report via inline menu button."""
    summary = progress.get_summary(callback.from_user.id)
    if callback.message:
        await callback.message.answer(
            _render_progress_report(summary, settings),
            reply_markup=_progress_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer()
