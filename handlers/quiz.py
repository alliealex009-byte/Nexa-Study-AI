"""Interactive auto-advancing MCQ quiz handlers (60s Physics / 45s Bio & Chem) with 4-min cleanup."""

from __future__ import annotations

import asyncio
import html as html_lib

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

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

# Track per-user question auto-advance timers
_QUIZ_TIMERS: dict[int, asyncio.Task] = {}


def _cancel_timer(user_id: int) -> None:
    task = _QUIZ_TIMERS.pop(user_id, None)
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
    opts = "\n".join(f"<b>{html_lib.escape(k)}.</b> {html_lib.escape(v)}" for k, v in sorted(q.options.items()))
    return (
        f"🎯 <b>Question {num}/{total}</b> ({html_lib.escape(q.exam)} {q.year} | "
        f"{html_lib.escape(q.subject.title())} — <i>{html_lib.escape(q.chapter)}</i>)\n"
        f"⏱️ Time limit: <b>{q_secs} seconds</b> (auto-advances when time is up)\n\n"
        f"{html_lib.escape(q.question)}\n\n"
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
            f"\n{icon} <b>Q{item['index']}</b> ({html_lib.escape(item['exam'])} {item['year']} — {html_lib.escape(item['chapter'])})\n"
            f"Your answer: {html_lib.escape(item['chosen'])} | Correct: <b>{html_lib.escape(item['correct'])}</b>\n"
            f"Explanation: {html_lib.escape(item['explanation'])}"
        )
    return "\n".join(lines)[:3900]


async def _send_current_question_with_timer(
    *,
    bot: Bot,
    chat_id: int,
    user_id: int,
    session: QuizSession,
    quiz_service: QuizService,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    """Send current quiz question, schedule 4-min cleanup, and arm the 45s/60s auto-next timer."""
    _cancel_timer(user_id)
    q = session.current_question
    if q is None:
        return

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
            skipped, updated_session, finished = quiz_service.skip_timed_out_question(user_id, expected_idx)
            if not skipped or updated_session is None:
                return
            notice = await bot.send_message(
                chat_id=chat_id,
                text=f"⏱️ <b>Time's up ({timeout_secs}s)!</b> Moving automatically to the next question…",
                parse_mode="HTML",
            )
            schedule_auto_delete(bot, chat_id, notice.message_id, AUTO_DELETE_SECONDS)
            if finished:
                result = quiz_service.finalize_session(user_id)
                if result:
                    progress.record_quiz_result(
                        user_id,
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
                    user_id=user_id,
                    session=updated_session,
                    quiz_service=quiz_service,
                    progress=progress,
                    settings=settings,
                )
        except asyncio.CancelledError:
            return

    _QUIZ_TIMERS[user_id] = asyncio.create_task(_on_timeout())


@router.callback_query(F.data == "menu:quiz")
async def cb_quiz_menu(callback: CallbackQuery, users: UserRepository, settings: Settings) -> None:
    """Display colored quiz mode choices tailored to the student's NEET/JEE exam."""
    exam = _user_exam_filter(users, callback.from_user.id) or "NEET/JEE"
    if callback.message:
        await callback.message.answer(
            f"🎯 <b>Practice Quiz ({html_lib.escape(exam)} Track)</b>\n\n"
            "⏱️ Auto-next timers: <b>45s</b> (Biology/Chemistry) • <b>60s</b> (Physics)\n"
            "Choose a quiz mode below:",
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
    """List verified chapters available for the student's exam track."""
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
    """Start a chapter-wise quiz filtered to the student's exam."""
    chapter = callback.data.split("quiz:chap:", 1)[1]
    exam = _user_exam_filter(users, callback.from_user.id)
    session = quiz_service.start_quiz(
        callback.from_user.id,
        mode="chapter",
        exam=exam,
        chapter=chapter,
        num_questions=5,
    )
    if session is None or not callback.message:
        await callback.answer("No questions found for this chapter.", show_alert=True)
        return
    await callback.answer(f"Started {chapter} quiz!")
    await _send_current_question_with_timer(
        bot=bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
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
    """Start a subject-wise, mixed, or timed quiz strictly filtered to NEET or JEE."""
    _, _, mode, subject = callback.data.split(":", 3)
    exam = _user_exam_filter(users, callback.from_user.id)
    time_limit = 300 if mode == "timed" else None
    session = quiz_service.start_quiz(
        callback.from_user.id,
        mode=mode,
        exam=exam,
        subject=None if subject == "mixed" else subject,
        num_questions=5,
        time_limit_seconds=time_limit,
    )
    if session is None or not callback.message:
        await callback.answer(
            f"No {subject.title()} questions found for your {exam or 'selected'} track.",
            show_alert=True,
        )
        return
    await callback.answer("Quiz started!")
    await _send_current_question_with_timer(
        bot=bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
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
    """Record a quiz answer, cancel current timer, and immediately send the next question or report."""
    option = callback.data.split("quiz:ans:", 1)[1]
    _cancel_timer(callback.from_user.id)
    _, session, finished = quiz_service.submit_answer(callback.from_user.id, option)
    if session is None or not callback.message:
        await callback.answer("No active quiz session. Start a new quiz from the menu.", show_alert=True)
        return

    if finished:
        result = quiz_service.finalize_session(callback.from_user.id)
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

    await callback.answer(f"Recorded option {option}")
    await _send_current_question_with_timer(
        bot=bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        session=session,
        quiz_service=quiz_service,
        progress=progress,
        settings=settings,
    )


@router.callback_query(F.data == "quiz:cancel")
async def cb_quiz_cancel(callback: CallbackQuery, quiz_service: QuizService, settings: Settings) -> None:
    """Cancel the current quiz session and stop its timer."""
    _cancel_timer(callback.from_user.id)
    quiz_service.cancel_session(callback.from_user.id)
    if callback.message:
        await callback.message.answer("🛑 Quiz cancelled.", reply_markup=back_to_menu_keyboard(settings))
    await callback.answer("Quiz cancelled")
