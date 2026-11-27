"""Main entrypoint for NEXA STUDY AI Telegram bot."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import sys
from pathlib import Path
from typing import TextIO

from aiogram import Bot, Dispatcher

from ai.ollama import OllamaClient
from config import Settings, configure_logging
from database.chats import ChatRepository
from database.mongo import MongoManager
from database.progress import ProgressRepository
from database.questions import QuestionRepository
from database.users import UserRepository
from handlers import admin, doubt, image, progress, pyq, quiz, start
from middlewares.security import RateLimitMiddleware, SlidingWindowRateLimiter
from middlewares.tracking import ActivityTrackingMiddleware
from services.ncert import NCERTRAGService
from services.ocr import OCRService
from services.pyq import PYQService
from services.quiz import QuizService

logger = logging.getLogger(__name__)


class SingleInstanceLock:
    """Prevents duplicate Telegram polling processes via OS file locking."""

    def __init__(self, lock_path: str) -> None:
        self._lock_path = Path(lock_path)
        self._handle: TextIO | None = None

    def acquire(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._lock_path.open("w", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise RuntimeError(
                f"Another NEXA STUDY AI polling instance is already running (lock: {self._lock_path})."
            ) from exc

    def release(self) -> None:
        if self._handle is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None


async def run_bot() -> None:
    """Initialize all services, check Ollama health, and start Telegram polling."""
    settings = Settings.from_env()
    configure_logging(settings)
    settings.validate_for_runtime()

    lock = SingleInstanceLock(settings.lock_file_path)
    lock.acquire()

    ollama = OllamaClient(settings)
    mongo = MongoManager(settings)
    mongo.connect()

    users = UserRepository(mongo)
    chats = ChatRepository(mongo)
    questions = QuestionRepository(mongo)
    progress_repo = ProgressRepository(mongo)

    ocr_service = OCRService(
        min_confidence=settings.ocr_min_confidence,
        lang=settings.ocr_lang,
    )
    ncert_service = NCERTRAGService(settings.data_dir / "ncert")
    pyq_service = PYQService(settings.data_dir / "pyq")
    quiz_service = QuizService(pyq_service)

    healthy, installed_models = await ollama.health_check()
    if healthy:
        logger.info("Ollama reachable at %s | installed models: %s", settings.ollama_base_url, installed_models)
        if settings.ollama_model not in installed_models:
            logger.warning(
                "Configured model '%s' not found in Ollama tags %s. "
                "Ensure your existing persistent Ollama volume is mounted.",
                settings.ollama_model,
                installed_models,
            )
    else:
        logger.warning(
            "Ollama is not reachable at %s during startup. The bot will still start and retry per request.",
            settings.ollama_base_url,
        )

    bot = Bot(token=settings.telegram_bot_token)
    bot_username = ""
    try:
        me = await bot.get_me()
        bot_username = me.username or ""
        logger.info("Authenticated as @%s", bot_username)
    except Exception as exc:
        logger.warning("Could not fetch bot username via getMe: %s", exc)

    dp = Dispatcher()

    # Track DM users and groups automatically for Owner Panel stats & broadcasts
    tracker_mw = ActivityTrackingMiddleware(users, chats)
    dp.message.middleware(tracker_mw)
    dp.callback_query.middleware(tracker_mw)

    limiter = SlidingWindowRateLimiter(
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    rate_mw = RateLimitMiddleware(limiter)
    dp.message.middleware(rate_mw)
    dp.callback_query.middleware(rate_mw)

    # Register routers (admin before doubt so owner broadcast messages aren't treated as doubts)
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(image.router)
    dp.include_router(pyq.router)
    dp.include_router(quiz.router)
    dp.include_router(progress.router)
    dp.include_router(doubt.router)

    # Dependency injection for aiogram 3.x handlers
    dp["settings"] = settings
    dp["bot_username"] = bot_username
    dp["mongo"] = mongo
    dp["ollama"] = ollama
    dp["ocr"] = ocr_service
    dp["ncert"] = ncert_service
    dp["pyq_service"] = pyq_service
    dp["quiz_service"] = quiz_service
    dp["users"] = users
    dp["chats"] = chats
    dp["questions"] = questions
    dp["progress"] = progress_repo

    logger.info(
        "Starting NEXA STUDY AI | NCERT chapters: %d | Verified PYQs: %d | Owners: %d | MongoDB: %s",
        len(ncert_service.list_chapters()),
        len(pyq_service.all_items),
        len(settings.owner_ids),
        "connected" if mongo.is_connected else "in-memory fallback",
    )

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await ollama.close()
        mongo.close()
        await bot.session.close()
        lock.release()
        logger.info("NEXA STUDY AI shut down cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
    except Exception as fatal_exc:
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).error("Fatal startup error: %s", fatal_exc)
        sys.exit(1)
