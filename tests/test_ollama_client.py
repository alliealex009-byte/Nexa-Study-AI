"""Tests for async OllamaClient (text + direct qwen2.5vl:3b vision) with mocked HTTPX transport."""

from __future__ import annotations

import io
import json
import unittest

import httpx
from PIL import Image

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
        self.assertEqual(captured_payload["keep_alive"], "15m")
        await client.close()

    async def test_direct_vision_generation_sends_base64_image(self) -> None:
        captured_payload: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_payload.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "model": "qwen2.5vl:3b",
                    "message": {"role": "assistant", "content": "Correct Answer: A. Δt = (4/9) Δo"},
                },
            )

        img = Image.new("RGB", (1600, 900), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        settings = Settings(telegram_bot_token="dummy", ollama_vision_model="qwen2.5vl:3b")
        client = OllamaClient(settings)
        client._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(handler),
        )

        resp = await client.generate_vision("Sys", "Solve this", buf.getvalue())
        self.assertIn("Δt = (4/9) Δo", resp.text)
        self.assertEqual(captured_payload["model"], "qwen2.5vl:3b")
        images = captured_payload["messages"][1].get("images", [])
        self.assertEqual(len(images), 1)
        self.assertTrue(len(images[0]) > 50)
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
