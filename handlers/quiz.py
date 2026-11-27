"""Interactive auto-advancing, zero-repeat MCQ quiz handlers (shared in Group Chats, one answer per user)."""

from __future__ import annotations

import asyncio
import html as html_lib
from collections import OrderedDict

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from ai.formatter import clean_latex_to_unicode
from config import Settings
from database.progress import ProgressRepository
from database.users import UserRepository
from keyboards.main import back_to_menu_keyboard
from keyboards.subjects import quiz_chapter_keyboard, quiz_mode_keyboard, quiz_options_keyboard
from services.analytics import pick_motivational_quote
from services.cleanup import AUTO_DELETE_SECONDS, schedule_auto_delete
from services.pyq import PYQService
from services.quiz import QuizService, QuizSession, question_time_limit_seconds

router = Router(name="quiz")

_QUIZ_TIMERS: dict[int, asyncio.Task] = {}
_ANSWERED_QUIZ_MESSAGES: OrderedDict[tuple[int, int], set[int]] = OrderedDict()
_MAX_TRACKED_QUIZ_MSGS = 500


def _mark_quiz_answered(chat_id: int, message_id: int, user_id: int) -> bool:
    """Return True if user hasn't answered this quiz question message yet, False if duplicate tap."""
    key = (chat_id, message_id)
    answered = _ANSWERED_QUIZ_MESSAGES.get(key)
    if answered is None:
        answered = set()
        _ANSWERED_QUIZ_MESSAGES[key] = answered
        if len(_ANSWERED_QUIZ_MESSAGES) > _MAX_TRACKED_QUIZ_MSGS:
            _ANSWERED_QUIZ_MESSAGES.popitem(last=False)
    if user_id in answered:
        return False
    answered.add(user_id)
    return True


def _quiz_session_key(chat_id: int, chat_type: str, user_id: int) -> int:
    return user_id if chat_type == "private" else chat_id


def _cancel_timer(session_key: int) -> None:
    task = _QUIZ_TIMERS.pop(session_key, None)
    if task and not task.done():
        task.cancel()


def _user_exam_filter(users: UserRepository, user_id: int) -> str | None:
    saved = str(users.get_user(user_id).get("target_exam", "")).strip()
    if saved.lower().startswith("jee"):
        return "JEE"
    if saved.lower().startswith("neet"):
        return "NEET UG"
    return None


def _format_quiz_question(session: QuizSession) -> str:
    q = session.current_question
    if q is None:
        return "Quiz complete!"
    num = session.current_index + 1
    total = len(session.questions)
    q_secs = question_time_limit_seconds(q.subject)
    opts = "\n".join(
        f"<b>{html_lib.escape(k)}.</b> {html_lib.escape(clean_latex_to_unicode(v))}"
        for k, v in sorted(q.options.items())
    )
    return (
        f"🎯 <b>Question {num}/{total}</b> ({html_lib.escape(q.exam)} {q.year} | "
        f"{html_lib.escape(q.subject.title())} — <i>{html_lib.escape(clean_latex_to_unicode(q.chapter))}</i>)\n"
        f"⏱️ Time limit: <b>{q_secs} seconds</b> (auto-advances when time is up)\n\n"
        f"{html_lib.escape(clean_latex_to_unicode(q.question))}\n\n"
        f"{opts}"
    )


def _format_quiz_report(result: dict) -> str:
    header = "⏱️ <b>Time's Up! Quiz Submitted</b>\n" if result["timed_out"] else "🏁 <b>Quiz Completed!</b>\n"
    quote = pick_motivational_quote(accuracy=float(result["accuracy"]))
    lines = [
        header,
        f"• Score: <b>{result['score']} / {result['total']}</b>",
        f"• Accuracy: <b>{result['accuracy']:.1f}%</b>",
        f"• Time Taken: <b>{result['elapsed_seconds']:.0f}s</b>",
        f"\n💡 <i>{html_lib.escape(quote)}</i>\n",
        "📖 <b>Answer Review &amp; Explanations:</b>",
    ]
    for item in result["items"]:
        icon = "✅" if item["is_correct"] else "❌"
        lines.append(
            f"\n{icon} <b>Q{item['index']}</b> ({html_lib.escape(item['exam'])} {item['year']} — {html_lib.escape(clean_latex_to_unicode(item['chapter']))})\n"
            f"Your answer: {html_lib.escape(item['chosen'])} | Correct: <b>{html_lib.escape(item['correct'])}</b>\n"
            f"Explanation: {html_lib.escape(clean_latex_to_unicode(item['explanation']))}"
        )
    return "\n".join(lines)[:3900]


async def _send_current_question_with_timer(
    *,
    bot: Bot,
    chat_id: int,
    session_key: int,
    owner_user_id: int,
    session: QuizSession,
    quiz_service: QuizService,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    _cancel_timer(session_key)
    q = session.current_question
    if q is None:
        return

    if q.image_url:
        try:
            diag = await bot.send_photo(chat_id=chat_id, photo=q.image_url)
            schedule_auto_delete(bot, chat_id, diag.message_id, AUTO_DELETE_SECONDS)
        except Exception:
            pass

    sent = await bot.send_message(
        chat_id=chat_id,
        text=_format_quiz_question(session),
        reply_markup=quiz_options_keyboard(settings),
        parse_mode="HTML",
    )
    schedule_auto_delete(bot, chat_id, sent.message_id, AUTO_DELETE_SECONDS)

    expected_idx = session.current_index
    timeout_secs = question_time_limit_seconds(q.subject)

    async def _on_timeout() -> None:
        try:
            await asyncio.sleep(timeout_secs)
            skipped, updated_session, finished = quiz_service.skip_timed_out_question(session_key, expected_idx)
            if not skipped or updated_session is None:
                return
            notice = await bot.send_message(
                chat_id=chat_id,
                text=f"⏱️ <b>Time's up ({timeout_secs}s)!</b> Moving automatically to the next question…",
                parse_mode="HTML",
            )
            schedule_auto_delete(bot, chat_id, notice.message_id, AUTO_DELETE_SECONDS)
            if finished:
                result = quiz_service.finalize_session(session_key)
                if result:
                    progress.record_quiz_result(
                        owner_user_id,
                        mode=result["mode"],
                        subject=result["subject"],
                        score=result["score"],
                        total=result["total"],
                        item_results=result["items"],
                    )
                    await bot.send_message(
                        chat_id=chat_id,
                        text=_format_quiz_report(result),
                        reply_markup=back_to_menu_keyboard(settings),
                        parse_mode="HTML",
                    )
            else:
                await _send_current_question_with_timer(
                    bot=bot,
                    chat_id=chat_id,
                    session_key=session_key,
                    owner_user_id=owner_user_id,
                    session=updated_session,
                    quiz_service=quiz_service,
                    progress=progress,
                    settings=settings,
                )
        except asyncio.CancelledError:
            return

    _QUIZ_TIMERS[session_key] = asyncio.create_task(_on_timeout())


@router.callback_query(F.data == "menu:quiz")
async def cb_quiz_menu(callback: CallbackQuery, users: UserRepository, settings: Settings) -> None:
    exam = _user_exam_filter(users, callback.from_user.id) or "NEET/JEE"
    if callback.message:
        await callback.message.answer(
            f"🎯 <b>Practice Quiz ({html_lib.escape(exam)} Track • Zero Repeats)</b>\n\n"
            "⏱️ Auto-next timers: <b>45s</b> (Biology/Chemistry) • <b>60s</b> (Physics)\n"
            "In groups, any member can tap answers! Choose a quiz mode below:",
            reply_markup=quiz_mode_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "quiz:chapters")
async def cb_quiz_chapters(
    callback: CallbackQuery,
    pyq_service: PYQService,
    users: UserRepository,
    settings: Settings,
) -> None:
    exam = _user_exam_filter(users, callback.from_user.id)
    chapters = pyq_service.list_chapters(exam=exam)
    if not chapters:
        await callback.answer("No quiz chapters available yet.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            "📖 <b>Select a Chapter for Practice:</b>",
            reply_markup=quiz_chapter_keyboard(chapters, settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("quiz:chap:"))
async def cb_start_chapter_quiz(
    callback: CallbackQuery,
    bot: Bot,
    quiz_service: QuizService,
    users: UserRepository,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    if not callback.message:
        await callback.answer()
        return
    chapter = callback.data.split("quiz:chap:", 1)[1]
    exam = _user_exam_filter(users, callback.from_user.id)
    skey = _quiz_session_key(callback.message.chat.id, callback.message.chat.type, callback.from_user.id)
    seen = progress.get_seen_pyq_ids(skey)
    session = quiz_service.start_quiz(
        skey,
        mode="chapter",
        exam=exam,
        chapter=chapter,
        num_questions=5,
        exclude_ids=seen,
    )
    if session is None:
        await callback.answer("No questions found for this chapter.", show_alert=True)
        return
    progress.mark_pyq_seen(skey, [q.pyq_id for q in session.questions])
    await callback.answer(f"Started {chapter} quiz!")
    await _send_current_question_with_timer(
        bot=bot,
        chat_id=callback.message.chat.id,
        session_key=skey,
        owner_user_id=callback.from_user.id,
        session=session,
        quiz_service=quiz_service,
        progress=progress,
        settings=settings,
    )


@router.callback_query(F.data.startswith("quiz:start:"))
async def cb_start_quiz(
    callback: CallbackQuery,
    bot: Bot,
    quiz_service: QuizService,
    users: UserRepository,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    if not callback.message:
        await callback.answer()
        return
    _, _, mode, subject = callback.data.split(":", 3)
    exam = _user_exam_filter(users, callback.from_user.id)
    time_limit = 300 if mode == "timed" else None
    skey = _quiz_session_key(callback.message.chat.id, callback.message.chat.type, callback.from_user.id)
    seen = progress.get_seen_pyq_ids(skey)
    session = quiz_service.start_quiz(
        skey,
        mode=mode,
        exam=exam,
        subject=None if subject == "mixed" else subject,
        num_questions=5,
        time_limit_seconds=time_limit,
        exclude_ids=seen,
    )
    if session is None:
        await callback.answer(
            f"No {subject.title()} questions found for your {exam or 'selected'} track.",
            show_alert=True,
        )
        return
    progress.mark_pyq_seen(skey, [q.pyq_id for q in session.questions])
    await callback.answer("Quiz started!")
    await _send_current_question_with_timer(
        bot=bot,
        chat_id=callback.message.chat.id,
        session_key=skey,
        owner_user_id=callback.from_user.id,
        session=session,
        quiz_service=quiz_service,
        progress=progress,
        settings=settings,
    )


@router.callback_query(F.data.startswith("quiz:ans:"))
async def cb_quiz_answer(
    callback: CallbackQuery,
    bot: Bot,
    quiz_service: QuizService,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    if not callback.message:
        await callback.answer()
        return

    # Strictly block the same user from answering the same quiz question twice
    if not _mark_quiz_answered(callback.message.chat.id, callback.message.message_id, callback.from_user.id):
        await callback.answer("⚠️ You already answered this question!", show_alert=True)
        return

    option = callback.data.split("quiz:ans:", 1)[1]
    skey = _quiz_session_key(callback.message.chat.id, callback.message.chat.type, callback.from_user.id)
    _cancel_timer(skey)
    _, session, finished = quiz_service.submit_answer(skey, option)
    if session is None:
        await callback.answer("No active quiz session in this chat. Tap Practice Quiz to start one!", show_alert=True)
        return

    if finished:
        result = quiz_service.finalize_session(skey)
        if result:
            progress.record_quiz_result(
                callback.from_user.id,
                mode=result["mode"],
                subject=result["subject"],
                score=result["score"],
                total=result["total"],
                item_results=result["items"],
            )
            await callback.message.answer(
                _format_quiz_report(result),
                reply_markup=back_to_menu_keyboard(settings),
                parse_mode="HTML",
            )
        await callback.answer("Quiz finished!")
        return

    who = callback.from_user.first_name or "Student"
    await callback.answer(f"{who} picked {option}")
    await _send_current_question_with_timer(
        bot=bot,
        chat_id=callback.message.chat.id,
        session_key=skey,
        owner_user_id=callback.from_user.id,
        session=session,
        quiz_service=quiz_service,
        progress=progress,
        settings=settings,
    )


@router.callback_query(F.data == "quiz:cancel")
async def cb_quiz_cancel(callback: CallbackQuery, quiz_service: QuizService, settings: Settings) -> None:
    if callback.message:
        skey = _quiz_session_key(callback.message.chat.id, callback.message.chat.type, callback.from_user.id)
        _cancel_timer(skey)
        quiz_service.cancel_session(skey)
        await callback.message.answer("🛑 Quiz ended.", reply_markup=back_to_menu_keyboard(settings))
    await callback.answer("Quiz ended")
