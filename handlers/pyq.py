"""10-Year (2016–2025) NEET & JEE PYQ browser, auto-advancing Quiz Polls (45s/60s), and 4-min cleanup."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from config import Settings
from database.progress import ProgressRepository
from database.users import UserRepository
from keyboards.main import back_to_menu_keyboard
from keyboards.styles import styled_button, tg_emoji
from keyboards.subjects import (
    pyq_answer_keyboard,
    pyq_exam_keyboard,
    pyq_subject_keyboard,
    pyq_year_keyboard,
)
from services.cleanup import AUTO_DELETE_SECONDS, schedule_auto_delete
from services.pyq import PYQItem, PYQService
from services.quiz import question_time_limit_seconds

logger = logging.getLogger(__name__)
router = Router(name="pyq")

# Active auto-advancing poll marathon tasks per chat_id
_ACTIVE_POLL_LOOPS: dict[int, asyncio.Task] = {}


def _resolve_user_exam(users: UserRepository, user_id: int, explicit_exam: str | None = None) -> str | None:
    """Honor explicit exam command (/neet, /jee); otherwise filter strictly by student's saved exam."""
    if explicit_exam and explicit_exam.lower() not in {"all", "any", "mixed"}:
        return explicit_exam
    user = users.get_user(user_id)
    saved = str(user.get("target_exam", "")).strip()
    if saved.lower().startswith("jee"):
        return "JEE"
    if saved.lower().startswith("neet"):
        return "NEET UG"
    return None


def format_pyq_html(q: PYQItem, settings: Settings | None = None) -> str:
    """Render a PYQ card cleanly in HTML with its 45s/60s target timer."""
    icon = tg_emoji("pyq", settings)
    secs = question_time_limit_seconds(q.subject)
    options_text = "\n".join(
        f"<b>{html_lib.escape(k)}.</b> {html_lib.escape(v)}" for k, v in sorted(q.options.items())
    )
    return (
        f"{icon} <b>{html_lib.escape(q.exam)} {q.year}</b> | "
        f"{html_lib.escape(q.subject.title())} — <i>{html_lib.escape(q.chapter)}</i>\n"
        f"⏱️ Target Time: <b>{secs}s</b>\n\n"
        f"{html_lib.escape(q.question)}\n\n"
        f"{options_text}\n\n"
        "Tap your answer below (next question loads automatically!):"
    )


async def send_pyq_quiz_poll(bot: Bot, chat_id: int, q: PYQItem, index: int = 1, total: int = 1) -> None:
    """Send a native Telegram Quiz Poll with 60s Physics / 45s Bio & Chem timer & 4-min auto-delete."""
    sorted_keys = sorted(q.options.keys())
    options = [f"{k}. {q.options[k]}"[:100] for k in sorted_keys]
    correct_idx = sorted_keys.index(q.correct_option) if q.correct_option in sorted_keys else 0
    open_period = question_time_limit_seconds(q.subject)
    prefix = f"[{index}/{total} • {q.exam} {q.year} • {open_period}s] " if total > 1 else f"[{q.exam} {q.year} • {open_period}s] "
    poll_question = f"{prefix}{q.question}"[:300]
    explanation = f"{q.explanation} ({q.source})"[:200]
    sent = await bot.send_poll(
        chat_id=chat_id,
        question=poll_question,
        options=options,
        type="quiz",
        correct_option_id=correct_idx,
        explanation=explanation,
        is_anonymous=False,
        open_period=open_period,
    )
    schedule_auto_delete(bot, chat_id, sent.message_id, AUTO_DELETE_SECONDS)


async def _run_auto_poll_series(
    bot: Bot,
    chat_id: int,
    items: list[PYQItem],
    settings: Settings,
) -> None:
    """Automatically send the next Quiz Poll after each 45s/60s poll timer closes."""
    total = len(items)
    try:
        for idx, item in enumerate(items, start=1):
            await send_pyq_quiz_poll(bot, chat_id, item, index=idx, total=total)
            if idx < total:
                wait_secs = question_time_limit_seconds(item.subject) + 3
                await asyncio.sleep(wait_secs)
        await bot.send_message(
            chat_id=chat_id,
            text="🏁 <b>Auto-Poll Session Complete!</b> Tap /poll anytime for another round.",
            reply_markup=back_to_menu_keyboard(settings),
            parse_mode="HTML",
        )
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.warning("Auto-poll series interrupted in chat %s: %s", chat_id, exc)
    finally:
        _ACTIVE_POLL_LOOPS.pop(chat_id, None)


async def start_auto_poll_series(
    bot: Bot,
    chat_id: int,
    pyq_service: PYQService,
    settings: Settings,
    *,
    exam: str | None = None,
    subject: str | None = None,
    count: int = 5,
) -> bool:
    """Start a 5-question auto-advancing Quiz Poll marathon in DM or Group Chat."""
    existing = _ACTIVE_POLL_LOOPS.pop(chat_id, None)
    if existing and not existing.done():
        existing.cancel()

    items = pyq_service.query(exam=exam, subject=subject, limit=count, shuffle=True)
    if not items:
        return False

    stop_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [styled_button("Stop Auto-Poll", callback_data="pyq:stop_poll", style="danger", emoji_key="cancel", settings=settings)]
        ]
    )
    exam_tag = exam or "NEET/JEE"
    intro = await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⚡ <b>Starting {len(items)}-Question Auto-Poll ({html_lib.escape(exam_tag)})</b>\n"
            "⏱️ <b>45s</b> for Bio/Chem • <b>60s</b> for Physics\n"
            "Next poll arrives automatically when time ends! Old polls auto-delete after 4 min."
        ),
        reply_markup=stop_kb,
        parse_mode="HTML",
    )
    schedule_auto_delete(bot, chat_id, intro.message_id, AUTO_DELETE_SECONDS)
    _ACTIVE_POLL_LOOPS[chat_id] = asyncio.create_task(_run_auto_poll_series(bot, chat_id, items, settings))
    return True


async def _send_random_prep(
    message: Message,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    settings: Settings,
    *,
    exam: str | None = None,
    subject: str | None = None,
) -> None:
    """Send a random exam-filtered 10-year PYQ with 4-minute auto-delete."""
    user_id = message.from_user.id if message.from_user else 0
    resolved_exam = _resolve_user_exam(users, user_id, explicit_exam=exam)
    item = pyq_service.random_question(exam=resolved_exam, subject=subject)
    if not item:
        await message.answer(
            "No matching 10-year PYQs found. Run <code>scripts/import_opensource_pyqs.py</code> to import more.",
            parse_mode="HTML",
        )
        return
    sent = await message.answer(
        format_pyq_html(item, settings),
        reply_markup=pyq_answer_keyboard(item.pyq_id, resolved_exam or item.exam, subject or "mixed", settings),
        parse_mode="HTML",
    )
    schedule_auto_delete(bot, sent.chat.id, sent.message_id, AUTO_DELETE_SECONDS)


@router.message(Command("random"))
@router.message(Command("prep"))
async def cmd_random_prep(
    message: Message,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    settings: Settings,
) -> None:
    """Send a random 10-year prep question matching the student's NEET/JEE selection."""
    await _send_random_prep(message, bot, pyq_service, users, settings)


@router.message(Command("neet"))
async def cmd_random_neet(
    message: Message,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    settings: Settings,
) -> None:
    """Send a random 10-year (2016–2025) NEET UG question (DM & Group Chat)."""
    await _send_random_prep(message, bot, pyq_service, users, settings, exam="NEET UG")


@router.message(Command("jee"))
async def cmd_random_jee(
    message: Message,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    settings: Settings,
) -> None:
    """Send a random 10-year (2016–2025) JEE Main/Advanced question (DM & Group Chat)."""
    await _send_random_prep(message, bot, pyq_service, users, settings, exam="JEE")


@router.message(Command("poll"))
async def cmd_group_quiz_poll(
    message: Message,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    settings: Settings,
) -> None:
    """Start an auto-advancing 5-question Telegram Quiz Poll session (45s Bio/Chem, 60s Physics)."""
    arg = (message.text or "").split(maxsplit=1)
    explicit_exam = None
    if len(arg) > 1:
        token = arg[1].strip().lower()
        if "neet" in token:
            explicit_exam = "NEET UG"
        elif "jee" in token:
            explicit_exam = "JEE"
    user_id = message.from_user.id if message.from_user else 0
    resolved_exam = _resolve_user_exam(users, user_id, explicit_exam=explicit_exam)
    started = await start_auto_poll_series(bot, message.chat.id, pyq_service, settings, exam=resolved_exam)
    if not started:
        await message.answer("No PYQs available to create a poll.")


@router.callback_query(F.data == "pyq:stop_poll")
async def cb_stop_poll(callback: CallbackQuery) -> None:
    """Stop the active auto-advancing poll session in this chat."""
    if callback.message:
        task = _ACTIVE_POLL_LOOPS.pop(callback.message.chat.id, None)
        if task and not task.done():
            task.cancel()
        await callback.message.answer("🛑 Auto-Poll session stopped.")
    await callback.answer("Stopped")


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
async def cb_pyq_by_year(
    callback: CallbackQuery,
    bot: Bot,
    pyq_service: PYQService,
    settings: Settings,
) -> None:
    """Serve a random PYQ from the selected exam and year with 4-min auto-delete."""
    _, _, exam, year_str = callback.data.split(":", 3)
    item = pyq_service.random_question(exam=exam, year=int(year_str))
    if not item:
        await callback.answer("No PYQ found for that year.", show_alert=True)
        return
    if callback.message:
        sent = await callback.message.answer(
            format_pyq_html(item, settings),
            reply_markup=pyq_answer_keyboard(item.pyq_id, exam, item.subject, settings),
            parse_mode="HTML",
        )
        schedule_auto_delete(bot, sent.chat.id, sent.message_id, AUTO_DELETE_SECONDS)
    await callback.answer()


@router.callback_query(F.data.startswith("pyq:random:"))
async def cb_pyq_random(
    callback: CallbackQuery,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    settings: Settings,
) -> None:
    """Serve a random 10-year prep question filtered to the student's NEET/JEE exam."""
    subject = callback.data.split("pyq:random:", 1)[1]
    resolved_exam = _resolve_user_exam(users, callback.from_user.id)
    item = pyq_service.random_question(
        exam=resolved_exam,
        subject=None if subject in {"all", "mixed"} else subject,
    )
    if not item:
        await callback.answer("No matching PYQs available for your exam track.", show_alert=True)
        return
    if callback.message:
        sent = await callback.message.answer(
            format_pyq_html(item, settings),
            reply_markup=pyq_answer_keyboard(item.pyq_id, resolved_exam or item.exam, subject, settings),
            parse_mode="HTML",
        )
        schedule_auto_delete(bot, sent.chat.id, sent.message_id, AUTO_DELETE_SECONDS)
    await callback.answer("Random 10-yr prep!")


@router.callback_query(F.data.startswith("pyq:poll:"))
async def cb_pyq_poll(
    callback: CallbackQuery,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    settings: Settings,
) -> None:
    """Launch an auto-advancing 5-question Quiz Poll session matching the student's exam."""
    subject = callback.data.split("pyq:poll:", 1)[1]
    resolved_exam = _resolve_user_exam(users, callback.from_user.id)
    if not callback.message:
        await callback.answer()
        return
    started = await start_auto_poll_series(
        bot,
        callback.message.chat.id,
        pyq_service,
        settings,
        exam=resolved_exam,
        subject=None if subject in {"all", "mixed"} else subject,
    )
    await callback.answer("Auto-Poll started!" if started else "No matching PYQs found.", show_alert=not started)


@router.callback_query(F.data.startswith("pyq:list:"))
async def cb_pyq_question(
    callback: CallbackQuery,
    bot: Bot,
    pyq_service: PYQService,
    settings: Settings,
) -> None:
    """Serve a verified PYQ with colored interactive A/B/C/D answer buttons & 4-min auto-delete."""
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
        sent = await callback.message.answer(
            format_pyq_html(item, settings),
            reply_markup=pyq_answer_keyboard(item.pyq_id, exam, subject, settings),
            parse_mode="HTML",
        )
        schedule_auto_delete(bot, sent.chat.id, sent.message_id, AUTO_DELETE_SECONDS)
    await callback.answer()


@router.callback_query(F.data.startswith("pyq:ans:"))
async def cb_pyq_answer(
    callback: CallbackQuery,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    """Evaluate student's PYQ answer, show explanation, and automatically send the next question!"""
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
        f"🔗 Source: {html_lib.escape(item.source)}\n"
        "<i>Loading next question in 3 seconds…</i>"
    )
    await callback.answer("Correct!" if is_correct else f"Correct answer: {item.correct_option}")

    if callback.message:
        exp_msg = await callback.message.answer(reply, parse_mode="HTML")
        schedule_auto_delete(bot, exp_msg.chat.id, exp_msg.message_id, AUTO_DELETE_SECONDS)

        # Auto-advance to the next question matching the student's NEET/JEE exam track!
        await asyncio.sleep(3)
        resolved_exam = _resolve_user_exam(users, callback.from_user.id)
        next_item = pyq_service.random_question(exam=resolved_exam)
        if next_item:
            next_msg = await callback.message.answer(
                format_pyq_html(next_item, settings),
                reply_markup=pyq_answer_keyboard(next_item.pyq_id, resolved_exam or next_item.exam, "mixed", settings),
                parse_mode="HTML",
            )
            schedule_auto_delete(bot, next_msg.chat.id, next_msg.message_id, AUTO_DELETE_SECONDS)
