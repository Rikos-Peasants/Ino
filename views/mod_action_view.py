"""Buttons for moderation.

Two things live here:

* :class:`ConfirmActionView` — the "are you sure" step in front of a ban or a
  kick, showing the target's prior record so the decision is informed.
* :class:`AlertActionView` — Ban / Kick / Timeout buttons attached directly to
  a scam or burst alert, so a moderator can act from the alert instead of
  copying an ID into a command. It also carries the Image button, which shows
  the flagged image and offers to add it to the scam image list.

Both route through :class:`~models.mod_actions.ModerationActions`, so an action
taken from a button is recorded exactly like one taken from a command.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Optional

import discord

from config import Config
from models.mod_actions import ActionResult, ModerationActions, format_duration

logger = logging.getLogger(__name__)

DANGER = 0xE05252
WARN = 0xE8A33D
GOOD = 0x77DD77

# The one-click option the user asked for on alerts.
ALERT_TIMEOUT = timedelta(days=7)


async def is_moderator(bot, member: discord.Member) -> bool:
    """Whether a member may take moderation actions."""
    if not isinstance(member, discord.Member):
        return False
    try:
        if await bot.is_owner(member):
            return True
    except Exception:
        pass

    perms = member.guild_permissions
    if perms.administrator or perms.ban_members or perms.moderate_members:
        return True

    allowed = {
        getattr(Config, "DEFAULT_MODERATION_REVIEW_ROLE_ID", None),
        getattr(Config, "DEFAULT_MODERATION_ADMIN_ROLE_ID", None),
        getattr(Config, "NSFWBAN_MODERATOR_ROLE_ID", None),
        getattr(Config, "STAFF_ROLE_ID", None),
    }
    allowed.discard(None)
    return any(role.id in allowed for role in member.roles)


class ConfirmActionView(discord.ui.View):
    """A yes/no gate in front of a destructive action."""

    def __init__(self, invoker: discord.Member, label: str, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.invoker = invoker
        self.confirmed: Optional[bool] = None
        self.message: Optional[discord.Message] = None
        self.confirm.label = label

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                "This confirmation is not yours.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.confirmed = False
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self) -> None:
        self.confirmed = False
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class AlertActionView(discord.ui.View):
    """Moderation buttons attached to a scam or burst alert.

    Genuinely persistent: ``timeout=None`` and the custom_ids are static, so
    discord.py can reattach them after a restart. An alert raised overnight is
    often not seen until morning, and a dead button then is worse than none.

    Because the ids must stay static, the target is not encoded in them. It is
    recovered from the ``User ID: N`` prefix in the alert embed's footer, which
    every alert embed sets.
    """

    FOOTER_PATTERN = re.compile(r"User ID:\s*(\d{15,25})")

    def __init__(self, bot, target_id: int = 0, context: str = "scam alert"):
        super().__init__(timeout=None)
        self.bot = bot
        self.target_id = target_id
        self.context = context

    # ------------------------------------------------------------------

    def _actions(self) -> Optional[ModerationActions]:
        return getattr(self.bot, "mod_actions", None)

    @classmethod
    def _target_id_from(cls, interaction: discord.Interaction) -> Optional[int]:
        """Recover the subject of the alert from its embed footer."""
        message = interaction.message
        if message is None:
            return None
        for embed in message.embeds:
            text = (embed.footer.text if embed.footer else "") or ""
            match = cls.FOOTER_PATTERN.search(text)
            if match:
                return int(match.group(1))
        return None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await is_moderator(self.bot, interaction.user):
            await interaction.response.send_message(
                "❌ You need moderation permissions to use these.", ephemeral=True
            )
            return False
        return True

    async def _run(
        self,
        interaction: discord.Interaction,
        action: str,
        duration: Optional[timedelta] = None,
    ) -> None:
        await interaction.response.defer()

        actions = self._actions()
        if actions is None:
            await interaction.followup.send(
                "❌ The moderation system is not available.", ephemeral=True
            )
            return

        target_id = self._target_id_from(interaction) or self.target_id
        if not target_id:
            await interaction.followup.send(
                "❌ Could not work out who this alert is about.", ephemeral=True
            )
            return

        guild = interaction.guild
        moderator = interaction.user
        reason = f"{self.context}: actioned by {moderator} from the alert"

        member = guild.get_member(target_id)
        if action in ("kick", "timeout") and member is None:
            await interaction.followup.send(
                "❌ That member has already left the server.", ephemeral=True
            )
            return

        if action == "ban":
            target = member or discord.Object(id=target_id)
            if member is None:
                # Ban by ID still works for someone who already left.
                try:
                    target = await self.bot.fetch_user(target_id)
                except discord.HTTPException:
                    await interaction.followup.send("❌ Could not look that user up.", ephemeral=True)
                    return
            result = await actions.ban(guild, moderator, target, reason, delete_message_days=1)
        elif action == "kick":
            result = await actions.kick(guild, moderator, member, reason)
            target = member
        else:
            result = await actions.timeout(guild, moderator, member, duration, reason)
            target = member

        if not result.ok:
            await interaction.followup.send(f"❌ {result.message}", ephemeral=True)
            return

        await actions.post_log(guild, moderator, target, result, reason, source=self.context)
        await self._mark_resolved(interaction, moderator, result, duration)

    async def _mark_resolved(
        self,
        interaction: discord.Interaction,
        moderator: discord.Member,
        result: ActionResult,
        duration: Optional[timedelta],
    ) -> None:
        """Disable the buttons and stamp the alert with what was done."""
        for item in self.children:
            item.disabled = True

        summary = result.action.title()
        if duration:
            summary += f" ({format_duration(duration)})"

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.add_field(
            name="✅ Resolved",
            value=(
                f"**{summary}** by {moderator.mention}\n"
                f"DM {'delivered' if result.dm_delivered else 'not delivered'}"
            ),
            inline=False,
        )
        embed.color = GOOD

        try:
            await interaction.message.edit(embed=embed, view=self)
        except discord.HTTPException as exc:
            logger.warning("Could not update alert after action: %s", exc)

    # ------------------------------------------------------------------

    @discord.ui.button(
        label="Ban", emoji="🔨", style=discord.ButtonStyle.danger, custom_id="alert:ban"
    )
    async def ban_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._run(interaction, "ban")

    @discord.ui.button(
        label="Kick", emoji="👢", style=discord.ButtonStyle.danger, custom_id="alert:kick"
    )
    async def kick_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._run(interaction, "kick")

    @discord.ui.button(
        label="Timeout 1 week", emoji="⏳", style=discord.ButtonStyle.primary,
        custom_id="alert:timeout",
    )
    async def timeout_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._run(interaction, "timeout", ALERT_TIMEOUT)

    @discord.ui.button(
        label="Dismiss", emoji="✅", style=discord.ButtonStyle.secondary,
        custom_id="alert:dismiss",
    )
    async def dismiss_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.add_field(
            name="✅ Dismissed",
            value=f"Marked as a false positive by {interaction.user.mention}.",
            inline=False,
        )
        embed.color = 0x9B8F95
        try:
            await interaction.message.edit(embed=embed, view=self)
        except discord.HTTPException as exc:
            logger.warning("Could not update dismissed alert: %s", exc)

    @staticmethod
    def _alert_image_url(message: Optional[discord.Message]) -> Optional[str]:
        """The alert's own copy of the flagged image, if it kept one."""
        if message is None:
            return None
        for attachment in message.attachments:
            if (attachment.content_type or "").startswith("image/"):
                return attachment.url
        for embed in message.embeds:
            # Discord rewrites an attachment:// reference into a CDN link on the
            # way back out, so this covers the same copy from the other side.
            url = embed.image.url if embed.image else None
            if url and url.startswith("https://"):
                return url
        return None

    @discord.ui.button(
        label="Image", emoji="🖼️", style=discord.ButtonStyle.secondary,
        custom_id="alert:image", row=1,
    )
    async def image_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        """Show the flagged image, with a one-click way to blocklist it."""
        image_url = self._alert_image_url(interaction.message)
        if not image_url:
            await interaction.response.send_message(
                "❌ This alert did not keep a copy of the image.", ephemeral=True
            )
            return

        controller = getattr(self.bot, "scam_image_controller", None)
        embed = discord.Embed(
            title="🖼️ Flagged image",
            description=(
                "Add it to the scam image list and Ino will delete it on sight from now on."
                if controller
                else "Scam image detection is not available, so this cannot be blocklisted."
            ),
            color=WARN,
        )
        embed.set_image(url=image_url)

        view = None
        if controller is not None:
            try:
                from views.scam_image_view import AlertImagePreviewView
                view = AlertImagePreviewView(controller, image_url, interaction.user.id)
            except Exception as exc:
                logger.warning("Could not build the scam image preview view: %s", exc)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="History", emoji="📋", style=discord.ButtonStyle.secondary,
        custom_id="alert:history", row=1,
    )
    async def history_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        """Prior record for this user, so the decision is informed."""
        actions = self._actions()
        target_id = self._target_id_from(interaction) or self.target_id
        if actions is None or not target_id:
            await interaction.response.send_message("❌ Unavailable.", ephemeral=True)
            return

        entries = await actions.get_history(str(interaction.guild.id), str(target_id), limit=8)
        total = await actions.count_history(str(interaction.guild.id), str(target_id))

        embed = discord.Embed(
            title="📋 Moderation history",
            description=f"<@{target_id}> · **{total}** recorded action(s)",
            color=WARN if total else GOOD,
        )
        if not entries:
            embed.description += "\n\nNothing on record."
        else:
            for entry in entries:
                stamp = int(entry["created_at"].timestamp())
                embed.add_field(
                    name=f"{entry['action'].title()} · <t:{stamp}:R>",
                    value=(
                        f"by {entry.get('moderator_name', 'unknown')}\n"
                        f"{(entry.get('reason') or 'No reason')[:150]}"
                    ),
                    inline=False,
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)
