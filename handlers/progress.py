"""Student progress analytics handler with Today/Weekly/Monthly stats, PNG focus graphic & motivation."""

from __future__ import annotations

import asyncio
import html as html_lib

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message

from config import Settings
from database.progress import ProgressRepository
from keyboards.styles import styled_button, tg_emoji
from services.analytics import pick_motivational_quote, render_progress_graphic

router = Router(name="progress")


def _progress_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("Random 10-Yr Prep", callback_data="pyq:random:all", style="success", emoji_key="random", settings=settings),
                styled_button("Practice Quiz", callback_data="menu:quiz", style="primary", emoji_key="quiz", settings=settings),
            ],
            [
                styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings),
            ],
        ]
    )


def _render_progress_report(summary: dict, settings: Settings | None = None) -> str:
    icon = tg_emoji("progress", settings)
    quote = pick_motivational_quote(
        accuracy=float(summary.get("quiz_accuracy", 0.0)),
        today_count=int(summary.get("today_questions", 0)),
    )
    lines = [
        f"{icon} <b>Your NEXA STUDY AI Progress</b>\n",
        f"📅 <b>Questions Done:</b> Today: <b>{summary['today_questions']}</b> | Weekly (7d): <b>{summary['weekly_questions']}</b> | Monthly (30d): <b>{summary['monthly_questions']}</b>",
        f"• All-Time Attempted: <b>{summary['questions_attempted']}</b> | Solved: <b>{summary['questions_solved']}</b>",
        f"• Quizzes Completed: <b>{summary['quizzes_completed']}</b> | Overall Accuracy: <b>{summary['quiz_accuracy']:.1f}%</b>",
        f"• Active Study Days: <b>{summary['active_days_count']}</b>",
    ]

    if summary["subjects"]:
        lines.append("\n📚 <b>Subject-wise Performance:</b>")
        for s in summary["subjects"]:
            acc_str = f"{s['accuracy']:.1f}% ({s['correct']}/{s['attempted']})" if s["accuracy"] is not None else "No MCQs yet"
            lines.append(f"• {html_lib.escape(str(s['subject']))}: {acc_str} | Doubts: {s['doubts']}")

    if summary["weak_topics"]:
        lines.append("\n⚠️ <b>Where to Work Next (&lt;60% accuracy):</b>")
        for topic in summary["weak_topics"]:
            lines.append(f"• {html_lib.escape(str(topic['topic']))}: {topic['accuracy']:.1f}% ({topic['correct']}/{topic['attempted']})")
    else:
        lines.append("\n✅ No weak chapters flagged yet — keep practicing quizzes!")

    lines.append(f"\n💡 <i>{html_lib.escape(quote)}</i>")
    return "\n".join(lines)


async def _send_progress_dashboard(
    message: Message,
    user_id: int,
    student_name: str,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    summary = progress.get_summary(user_id)
    caption = _render_progress_report(summary, settings)
    png_bytes = await asyncio.to_thread(render_progress_graphic, summary, student_name)
    photo = BufferedInputFile(png_bytes, filename="nexa_progress.png")
    await message.answer_photo(
        photo=photo,
        caption=caption[:1020],
        reply_markup=_progress_keyboard(settings),
        parse_mode="HTML",
    )


@router.message(Command("progress"))
async def cmd_progress(message: Message, progress: ProgressRepository, settings: Settings) -> None:
    """Show graphical progress report + Today/Weekly/Monthly stats via /progress."""
    if not message.from_user:
        return
    await _send_progress_dashboard(
        message,
        message.from_user.id,
        message.from_user.first_name or "Student",
        progress,
        settings,
    )


@router.callback_query(F.data == "menu:progress")
async def cb_progress(callback: CallbackQuery, progress: ProgressRepository, settings: Settings) -> None:
    """Show graphical progress report + Today/Weekly/Monthly stats via inline button."""
    if callback.message:
        await _send_progress_dashboard(
            callback.message,
            callback.from_user.id,
            callback.from_user.first_name or "Student",
            progress,
            settings,
        )
    await callback.answer()
