"""Single entry point for text generation with automatic provider fallback.

Order of attempts:
    1. Gemini (google-genai) -- native multimodal, understands YouTube URLs directly.
    2. OpenRouter ``google/gemma-4-31b-it:free``
    3. OpenRouter ``z-ai/glm-5.3-flash``

The OpenRouter models are text-only, so when a call carried a video the router
swaps the video for its transcript before retrying. Callers do not have to know
which provider answered.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import aiohttp

from config import Config

try:  # Optional: the bot still runs (on OpenRouter alone) without the SDK.
    from google import genai  # type: ignore
    from google.genai import types as genai_types  # type: ignore
except ImportError:  # pragma: no cover - exercised only on installs without the SDK
    genai = None  # type: ignore
    genai_types = None  # type: ignore

from models.gemini_utils import (
    apply_thinking_defaults,
    describe_gemini_response,
    extract_gemini_text,
)

logger = logging.getLogger(__name__)

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class AIResult:
    """What came back, and who produced it."""

    text: str
    provider: str
    model: str
    used_transcript: bool = False
    attempts: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.text)


class _CircuitBreaker:
    """Stops hammering a provider that just told us to go away.

    A provider trips open after ``threshold`` consecutive failures and stays
    open for ``cooldown`` seconds. Without this a rate-limited free model burns
    a full HTTP round trip on every single announcement.
    """

    def __init__(self, threshold: int = 3, cooldown: float = 300.0):
        self.threshold = threshold
        self.cooldown = cooldown
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def is_open(self, key: str) -> bool:
        until = self._open_until.get(key, 0.0)
        if until and time.monotonic() < until:
            return True
        if until:
            # Cooldown elapsed - give the provider another chance.
            self._open_until.pop(key, None)
            self._failures.pop(key, None)
        return False

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)
        self._open_until.pop(key, None)

    def record_failure(self, key: str) -> None:
        count = self._failures.get(key, 0) + 1
        self._failures[key] = count
        if count >= self.threshold:
            self._open_until[key] = time.monotonic() + self.cooldown
            logger.warning(
                "AI provider %s tripped its circuit breaker after %s failures; "
                "skipping it for %.0fs",
                key,
                count,
                self.cooldown,
            )


class AIRouter:
    """Gemini-first text generation with OpenRouter models behind it."""

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        openrouter_api_key: Optional[str] = None,
        openrouter_models: Optional[Sequence[str]] = None,
    ):
        self.gemini_api_key = gemini_api_key or Config.GEMINI_API_KEY
        self.openrouter_api_key = openrouter_api_key or Config.OPENROUTER_API_KEY
        self.openrouter_models = list(openrouter_models or Config.OPENROUTER_MODELS)
        self.gemini_model = Config.GEMINI_TEXT_MODEL

        self._breaker = _CircuitBreaker()
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()

        self._gemini_client = None
        if self.gemini_api_key and genai is not None:
            try:
                self._gemini_client = genai.Client(api_key=self.gemini_api_key)
            except Exception as exc:
                logger.error("Failed to construct Gemini client: %s", exc)

        if not self._gemini_client and not self.openrouter_api_key:
            logger.warning(
                "AIRouter has no usable provider (no Gemini client, no OpenRouter key)"
            )
        else:
            logger.info(
                "AIRouter ready - gemini=%s openrouter=%s",
                bool(self._gemini_client),
                ", ".join(self.openrouter_models) if self.openrouter_api_key else "off",
            )

    @property
    def available(self) -> bool:
        return bool(self._gemini_client or self.openrouter_api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        # Lazily created so the router can be constructed outside a running loop.
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=Config.AI_REQUEST_TIMEOUT)
                )
            return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        *,
        video_url: Optional[str] = None,
        transcript: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.9,
    ) -> AIResult:
        """Generate text, walking the provider chain until something answers.

        ``video_url`` is handed to Gemini natively. If Gemini fails and a
        ``transcript`` was supplied, the OpenRouter attempts get the transcript
        folded into the prompt so they still have real video context.
        """
        attempts: list[str] = []

        gemini_text = await self._try_gemini(
            prompt,
            system_prompt,
            video_url=video_url,
            max_tokens=max_tokens,
            temperature=temperature,
            attempts=attempts,
        )
        if gemini_text:
            return AIResult(gemini_text, "gemini", self.gemini_model, False, attempts)

        # Gemini is out. Rebuild the prompt for text-only models, substituting
        # the transcript for the video we can no longer send.
        fallback_prompt = self._with_transcript(prompt, video_url, transcript)
        used_transcript = fallback_prompt is not prompt

        for model in self.openrouter_models:
            text = await self._try_openrouter(
                model,
                fallback_prompt,
                system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                attempts=attempts,
            )
            if text:
                return AIResult(text, "openrouter", model, used_transcript, attempts)

        logger.error("All AI providers failed. Attempts: %s", "; ".join(attempts))
        return AIResult("", "none", "", used_transcript, attempts)

    # ------------------------------------------------------------------
    # Gemini
    # ------------------------------------------------------------------

    async def _try_gemini(
        self,
        prompt: str,
        system_prompt: Optional[str],
        *,
        video_url: Optional[str],
        max_tokens: int,
        temperature: float,
        attempts: list[str],
    ) -> str:
        if not self._gemini_client or genai_types is None:
            attempts.append("gemini:unavailable")
            return ""
        if self._breaker.is_open("gemini"):
            attempts.append("gemini:circuit-open")
            return ""

        parts: list[Any] = []
        if video_url:
            # Gemini can ingest a YouTube URL directly; this is the only path
            # in the chain that actually watches the video.
            try:
                parts.append(
                    genai_types.Part(
                        file_data=genai_types.FileData(file_uri=video_url)
                    )
                )
            except Exception as exc:
                logger.debug("Could not build Gemini video part: %s", exc)
        parts.append(genai_types.Part.from_text(text=prompt))

        # Suppresses the thinking monologue and enforces an output floor.
        # Without it, thinking is billed against max_output_tokens and replies
        # come back truncated mid-sentence. See models/gemini_utils.py.
        config_kwargs: dict[str, Any] = apply_thinking_defaults(
            genai_types,
            {
                "response_mime_type": "text/plain",
                "max_output_tokens": max_tokens * 2,
                "temperature": temperature,
            },
        )
        if system_prompt:
            config_kwargs["system_instruction"] = [
                genai_types.Part.from_text(text=system_prompt)
            ]

        def _call() -> Any:
            return self._gemini_client.models.generate_content(
                model=self.gemini_model,
                contents=[genai_types.Content(role="user", parts=parts)],
                config=genai_types.GenerateContentConfig(**config_kwargs),
            )

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(_call), timeout=Config.AI_REQUEST_TIMEOUT
            )
        except asyncio.TimeoutError:
            attempts.append("gemini:timeout")
            self._breaker.record_failure("gemini")
            logger.warning("Gemini timed out after %ss", Config.AI_REQUEST_TIMEOUT)
            return ""
        except Exception as exc:
            attempts.append(f"gemini:error({type(exc).__name__})")
            self._breaker.record_failure("gemini")
            logger.warning("Gemini call failed, falling back to OpenRouter: %s", exc)
            return ""

        text = extract_gemini_text(response)
        if text:
            self._breaker.record_success("gemini")
            attempts.append("gemini:ok")
            return text

        attempts.append("gemini:empty")
        self._breaker.record_failure("gemini")
        logger.warning("Gemini returned no text (%s)", describe_gemini_response(response))
        return ""

    # ------------------------------------------------------------------
    # OpenRouter
    # ------------------------------------------------------------------

    async def _try_openrouter(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str],
        *,
        max_tokens: int,
        temperature: float,
        attempts: list[str],
    ) -> str:
        if not self.openrouter_api_key:
            attempts.append(f"{model}:no-key")
            return ""
        if self._breaker.is_open(model):
            attempts.append(f"{model}:circuit-open")
            return ""

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            # Reasoning models (glm-*) spend part of the budget thinking, so the
            # cap has to cover both the monologue and the answer. "low" keeps the
            # monologue short; it cannot be disabled outright on some endpoints.
            "reasoning": {"effort": "low"},
            "max_tokens": max_tokens * 3,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": Config.WEB_BASE_URL,
            "X-Title": "Ino Discord Bot",
        }

        data: Any = None
        for attempt_payload in (payload, None):
            if attempt_payload is None:
                # The model rejected the reasoning knob entirely; retry plain.
                attempt_payload = {k: v for k, v in payload.items() if k != "reasoning"}

            try:
                session = await self._get_session()
                async with session.post(
                    OPENROUTER_ENDPOINT, json=attempt_payload, headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        break

                    body = (await response.text())[:300]
                    if response.status == 400 and "reasoning" in body.lower():
                        logger.debug(
                            "OpenRouter %s rejected the reasoning parameter, retrying "
                            "without it",
                            model,
                        )
                        continue

                    attempts.append(f"{model}:http{response.status}")
                    self._breaker.record_failure(model)
                    logger.warning(
                        "OpenRouter %s returned %s: %s", model, response.status, body
                    )
                    return ""
            except asyncio.TimeoutError:
                attempts.append(f"{model}:timeout")
                self._breaker.record_failure(model)
                logger.warning("OpenRouter %s timed out", model)
                return ""
            except Exception as exc:
                attempts.append(f"{model}:error({type(exc).__name__})")
                self._breaker.record_failure(model)
                logger.warning("OpenRouter %s call failed: %s", model, exc)
                return ""

        if data is None:
            attempts.append(f"{model}:no-response")
            self._breaker.record_failure(model)
            return ""

        text = self._extract_openrouter_text(data)
        if text:
            self._breaker.record_success(model)
            attempts.append(f"{model}:ok")
            return text

        attempts.append(f"{model}:empty")
        self._breaker.record_failure(model)
        logger.warning("OpenRouter %s returned an empty completion", model)
        return ""

    @staticmethod
    def _extract_openrouter_text(data: Any) -> str:
        """Pull the assistant text out of an OpenAI-shaped response."""
        try:
            choices = data.get("choices") or []
            if not choices:
                return ""
            message = choices[0].get("message") or {}
        except AttributeError:
            return ""

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

        # Some providers return content as a list of typed blocks.
        if isinstance(content, list):
            chunks = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") in (None, "text")
            ]
            joined = "".join(chunks).strip()
            if joined:
                return joined

        # Last resort: a reasoning model that spent its whole budget thinking
        # still tells us what it was going to say.
        reasoning = message.get("reasoning")
        if isinstance(reasoning, str) and reasoning.strip():
            logger.debug("Falling back to reasoning text for an empty completion")
            return reasoning.strip()

        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _with_transcript(
        prompt: str, video_url: Optional[str], transcript: Optional[str]
    ) -> str:
        """Fold a transcript into the prompt for models that cannot see video."""
        if not transcript or not transcript.strip():
            return prompt

        clipped = transcript.strip()
        if len(clipped) > Config.TRANSCRIPT_MAX_CHARS:
            clipped = clipped[: Config.TRANSCRIPT_MAX_CHARS].rsplit(" ", 1)[0] + " ..."

        source = f" ({video_url})" if video_url else ""
        return (
            f"{prompt}\n\n"
            f"--- TRANSCRIPT OF THE VIDEO{source} ---\n"
            f"You cannot watch the video, but these are its subtitles. Use them as "
            f"the ground truth for what actually happens in it.\n\n"
            f"{clipped}\n"
            f"--- END TRANSCRIPT ---"
        )
