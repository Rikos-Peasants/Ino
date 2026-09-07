"""Moderation slash commands: /ban, /kick, /timeout, /untimeout, /unban, /modlogs.

The server had no ban, kick or timeout command at all — moderators were using
Discord's own UI, which leaves no record in Ino's log and sends no explanation
to the member. These do both, plus a confirmation step with the target's prior
record in front of anything irreversible.

Execution lives in :class:`~models.mod_actions.ModerationActions` so the
buttons on scam alerts take exactly the same path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import commands

from config import Config
from controllers.security import admin_command, moderator_command
from models.mod_actions import MAX_TIMEOUT, ModerationActions, format_duration, parse_duration
from views.mod_action_view import ConfirmActionView

logger = logging.getLogger(__name__)

DANGER = 0xE05252
WARN = 0xE8A33D
GOOD = 0x77DD77
ACCENT = 0xF2A65A

DURATION_HELP = "e.g. `30m`, `2h`, `7d`, `1w`, or `1d12h`"


class ModerationCommandsController:
    """Registers the moderation commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _actions(self) -> Optional[ModerationActions]:
        return getattr(self.bot, "mod_actions", None)

    async def _fail(self, ctx, message: str) -> None:
        await ctx.send(
            embed=discord.Embed(description=f"❌ {message}", color=DANGER), ephemeral=True
        )

    async def _confirm(
        self, ctx, target: discord.abc.User, action: str, reason: str, extra: str = ""
    ) -> bool:
        """Show a confirmation with the target's record. True if confirmed."""
        actions = self._actions()
        history = await actions.get_history(str(ctx.guild.id), str(target.id), limit=3)
        total = await actions.count_history(str(ctx.guild.id), str(target.id))

        embed = discord.Embed(
            title=f"Confirm {action}",
            description=f"{target.mention} · `{target}`\n`{target.id}`",
            color=WARN,
        )
        embed.add_field(name="Reason", value=reason[:500], inline=False)
        if extra:
            embed.add_field(name="Effect", value=extra, inline=False)

        # Account age is the cheapest signal for a throwaway alt.
        created = target.created_at
        embed.add_field(
            name="Account created", value=f"<t:{int(created.timestamp())}:R>", inline=True
        )
        member = ctx.guild.get_member(target.id)
        if member and member.joined_at:
            embed.add_field(
                name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True
            )

        if total:
            lines = [
                f"`{e['action']}` <t:{int(e['created_at'].timestamp())}:R> — "
                f"{(e.get('reason') or 'no reason')[:60]}"
                for e in history
            ]
            embed.add_field(
                name=f"Prior record ({total})", value="\n".join(lines), inline=False
            )
        else:
            embed.add_field(name="Prior record", value="Nothing on record.", inline=False)

        if target.display_avatar:
            embed.set_thumbnail(url=target.display_avatar.url)

        view = ConfirmActionView(ctx.author, label=action.title())
        view.message = await ctx.send(embed=embed, view=view)
        await view.wait()

        if not view.confirmed:
            embed.title = f"{action.title()} cancelled"
            embed.color = 0x9B8F95
            for item in view.children:
                item.disabled = True
            try:
                await view.message.edit(embed=embed, view=view)
            except discord.HTTPException:
                pass
            return False
        return True

    async def _report(self, ctx, target, result, reason: str, view_message=None) -> None:
        """Post the success embed and mirror it to the moderation log."""
        embed = discord.Embed(
            title=f"✅ {result.action.title()} · {target}",
            color=GOOD,
        )
        embed.add_field(name="User", value=f"{getattr(target, 'mention', target)}\n`{target.id}`", inline=True)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(
            name="DM", value="delivered" if result.dm_delivered else "not delivered", inline=True
        )
        embed.add_field(name="Reason", value=reason[:1000], inline=False)
        if result.expires_at:
            embed.add_field(
                name="Expires", value=f"<t:{int(result.expires_at.timestamp())}:R>", inline=True
            )
        if result.details.get("delete_message_days"):
            embed.add_field(
                name="Messages removed",
                value=f"last {result.details['delete_message_days']} day(s)",
                inline=True,
            )

        if view_message is not None:
            try:
                await view_message.edit(embed=embed, view=None)
            except discord.HTTPException:
                await ctx.send(embed=embed)
        else:
            await ctx.send(embed=embed)

        await self._actions().post_log(ctx.guild, ctx.author, target, result, reason)

    # ------------------------------------------------------------------

    def register_commands(self):
        """Attach the moderation commands."""

        @self.bot.hybrid_command(
            name="timeout",
            description="Time a member out for a duration (Moderate Members required)",
        )
        @discord.app_commands.describe(
            user="Who to time out",
            duration=f"How long — {DURATION_HELP}. Max 28 days.",
            reason="Why. The member is told this.",
            silent="Skip the DM notification",
        )
        @moderator_command
        async def timeout_command(
            ctx,
            user: discord.Member,
            duration: str,
            *,
            reason: str = "No reason provided",
            silent: bool = False,
        ):
            actions = self._actions()
            if actions is None:
                await self._fail(ctx, "The moderation system is not available.")
                return

            parsed = parse_duration(duration)
            if parsed is None:
                await self._fail(
                    ctx, f"I could not read `{duration}` as a duration. Try {DURATION_HELP}."
                )
                return
            if parsed > MAX_TIMEOUT:
                await self._fail(
                    ctx,
                    f"Discord caps timeouts at 28 days; you asked for "
                    f"{format_duration(parsed)}. Use `/ban` for longer.",
                )
                return

            await ctx.defer()
            result = await actions.timeout(
                ctx.guild, ctx.author, user, parsed, reason, notify=not silent
            )
            if not result.ok:
                await self._fail(ctx, result.message)
                return
            await self._report(ctx, user, result, reason)

        @self.bot.hybrid_command(
            name="untimeout", description="Lift a member's timeout (Moderate Members required)"
        )
        @discord.app_commands.describe(user="Who to release", reason="Why")
        @moderator_command
        async def untimeout_command(
            ctx, user: discord.Member, *, reason: str = "Timeout lifted by a moderator"
        ):
            actions = self._actions()
            if actions is None:
                await self._fail(ctx, "The moderation system is not available.")
                return

            await ctx.defer()
            result = await actions.untimeout(ctx.guild, ctx.author, user, reason)
            if not result.ok:
                await self._fail(ctx, result.message)
                return
            await self._report(ctx, user, result, reason)

        @self.bot.hybrid_command(
            name="kick", description="Remove a member from the server (Kick Members required)"
        )
        @discord.app_commands.describe(
            user="Who to remove",
            reason="Why. The member is told this.",
            silent="Skip the DM notification",
            confirm="Skip the confirmation step",
        )
        @moderator_command
        async def kick_command(
            ctx,
            user: discord.Member,
            *,
            reason: str = "No reason provided",
            silent: bool = False,
            confirm: bool = False,
        ):
            actions = self._actions()
            if actions is None:
                await self._fail(ctx, "The moderation system is not available.")
                return

            refusal = actions.check_hierarchy(ctx.author, user, ctx.guild)
            if refusal:
                await self._fail(ctx, refusal)
                return

            await ctx.defer()

            message = None
            if not confirm:
                if not await self._confirm(
                    ctx, user, "kick", reason, "They can rejoin with a new invite."
                ):
                    return
                message = None

            result = await actions.kick(ctx.guild, ctx.author, user, reason, notify=not silent)
            if not result.ok:
                await self._fail(ctx, result.message)
                return
            await self._report(ctx, user, result, reason, message)

        @self.bot.hybrid_command(
            name="ban", description="[Admin] Ban a user from the server"
        )
        @discord.app_commands.describe(
            user="Who to ban — pick them from the list",
            user_id="Or paste an ID, to ban someone who already left or has not joined",
            reason="Why. The user is told this.",
            delete_days="Delete their messages from the last N days (0-7)",
            silent="Skip the DM notification",
            confirm="Skip the confirmation step",
        )
        @admin_command
        async def ban_command(
            ctx,
            user: Optional[discord.User] = None,
            user_id: Optional[str] = None,
            *,
            reason: str = "No reason provided",
            delete_days: int = 0,
            silent: bool = False,
            confirm: bool = False,
        ):
            actions = self._actions()
            if actions is None:
                await self._fail(ctx, "The moderation system is not available.")
                return

            # `user` is a real user picker, which is what you want almost every
            # time. `user_id` stays available because banning someone who has
            # already left, or pre-banning a raider, cannot go through a picker.
            if user is None and not user_id:
                await self._fail(
                    ctx, "Pick a user, or pass `user_id` to ban someone who is not in the server."
                )
                return
            if user is not None and user_id:
                await self._fail(ctx, "Give me either a user or an ID, not both.")
                return

            target = user
            if target is None:
                target = await self._resolve_user(ctx, user_id)
                if target is None:
                    await self._fail(
                        ctx,
                        f"Could not find a user matching `{user_id[:60]}`. "
                        f"Check the ID is right.",
                    )
                    return

            if not 0 <= delete_days <= 7:
                await self._fail(ctx, "`delete_days` must be between 0 and 7.")
                return

            refusal = actions.check_hierarchy(ctx.author, target, ctx.guild)
            if refusal:
                await self._fail(ctx, refusal)
                return

            await ctx.defer()

            if not confirm:
                effect = "This is permanent until manually reversed with `/unban`."
                if delete_days:
                    effect += f"\nTheir messages from the last {delete_days} day(s) are deleted."
                if not await self._confirm(ctx, target, "ban", reason, effect):
                    return

            result = await actions.ban(
                ctx.guild, ctx.author, target, reason,
                delete_message_days=delete_days, notify=not silent,
            )
            if not result.ok:
                await self._fail(ctx, result.message)
                return
            await self._report(ctx, target, result, reason)

        @self.bot.hybrid_command(name="unban", description="[Admin] Lift a ban")
        @discord.app_commands.describe(user_id="The banned user's ID", reason="Why")
        @admin_command
        async def unban_command(
            ctx, user_id: str, *, reason: str = "Ban lifted by an admin"
        ):
            actions = self._actions()
            if actions is None:
                await self._fail(ctx, "The moderation system is not available.")
                return

            digits = "".join(ch for ch in user_id if ch.isdigit())
            if not digits:
                await self._fail(ctx, "That does not look like a user ID.")
                return

            await ctx.defer()
            result = await actions.unban(ctx.guild, ctx.author, int(digits), reason)
            if not result.ok:
                await self._fail(ctx, result.message)
                return

            target = await self.bot.fetch_user(int(digits))
            await self._report(ctx, target, result, reason)

        @self.bot.hybrid_command(
            name="modlogs", description="Show a user's moderation history"
        )
        @discord.app_commands.describe(user="Whose record to show")
        @moderator_command
        async def modlogs_command(ctx, user: discord.User):
            actions = self._actions()
            if actions is None:
                await self._fail(ctx, "The moderation system is not available.")
                return

            await ctx.defer(ephemeral=True)
            entries = await actions.get_history(str(ctx.guild.id), str(user.id), limit=10)
            total = await actions.count_history(str(ctx.guild.id), str(user.id))

            embed = discord.Embed(
                title=f"📋 Moderation history · {user}",
                description=f"{user.mention} · **{total}** recorded action(s)",
                color=WARN if total else GOOD,
            )
            embed.set_thumbnail(url=user.display_avatar.url)

            if not entries:
                embed.description += "\n\nNothing on record. A clean slate."
            else:
                for entry in entries:
                    stamp = int(entry["created_at"].timestamp())
                    value = (
                        f"by {entry.get('moderator_name', 'unknown')}\n"
                        f"{(entry.get('reason') or 'No reason given')[:200]}"
                    )
                    if entry.get("duration_seconds"):
                        value += f"\nDuration: {format_duration(timedelta(seconds=entry['duration_seconds']))}"
                    embed.add_field(
                        name=f"{entry['action'].title()} · <t:{stamp}:R>",
                        value=value,
                        inline=False,
                    )

            await ctx.send(embed=embed, ephemeral=True)

        logger.info("✅ Moderation commands registered")

    # ------------------------------------------------------------------

    async def _resolve_user(self, ctx, raw: str) -> Optional[discord.abc.User]:
        """Resolve a mention, an ID, or a name — including users not in the guild.

        Taking a string rather than a Member is deliberate: banning someone who
        has already left, or pre-banning a raider, are both things you want and
        neither resolves as a Member.
        """
        raw = raw.strip()

        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits and len(digits) >= 15:
            member = ctx.guild.get_member(int(digits))
            if member:
                return member
            try:
                return await self.bot.fetch_user(int(digits))
            except discord.HTTPException:
                return None

        # Fall back to a name lookup within the guild.
        lowered = raw.lower().lstrip("@")
        for member in ctx.guild.members:
            if lowered in (member.name.lower(), member.display_name.lower()):
                return member
        return None
