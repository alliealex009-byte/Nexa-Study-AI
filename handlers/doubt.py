"""AI doubt solver (DM & Group Chat /ask), follow-up modes, and NCERT Explorer handlers."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ai.ollama import OllamaClient, OllamaError
from ai.prompts import build_system_prompt, build_user_prompt
from ai.verifier import extract_and_verify
from config import Settings
from database.progress import ProgressRepository
from database.questions import QuestionRepository
from database.users import UserRepository
from keyboards.main import back_to_menu_keyboard
from keyboards.subjects import doubt_followup_keyboard, ncert_subject_keyboard
from middlewares.security import sanitize_user_text
from services.ncert import NCERTRAGService

logger = logging.getLogger(__name__)
router = Router(name="doubt")

_SUBJECT_LABELS = {
    "biology": "🧬 Biology",
    "chemistry": "⚗️ Chemistry",
    "physics": "📐 Physics",
    "general": "📘 General Science",
}


def _trim_telegram_message(text: str, limit: int = 3900) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 40].rstrip() + "\n\n…(truncated for Telegram length)"


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
    settings: Settings | None = None,
    conversation_context: str = "",
    from_ocr: bool = False,
) -> None:
    """Core pipeline: NCERT RAG -> SymPy verification -> Ollama -> save history & progress."""
    status_note = (
        "⏳ Another student's question is being solved right now. Your question is next in queue…"
        if ollama.is_busy
        else f"🤖 Thinking through your {_SUBJECT_LABELS.get(subject, 'Science')} question…"
    )
    thinking_msg = await message.answer(status_note)

    ncert_context, citations = ncert.build_context_block(question_text, subject=subject, top_k=2)
    verification = extract_and_verify(question_text)

    sys_prompt = build_system_prompt(subject=subject, mode=mode)
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

    sections = [response.text]
    if verification.verified:
        sections.append(f"🧮 SymPy Check: {verification.summary}")
    if citations:
        refs = "\n".join(f"• {c}" for c in citations)
        sections.append(f"📚 Verified NCERT Reference(s):\n{refs}")

    final_text = _trim_telegram_message("\n\n".join(sections))
    questions.save_question(
        user_id=user_id,
        subject=subject,
        question=question_text,
        answer=response.text,
        source="ocr" if from_ocr else "text",
    )
    progress.record_doubt(user_id=user_id, subject=subject)

    await thinking_msg.edit_text(final_text, reply_markup=doubt_followup_keyboard(subject, settings))


@router.callback_query(F.data.startswith("subject:"))
async def cb_select_subject(callback: CallbackQuery, users: UserRepository, settings: Settings) -> None:
    """Set the student's active subject for text and image questions."""
    subject = callback.data.split("subject:", 1)[1]
    users.update_preferences(callback.from_user.id, active_subject=subject)
    label = _SUBJECT_LABELS.get(subject, subject.title())
    if callback.message:
        await callback.message.answer(
            f"{label} selected! Send your question as text (or `/ask <question>` in a group) or upload a clear photo.",
            reply_markup=back_to_menu_keyboard(settings),
            parse_mode="Markdown",
        )
    await callback.answer(f"Switched to {subject.title()}")


@router.callback_query(F.data == "menu:ncert")
async def cb_ncert_menu(callback: CallbackQuery, settings: Settings) -> None:
    """Show NCERT Explorer subject choices."""
    if callback.message:
        await callback.message.answer(
            "📚 <b>NCERT Explorer</b>\n\n"
            "Select a subject to see indexed NCERT chapters, or type any NCERT concept question directly.",
            reply_markup=ncert_subject_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("ncert:subj:"))
async def cb_ncert_chapters(
    callback: CallbackQuery,
    ncert: NCERTRAGService,
    users: UserRepository,
    settings: Settings,
) -> None:
    """List verified NCERT chapters available for a subject."""
    subject = callback.data.split("ncert:subj:", 1)[1]
    users.update_preferences(callback.from_user.id, active_subject=subject)
    chapters = ncert.list_chapters(subject=subject)
    if not chapters:
        text = (
            f"No verified NCERT passages are indexed for {subject.title()} yet. "
            "Add authorized NCERT JSON files under <code>data/ncert/</code> and restart the bot."
        )
    else:
        lines = [f"📚 <b>Indexed NCERT {subject.title()} Chapters:</b>\n"]
        for ch in chapters:
            lines.append(f"• Class {ch['class_level']} — Ch. {ch['chapter_number']}: {ch['chapter_title']}")
        lines.append("\nType any question from these chapters to get an NCERT-grounded answer!")
        text = "\n".join(lines)
    if callback.message:
        await callback.message.answer(text, reply_markup=back_to_menu_keyboard(settings), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("mode:"))
async def cb_reexplain_mode(
    callback: CallbackQuery,
    settings: Settings,
    ollama: OllamaClient,
    ncert: NCERTRAGService,
    questions: QuestionRepository,
    progress: ProgressRepository,
) -> None:
    """Re-explain the student's last question in simpler or exam-oriented mode."""
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
            settings=settings,
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
) -> None:
    """Handle plain-text doubts in private DM (and replies to the bot in group chats)."""
    if not message.from_user or not message.text:
        return

    # In group chats, only answer plain text when directly replying to the bot (use /ask otherwise)
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
        settings=settings,
        conversation_context=conv_context,
    )
