"""Browsable /help.

Commands are bucketed by name into a handful of categories. Anything not
explicitly listed still shows up under "Everything else", so a newly added
command is never invisible just because nobody updated this file.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

ACCENT = 0xF2A65A
PER_CATEGORY_LIMIT = 25

# (key, label, emoji, blurb, command names)
CATEGORIES: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    (
        "start",
        "Getting started",
        "⛩️",
        "The handful worth knowing on day one.",
        ("help", "ping", "about", "rep", "daily", "leaderboard", "profile", "quests"),
    ),
    (
        "rep",
        "Reputation",
        "🎭",
        "Earn standing at the shrine.",
        ("rep", "daily", "thank", "repways", "inorep"),
    ),
    (
        "ranking",
        "Points & ranking",
        "🏆",
        "Leaderboards, stats and streaks.",
        ("leaderboard", "stats", "profile", "quests", "selectquests", "events"),
    ),
    (
        "art",
        "Art challenges",
        "🎨",
        "Challenges, submissions and duels.",
        (
            "artchallenge",
            "artstats",
            "artleaderboard",
            "artsubmit",
            "duel",
            "duelstats",
            "debuff",
        ),
    ),
    (
        "fun",
        "Fun",
        "🎲",
        "Nonsense, on request.",
        (
            "8ball",
            "roll",
            "coinflip",
            "ship",
            "vibecheck",
            "fortune",
            "choose",
            "rps",
            "wouldyourather",
            "avatar",
        ),
    ),
    (
        "utility",
        "Utility",
        "🔧",
        "Translation, support and odds and ends.",
        ("translation", "language", "patreon", "uptime", "logoff"),
    ),
    (
        "staff",
        "Staff",
        "🛡️",
        "Moderation. Most of these need permissions.",
        (
            "warn",
            "warnings",
            "clearwarnings",
            "nsfwban",
            "nsfwunban",
            "overrule",
            "modconfig",
            "modstats",
            "setlogchannel",
            "sync",
        ),
    ),
)


class HelpView(discord.ui.View):
    """A category dropdown over the bot's command tree."""

    def __init__(self, bot: commands.Bot, invoker: discord.abc.User, timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.invoker = invoker
        self.current = "start"
        self.message: Optional[discord.Message] = None
        self.add_item(CategorySelect(self))

    # ------------------------------------------------------------------

    def _all_commands(self) -> dict[str, commands.Command]:
        return {command.name: command for command in self.bot.commands}

    def _categorised_names(self) -> set[str]:
        names: set[str] = set()
        for _, _, _, _, members in CATEGORIES:
            names.update(members)
        return names

    def _commands_for(self, key: str) -> list[commands.Command]:
        available = self._all_commands()

        if key == "other":
            known = self._categorised_names()
            chosen: Iterable[str] = sorted(set(available) - known)
        else:
            entry = next((c for c in CATEGORIES if c[0] == key), None)
            if entry is None:
                return []
            # Preserve the curated order rather than sorting alphabetically.
            chosen = [name for name in entry[4] if name in available]

        return [available[name] for name in chosen][:PER_CATEGORY_LIMIT]

    def _meta_for(self, key: str) -> tuple[str, str, str]:
        if key == "other":
            return "Everything else", "📦", "Commands that do not fit a category."
        entry = next((c for c in CATEGORIES if c[0] == key), None)
        if entry is None:
            return "Help", "❓", ""
        return entry[1], entry[2], entry[3]

    def build_embed(self) -> discord.Embed:
        label, emoji, blurb = self._meta_for(self.current)
        found = self._commands_for(self.current)

        embed = discord.Embed(
            title=f"{emoji} {label}",
            description=blurb,
            color=ACCENT,
        )

        if not found:
            embed.description = f"{blurb}\n\nNothing here right now."
        else:
            lines = []
            for command in found:
                description = (command.description or command.help or "").split("\n")[0]
                # Discord truncates hard at 1024 per field; keep each line short
                # enough that a full category always fits in one.
                lines.append(f"`/{command.name}` — {description[:70]}")
            embed.add_field(name="​", value="\n".join(lines), inline=False)

        total = len(self._all_commands())
        embed.set_footer(
            text=f"{len(found)} shown · {total} commands total · /help <command> for detail"
        )
        return embed

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class CategorySelect(discord.ui.Select):
    def __init__(self, view: HelpView):
        self._parent = view
        options = [
            discord.SelectOption(
                label=label,
                value=key,
                emoji=emoji,
                description=blurb[:100],
                default=key == view.current,
            )
            for key, label, emoji, blurb, _ in CATEGORIES
        ]
        options.append(
            discord.SelectOption(
                label="Everything else",
                value="other",
                emoji="📦",
                description="Commands that do not fit a category.",
            )
        )
        super().__init__(placeholder="Pick a category…", options=options)

    async def callback(self, interaction: discord.Interaction):
        self._parent.current = self.values[0]
        for option in self.options:
            option.default = option.value == self.values[0]
        await interaction.response.edit_message(
            embed=self._parent.build_embed(), view=self._parent
        )
