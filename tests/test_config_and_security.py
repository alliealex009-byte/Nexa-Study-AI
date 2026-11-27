"""Tests for configuration, secret redaction, input validation, and rate limiting."""

from __future__ import annotations

import logging
import unittest

from config import SecretRedactionFilter, Settings
from middlewares.security import SlidingWindowRateLimiter, sanitize_user_text


class TestConfigAndSecurity(unittest.TestCase):
    def test_secret_redaction_masks_tokens_and_mongo_uri(self) -> None:
        filt = SecretRedactionFilter(["super_secret_token_123"])
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Bot token 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg and mongodb+srv://user:myPass99@cluster.mongodb.net/db",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        self.assertNotIn("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ", record.msg)
        self.assertNotIn("myPass99", record.msg)
        self.assertIn("[REDACTED_BOT_TOKEN]", record.msg)
        self.assertIn("[REDACTED]", record.msg)

    def test_validate_for_runtime_rejects_placeholder(self) -> None:
        settings = Settings(telegram_bot_token="your_bot_token_from_botfather")
        with self.assertRaises(ValueError):
            settings.validate_for_runtime()

    def test_sanitize_user_text(self) -> None:
        cleaned, err = sanitize_user_text("  What is Newton's \x00second law?  ")
        self.assertIsNone(err)
        self.assertEqual(cleaned, "What is Newton's second law?")

        _, err_empty = sanitize_user_text("   ")
        self.assertIsNotNone(err_empty)

        _, err_long = sanitize_user_text("a" * 500, max_chars=200)
        self.assertIsNotNone(err_long)

    def test_rate_limiter_sliding_window(self) -> None:
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10)
        self.assertEqual(limiter.check(101, now=1.0), (True, 0))
        self.assertEqual(limiter.check(101, now=2.0), (True, 0))
        allowed, retry = limiter.check(101, now=3.0)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry, 1)
        # After window passes, request is allowed again
        self.assertEqual(limiter.check(101, now=12.0), (True, 0))


if __name__ == "__main__":
    unittest.main()
