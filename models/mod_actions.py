"""One place where moderation actions actually happen.

Both the slash commands and the buttons on scam/burst alerts call into this, so
a ban issued from an alert behaves identically to a ban issued from ``/ban``:
same hierarchy checks, same DM, same audit record, same log embed.

Every action returns a :class:`ActionResult` rather than raising, because the
callers are Discord interactions where a traceback is useless to the person who
pressed the button.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import discord

from config import Config

logger = logging.getLogger(__name__)

# Discord's hard ceiling on communication_disabled_until.
MAX_TIMEOUT = timedelta(days=28)

_DURATION_PATTERN = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> Optional[timedelta]:
    """Parse ``30m``, ``2h30m``, ``7d``, ``1w`` into a timedelta.

    Returns None when nothing parses, so callers can tell the difference
    between "no duration given" and "zero".
    """
    if not text:
        return None

    matches = _DURATION_PATTERN.findall(text.strip())
    if not matches:
        return None

    total = 0
    for amount, unit in matches:
        total += int(amount) * _UNIT_SECONDS[unit.lower()]

    return timedelta(seconds=total) if total > 0 else None


def format_duration(delta: timedelta) -> str:
    """Human-readable duration, largest unit first."""
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "0 seconds"

    units = (("week", 604800), ("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1))
    parts = []
    for name, size in units:
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count} {name}{'s' if count != 1 else ''}")
    return " ".join(parts[:2])


@dataclass
class ActionResult:
    """Outcome of a moderation action."""

    ok: bool
    action: str
    target_id: int
    message: str = ""
    dm_delivered: bool = False
    messages_deleted: int = 0
    expires_at: Optional[datetime] = None
    details: dict[str, Any] = field(default_factory=dict)


class ModerationActions:
    """Executes and records moderation actions."""

    def __init__(self, bot):
        self.bot = bot
        db = getattr(getattr(bot, "leaderboard_manager", None), "db", None)
        self.history = db["moderation_actions"] if db is not None else None

        if self.history is not None:
            try:
                self.history.create_index([("guild_id", 1), ("target_id", 1), ("created_at", -1)])
                self.history.create_index([("moderator_id", 1), ("created_at", -1)])
            except Exception as exc:
                logger.error("Could not create moderation_actions indexes: %s", exc)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def check_hierarchy(
        self, moderator: discord.Member, target: discord.abc.User, guild: discord.Guild
    ) -> Optional[str]:
        """Return a refusal reason, or None when the action is permitted.

        Checked before touching Discord so the failure is a clear sentence
        rather than a 403 surfaced as "something broke".
        """
        if target.id == moderator.id:
            return "You cannot action yourself."
        if self.bot.user and target.id == self.bot.user.id:
            return "Ino declines to action herself."
        if target.id == guild.owner_id:
            return "That is the server owner."

        member = guild.get_member(target.id)
        if member is None:
            # Not in the guild: only ban/unban apply, and neither needs a
            # hierarchy comparison.
            return None

        if member.top_role >= moderator.top_role and guild.owner_id != moderator.id:
            return (
                f"{member.display_name} has a role at or above yours, "
                f"so you cannot action them."
            )

        me = guild.me
        if me and member.top_role >= me.top_role:
            return (
                f"{member.display_name} has a role above Ino's, so she cannot "
                f"action them. Move her role higher in the list."
            )
        return None

    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------

    async def notify_target(
        self,
        target: discord.abc.User,
        guild: discord.Guild,
        action: str,
        reason: str,
        duration: Optional[timedelta] = None,
        expires_at: Optional[datetime] = None,
    ) -> bool:
        """DM the member before the action lands. Never fatal."""
        colors = {
            "ban": 0xE05252,
            "kick": 0xE8A33D,
            "timeout": 0xE8A33D,
            "unban": 0x77DD77,
            "untimeout": 0x77DD77,
        }
        titles = {
            "ban": f"You have been banned from {guild.name}",
            "kick": f"You have been removed from {guild.name}",
            "timeout": f"You have been timed out in {guild.name}",
            "unban": f"Your ban in {guild.name} has been lifted",
            "untimeout": f"Your timeout in {guild.name} has been lifted",
        }

        embed = discord.Embed(
            title=titles.get(action, f"Moderation action in {guild.name}"),
            color=colors.get(action, 0xE8A33D),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Reason", value=reason[:1000] or "No reason given", inline=False)

        if duration:
            embed.add_field(name="Duration", value=format_duration(duration), inline=True)
        if expires_at:
            embed.add_field(
                name="Expires", value=f"<t:{int(expires_at.timestamp())}:R>", inline=True
            )

        if action in ("ban", "kick", "timeout"):
            embed.add_field(
                name="Think this is wrong?",
                value=(
                    "Replies here are not read. Appeals go through the "
                    "**ask-and-complain-to-staff** channel, or a server admin."
                    if action != "ban"
                    else "Appeals go to a server admin directly."
                ),
                inline=False,
            )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        try:
            await target.send(embed=embed)
            return True
        except (discord.Forbidden, discord.HTTPException):
            # DMs closed, or the bot shares no mutual channel any more.
            return False

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def timeout(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.Member,
        duration: timedelta,
        reason: str,
        notify: bool = True,
    ) -> ActionResult:
        if duration > MAX_TIMEOUT:
            return ActionResult(
                False, "timeout", target.id,
                f"Discord caps timeouts at 28 days. Use `/ban` for anything longer.",
            )

        refusal = self.check_hierarchy(moderator, target, guild)
        if refusal:
            return ActionResult(False, "timeout", target.id, refusal)

        expires_at = datetime.now(timezone.utc) + duration
        # DM first: after a timeout lands they can still receive it, but doing
        # it first keeps ordering consistent with kick and ban.
        dm = await self.notify_target(
            target, guild, "timeout", reason, duration, expires_at
        ) if notify else False

        try:
            await target.timeout(
                expires_at, reason=self._audit_reason(moderator, reason)
            )
        except discord.Forbidden:
            return ActionResult(False, "timeout", target.id, "Ino lacks permission to time that member out.")
        except discord.HTTPException as exc:
            return ActionResult(False, "timeout", target.id, f"Discord refused: {exc}")

        await self._record(guild, moderator, target, "timeout", reason, duration=duration, expires_at=expires_at)
        return ActionResult(
            True, "timeout", target.id,
            f"Timed out for {format_duration(duration)}.",
            dm_delivered=dm, expires_at=expires_at,
        )

    async def untimeout(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.Member,
        reason: str,
        notify: bool = True,
    ) -> ActionResult:
        if not target.is_timed_out():
            return ActionResult(False, "untimeout", target.id, f"{target.display_name} is not timed out.")

        try:
            await target.timeout(None, reason=self._audit_reason(moderator, reason))
        except discord.Forbidden:
            return ActionResult(False, "untimeout", target.id, "Ino lacks permission to do that.")
        except discord.HTTPException as exc:
            return ActionResult(False, "untimeout", target.id, f"Discord refused: {exc}")

        dm = await self.notify_target(target, guild, "untimeout", reason) if notify else False
        await self._record(guild, moderator, target, "untimeout", reason)
        return ActionResult(True, "untimeout", target.id, "Timeout lifted.", dm_delivered=dm)

    async def kick(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.Member,
        reason: str,
        notify: bool = True,
    ) -> ActionResult:
        refusal = self.check_hierarchy(moderator, target, guild)
        if refusal:
            return ActionResult(False, "kick", target.id, refusal)

        # Must DM before removing them, or the bot loses the mutual guild.
        dm = await self.notify_target(target, guild, "kick", reason) if notify else False

        try:
            await guild.kick(target, reason=self._audit_reason(moderator, reason))
        except discord.Forbidden:
            return ActionResult(False, "kick", target.id, "Ino lacks permission to kick that member.")
        except discord.HTTPException as exc:
            return ActionResult(False, "kick", target.id, f"Discord refused: {exc}")

        await self._record(guild, moderator, target, "kick", reason)
        return ActionResult(True, "kick", target.id, "Removed from the server.", dm_delivered=dm)

    async def ban(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.abc.User,
        reason: str,
        delete_message_days: int = 0,
        notify: bool = True,
    ) -> ActionResult:
        refusal = self.check_hierarchy(moderator, target, guild)
        if refusal:
            return ActionResult(False, "ban", target.id, refusal)

        delete_message_days = max(0, min(7, delete_message_days))
        dm = await self.notify_target(target, guild, "ban", reason) if notify else False

        try:
            await guild.ban(
                target,
                reason=self._audit_reason(moderator, reason),
                delete_message_seconds=delete_message_days * 86400,
            )
        except discord.Forbidden:
            return ActionResult(False, "ban", target.id, "Ino lacks permission to ban that user.")
        except discord.HTTPException as exc:
            return ActionResult(False, "ban", target.id, f"Discord refused: {exc}")

        await self._record(
            guild, moderator, target, "ban", reason,
            extra={"delete_message_days": delete_message_days},
        )
        return ActionResult(
            True, "ban", target.id, "Banned.",
            dm_delivered=dm,
            details={"delete_message_days": delete_message_days},
        )

    async def unban(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        user_id: int,
        reason: str,
    ) -> ActionResult:
        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            return ActionResult(False, "unban", user_id, "No Discord account with that ID.")
        except discord.HTTPException as exc:
            return ActionResult(False, "unban", user_id, f"Could not look that user up: {exc}")

        try:
            await guild.unban(user, reason=self._audit_reason(moderator, reason))
        except discord.NotFound:
            return ActionResult(False, "unban", user_id, f"**{user}** is not banned.")
        except discord.Forbidden:
            return ActionResult(False, "unban", user_id, "Ino lacks permission to unban.")
        except discord.HTTPException as exc:
            return ActionResult(False, "unban", user_id, f"Discord refused: {exc}")

        dm = await self.notify_target(user, guild, "unban", reason)
        await self._record(guild, moderator, user, "unban", reason)
        return ActionResult(True, "unban", user_id, f"Unbanned **{user}**.", dm_delivered=dm)

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    @staticmethod
    def _audit_reason(moderator: discord.Member, reason: str) -> str:
        """What shows up in Discord's own audit log. Capped at 512."""
        return f"{moderator} ({moderator.id}): {reason}"[:512]

    async def _record(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.abc.User,
        action: str,
        reason: str,
        duration: Optional[timedelta] = None,
        expires_at: Optional[datetime] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        if self.history is None:
            return

        entry = {
            "guild_id": str(guild.id),
            "action": action,
            "target_id": str(target.id),
            "target_name": str(target),
            "moderator_id": str(moderator.id),
            "moderator_name": str(moderator),
            "reason": reason,
            "created_at": datetime.now(timezone.utc),
        }
        if duration:
            entry["duration_seconds"] = int(duration.total_seconds())
        if expires_at:
            entry["expires_at"] = expires_at
        if extra:
            entry.update(extra)

        try:
            await asyncio.to_thread(self.history.insert_one, entry)
        except Exception as exc:
            # The action already happened; losing the record must not undo it.
            logger.error("Could not record moderation action: %s", exc)

    async def get_history(
        self, guild_id: str, target_id: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Recent actions against a user, newest first."""
        if self.history is None:
            return []

        def _query():
            return list(
                self.history.find({"guild_id": guild_id, "target_id": target_id})
                .sort("created_at", -1)
                .limit(limit)
            )

        try:
            return await asyncio.to_thread(_query)
        except Exception as exc:
            logger.error("Could not read moderation history: %s", exc)
            return []

    async def count_history(self, guild_id: str, target_id: str) -> int:
        if self.history is None:
            return 0
        try:
            return await asyncio.to_thread(
                self.history.count_documents,
                {"guild_id": guild_id, "target_id": target_id},
            )
        except Exception as exc:
            logger.error("Could not count moderation history: %s", exc)
            return 0

    # ------------------------------------------------------------------

    async def get_log_channel(self, guild: discord.Guild):
        """The configured moderation log channel, if there is one."""
        events = getattr(self.bot, "events_controller", None)
        manager = getattr(events, "moderation_manager", None) if events else None
        if manager:
            try:
                channel_id = await manager.get_moderation_log_channel_id(str(guild.id))
                if channel_id:
                    return guild.get_channel(channel_id)
            except Exception as exc:
                logger.warning("Could not read moderation log channel: %s", exc)
        return None

    async def post_log(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.abc.User,
        result: ActionResult,
        reason: str,
        source: str = "command",
    ) -> None:
        """Post the action to the moderation log channel."""
        channel = await self.get_log_channel(guild)
        if channel is None:
            return

        colors = {
            "ban": 0xE05252, "kick": 0xE8A33D, "timeout": 0xE8A33D,
            "unban": 0x77DD77, "untimeout": 0x77DD77,
        }
        embed = discord.Embed(
            title=f"{result.action.title()} · {target}",
            color=colors.get(result.action, 0x9B8F95),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User", value=f"{getattr(target, 'mention', target)}\n`{target.id}`", inline=True)
        embed.add_field(name="Moderator", value=f"{moderator.mention}\n`{moderator.id}`", inline=True)
        embed.add_field(name="Source", value=source, inline=True)
        embed.add_field(name="Reason", value=reason[:1000] or "No reason given", inline=False)

        if result.expires_at:
            embed.add_field(name="Expires", value=f"<t:{int(result.expires_at.timestamp())}:R>", inline=True)
        embed.add_field(
            name="DM", value="delivered" if result.dm_delivered else "not delivered", inline=True
        )
        if result.messages_deleted:
            embed.add_field(name="Messages removed", value=str(result.messages_deleted), inline=True)

        avatar = getattr(target, "display_avatar", None)
        if avatar:
            embed.set_thumbnail(url=avatar.url)

        try:
            await channel.send(embed=embed)
        except discord.HTTPException as exc:
            logger.warning("Could not post moderation log: %s", exc)
