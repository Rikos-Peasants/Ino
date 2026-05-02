import asyncio
import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands

from config import Config
from views.scam_image_view import ScamImageAddUrlModal, ScamImageStatusView, signature_embed

logger = logging.getLogger(__name__)


class ScamImageController:
    """Discord commands and message hooks for scam image detection."""

    def __init__(self, bot, manager):
        self.bot = bot
        self.manager = manager
        self.enabled = getattr(Config, "SCAM_IMAGE_DETECTION_ENABLED", True)
        self.delete_matches = getattr(Config, "SCAM_IMAGE_DELETE_MATCHES", False)
        self.dhash_distance = getattr(Config, "SCAM_IMAGE_DHASH_DISTANCE", 4)
        self.max_attachment_bytes = getattr(Config, "SCAM_IMAGE_MAX_ATTACHMENT_BYTES", 8 * 1024 * 1024)
        self.allowed_url_content_types = {"image/jpeg", "image/png", "image/webp"}

    def register_commands(self):
        group = app_commands.Group(
            name="scamimage",
            description="Manage scam image signatures and detections",
        )

        @group.command(name="status", description="Show scam image detector status")
        async def status(interaction: discord.Interaction):
            if not await self.can_manage_scam_images(interaction):
                await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
                return

            counts = await asyncio.to_thread(self.manager.counts)
            embed = discord.Embed(title="Scam Image Detection", color=discord.Color.blurple())
            embed.add_field(name="Enabled", value=str(self.enabled), inline=True)
            embed.add_field(name="Delete Matches", value=str(self.delete_matches), inline=True)
            embed.add_field(name="dHash Distance", value=str(self.dhash_distance), inline=True)
            embed.add_field(
                name="Signatures",
                value=f"{counts['active']} active / {counts['total']} total",
                inline=True,
            )
            embed.add_field(name="Detections", value=str(counts["detections"]), inline=True)
            await interaction.response.send_message(
                embed=embed,
                view=ScamImageStatusView(self),
                ephemeral=True,
            )

        @group.command(name="scan", description="Scan an image without adding it")
        @app_commands.describe(image="Image attachment to scan")
        async def scan(interaction: discord.Interaction, image: discord.Attachment):
            if not await self.can_manage_scam_images(interaction):
                await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
                return

            if image.size > self.max_attachment_bytes:
                await interaction.response.send_message(
                    "That attachment is larger than the configured limit.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer(ephemeral=True)
            body = await image.read(use_cached=True)
            match = await asyncio.to_thread(self.manager.find_match, image.filename, body, self.dhash_distance)
            try:
                signature = await asyncio.to_thread(self.manager.build_signature, body, "scan only")
            except Exception:
                await interaction.followup.send("That attachment is not a readable image.", ephemeral=True)
                return

            embed = signature_embed("Scan Result", signature)
            if match:
                embed.color = discord.Color.red()
                embed.add_field(
                    name="Matched",
                    value=f"`{match.kind}` {match.label}\n{match.detail}",
                    inline=False,
                )
            else:
                embed.color = discord.Color.orange()
                embed.add_field(name="Matched", value="No", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

        @group.command(name="add", description="Add an image attachment to scam signatures")
        @app_commands.describe(image="Image attachment to add", label="Short label for this signature")
        async def add(interaction: discord.Interaction, image: discord.Attachment, label: str):
            if not await self.can_manage_scam_images(interaction):
                await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            if image.size > self.max_attachment_bytes:
                await interaction.followup.send("That attachment is larger than the configured limit.", ephemeral=True)
                return

            body = await image.read(use_cached=True)
            try:
                signature = await asyncio.to_thread(self.manager.build_signature, body, label)
            except Exception:
                await interaction.followup.send("That attachment is not a readable image.", ephemeral=True)
                return

            created, action = await asyncio.to_thread(
                self.manager.add_signature,
                signature,
                source=f"discord attachment:{image.filename}",
                added_by_id=interaction.user.id,
                added_by_name=str(interaction.user),
            )
            embed = signature_embed(f"Signature {action.title()}", signature)
            await interaction.followup.send(embed=embed, ephemeral=True)

        @group.command(name="add_url", description="Open a modal to add an image by URL")
        async def add_url(interaction: discord.Interaction):
            if not await self.can_manage_scam_images(interaction):
                await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
                return
            await interaction.response.send_modal(ScamImageAddUrlModal(self))

        @group.command(name="bulk_recent", description="Add image attachments from recent channel history")
        @app_commands.describe(
            label="Label to apply to added signatures",
            limit="Messages to inspect, max 100",
            channel="Channel to scan; defaults to current channel",
        )
        async def bulk_recent(
            interaction: discord.Interaction,
            label: str,
            limit: app_commands.Range[int, 1, 100] = 25,
            channel: Optional[discord.TextChannel] = None,
        ):
            if not await self.can_manage_scam_images(interaction):
                await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            target = channel or interaction.channel
            if not isinstance(target, discord.TextChannel):
                await interaction.followup.send("Pick a text channel.", ephemeral=True)
                return

            added = 0
            skipped = 0
            async for message in target.history(limit=limit):
                for attachment in message.attachments:
                    if attachment.size > self.max_attachment_bytes:
                        skipped += 1
                        continue
                    try:
                        body = await attachment.read(use_cached=True)
                        signature = await asyncio.to_thread(self.manager.build_signature, body, label)
                        await asyncio.to_thread(
                            self.manager.add_signature,
                            signature,
                            source=f"discord message:{message.id}/{attachment.filename}",
                            added_by_id=interaction.user.id,
                            added_by_name=str(interaction.user),
                        )
                        added += 1
                    except Exception:
                        skipped += 1

            await interaction.followup.send(
                f"Bulk add complete. Added/updated `{added}` signatures; skipped `{skipped}`.",
                ephemeral=True,
            )

        @group.command(name="list", description="List scam image signatures")
        async def list_signatures(
            interaction: discord.Interaction,
            query: Optional[str] = None,
            active_only: bool = True,
        ):
            if not await self.can_manage_scam_images(interaction):
                await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
                return
            await self.send_signature_list(interaction, query=query, active_only=active_only)

        @group.command(name="disable", description="Disable a scam image signature by SHA-256 prefix")
        async def disable(interaction: discord.Interaction, sha256_prefix: str):
            await self._set_signature_active(interaction, sha256_prefix, False)

        @group.command(name="enable", description="Enable a scam image signature by SHA-256 prefix")
        async def enable(interaction: discord.Interaction, sha256_prefix: str):
            await self._set_signature_active(interaction, sha256_prefix, True)

        @group.command(name="recent", description="Show recent scam image detections")
        async def recent(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 15] = 5):
            if not await self.can_manage_scam_images(interaction):
                await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
                return
            await self.send_recent_detections(interaction, limit=limit)

        @group.command(name="seed_defaults", description="Import bundled default scam image signatures")
        async def seed_defaults(interaction: discord.Interaction):
            if not await self.can_manage_scam_images(interaction):
                await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            result = await asyncio.to_thread(self.manager.seed_default_signatures)
            await interaction.followup.send(
                (
                    "Default scam signatures imported. "
                    f"Created `{result['created']}`, updated `{result['updated']}`, total `{result['total']}`."
                ),
                ephemeral=True,
            )

        self.bot.tree.add_command(group, guild=discord.Object(id=Config.GUILD_ID))

    async def can_manage_scam_images(self, interaction: discord.Interaction) -> bool:
        if (
            not interaction.guild
            or interaction.guild.id != Config.GUILD_ID
            or not isinstance(interaction.user, discord.Member)
        ):
            return False

        if await self.bot.is_owner(interaction.user):
            return True
        if interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild:
            return True

        moderator_role_id = getattr(Config, "NSFWBAN_MODERATOR_ROLE_ID", None)
        if moderator_role_id and discord.utils.get(interaction.user.roles, id=moderator_role_id):
            return True
        return False

    async def scan_message(self, message: discord.Message) -> bool:
        if not self.enabled or not message.attachments:
            return False

        for attachment in message.attachments:
            if attachment.size > self.max_attachment_bytes:
                continue
            if not self.manager.is_supported_image(attachment.filename):
                continue
            try:
                body = await attachment.read(use_cached=True)
            except discord.HTTPException:
                logger.warning(f"Could not read attachment {attachment.filename} from message {message.id}")
                continue

            match = await asyncio.to_thread(self.manager.find_match, attachment.filename, body, self.dhash_distance)
            if not match:
                continue

            detection_id = await asyncio.to_thread(self.manager.record_detection, message, attachment, match)
            logger.warning(
                "Scam image match kind=%s label=%s user=%s channel=%s attachment=%s",
                match.kind,
                match.label,
                message.author,
                message.channel,
                attachment.filename,
            )

            if self.delete_matches:
                try:
                    await message.delete()
                    await asyncio.to_thread(
                        self.manager.update_detection_delete_result,
                        detection_id,
                        deleted=True,
                        delete_error=None,
                    )
                    return True
                except discord.Forbidden:
                    await asyncio.to_thread(
                        self.manager.update_detection_delete_result,
                        detection_id,
                        deleted=False,
                        delete_error="missing Manage Messages permission",
                    )
                except discord.HTTPException as e:
                    await asyncio.to_thread(
                        self.manager.update_detection_delete_result,
                        detection_id,
                        deleted=False,
                        delete_error=str(e),
                    )
            return True
        return False

    async def add_url_from_modal(self, interaction: discord.Interaction, url: str, label: str):
        if not await self.can_manage_scam_images(interaction):
            await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await self._validate_fetch_url(url)
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, allow_redirects=False) as response:
                    if response.status != 200:
                        await interaction.followup.send(f"Could not fetch URL: HTTP {response.status}", ephemeral=True)
                        return

                    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    if content_type not in self.allowed_url_content_types:
                        await interaction.followup.send("That URL did not return a supported image type.", ephemeral=True)
                        return

                    if response.content_length and response.content_length > self.max_attachment_bytes:
                        await interaction.followup.send(
                            "That URL returned an image larger than the configured limit.",
                            ephemeral=True,
                        )
                        return

                    body = await response.content.read(self.max_attachment_bytes + 1)
                    if len(body) > self.max_attachment_bytes:
                        await interaction.followup.send(
                            "That URL returned an image larger than the configured limit.",
                            ephemeral=True,
                        )
                        return
        except Exception as e:
            await interaction.followup.send(f"Could not fetch URL: `{e}`", ephemeral=True)
            return

        try:
            signature = await asyncio.to_thread(self.manager.build_signature, body, label)
        except Exception:
            await interaction.followup.send("That URL did not return a readable image.", ephemeral=True)
            return

        await asyncio.to_thread(
            self.manager.add_signature,
            signature,
            source=url,
            added_by_id=interaction.user.id,
            added_by_name=str(interaction.user),
        )
        await interaction.followup.send(embed=signature_embed("Signature Added", signature), ephemeral=True)

    async def _validate_fetch_url(self, url: str):
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() != "https":
            raise ValueError("Only https:// image URLs are allowed.")
        if not parsed.hostname:
            raise ValueError("URL must include a hostname.")

        hostname = parsed.hostname.strip().lower()
        if hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".localhost") or hostname.endswith(".local"):
            raise ValueError("Local URLs are not allowed.")

        try:
            addresses = [ipaddress.ip_address(hostname)]
        except ValueError:
            loop = asyncio.get_running_loop()
            resolved = await loop.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            addresses = [ipaddress.ip_address(item[4][0]) for item in resolved]

        for address in addresses:
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            ):
                raise ValueError("Private or local network URLs are not allowed.")

    async def send_signature_list(
        self,
        interaction: discord.Interaction,
        query: Optional[str] = None,
        active_only: bool = True,
    ):
        rows = await asyncio.to_thread(self.manager.list_signatures, query=query, active_only=active_only, limit=10)
        if not rows:
            responder = interaction.response.send_message if not interaction.response.is_done() else interaction.followup.send
            await responder("No scam image signatures found.", ephemeral=True)
            return

        embed = discord.Embed(title="Scam Image Signatures", color=discord.Color.blurple())
        for row in rows:
            status = "active" if row.get("active") else "disabled"
            embed.add_field(
                name=f"{row.get('label', 'unlabeled')} ({status})",
                value=(
                    f"`{row['sha256'][:16]}...`\n"
                    f"{row.get('bytes', 0)} bytes, {row.get('width', 0)}x{row.get('height', 0)}, "
                    f"dHash `{row.get('dhash', '')}`"
                ),
                inline=False,
            )
        responder = interaction.response.send_message if not interaction.response.is_done() else interaction.followup.send
        await responder(embed=embed, ephemeral=True)

    async def send_recent_detections(self, interaction: discord.Interaction, limit: int = 5):
        rows = await asyncio.to_thread(self.manager.recent_detections, limit=limit)
        if not rows:
            responder = interaction.response.send_message if not interaction.response.is_done() else interaction.followup.send
            await responder("No scam image detections recorded yet.", ephemeral=True)
            return

        embed = discord.Embed(title="Recent Scam Image Detections", color=discord.Color.red())
        for row in rows:
            status = "deleted" if row.get("deleted") else f"not deleted ({row.get('delete_error') or 'unknown'})"
            embed.add_field(
                name=f"{row.get('match_label')} via {row.get('match_kind')}",
                value=f"{row.get('user_name')} in #{row.get('channel_name')} - {status}",
                inline=False,
            )
        responder = interaction.response.send_message if not interaction.response.is_done() else interaction.followup.send
        await responder(embed=embed, ephemeral=True)

    async def _set_signature_active(self, interaction: discord.Interaction, sha256_prefix: str, active: bool):
        if not await self.can_manage_scam_images(interaction):
            await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
            return
        ok, message = await asyncio.to_thread(self.manager.set_signature_active, sha256_prefix, active)
        await interaction.response.send_message(("✅ " if ok else "❌ ") + message, ephemeral=True)
