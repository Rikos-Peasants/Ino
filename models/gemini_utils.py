"""Helpers for working with Google GenAI responses."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Headroom for any call that does still think, so a reply is never cut off.
MIN_OUTPUT_TOKENS = 800


def low_thinking_config(types_module: Any) -> Any:
    """Build a ThinkingConfig that suppresses the reasoning monologue.

    ``gemini-flash-latest`` bills thinking against ``max_output_tokens`` and
    will happily spend several hundred tokens on a one-line answer, so a caller
    with a tight cap gets a truncated reply or an empty one. ``thinking_level``
    reliably suppresses it; ``thinking_budget=0`` is accepted but not always
    honoured, so it is only the fallback for older SDKs.

    Returns None when the SDK has no ThinkingConfig at all, in which case
    callers should just raise their token ceiling.
    """
    thinking_config = getattr(types_module, "ThinkingConfig", None)
    if thinking_config is None:
        return None

    for attempt in ({"thinking_level": "LOW"}, {"thinking_budget": 0}):
        try:
            return thinking_config(**attempt)
        except Exception:
            continue

    logger.debug("No usable ThinkingConfig form found")
    return None


def apply_thinking_defaults(types_module: Any, config_kwargs: dict) -> dict:
    """Add a low thinking budget and a sane output floor to a config dict."""
    thinking = low_thinking_config(types_module)
    if thinking is not None:
        config_kwargs.setdefault("thinking_config", thinking)

    requested = config_kwargs.get("max_output_tokens") or 0
    config_kwargs["max_output_tokens"] = max(requested, MIN_OUTPUT_TOKENS)
    return config_kwargs


def extract_gemini_text(response: Any) -> str:
    """Return generated text from a GenAI response, including candidate parts."""
    if response is None:
        return ""

    try:
        text = getattr(response, "text", None)
    except Exception:
        text = None

    if isinstance(text, str) and text.strip():
        return text.strip()

    chunks: list[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                chunks.append(part_text.strip())

    return "\n".join(chunks).strip()


def extract_gemini_stream_text(stream: Any) -> str:
    """Return generated text from a GenAI streaming response."""
    chunks: list[str] = []

    for chunk in stream:
        try:
            text = getattr(chunk, "text", None)
        except Exception:
            text = None

        if isinstance(text, str) and text:
            chunks.append(text)
            continue

        chunk_text = extract_gemini_text(chunk)
        if chunk_text:
            chunks.append(chunk_text)

    return "".join(chunks).strip()


def describe_gemini_response(response: Any) -> str:
    """Build concise diagnostics for empty GenAI responses."""
    if response is None:
        return "response=None"

    details: list[str] = []
    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback:
        details.append(f"prompt_feedback={prompt_feedback}")

    for index, candidate in enumerate(getattr(response, "candidates", []) or []):
        finish_reason = getattr(candidate, "finish_reason", None)
        finish_message = getattr(candidate, "finish_message", None)
        safety_ratings = getattr(candidate, "safety_ratings", None)
        candidate_details = [f"candidate[{index}]"]
        if finish_reason:
            candidate_details.append(f"finish_reason={finish_reason}")
        if finish_message:
            candidate_details.append(f"finish_message={finish_message}")
        if safety_ratings:
            candidate_details.append(f"safety_ratings={safety_ratings}")
        details.append(" ".join(candidate_details))

    return "; ".join(details) if details else "no candidates or diagnostics"
