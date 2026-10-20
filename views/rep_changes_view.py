"""Paginated embed for ``/inorep changes``."""

from __future__ import annotations

from typing import Optional

import discord

from models.inorep_status import get_inorep_tier
from models.rep_changes import ChangeGroup, summarize

GROUPS_PER_PAGE = 10
GAIN = 0x77DD77
LOSS = 0xE05252


def _timestamp(group: ChangeGroup) -> str:
    if not group.newest:
        return ""
    newest = int(group.newest.timestamp())
    oldest = int(group.oldest.timestamp()) if group.oldest else newest
    # A run of one, or one that all landed within a few minutes, gets a single
    # relative stamp. Longer runs show the span they covered.
    if newest - oldest < 300:
        return f"<t:{newest}:R>"
    return f"<t:{oldest}:t>–<t:{newest}:t> <t:{newest}:R>"


def format_group(group: ChangeGroup) -> str:
    """Two lines per group: what happened, then when and where it left you."""
    count = f" ×{group.count}" if group.count > 1 else ""
    head = f"`{group.signed_total:>6}` {group.emoji} **{group.label}**{count}"
    if group.detail_text:
        head += f" · {group.detail_text}"
    if group.staff:
        head += f" · by {group.staff}"

    tail = [_timestamp(group)]
    if group.rep_after is not None:
        tail.append(f"→ {group.rep_after:,}")
    return f"{head}\n-# {' '.join(part for part in tail if part)}"


class RepChangesView(discord.ui.View):
    """Prev/next through grouped rep changes. Only the invoker can page."""

    def __init__(
        self,
        target: discord.abc.User,
        viewer_id: int,
        groups: list[ChangeGroup],
        raw_count: int,
        scan_limit: int,
        current_rep: int,
    ):
        super().__init__(timeout=300)
        self.target = target
        self.viewer_id = viewer_id
        self.groups = groups
        self.raw_count = raw_count
        self.scan_limit = scan_limit
        self.current_rep = current_rep
        self.page = 0
        self.pages = max(1, -(-len(groups) // GROUPS_PER_PAGE))
        self.message: Optional[discord.Message] = None
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= self.pages - 1
        if self.pages <= 1:
            self.clear_items()

    def build_embed(self) -> discord.Embed:
        tier = get_inorep_tier(self.current_rep, self.target.id)
        embed = discord.Embed(
            title="📜 InoRep changes",
            color=int(tier.get("color", 0xF2A65A)),
        )
        embed.set_author(name=self.target.display_name, icon_url=self.target.display_avatar.url)

        if not self.groups:
            embed.description = (
                "Nothing on record yet. Chat, `/daily`, or get thanked and it will show up here."
            )
            return embed

        start = self.page * GROUPS_PER_PAGE
        shown = self.groups[start:start + GROUPS_PER_PAGE]
        gained, lost = summarize(self.groups)

        lines = [
            f"Now at **{self.current_rep:,}** · {tier.get('status', '')}",
            f"Across these changes: **+{gained:,}** earned, **{lost:,}** lost",
            "",
        ]
        lines.extend(format_group(group) for group in shown)
        embed.description = "\n".join(lines)[:4096]

        footer = f"Page {self.page + 1}/{self.pages} · {self.raw_count:,} changes, grouped"
        if self.raw_count >= self.scan_limit:
            footer += f" (most recent {self.scan_limit:,})"
        embed.set_footer(text=footer)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.viewer_id:
            return True
        await interaction.response.send_message(
            "Run `/inorep changes` to see your own.", ephemeral=True
        )
        return False

    @discord.ui.button(label="Newer", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Older", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.pages - 1, self.page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self) -> None:
        if not self.message:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass
