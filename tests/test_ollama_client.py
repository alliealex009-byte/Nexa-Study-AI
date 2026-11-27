"""Tests for async OllamaClient with mocked HTTPX transport."""

from __future__ import annotations

import json
import unittest

import httpx

from ai.ollama import OllamaClient, OllamaError
from config import Settings


class TestOllamaClient(unittest.IsolatedAsyncioTestCase):
    async def test_health_check_and_chat_generation(self) -> None:
        captured_payload: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]})
            if request.url.path == "/api/chat":
                captured_payload.update(json.loads(request.content.decode("utf-8")))
                return httpx.Response(
                    200,
                    json={
                        "model": "qwen2.5:3b",
                        "message": {"role": "assistant", "content": "a = F / m = 5 m/s²"},
                        "eval_count": 12,
                        "total_duration": 2_500_000_000,
                    },
                )
            return httpx.Response(404)

        settings = Settings(
            telegram_bot_token="dummy",
            ollama_base_url="http://127.0.0.1:11434",
            ollama_model="qwen2.5:3b",
            ollama_num_threads=2,
            ollama_num_ctx=2048,
        )
        client = OllamaClient(settings)
        client._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(handler),
        )

        healthy, models = await client.health_check()
        self.assertTrue(healthy)
        self.assertIn("qwen2.5:3b", models)

        resp = await client.generate_chat("System rules", "Find a for F=20, m=4")
        self.assertIn("5 m/s²", resp.text)
        self.assertEqual(captured_payload["options"]["num_thread"], 2)
        self.assertEqual(captured_payload["options"]["num_ctx"], 2048)
        await client.close()

    async def test_handles_http_error_cleanly(self) -> None:
        def error_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        settings = Settings(telegram_bot_token="dummy")
        client = OllamaClient(settings)
        client._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(error_handler),
        )
        with self.assertRaises(OllamaError):
            await client.generate_chat("sys", "usr")
        await client.close()


if __name__ == "__main__":
    unittest.main()
