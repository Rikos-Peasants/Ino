"""Fetch YouTube subtitles so text-only models get real video context.

Used when Gemini (which can watch a video directly) is unavailable and we fall
back to OpenRouter. Auto-generated captions count -- an ASR transcript is still
far better context than the title alone.

Deliberately dependency-free: it talks to the same InnerTube ``player`` endpoint
the mobile apps use, then downloads the ``timedtext`` track. The ``WEB`` client
returns ``UNPLAYABLE`` without a PO token, so we ask as ANDROID/IOS.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from typing import Any, Optional
from xml.etree import ElementTree

import aiohttp

logger = logging.getLogger(__name__)

PLAYER_ENDPOINT = "https://www.youtube.com/youtubei/v1/player"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Clients that still hand out caption tracks without a PO token, best first.
INNERTUBE_CLIENTS: tuple[dict[str, Any], ...] = (
    {
        "clientName": "ANDROID",
        "clientVersion": "20.10.38",
        "androidSdkVersion": 34,
        "hl": "en",
    },
    {
        "clientName": "IOS",
        "clientVersion": "20.10.4",
        "deviceModel": "iPhone16,2",
        "hl": "en",
    },
)

_VIDEO_ID_PATTERNS = (
    re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtu\.be/)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/(?:shorts|embed|live|v)/)([A-Za-z0-9_-]{11})"),
)


def extract_video_id(url_or_id: str) -> Optional[str]:
    """Pull the 11-character video id out of any common YouTube URL shape."""
    if not url_or_id:
        return None

    candidate = url_or_id.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate

    for pattern in _VIDEO_ID_PATTERNS:
        match = pattern.search(candidate)
        if match:
            return match.group(1)
    return None


class YouTubeTranscriptFetcher:
    """Downloads subtitle text for a video, with a small in-memory cache."""

    def __init__(
        self,
        preferred_languages: tuple[str, ...] = ("en", "en-US", "en-GB"),
        cache_ttl: float = 3600.0,
        timeout: float = 20.0,
    ):
        self.preferred_languages = preferred_languages
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        # video_id -> (expires_at, transcript or None for a known-miss)
        self._cache: dict[str, tuple[float, Optional[str]]] = {}

    async def get_transcript(
        self, url_or_id: str, session: Optional[aiohttp.ClientSession] = None
    ) -> Optional[str]:
        """Return plain transcript text, or None when the video has no captions."""
        video_id = extract_video_id(url_or_id)
        if not video_id:
            logger.debug("Could not extract a video id from %r", url_or_id)
            return None

        cached = self._cache.get(video_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        owns_session = session is None
        if owns_session:
            session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )

        try:
            transcript = await self._fetch(video_id, session)
        except Exception as exc:
            logger.warning("Transcript fetch failed for %s: %s", video_id, exc)
            transcript = None
        finally:
            if owns_session:
                await session.close()

        # Cache misses too, so a caption-less video is not re-probed every check.
        self._cache[video_id] = (time.monotonic() + self.cache_ttl, transcript)
        if transcript:
            logger.info(
                "Fetched transcript for %s (%s characters)", video_id, len(transcript)
            )
        else:
            logger.info("No transcript available for %s", video_id)
        return transcript

    # ------------------------------------------------------------------

    async def _fetch(
        self, video_id: str, session: aiohttp.ClientSession
    ) -> Optional[str]:
        tracks: list[dict[str, Any]] = []
        for client in INNERTUBE_CLIENTS:
            tracks = await self._get_caption_tracks(video_id, client, session)
            if tracks:
                break

        if not tracks:
            return None

        track = self._pick_track(tracks)
        if not track or not track.get("baseUrl"):
            return None

        logger.debug(
            "Using %s caption track for %s (auto-generated=%s)",
            track.get("languageCode"),
            video_id,
            track.get("kind") == "asr",
        )
        return await self._download_track(track, session)

    async def _get_caption_tracks(
        self,
        video_id: str,
        client: dict[str, Any],
        session: aiohttp.ClientSession,
    ) -> list[dict[str, Any]]:
        payload = {"context": {"client": client}, "videoId": video_id}
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}

        try:
            async with session.post(
                PLAYER_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    logger.debug(
                        "InnerTube %s returned %s for %s",
                        client["clientName"],
                        response.status,
                        video_id,
                    )
                    return []
                # YouTube sometimes labels this text/plain.
                data = await response.json(content_type=None)
        except Exception as exc:
            logger.debug(
                "InnerTube %s request failed for %s: %s",
                client["clientName"],
                video_id,
                exc,
            )
            return []

        renderer = (data.get("captions") or {}).get(
            "playerCaptionsTracklistRenderer"
        ) or {}
        return renderer.get("captionTracks") or []

    def _pick_track(self, tracks: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """Prefer a human English track, then English ASR, then anything."""

        def is_asr(track: dict[str, Any]) -> bool:
            return track.get("kind") == "asr"

        def lang(track: dict[str, Any]) -> str:
            return (track.get("languageCode") or "").lower()

        preferred = [code.lower() for code in self.preferred_languages]

        for code in preferred:
            for track in tracks:
                if lang(track) == code and not is_asr(track):
                    return track
        for code in preferred:
            for track in tracks:
                if lang(track) == code and is_asr(track):
                    return track
        # Some channels only caption in their base language; still useful.
        for track in tracks:
            if not is_asr(track):
                return track
        return tracks[0] if tracks else None

    async def _download_track(
        self, track: dict[str, Any], session: aiohttp.ClientSession
    ) -> Optional[str]:
        url = track["baseUrl"]
        try:
            async with session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    logger.debug("timedtext returned %s", response.status)
                    return None
                raw = await response.text()
        except Exception as exc:
            logger.debug("timedtext download failed: %s", exc)
            return None

        return parse_timedtext(raw)


def parse_timedtext(raw: str) -> Optional[str]:
    """Turn a timedtext payload into plain prose.

    Handles both the JSON3 shape and the srv3/legacy XML shape, since YouTube
    ignores the ``fmt`` parameter on some caption URLs and returns XML anyway.
    """
    if not raw or not raw.strip():
        return None

    stripped = raw.lstrip()
    if stripped.startswith("{"):
        parsed = _parse_json3(stripped)
        if parsed:
            return parsed

    return _parse_xml(raw)


def _parse_json3(raw: str) -> Optional[str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    lines: list[str] = []
    for event in data.get("events") or []:
        segments = event.get("segs") or []
        text = "".join(seg.get("utf8", "") for seg in segments)
        text = text.replace("\n", " ").strip()
        if text:
            lines.append(text)

    return _cleanup(" ".join(lines))


def _parse_xml(raw: str) -> Optional[str]:
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return None

    lines: list[str] = []
    # srv3 uses <p>, the legacy format uses <text>; both may nest <s> runs.
    for node in root.iter():
        if node.tag not in ("p", "text"):
            continue
        pieces: list[str] = []
        if node.text:
            pieces.append(node.text)
        for child in node:
            if child.text:
                pieces.append(child.text)
            if child.tail:
                pieces.append(child.tail)
        text = html.unescape("".join(pieces)).replace("\n", " ").strip()
        if text:
            lines.append(text)

    return _cleanup(" ".join(lines))


def _cleanup(text: str) -> Optional[str]:
    """Collapse whitespace and drop caption noise like [Music] and [♪♪♪]."""
    if not text:
        return None

    text = re.sub(r"\[[^\]]{0,40}\]", " ", text)  # [Music], [Applause], [♪♪♪]
    text = re.sub(r"\s+", " ", text).strip()
    return text or None
