"""Interactive setup wizard for donation goals.

`/setup-dono` opens a hub: an embed showing the goal's current state plus
buttons into modals and sub-views for each part of it. Everything is ephemeral
and gated to the bot owner.
"""

import logging
from typing import Optional

import discord

from config import Config

logger = logging.getLogger(__name__)

ACCENT = 0xAD1457
TIMEOUT = 900  # 15 minutes


def _short(value: Optional[str], limit: int = 60, fallback: str = "not set") -> str:
    if not value:
        return fallback
    value = str(value)
    return value if len(value) <= limit else value[: limit - 1] + "…"


async def build_status_embed(controller, goal: dict) -> discord.Embed:
    """The hub embed: everything about this goal, at a glance."""
    manager = controller.manager
    progress = await manager.get_progress(goal.get("goal_id")) if manager else {}

    embed = discord.Embed(
        title=f"Goal setup · {goal.get('title') or goal.get('name') or 'Untitled'}",
        description=_short(goal.get("description"), 300, "*No description yet.*"),
        color=ACCENT,
    )

    target = float(goal.get("target_usd") or 0)
    raised = float(progress.get("raised_usd") or 0)
    pct = float(progress.get("percent") or 0)
    filled = int(pct // 10)
    embed.add_field(
        name="Progress",
        value=(
            f"`{'█' * filled}{'░' * (10 - filled)}` {pct:.1f}%\n"
            f"**${raised:,.2f}** of **${target:,.2f}**"
            + (f"  (incl. ${float(goal.get('backfill_usd') or 0):,.2f} backfill)"
               if goal.get("backfill_usd") else "")
        ),
        inline=False,
    )

    channel_id = goal.get("channel_id")
    embed.add_field(
        name="Channel",
        value=f"<#{channel_id}>" if channel_id else "*not linked*",
        inline=True,
    )
    embed.add_field(
        name="Message",
        value="posted" if goal.get("message_id") else "*not posted*",
        inline=True,
    )
    embed.add_field(
        name="Donations",
        value=str(progress.get("donation_count", 0)),
        inline=True,
    )

    ping = goal.get("ping_role_id")
    embed.add_field(
        name="Announcements",
        value=(
            ("on" if goal.get("announce", True) else "off")
            + (f" · pings <@&{ping}>" if ping else "")
        ),
        inline=True,
    )
    embed.add_field(name="Bar heading", value=f"`{_short(goal.get('bar_title'), 30)}`", inline=True)
    embed.add_field(name="Reward", value=_short(goal.get("reward"), 60, "*not set*"), inline=True)

    embed.add_field(
        name="Ko-fi webhook",
        value=(
            f"`{Config.WEB_BASE_URL}/webhooks/kofi`\n"
            + ("Token configured." if Config.KOFI_VERIFICATION_TOKEN
               else "⚠️ `KOFI_VERIFICATION_TOKEN` unset, webhooks are rejected.")
        ),
        inline=False,
    )
    embed.set_footer(text=f"goal id {goal.get('goal_id')} · name {goal.get('name')}")
    return embed


# ======================================================================
# modals
# ======================================================================
class GoalDetailsModal(discord.ui.Modal, title="Goal details"):
    def __init__(self, hub: "DonationSetupView"):
        super().__init__(timeout=TIMEOUT)
        goal = hub.goal
        self.hub = hub
        self.f_name = discord.ui.TextInput(
            label="Short name (used in URLs)", default=goal.get("name") or "maidmaster",
            max_length=40, required=True,
        )
        self.f_title = discord.ui.TextInput(
            label="Title shown on the website",
            default=goal.get("title") or "Rayen in a maid costume",
            max_length=100, required=True,
        )
        self.f_target = discord.ui.TextInput(
            label="Target in USD", default=f"{float(goal.get('target_usd') or 600):.2f}",
            max_length=12, required=True,
        )
        self.f_reward = discord.ui.TextInput(
            label="What happens when it is hit",
            default=goal.get("reward") or "", max_length=120, required=False,
        )
        self.f_desc = discord.ui.TextInput(
            label="Description", style=discord.TextStyle.paragraph,
            default=goal.get("description") or "", max_length=600, required=False,
        )
        for f in (self.f_name, self.f_title, self.f_target, self.f_reward, self.f_desc):
            self.add_item(f)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target = float(str(self.f_target.value).replace("$", "").replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message(
                f"`{self.f_target.value}` is not a number. Target unchanged.", ephemeral=True
            )
            return
        if target <= 0:
            await interaction.response.send_message("Target must be above zero.", ephemeral=True)
            return

        await self.hub.controller.manager.update_goal(
            self.hub.goal["goal_id"],
            name=str(self.f_name.value),
            title=str(self.f_title.value),
            target_usd=target,
            reward=str(self.f_reward.value) or None,
            description=str(self.f_desc.value) or None,
        )
        await self.hub.reload_and_refresh(interaction)


class BarAppearanceModal(discord.ui.Modal, title="Progress bar appearance"):
    def __init__(self, hub: "DonationSetupView"):
        super().__init__(timeout=TIMEOUT)
        self.hub = hub
        goal = hub.goal
        self.f_title = discord.ui.TextInput(
            label="Heading drawn on the image",
            default=goal.get("bar_title") or "MAIDMASTER", max_length=40, required=True,
        )
        self.f_sub = discord.ui.TextInput(
            label="Footer line (blank = supporter count)",
            default=goal.get("bar_subtitle") or "", max_length=80, required=False,
        )
        self.add_item(self.f_title)
        self.add_item(self.f_sub)

    async def on_submit(self, interaction: discord.Interaction):
        await self.hub.controller.manager.update_goal(
            self.hub.goal["goal_id"], bar_title=str(self.f_title.value)
        )
        # A blank subtitle means "fall back to the supporter count", which
        # update_goal cannot express because it skips None.
        if str(self.f_sub.value).strip():
            await self.hub.controller.manager.update_goal(
                self.hub.goal["goal_id"], bar_subtitle=str(self.f_sub.value)
            )
        else:
            await self.hub.controller.manager.clear_goal_field(
                self.hub.goal["goal_id"], "bar_subtitle"
            )
        await self.hub.reload_and_refresh(interaction)


class BackfillModal(discord.ui.Modal, title="Backfill"):
    def __init__(self, hub: "DonationSetupView"):
        super().__init__(timeout=TIMEOUT)
        self.hub = hub
        self.f_amount = discord.ui.TextInput(
            label="USD raised before webhooks were connected",
            default=f"{float(hub.goal.get('backfill_usd') or 0):.2f}",
            max_length=12, required=True,
        )
        self.add_item(self.f_amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = float(str(self.f_amount.value).replace("$", "").replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("That is not a number.", ephemeral=True)
            return
        if amount < 0:
            await interaction.response.send_message("Backfill cannot be negative.", ephemeral=True)
            return
        await self.hub.controller.manager.update_goal(
            self.hub.goal["goal_id"], backfill_usd=amount
        )
        await self.hub.reload_and_refresh(interaction)


class NewChannelModal(discord.ui.Modal, title="Create a channel"):
    def __init__(self, hub: "DonationSetupView", with_category: bool):
        super().__init__(timeout=TIMEOUT)
        self.hub = hub
        self.with_category = with_category
        self.f_channel = discord.ui.TextInput(
            label="Channel name", default="donation-goal", max_length=90, required=True,
        )
        self.add_item(self.f_channel)
        self.f_category = None
        if with_category:
            self.f_category = discord.ui.TextInput(
                label="New category name", default="Support", max_length=90, required=True,
            )
            self.add_item(self.f_category)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        controller = self.hub.controller
        try:
            category = None
            if self.with_category and self.f_category:
                category = await guild.create_category(
                    name=str(self.f_category.value),
                    reason="Donation goal category created via /setup-dono",
                )
            channel = await controller.create_goal_channel(
                guild, str(self.f_channel.value), category
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I need **Manage Channels** to do that.", ephemeral=True
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"Discord refused: {e}", ephemeral=True)
            return

        await controller.manager.update_goal(
            self.hub.goal["goal_id"],
            channel_id=str(channel.id),
            category_id=str(category.id) if category else None,
        )
        # A brand new channel has no message in it yet.
        await controller.manager.clear_goal_field(self.hub.goal["goal_id"], "message_id")
        await self.hub.reload_and_refresh(interaction, note=f"Created {channel.mention}")


class NewGoalModal(discord.ui.Modal, title="New goal"):
    def __init__(self, hub: "DonationSetupView"):
        super().__init__(timeout=TIMEOUT)
        self.hub = hub
        self.f_title = discord.ui.TextInput(
            label="Title", placeholder="Rayen in a maid costume", max_length=100, required=True
        )
        self.f_target = discord.ui.TextInput(
            label="Target in USD", default="600.00", max_length=12, required=True
        )
        self.f_desc = discord.ui.TextInput(
            label="Description", style=discord.TextStyle.paragraph,
            max_length=600, required=False,
        )
        for f in (self.f_title, self.f_target, self.f_desc):
            self.add_item(f)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target = float(str(self.f_target.value).replace("$", "").replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("Target is not a number.", ephemeral=True)
            return
        goal = await self.hub.controller.manager.create_goal(
            name=str(self.f_title.value),
            title=str(self.f_title.value),
            target_usd=target,
            description=str(self.f_desc.value) or None,
            bar_title=str(self.f_title.value).upper()[:40],
            created_by=str(interaction.user.id),
        )
        if not goal:
            await interaction.response.send_message("Could not create the goal.", ephemeral=True)
            return
        self.hub.goal = goal
        await self.hub.reload_and_refresh(interaction, note=f"Created and activated **{goal['title']}**")


# ======================================================================
# sub-views
# ======================================================================
class ExistingChannelSelect(discord.ui.ChannelSelect):
    """Links whichever text channel the owner picks to this goal."""

    def __init__(self, hub: "DonationSetupView"):
        super().__init__(
            placeholder="Link an existing channel",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1, row=0,
        )
        self.hub = hub

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # ChannelSelect yields AppCommandChannel; resolve() gives the real one.
        picked = self.values[0]
        channel = picked.resolve() or interaction.guild.get_channel(picked.id)
        if channel is None:
            await interaction.followup.send("Could not resolve that channel.", ephemeral=True)
            return
        await self.hub.controller.manager.update_goal(
            self.hub.goal["goal_id"], channel_id=str(channel.id)
        )
        # Pointing at a different channel invalidates the old message id.
        await self.hub.controller.manager.clear_goal_field(self.hub.goal["goal_id"], "message_id")
        await self.hub.reload_and_refresh(interaction, note=f"Linked {channel.mention}")


class ChannelChoiceView(discord.ui.View):
    """Link an existing channel, or make a new one, with or without a category."""

    def __init__(self, hub: "DonationSetupView"):
        super().__init__(timeout=TIMEOUT)
        self.hub = hub
        self.add_item(ExistingChannelSelect(hub))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.hub.interaction_check(interaction)

    @discord.ui.button(label="Create channel", style=discord.ButtonStyle.primary, row=1)
    async def create_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(NewChannelModal(self.hub, with_category=False))

    @discord.ui.button(label="Create category + channel", style=discord.ButtonStyle.primary, row=1)
    async def create_both(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(NewChannelModal(self.hub, with_category=True))

    @discord.ui.button(label="Lock permissions on linked channel", style=discord.ButtonStyle.secondary, row=2)
    async def lock(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel_id = self.hub.goal.get("channel_id")
        if not channel_id:
            await interaction.response.send_message("No channel linked yet.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        channel = interaction.guild.get_channel(int(channel_id))
        if channel is None:
            await interaction.followup.send("That channel no longer exists.", ephemeral=True)
            return
        try:
            await self.hub.controller.lock_goal_channel(channel)
        except discord.Forbidden:
            await interaction.followup.send("I need **Manage Roles** on that channel.", ephemeral=True)
            return
        await self.hub.reload_and_refresh(
            interaction, note=f"{channel.mention} is now read-only for everyone but admins"
        )

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.hub.reload_and_refresh(interaction)


class PingRoleSelect(discord.ui.RoleSelect):
    def __init__(self, hub: "DonationSetupView"):
        super().__init__(
            placeholder="Role to ping on each donation",
            min_values=1, max_values=1, row=0,
        )
        self.hub = hub

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        role = self.values[0]
        await self.hub.controller.manager.update_goal(
            self.hub.goal["goal_id"], ping_role_id=str(role.id)
        )
        await self.hub.reload_and_refresh(interaction, note=f"Pinging {role.mention}")


class NotificationsView(discord.ui.View):
    """Announcement toggle plus the role pinged on each donation."""

    def __init__(self, hub: "DonationSetupView"):
        super().__init__(timeout=TIMEOUT)
        self.hub = hub
        self.add_item(PingRoleSelect(hub))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.hub.interaction_check(interaction)

    @discord.ui.button(label="Toggle announcements", style=discord.ButtonStyle.primary, row=1)
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        new_value = not self.hub.goal.get("announce", True)
        await self.hub.controller.manager.update_goal(
            self.hub.goal["goal_id"], announce=new_value
        )
        await self.hub.reload_and_refresh(
            interaction, note=f"Announcements {'on' if new_value else 'off'}"
        )

    @discord.ui.button(label="Clear ping role", style=discord.ButtonStyle.secondary, row=1)
    async def clear_ping(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.hub.controller.manager.clear_goal_field(
            self.hub.goal["goal_id"], "ping_role_id"
        )
        await self.hub.reload_and_refresh(interaction, note="Ping role cleared")

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.hub.reload_and_refresh(interaction)


class GoalPickSelect(discord.ui.Select):
    def __init__(self, hub: "DonationSetupView", goals: list):
        options = [
            discord.SelectOption(
                label=_short(g.get("title") or g.get("name"), 90),
                value=g["goal_id"],
                description=f"${float(g.get('target_usd') or 0):,.0f} target",
                default=bool(g.get("is_active")),
            )
            for g in goals[:25]
        ]
        super().__init__(placeholder="Switch active goal", options=options, row=0)
        self.hub = hub

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        goal_id = self.values[0]
        await self.hub.controller.manager.activate_goal(goal_id)
        goal = await self.hub.controller.manager.get_goal(goal_id)
        if goal:
            self.hub.goal = goal
        await self.hub.reload_and_refresh(interaction, note="Active goal switched")


class GoalSwitchView(discord.ui.View):
    """Pick which stored goal is the live one, or start a new one."""

    def __init__(self, hub: "DonationSetupView", goals: list):
        super().__init__(timeout=TIMEOUT)
        self.hub = hub
        if goals:
            self.add_item(GoalPickSelect(hub, goals))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.hub.interaction_check(interaction)

    @discord.ui.button(label="New goal", style=discord.ButtonStyle.success, row=1)
    async def new_goal(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(NewGoalModal(self.hub))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.hub.reload_and_refresh(interaction)


# ======================================================================
# the hub
# ======================================================================
class DonationSetupView(discord.ui.View):
    """Top-level setup hub. Every button either opens a modal or swaps views."""

    def __init__(self, controller, goal: dict, owner_id: int):
        super().__init__(timeout=TIMEOUT)
        self.controller = controller
        self.goal = goal
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "This setup panel belongs to someone else.", ephemeral=True
        )
        return False

    async def reload_and_refresh(self, interaction: discord.Interaction, note: Optional[str] = None):
        """Re-read the goal from the database and redraw the hub."""
        fresh = await self.controller.manager.get_goal(self.goal["goal_id"])
        if fresh:
            self.goal = fresh
        embed = await build_status_embed(self.controller, self.goal)
        if note:
            embed.add_field(name="​", value=f"✅ {note}", inline=False)

        view = DonationSetupView(self.controller, self.goal, self.owner_id)
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.edit_message(embed=embed, view=view)
        except discord.HTTPException as e:
            logger.error(f"Could not refresh donation setup hub: {e}")

    # ------------------------------------------------------------------
    @discord.ui.button(label="Goal details", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def details(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(GoalDetailsModal(self))

    @discord.ui.button(label="Channel", emoji="📢", style=discord.ButtonStyle.primary, row=0)
    async def channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = await build_status_embed(self.controller, self.goal)
        embed.description = (
            "Link a channel that already exists, or have me create one. "
            "Either way everyone can read it and only admins can post."
        )
        await interaction.response.edit_message(embed=embed, view=ChannelChoiceView(self))

    @discord.ui.button(label="Notifications", emoji="🔔", style=discord.ButtonStyle.primary, row=0)
    async def notifications(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = await build_status_embed(self.controller, self.goal)
        await interaction.response.edit_message(embed=embed, view=NotificationsView(self))

    @discord.ui.button(label="Bar look", emoji="🎨", style=discord.ButtonStyle.secondary, row=1)
    async def appearance(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(BarAppearanceModal(self))

    @discord.ui.button(label="Backfill", emoji="💰", style=discord.ButtonStyle.secondary, row=1)
    async def backfill(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(BackfillModal(self))

    @discord.ui.button(label="Switch goal", emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def switch(self, interaction: discord.Interaction, _: discord.ui.Button):
        goals = await self.controller.manager.list_goals()
        embed = await build_status_embed(self.controller, self.goal)
        await interaction.response.edit_message(embed=embed, view=GoalSwitchView(self, goals))

    @discord.ui.button(label="Post / update bar", emoji="✅", style=discord.ButtonStyle.success, row=2)
    async def deploy(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self.goal.get("channel_id"):
            await interaction.response.send_message(
                "Link or create a channel first.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        ok = await self.controller.refresh_progress_message(goal_id=self.goal["goal_id"])
        await self.reload_and_refresh(
            interaction,
            note="Progress bar posted" if ok else "⚠️ Could not post, check my permissions",
        )

    @discord.ui.button(label="Preview bar", emoji="👁", style=discord.ButtonStyle.secondary, row=2)
    async def preview(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        file = await self.controller.build_bar_file(self.goal)
        if not file:
            await interaction.followup.send("Could not render the bar.", ephemeral=True)
            return
        await interaction.followup.send(
            "This is what gets posted:", file=file, ephemeral=True
        )
