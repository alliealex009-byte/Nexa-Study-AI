"""Owner Panel handler: live stats, 1-tap 5K open-source PYQ sync, and safe broadcasting."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import platform
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ai.ollama import OllamaClient
from config import Settings
from database.chats import ChatRepository
from database.mongo import MongoManager
from database.progress import ProgressRepository
from database.users import UserRepository
from keyboards.styles import styled_button
from scripts.import_opensource_pyqs import sync_opensource_5k
from services.ncert import NCERTRAGService
from services.pyq import PYQService

logger = logging.getLogger(__name__)
router = Router(name="admin")

_PENDING_BROADCAST: dict[int, str] = {}


def owner_panel_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Colored Bot API 9.4 Owner Panel inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("📊 Live Stats", callback_data="admin:stats", style="primary", settings=settings),
                styled_button("🩺 System Health", callback_data="admin:health", style="primary", settings=settings),
            ],
            [
                styled_button("📢 Broadcast DM Users", callback_data="admin:bcast:dm", style="success", settings=settings),
                styled_button("👥 Broadcast Groups", callback_data="admin:bcast:groups", style="success", settings=settings),
            ],
            [
                styled_button("🌐 Broadcast All (DM + Groups)", callback_data="admin:bcast:all", style="danger", settings=settings),
            ],
            [
                styled_button("📥 Sync 5K Open-Source Bank", callback_data="admin:sync5k", style="primary", settings=settings),
            ],
            [
                styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings),
            ],
        ]
    )


def _cancel_broadcast_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [styled_button("Cancel Broadcast", callback_data="admin:bcast:cancel", style="danger", emoji_key="cancel", settings=settings)]
        ]
    )


async def run_broadcast(
    bot: Any,
    target_ids: list[int],
    *,
    text: str | None = None,
    from_chat_id: int | None = None,
    message_id: int | None = None,
    chats: ChatRepository | None = None,
    delay_seconds: float = 0.05,
) -> dict[str, int]:
    """Send a broadcast safely at ~20 msgs/sec, handling blocked users and removed groups cleanly."""
    delivered = 0
    failed = 0
    unique_ids = list(dict.fromkeys(target_ids))

    for chat_id in unique_ids:
        try:
            if from_chat_id is not None and message_id is not None:
                await bot.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id)
            elif text:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            else:
                continue
            delivered += 1
        except Exception as exc:
            failed += 1
            err_lower = str(exc).lower()
            if chats is not None and chat_id < 0 and ("kicked" in err_lower or "not found" in err_lower):
                chats.remove_group(chat_id)
            logger.debug("Broadcast failed for chat_id=%s: %s", chat_id, exc)
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

    return {"total": len(unique_ids), "delivered": delivered, "failed": failed}


def _build_stats_html(
    users: UserRepository,
    chats: ChatRepository,
    progress: ProgressRepository,
    pyq_service: PYQService,
    ncert: NCERTRAGService,
    mongo: MongoManager,
) -> str:
    u = users.get_user_stats()
    g = chats.get_group_stats()
    p = progress.get_global_stats()

    recent_group_lines = ""
    if g["recent_groups"]:
        names = "\n".join(
            f"  • {html_lib.escape(str(item['title']))} (<code>{item['chat_id']}</code>)"
            for item in g["recent_groups"]
        )
        recent_group_lines = f"\n\n<b>Recent Active Groups:</b>\n{names}"

    return (
        "👑 <b>NEXA STUDY AI — Live Owner Stats</b>\n\n"
        "<b>👥 Audience:</b>\n"
        f"• DM Users: <b>{u['total_users']}</b> (NEET: <b>{u['neet_users']}</b> | JEE: <b>{u['jee_users']}</b>)\n"
        f"• Active Users: 24h: <b>{u['active_24h']}</b> | 7d: <b>{u['active_7d']}</b>\n"
        f"• Groups / Supergroups: <b>{g['total_groups']}</b>\n\n"
        "<b>📈 Platform Activity:</b>\n"
        f"• Total Questions Attempted: <b>{p['total_attempted']}</b>\n"
        f"• Total Questions Solved: <b>{p['total_solved']}</b>\n"
        f"• Total Quizzes Completed: <b>{p['total_quizzes']}</b>\n\n"
        "<b>📚 Content &amp; Storage:</b>\n"
        f"• Loaded PYQ / Prep Bank: <b>{len(pyq_service.all_items)}</b> questions\n"
        f"• Indexed NCERT Chapters: <b>{len(ncert.list_chapters())}</b>\n"
        f"• Database: <b>{'MongoDB Connected' if mongo.is_connected else 'In-Memory Fallback'}</b>"
        f"{recent_group_lines}"
    )


@router.message(Command("admin"))
@router.message(Command("owner"))
async def cmd_owner_panel(message: Message, settings: Settings) -> None:
    """Open the Owner Panel (strictly restricted to OWNER_IDS in .env)."""
    uid = message.from_user.id if message.from_user else None
    if not settings.is_owner(uid):
        await message.answer("⛔ Owner access only.")
        return

    await message.answer(
        "👑 <b>NEXA STUDY AI — Owner Panel</b>\n\n"
        "Manage broadcasts, inspect DM &amp; Group stats, sync 5,000+ open-source questions, and check live AI health.\n"
        "Quick command: <code>/broadcast &lt;message&gt;</code> (or reply to any photo/post with <code>/broadcast</code>).",
        reply_markup=owner_panel_keyboard(settings),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:sync5k")
async def cb_admin_sync_5k(
    callback: CallbackQuery,
    settings: Settings,
    pyq_service: PYQService,
) -> None:
    """Download up to 5,000 open-source NEET/JEE questions from HuggingFace and hot-reload PYQService."""
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("⛔ Owner access only.", show_alert=True)
        return
    if not callback.message:
        await callback.answer()
        return

    await callback.answer("Starting 5K open-source sync…")
    status = await callback.message.answer(
        "📥 Downloading up to <b>5,000</b> open-source NEET &amp; JEE questions from HuggingFace…\n"
        "<i>This runs in the background and hot-reloads automatically when done.</i>",
        parse_mode="HTML",
    )
    try:
        out_path = settings.data_dir / "pyq" / "opensource_5k_bank.json"
        imported = await asyncio.to_thread(sync_opensource_5k, out_path, 5000)
        total_loaded = pyq_service.reload()
        await status.edit_text(
            f"✅ <b>Open-Source Sync Complete!</b>\n"
            f"• Imported: <b>{imported}</b> questions\n"
            f"• Total Active Question Bank: <b>{total_loaded}</b> questions (zero-repeat ready!)",
            reply_markup=owner_panel_keyboard(settings),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning("5K open-source sync failed: %s", exc)
        await status.edit_text(
            f"⚠️ Sync failed: <code>{html_lib.escape(str(exc)[:250])}</code>\n"
            "You can also run <code>python3 scripts/import_opensource_pyqs.py --sync-5k</code> directly on your VPS.",
            reply_markup=owner_panel_keyboard(settings),
            parse_mode="HTML",
        )


@router.message(Command("broadcast"))
async def cmd_quick_broadcast(
    message: Message,
    bot: Bot,
    settings: Settings,
    users: UserRepository,
    chats: ChatRepository,
) -> None:
    """Broadcast text or a replied message to all DM users and groups."""
    uid = message.from_user.id if message.from_user else None
    if not settings.is_owner(uid):
        await message.answer("⛔ Owner access only.")
        return

    parts = (message.text or "").split(maxsplit=1)
    reply_msg = message.reply_to_message
    if len(parts) < 2 and reply_msg is None:
        await message.answer(
            "Usage:\n• <code>/broadcast Your announcement here</code>\n"
            "• Or reply to any photo/message with <code>/broadcast</code>",
            parse_mode="HTML",
        )
        return

    targets = users.get_all_user_ids() + chats.get_all_group_ids()
    status = await message.answer(f"📢 Broadcasting to <b>{len(set(targets))}</b> chats…", parse_mode="HTML")

    if reply_msg is not None:
        report = await run_broadcast(
            bot,
            targets,
            from_chat_id=reply_msg.chat.id,
            message_id=reply_msg.message_id,
            chats=chats,
        )
    else:
        report = await run_broadcast(
            bot,
            targets,
            text=f"📢 <b>Announcement from NEXA STUDY AI</b>\n\n{html_lib.escape(parts[1].strip())}",
            chats=chats,
        )

    await status.edit_text(
        f"✅ <b>Broadcast Finished</b>\n"
        f"• Targets: <b>{report['total']}</b>\n"
        f"• Delivered: <b>{report['delivered']}</b>\n"
        f"• Failed/Blocked: <b>{report['failed']}</b>",
        reply_markup=owner_panel_keyboard(settings),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(
    callback: CallbackQuery,
    settings: Settings,
    users: UserRepository,
    chats: ChatRepository,
    progress: ProgressRepository,
    pyq_service: PYQService,
    ncert: NCERTRAGService,
    mongo: MongoManager,
) -> None:
    """Show live DM, Group, and platform stats."""
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("⛔ Owner access only.", show_alert=True)
        return
    text = _build_stats_html(users, chats, progress, pyq_service, ncert, mongo)
    if callback.message:
        await callback.message.answer(text, reply_markup=owner_panel_keyboard(settings), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:health")
async def cb_admin_health(
    callback: CallbackQuery,
    settings: Settings,
    ollama: OllamaClient,
    mongo: MongoManager,
) -> None:
    """Check Ollama container health, installed models, and MongoDB connection."""
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("⛔ Owner access only.", show_alert=True)
        return

    healthy, models = await ollama.health_check()
    models_str = ", ".join(models) if models else "None detected"
    text = (
        "🩺 <b>System Health</b>\n\n"
        f"• Ollama API: <b>{'Online ✅' if healthy else 'Unreachable ❌'}</b>\n"
        f"• Text Model: <code>{html_lib.escape(settings.ollama_model)}</code>\n"
        f"• Vision Model: <code>{html_lib.escape(settings.ollama_vision_model or 'Tesseract OCR mode')}</code>\n"
        f"• Installed Models: <code>{html_lib.escape(models_str)}</code>\n"
        f"• AI Slot Busy: <b>{'Yes' if ollama.is_busy else 'Idle'}</b>\n"
        f"• MongoDB: <b>{'Connected ✅' if mongo.is_connected else 'In-Memory Fallback ⚠️'}</b>\n"
        f"• Host Arch: <code>{html_lib.escape(platform.machine())}</code> | Python <code>{platform.python_version()}</code>"
    )
    if callback.message:
        await callback.message.answer(text, reply_markup=owner_panel_keyboard(settings), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin:bcast:"))
async def cb_admin_broadcast_prompt(callback: CallbackQuery, settings: Settings) -> None:
    """Start or cancel interactive owner broadcast mode."""
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("⛔ Owner access only.", show_alert=True)
        return

    target = callback.data.split("admin:bcast:", 1)[1]
    if target == "cancel":
        _PENDING_BROADCAST.pop(callback.from_user.id, None)
        if callback.message:
            await callback.message.answer("🛑 Broadcast cancelled.", reply_markup=owner_panel_keyboard(settings))
        await callback.answer("Cancelled")
        return

    _PENDING_BROADCAST[callback.from_user.id] = target
    label = {"dm": "all DM users", "groups": "all Groups", "all": "ALL DM users & Groups"}.get(target, target)
    if callback.message:
        await callback.message.answer(
            f"📢 <b>Broadcast Mode ({label})</b>\n\n"
            "Send the message (text, photo, or forwarded post) you want to broadcast now:",
            reply_markup=_cancel_broadcast_keyboard(settings),
            parse_mode="HTML",
        )
    await callback.answer("Send your broadcast message")


@router.message(lambda msg: msg.from_user is not None and msg.from_user.id in _PENDING_BROADCAST)
async def handle_pending_broadcast_message(
    message: Message,
    bot: Bot,
    settings: Settings,
    users: UserRepository,
    chats: ChatRepository,
) -> None:
    """Capture the owner's next message and broadcast it to the selected audience."""
    if not message.from_user or not settings.is_owner(message.from_user.id):
        return

    target = _PENDING_BROADCAST.pop(message.from_user.id, "all")
    if target == "dm":
        target_ids = users.get_all_user_ids()
    elif target == "groups":
        target_ids = chats.get_all_group_ids()
    else:
        target_ids = users.get_all_user_ids() + chats.get_all_group_ids()

    status = await message.answer(f"📢 Broadcasting to <b>{len(set(target_ids))}</b> chats…", parse_mode="HTML")
    report = await run_broadcast(
        bot,
        target_ids,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
        chats=chats,
    )
    await status.edit_text(
        f"✅ <b>Broadcast Finished ({target.upper()})</b>\n"
        f"• Targets: <b>{report['total']}</b>\n"
        f"• Delivered: <b>{report['delivered']}</b>\n"
        f"• Failed/Blocked: <b>{report['failed']}</b>",
        reply_markup=owner_panel_keyboard(settings),
        parse_mode="HTML",
    )
