"""The unified, paginated leaderboard.

Replaces the old four-button view, which had a copy of the same handler per
board, no pagination, and locked every control to the person who ran the
command. Here each board is described once as a :class:`Board`, the view renders
any of them the same way, and anyone can page through a public scoreboard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import discord

from models.cache import leaderboard_cache

logger = logging.getLogger(__name__)

PAGE_SIZE = 10
ACCENT = 0xF2A65A
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


@dataclass
class Row:
    """One normalized leaderboard entry."""

    user_id: Optional[int]
    name: str
    value: int
    detail: str = ""


@dataclass
class Board:
    """A leaderboard source, normalized so the view can render it generically."""

    key: str
    label: str
    emoji: str
    description: str
    unit: str
    # Called as fetch(sort_key) -> list[Row], already sorted best-first.
    # sort_key is None unless the board declares sort_options.
    fetch: Callable[[Optional[str]], Awaitable[list[Row]]]
    sort_options: dict[str, str] = field(default_factory=dict)
    footer: Optional[Callable[[list[Row]], Awaitable[str]]] = None
    # Overrides `unit` per sort, for boards whose headline number changes with
    # the sort (images by score vs. by count).
    units_by_sort: dict[str, str] = field(default_factory=dict)
    # Sorts where topping the list is not an achievement, so no medals.
    unmedalled_sorts: set[str] = field(default_factory=set)

    def unit_for(self, sort_key: Optional[str]) -> str:
        return self.units_by_sort.get(sort_key or "", self.unit)


def _medal(rank: int) -> str:
    return MEDALS.get(rank, f"`#{rank:>2}`")


class LeaderboardView(discord.ui.View):
    """Board switcher + pagination + jump-to-me, over any set of boards."""

    def __init__(
        self,
        boards: list[Board],
        *,
        invoker: discord.abc.User,
        initial_key: str = "points",
        timeout: float = 300.0,
    ):
        super().__init__(timeout=timeout)
        self.boards = {board.key: board for board in boards}
        self.order = [board.key for board in boards]
        self.invoker = invoker
        self.current_key = initial_key if initial_key in self.boards else self.order[0]
        self.page = 0
        self.sort_key: Optional[str] = None
        self.message: Optional[discord.Message] = None
        self._rows: list[Row] = []

        self._board_select = BoardSelect(self)
        self.add_item(self._board_select)
        self._sort_select: Optional[SortSelect] = None
        self._rebuild_sort_select()

    # ------------------------------------------------------------------

    @property
    def board(self) -> Board:
        return self.boards[self.current_key]

    @property
    def page_count(self) -> int:
        return max(1, -(-len(self._rows) // PAGE_SIZE))

    async def load(self, force: bool = False) -> None:
        """Fetch the current board, through the shared short-lived cache."""
        cache_key = f"lb:{self.current_key}:{self.sort_key or 'default'}"
        if force:
            leaderboard_cache.invalidate(cache_key)
        board = self.board
        sort_key = self.sort_key
        self._rows = await leaderboard_cache.get_or_compute(
            cache_key, lambda: board.fetch(sort_key)
        )
        self.page = max(0, min(self.page, self.page_count - 1))

    async def build_embed(self) -> discord.Embed:
        board = self.board
        embed = discord.Embed(
            title=f"{board.emoji} {board.label}",
            description=board.description,
            color=ACCENT,
        )

        if not self._rows:
            embed.description = f"{board.description}\n\nNothing here yet. Be the first."
            return embed

        unit = board.unit_for(self.sort_key)
        medalled = self.sort_key not in board.unmedalled_sorts
        start = self.page * PAGE_SIZE
        lines = []
        for offset, row in enumerate(self._rows[start : start + PAGE_SIZE]):
            rank = start + offset + 1
            name = discord.utils.escape_markdown(row.name)[:28]
            # Highlight whoever opened the leaderboard so they can find themselves.
            if row.user_id and row.user_id == self.invoker.id:
                name = f"__**{name}**__"
            prefix = _medal(rank) if medalled else f"`#{rank:>2}`"
            line = f"{prefix} {name} — **{row.value:,}** {unit}"
            if row.detail:
                line += f"  ·  {row.detail}"
            lines.append(line)

        embed.add_field(name="​", value="\n".join(lines), inline=False)

        # Where the viewer sits, even when they are off this page.
        own_rank = next(
            (i + 1 for i, row in enumerate(self._rows) if row.user_id == self.invoker.id),
            None,
        )
        if own_rank:
            own = self._rows[own_rank - 1]
            embed.add_field(
                name="Your position",
                value=f"#{own_rank} of {len(self._rows):,} — **{own.value:,}** {unit}",
                inline=False,
            )

        footer = f"Page {self.page + 1}/{self.page_count}"
        if board.footer:
            try:
                extra = await board.footer(self._rows)
                if extra:
                    footer += f" • {extra}"
            except Exception as exc:
                logger.debug("Board footer failed: %s", exc)
        embed.set_footer(text=footer)
        return embed

    # ------------------------------------------------------------------

    def _rebuild_sort_select(self) -> None:
        """Show the sort dropdown only for boards that offer sorting."""
        if self._sort_select is not None:
            self.remove_item(self._sort_select)
            self._sort_select = None

        options = self.board.sort_options
        if options:
            self._sort_select = SortSelect(self, options)
            self.add_item(self._sort_select)

    def _sync_buttons(self) -> None:
        multipage = self.page_count > 1
        self.first_page.disabled = not multipage or self.page == 0
        self.prev_page.disabled = not multipage or self.page == 0
        self.next_page.disabled = not multipage or self.page >= self.page_count - 1
        self.last_page.disabled = not multipage or self.page >= self.page_count - 1

    async def refresh(self, interaction: discord.Interaction, force: bool = False) -> None:
        """Reload, re-render, and edit the message in place."""
        await self.load(force=force)
        self._sync_buttons()
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=2)
    async def first_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.page = 0
        await self.refresh(interaction)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, row=2)
    async def prev_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await self.refresh(interaction)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, row=2)
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.page = min(self.page_count - 1, self.page + 1)
        await self.refresh(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=2)
    async def last_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        self.page = self.page_count - 1
        await self.refresh(interaction)

    @discord.ui.button(label="Find me", emoji="📍", style=discord.ButtonStyle.primary, row=3)
    async def jump_to_me(self, interaction: discord.Interaction, _: discord.ui.Button):
        """Page straight to whoever pressed the button."""
        await self.load()
        index = next(
            (i for i, row in enumerate(self._rows) if row.user_id == interaction.user.id),
            None,
        )
        if index is None:
            await interaction.response.send_message(
                f"You are not on the {self.board.label} board yet.", ephemeral=True
            )
            return

        self.page = index // PAGE_SIZE
        # Render for the presser, so their row is the highlighted one.
        previous_invoker, self.invoker = self.invoker, interaction.user
        try:
            await self.refresh(interaction)
        finally:
            self.invoker = previous_invoker

    @discord.ui.button(emoji="🔄", style=discord.ButtonStyle.secondary, row=3)
    async def refresh_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.refresh(interaction, force=True)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        logger.error("Leaderboard interaction failed on %s: %s", item, error)
        message = "❌ Something went wrong loading that board."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class BoardSelect(discord.ui.Select):
    """Switch between leaderboards."""

    def __init__(self, view: LeaderboardView):
        self._parent = view
        options = [
            discord.SelectOption(
                label=view.boards[key].label,
                value=key,
                emoji=view.boards[key].emoji,
                description=view.boards[key].description[:100],
                default=key == view.current_key,
            )
            for key in view.order
        ]
        super().__init__(placeholder="Choose a leaderboard…", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self._parent.current_key = self.values[0]
        self._parent.page = 0
        self._parent.sort_key = None
        for option in self.options:
            option.default = option.value == self.values[0]
        self._parent._rebuild_sort_select()
        await self._parent.refresh(interaction)


class SortSelect(discord.ui.Select):
    """Change the sort of a board that supports it."""

    def __init__(self, view: LeaderboardView, sort_options: dict[str, str]):
        self._parent = view
        current = view.sort_key or next(iter(sort_options))
        options = [
            discord.SelectOption(label=label, value=value, default=value == current)
            for value, label in sort_options.items()
        ]
        super().__init__(placeholder="Sort by…", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        self._parent.sort_key = self.values[0]
        self._parent.page = 0
        for option in self.options:
            option.default = option.value == self.values[0]
        await self._parent.refresh(interaction)
