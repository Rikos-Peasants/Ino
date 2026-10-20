"""Turn raw InoRep history into a readable, grouped timeline.

Every rep change is logged to ``inorep_history`` one row at a time, so a busy
chatter's history is mostly "Chatting in #general" fifty times over. This module
folds *consecutive* entries of the same kind into one row ("Chatting x50"),
while keeping the order intact: chatting, then an image spam penalty, then
more chatting shows up as three rows, not two.

Runs also break at UTC midnight, so a group never hides how many days it spans.

Pure functions only: both ``/inorep changes`` and the website's ``/me/changes``
page render from :func:`group_changes`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

SYSTEM_ACTOR_ID = "0"

# Distinct details kept per group, e.g. which channels or who thanked you.
MAX_DETAILS = 4


@dataclass(frozen=True)
class ChangeKind:
    key: str
    label: str
    emoji: str


# Checked in order, first match wins. Each pattern may capture a "detail"
# group shown next to the label (channel, quest name, who thanked you...).
_RULES: tuple[tuple[re.Pattern[str], ChangeKind], ...] = tuple(
    (re.compile(pattern), ChangeKind(key, label, emoji))
    for pattern, key, label, emoji in (
        # Must come before the generic chatting rule.
        (r"^Chatting in image-only channel", "image_channel_chat", "Chatting in an image-only channel", "🚫"),
        (r"^Chatting in (?P<detail>#.+)$", "chat", "Chatting", "💬"),
        (r"^Someone reacted to your post", "reaction", "Reactions on your posts", "⭐"),
        (r"^Voice chat\b", "voice", "Voice chat", "🎙️"),
        (r"^Daily check-in(?: \((?P<detail>day \d+) streak\))?", "daily", "Daily check-in", "⛩️"),
        (r"^Tried to thank themselves", "self_thank", "Tried to thank yourself", "🙃"),
        (r"^Thanked by (?P<detail>[^:]+)", "thanked", "Thanked", "🍡"),
        (r"^(?:Shared an image|Posted an image in image channel)", "image", "Image posts", "🖼️"),
        (r"^Completed quest: (?P<detail>.+)$", "quest", "Quests completed", "📜"),
        (r"^Completed a quest", "quest", "Quests completed", "📜"),
        (r"^Completed an art challenge", "art", "Art challenges", "🎨"),
        (r"^Repeated same-message spam", "spam", "Message spam", "🔁"),
        (r"^Ping spam", "ping_spam", "Ping spam", "📣"),
        (
            r"^(?:Severe violation detected|Harmful content flagged|Content flagged for review)",
            "flagged",
            "Content flagged by moderation",
            "🛡️",
        ),
        (r"^Said something mean about Ino", "mean", "Said something mean about Ino", "💢"),
        (r"^Said something nice about Ino", "nice", "Said something nice about Ino", "💖"),
    )
)


@dataclass
class ChangeGroup:
    """A run of consecutive history entries of the same kind."""

    key: str
    label: str
    emoji: str
    count: int = 0
    total: int = 0
    # Newest-first input, so `newest` is set by the first entry and `oldest`
    # keeps moving back as the run grows.
    newest: Optional[datetime] = None
    oldest: Optional[datetime] = None
    rep_after: Optional[int] = None
    staff: Optional[str] = None
    details: list[str] = field(default_factory=list)
    more_details: int = 0

    def add_detail(self, detail: Optional[str]) -> None:
        if not detail or detail in self.details:
            return
        if len(self.details) < MAX_DETAILS:
            self.details.append(detail)
        else:
            self.more_details += 1

    @property
    def detail_text(self) -> str:
        text = ", ".join(self.details)
        if self.more_details:
            text += f" +{self.more_details} more"
        return text

    @property
    def signed_total(self) -> str:
        return f"+{self.total:,}" if self.total > 0 else f"{self.total:,}"


def _as_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    # pymongo hands back naive datetimes that are already UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def classify(entry: dict[str, Any]) -> tuple[str, ChangeKind, Optional[str], Optional[str]]:
    """Return ``(group_key, kind, detail, staff_name)`` for one history entry."""
    reason = str(entry.get("reason") or "").strip()
    moderator_id = str(entry.get("moderator_id") or SYSTEM_ACTOR_ID)

    # Anything a person did by hand stays its own thing: only merge repeats of
    # the same reason from the same moderator.
    if moderator_id != SYSTEM_ACTOR_ID:
        amount = int(entry.get("amount") or 0)
        staff = str(entry.get("moderator_name") or "staff")
        kind = ChangeKind(
            key="staff",
            label=reason or ("Staff reward" if amount >= 0 else "Staff penalty"),
            emoji="🔨" if amount < 0 else "🎁",
        )
        sign = "+" if amount >= 0 else "-"
        return f"staff:{moderator_id}:{sign}:{reason}", kind, None, staff

    for pattern, kind in _RULES:
        match = pattern.match(reason)
        if match:
            detail = match.groupdict().get("detail")
            return kind.key, kind, detail.strip() if detail else None, None

    fallback = ChangeKind(key="other", label=reason or "Unlabelled change", emoji="•")
    return f"other:{reason}", fallback, None, None


def group_changes(entries: Iterable[dict[str, Any]]) -> list[ChangeGroup]:
    """Fold newest-first history into runs of the same kind.

    Only *adjacent* entries merge, and never across a UTC day boundary, so the
    timeline keeps its order: chat, chat, spam, chat becomes three groups.
    """
    groups: list[ChangeGroup] = []
    current: Optional[ChangeGroup] = None
    current_key: Optional[str] = None
    current_day = None

    for entry in entries:
        key, kind, detail, staff = classify(entry)
        when = _as_utc(entry.get("created_at"))
        day = when.date() if when else None

        if current is None or key != current_key or day != current_day:
            current = ChangeGroup(key=kind.key, label=kind.label, emoji=kind.emoji, staff=staff)
            current.newest = when
            new_rep = entry.get("new_rep")
            current.rep_after = int(new_rep) if new_rep is not None else None
            groups.append(current)
            current_key, current_day = key, day

        current.count += 1
        current.total += int(entry.get("amount") or 0)
        current.oldest = when or current.oldest
        current.add_detail(detail)

    return groups


def summarize(groups: Iterable[ChangeGroup]) -> tuple[int, int]:
    """Total ``(gained, lost)`` across groups; ``lost`` is negative or zero."""
    gained = lost = 0
    for group in groups:
        if group.total >= 0:
            gained += group.total
        else:
            lost += group.total
    return gained, lost
