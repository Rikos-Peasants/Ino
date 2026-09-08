"""The ``/notifications`` panel.

A multi-select listing every optional DM category, pre-selected with the ones
currently on, so turning something off is deselecting it rather than hunting for
an "off" button. The locked moderation and safety categories are shown in the
embed but kept out of the menu, because offering a toggle that silently refuses
to move is worse than saying plainly that it cannot be turned off.
"""

from __future__ import annotations

import logging

import discord

from models.notification_preferences import CATEGORIES, OPTIONAL_CATEGORIES

logger = logging.getLogger(__name__)

ACCENT = 0xF2A65A
TIMEOUT = 300


def build_embed(states: dict[str, bool], saved: bool = False) -> discord.Embed:
    """Render the current state of every category."""
    embed = discord.Embed(
        title="🔔 Your DM notifications",
        description=(
            "Pick which DMs you want from Ino. Anything you deselect in the menu "
            "below stops being sent — everywhere, not just this server."
        ),
        color=ACCENT,
    )

    optional_lines = [
        f"{'🟢' if states.get(c.key, c.default) else '⚪'} {c.emoji} **{c.label}**\n"
        f"　　{c.description}"
        for c in CATEGORIES
        if c.optional
    ]
    embed.add_field(name="Optional", value="\n".join(optional_lines), inline=False)

    locked_lines = [
        f"🔒 {c.emoji} **{c.label}** — {c.description}"
        for c in CATEGORIES
        if not c.optional
    ]
    if locked_lines:
        embed.add_field(
            name="Always on",
            value="\n".join(locked_lines)
            + "\n\n*These can't be turned off — you'd have no way of knowing you "
            "were warned, or that your account looks compromised.*",
            inline=False,
        )

    embed.set_footer(
        text="Saved." if saved else "Changes save as soon as you close the menu."
    )
    return embed


class CategorySelect(discord.ui.Select):
    """One menu, pre-selected with whatever is currently enabled."""

    def __init__(self, states: dict[str, bool]):
        options = [
            discord.SelectOption(
                label=c.label,
                value=c.key,
                description=c.description[:100],
                emoji=c.emoji,
                default=states.get(c.key, c.default),
            )
            for c in OPTIONAL_CATEGORIES
        ]
        super().__init__(
            placeholder="Select the DMs you want to receive…",
            min_values=0,
            max_values=len(options),
            options=options,
            # Pinned, because _rebuild re-adds this after the buttons exist and
            # auto-placement would otherwise shuffle it below them.
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view: NotificationSettingsView = self.view  # type: ignore[assignment]
        await view.apply(interaction, set(self.values))


class NotificationSettingsView(discord.ui.View):
    """Ephemeral, single-user panel over :class:`NotificationPreferences`."""

    def __init__(self, prefs, user_id: int, states: dict[str, bool]):
        super().__init__(timeout=TIMEOUT)
        self.prefs = prefs
        self.user_id = user_id
        self.states = dict(states)
        self.add_item(CategorySelect(self.states))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "That panel isn't yours — run `/notifications` to get your own.",
                ephemeral=True,
            )
            return False
        return True

    async def apply(self, interaction: discord.Interaction, selected: set[str]):
        """Write the menu's selection back as the full optional state."""
        values = {c.key: (c.key in selected) for c in OPTIONAL_CATEGORIES}

        if not await self.prefs.set_many(self.user_id, values):
            await interaction.response.send_message(
                "I couldn't save that — preferences storage is unavailable right "
                "now. Try again in a bit.",
                ephemeral=True,
            )
            return

        self.states.update(values)
        self._rebuild()
        await interaction.response.edit_message(
            embed=build_embed(self.states, saved=True), view=self
        )

    @discord.ui.button(label="Turn all off", style=discord.ButtonStyle.secondary, row=1)
    async def all_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.apply(interaction, set())

    @discord.ui.button(label="Reset to defaults", style=discord.ButtonStyle.secondary, row=1)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.prefs.reset(self.user_id):
            await interaction.response.send_message(
                "I couldn't reset that — preferences storage is unavailable right "
                "now. Try again in a bit.",
                ephemeral=True,
            )
            return

        self.states = await self.prefs.get_all(self.user_id)
        self._rebuild()
        await interaction.response.edit_message(
            embed=build_embed(self.states, saved=True), view=self
        )

    def _rebuild(self):
        """Re-render the menu so its checkmarks match what was just saved."""
        for item in list(self.children):
            if isinstance(item, CategorySelect):
                self.remove_item(item)
        self.add_item(CategorySelect(self.states))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
