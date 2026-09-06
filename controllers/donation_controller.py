"""Owner-only donation goal commands and the live progress-bar message.

`/setup-dono` opens an interactive wizard (see views/donation_setup_view.py).
Everything about a goal lives in MongoDB, so the wizard reads and writes the
same records the website renders from.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import tasks

from config import Config
from models.donation_progress_bar import render_progress_bar
from views.donation_setup_view import DonationSetupView, build_status_embed

logger = logging.getLogger(__name__)

ACCENT = 0xAD1457


class DonationController:
    """Slash commands plus the goal channel's self-updating progress message."""

    def __init__(self, bot):
        self.bot = bot
        # Serialises bar re-renders. Two donations landing together would
        # otherwise race on edit and could leave the older total displayed.
        self._refresh_lock = asyncio.Lock()

    @property
    def manager(self):
        return getattr(self.bot, "donation_manager", None)

    async def _require_owner(self, interaction: discord.Interaction) -> bool:
        if await self.bot.is_owner(interaction.user):
            return True
        await interaction.response.send_message(
            "Only the bot owner can manage donation goals.", ephemeral=True
        )
        return False

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------
    async def build_bar_file(self, goal: Dict[str, Any]) -> Optional[discord.File]:
        """Render the Pillow bar for one goal."""
        manager = self.manager
        if not manager:
            return None
        progress = await manager.get_progress(goal.get("goal_id"))
        buffer = await asyncio.to_thread(
            render_progress_bar,
            progress["raised_usd"],
            progress["goal_usd"],
            progress["donation_count"],
            goal.get("bar_title") or "DONATION GOAL",
            goal.get("bar_subtitle"),
        )
        return discord.File(buffer, filename="donation-goal.png")

    async def _build_embed(self, goal: Dict[str, Any]) -> discord.Embed:
        progress = await self.manager.get_progress(goal.get("goal_id"))
        reward = goal.get("reward")
        description = goal.get("description") or ""

        embed = discord.Embed(
            title=goal.get("title") or "Donation goal",
            description=(
                f"{description}\n\n" if description else ""
            ) + (
                f"**${progress['raised_usd']:,.2f}** of **${progress['goal_usd']:,.2f}**\n"
                f"[Donate on Ko-fi]({Config.KOFI_URL}) · "
                f"[Every supporter]({Config.WEB_BASE_URL}/donations)"
            ),
            color=ACCENT,
            timestamp=datetime.now(timezone.utc),
        )
        if reward:
            embed.add_field(name="At 100%", value=reward, inline=False)
        embed.set_image(url="attachment://donation-goal.png")
        embed.set_footer(text="Updates automatically when a donation lands")
        return embed

    # ------------------------------------------------------------------
    # channel provisioning
    # ------------------------------------------------------------------
    def _goal_channel_overwrites(self, guild: discord.Guild) -> dict:
        overwrites = {
            # Everyone sees the goal; nobody can chat in it.
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                add_reactions=False,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False,
            ),
            # The bot must be able to post and edit its own message.
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                manage_messages=True,
                read_message_history=True,
            ),
        }
        # Any role with Administrator keeps the ability to talk in there.
        for role in guild.roles:
            if role.permissions.administrator and role != guild.default_role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )
        return overwrites

    async def create_goal_channel(
        self, guild: discord.Guild, name: str, category: Optional[discord.CategoryChannel]
    ) -> discord.TextChannel:
        """Create a channel everyone can read and only admins can post in."""
        clean = (name or "donation-goal").strip().lower().replace(" ", "-")
        return await guild.create_text_channel(
            name=clean,
            overwrites=self._goal_channel_overwrites(guild),
            category=category,
            topic=f"Donation goal · {Config.KOFI_URL}",
            reason="Donation goal channel created via /setup-dono",
        )

    async def lock_goal_channel(self, channel: discord.TextChannel):
        """Apply the same read-only permissions to a channel that already exists."""
        guild = channel.guild
        for target, overwrite in self._goal_channel_overwrites(guild).items():
            await channel.set_permissions(
                target, overwrite=overwrite,
                reason="Donation goal channel lockdown via /setup-dono",
            )

    # ------------------------------------------------------------------
    # the progress message
    # ------------------------------------------------------------------
    async def refresh_progress_message(
        self,
        donation: Optional[Dict[str, Any]] = None,
        goal_id: Optional[str] = None,
    ) -> bool:
        """Re-render the bar and edit the pinned message in place."""
        manager = self.manager
        if not manager:
            return False

        async with self._refresh_lock:
            goal = await (manager.get_goal(goal_id) if goal_id else manager.get_active_goal())
            if not goal:
                return False

            channel_id = goal.get("channel_id")
            if not channel_id:
                return False

            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                except discord.NotFound:
                    logger.warning("Goal channel %s is gone, unlinking", channel_id)
                    await manager.clear_goal_field(goal["goal_id"], "channel_id")
                    await manager.clear_goal_field(goal["goal_id"], "message_id")
                    return False
                except discord.Forbidden:
                    logger.error("No access to goal channel %s", channel_id)
                    return False

            embed = await self._build_embed(goal)
            file = await self.build_bar_file(goal)
            if file is None:
                return False

            message_id = goal.get("message_id")
            if message_id:
                try:
                    message = await channel.fetch_message(int(message_id))
                    await message.edit(embed=embed, attachments=[file])
                    await self._maybe_announce(channel, goal, donation)
                    return True
                except discord.NotFound:
                    logger.info("Goal message missing, posting a new one")
                except discord.Forbidden:
                    logger.error("Missing permission to edit the goal message")
                    return False
                except Exception as e:
                    logger.error(f"Error editing goal message: {e}")
                    return False
                # The File object was consumed by the failed edit.
                file = await self.build_bar_file(goal)

            try:
                message = await channel.send(embed=embed, file=file)
                await manager.update_goal(goal["goal_id"], message_id=str(message.id))
                try:
                    await message.pin()
                except discord.HTTPException:
                    pass
                await self._maybe_announce(channel, goal, donation)
                return True
            except discord.Forbidden:
                logger.error("Missing permission to post in the goal channel")
                return False
            except Exception as e:
                logger.error(f"Error posting goal message: {e}")
                return False

    async def _maybe_announce(self, channel, goal: Dict[str, Any], donation: Optional[Dict[str, Any]]):
        """Post a short thank-you under the bar for a new donation."""
        if not donation or not goal.get("announce", True):
            return

        name = donation.get("from_name") or "Anonymous"
        amount = donation.get("amount_usd") or 0.0
        line = f"**{name}** just donated **${amount:,.2f}**. Riko is pretending not to care."

        role_id = goal.get("ping_role_id")
        content = f"<@&{role_id}> {line}" if role_id else line

        try:
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=False,
                    roles=[discord.Object(id=int(role_id))] if role_id else False,
                ),
            )
        except Exception as e:
            logger.error(f"Error announcing donation: {e}")

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------
    def register_commands(self):
        guild_obj = discord.Object(id=Config.GUILD_ID)

        @app_commands.command(
            name="setup-dono",
            description="Open the donation goal setup panel (bot owner only)",
        )
        async def setup_dono(interaction: discord.Interaction):
            if not await self._require_owner(interaction):
                return
            if not self.manager:
                await interaction.response.send_message(
                    "The donation system is unavailable (no database connection).",
                    ephemeral=True,
                )
                return
            if interaction.guild is None:
                await interaction.response.send_message("Run this in the server.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            goal = await self.manager.ensure_default_goal()
            embed = await build_status_embed(self, goal)
            view = DonationSetupView(self, goal, interaction.user.id)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        self.bot.tree.add_command(setup_dono, guild=guild_obj)

        # ------------------------------------------------------------------
        dono = app_commands.Group(name="dono", description="Donation goal controls (bot owner only)")

        @dono.command(name="goal", description="Change the active goal's target")
        @app_commands.describe(amount="New target in USD")
        async def dono_goal(interaction: discord.Interaction, amount: float):
            if not await self._require_owner(interaction):
                return
            if not self.manager:
                await interaction.response.send_message("Donations unavailable.", ephemeral=True)
                return
            if amount <= 0:
                await interaction.response.send_message("Target must be above zero.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            goal = await self.manager.ensure_default_goal()
            await self.manager.update_goal(goal["goal_id"], target_usd=amount)
            await self.refresh_progress_message(goal_id=goal["goal_id"])
            progress = await self.manager.get_progress(goal["goal_id"])
            await interaction.followup.send(
                f"Target is now **${amount:,.2f}**. Currently at "
                f"${progress['raised_usd']:,.2f} ({progress['percent']:.1f}%).",
                ephemeral=True,
            )

        @dono.command(name="backfill", description="Set USD raised before webhooks were connected")
        @app_commands.describe(amount="Amount in USD to add on top of webhook donations")
        async def dono_backfill(interaction: discord.Interaction, amount: float):
            if not await self._require_owner(interaction):
                return
            if not self.manager:
                await interaction.response.send_message("Donations unavailable.", ephemeral=True)
                return
            if amount < 0:
                await interaction.response.send_message("Backfill cannot be negative.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            goal = await self.manager.ensure_default_goal()
            await self.manager.update_goal(goal["goal_id"], backfill_usd=amount)
            await self.refresh_progress_message(goal_id=goal["goal_id"])
            progress = await self.manager.get_progress(goal["goal_id"])
            await interaction.followup.send(
                f"Backfill set to **${amount:,.2f}**. Total is now "
                f"**${progress['raised_usd']:,.2f}**.",
                ephemeral=True,
            )

        @dono.command(name="refresh", description="Re-render the progress bar now")
        async def dono_refresh(interaction: discord.Interaction):
            if not await self._require_owner(interaction):
                return
            await interaction.response.defer(ephemeral=True)
            ok = await self.refresh_progress_message()
            await interaction.followup.send(
                "Progress bar refreshed." if ok else
                "Could not refresh. Open `/setup-dono` and link a channel first.",
                ephemeral=True,
            )

        @dono.command(name="status", description="Show donation totals and configuration")
        async def dono_status(interaction: discord.Interaction):
            if not await self._require_owner(interaction):
                return
            if not self.manager:
                await interaction.response.send_message("Donations unavailable.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            goal = await self.manager.ensure_default_goal()
            await interaction.followup.send(
                embed=await build_status_embed(self, goal), ephemeral=True
            )

        self.bot.tree.add_command(dono, guild=guild_obj)
        logger.info("✅ Donation commands registered")

    # ------------------------------------------------------------------
    # periodic safety net
    # ------------------------------------------------------------------
    @tasks.loop(minutes=30)
    async def periodic_refresh(self):
        """Catch up if a webhook was missed while the bot was restarting."""
        try:
            await self.refresh_progress_message()
        except Exception as e:
            logger.error(f"Error in periodic donation refresh: {e}")

    @periodic_refresh.before_loop
    async def before_periodic_refresh(self):
        await self.bot.wait_until_ready()

    def start_tasks(self):
        if not self.periodic_refresh.is_running():
            self.periodic_refresh.start()

    def stop_tasks(self):
        if self.periodic_refresh.is_running():
            self.periodic_refresh.cancel()
