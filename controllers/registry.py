"""Command registration and slash-command syncing.

Registration used to be an ad-hoc run of if-blocks in ``setup_hook``, and every
boot then called ``tree.sync()`` twice — once per guild, once globally —
regardless of whether anything had changed. Those are rate-limited endpoints and
the global one is the slow path, so restarts paid for work that was almost
always a no-op.

This module centralises both halves:

* :func:`register_all` walks a declared list of controllers, isolating failures
  so one broken controller cannot take the rest of the command set down.
* :class:`CommandSyncer` fingerprints the command payload and only talks to
  Discord when that fingerprint changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import discord

logger = logging.getLogger(__name__)

# Written next to the code so a container restart on the same image skips the
# sync, while a rebuild (new image, empty layer) correctly forces one.
FINGERPRINT_PATH = Path(__file__).resolve().parent.parent / ".command-sync-state"


@dataclass
class Registration:
    """One controller's contribution to the command set."""

    name: str
    register: Callable[[], Any]
    required: bool = False


def register_all(registrations: list[Registration]) -> tuple[int, list[str]]:
    """Run every registration, isolating failures.

    Returns ``(succeeded, failed_names)``. A failure in a controller marked
    ``required`` is re-raised, because booting without it would leave the bot in
    a state that looks healthy but silently misses core commands.
    """
    succeeded = 0
    failed: list[str] = []

    for entry in registrations:
        try:
            entry.register()
            succeeded += 1
            logger.info("✅ Registered %s", entry.name)
        except Exception as exc:
            failed.append(entry.name)
            logger.error("❌ Failed to register %s: %s", entry.name, exc, exc_info=True)
            if entry.required:
                raise

    if failed:
        logger.warning(
            "%s/%s command groups registered; failed: %s",
            succeeded,
            len(registrations),
            ", ".join(failed),
        )
    else:
        logger.info("All %s command groups registered", succeeded)

    return succeeded, failed


class CommandSyncer:
    """Syncs the command tree to Discord, but only when it has changed."""

    def __init__(self, bot: discord.Client, guild_id: Optional[int] = None):
        self.bot = bot
        self.guild_id = guild_id

    # ------------------------------------------------------------------

    def fingerprint(self) -> str:
        """Hash everything Discord would care about in the command payload.

        Name, description, and the full parameter list, so a renamed argument or
        a changed description still triggers a sync — but an unchanged restart
        does not.
        """
        entries = []
        for command in sorted(self.bot.tree.get_commands(), key=lambda c: c.name):
            entries.append(self._describe(command))

        blob = json.dumps(entries, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _describe(self, command: Any) -> dict[str, Any]:
        described: dict[str, Any] = {
            "name": command.name,
            "description": getattr(command, "description", ""),
            "type": type(command).__name__,
        }

        # Groups nest; recurse so a change inside /inorep add is detected too.
        children = getattr(command, "commands", None)
        if children:
            described["children"] = sorted(
                (self._describe(child) for child in children),
                key=lambda d: d["name"],
            )

        parameters = getattr(command, "parameters", None)
        if parameters:
            described["params"] = [
                {
                    "name": parameter.name,
                    "description": parameter.description,
                    "required": parameter.required,
                    "type": str(parameter.type),
                }
                for parameter in parameters
            ]

        return described

    def _read_previous(self) -> Optional[str]:
        try:
            return FINGERPRINT_PATH.read_text().strip() or None
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.debug("Could not read command fingerprint: %s", exc)
            return None

    def _write(self, fingerprint: str) -> None:
        try:
            FINGERPRINT_PATH.write_text(fingerprint)
        except OSError as exc:
            # Non-fatal: we just re-sync next boot.
            logger.warning("Could not persist command fingerprint: %s", exc)

    # ------------------------------------------------------------------

    async def sync(self, force: bool = False) -> dict[str, Any]:
        """Sync if the command set changed. Returns a small report."""
        current = self.fingerprint()
        previous = self._read_previous()
        command_count = len(self.bot.tree.get_commands())

        if not force and previous == current:
            logger.info(
                "⏭️  Command set unchanged (%s commands, %s) - skipping sync",
                command_count,
                current[:12],
            )
            return {"synced": False, "reason": "unchanged", "commands": command_count}

        reason = "forced" if force else ("first run" if not previous else "changed")
        logger.info(
            "🔄 Syncing %s commands (%s: %s -> %s)",
            command_count,
            reason,
            (previous or "none")[:12],
            current[:12],
        )

        result: dict[str, Any] = {"synced": True, "reason": reason, "commands": command_count}

        # Guild sync applies instantly, so it is what members actually get.
        if self.guild_id:
            try:
                guild = discord.Object(id=self.guild_id)
                self.bot.tree.copy_global_to(guild=guild)
                synced = await self.bot.tree.sync(guild=guild)
                result["guild"] = len(synced)
                logger.info("✅ Synced %s commands to guild %s", len(synced), self.guild_id)
            except discord.HTTPException as exc:
                result["guild_error"] = str(exc)
                logger.error("❌ Guild sync failed: %s", exc)

        # The global sync takes up to an hour to propagate and is only needed so
        # the commands exist outside the home guild.
        try:
            synced_global = await self.bot.tree.sync()
            result["global"] = len(synced_global)
            logger.info("✅ Synced %s commands globally", len(synced_global))
        except discord.HTTPException as exc:
            result["global_error"] = str(exc)
            logger.error("❌ Global sync failed: %s", exc)

        # Only remember the fingerprint if at least one sync landed, so a failed
        # sync retries next boot instead of being cached as done.
        if result.get("guild") is not None or result.get("global") is not None:
            self._write(current)

        return result
