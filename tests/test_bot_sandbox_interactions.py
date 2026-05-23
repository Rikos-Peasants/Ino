import asyncio
import os
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DISCORD_TOKEN"] = "dummy"
os.environ["GUILD_ID"] = "123456789012345678"
os.environ["MONGO_URI"] = "mongodb://example.invalid/ino"
os.environ["INO_SANDBOX_MODE"] = "true"
os.environ["INO_SANDBOX_CHANNEL_IDS"] = "111111111111111111,222222222222222222"
os.environ.pop("BANNED_ROLE_ID", None)
os.environ.pop("RESTRICTED_ROLE_ID", None)

from bot import RikoBot
from config import Config


class FakeCommandContext:
    def __init__(self, command_name, channel_id):
        self.command = SimpleNamespace(name=command_name) if command_name else None
        self.channel = SimpleNamespace(id=channel_id) if channel_id is not None else None
        self.sent = []

    async def send(self, content):
        self.sent.append(content)


class FakeResponse:
    def __init__(self):
        self.sent = []
        self._done = False

    def is_done(self):
        return self._done

    async def send_message(self, content, ephemeral=False):
        self.sent.append((content, ephemeral))
        self._done = True


def fake_interaction(guild_id, channel_id):
    guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
    channel = SimpleNamespace(id=channel_id) if channel_id is not None else None
    return SimpleNamespace(guild=guild, channel=channel, response=FakeResponse())


async def run_checks():
    bot = RikoBot.__new__(RikoBot)

    allowed = fake_interaction(Config.GUILD_ID, 111111111111111111)
    assert await RikoBot._allow_sandbox_interaction(bot, allowed, notify=True) is True
    assert allowed.response.sent == []

    outside_channel = fake_interaction(Config.GUILD_ID, 333333333333333333)
    assert await RikoBot._allow_sandbox_interaction(bot, outside_channel, notify=True) is False
    assert outside_channel.response.sent == [
        ("This bot is only available in the approved sandbox channels.", True)
    ]

    wrong_guild = fake_interaction(999999999999999999, 111111111111111111)
    assert await RikoBot._tree_interaction_check(bot, wrong_guild) is False
    assert wrong_guild.response.sent == [
        ("This bot is only available in the approved server.", True)
    ]

    dm = fake_interaction(None, None)
    assert await RikoBot._allow_sandbox_interaction(bot, dm, notify=True) is False
    assert dm.response.sent == [
        ("This bot is only available in the approved server.", True)
    ]

    public_context = FakeCommandContext("leaderboard", 111111111111111111)
    assert await RikoBot._allow_sandbox_command_context(bot, public_context) is True
    assert public_context.sent == []

    admin_context = FakeCommandContext("warn", 111111111111111111)
    assert await RikoBot._allow_sandbox_command_context(bot, admin_context) is False
    assert admin_context.sent == ["Sandbox mode only allows public persona/community commands."]

    unknown_context = FakeCommandContext("totally_unknown", 111111111111111111)
    assert await RikoBot._allow_sandbox_command_context(bot, unknown_context) is False
    assert unknown_context.sent == ["Sandbox mode only allows public persona/community commands."]

    wrong_channel_context = FakeCommandContext("leaderboard", 333333333333333333)
    assert await RikoBot._allow_sandbox_command_context(bot, wrong_channel_context) is False
    assert wrong_channel_context.sent == [
        "This bot is only available in the approved sandbox channels."
    ]


def main():
    asyncio.run(run_checks())
    print("bot sandbox interaction test passed")


if __name__ == "__main__":
    main()
