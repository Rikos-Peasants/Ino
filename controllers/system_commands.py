"""Status, help, and diagnostics: /ping, /help, /about, /sync.

Also installs the app-command error handler. Slash commands previously had no
``tree.on_error``, so anything that raised surfaced to members as Discord's
generic "the application did not respond" with no explanation and nothing
actionable in the logs beyond a traceback.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from controllers.security import owner_command, public_command

try:
    import psutil
except ImportError:  # Optional; the memory field is simply omitted without it.
    psutil = None

logger = logging.getLogger(__name__)

ACCENT = 0xF2A65A
GOOD = 0x77DD77
WARN = 0xE8A33D
BAD = 0xE05252

# Latency thresholds in milliseconds, worst-first.
LATENCY_BANDS = ((400, "🔴", BAD), (200, "🟠", WARN), (0, "🟢", GOOD))


def _band(ms: Optional[float]) -> tuple[str, int]:
    """Return (emoji, colour) for a latency reading."""
    if ms is None:
        return "⚫", BAD
    for threshold, emoji, color in LATENCY_BANDS:
        if ms >= threshold:
            return emoji, color
    return "🟢", GOOD


def _format_ms(ms: Optional[float]) -> str:
    if ms is None:
        return "unreachable"
    if ms < 1:
        return "<1 ms"
    return f"{ms:.0f} ms"


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


class SystemCommandsController:
    """Registers status and help commands, and the global error handlers."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.started_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Probes
    # ------------------------------------------------------------------

    async def _probe_database(self) -> Optional[float]:
        """Round-trip time of a real Mongo command, in milliseconds."""
        manager = getattr(self.bot, "leaderboard_manager", None)
        client = getattr(manager, "client", None)
        if client is None:
            return None

        def _ping():
            client.admin.command("ping")

        try:
            start = time.perf_counter()
            await asyncio.wait_for(asyncio.to_thread(_ping), timeout=5.0)
            return (time.perf_counter() - start) * 1000
        except Exception as exc:
            logger.warning("Database probe failed: %s", exc)
            return None

    def _ai_status(self) -> str:
        """One line describing which AI providers are usable right now."""
        monitor = getattr(self.bot, "youtube_monitor", None)
        router = getattr(monitor, "ai_router", None)
        if router is None:
            return "not configured"

        parts = []
        parts.append("Gemini ✅" if router._gemini_client else "Gemini ❌")
        if router.openrouter_api_key:
            for model in router.openrouter_models:
                short = model.split("/")[-1].replace(":free", "")
                # A tripped breaker means it is failing and being skipped.
                mark = "⏸️" if router._breaker.is_open(model) else "✅"
                parts.append(f"{short} {mark}")
        else:
            parts.append("OpenRouter ❌")
        return " · ".join(parts)

    # ------------------------------------------------------------------

    def register_commands(self):
        """Attach the system commands and error handlers."""

        @self.bot.hybrid_command(name="ping", description="Check Ino's latency and health")
        @public_command
        async def ping_command(ctx):
            # Time the visible round trip: send now, measure, then edit.
            sent_at = time.perf_counter()
            message = await ctx.send(
                embed=discord.Embed(title="🏓 Measuring…", color=0x4A4A5A)
            )
            if message is None:
                try:
                    message = await ctx.original_response()
                except Exception:
                    return
            api_ms = (time.perf_counter() - sent_at) * 1000

            gateway_ms = self.bot.latency * 1000
            if gateway_ms != gateway_ms or gateway_ms <= 0:  # NaN before first heartbeat
                gateway_ms = None

            db_ms = await self._probe_database()

            # The embed takes the colour of the worst reading, so a healthy bot
            # is green at a glance and a degraded one is not.
            readings = [gateway_ms, api_ms, db_ms]
            worst = max((r for r in readings if r is not None), default=0)
            _, color = _band(None if any(r is None for r in readings) else worst)

            embed = discord.Embed(title="🏓 Pong", color=color)
            embed.add_field(
                name=f"{_band(gateway_ms)[0]} Gateway",
                value=_format_ms(gateway_ms),
                inline=True,
            )
            embed.add_field(
                name=f"{_band(api_ms)[0]} Message",
                value=_format_ms(api_ms),
                inline=True,
            )
            embed.add_field(
                name=f"{_band(db_ms)[0]} Database",
                value=_format_ms(db_ms),
                inline=True,
            )

            uptime = (datetime.now(timezone.utc) - self.started_at).total_seconds()
            embed.add_field(name="⏱️ Uptime", value=_format_duration(uptime), inline=True)

            if psutil is not None:
                try:
                    rss = psutil.Process().memory_info().rss / (1024 * 1024)
                    embed.add_field(name="🧠 Memory", value=f"{rss:.0f} MB", inline=True)
                except Exception:
                    pass

            embed.add_field(
                name="🎙️ Voice sessions",
                value=str(len(getattr(self.bot, "voice_clients", []) or [])),
                inline=True,
            )
            embed.add_field(name="🤖 AI providers", value=self._ai_status(), inline=False)

            await message.edit(embed=embed)

        @self.bot.hybrid_command(name="about", description="About Ino, and how she is running")
        @public_command
        async def about_command(ctx):
            embed = discord.Embed(
                title="⛩️ Ino",
                description=(
                    "Shrine guardian for this server. She scores your art, keeps "
                    "the leaderboards, watches for scams, and remembers exactly "
                    "how polite you have been."
                ),
                color=ACCENT,
            )
            if self.bot.user and self.bot.user.display_avatar:
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)

            uptime = (datetime.now(timezone.utc) - self.started_at).total_seconds()
            embed.add_field(name="Uptime", value=_format_duration(uptime), inline=True)
            embed.add_field(
                name="Commands",
                value=str(len(self.bot.tree.get_commands())),
                inline=True,
            )
            embed.add_field(
                name="Members watched",
                value=f"{sum(g.member_count or 0 for g in self.bot.guilds):,}",
                inline=True,
            )
            embed.add_field(
                name="Running on",
                value=f"discord.py {discord.__version__} · Python {platform.python_version()}",
                inline=False,
            )
            embed.add_field(
                name="Website",
                value=f"[{Config.WEB_BASE_URL.replace('https://', '')}]({Config.WEB_BASE_URL})",
                inline=True,
            )
            embed.add_field(
                name="Support",
                value=f"[Patreon]({Config.PATREON_URL}) · [Ko-fi]({Config.KOFI_URL})",
                inline=True,
            )
            await ctx.send(embed=embed)

        @self.bot.hybrid_command(name="help", description="Browse everything Ino can do")
        @public_command
        async def help_command(ctx, command: Optional[str] = None):
            if command:
                await self._send_command_help(ctx, command)
                return

            from views.help_view import HelpView

            view = HelpView(self.bot, invoker=ctx.author)
            view.message = await ctx.send(embed=view.build_embed(), view=view)

        @self.bot.hybrid_command(
            name="sync", description="[Owner] Force a slash command re-sync"
        )
        @owner_command
        async def sync_command(ctx):
            await ctx.defer(ephemeral=True)

            syncer = getattr(self.bot, "command_syncer", None)
            if syncer is None:
                from controllers.registry import CommandSyncer
                syncer = CommandSyncer(self.bot, Config.GUILD_ID)
                self.bot.command_syncer = syncer

            report = await syncer.sync(force=True)
            self.bot.last_sync_report = report

            lines = [f"**Commands:** {report.get('commands', 0)}"]
            if "guild" in report:
                lines.append(f"**Guild:** {report['guild']} synced")
            if "global" in report:
                lines.append(f"**Global:** {report['global']} synced")
            for key in ("guild_error", "global_error"):
                if key in report:
                    lines.append(f"⚠️ `{key}`: {report[key]}")

            await ctx.send(
                embed=discord.Embed(
                    title="🔄 Sync complete",
                    description="\n".join(lines),
                    color=GOOD,
                ),
                ephemeral=True,
            )

        self._install_error_handlers()
        logger.info("✅ System commands registered")

    # ------------------------------------------------------------------

    async def _send_command_help(self, ctx, name: str) -> None:
        """Detail view for a single command."""
        name = name.lstrip("/").strip().lower()
        command = self.bot.get_command(name)

        if command is None:
            await ctx.send(
                embed=discord.Embed(
                    description=f"❌ No command called `{name}`. Try `/help` to browse.",
                    color=BAD,
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"/{command.qualified_name}",
            description=command.description or command.help or "No description.",
            color=ACCENT,
        )

        signature = getattr(command, "signature", "")
        if signature:
            embed.add_field(
                name="Usage",
                value=f"`/{command.qualified_name} {signature}`",
                inline=False,
            )
        if command.aliases:
            embed.add_field(
                name="Also known as",
                value=", ".join(f"`{alias}`" for alias in command.aliases),
                inline=False,
            )
        await ctx.send(embed=embed)

    def _install_error_handlers(self) -> None:
        """Give slash commands a real error path instead of a silent timeout."""

        async def on_app_command_error(
            interaction: discord.Interaction, error: app_commands.AppCommandError
        ):
            embed = self._error_embed(error)

            # The interaction may or may not already be acknowledged depending on
            # where it failed, so both paths have to be covered.
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
            except discord.HTTPException as exc:
                logger.debug("Could not deliver error embed: %s", exc)

            command_name = interaction.command.name if interaction.command else "unknown"
            if isinstance(
                error,
                (
                    app_commands.CommandOnCooldown,
                    app_commands.MissingPermissions,
                    app_commands.CheckFailure,
                ),
            ):
                # Expected refusals: noise at error level, useful at info.
                logger.info("/%s refused: %s", command_name, error)
            else:
                logger.error("/%s failed: %s", command_name, error, exc_info=error)

        self.bot.tree.on_error = on_app_command_error

    @staticmethod
    def _error_embed(error: Exception) -> discord.Embed:
        """Translate an exception into something a member can act on."""
        if isinstance(error, app_commands.CommandOnCooldown):
            retry_at = int(time.time() + error.retry_after)
            return discord.Embed(
                title="⏳ Slow down",
                description=f"That command is on cooldown. Try again <t:{retry_at}:R>.",
                color=WARN,
            )

        if isinstance(error, app_commands.MissingPermissions):
            missing = ", ".join(error.missing_permissions)
            return discord.Embed(
                title="🔒 Not allowed",
                description=f"You need the following permission(s): `{missing}`.",
                color=WARN,
            )

        if isinstance(error, app_commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            return discord.Embed(
                title="🔒 Ino is missing permissions",
                description=f"She needs `{missing}` in this channel to do that.",
                color=WARN,
            )

        if isinstance(error, app_commands.CheckFailure):
            return discord.Embed(
                title="🔒 Not allowed",
                description="You cannot use that command here.",
                color=WARN,
            )

        if isinstance(error, app_commands.CommandInvokeError):
            original = error.original
            if isinstance(original, discord.Forbidden):
                return discord.Embed(
                    title="🔒 Blocked by Discord",
                    description="Ino does not have permission to do that here.",
                    color=WARN,
                )
            if isinstance(original, asyncio.TimeoutError):
                return discord.Embed(
                    title="⌛ Timed out",
                    description="That took too long. Try again in a moment.",
                    color=WARN,
                )

        return discord.Embed(
            title="💥 Something broke",
            description=(
                "That did not work, and it is not your fault. "
                "The failure has been logged."
            ),
            color=BAD,
        )
