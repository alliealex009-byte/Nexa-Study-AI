"""Interactive MCQ quiz and timed mock test handlers with colored buttons."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from config import Settings
from database.progress import ProgressRepository
from keyboards.main import back_to_menu_keyboard
from keyboards.subjects import quiz_chapter_keyboard, quiz_mode_keyboard, quiz_options_keyboard
from services.pyq import PYQService
from services.quiz import QuizService, QuizSession

router = Router(name="quiz")


def _format_quiz_question(session: QuizSession) -> str:
    q = session.current_question
    if q is None:
        return "Quiz complete!"
    num = session.current_index + 1
    total = len(session.questions)
    timer_line = ""
    if session.remaining_seconds is not None:
        mins, secs = divmod(session.remaining_seconds, 60)
        timer_line = f"⏱️ Time left: **{mins:02d}:{secs:02d}**\n"

    opts = "\n".join(f"**{k}.** {v}" for k, v in sorted(q.options.items()))
    return (
        f"🎯 **Question {num}/{total}** ({q.exam} {q.year} | {q.subject.title()} — _{q.chapter}_)\n"
        f"{timer_line}\n"
        f"{q.question}\n\n"
        f"{opts}"
    )


def _format_quiz_report(result: dict) -> str:
    header = "⏱️ **Time's Up! Quiz Submitted**\n" if result["timed_out"] else "🏁 **Quiz Completed!**\n"
    lines = [
        header,
        f"• Score: **{result['score']} / {result['total']}**",
        f"• Accuracy: **{result['accuracy']:.1f}%**",
        f"• Time Taken: **{result['elapsed_seconds']:.0f}s**\n",
        "📖 **Answer Review & Explanations:**",
    ]
    for item in result["items"]:
        icon = "✅" if item["is_correct"] else "❌"
        lines.append(
            f"\n{icon} **Q{item['index']}** ({item['exam']} {item['year']} — {item['chapter']})\n"
            f"Your answer: {item['chosen']} | Correct: **{item['correct']}**\n"
            f"Explanation: {item['explanation']}"
        )
    return "\n".join(lines)[:3900]


@router.callback_query(F.data == "menu:quiz")
async def cb_quiz_menu(callback: CallbackQuery, settings: Settings) -> None:
    """Display colored quiz mode choices."""
    if callback.message:
        await callback.message.answer(
            "🎯 **Practice Quiz & 10-Year Mock Tests**\n\n"
            "Choose a subject quiz, chapter-wise drill, mixed 10-yr mock, or 5-minute timed test:",
            reply_markup=quiz_mode_keyboard(settings),
            parse_mode="Markdown",
        )
    await callback.answer()


@router.callback_query(F.data == "quiz:chapters")
async def cb_quiz_chapters(callback: CallbackQuery, pyq_service: PYQService, settings: Settings) -> None:
    """List verified chapters for chapter-wise quiz."""
    chapters = pyq_service.list_chapters()
    if not chapters:
        await callback.answer("No quiz chapters available yet.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            "📖 **Select a Chapter for Practice:**",
            reply_markup=quiz_chapter_keyboard(chapters, settings),
            parse_mode="Markdown",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("quiz:chap:"))
async def cb_start_chapter_quiz(callback: CallbackQuery, quiz_service: QuizService, settings: Settings) -> None:
    """Start a chapter-wise quiz."""
    chapter = callback.data.split("quiz:chap:", 1)[1]
    session = quiz_service.start_quiz(
        callback.from_user.id,
        mode="chapter",
        chapter=chapter,
        num_questions=5,
    )
    if session is None:
        await callback.answer("No questions found for this chapter.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            _format_quiz_question(session),
            reply_markup=quiz_options_keyboard(settings),
            parse_mode="Markdown",
        )
    await callback.answer(f"Started {chapter} quiz!")


@router.callback_query(F.data.startswith("quiz:start:"))
async def cb_start_quiz(callback: CallbackQuery, quiz_service: QuizService, settings: Settings) -> None:
    """Start a subject-wise, mixed, or timed quiz."""
    _, _, mode, subject = callback.data.split(":", 3)
    time_limit = 300 if mode == "timed" else None
    session = quiz_service.start_quiz(
        callback.from_user.id,
        mode=mode,
        subject=None if subject == "mixed" else subject,
        num_questions=5,
        time_limit_seconds=time_limit,
    )
    if session is None:
        await callback.answer("Not enough verified questions loaded for this quiz.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            _format_quiz_question(session),
            reply_markup=quiz_options_keyboard(settings),
            parse_mode="Markdown",
        )
    await callback.answer("Quiz started!")


@router.callback_query(F.data.startswith("quiz:ans:"))
async def cb_quiz_answer(
    callback: CallbackQuery,
    quiz_service: QuizService,
    progress: ProgressRepository,
    settings: Settings,
) -> None:
    """Record a quiz answer and advance to next question or finalize."""
    option = callback.data.split("quiz:ans:", 1)[1]
    _, session, finished = quiz_service.submit_answer(callback.from_user.id, option)
    if session is None:
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
            if callback.message:
                await callback.message.answer(
                    _format_quiz_report(result),
                    reply_markup=back_to_menu_keyboard(settings),
                    parse_mode="Markdown",
                )
        await callback.answer("Quiz finished!")
        return

    if callback.message:
        await callback.message.answer(
            _format_quiz_question(session),
            reply_markup=quiz_options_keyboard(settings),
            parse_mode="Markdown",
        )
    await callback.answer(f"Recorded option {option}")


@router.callback_query(F.data == "quiz:cancel")
async def cb_quiz_cancel(callback: CallbackQuery, quiz_service: QuizService, settings: Settings) -> None:
    """Cancel the current quiz session."""
    quiz_service.cancel_session(callback.from_user.id)
    if callback.message:
        await callback.message.answer("🛑 Quiz cancelled.", reply_markup=back_to_menu_keyboard(settings))
    await callback.answer("Quiz cancelled")
