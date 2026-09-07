"""Utility commands chosen for how this server actually runs.

It has code-help and bug-report forums, a stage channel for events, Minecraft
channels, and a membership spread across timezones with auto-translation
already enabled. So:

* ``/userinfo``  — account age and join date at a glance, which is the fastest
  alt check a moderator has, plus the member's own rep and rank.
* ``/serverinfo`` — the numbers people ask for repeatedly.
* ``/poll``      — button voting with live counts, for the feedback and
  suggestion channels.
* ``/remindme``  — for "check back after the build finishes" in help threads.
* ``/afk``       — so a help thread gets an answer instead of silence.
* ``/timestamp`` — renders a time in everyone's own timezone, for events.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import commands, tasks

from config import Config
from controllers.security import public_command
from models.mod_actions import format_duration, parse_duration

logger = logging.getLogger(__name__)

ACCENT = 0xF2A65A
GOOD = 0x77DD77
WARN = 0xE8A33D
DANGER = 0xE05252

POLL_EMOJI = ("🇦", "🇧", "🇨", "🇩", "🇪")
MAX_REMINDERS_PER_USER = 10
# Discord's own limit is 25; five keeps a poll readable.
MAX_POLL_OPTIONS = 5


class PollView(discord.ui.View):
    """Button voting with live counts. One vote per person, changeable."""

    def __init__(self, question: str, options: list[str], author_id: int, timeout: float = 86400):
        super().__init__(timeout=timeout)
        self.question = question
        self.options = options
        self.author_id = author_id
        self.message: Optional[discord.Message] = None
        # user_id -> option index, so a second click moves the vote rather
        # than adding one.
        self.votes: dict[int, int] = {}

        for index, option in enumerate(options):
            self.add_item(PollButton(index, option))
        self.add_item(PollEndButton())

    def counts(self) -> list[int]:
        tally = [0] * len(self.options)
        for choice in self.votes.values():
            if 0 <= choice < len(tally):
                tally[choice] += 1
        return tally

    def build_embed(self, closed: bool = False) -> discord.Embed:
        tally = self.counts()
        total = sum(tally) or 0

        embed = discord.Embed(
            title=("📊 " if not closed else "📊 Closed · ") + self.question[:230],
            color=0x9B8F95 if closed else ACCENT,
        )

        lines = []
        highest = max(tally) if tally else 0
        for index, option in enumerate(self.options):
            count = tally[index]
            share = (count / total * 100) if total else 0
            filled = round(share / 100 * 12)
            bar = "█" * filled + "░" * (12 - filled)
            # Only mark a winner once, and never on a tie at zero.
            lead = " ←" if closed and count == highest and count > 0 else ""
            lines.append(
                f"{POLL_EMOJI[index]} **{option[:60]}**\n"
                f"`{bar}` {count} ({share:.0f}%){lead}"
            )

        embed.description = "\n\n".join(lines)
        embed.set_footer(
            text=f"{total} vote{'s' if total != 1 else ''}"
            + ("" if closed else " · click to vote, click again to change")
        )
        return embed

    async def refresh(self, interaction: discord.Interaction, closed: bool = False):
        if closed:
            for item in self.children:
                item.disabled = True
        await interaction.response.edit_message(embed=self.build_embed(closed), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(embed=self.build_embed(closed=True), view=self)
            except discord.HTTPException:
                pass


class PollButton(discord.ui.Button):
    def __init__(self, index: int, option: str):
        super().__init__(
            label=option[:70] or f"Option {index + 1}",
            emoji=POLL_EMOJI[index],
            style=discord.ButtonStyle.secondary,
        )
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: PollView = self.view
        previous = view.votes.get(interaction.user.id)

        if previous == self.index:
            # Clicking your own choice again retracts it.
            view.votes.pop(interaction.user.id, None)
        else:
            view.votes[interaction.user.id] = self.index

        await view.refresh(interaction)


class PollEndButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="End poll", emoji="🔒", style=discord.ButtonStyle.danger, row=1)

    async def callback(self, interaction: discord.Interaction):
        view: PollView = self.view
        is_author = interaction.user.id == view.author_id
        can_manage = getattr(interaction.user.guild_permissions, "manage_messages", False)
        if not (is_author or can_manage):
            await interaction.response.send_message(
                "Only whoever started the poll can end it.", ephemeral=True
            )
            return
        view.stop()
        await view.refresh(interaction, closed=True)


class UtilityCommandsController:
    """Registers the utility commands and runs the reminder loop."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db = getattr(getattr(bot, "leaderboard_manager", None), "db", None)
        self.reminders = db["reminders"] if db is not None else None
        self.afk = db["afk_status"] if db is not None else None

        if self.reminders is not None:
            try:
                self.reminders.create_index([("due_at", 1)])
                self.reminders.create_index([("user_id", 1)])
                self.afk.create_index([("user_id", 1), ("guild_id", 1)], unique=True)
            except Exception as exc:
                logger.error("Could not create utility indexes: %s", exc)

    # ------------------------------------------------------------------

    def register_commands(self):
        """Attach the utility commands."""

        @self.bot.hybrid_command(
            name="userinfo", description="Account age, join date, roles and rank for a member"
        )
        @discord.app_commands.describe(user="Who to look up (defaults to you)")
        @public_command
        async def userinfo_command(ctx, user: Optional[discord.Member] = None):
            target = user or ctx.author
            await ctx.defer()

            embed = discord.Embed(color=target.color if target.color.value else ACCENT)
            embed.set_author(name=str(target), icon_url=target.display_avatar.url)
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.add_field(name="ID", value=f"`{target.id}`", inline=True)
            embed.add_field(
                name="Account created",
                value=f"<t:{int(target.created_at.timestamp())}:D>\n<t:{int(target.created_at.timestamp())}:R>",
                inline=True,
            )
            if target.joined_at:
                embed.add_field(
                    name="Joined server",
                    value=f"<t:{int(target.joined_at.timestamp())}:D>\n<t:{int(target.joined_at.timestamp())}:R>",
                    inline=True,
                )

            # A young account that joined recently is the pattern worth seeing.
            age = datetime.now(timezone.utc) - target.created_at
            if age < timedelta(days=7):
                embed.add_field(
                    name="⚠️ Note",
                    value=f"This account is only {format_duration(age)} old.",
                    inline=False,
                )

            roles = [r.mention for r in reversed(target.roles) if r.name != "@everyone"]
            embed.add_field(
                name=f"Roles ({len(roles)})",
                value=" ".join(roles[:15]) + (" …" if len(roles) > 15 else "") or "None",
                inline=False,
            )

            economy = getattr(self.bot, "rep_economy", None)
            if economy:
                try:
                    profile = await economy.get_profile(target, str(ctx.guild.id))
                    _, title, emoji = profile["tier"]
                    embed.add_field(
                        name="InoRep",
                        value=f"{emoji} **{profile['rep']:,}** · {title}"
                        + (f" · rank #{profile['rank']}" if profile["rank"] else ""),
                        inline=False,
                    )
                except Exception as exc:
                    logger.debug("Could not read rep for userinfo: %s", exc)

            if target.is_timed_out():
                embed.add_field(
                    name="⏳ Timed out until",
                    value=f"<t:{int(target.communication_disabled_until.timestamp())}:R>",
                    inline=False,
                )
                embed.color = WARN

            await ctx.send(embed=embed)

        @self.bot.hybrid_command(name="serverinfo", description="Stats about this server")
        @public_command
        async def serverinfo_command(ctx):
            guild = ctx.guild
            await ctx.defer()

            embed = discord.Embed(title=guild.name, color=ACCENT)
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)

            embed.add_field(name="Members", value=f"{guild.member_count:,}", inline=True)
            embed.add_field(
                name="Created",
                value=f"<t:{int(guild.created_at.timestamp())}:D>",
                inline=True,
            )
            embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)

            text = sum(1 for c in guild.channels if isinstance(c, discord.TextChannel))
            voice = sum(1 for c in guild.channels if isinstance(c, discord.VoiceChannel))
            forum = sum(1 for c in guild.channels if isinstance(c, discord.ForumChannel))
            embed.add_field(
                name="Channels",
                value=f"{text} text · {voice} voice · {forum} forum",
                inline=True,
            )
            embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
            embed.add_field(
                name="Boosts",
                value=f"{guild.premium_subscription_count or 0} (tier {guild.premium_tier})",
                inline=True,
            )
            embed.add_field(name="Emoji", value=str(len(guild.emojis)), inline=True)

            manager = getattr(self.bot, "leaderboard_manager", None)
            if manager and hasattr(manager, "get_stats_summary"):
                try:
                    stats = await asyncio.to_thread(manager.get_stats_summary)
                    embed.add_field(
                        name="Images scored",
                        value=f"{stats['total_images']:,} from {stats['total_users']:,} people",
                        inline=False,
                    )
                except Exception as exc:
                    logger.debug("Could not read stats for serverinfo: %s", exc)

            embed.set_footer(text=f"ID: {guild.id}")
            await ctx.send(embed=embed)

        @self.bot.hybrid_command(name="poll", description="Start a poll people vote on with buttons")
        @discord.app_commands.describe(
            question="What you are asking",
            options="Choices, separated by | — up to 5. Leave empty for Yes/No.",
        )
        @public_command
        async def poll_command(ctx, question: str, *, options: Optional[str] = None):
            if options:
                choices = [part.strip() for part in options.split("|") if part.strip()]
            else:
                choices = ["Yes", "No"]

            if len(choices) < 2:
                await ctx.send(
                    "❌ Give me at least two options separated by `|`, or none for Yes/No.",
                    ephemeral=True,
                )
                return
            if len(choices) > MAX_POLL_OPTIONS:
                await ctx.send(
                    f"❌ At most {MAX_POLL_OPTIONS} options, or nobody reads it.",
                    ephemeral=True,
                )
                return

            view = PollView(question, choices, ctx.author.id)
            embed = view.build_embed()
            embed.set_author(
                name=f"Poll by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url
            )
            view.message = await ctx.send(embed=embed, view=view)

        @self.bot.hybrid_command(
            name="remindme", description="Have Ino remind you about something later"
        )
        @discord.app_commands.describe(
            when="How long from now — e.g. 30m, 2h, 3d",
            what="What to remind you about",
        )
        @public_command
        async def remindme_command(ctx, when: str, *, what: str = "no note"):
            delay = parse_duration(when)
            if delay is None:
                await ctx.send(
                    "❌ I could not read that. Try `30m`, `2h`, `3d`, or `1d12h`.",
                    ephemeral=True,
                )
                return
            if delay < timedelta(minutes=1):
                await ctx.send("❌ One minute is the shortest I will bother with.", ephemeral=True)
                return
            if delay > timedelta(days=365):
                await ctx.send("❌ A year is the longest I will remember.", ephemeral=True)
                return
            if self.reminders is None:
                await ctx.send("❌ Reminders are not available right now.", ephemeral=True)
                return

            pending = await asyncio.to_thread(
                self.reminders.count_documents, {"user_id": str(ctx.author.id)}
            )
            if pending >= MAX_REMINDERS_PER_USER:
                await ctx.send(
                    f"❌ You already have {MAX_REMINDERS_PER_USER} reminders pending.",
                    ephemeral=True,
                )
                return

            due_at = datetime.now(timezone.utc) + delay
            await asyncio.to_thread(
                self.reminders.insert_one,
                {
                    "user_id": str(ctx.author.id),
                    "channel_id": str(ctx.channel.id),
                    "guild_id": str(ctx.guild.id) if ctx.guild else None,
                    "note": what[:500],
                    "due_at": due_at,
                    "created_at": datetime.now(timezone.utc),
                    "jump_url": ctx.message.jump_url if ctx.message else None,
                },
            )

            embed = discord.Embed(
                title="⏰ Reminder set",
                description=f"I will nudge you <t:{int(due_at.timestamp())}:R>.",
                color=GOOD,
            )
            embed.add_field(name="About", value=what[:500], inline=False)
            await ctx.send(embed=embed, ephemeral=True)

        @self.bot.hybrid_command(
            name="afk", description="Mark yourself AFK; Ino tells anyone who pings you"
        )
        @public_command
        async def afk_command(ctx):
            # No custom reason, by design. The status is echoed into a normal
            # message when someone pings you, which made a free-text field a
            # way to get Ino to say arbitrary things to a channel on demand.
            # "Away" is all anyone actually needs to know.
            if self.afk is None:
                await ctx.send("❌ AFK is not available right now.", ephemeral=True)
                return

            await asyncio.to_thread(
                self.afk.update_one,
                {"user_id": str(ctx.author.id), "guild_id": str(ctx.guild.id)},
                {
                    "$set": {
                        "user_id": str(ctx.author.id),
                        "guild_id": str(ctx.guild.id),
                        "since": datetime.now(timezone.utc),
                    }
                },
                True,
            )
            await ctx.send(
                embed=discord.Embed(
                    description=(
                        "💤 You are marked as away.\n"
                        "Anyone who pings you will be told. Send a message to clear it."
                    ),
                    color=ACCENT,
                ),
                ephemeral=True,
            )

        @self.bot.hybrid_command(
            name="timestamp",
            description="Turn a time into a stamp that shows in everyone's timezone",
        )
        @discord.app_commands.describe(
            when="How far from now — e.g. 2h, 3d. Use 0 for right now."
        )
        @public_command
        async def timestamp_command(ctx, when: str = "0"):
            delay = parse_duration(when) or timedelta(0)
            moment = datetime.now(timezone.utc) + delay
            stamp = int(moment.timestamp())

            styles = [
                ("Relative", "R"), ("Short time", "t"), ("Long time", "T"),
                ("Short date", "d"), ("Long date", "D"),
                ("Full", "F"),
            ]
            embed = discord.Embed(
                title="🕐 Timestamp",
                description=(
                    "Paste any of these; everyone sees it in their own timezone."
                ),
                color=ACCENT,
            )
            for name, style in styles:
                embed.add_field(
                    name=name,
                    value=f"<t:{stamp}:{style}>\n`<t:{stamp}:{style}>`",
                    inline=True,
                )
            await ctx.send(embed=embed)

        logger.info("✅ Utility commands registered")

    # ------------------------------------------------------------------

    def start_tasks(self):
        """Start the reminder loop.

        Kept out of ``register_commands`` so registration stays a pure,
        loop-free operation — starting a task there made the whole controller
        fail to register whenever no event loop was running yet.
        """
        if self.reminders is None:
            return
        if self.deliver_reminders.is_running():
            return
        try:
            self.deliver_reminders.start()
        except RuntimeError as exc:
            logger.warning("Could not start the reminder loop: %s", exc)

    @tasks.loop(seconds=30)
    async def deliver_reminders(self):
        """Deliver anything that has come due."""
        if self.reminders is None:
            return

        try:
            due = await asyncio.to_thread(
                lambda: list(
                    self.reminders.find({"due_at": {"$lte": datetime.now(timezone.utc)}}).limit(25)
                )
            )
        except Exception as exc:
            logger.error("Could not read due reminders: %s", exc)
            return

        for entry in due:
            # Delete first: a reminder that fails to send is better than one
            # that loops forever retrying against a deleted channel.
            try:
                await asyncio.to_thread(self.reminders.delete_one, {"_id": entry["_id"]})
            except Exception as exc:
                logger.error("Could not clear reminder: %s", exc)
                continue

            try:
                await self._send_reminder(entry)
            except Exception as exc:
                logger.warning("Could not deliver reminder: %s", exc)

    async def _send_reminder(self, entry: dict) -> None:
        user = self.bot.get_user(int(entry["user_id"]))
        if user is None:
            user = await self.bot.fetch_user(int(entry["user_id"]))

        created = entry.get("created_at")
        embed = discord.Embed(
            title="⏰ Reminder",
            description=entry.get("note", "no note"),
            color=ACCENT,
        )
        if created:
            embed.set_footer(text="Set")
            embed.timestamp = created
        if entry.get("jump_url"):
            embed.add_field(name="From", value=f"[Jump]({entry['jump_url']})", inline=False)

        # Prefer the channel it was set in, so the context is nearby; fall back
        # to a DM when that channel is gone or unwritable.
        channel = self.bot.get_channel(int(entry["channel_id"])) if entry.get("channel_id") else None
        if channel is not None:
            try:
                await channel.send(content=f"<@{entry['user_id']}>", embed=embed)
                return
            except discord.HTTPException:
                pass

        try:
            await user.send(embed=embed)
        except discord.HTTPException:
            logger.info("Could not deliver reminder to %s by any route", entry["user_id"])

    @deliver_reminders.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------

    async def handle_afk(self, message: discord.Message) -> None:
        """Clear the author's AFK, and answer for anyone they pinged.

        Everything here replies with mentions fully suppressed. A display name
        is attacker-controlled text, and a name like ``<@&1234...>`` echoed into
        message content would otherwise ping that role.
        """
        if self.afk is None or not message.guild or message.author.bot:
            return

        guild_id = str(message.guild.id)
        silent = discord.AllowedMentions.none()

        try:
            own = await asyncio.to_thread(
                self.afk.find_one_and_delete,
                {"user_id": str(message.author.id), "guild_id": guild_id},
            )
            if own:
                since = own.get("since")
                away = ""
                if since:
                    away = f" You were away for {format_duration(datetime.now(timezone.utc) - since)}."
                await message.reply(
                    f"👋 Welcome back.{away}",
                    mention_author=False,
                    allowed_mentions=silent,
                    delete_after=30,
                )

            # One reply per message however many AFK people were pinged, so a
            # message tagging several of them cannot be turned into a wall of
            # bot messages.
            away_names = []
            for mentioned in message.mentions[:5]:
                if mentioned.id == message.author.id:
                    continue
                entry = await asyncio.to_thread(
                    self.afk.find_one, {"user_id": str(mentioned.id), "guild_id": guild_id}
                )
                if not entry:
                    continue
                since = entry.get("since")
                ago = f" (<t:{int(since.timestamp())}:R>)" if since else ""
                name = discord.utils.escape_markdown(mentioned.display_name)[:32]
                away_names.append(f"**{name}**{ago}")

            if away_names:
                who = ", ".join(away_names)
                await message.reply(
                    f"💤 {who} {'is' if len(away_names) == 1 else 'are'} away.",
                    mention_author=False,
                    allowed_mentions=silent,
                    delete_after=60,
                )
        except Exception as exc:
            logger.debug("AFK handling failed: %s", exc)
