"""AI doubt solver (DM & Group Chat /ask), follow-up modes, and Class 11/12 NCERT Explorer."""

from __future__ import annotations

import html as html_lib
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ai.formatter import detect_subject_from_text, format_ai_response_for_telegram
from ai.ollama import OllamaClient, OllamaError
from ai.prompts import build_system_prompt, build_user_prompt
from ai.verifier import extract_and_verify
from config import Settings
from database.progress import ProgressRepository
from database.questions import QuestionRepository
from database.users import UserRepository
from keyboards.main import back_to_menu_keyboard
from keyboards.subjects import (
    doubt_followup_keyboard,
    ncert_class_keyboard,
    ncert_subject_keyboard,
)
from middlewares.security import sanitize_user_text
from services.ncert import NCERTRAGService
from services.pyq import PYQService

logger = logging.getLogger(__name__)
router = Router(name="doubt")

_SUBJECT_LABELS = {
    "biology": "🧬 Biology",
    "chemistry": "⚗️ Chemistry",
    "physics": "📐 Physics",
    "general": "📘 General Science",
}


async def answer_doubt(
    *,
    message: Message,
    user_id: int,
    question_text: str,
    subject: str,
    mode: str,
    ollama: OllamaClient,
    ncert: NCERTRAGService,
    questions: QuestionRepository,
    progress: ProgressRepository,
    pyq_service: PYQService | None = None,
    settings: Settings | None = None,
    conversation_context: str = "",
    from_ocr: bool = False,
    force_ai: bool = False,
) -> None:
    """Core pipeline: Verified PYQ fast-match -> NCERT RAG -> SymPy -> Ollama -> clean HTML."""
    # Auto-detect subject from question content so Chemistry OCR never uses Physics template
    resolved_subject = detect_subject_from_text(question_text, fallback=subject)

    # Instant verified PYQ match (0ms CPU, 100% accurate!) when not explicitly re-explaining via AI
    if not force_ai and pyq_service is not None:
        matched = pyq_service.find_matching_pyq(question_text)
        if matched is not None:
            correct_val = matched.options.get(matched.correct_option, "")
            verified_html = (
                f"✅ <b>Verified PYQ Solution ({html_lib.escape(matched.exam)} {matched.year})</b>\n"
                f"<i>{html_lib.escape(matched.subject.title())} — {html_lib.escape(matched.chapter)}</i>\n\n"
                f"<b>Correct Answer:</b> {html_lib.escape(matched.correct_option)}. {html_lib.escape(correct_val)}\n\n"
                f"📖 <b>Explanation:</b>\n{html_lib.escape(matched.explanation)}\n\n"
                f"🔗 <i>Source: {html_lib.escape(matched.source)}</i>"
            )
            questions.save_question(
                user_id=user_id,
                subject=matched.subject,
                question=matched.question,
                answer=f"Correct Answer: {matched.correct_option}. {correct_val}. {matched.explanation}",
                source="ocr" if from_ocr else "text",
                chapter=matched.chapter,
            )
            progress.record_doubt(user_id=user_id, subject=matched.subject, chapter=matched.chapter)
            await message.answer(
                verified_html,
                reply_markup=doubt_followup_keyboard(matched.subject, settings),
                parse_mode="HTML",
            )
            return

    status_note = (
        "⏳ Another student's question is being solved right now. Your question is next in queue…"
        if ollama.is_busy
        else f"🤖 AAKASH AI is solving your {_SUBJECT_LABELS.get(resolved_subject, 'Science')} question…"
    )
    thinking_msg = await message.answer(status_note)

    ncert_context, citations = ncert.build_context_block(question_text, subject=resolved_subject, top_k=2)
    verification = extract_and_verify(question_text)

    sys_prompt = build_system_prompt(subject=resolved_subject, mode=mode)
    usr_prompt = build_user_prompt(
        question=question_text,
        ncert_context=ncert_context,
        verification_note=verification.summary if verification.verified else "",
        conversation_context=conversation_context,
        from_ocr=from_ocr,
    )

    try:
        response = await ollama.generate_chat(sys_prompt, usr_prompt)
    except OllamaError as exc:
        await thinking_msg.edit_text(f"⚠️ {exc}", reply_markup=back_to_menu_keyboard(settings))
        return

    body_html = format_ai_response_for_telegram(response.text, max_len=3400)
    sections = [body_html]
    if verification.verified:
        sections.append(f"🧮 <b>SymPy Check:</b> {html_lib.escape(verification.summary)}")
    if citations:
        refs = "\n".join(f"• {html_lib.escape(c)}" for c in citations)
        sections.append(f"📚 <b>Verified NCERT Reference(s):</b>\n{refs}")

    final_html = "\n\n".join(sections)[:3950]
    questions.save_question(
        user_id=user_id,
        subject=resolved_subject,
        question=question_text,
        answer=response.text,
        source="ocr" if from_ocr else "text",
    )
    progress.record_doubt(user_id=user_id, subject=resolved_subject)

    await thinking_msg.edit_text(
        final_html,
        reply_markup=doubt_followup_keyboard(resolved_subject, settings),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("subject:"))
async def cb_select_subject(callback: CallbackQuery, users: UserRepository, settings: Settings) -> None:
    """Set the student's active subject for text and image questions."""
    subject = callback.data.split("subject:", 1)[1]
    users.update_preferences(callback.from_user.id, active_subject=subject)
    label = _SUBJECT_LABELS.get(subject, subject.title())
    if callback.message:
        await callback.message.answer(
            f"{label} selected! Send your question as text (or <code>/ask &lt;question&gt;</code> in a group) or upload a clear photo.",
            reply_markup=back_to_menu_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer(f"Switched to {subject.title()}")


@router.callback_query(F.data == "menu:ncert")
async def cb_ncert_menu(callback: CallbackQuery, settings: Settings) -> None:
    """Show NCERT Explorer subject choices."""
    if callback.message:
        await callback.message.answer(
            "📚 <b>NCERT Explorer (Class 11 &amp; 12 Complete)</b>\n\n"
            "Select a subject to browse all Class 11 &amp; Class 12 chapters:",
            reply_markup=ncert_subject_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("ncert:subj:"))
async def cb_ncert_choose_class(
    callback: CallbackQuery,
    ncert: NCERTRAGService,
    users: UserRepository,
    settings: Settings,
) -> None:
    """Show Class 11 / Class 12 sub-menu for the selected NCERT subject."""
    subject = callback.data.split("ncert:subj:", 1)[1]
    users.update_preferences(callback.from_user.id, active_subject=subject)
    c11 = len(ncert.list_chapters(subject=subject, class_level=11))
    c12 = len(ncert.list_chapters(subject=subject, class_level=12))
    if callback.message:
        await callback.message.answer(
            f"📚 <b>NCERT {subject.title()}</b>\n\n"
            f"• Class 11: <b>{c11}</b> chapters indexed\n"
            f"• Class 12: <b>{c12}</b> chapters indexed\n\n"
            "Choose a class below:",
            reply_markup=ncert_class_keyboard(subject, settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("ncert:class:"))
async def cb_ncert_chapters_by_class(
    callback: CallbackQuery,
    ncert: NCERTRAGService,
    settings: Settings,
) -> None:
    """List all indexed NCERT chapters for a specific subject and class (11 or 12)."""
    _, _, subject, class_str = callback.data.split(":", 3)
    class_level = int(class_str)
    chapters = ncert.list_chapters(subject=subject, class_level=class_level)
    if not chapters:
        text = f"No NCERT passages indexed yet for Class {class_level} {subject.title()}."
    else:
        lines = [f"📚 <b>NCERT Class {class_level} {subject.title()} ({len(chapters)} Chapters):</b>\n"]
        for ch in chapters:
            lines.append(f"• Ch. {ch['chapter_number']}: {html_lib.escape(str(ch['chapter_title']))}")
        lines.append("\nType any question from these chapters to get an NCERT-grounded answer!")
        text = "\n".join(lines)
    if callback.message:
        await callback.message.answer(
            text,
            reply_markup=ncert_class_keyboard(subject, settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("mode:"))
async def cb_reexplain_mode(
    callback: CallbackQuery,
    settings: Settings,
    ollama: OllamaClient,
    ncert: NCERTRAGService,
    questions: QuestionRepository,
    progress: ProgressRepository,
    pyq_service: PYQService,
) -> None:
    """Re-explain the student's last question in simpler or exam-oriented mode via AAKASH AI."""
    _, mode, subject = callback.data.split(":", 2)
    last_q = questions.get_last_question(callback.from_user.id)
    if not last_q:
        await callback.answer("Ask a question first before switching explanation style.", show_alert=True)
        return

    await callback.answer(f"Generating {mode} explanation…")
    if callback.message:
        await answer_doubt(
            message=callback.message,
            user_id=callback.from_user.id,
            question_text=last_q["question"],
            subject=last_q.get("subject", subject),
            mode=mode,
            ollama=ollama,
            ncert=ncert,
            questions=questions,
            progress=progress,
            pyq_service=pyq_service,
            settings=settings,
            force_ai=True,
        )


@router.callback_query(F.data.startswith("doubt:followup:"))
async def cb_followup_prompt(callback: CallbackQuery) -> None:
    """Prompt the student to type their follow-up question."""
    if callback.message:
        await callback.message.answer(
            "💬 Type your follow-up question now — I'll use your previous question as context."
        )
    await callback.answer()


@router.message(Command("ask"))
async def cmd_ask_doubt(
    message: Message,
    settings: Settings,
    ollama: OllamaClient,
    ncert: NCERTRAGService,
    users: UserRepository,
    questions: QuestionRepository,
    progress: ProgressRepository,
    pyq_service: PYQService,
) -> None:
    """Explicit /ask <question> command that works in both Group Chats and DMs."""
    if not message.from_user or not message.text:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: <code>/ask What is Newton's second law?</code>", parse_mode="HTML")
        return

    cleaned, error = sanitize_user_text(parts[1], max_chars=settings.max_input_chars)
    if error:
        await message.answer(f"⚠️ {error}")
        return

    user = users.upsert_user(
        message.from_user.id,
        first_name=message.from_user.first_name or "",
        username=message.from_user.username or "",
    )
    await answer_doubt(
        message=message,
        user_id=message.from_user.id,
        question_text=cleaned,
        subject=user.get("active_subject", "general"),
        mode=user.get("explanation_mode", "standard"),
        ollama=ollama,
        ncert=ncert,
        questions=questions,
        progress=progress,
        pyq_service=pyq_service,
        settings=settings,
    )


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_question(
    message: Message,
    settings: Settings,
    ollama: OllamaClient,
    ncert: NCERTRAGService,
    users: UserRepository,
    questions: QuestionRepository,
    progress: ProgressRepository,
    pyq_service: PYQService,
) -> None:
    """Handle plain-text doubts in private DM (and replies to the bot in group chats)."""
    if not message.from_user or not message.text:
        return

    if message.chat.type != "private":
        reply_to = message.reply_to_message
        if not (reply_to and reply_to.from_user and reply_to.from_user.is_bot):
            return

    cleaned, error = sanitize_user_text(message.text, max_chars=settings.max_input_chars)
    if error:
        await message.answer(f"⚠️ {error}")
        return

    user = users.upsert_user(
        message.from_user.id,
        first_name=message.from_user.first_name or "",
        username=message.from_user.username or "",
    )
    subject = user.get("active_subject", "general")
    mode = user.get("explanation_mode", "standard")

    last_q = questions.get_last_question(message.from_user.id)
    conv_context = ""
    if last_q and len(cleaned) < 180:
        conv_context = (
            f"Previous Question ({last_q.get('subject', 'general')}): {last_q.get('question', '')}\n"
            f"Previous Answer Summary: {last_q.get('answer_preview', '')[:300]}"
        )

    await answer_doubt(
        message=message,
        user_id=message.from_user.id,
        question_text=cleaned,
        subject=subject,
        mode=mode,
        ollama=ollama,
        ncert=ncert,
        questions=questions,
        progress=progress,
        pyq_service=pyq_service,
        settings=settings,
        conversation_context=conv_context,
    )
