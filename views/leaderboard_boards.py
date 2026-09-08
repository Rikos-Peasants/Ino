"""Adapters that turn each data source into a :class:`Board`.

Kept apart from the view so the view stays generic and the Mongo-shaped details
live in one place. Every fetch runs its blocking work on a worker thread.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from models.rep_economy import tier_for, tier_label
from views.leaderboard_view import Board, Row

logger = logging.getLogger(__name__)

FETCH_LIMIT = 100  # Deep enough for ten pages.


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_boards(
    leaderboard_manager,
    quest_manager=None,
    art_manager=None,
    guild_id: Optional[str] = None,
) -> list[Board]:
    """Assemble every board the server currently has data for."""
    boards: list[Board] = []

    # ---- Points -------------------------------------------------------
    async def fetch_points(_sort: Optional[str]) -> list[Row]:
        entries = await leaderboard_manager.get_combined_leaderboard(
            limit=FETCH_LIMIT, quest_manager=quest_manager
        )
        return [
            Row(
                user_id=_as_int(entry.get("user_id")),
                name=entry.get("user_name", "Unknown"),
                value=entry.get("total_points", 0),
                detail=f"{entry.get('quest_points', 0):,} from quests"
                if entry.get("quest_points")
                else "",
            )
            for entry in entries
        ]

    boards.append(
        Board(
            key="points",
            label="Points",
            emoji="🏆",
            description="Chat, voice and quest points combined.",
            unit="pts",
            fetch=fetch_points,
        )
    )

    # ---- Images -------------------------------------------------------
    if hasattr(leaderboard_manager, "get_leaderboard"):

        async def fetch_images(sort: Optional[str]) -> list[Row]:
            sort_by = sort or "total_score"
            entries = await asyncio.to_thread(
                leaderboard_manager.get_leaderboard, FETCH_LIMIT, sort_by
            )
            rows = []
            for entry in entries:
                # This manager returns dicts on Mongo and tuples on the JSON
                # fallback, so normalize both. Either way the payload is always
                # (name, id, total_score, image_count) regardless of the sort.
                if isinstance(entry, dict):
                    name = entry.get("user_name", "Unknown")
                    user_id = _as_int(entry.get("user_id"))
                    score = entry.get("total_score", 0)
                    count = entry.get("image_count", 0)
                else:
                    name, user_id, score, count = (list(entry) + [0, 0, 0, 0])[:4]
                    user_id = _as_int(user_id)

                # The headline number has to be the thing we sorted by, or the
                # ordering looks broken to anyone reading it.
                average = round(score / count, 2) if count else 0
                if sort_by == "image_count":
                    value, detail = count, f"{score:,} score"
                elif sort_by == "avg_score":
                    value, detail = average, f"{count:,} images"
                else:
                    value, detail = score, f"{count:,} images"

                rows.append(Row(user_id=user_id, name=name, value=value, detail=detail))
            return rows

        async def images_footer(_rows: list[Row]) -> str:
            try:
                stats = await asyncio.to_thread(leaderboard_manager.get_stats_summary)
                return (
                    f"{stats['total_images']:,} images from "
                    f"{stats['total_users']:,} people"
                )
            except Exception:
                return ""

        boards.append(
            Board(
                key="images",
                label="Images",
                emoji="📸",
                description="Net upvotes on images posted to the gallery.",
                unit="score",
                fetch=fetch_images,
                sort_options={
                    "total_score": "Total score",
                    "avg_score": "Average score",
                    "image_count": "Image count",
                },
                units_by_sort={
                    "image_count": "images",
                    "avg_score": "avg score",
                },
                footer=images_footer,
            )
        )

    # ---- InoRep -------------------------------------------------------
    inorep = getattr(leaderboard_manager, "inorep_manager", None)
    if inorep and guild_id:

        async def fetch_rep(sort: Optional[str]) -> list[Row]:
            reverse = sort == "worst"
            entries = await inorep.get_leaderboard(
                guild_id, limit=FETCH_LIMIT, reverse=reverse
            )
            rows = []
            for entry in entries:
                rep = entry.get("rep", 0)
                tier = tier_for(rep, _as_int(entry.get("user_id")))
                rows.append(
                    Row(
                        user_id=_as_int(entry.get("user_id")),
                        name=entry.get("user_name", "Unknown"),
                        value=rep,
                        detail=tier_label(tier),
                    )
                )
            return rows

        boards.append(
            Board(
                key="inorep",
                label="InoRep",
                emoji="🎭",
                description="Standing at the shrine. Earn it with `/repways`.",
                unit="rep",
                fetch=fetch_rep,
                sort_options={"best": "Most respected", "worst": "Least respected"},
                unmedalled_sorts={"worst"},
            )
        )

    # ---- Art challenges ----------------------------------------------
    if art_manager:

        async def fetch_art(_sort: Optional[str]) -> list[Row]:
            entries = await asyncio.to_thread(
                art_manager.get_challenge_leaderboard, FETCH_LIMIT
            )
            return [
                Row(
                    user_id=_as_int(entry.get("user_id")),
                    name=entry.get("user_name", "Unknown"),
                    value=entry.get("total_points", 0),
                    detail=f"{entry.get('verified_submissions', 0)} verified",
                )
                for entry in entries
            ]

        boards.append(
            Board(
                key="art",
                label="Art challenges",
                emoji="🎨",
                description="Points from completed art challenges.",
                unit="pts",
                fetch=fetch_art,
            )
        )

    return boards
