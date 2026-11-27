"""Image question solver handler using lightweight ARM64 Tesseract OCR + Ollama."""

from __future__ import annotations

import asyncio
import io
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from ai.ollama import OllamaClient
from config import Settings
from database.progress import ProgressRepository
from database.questions import QuestionRepository
from database.users import UserRepository
from handlers.doubt import answer_doubt
from keyboards.main import back_to_menu_keyboard
from services.ncert import NCERTRAGService
from services.ocr import OCRService

logger = logging.getLogger(__name__)
router = Router(name="image")

IMAGE_TIPS_TEXT = (
    "📸 **Solve from Image (OCR)**\n\n"
    "Send a photo (or image file) of your Biology, Chemistry, or Physics question right now.\n\n"
    "Tips for best accuracy:\n"
    "• Crop tightly around a single question.\n"
    "• Keep the page flat with bright, even lighting.\n"
    "• Printed text and neat handwriting work best.\n"
    "• You can add a caption like `Physics` or `Biology` to set the subject."
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
            parse_mode="Markdown",
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
) -> None:
    if not message.from_user:
        return

    status_msg = await message.answer("🔍 Reading text from your image (OCR)…")

    # Run CPU-bound Pillow + Tesseract in a worker thread so Telegram polling stays responsive
    ocr_result = await asyncio.to_thread(ocr.extract_text, image_bytes)

    if not ocr_result.is_readable:
        await status_msg.edit_text(
            f"⚠️ **Image Not Clear Enough**\n\n{ocr_result.reason}",
            reply_markup=back_to_menu_keyboard(settings),
            parse_mode="Markdown",
        )
        return

    user = users.upsert_user(
        message.from_user.id,
        first_name=message.from_user.first_name or "",
        username=message.from_user.username or "",
    )
    subject = _infer_subject_from_caption(caption, user.get("active_subject", "general"))
    mode = user.get("explanation_mode", "standard")

    preview = ocr_result.text[:400] + ("…" if len(ocr_result.text) > 400 else "")
    await status_msg.edit_text(
        f"✅ **Extracted Question** (OCR confidence: {ocr_result.confidence:.0f}%):\n\n{preview}",
        parse_mode="Markdown",
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
) -> None:
    """Download highest-resolution Telegram photo, run OCR, and solve via Ollama."""
    if not message.photo:
        return
    # In group chats, only run OCR on photos if caption mentions /ask or replies to the bot
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
    )
