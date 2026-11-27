"""Async Ollama client optimized for ARM64 CPU-only text & direct vision (qwen2.5vl:3b) inference."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image, ImageOps

from config import Settings

logger = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Raised when Ollama cannot complete a request."""


@dataclass(frozen=True)
class OllamaResponse:
    """Structured response from Ollama chat or vision generation."""

    text: str
    model: str
    eval_count: int = 0
    total_duration_ms: float = 0.0


def _prepare_vision_image_b64(image_bytes: bytes, max_width: int = 1024) -> str:
    """Downscale large phone photos to <=1024px JPEG so CPU vision inference stays fast & low-RAM."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            if img.width > max_width:
                ratio = max_width / img.width
                img = img.resize(
                    (max_width, max(1, int(img.height * ratio))),
                    Image.Resampling.LANCZOS,
                )
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85, optimize=True)
            return base64.b64encode(out.getvalue()).decode("ascii")
    except Exception:
        return base64.b64encode(image_bytes).decode("ascii")


class OllamaClient:
    """Lightweight async HTTPX client with strict concurrency control & keep-alive for 2-CPU VPS."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model
        self._vision_model = settings.ollama_vision_model
        self._timeout = settings.ollama_timeout_seconds
        self._num_threads = settings.ollama_num_threads
        self._num_ctx = settings.ollama_num_ctx
        self._temperature = settings.ollama_temperature
        self._semaphore = asyncio.Semaphore(settings.ollama_max_concurrent)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTPX connection pool."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    @property
    def is_busy(self) -> bool:
        """Return True if the single CPU inference slot is currently occupied."""
        return self._semaphore.locked()

    @property
    def vision_model(self) -> str:
        return self._vision_model

    async def health_check(self) -> tuple[bool, list[str]]:
        """Verify Ollama is reachable and list installed models without pulling new ones."""
        client = await self._get_client()
        try:
            resp = await client.get("/api/tags", timeout=10.0)
            resp.raise_for_status()
            payload = resp.json()
            models = [m.get("name", "") for m in payload.get("models", []) if isinstance(m, dict)]
            return True, models
        except Exception as exc:
            logger.warning("Ollama health check failed: %s", exc)
            return False, []

    async def _post_chat(self, payload: dict[str, Any], model_label: str) -> OllamaResponse:
        async with self._semaphore:
            client = await self._get_client()
            try:
                resp = await client.post("/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
            except httpx.TimeoutException as exc:
                logger.error("Ollama request timed out after %.1fs", self._timeout)
                raise OllamaError(
                    "AAKASH AI took too long to respond on CPU. Please try a shorter question or retry."
                ) from exc
            except httpx.HTTPStatusError as exc:
                logger.error("Ollama HTTP error %s", exc.response.status_code)
                raise OllamaError(
                    f"Local AI service returned HTTP {exc.response.status_code}. Check that model '{model_label}' is installed."
                ) from exc
            except httpx.RequestError as exc:
                logger.error("Cannot connect to Ollama at %s", self._base_url)
                raise OllamaError(
                    "Cannot reach the local AI service. Ensure the 'ollama' Docker container is running."
                ) from exc

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = (message.get("content") or "").strip()
        if not content:
            raise OllamaError("Local AI returned an empty response. Please try asking again.")

        total_ns = data.get("total_duration", 0) or 0
        return OllamaResponse(
            text=content,
            model=data.get("model", model_label),
            eval_count=int(data.get("eval_count", 0) or 0),
            total_duration_ms=round(total_ns / 1_000_000, 1),
        )

    async def generate_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int = 380,
    ) -> OllamaResponse:
        """Generate a fast, concise chat completion using the local Ollama container."""
        payload: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "keep_alive": "15m",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "num_thread": self._num_threads,
                "num_ctx": self._num_ctx,
                "num_predict": max_tokens,
                "temperature": self._temperature if temperature is None else temperature,
            },
        }
        return await self._post_chat(payload, self._model)

    async def generate_vision(
        self,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 420,
    ) -> OllamaResponse:
        """Solve an image question directly using a vision model (e.g., qwen2.5vl:3b or gemma3:4b)."""
        target_model = (model or self._vision_model).strip()
        if not target_model:
            raise OllamaError("No OLLAMA_VISION_MODEL configured.")

        b64_img = await asyncio.to_thread(_prepare_vision_image_b64, image_bytes)
        payload: dict[str, Any] = {
            "model": target_model,
            "stream": False,
            "keep_alive": "15m",
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": [b64_img],
                },
            ],
            "options": {
                "num_thread": self._num_threads,
                "num_ctx": self._num_ctx,
                "num_predict": max_tokens,
                "temperature": self._temperature if temperature is None else temperature,
            },
        }
        return await self._post_chat(payload, target_model)
