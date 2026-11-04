"""Anyone handed the honeypot role is kicked straight away."""

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord

from config import Config
from controllers.events import EventsController
from models.mod_actions import ActionResult


def _role(role_id):
    # discord.Role hashes by id; the handler diffs role sets.
    return discord.Object(id=role_id)


def _member(roles, bot=False):
    guild = SimpleNamespace(id=Config.GUILD_ID, me=SimpleNamespace(id=1), roles=[])
    return SimpleNamespace(id=42, bot=bot, roles=roles, guild=guild)


def _controller():
    controller = EventsController.__new__(EventsController)
    mod_actions = MagicMock()
    mod_actions.kick = AsyncMock(return_value=ActionResult(True, "kick", 42))
    mod_actions.post_log = AsyncMock()
    controller.bot = SimpleNamespace(mod_actions=mod_actions)
    controller.user_safety_monitor = MagicMock(handle_member_update=AsyncMock())
    return controller, mod_actions


class HoneypotRoleTests(unittest.TestCase):
    def test_gaining_the_role_kicks_and_logs(self):
        controller, mod_actions = _controller()
        before = _member([_role(1)])
        after = _member([_role(1), _role(Config.HONEYPOT_ROLE_ID)])

        asyncio.run(controller._handle_member_update(before, after))

        mod_actions.kick.assert_awaited_once()
        mod_actions.post_log.assert_awaited_once()
        # The member is gone, so the rest of the update handling is skipped.
        controller.user_safety_monitor.handle_member_update.assert_not_awaited()

    def test_other_role_changes_are_left_alone(self):
        controller, mod_actions = _controller()
        before = _member([_role(1)])
        after = _member([_role(1), _role(2)])

        asyncio.run(controller._handle_member_update(before, after))

        mod_actions.kick.assert_not_awaited()

    def test_bots_are_never_kicked(self):
        controller, mod_actions = _controller()
        asyncio.run(controller.kick_honeypot_member(_member([], bot=True)))
        mod_actions.kick.assert_not_awaited()

    def test_refused_kick_is_not_logged(self):
        controller, mod_actions = _controller()
        mod_actions.kick.return_value = ActionResult(False, "kick", 42, "role above Ino")

        asyncio.run(controller.kick_honeypot_member(_member([])))

        mod_actions.post_log.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
