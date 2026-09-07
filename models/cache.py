"""A small async TTL cache.

Leaderboards are read far more often than they change, and every read is a
blocking Mongo aggregation. Caching them for a few seconds turns page-flipping
in a leaderboard view from "one aggregation per click" into "one per window".

Single-flight: concurrent callers asking for the same cold key wait on one
computation instead of each starting their own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


class TTLCache:
    """Async cache keyed by string, with per-entry expiry and single-flight."""

    def __init__(self, default_ttl: float = 30.0, max_entries: int = 512):
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self._entries: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, key: str) -> Optional[Any]:
        """Return a live value, or None when missing or expired."""
        entry = self._entries.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        if len(self._entries) >= self.max_entries:
            self._evict()
        self._entries[key] = (
            time.monotonic() + (self.default_ttl if ttl is None else ttl),
            value,
        )

    def invalidate(self, prefix: str = "") -> None:
        """Drop everything, or everything under a key prefix."""
        if not prefix:
            self._entries.clear()
            return
        for key in [k for k in self._entries if k.startswith(prefix)]:
            self._entries.pop(key, None)

    async def get_or_compute(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        ttl: Optional[float] = None,
    ) -> Any:
        """Return the cached value, computing it once if several callers race."""
        cached = self.get(key)
        if cached is not None:
            return cached

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Another waiter may have filled it while we queued for the lock.
            cached = self.get(key)
            if cached is not None:
                return cached

            try:
                value = await factory()
            finally:
                # Only the last waiter out clears the lock, so it is not
                # recreated under every caller.
                if not lock.locked() or lock._waiters is None or not lock._waiters:
                    self._locks.pop(key, None)

            self.set(key, value, ttl)
            return value

    def _evict(self) -> None:
        """Drop expired entries first, then the soonest to expire."""
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._entries.items() if exp < now]
        for key in expired:
            self._entries.pop(key, None)

        if len(self._entries) < self.max_entries:
            return

        overflow = len(self._entries) - self.max_entries + 1
        for key, _ in sorted(self._entries.items(), key=lambda kv: kv[1][0])[:overflow]:
            self._entries.pop(key, None)


# Shared instance for leaderboard reads.
leaderboard_cache = TTLCache(default_ttl=30.0)
