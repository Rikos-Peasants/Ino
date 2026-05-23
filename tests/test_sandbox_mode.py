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
os.environ["BANNED_ROLE_ID"] = ""
os.environ["RESTRICTED_ROLE_ID"] = ""

from config import Config
from config import get_int_env
from controllers.security import CommandSecurity, SecurityLevel


class FakeBot:
    async def is_owner(self, user):
        return True


def fake_context(channel_id):
    permissions = SimpleNamespace(administrator=True, manage_guild=True)
    author = SimpleNamespace(guild_permissions=permissions, roles=[])
    channel = SimpleNamespace(id=channel_id)
    return SimpleNamespace(author=author, channel=channel, guild=object(), bot=FakeBot())


def main():
    assert Config.SANDBOX_MODE is True
    assert Config.BANNED_ROLE_ID is None
    assert Config.RESTRICTED_ROLE_ID is None
    os.environ["OPTIONAL_EMPTY_ROLE_ID"] = "   "
    assert get_int_env("OPTIONAL_EMPTY_ROLE_ID", None) is None
    assert Config.is_sandbox_channel_allowed(111111111111111111) is True
    assert Config.is_sandbox_channel_allowed(333333333333333333) is False

    original_channels = Config.SANDBOX_CHANNEL_IDS
    try:
        Config.SANDBOX_CHANNEL_IDS = []
        assert Config.is_sandbox_channel_allowed(111111111111111111) is False
        try:
            Config.validate()
        except ValueError as error:
            assert "INO_SANDBOX_CHANNEL_IDS" in str(error)
        else:
            raise AssertionError("sandbox mode must require INO_SANDBOX_CHANNEL_IDS")
    finally:
        Config.SANDBOX_CHANNEL_IDS = original_channels

    public_allowed, _ = asyncio.run(
        CommandSecurity.check_permissions(fake_context(111111111111111111), SecurityLevel.PUBLIC)
    )
    assert public_allowed is True

    admin_allowed, admin_error = asyncio.run(
        CommandSecurity.check_permissions(fake_context(111111111111111111), SecurityLevel.ADMIN)
    )
    assert admin_allowed is False
    assert "Sandbox mode" in admin_error

    outside_allowed, outside_error = asyncio.run(
        CommandSecurity.check_permissions(fake_context(333333333333333333), SecurityLevel.PUBLIC)
    )
    assert outside_allowed is False
    assert "sandbox channels" in outside_error

    print("sandbox mode test passed")


if __name__ == "__main__":
    main()
