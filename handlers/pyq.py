"""10-Year (2016–2025) NEET & JEE PYQ browser, random prep, and Group Chat Quiz Polls."""

from __future__ import annotations

import html as html_lib

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import Settings
from database.progress import ProgressRepository
from keyboards.main import back_to_menu_keyboard
from keyboards.styles import tg_emoji
from keyboards.subjects import (
    pyq_answer_keyboard,
    pyq_exam_keyboard,
    pyq_subject_keyboard,
    pyq_year_keyboard,
)
from services.pyq import PYQItem, PYQService

router = Router(name="pyq")


def format_pyq_html(q: PYQItem, settings: Settings | None = None) -> str:
    """Render a PYQ card cleanly in HTML with optional premium emoji."""
    icon = tg_emoji("pyq", settings)
    options_text = "\n".join(
        f"<b>{html_lib.escape(k)}.</b> {html_lib.escape(v)}" for k, v in sorted(q.options.items())
    )
    return (
        f"{icon} <b>{html_lib.escape(q.exam)} {q.year}</b> | "
        f"{html_lib.escape(q.subject.title())} — <i>{html_lib.escape(q.chapter)}</i>\n\n"
        f"{html_lib.escape(q.question)}\n\n"
        f"{options_text}\n\n"
        "Tap your answer below:"
    )


async def send_pyq_quiz_poll(bot: Bot, chat_id: int, q: PYQItem) -> None:
    """Send a native Telegram Quiz Poll (works seamlessly in Group Chats & DMs)."""
    sorted_keys = sorted(q.options.keys())
    options = [f"{k}. {q.options[k]}"[:100] for k in sorted_keys]
    correct_idx = sorted_keys.index(q.correct_option) if q.correct_option in sorted_keys else 0
    poll_question = f"[{q.exam} {q.year} | {q.subject.title()}] {q.question}"[:300]
    explanation = f"{q.explanation} ({q.source})"[:200]
    await bot.send_poll(
        chat_id=chat_id,
        question=poll_question,
        options=options,
        type="quiz",
        correct_option_id=correct_idx,
        explanation=explanation,
        is_anonymous=False,
    )


async def _send_random_prep(
    message: Message,
    pyq_service: PYQService,
    settings: Settings,
    *,
    exam: str | None = None,
    subject: str | None = None,
) -> None:
    """Send a random 10-year NEET/JEE prep question in either DM or Group Chat."""
    item = pyq_service.random_question(exam=exam, subject=subject)
    if not item:
        await message.answer(
            "No matching 10-year PYQs found. Run <code>scripts/import_opensource_pyqs.py</code> to import more.",
            parse_mode="HTML",
        )
        return
    await message.answer(
        format_pyq_html(item, settings),
        reply_markup=pyq_answer_keyboard(item.pyq_id, exam or item.exam, subject or item.subject, settings),
        parse_mode="HTML",
    )


@router.message(Command("random"))
@router.message(Command("prep"))
async def cmd_random_prep(message: Message, pyq_service: PYQService, settings: Settings) -> None:
    """Send a random 10-year NEET or JEE prep question (works in both DM and Group Chat)."""
    await _send_random_prep(message, pyq_service, settings)


@router.message(Command("neet"))
async def cmd_random_neet(message: Message, pyq_service: PYQService, settings: Settings) -> None:
    """Send a random 10-year (2016–2025) NEET UG question (DM & Group Chat)."""
    await _send_random_prep(message, pyq_service, settings, exam="NEET UG")


@router.message(Command("jee"))
async def cmd_random_jee(message: Message, pyq_service: PYQService, settings: Settings) -> None:
    """Send a random 10-year (2016–2025) JEE Main/Advanced question (DM & Group Chat)."""
    await _send_random_prep(message, pyq_service, settings, exam="JEE")


@router.message(Command("poll"))
async def cmd_group_quiz_poll(message: Message, bot: Bot, pyq_service: PYQService) -> None:
    """Send a native Telegram Quiz Poll from the 10-year NEET/JEE bank (ideal for Group Chats)."""
    arg = (message.text or "").split(maxsplit=1)
    exam_filter = None
    if len(arg) > 1:
        token = arg[1].strip().lower()
        if "neet" in token:
            exam_filter = "NEET UG"
        elif "jee" in token:
            exam_filter = "JEE"
    item = pyq_service.random_question(exam=exam_filter)
    if not item:
        await message.answer("No PYQs available to create a poll.")
        return
    await send_pyq_quiz_poll(bot, message.chat.id, item)


@router.callback_query(F.data == "menu:pyq")
async def cb_pyq_menu(callback: CallbackQuery, settings: Settings) -> None:
    """Show 10-Year PYQ exam choices."""
    icon = tg_emoji("pyq", settings)
    if callback.message:
        await callback.message.answer(
            f"{icon} <b>10-Year Previous Year Questions (2016–2025)</b>\n\nChoose an exam or launch random prep:",
            reply_markup=pyq_exam_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("pyq:exam:"))
async def cb_pyq_exam(callback: CallbackQuery, settings: Settings) -> None:
    """Show subject & year sub-menu for the selected exam."""
    exam = callback.data.split("pyq:exam:", 1)[1]
    if callback.message:
        await callback.message.answer(
            f"📝 <b>{html_lib.escape(exam)} (10-Year Bank)</b> — Choose a subject or year:",
            reply_markup=pyq_subject_keyboard(exam, settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("pyq:years:"))
async def cb_pyq_years(callback: CallbackQuery, pyq_service: PYQService, settings: Settings) -> None:
    """Show 10-year (2016–2025) year buttons for an exam."""
    exam = callback.data.split("pyq:years:", 1)[1]
    years = pyq_service.list_years(exam=exam)
    if not years:
        await callback.answer("No years loaded for this exam.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            f"📅 <b>{html_lib.escape(exam)} — Select Year:</b>",
            reply_markup=pyq_year_keyboard(exam, years, settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("pyq:year:"))
async def cb_pyq_by_year(callback: CallbackQuery, pyq_service: PYQService, settings: Settings) -> None:
    """Serve a random PYQ from the selected exam and year."""
    _, _, exam, year_str = callback.data.split(":", 3)
    item = pyq_service.random_question(exam=exam, year=int(year_str))
    if not item:
        await callback.answer("No PYQ found for that year.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            format_pyq_html(item, settings),
            reply_markup=pyq_answer_keyboard(item.pyq_id, exam, item.subject, settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("pyq:random:"))
async def cb_pyq_random(callback: CallbackQuery, pyq_service: PYQService, settings: Settings) -> None:
    """Serve a random 10-year prep question for any exam or a specific subject."""
    subject = callback.data.split("pyq:random:", 1)[1]
    item = pyq_service.random_question(subject=None if subject == "all" else subject)
    if not item:
        await callback.answer("No matching PYQs available.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            format_pyq_html(item, settings),
            reply_markup=pyq_answer_keyboard(item.pyq_id, item.exam, subject, settings),
            parse_mode="HTML",
        )
    await callback.answer("Random 10-yr prep!")


@router.callback_query(F.data.startswith("pyq:poll:"))
async def cb_pyq_poll(callback: CallbackQuery, bot: Bot, pyq_service: PYQService) -> None:
    """Send a native Telegram Quiz Poll into the current DM or Group Chat."""
    subject = callback.data.split("pyq:poll:", 1)[1]
    item = pyq_service.random_question(subject=None if subject in {"all", "mixed"} else subject)
    if not item or not callback.message:
        await callback.answer("No PYQ available for poll.", show_alert=True)
        return
    await send_pyq_quiz_poll(bot, callback.message.chat.id, item)
    await callback.answer("Quiz poll sent!")


@router.callback_query(F.data.startswith("pyq:list:"))
async def cb_pyq_question(callback: CallbackQuery, pyq_service: PYQService, settings: Settings) -> None:
    """Serve a verified PYQ with colored interactive A/B/C/D answer buttons."""
    _, _, exam, subject = callback.data.split(":", 3)
    item = pyq_service.random_question(
        exam=None if exam in {"all", "mixed"} else exam,
        subject=None if subject in {"all", "mixed"} else subject,
    )
    if not item:
        if callback.message:
            await callback.message.answer(
                f"No verified PYQs are loaded yet for <b>{html_lib.escape(exam)} — {html_lib.escape(subject.title())}</b>.",
                reply_markup=back_to_menu_keyboard(settings),
                parse_mode="HTML",
            )
        await callback.answer()
        return

    if callback.message:
        await callback.message.answer(
            format_pyq_html(item, settings),
            reply_markup=pyq_answer_keyboard(item.pyq_id, exam, subject, settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("pyq:ans:"))
async def cb_pyq_answer(
    callback: CallbackQuery,
    pyq_service: PYQService,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    """Evaluate student's PYQ answer and show verified explanation and source."""
    _, _, pyq_id, chosen = callback.data.split(":", 3)
    item = pyq_service.get_by_id(pyq_id)
    if not item:
        await callback.answer("Question not found.", show_alert=True)
        return

    is_correct = chosen.upper() == item.correct_option
    progress.record_quiz_result(
        callback.from_user.id,
        mode="pyq",
        subject=item.subject,
        score=1 if is_correct else 0,
        total=1,
        item_results=[
            {
                "subject": item.subject,
                "chapter": item.chapter,
                "is_correct": is_correct,
            }
        ],
    )

    who = html_lib.escape(callback.from_user.first_name or "Student")
    verdict = f"✅ <b>Correct, {who}!</b>" if is_correct else f"❌ <b>Not quite, {who}.</b> You chose <b>{html_lib.escape(chosen)}</b>."
    reply = (
        f"{verdict}\n"
        f"Correct Answer: <b>{html_lib.escape(item.correct_option)}. {html_lib.escape(item.options[item.correct_option])}</b>\n\n"
        f"📖 <b>Explanation:</b>\n{html_lib.escape(item.explanation)}\n\n"
        f"🔗 Source: {html_lib.escape(item.source)}"
    )
    if callback.message:
        await callback.message.answer(
            reply,
            reply_markup=pyq_answer_keyboard(item.pyq_id, item.exam, item.subject, settings),
            parse_mode="HTML",
        )
    await callback.answer("Correct!" if is_correct else f"Correct answer: {item.correct_option}")
