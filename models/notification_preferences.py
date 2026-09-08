"""Per-user control over the DMs Ino sends.

Ino DMs a lot: quest completions, achievements, bookmark confirmations, rep
rank-ups, reminders, rule nudges. Individually each one is useful; together
they are the most common complaint about the bot, and the only remedy a member
had was closing DMs from the whole server -- which also silences the moderation
notices they actually need to see.

So preferences are stored per *category* rather than per send site, and they are
global to the user rather than per guild: someone annoyed by quest DMs is
annoyed by the DM, not by the server it came from, and several send sites
(reminders, bookmarks) have no reliable guild context by the time they fire.

Two categories are deliberately not optional. Moderation notices tell a member
they were warned, timed out or banned, and safety notices are the anti-scam
"your account may be compromised" DM and the mental-health resources. Letting
someone mute those produces members who genuinely do not know they were
punished, so :data:`CATEGORIES` marks them ``locked`` and
:meth:`NotificationPreferences.is_enabled` always returns True for them.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Category:
    """One switch in ``/notifications``."""

    key: str
    label: str
    emoji: str
    description: str
    # False for the moderation and safety notices, which always send.
    optional: bool = True
    # What a user who has never touched /notifications gets.
    default: bool = True


CATEGORIES: tuple[Category, ...] = (
    Category(
        key="quests",
        label="Quest progress",
        emoji="🎯",
        description="Daily and weekly quests you finish, plus posting streaks.",
    ),
    Category(
        key="achievements",
        label="Achievements",
        emoji="🏆",
        description="Achievements you unlock, including art competition wins.",
    ),
    Category(
        key="rep",
        label="InoRep rank-ups",
        emoji="📈",
        description="When you climb to a new InoRep tier.",
    ),
    Category(
        key="bookmarks",
        label="Bookmark confirmations",
        emoji="🔖",
        description="Receipts when you bookmark or unbookmark an image.",
    ),
    Category(
        key="reminders",
        label="Reminders",
        emoji="⏰",
        description="Your own /remindme reminders, when the original channel is gone.",
    ),
    Category(
        key="rule_nudges",
        label="Rule nudges",
        emoji="📋",
        description="Why a message of yours was removed, e.g. invite links or unspoilered media.",
    ),
    Category(
        key="translation",
        label="Translation prompts",
        emoji="🌐",
        description="Asking whether you want your messages auto-translated.",
    ),
    Category(
        key="moderation",
        label="Moderation notices",
        emoji="🛡️",
        description="Warnings, timeouts, bans and NSFW access changes.",
        optional=False,
    ),
    Category(
        key="safety",
        label="Safety alerts",
        emoji="🚨",
        description="Account-compromise warnings and mental health resources.",
        optional=False,
    ),
)

CATEGORIES_BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}
OPTIONAL_CATEGORIES: tuple[Category, ...] = tuple(c for c in CATEGORIES if c.optional)


class NotificationPreferences:
    """Storage for which DM categories a user still wants.

    Falls back to "everything on" whenever Mongo is missing or erroring. A
    preferences lookup failing should never be the reason a member misses a
    notification, and the alternative -- silently swallowing DMs -- looks
    identical to the bot being broken.
    """

    COLLECTION = "notification_preferences"

    def __init__(self, db=None):
        self.db = db
        self.collection = None
        # user_id -> {category_key: bool}. Read on every DM, so the round trip
        # is worth avoiding; writes go through this instance and invalidate it.
        self._cache: dict[int, dict[str, bool]] = {}

        if db is not None:
            try:
                self.collection = db[self.COLLECTION]
                self.collection.create_index("user_id", unique=True)
            except Exception as e:
                logger.warning(f"Could not initialize notification preference collection: {e}")
                self.collection = None

    @property
    def is_configured(self) -> bool:
        return self.collection is not None

    async def get_all(self, user_id: int) -> dict[str, bool]:
        """Every category's effective state for a user, defaults filled in."""
        stored = await self._load(user_id)
        return {
            c.key: True if not c.optional else stored.get(c.key, c.default)
            for c in CATEGORIES
        }

    async def is_enabled(self, user_id: int, category: str) -> bool:
        """Whether ``category`` may be DMed to ``user_id``."""
        meta = CATEGORIES_BY_KEY.get(category)
        if meta is None:
            # An unknown key means a send site and this list drifted apart.
            # Deliver it and complain, rather than dropping mail silently.
            logger.warning("Unknown notification category %r, allowing send", category)
            return True
        if not meta.optional:
            return True

        stored = await self._load(user_id)
        return stored.get(category, meta.default)

    async def set(self, user_id: int, category: str, enabled: bool) -> bool:
        """Turn one category on or off. Returns False if it could not be saved."""
        return await self.set_many(user_id, {category: enabled})

    async def set_many(self, user_id: int, values: dict[str, bool]) -> bool:
        """Apply several toggles in one write.

        Keys naming a locked or unknown category are ignored rather than
        rejected, so a stale view cannot fail the whole submission.
        """
        updates = {
            key: bool(value)
            for key, value in values.items()
            if (meta := CATEGORIES_BY_KEY.get(key)) is not None and meta.optional
        }
        if not updates:
            return True
        if self.collection is None:
            return False

        try:
            await asyncio.to_thread(
                self.collection.update_one,
                {"user_id": int(user_id)},
                {
                    "$set": {
                        **{f"categories.{k}": v for k, v in updates.items()},
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$setOnInsert": {"user_id": int(user_id)},
                },
                upsert=True,
            )
        except Exception as e:
            logger.error(f"Could not save notification preferences for {user_id}: {e}")
            return False

        self._cache.setdefault(int(user_id), {}).update(updates)
        return True

    async def reset(self, user_id: int) -> bool:
        """Drop the user's overrides, putting every category back to default."""
        if self.collection is None:
            return False
        try:
            await asyncio.to_thread(self.collection.delete_one, {"user_id": int(user_id)})
        except Exception as e:
            logger.error(f"Could not reset notification preferences for {user_id}: {e}")
            return False
        self._cache.pop(int(user_id), None)
        return True

    async def _load(self, user_id: int) -> dict[str, bool]:
        user_id = int(user_id)
        cached = self._cache.get(user_id)
        if cached is not None:
            return cached

        if self.collection is None:
            self._cache[user_id] = {}
            return {}

        try:
            doc = await asyncio.to_thread(
                self.collection.find_one, {"user_id": user_id}, {"categories": 1}
            )
        except Exception as e:
            # Not cached: a transient Mongo blip should not pin this user to
            # "all defaults" for the rest of the process lifetime.
            logger.error(f"Could not read notification preferences for {user_id}: {e}")
            return {}

        stored = (doc or {}).get("categories") or {}
        resolved = {
            key: bool(value)
            for key, value in stored.items()
            if key in CATEGORIES_BY_KEY
        }
        self._cache[user_id] = resolved
        return resolved


async def should_dm(bot, user_id: int, category: str) -> bool:
    """Convenience check for send sites that only hold a ``bot`` reference.

    Missing manager means the feature never initialised, which should not
    suppress notifications, so this defaults to True.
    """
    prefs: Optional[NotificationPreferences] = getattr(bot, "notification_preferences", None)
    if prefs is None:
        return True
    try:
        return await prefs.is_enabled(user_id, category)
    except Exception as e:
        logger.error(f"Notification preference check failed for {user_id}/{category}: {e}")
        return True
