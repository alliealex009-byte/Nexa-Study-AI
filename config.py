"""Configuration management and secret-safe logging for NEXA STUDY AI."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class SecretRedactionFilter(logging.Filter):
    """Prevents Telegram tokens, MongoDB credentials, and secrets from appearing in logs."""

    _PATTERNS = [
        re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
        re.compile(r"(mongodb(?:\+srv)?://[^:\s]+:)([^@\s]+)(@)"),
        re.compile(r"(?i)(token|password|secret|api[_-]?key)\s*[:=]\s*([^\s,;]+)"),
    ]

    def __init__(self, secrets_to_mask: list[str] | None = None) -> None:
        super().__init__()
        self._secrets = [s for s in (secrets_to_mask or []) if s and len(s) >= 6]

    def _redact(self, text: str) -> str:
        masked = text
        for secret in self._secrets:
            masked = masked.replace(secret, "[REDACTED]")
        masked = self._PATTERNS[0].sub("[REDACTED_BOT_TOKEN]", masked)
        masked = self._PATTERNS[1].sub(r"\1[REDACTED]\3", masked)
        masked = self._PATTERNS[2].sub(r"\1=[REDACTED]", masked)
        return masked

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    self._redact(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: self._redact(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        return True


DEFAULT_PREMIUM_EMOJI_KEYS = (
    "biology",
    "chemistry",
    "physics",
    "image",
    "ncert",
    "pyq",
    "quiz",
    "progress",
    "settings",
    "help",
    "random",
    "widget",
    "home",
    "spark",
    "check",
    "cancel",
)


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    telegram_bot_token: str
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_seconds: float = 120.0
    ollama_num_threads: int = 2
    ollama_num_ctx: int = 2048
    ollama_temperature: float = 0.3
    ollama_max_concurrent: int = 1
    mongodb_uri: str = ""
    mongodb_db_name: str = "nexa_study_ai"
    mongodb_timeout_ms: int = 5000
    question_ttl_days: int = 90
    rate_limit_requests: int = 8
    rate_limit_window_seconds: int = 60
    max_input_chars: int = 1500
    max_image_size_mb: int = 5
    ocr_min_confidence: float = 45.0
    ocr_lang: str = "eng"
    lock_file_path: str = "/tmp/nexa_study_ai.lock"
    log_level: str = "INFO"
    data_dir: Path = BASE_DIR / "data"
    # Telegram Bot API 9.4+ & 10.4+ UI features
    enable_colored_buttons: bool = True
    enable_premium_emoji: bool = True
    enable_telegram_widgets: bool = True
    premium_emoji_ids: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "Settings":
        """Load and validate settings from environment variables and optional .env file."""
        if env_file is not None:
            load_dotenv(dotenv_path=env_file, override=False)
        else:
            load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)

        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
        if not ollama_url.startswith(("http://", "https://")):
            raise ValueError("OLLAMA_BASE_URL must start with http:// or https://")

        emoji_map: dict[str, str] = {}
        for key in DEFAULT_PREMIUM_EMOJI_KEYS:
            val = os.getenv(f"PREMIUM_EMOJI_{key.upper()}", "").strip()
            if val:
                emoji_map[key] = val

        return cls(
            telegram_bot_token=token,
            ollama_base_url=ollama_url,
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b").strip(),
            ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
            ollama_num_threads=max(1, int(os.getenv("OLLAMA_NUM_THREADS", "2"))),
            ollama_num_ctx=max(512, int(os.getenv("OLLAMA_NUM_CTX", "2048"))),
            ollama_temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0.3")),
            ollama_max_concurrent=max(1, int(os.getenv("OLLAMA_MAX_CONCURRENT", "1"))),
            mongodb_uri=os.getenv("MONGODB_URI", "").strip(),
            mongodb_db_name=os.getenv("MONGODB_DB_NAME", "nexa_study_ai").strip() or "nexa_study_ai",
            mongodb_timeout_ms=max(1000, int(os.getenv("MONGODB_TIMEOUT_MS", "5000"))),
            question_ttl_days=max(7, int(os.getenv("QUESTION_TTL_DAYS", "90"))),
            rate_limit_requests=max(1, int(os.getenv("RATE_LIMIT_REQUESTS", "8"))),
            rate_limit_window_seconds=max(10, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))),
            max_input_chars=max(200, int(os.getenv("MAX_INPUT_CHARS", "1500"))),
            max_image_size_mb=max(1, int(os.getenv("MAX_IMAGE_SIZE_MB", "5"))),
            ocr_min_confidence=float(os.getenv("OCR_MIN_CONFIDENCE", "45.0")),
            ocr_lang=os.getenv("OCR_LANG", "eng").strip() or "eng",
            lock_file_path=os.getenv("LOCK_FILE_PATH", "/tmp/nexa_study_ai.lock").strip(),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            data_dir=Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))),
            enable_colored_buttons=_parse_bool(os.getenv("ENABLE_COLORED_BUTTONS"), default=True),
            enable_premium_emoji=_parse_bool(os.getenv("ENABLE_PREMIUM_EMOJI"), default=True),
            enable_telegram_widgets=_parse_bool(os.getenv("ENABLE_TELEGRAM_WIDGETS"), default=True),
            premium_emoji_ids=emoji_map,
        )

    def validate_for_runtime(self) -> None:
        """Validate required runtime secrets before starting polling."""
        if not self.telegram_bot_token or self.telegram_bot_token == "your_bot_token_from_botfather":
            raise ValueError(
                "TELEGRAM_BOT_TOKEN is missing or still set to the example placeholder. "
                "Update your .env file before starting the bot."
            )


def configure_logging(settings: Settings) -> None:
    """Configure application logging with automatic secret redaction."""
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redaction_filter = SecretRedactionFilter(
        secrets_to_mask=[settings.telegram_bot_token, settings.mongodb_uri]
    )
    root_logger = logging.getLogger()
    root_logger.addFilter(redaction_filter)
    for handler in root_logger.handlers:
        handler.addFilter(redaction_filter)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
