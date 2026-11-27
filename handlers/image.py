"""Image question solver: Verified PYQ fast-match -> Direct Vision (qwen2.5vl:3b) -> Tesseract OCR fallback."""

from __future__ import annotations

import asyncio
import html as html_lib
import io
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from ai.formatter import detect_subject_from_text, format_ai_response_for_telegram
from ai.ollama import OllamaClient, OllamaError
from ai.prompts import build_system_prompt
from config import Settings
from database.progress import ProgressRepository
from database.questions import QuestionRepository
from database.users import UserRepository
from handlers.doubt import answer_doubt
from keyboards.main import back_to_menu_keyboard
from keyboards.subjects import doubt_followup_keyboard
from services.ncert import NCERTRAGService
from services.ocr import OCRService
from services.pyq import PYQService

logger = logging.getLogger(__name__)
router = Router(name="image")

IMAGE_TIPS_TEXT = (
    "📸 <b>Solve from Image (Vision AI + OCR)</b>\n\n"
    "Send a photo (or image file) of your Biology, Chemistry, or Physics question right now.\n\n"
    "Tips for best accuracy:\n"
    "• Crop tightly around a single question.\n"
    "• Keep the page flat with bright, even lighting.\n"
    "• Printed text, equations, diagrams, and neat handwriting are supported.\n"
    "• Add an optional caption like <code>Physics</code> or <code>Biology</code>."
)


def _infer_subject_from_caption(caption: str | None, fallback: str) -> str:
    if not caption:
        return fallback
    lower = caption.lower()
    for subj in ("biology", "chemistry", "physics"):
        if subj in lower:
            return subj
    return fallback


@router.callback_query(F.data == "menu:image")
async def cb_image_prompt(callback: CallbackQuery, settings: Settings) -> None:
    """Guide the student to upload a question photo."""
    if callback.message:
        await callback.message.answer(
            IMAGE_TIPS_TEXT,
            reply_markup=back_to_menu_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer()


async def _process_image_bytes(
    *,
    message: Message,
    image_bytes: bytes,
    caption: str | None,
    settings: Settings,
    ocr: OCRService,
    ollama: OllamaClient,
    ncert: NCERTRAGService,
    users: UserRepository,
    questions: QuestionRepository,
    progress: ProgressRepository,
    pyq_service: PYQService,
) -> None:
    if not message.from_user:
        return

    user = users.upsert_user(
        message.from_user.id,
        first_name=message.from_user.first_name or "",
        username=message.from_user.username or "",
    )
    fallback_subj = _infer_subject_from_caption(caption, user.get("active_subject", "general"))
    mode = user.get("explanation_mode", "standard")

    status_msg = await message.answer("🔍 Analyzing your question image…")

    # Step 1: Quick OCR check (<0.5s) — if it matches a verified 10-year PYQ, answer instantly!
    ocr_result = await asyncio.to_thread(ocr.extract_text, image_bytes)
    if ocr_result.is_readable:
        matched = pyq_service.find_matching_pyq(ocr_result.text)
        if matched is not None:
            await status_msg.delete()
            await answer_doubt(
                message=message,
                user_id=message.from_user.id,
                question_text=ocr_result.text,
                subject=matched.subject,
                mode=mode,
                ollama=ollama,
                ncert=ncert,
                questions=questions,
                progress=progress,
                pyq_service=pyq_service,
                settings=settings,
                from_ocr=True,
            )
            return

    # Step 2: If OLLAMA_VISION_MODEL (e.g. qwen2.5vl:3b) is configured, solve directly with Vision AI!
    if ollama.vision_model:
        subject = detect_subject_from_text(ocr_result.text or caption or "", fallback=fallback_subj)
        await status_msg.edit_text(
            f"👁️ AAKASH Vision AI (<code>{html_lib.escape(ollama.vision_model)}</code>) is reading &amp; solving your image…",
            parse_mode="HTML",
        )
        vision_prompt = (
            "Read the NEET/JEE question, equations, chemical symbols (like Δt, Δo), or diagram in this image carefully. "
            "If the image is too blurry or unreadable to be certain, say so clearly and ask for a clearer photo instead of guessing. "
            "Otherwise, state the correct answer clearly and give a concise step-by-step explanation."
        )
        if caption and caption.strip():
            vision_prompt += f"\n\nStudent note: {caption.strip()}"

        try:
            sys_prompt = build_system_prompt(subject=subject, mode=mode)
            resp = await ollama.generate_vision(
                system_prompt=sys_prompt,
                user_prompt=vision_prompt,
                image_bytes=image_bytes,
            )
            body_html = format_ai_response_for_telegram(resp.text, max_len=3600)
            questions.save_question(
                user_id=message.from_user.id,
                subject=subject,
                question=ocr_result.text or (caption or "[Image Question]"),
                answer=resp.text,
                source="vision",
            )
            progress.record_doubt(user_id=message.from_user.id, subject=subject)
            await status_msg.edit_text(
                f"👁️ <b>AAKASH Vision Solution</b>\n\n{body_html}",
                reply_markup=doubt_followup_keyboard(subject, settings),
                parse_mode="HTML",
            )
            return
        except OllamaError as exc:
            logger.warning("Direct vision model '%s' failed, falling back to Tesseract OCR: %s", ollama.vision_model, exc)

    # Step 3: Automatic fallback to Tesseract OCR + text model
    if not ocr_result.is_readable:
        await status_msg.edit_text(
            f"⚠️ <b>Image Not Clear Enough</b>\n\n{html_lib.escape(ocr_result.reason)}",
            reply_markup=back_to_menu_keyboard(settings),
            parse_mode="HTML",
        )
        return

    subject = detect_subject_from_text(ocr_result.text, fallback=fallback_subj)
    preview = ocr_result.text[:400] + ("…" if len(ocr_result.text) > 400 else "")
    await status_msg.edit_text(
        f"✅ <b>Extracted Question</b> (OCR confidence: {ocr_result.confidence:.0f}%):\n\n{html_lib.escape(preview)}",
        parse_mode="HTML",
    )

    combined_question = ocr_result.text
    if caption and caption.strip():
        combined_question = f"{ocr_result.text}\n\nStudent note: {caption.strip()}"

    await answer_doubt(
        message=message,
        user_id=message.from_user.id,
        question_text=combined_question,
        subject=subject,
        mode=mode,
        ollama=ollama,
        ncert=ncert,
        questions=questions,
        progress=progress,
        pyq_service=pyq_service,
        settings=settings,
        from_ocr=True,
    )


@router.message(F.photo)
async def handle_photo_question(
    message: Message,
    bot: Bot,
    settings: Settings,
    ocr: OCRService,
    ollama: OllamaClient,
    ncert: NCERTRAGService,
    users: UserRepository,
    questions: QuestionRepository,
    progress: ProgressRepository,
    pyq_service: PYQService,
) -> None:
    """Download highest-resolution Telegram photo and solve via PYQ match, Vision AI, or OCR."""
    if not message.photo:
        return
    if message.chat.type != "private":
        cap = (message.caption or "").lower()
        reply_to = message.reply_to_message
        if "/ask" not in cap and not (reply_to and reply_to.from_user and reply_to.from_user.is_bot):
            return

    photo = message.photo[-1]
    max_bytes = settings.max_image_size_mb * 1024 * 1024
    if photo.file_size and photo.file_size > max_bytes:
        await message.answer(
            f"⚠️ Image is larger than {settings.max_image_size_mb} MB. Please crop or compress it and resend."
        )
        return

    buffer = io.BytesIO()
    await bot.download(photo, destination=buffer)
    await _process_image_bytes(
        message=message,
        image_bytes=buffer.getvalue(),
        caption=message.caption,
        settings=settings,
        ocr=ocr,
        ollama=ollama,
        ncert=ncert,
        users=users,
        questions=questions,
        progress=progress,
        pyq_service=pyq_service,
    )


@router.message(F.document & F.document.mime_type.startswith("image/"))
async def handle_image_document(
    message: Message,
    bot: Bot,
    settings: Settings,
    ocr: OCRService,
    ollama: OllamaClient,
    ncert: NCERTRAGService,
    users: UserRepository,
    questions: QuestionRepository,
    progress: ProgressRepository,
    pyq_service: PYQService,
) -> None:
    """Support uncompressed image files sent as Telegram documents."""
    doc = message.document
    if not doc:
        return
    if message.chat.type != "private":
        cap = (message.caption or "").lower()
        reply_to = message.reply_to_message
        if "/ask" not in cap and not (reply_to and reply_to.from_user and reply_to.from_user.is_bot):
            return

    max_bytes = settings.max_image_size_mb * 1024 * 1024
    if doc.file_size and doc.file_size > max_bytes:
        await message.answer(
            f"⚠️ Image file exceeds {settings.max_image_size_mb} MB. Please send a smaller image."
        )
        return

    buffer = io.BytesIO()
    await bot.download(doc, destination=buffer)
    await _process_image_bytes(
        message=message,
        image_bytes=buffer.getvalue(),
        caption=message.caption,
        settings=settings,
        ocr=ocr,
        ollama=ollama,
        ncert=ncert,
        users=users,
        questions=questions,
        progress=progress,
        pyq_service=pyq_service,
    )
