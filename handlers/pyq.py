"""10-Year (2016–2025) NEET & JEE PYQ browser, zero-repeat engine, one-answer-per-user guard, auto-polls & diagrams."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
from collections import OrderedDict

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ai.formatter import clean_latex_to_unicode
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

_ACTIVE_POLL_LOOPS: dict[int, asyncio.Task] = {}
# Prevent the same user from answering the same PYQ message multiple times: (chat_id, msg_id) -> {user_ids}
_ANSWERED_PYQ_MESSAGES: OrderedDict[tuple[int, int], set[int]] = OrderedDict()
_MAX_TRACKED_MSGS = 500


def _mark_user_answered(chat_id: int, message_id: int, user_id: int) -> bool:
    """Return True if this is the user's first answer on this question message, False if duplicate."""
    key = (chat_id, message_id)
    answered = _ANSWERED_PYQ_MESSAGES.get(key)
    if answered is None:
        answered = set()
        _ANSWERED_PYQ_MESSAGES[key] = answered
        if len(_ANSWERED_PYQ_MESSAGES) > _MAX_TRACKED_MSGS:
            _ANSWERED_PYQ_MESSAGES.popitem(last=False)
    if user_id in answered:
        return False
    answered.add(user_id)
    return True


def _scope_id(chat_id: int, chat_type: str, user_id: int) -> int:
    return user_id if chat_type == "private" else chat_id


def _resolve_user_exam(users: UserRepository, user_id: int, explicit_exam: str | None = None) -> str | None:
    if explicit_exam and explicit_exam.lower() not in {"all", "any", "mixed"}:
        return explicit_exam
    user = users.get_user(user_id)
    saved = str(user.get("target_exam", "")).strip()
    if saved.lower().startswith("jee"):
        return "JEE"
    if saved.lower().startswith("neet"):
        return "NEET UG"
    return None


def _pick_unseen_pyq(
    pyq_service: PYQService,
    progress: ProgressRepository,
    scope_id: int,
    *,
    exam: str | None = None,
    subject: str | None = None,
    year: int | None = None,
) -> PYQItem | None:
    seen = progress.get_seen_pyq_ids(scope_id)
    item, wrapped = pyq_service.random_question(exam=exam, subject=subject, year=year, exclude_ids=seen)
    if item is None:
        return None
    if wrapped:
        pool_ids = {q.pyq_id for q in pyq_service.query(exam=exam, subject=subject, year=year, limit=10000)}
        progress.reset_seen_pyq_ids(scope_id, subset_to_clear=pool_ids)
    progress.mark_pyq_seen(scope_id, item.pyq_id)
    return item


def _stop_poll_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [styled_button("End Auto-Poll", callback_data="pyq:stop_poll", style="danger", emoji_key="cancel", settings=settings)]
        ]
    )


def format_pyq_html(q: PYQItem, settings: Settings | None = None) -> str:
    icon = tg_emoji("pyq", settings)
    secs = question_time_limit_seconds(q.subject)
    options_text = "\n".join(
        f"<b>{html_lib.escape(k)}.</b> {html_lib.escape(clean_latex_to_unicode(v))}"
        for k, v in sorted(q.options.items())
    )
    return (
        f"{icon} <b>{html_lib.escape(q.exam)} {q.year}</b> | "
        f"{html_lib.escape(q.subject.title())} — <i>{html_lib.escape(clean_latex_to_unicode(q.chapter))}</i>\n"
        f"⏱️ Target Time: <b>{secs}s</b>\n\n"
        f"{html_lib.escape(clean_latex_to_unicode(q.question))}\n\n"
        f"{options_text}\n\n"
        "Tap your answer once below (next unseen question loads automatically!):"
    )


async def send_pyq_quiz_poll(
    bot: Bot,
    chat_id: int,
    q: PYQItem,
    *,
    index: int = 1,
    total: int = 1,
    settings: Settings | None = None,
) -> None:
    if q.image_url:
        try:
            diag = await bot.send_photo(
                chat_id=chat_id,
                photo=q.image_url,
                caption=f"🖼️ <b>Diagram for Q{index}/{total}</b> ({html_lib.escape(q.exam)} {q.year})",
                parse_mode="HTML",
            )
            schedule_auto_delete(bot, chat_id, diag.message_id, AUTO_DELETE_SECONDS)
        except Exception as exc:
            logger.debug("Could not send PYQ diagram %s: %s", q.image_url, exc)

    sorted_keys = sorted(q.options.keys())
    options = [f"{k}. {clean_latex_to_unicode(q.options[k])}"[:100] for k in sorted_keys]
    correct_idx = sorted_keys.index(q.correct_option) if q.correct_option in sorted_keys else 0
    open_period = question_time_limit_seconds(q.subject)
    prefix = f"[{index}/{total} • {q.exam} {q.year} • {open_period}s] " if total > 1 else f"[{q.exam} {q.year} • {open_period}s] "
    poll_question = f"{prefix}{clean_latex_to_unicode(q.question)}"[:300]
    explanation = clean_latex_to_unicode(f"{q.explanation} ({q.source})")[:200]
    sent = await bot.send_poll(
        chat_id=chat_id,
        question=poll_question,
        options=options,
        type="quiz",
        correct_option_id=correct_idx,
        explanation=explanation,
        is_anonymous=False,
        open_period=open_period,
        reply_markup=_stop_poll_keyboard(settings),
    )
    schedule_auto_delete(bot, chat_id, sent.message_id, AUTO_DELETE_SECONDS)


async def _run_auto_poll_series(
    bot: Bot,
    chat_id: int,
    items: list[PYQItem],
    settings: Settings,
) -> None:
    total = len(items)
    try:
        for idx, item in enumerate(items, start=1):
            await send_pyq_quiz_poll(bot, chat_id, item, index=idx, total=total, settings=settings)
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
    scope_id: int,
    pyq_service: PYQService,
    progress: ProgressRepository,
    settings: Settings,
    *,
    exam: str | None = None,
    subject: str | None = None,
    count: int = 5,
) -> bool:
    existing = _ACTIVE_POLL_LOOPS.pop(chat_id, None)
    if existing and not existing.done():
        existing.cancel()

    seen = progress.get_seen_pyq_ids(scope_id)
    items = pyq_service.query(exam=exam, subject=subject, limit=count, shuffle=True, exclude_ids=seen)
    if not items:
        return False
    progress.mark_pyq_seen(scope_id, [q.pyq_id for q in items])

    exam_tag = exam or "NEET/JEE"
    intro = await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⚡ <b>Starting {len(items)}-Question Auto-Poll ({html_lib.escape(exam_tag)})</b>\n"
            "⏱️ <b>45s</b> for Bio/Chem • <b>60s</b> for Physics • <b>Zero Repeats</b>\n"
            "Tap <b>End Auto-Poll</b> on any poll (or send <code>/stoppoll</code>) to stop anytime."
        ),
        reply_markup=_stop_poll_keyboard(settings),
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
    progress: ProgressRepository,
    settings: Settings,
    *,
    exam: str | None = None,
    subject: str | None = None,
) -> None:
    user_id = message.from_user.id if message.from_user else 0
    scope = _scope_id(message.chat.id, message.chat.type, user_id)
    resolved_exam = _resolve_user_exam(users, user_id, explicit_exam=exam)
    item = _pick_unseen_pyq(pyq_service, progress, scope, exam=resolved_exam, subject=subject)
    if not item:
        await message.answer(
            "No matching PYQs found. Ask the owner to run <b>Sync 5K Open-Source Bank</b> in /admin.",
            parse_mode="HTML",
        )
        return
    if item.image_url:
        try:
            diag = await bot.send_photo(chat_id=message.chat.id, photo=item.image_url)
            schedule_auto_delete(bot, diag.chat.id, diag.message_id, AUTO_DELETE_SECONDS)
        except Exception:
            pass
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
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    await _send_random_prep(message, bot, pyq_service, users, progress, settings)


@router.message(Command("neet"))
async def cmd_random_neet(
    message: Message,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    await _send_random_prep(message, bot, pyq_service, users, progress, settings, exam="NEET UG")


@router.message(Command("jee"))
async def cmd_random_jee(
    message: Message,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    await _send_random_prep(message, bot, pyq_service, users, progress, settings, exam="JEE")


@router.message(Command("poll"))
async def cmd_group_quiz_poll(
    message: Message,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    arg = (message.text or "").split(maxsplit=1)
    explicit_exam = None
    if len(arg) > 1:
        token = arg[1].strip().lower()
        if "neet" in token:
            explicit_exam = "NEET UG"
        elif "jee" in token:
            explicit_exam = "JEE"
    user_id = message.from_user.id if message.from_user else 0
    scope = _scope_id(message.chat.id, message.chat.type, user_id)
    resolved_exam = _resolve_user_exam(users, user_id, explicit_exam=explicit_exam)
    started = await start_auto_poll_series(
        bot, message.chat.id, scope, pyq_service, progress, settings, exam=resolved_exam
    )
    if not started:
        await message.answer("No PYQs available to create a poll.")


@router.message(Command("stoppoll"))
@router.message(Command("stop"))
async def cmd_stop_poll(message: Message) -> None:
    task = _ACTIVE_POLL_LOOPS.pop(message.chat.id, None)
    if task and not task.done():
        task.cancel()
        await message.answer("🛑 Auto-Poll session stopped.")
    else:
        await message.answer("No active Auto-Poll is running in this chat.")


@router.callback_query(F.data == "pyq:stop_poll")
async def cb_stop_poll(callback: CallbackQuery) -> None:
    if callback.message:
        task = _ACTIVE_POLL_LOOPS.pop(callback.message.chat.id, None)
        if task and not task.done():
            task.cancel()
        await callback.message.answer("🛑 Auto-Poll session ended.")
    await callback.answer("Auto-Poll stopped")


@router.callback_query(F.data == "menu:pyq")
async def cb_pyq_menu(callback: CallbackQuery, settings: Settings) -> None:
    icon = tg_emoji("pyq", settings)
    if callback.message:
        await callback.message.answer(
            f"{icon} <b>10-Year Previous Year Questions (2016–2025)</b>\n\nChoose an exam or launch zero-repeat random prep:",
            reply_markup=pyq_exam_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("pyq:exam:"))
async def cb_pyq_exam(callback: CallbackQuery, settings: Settings) -> None:
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
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    _, _, exam, year_str = callback.data.split(":", 3)
    if not callback.message:
        await callback.answer()
        return
    scope = _scope_id(callback.message.chat.id, callback.message.chat.type, callback.from_user.id)
    item = _pick_unseen_pyq(pyq_service, progress, scope, exam=exam, year=int(year_str))
    if not item:
        await callback.answer("No PYQ found for that year.", show_alert=True)
        return
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
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    subject = callback.data.split("pyq:random:", 1)[1]
    if not callback.message:
        await callback.answer()
        return
    scope = _scope_id(callback.message.chat.id, callback.message.chat.type, callback.from_user.id)
    resolved_exam = _resolve_user_exam(users, callback.from_user.id)
    item = _pick_unseen_pyq(
        pyq_service,
        progress,
        scope,
        exam=resolved_exam,
        subject=None if subject in {"all", "mixed"} else subject,
    )
    if not item:
        await callback.answer("No matching PYQs available for your exam track.", show_alert=True)
        return
    sent = await callback.message.answer(
        format_pyq_html(item, settings),
        reply_markup=pyq_answer_keyboard(item.pyq_id, resolved_exam or item.exam, subject, settings),
        parse_mode="HTML",
    )
    schedule_auto_delete(bot, sent.chat.id, sent.message_id, AUTO_DELETE_SECONDS)
    await callback.answer("Fresh unseen question!")


@router.callback_query(F.data.startswith("pyq:poll:"))
async def cb_pyq_poll(
    callback: CallbackQuery,
    bot: Bot,
    pyq_service: PYQService,
    users: UserRepository,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    subject = callback.data.split("pyq:poll:", 1)[1]
    if not callback.message:
        await callback.answer()
        return
    scope = _scope_id(callback.message.chat.id, callback.message.chat.type, callback.from_user.id)
    resolved_exam = _resolve_user_exam(users, callback.from_user.id)
    started = await start_auto_poll_series(
        bot,
        callback.message.chat.id,
        scope,
        pyq_service,
        progress,
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
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    _, _, exam, subject = callback.data.split(":", 3)
    if not callback.message:
        await callback.answer()
        return
    scope = _scope_id(callback.message.chat.id, callback.message.chat.type, callback.from_user.id)
    item = _pick_unseen_pyq(
        pyq_service,
        progress,
        scope,
        exam=None if exam in {"all", "mixed"} else exam,
        subject=None if subject in {"all", "mixed"} else subject,
    )
    if not item:
        await callback.message.answer(
            f"No verified PYQs are loaded yet for <b>{html_lib.escape(exam)} — {html_lib.escape(subject.title())}</b>.",
            reply_markup=back_to_menu_keyboard(settings),
            parse_mode="HTML",
        )
        await callback.answer()
        return

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
    if not callback.message:
        await callback.answer()
        return

    # Strictly block the same user from answering the same question multiple times
    if not _mark_user_answered(callback.message.chat.id, callback.message.message_id, callback.from_user.id):
        await callback.answer("⚠️ You already answered this question!", show_alert=True)
        return

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
        f"Correct Answer: <b>{html_lib.escape(item.correct_option)}. {html_lib.escape(clean_latex_to_unicode(item.options[item.correct_option]))}</b>\n\n"
        f"📖 <b>Explanation:</b>\n{html_lib.escape(clean_latex_to_unicode(item.explanation))}\n\n"
        f"🔗 Source: {html_lib.escape(item.source)}\n"
        "<i>Loading next unseen question in 3 seconds…</i>"
    )
    await callback.answer("Correct!" if is_correct else f"Correct answer: {item.correct_option}")

    exp_msg = await callback.message.answer(reply, parse_mode="HTML")
    schedule_auto_delete(bot, exp_msg.chat.id, exp_msg.message_id, AUTO_DELETE_SECONDS)

    await asyncio.sleep(3)
    scope = _scope_id(callback.message.chat.id, callback.message.chat.type, callback.from_user.id)
    resolved_exam = _resolve_user_exam(users, callback.from_user.id)
    next_item = _pick_unseen_pyq(pyq_service, progress, scope, exam=resolved_exam)
    if next_item:
        next_msg = await callback.message.answer(
            format_pyq_html(next_item, settings),
            reply_markup=pyq_answer_keyboard(next_item.pyq_id, resolved_exam or next_item.exam, "mixed", settings),
            parse_mode="HTML",
        )
        schedule_auto_delete(bot, next_msg.chat.id, next_msg.message_id, AUTO_DELETE_SECONDS)
