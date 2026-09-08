"""Ways to *earn* InoRep.

Historically rep only moved downwards - spam and ping penalties - so the
leaderboard was a shame list nobody could climb out of. This module adds the
earning side: chatting, daily check-ins with streaks, being reacted to, sitting
in voice, and thanking other people.

Everything funnels through :class:`InoRepManager` so history and mod-mode
immunity keep working. Rate limiting lives in memory (cheap, resets on restart,
good enough for anti-spam) while streaks and daily caps live in Mongo.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import Config
from models.inorep_status import (
    INOREP_TIERS,
    get_inorep_tier,
    get_next_inorep_threshold,
    get_previous_inorep_threshold,
)

logger = logging.getLogger(__name__)

SYSTEM_ACTOR_ID = "0"
SYSTEM_ACTOR_NAME = "Ino's Shrine"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today_key() -> str:
    return _utcnow().strftime("%Y-%m-%d")


@dataclass
class RepAward:
    """Result of an earning attempt."""

    granted: int
    new_total: int
    reason: str
    tier_changed: bool = False
    tier: Optional[dict[str, Any]] = None

    def __bool__(self) -> bool:
        return self.granted != 0


def tier_for(rep: int, user_id: Optional[int] = None) -> dict[str, Any]:
    """Return the InoRep tier a score sits in.

    Delegates to :mod:`models.inorep_status`, which is the single source of
    truth for the tier ladder and is what ``/inorep check``, the profile embeds
    and the website have always used. This module briefly had its own shorter
    ladder, which meant ``/rep`` and the leaderboard disagreed with everything
    else about what rank someone held.
    """
    return get_inorep_tier(rep, user_id)


def next_tier_for(rep: int) -> Optional[dict[str, Any]]:
    """Return the tier above the current one, or None at the top."""
    threshold = get_next_inorep_threshold(rep)
    if threshold is None:
        return None
    for tier in INOREP_TIERS:
        if int(tier["threshold"]) == threshold:
            return tier
    return None


def tier_label(tier: dict[str, Any]) -> str:
    """The display name of a tier, e.g. '⭐ Ino's Friend'."""
    return str(tier.get("status", "Unknown"))


def progress_bar(current: int, target: int, width: int = 12) -> str:
    """Render a text progress bar for embeds."""
    if target <= 0:
        return "█" * width
    ratio = max(0.0, min(1.0, current / target))
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


class RepEconomy:
    """Grants rep for positive behaviour, with per-user cooldowns and caps."""

    def __init__(self, inorep_manager: Any, bot: Any = None):
        self.inorep = inorep_manager
        self.bot = bot
        self.db = getattr(inorep_manager, "db", None)
        self.meta = self.db["inorep_meta"] if self.db is not None else None

        # user_id -> monotonic timestamp of last message award
        self._message_cooldown: dict[str, float] = {}
        # user_id -> accumulated whole minutes of voice time not yet paid out
        self._voice_progress: dict[str, float] = {}

        if self.meta is not None:
            try:
                self.meta.create_index([("user_id", 1), ("guild_id", 1)], unique=True)
            except Exception as exc:
                logger.error("Could not create inorep_meta index: %s", exc)

        logger.info("Rep economy initialized (earning=%s)", Config.REP_EARNING_ENABLED)

    # ------------------------------------------------------------------
    # Mongo helpers (pymongo is blocking, so keep it off the event loop)
    # ------------------------------------------------------------------

    async def _get_meta(self, user_id: str, guild_id: str) -> dict[str, Any]:
        if self.meta is None:
            return {}
        try:
            doc = await asyncio.to_thread(
                self.meta.find_one, {"user_id": user_id, "guild_id": guild_id}
            )
            return doc or {}
        except Exception as exc:
            logger.error("Error reading rep meta for %s: %s", user_id, exc)
            return {}

    async def _update_meta(
        self, user_id: str, guild_id: str, update: dict[str, Any]
    ) -> None:
        if self.meta is None:
            return
        try:
            await asyncio.to_thread(
                self.meta.update_one,
                {"user_id": user_id, "guild_id": guild_id},
                update,
                True,  # upsert
            )
        except Exception as exc:
            logger.error("Error writing rep meta for %s: %s", user_id, exc)

    # ------------------------------------------------------------------
    # Core grant
    # ------------------------------------------------------------------

    async def grant(
        self,
        user: Any,
        guild_id: str,
        amount: int,
        reason: str,
        *,
        apply_multiplier: bool = True,
    ) -> RepAward:
        """Add rep to a user and report whether they ranked up."""
        if amount == 0:
            return RepAward(0, await self.get_rep(str(user.id), guild_id), reason)

        if apply_multiplier and amount > 0 and self._is_patreon(user):
            amount = max(1, int(round(amount * Config.REP_PATREON_MULTIPLIER)))

        user_id = str(user.id)
        before = await self.get_rep(user_id, guild_id)

        ok = await self.inorep.add_rep(
            user_id=user_id,
            guild_id=guild_id,
            user_name=getattr(user, "display_name", str(user)),
            amount=amount,
            reason=reason,
            moderator_id=SYSTEM_ACTOR_ID,
            moderator_name=SYSTEM_ACTOR_NAME,
        )
        if not ok:
            return RepAward(0, before, reason)

        after = before + amount
        member_id = getattr(user, "id", None)
        old_tier = tier_for(before, member_id)
        new_tier = tier_for(after, member_id)
        return RepAward(
            granted=amount,
            new_total=after,
            reason=reason,
            tier_changed=old_tier["threshold"] != new_tier["threshold"],
            tier=new_tier,
        )

    async def get_rep(self, user_id: str, guild_id: str) -> int:
        return await self.inorep.get_user_rep(user_id, guild_id)

    @staticmethod
    def _is_patreon(user: Any) -> bool:
        role_id = getattr(Config, "PATREON_ROLE_ID", None)
        if not role_id:
            return False
        roles = getattr(user, "roles", None) or []
        return any(getattr(role, "id", None) == role_id for role in roles)

    # ------------------------------------------------------------------
    # Earning: chatting
    # ------------------------------------------------------------------

    async def award_message(self, message: Any) -> Optional[RepAward]:
        """Grant rep for a chat message, respecting cooldown and daily cap."""
        if not Config.REP_EARNING_ENABLED or not message.guild:
            return None
        author = message.author
        if getattr(author, "bot", False):
            return None
        if len(message.content.strip()) < Config.REP_MESSAGE_MIN_LENGTH:
            return None
        if message.content.startswith(Config.COMMAND_PREFIX):
            return None

        user_id = str(author.id)
        now = time.monotonic()
        last = self._message_cooldown.get(user_id, 0.0)
        if now - last < Config.REP_MESSAGE_COOLDOWN_SECONDS:
            return None
        self._message_cooldown[user_id] = now

        guild_id = str(message.guild.id)
        if not await self._consume_daily_budget(
            user_id, guild_id, "message", Config.REP_DAILY_MESSAGE_CAP
        ):
            return None

        amount = Config.REP_PER_MESSAGE
        if message.channel.id in Config.BOOSTER_TEXT_CHANNELS:
            amount *= 2

        channel_name = getattr(message.channel, "name", message.channel.id)
        return await self.grant(author, guild_id, amount, f"Chatting in #{channel_name}")

    # ------------------------------------------------------------------
    # Earning: reactions received
    # ------------------------------------------------------------------

    async def award_reaction_received(
        self, author: Any, reactor: Any, guild_id: str
    ) -> Optional[RepAward]:
        """Grant the message author rep when someone else reacts to them."""
        if not Config.REP_EARNING_ENABLED:
            return None
        if getattr(author, "bot", False) or getattr(reactor, "bot", False):
            return None
        # Self-reacting would be free rep.
        if getattr(author, "id", None) == getattr(reactor, "id", None):
            return None

        user_id = str(author.id)
        if not await self._consume_daily_budget(
            user_id, guild_id, "reaction", Config.REP_REACTION_DAILY_CAP
        ):
            return None

        return await self.grant(
            author, guild_id, Config.REP_PER_REACTION_RECEIVED, "Someone reacted to your post"
        )

    # ------------------------------------------------------------------
    # Earning: voice presence
    # ------------------------------------------------------------------

    async def award_voice_minutes(
        self, member: Any, guild_id: str, minutes: float
    ) -> Optional[RepAward]:
        """Accumulate voice minutes and pay out each completed interval."""
        if not Config.REP_EARNING_ENABLED or minutes <= 0:
            return None

        user_id = str(member.id)
        banked = self._voice_progress.get(user_id, 0.0) + minutes
        interval = max(1, Config.REP_VOICE_INTERVAL_MINUTES)
        intervals, self._voice_progress[user_id] = divmod(banked, interval)
        intervals = int(intervals)
        if intervals <= 0:
            return None

        return await self.grant(
            member,
            guild_id,
            Config.REP_PER_VOICE_INTERVAL * intervals,
            f"Voice chat ({intervals * interval} minutes)",
        )

    # ------------------------------------------------------------------
    # Earning: daily check-in with streaks
    # ------------------------------------------------------------------

    async def claim_daily(self, user: Any, guild_id: str) -> dict[str, Any]:
        """Claim the daily rep bonus.

        Returns a dict describing the outcome so the command can render it:
        ``{"claimed": bool, "amount": int, "streak": int, "next_available": dt}``
        """
        user_id = str(user.id)
        meta = await self._get_meta(user_id, guild_id)
        today = _today_key()
        last_claim = meta.get("daily_last_claim")

        if last_claim == today:
            tomorrow = (_utcnow() + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            return {
                "claimed": False,
                "amount": 0,
                "streak": meta.get("daily_streak", 0),
                "next_available": tomorrow,
                "total": await self.get_rep(user_id, guild_id),
            }

        yesterday = (_utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        streak = meta.get("daily_streak", 0) + 1 if last_claim == yesterday else 1

        bonus = min(
            Config.REP_DAILY_STREAK_BONUS * (streak - 1),
            Config.REP_DAILY_STREAK_BONUS_CAP,
        )
        amount = Config.REP_DAILY_BASE + bonus

        award = await self.grant(
            user, guild_id, amount, f"Daily check-in (day {streak} streak)"
        )

        await self._update_meta(
            user_id,
            guild_id,
            {
                "$set": {
                    "user_id": user_id,
                    "guild_id": guild_id,
                    "daily_last_claim": today,
                    "daily_streak": streak,
                },
                "$max": {"daily_best_streak": streak},
            },
        )

        return {
            "claimed": True,
            "amount": award.granted,
            "streak": streak,
            "bonus": bonus,
            "award": award,
            "total": award.new_total,
        }

    # ------------------------------------------------------------------
    # Earning: thanking someone else
    # ------------------------------------------------------------------

    async def thank(
        self, giver: Any, target: Any, guild_id: str, note: Optional[str] = None
    ) -> dict[str, Any]:
        """Give another member rep. Costs the giver nothing but a daily charge."""
        if getattr(target, "bot", False):
            return {"ok": False, "error": "Bots do not need your gratitude."}
        if giver.id == target.id:
            return {"ok": False, "error": "Thanking yourself? Ino is unimpressed."}

        giver_id = str(giver.id)
        remaining = await self._remaining_daily_budget(
            giver_id, guild_id, "thank", Config.REP_THANK_DAILY_LIMIT
        )
        if remaining <= 0:
            return {
                "ok": False,
                "error": (
                    f"You have used all {Config.REP_THANK_DAILY_LIMIT} of today's "
                    f"thanks. They reset at midnight UTC."
                ),
            }

        await self._consume_daily_budget(
            giver_id, guild_id, "thank", Config.REP_THANK_DAILY_LIMIT
        )

        reason = f"Thanked by {getattr(giver, 'display_name', giver)}"
        if note:
            reason += f": {note[:120]}"

        award = await self.grant(
            target,
            guild_id,
            Config.REP_THANK_AMOUNT,
            reason,
            apply_multiplier=False,
        )
        return {"ok": True, "award": award, "remaining": remaining - 1}

    # ------------------------------------------------------------------
    # Earning: one-off hooks used by other systems
    # ------------------------------------------------------------------

    async def award_image_post(self, user: Any, guild_id: str) -> Optional[RepAward]:
        return await self.grant(
            user, guild_id, Config.REP_IMAGE_POST_BONUS, "Shared an image"
        )

    async def award_quest_complete(
        self, user: Any, guild_id: str, quest_name: str = ""
    ) -> Optional[RepAward]:
        label = f"Completed quest: {quest_name}" if quest_name else "Completed a quest"
        return await self.grant(user, guild_id, Config.REP_QUEST_COMPLETE_BONUS, label)

    async def award_art_challenge(self, user: Any, guild_id: str) -> Optional[RepAward]:
        return await self.grant(
            user, guild_id, Config.REP_ART_CHALLENGE_BONUS, "Completed an art challenge"
        )

    # ------------------------------------------------------------------
    # Daily budgets
    # ------------------------------------------------------------------

    async def _remaining_daily_budget(
        self, user_id: str, guild_id: str, bucket: str, cap: int
    ) -> int:
        if cap <= 0:
            return 0
        meta = await self._get_meta(user_id, guild_id)
        budgets = meta.get("daily_budgets") or {}
        entry = budgets.get(bucket) or {}
        if entry.get("date") != _today_key():
            return cap
        return max(0, cap - int(entry.get("used", 0)))

    async def _consume_daily_budget(
        self, user_id: str, guild_id: str, bucket: str, cap: int
    ) -> bool:
        """Take one unit from a per-day budget. False when it is exhausted."""
        if cap <= 0:
            return False

        today = _today_key()
        meta = await self._get_meta(user_id, guild_id)
        entry = (meta.get("daily_budgets") or {}).get(bucket) or {}

        if entry.get("date") != today:
            used = 0
        else:
            used = int(entry.get("used", 0))

        if used >= cap:
            return False

        await self._update_meta(
            user_id,
            guild_id,
            {
                "$set": {
                    "user_id": user_id,
                    "guild_id": guild_id,
                    f"daily_budgets.{bucket}": {"date": today, "used": used + 1},
                }
            },
        )
        return True

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    async def get_profile(self, user: Any, guild_id: str) -> dict[str, Any]:
        """Everything /rep needs in one shot."""
        user_id = str(user.id)
        rep, meta, rank = await asyncio.gather(
            self.get_rep(user_id, guild_id),
            self._get_meta(user_id, guild_id),
            self.get_rank(user_id, guild_id),
        )

        current = tier_for(rep, getattr(user, "id", None))
        upcoming = next_tier_for(rep)
        if upcoming:
            floor = get_previous_inorep_threshold(rep)
            if floor is None:
                floor = int(current["threshold"])
            ceiling = int(upcoming["threshold"])
            span = max(1, ceiling - floor)
            bar = progress_bar(rep - floor, span)
            to_next = ceiling - rep
        else:
            bar = progress_bar(1, 1)
            to_next = 0

        return {
            "rep": rep,
            "rank": rank,
            "tier": current,
            "next_tier": upcoming,
            "to_next": to_next,
            "bar": bar,
            "streak": meta.get("daily_streak", 0),
            "best_streak": meta.get("daily_best_streak", 0),
            "daily_ready": meta.get("daily_last_claim") != _today_key(),
            "thanks_left": await self._remaining_daily_budget(
                user_id, guild_id, "thank", Config.REP_THANK_DAILY_LIMIT
            ),
        }

    async def get_rank(self, user_id: str, guild_id: str) -> Optional[int]:
        """1-based position on the rep leaderboard."""
        collection = getattr(self.inorep, "inorep_collection", None)
        if collection is None:
            return None
        try:
            rep = await self.get_rep(user_id, guild_id)
            ahead = await asyncio.to_thread(
                collection.count_documents,
                {"guild_id": guild_id, "rep": {"$gt": rep}},
            )
            return ahead + 1
        except Exception as exc:
            logger.error("Error computing rep rank for %s: %s", user_id, exc)
            return None
