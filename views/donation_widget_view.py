"""Link buttons attached under the donation goal embed.

Every button is a URL button, which means no custom_id, no callback and no
persistence problem: they keep working across restarts and even if the bot is
offline, because Discord resolves them client side.
"""

from typing import Any, Dict

import discord

from config import Config


class DonationWidgetView(discord.ui.View):
    """Ko-fi, donations page and leaderboard links, per the goal's settings."""

    def __init__(self, goal: Dict[str, Any]):
        # Link-only views never expire and never dispatch to the bot.
        super().__init__(timeout=None)

        base = Config.WEB_BASE_URL.rstrip("/")

        if goal.get("show_kofi_button", True):
            self.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label=(goal.get("kofi_button_label") or "Donate on Ko-fi")[:80],
                url=Config.KOFI_URL,
                emoji="☕",
            ))

        if goal.get("show_page_button", True):
            self.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label=(goal.get("page_button_label") or "All supporters")[:80],
                url=f"{base}/donations",
                emoji="📃",
            ))

        if goal.get("show_board_button"):
            self.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="Leaderboard",
                url=f"{base}/leaderboard",
                emoji="🏆",
            ))

    @property
    def is_empty(self) -> bool:
        """True when every button is switched off, so callers can send None."""
        return not self.children
