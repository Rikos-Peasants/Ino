"""The donation goal note under command replies.

It must stay out of the way: never for supporters, never outside the guild,
never on the donation commands themselves, and gone the moment staff turn it
off with /modconfig.
"""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Config
from controllers.donation_nudge import DonationNudge

DONOR_ROLE_ID = 4242


def run(coro):
    return asyncio.run(coro)


class FakeModeration:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.reads = 0

    async def get_moderation_setting(self, guild_id, name, default=None):
        self.reads += 1
        return self.enabled


class FakeDonations:
    def __init__(self, raised=150.0, target=600.0):
        self.goal = {"goal_id": "g1", "title": "Maid goal", "donor_role_id": DONOR_ROLE_ID}
        self.raised, self.target = raised, target

    async def get_active_goal(self):
        return self.goal

    async def get_progress(self, goal_id=None):
        percent = self.raised / self.target * 100
        return {
            "raised_usd": self.raised, "goal_usd": self.target,
            "percent": min(percent, 100.0), "percent_raw": percent,
            "donation_count": 3, "goal": self.goal,
        }


def make_nudge(enabled=True, **progress):
    moderation = FakeModeration(enabled)
    bot = SimpleNamespace(
        leaderboard_manager=SimpleNamespace(moderation_manager=moderation),
        donation_manager=FakeDonations(**progress),
    )
    return DonationNudge(bot), moderation


def member(*role_ids):
    return SimpleNamespace(
        bot=False, get_role=lambda rid: object() if rid in role_ids else None
    )


GUILD = SimpleNamespace(id=Config.GUILD_ID)


def test_note_has_goal_subtext_and_kofi_button():
    nudge, _ = make_nudge()
    content, view = run(nudge.build(member(), GUILD, "rank"))
    assert content.startswith("-# ")
    assert "Maid goal" in content and "$150.00 of $600" in content
    [button] = view.children
    assert button.url == Config.KOFI_URL


def test_supporters_get_nothing():
    nudge, _ = make_nudge()
    assert run(nudge.build(member(DONOR_ROLE_ID), GUILD, "rank")) is None


def test_other_guilds_and_donation_commands_are_skipped():
    nudge, _ = make_nudge()
    assert run(nudge.build(member(), SimpleNamespace(id=1), "rank")) is None
    assert run(nudge.build(member(), GUILD, "dono status")) is None
    assert run(nudge.build(member(), GUILD, "setup-dono")) is None


def test_modconfig_toggle_applies_after_invalidate():
    nudge, moderation = make_nudge()
    assert run(nudge.build(member(), GUILD, "rank")) is not None

    moderation.enabled = False
    nudge.invalidate()
    assert run(nudge.build(member(), GUILD, "rank")) is None


def test_toggle_is_cached_between_commands():
    nudge, moderation = make_nudge()
    run(nudge.build(member(), GUILD, "rank"))
    run(nudge.build(member(), GUILD, "rank"))
    assert moderation.reads == 1


def test_reached_goal_thanks_instead_of_pitching():
    nudge, _ = make_nudge(raised=700.0)
    content, _ = run(nudge.build(member(), GUILD, "rank"))
    assert "reached its goal" in content
