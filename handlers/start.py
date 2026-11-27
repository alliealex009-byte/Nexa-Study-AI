"""Start, DM NEET/JEE onboarding, menu, inline sub-menus, widgets, settings, and help handlers."""

from __future__ import annotations

import html as html_lib

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from config import Settings
from database.progress import ProgressRepository
from database.users import UserRepository
from keyboards.main import (
    back_to_menu_keyboard,
    exam_onboarding_keyboard,
    main_menu_keyboard,
)
from keyboards.styles import tg_emoji
from keyboards.subjects import settings_keyboard, subject_submenu_keyboard, widget_menu_keyboard
from services.analytics import pick_motivational_quote
from services.pyq import PYQService
from services.widgets import (
    build_formula_timer_widget_html,
    build_progress_widget_html,
    build_pyq_flashcard_widget_html,
    send_widget_or_fallback,
)

router = Router(name="start")


def _welcome_html(settings: Settings, target_exam: str = "NEET UG") -> str:
    spark = tg_emoji("spark", settings)
    exam_label = html_lib.escape(target_exam)
    return (
        f"{spark} <b>Welcome to NEXA STUDY AI</b>\n\n"
        "Your free, self-hosted <b>NEET UG &amp; JEE</b> study assistant powered by <b>AAKASH AI</b>.\n"
        f"🎯 Active Exam Track: <b>{exam_label}</b>\n\n"
        "• Tap any colored subject button below for its inline sub-menu\n"
        "• Send a clear photo of a question for instant OCR / Vision AI\n"
        "• Use <code>/random</code>, <code>/neet</code>, <code>/jee</code>, or <code>/poll</code> in <b>DM or Group Chats</b>\n"
        "• Timers: <b>45s</b> (Bio/Chem) &amp; <b>60s</b> (Physics) with auto-next &amp; 4-min cleanup"
    )


def _help_html(settings: Settings) -> str:
    info = tg_emoji("help", settings)
    return (
        f"{info} <b>How to use NEXA STUDY AI</b>\n\n"
        "<b>1. Exam Track</b>: Choose NEET UG or JEE in DM (or Settings) to receive exam-matched questions.\n"
        "<b>2. Auto-Next Practice &amp; Polls</b>:\n"
        "   • <code>/random</code> or <code>/prep</code> — Auto-advancing 10-year PYQs (45s Bio/Chem, 60s Physics)\n"
        "   • <code>/poll</code> — Auto-advancing Telegram Quiz Polls (great for study groups!)\n"
        "   • <code>/neet</code> / <code>/jee</code> — Instant exam-specific random question\n"
        "   • Previous questions auto-delete after 4 minutes to keep chats clean.\n"
        "<b>3. Solve from Image</b>: Send any cropped, well-lit question photo.\n"
        "<b>4. Progress Graphics</b>: Tap <b>My Progress</b> or <code>/progress</code> for Today/Weekly/Monthly stats, weak-topic chart &amp; daily motivation.\n\n"
        "Commands: <code>/start</code>, <code>/menu</code>, <code>/random</code>, <code>/neet</code>, <code>/jee</code>, <code>/poll</code>, <code>/progress</code>, <code>/help</code>"
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    users: UserRepository,
    settings: Settings,
    bot_username: str = "",
) -> None:
    """Register user; in DM prompt first-time users to pick NEET UG or JEE."""
    user = {"target_exam": "NEET UG", "exam_selected": True}
    if message.from_user:
        user = users.upsert_user(
            message.from_user.id,
            first_name=message.from_user.first_name or "",
            username=message.from_user.username or "",
        )

    if message.chat.type == "private" and not user.get("exam_selected", False):
        spark = tg_emoji("spark", settings)
        await message.answer(
            f"{spark} <b>Welcome to NEXA STUDY AI</b> (powered by <b>AAKASH AI</b>)!\n\n"
            "Before we start, which exam are you preparing for?\n"
            "I'll save your choice in memory so your random prep, quizzes, and polls match your exact exam:",
            reply_markup=exam_onboarding_keyboard(settings),
            parse_mode="HTML",
        )
        return

    await message.answer(
        _welcome_html(settings, user.get("target_exam", "NEET UG")),
        reply_markup=main_menu_keyboard(settings, bot_username),
        parse_mode="HTML",
    )


@router.message(Command("menu"))
async def cmd_menu(
    message: Message,
    users: UserRepository,
    settings: Settings,
    bot_username: str = "",
) -> None:
    """Display main menu directly."""
    target_exam = "NEET UG"
    if message.from_user:
        user = users.get_user(message.from_user.id)
        target_exam = user.get("target_exam", "NEET UG")
    await message.answer(
        _welcome_html(settings, target_exam),
        reply_markup=main_menu_keyboard(settings, bot_username),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("onboard:exam:"))
async def cb_onboard_exam(
    callback: CallbackQuery,
    users: UserRepository,
    settings: Settings,
    bot_username: str = "",
) -> None:
    """Save the student's NEET UG or JEE exam choice in memory/MongoDB and open main menu."""
    exam = callback.data.split("onboard:exam:", 1)[1]
    users.update_preferences(callback.from_user.id, target_exam=exam, exam_selected=True)
    quote = pick_motivational_quote()
    if callback.message:
        await callback.message.answer(
            f"✅ Saved! You are now on the <b>{html_lib.escape(exam)}</b> track — you'll get <b>{html_lib.escape(exam)}</b> questions automatically.\n\n"
            f"💡 <i>{html_lib.escape(quote)}</i>\n\n"
            + _welcome_html(settings, exam),
            reply_markup=main_menu_keyboard(settings, bot_username),
            parse_mode="HTML",
        )
    await callback.answer(f"Exam saved: {exam}")


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    """Show usage guide."""
    await message.answer(
        _help_html(settings),
        reply_markup=back_to_menu_keyboard(settings),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:home")
async def cb_home(
    callback: CallbackQuery,
    users: UserRepository,
    settings: Settings,
    bot_username: str = "",
) -> None:
    """Return to main menu."""
    user = users.get_user(callback.from_user.id)
    if callback.message:
        await callback.message.answer(
            _welcome_html(settings, user.get("target_exam", "NEET UG")),
            reply_markup=main_menu_keyboard(settings, bot_username),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "menu:help")
async def cb_help(callback: CallbackQuery, settings: Settings) -> None:
    """Display help text from main menu."""
    if callback.message:
        await callback.message.answer(
            _help_html(settings),
            reply_markup=back_to_menu_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("submenu:subject:"))
async def cb_subject_submenu(callback: CallbackQuery, users: UserRepository, settings: Settings) -> None:
    """Open colored inline sub-menu for Biology, Chemistry, or Physics."""
    subject = callback.data.split("submenu:subject:", 1)[1]
    users.update_preferences(callback.from_user.id, active_subject=subject)
    icon = tg_emoji(subject, settings)
    if callback.message:
        await callback.message.answer(
            f"{icon} <b>{subject.title()} Study Hub</b>\n\nChoose an action below:",
            reply_markup=subject_submenu_keyboard(subject, settings),
            parse_mode="HTML",
        )
    await callback.answer(f"{subject.title()} hub")


@router.message(Command("widget"))
async def cmd_widget(message: Message, settings: Settings) -> None:
    """Open the interactive study cards hub."""
    icon = tg_emoji("widget", settings)
    await message.answer(
        f"{icon} <b>Interactive Study Cards</b>\n\nTap a card below to launch:",
        reply_markup=widget_menu_keyboard(settings),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:widgets")
async def cb_widget_menu(callback: CallbackQuery, settings: Settings) -> None:
    """Display the interactive widgets sub-menu."""
    icon = tg_emoji("widget", settings)
    if callback.message:
        await callback.message.answer(
            f"{icon} <b>Interactive Study Cards</b>\n\nChoose a card to launch:",
            reply_markup=widget_menu_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("widget:"))
async def cb_send_widget(
    callback: CallbackQuery,
    bot: Bot,
    settings: Settings,
    progress: ProgressRepository,
    pyq_service: PYQService,
    users: UserRepository,
) -> None:
    """Send one of the interactive study cards (with safe fallback)."""
    if not callback.message:
        await callback.answer()
        return

    kind = callback.data.split("widget:", 1)[1]
    chat_id = callback.message.chat.id
    chat_type = callback.message.chat.type
    user = users.get_user(callback.from_user.id)

    if kind == "progress":
        summary = progress.get_summary(callback.from_user.id)
        widget_html = build_progress_widget_html(summary, callback.from_user.first_name or "Student")
        fallback = (
            f"📊 <b>Progress Snapshot</b>\n"
            f"• Today: <b>{summary['today_questions']}</b> | Weekly: <b>{summary['weekly_questions']}</b> | Monthly: <b>{summary['monthly_questions']}</b>\n"
            f"• Accuracy: <b>{summary['quiz_accuracy']:.1f}%</b>"
        )
        await send_widget_or_fallback(
            bot=bot,
            chat_id=chat_id,
            chat_type=chat_type,
            widget_html=widget_html,
            caption="📊 <b>Your Live Progress Card</b>",
            fallback_text=fallback,
            reply_markup=widget_menu_keyboard(settings),
            enabled=settings.enable_telegram_widgets,
            height=300,
        )
    elif kind == "pyq":
        item = pyq_service.random_question(exam=user.get("target_exam"))
        if not item:
            await callback.answer("No PYQs available.", show_alert=True)
            return
        widget_html = build_pyq_flashcard_widget_html(item)
        fallback = (
            f"📝 <b>{html_lib.escape(item.exam)} {item.year}</b> ({html_lib.escape(item.chapter)})\n\n"
            f"{html_lib.escape(item.question)}\n\n"
            "Tap /random for interactive buttons!"
        )
        await send_widget_or_fallback(
            bot=bot,
            chat_id=chat_id,
            chat_type=chat_type,
            widget_html=widget_html,
            caption=f"📝 <b>Interactive {html_lib.escape(item.exam)} {item.year} Flashcard</b>",
            fallback_text=fallback,
            reply_markup=widget_menu_keyboard(settings),
            enabled=settings.enable_telegram_widgets,
            height=380,
        )
    else:
        widget_html = build_formula_timer_widget_html()
        fallback = (
            "⏱️ <b>NEET/JEE High-Yield Formula Snapshot</b>\n\n"
            "• Physics: F = dp/dt = m·a | F = k|q₁q₂|/r²\n"
            "• Chemistry: ΔG° = -RT ln K | p₁ = p₁°·x₁\n"
            "• Biology: Mitochondria = 70S ribosomes + circular DNA"
        )
        await send_widget_or_fallback(
            bot=bot,
            chat_id=chat_id,
            chat_type=chat_type,
            widget_html=widget_html,
            caption="⏱️ <b>Interactive Pomodoro &amp; Formula Card</b>",
            fallback_text=fallback,
            reply_markup=widget_menu_keyboard(settings),
            enabled=settings.enable_telegram_widgets,
            height=220,
        )
    await callback.answer("Ready!")


@router.callback_query(F.data == "menu:settings")
async def cb_settings(callback: CallbackQuery, users: UserRepository, settings: Settings) -> None:
    """Show user settings panel."""
    user = users.get_user(callback.from_user.id)
    icon = tg_emoji("settings", settings)
    text = (
        f"{icon} <b>Your Study Settings</b>\n\n"
        f"• Target Exam: <b>{html_lib.escape(str(user.get('target_exam', 'NEET UG')))}</b>\n"
        f"• Explanation Style: <b>{html_lib.escape(str(user.get('explanation_mode', 'standard')).title())}</b>\n"
        f"• Active Subject: <b>{html_lib.escape(str(user.get('active_subject', 'general')).title())}</b>\n\n"
        "Tap an option below to update:"
    )
    if callback.message:
        await callback.message.answer(
            text,
            reply_markup=settings_keyboard(
                user.get("target_exam", "NEET UG"),
                user.get("explanation_mode", "standard"),
                settings,
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("set:exam:"))
async def cb_set_exam(callback: CallbackQuery, users: UserRepository, settings: Settings) -> None:
    """Update user's target exam preference."""
    exam = callback.data.split("set:exam:", 1)[1]
    user = users.update_preferences(callback.from_user.id, target_exam=exam, exam_selected=True)
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=settings_keyboard(user["target_exam"], user["explanation_mode"], settings)
        )
    await callback.answer(f"Target exam set to {exam}")


@router.callback_query(F.data.startswith("set:mode:"))
async def cb_set_mode(callback: CallbackQuery, users: UserRepository, settings: Settings) -> None:
    """Update user's default explanation style."""
    mode = callback.data.split("set:mode:", 1)[1]
    user = users.update_preferences(callback.from_user.id, explanation_mode=mode)
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=settings_keyboard(user["target_exam"], user["explanation_mode"], settings)
        )
    await callback.answer(f"Explanation style set to {mode.title()}")
