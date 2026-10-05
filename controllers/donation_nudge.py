"""A small donation-goal line under every command reply.

After a command finishes, the person who ran it gets a one-line subtext note
with the active goal's progress and a Ko-fi button. Slash commands get it as
an ephemeral followup, so only they see it; prefix commands get a quiet reply
that deletes itself. Supporters (the donor role) never see it, and staff can
switch it off with `/modconfig donation_nudge false`.
"""

import logging
import random
import time
from typing import Any, Dict, Optional

import discord
from discord.ext import commands

from config import Config

logger = logging.getLogger(__name__)

# Stored next to the other moderation settings so /modconfig owns it.
SETTING_NAME = "donation_nudge_enabled"

# The goal and the toggle are read on every command, so both are cached. A
# minute is short enough that a new donation shows up in the next few replies.
CACHE_SECONDS = 60

# How long the prefix-command version stays in the channel.
PREFIX_DELETE_AFTER = 30

# Commands that are already about donating, where a nudge would be noise.
SKIP_COMMANDS = {"setup-dono", "dono"}

# Each one says what a donation does and that nobody has to.
PITCHES = (
    "Donating helps keep Ino running and gets you the supporter role, "
    "but it's never required. Every command stays free.",
    "Totally optional, but every bit pushes the goal closer, and supporters "
    "get a role and no more of these notes.",
    "No pressure at all. If you enjoy Ino, a coffee helps cover the servers, "
    "and supporters stop seeing this line.",
    "Ino is free and stays free. Chipping in is optional and gets you the "
    "supporter role as a thank you.",
)


class DonationNudge:
    """Listens for finished commands and appends the goal line."""

    def __init__(self, bot):
        self.bot = bot
        self._enabled: Optional[bool] = None
        self._enabled_at = 0.0
        self._progress: Optional[Dict[str, Any]] = None
        self._progress_at = 0.0

    def register(self):
        self.bot.add_listener(self.on_app_command_completion, "on_app_command_completion")
        self.bot.add_listener(self.on_command_completion, "on_command_completion")

    def invalidate(self):
        """Drop the cached toggle, so a /modconfig change applies at once."""
        self._enabled = None

    # ------------------------------------------------------------------
    # cached reads
    # ------------------------------------------------------------------
    def _moderation_manager(self):
        leaderboard = getattr(self.bot, "leaderboard_manager", None)
        return getattr(leaderboard, "moderation_manager", None)

    async def is_enabled(self, guild_id: int) -> bool:
        now = time.monotonic()
        if self._enabled is None or now - self._enabled_at > CACHE_SECONDS:
            manager = self._moderation_manager()
            enabled = True
            if manager:
                enabled = bool(await manager.get_moderation_setting(
                    str(guild_id), SETTING_NAME, True
                ))
            self._enabled, self._enabled_at = enabled, now
        return self._enabled

    async def _get_progress(self) -> Optional[Dict[str, Any]]:
        manager = getattr(self.bot, "donation_manager", None)
        if not manager:
            return None
        now = time.monotonic()
        if self._progress is None or now - self._progress_at > CACHE_SECONDS:
            goal = await manager.get_active_goal()
            self._progress = await manager.get_progress(goal["goal_id"]) if goal else {}
            self._progress_at = now
        return self._progress or None

    # ------------------------------------------------------------------
    # building the note
    # ------------------------------------------------------------------
    @staticmethod
    def _donor_role_id(goal: Dict[str, Any]) -> Optional[int]:
        role_id = goal.get("donor_role_id") or Config.DONOR_ROLE_ID
        try:
            return int(role_id) if role_id else None
        except (TypeError, ValueError):
            return None

    async def build(self, user, guild, command_name: str):
        """Return ``(content, view)``, or None when this person gets no note."""
        if not guild or guild.id != Config.GUILD_ID:
            return None
        if getattr(user, "bot", False):
            return None
        if command_name.split(" ")[0] in SKIP_COMMANDS:
            return None
        if not await self.is_enabled(guild.id):
            return None

        progress = await self._get_progress()
        goal = (progress or {}).get("goal")
        if not goal:
            return None

        # Only a Member has roles; a plain User (role cache miss) gets the note.
        role_id = self._donor_role_id(goal)
        get_role = getattr(user, "get_role", None)
        if role_id and get_role and get_role(role_id):
            return None

        title = goal.get("title") or "Donation goal"
        raised, target = progress["raised_usd"], progress["goal_usd"]
        if progress["percent_raw"] >= 100:
            status = f"☕ **{title}** reached its goal of ${target:,.0f}, thank you all!"
            pitch = "Extra support is still welcome and never required."
        else:
            status = (
                f"☕ Current goal: **{title}** · ${raised:,.2f} of ${target:,.0f} "
                f"({progress['percent']:.0f}%)"
            )
            pitch = random.choice(PITCHES)
        content = f"-# {status}\n-# {pitch}"

        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(
            style=discord.ButtonStyle.link,
            label=(goal.get("kofi_button_label") or "Donate on Ko-fi")[:80],
            url=Config.KOFI_URL,
            emoji="☕",
        ))
        return content, view

    # ------------------------------------------------------------------
    # listeners
    # ------------------------------------------------------------------
    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        # A modal answer cannot be followed up, there is no message to hang
        # a followup off yet.
        if interaction.response.type == discord.InteractionResponseType.modal:
            return

        try:
            note = await self.build(
                interaction.user, interaction.guild, command.qualified_name
            )
            if not note:
                return
            content, view = note
            if interaction.response.is_done():
                await interaction.followup.send(content, view=view, ephemeral=True)
            else:
                await interaction.response.send_message(content, view=view, ephemeral=True)
        except discord.HTTPException as e:
            # Expired token, deleted channel and so on: the command itself
            # already worked, so this is never worth more than a debug line.
            logger.debug("Donation nudge not sent for /%s: %s", command.qualified_name, e)
        except Exception as e:
            logger.error("Donation nudge failed for /%s: %s", command.qualified_name, e)

    async def on_command_completion(self, ctx: commands.Context):
        # Hybrid commands run from the slash menu fire this too, alongside
        # on_app_command_completion, which already covered them.
        if ctx.interaction is not None:
            return
        try:
            note = await self.build(ctx.author, ctx.guild, ctx.command.qualified_name)
            if not note:
                return
            content, view = note
            await ctx.reply(
                content, view=view, mention_author=False, silent=True,
                delete_after=PREFIX_DELETE_AFTER,
            )
        except discord.HTTPException as e:
            logger.debug("Donation nudge not sent for R!%s: %s", ctx.command, e)
        except Exception as e:
            logger.error("Donation nudge failed for R!%s: %s", ctx.command, e)
