import asyncio
import ipaddress
import logging
import socket
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands

from config import Config
from views.scam_image_view import (
    ScamImageAddUrlModal,
    ScamImageStatusView,
    image_burst_alert_embed,
    scam_cross_channel_alert_embed,
    scam_detection_embed,
    signature_embed,
)

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
        self.cross_channel_threshold = getattr(Config, "SCAM_IMAGE_CROSS_CHANNEL_THRESHOLD", 3)
        self.cross_channel_window_seconds = getattr(Config, "SCAM_IMAGE_CROSS_CHANNEL_WINDOW_SECONDS", 15)
        self.cross_channel_alert_cooldown_minutes = getattr(
            Config,
            "SCAM_IMAGE_CROSS_CHANNEL_ALERT_COOLDOWN_MINUTES",
            10,
        )
        self.image_burst_scan_enabled = getattr(Config, "SCAM_IMAGE_BURST_SCAN_ENABLED", True)
        self.image_burst_ignored_channel_ids = set(getattr(Config, "IMAGE_REACTION_CHANNELS", []))
        self.image_burst_ignored_channel_ids.update(getattr(Config, "ART_CHALLENGE_CHANNELS", []))
        self.image_burst_delete_messages = getattr(Config, "SCAM_IMAGE_BURST_DELETE_MESSAGES", False)
        self.image_burst_timeout_enabled = getattr(Config, "SCAM_IMAGE_BURST_TIMEOUT_ENABLED", True)
        self.image_burst_timeout_seconds = getattr(Config, "SCAM_IMAGE_BURST_TIMEOUT_SECONDS", 60)
        self._image_burst_entries = []
        self._image_burst_confirmation_keys = set()
        self._image_burst_suppressed_until = {}
        self.allowed_url_content_types = {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/x-ms-bmp"}

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
            embed.add_field(
                name="Repeated Burst Actions",
                value=(
                    f"scan={self.image_burst_scan_enabled}, "
                    f"timeout={self.image_burst_timeout_enabled} "
                    f"({self.image_burst_timeout_seconds}s), "
                    f"delete={self.image_burst_delete_messages}"
                ),
                inline=False,
            )
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

        @group.command(name="scan_recent", description="Scan recent channel images against known scam signatures")
        @app_commands.describe(
            limit="Messages to inspect, max 100",
            channel="Channel to scan; defaults to current channel",
            delete_matches="Delete matched messages during this scan",
        )
        async def scan_recent(
            interaction: discord.Interaction,
            limit: app_commands.Range[int, 1, 100] = 25,
            channel: Optional[discord.TextChannel] = None,
            delete_matches: bool = False,
        ):
            if not await self.can_manage_scam_images(interaction):
                await interaction.response.send_message("You need moderation permissions.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            target = channel or interaction.channel
            if not isinstance(target, discord.TextChannel):
                await interaction.followup.send("Pick a text channel.", ephemeral=True)
                return

            scanned = 0
            matched = 0
            skipped = 0
            try:
                async for message in target.history(limit=limit):
                    if message.author.bot or not message.attachments:
                        continue
                    scanned += 1
                    try:
                        if await self.scan_message(
                            message,
                            force_delete=delete_matches,
                            alert_on_burst=False,
                            burst_eligible=False,
                        ):
                            matched += 1
                    except (discord.Forbidden, discord.HTTPException):
                        skipped += 1
                    except Exception:
                        logger.exception("Error scanning historical scam image message %s", message.id)
                        skipped += 1
            except discord.Forbidden:
                await interaction.followup.send(
                    f"I can't read message history in {target.mention}.",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as e:
                await interaction.followup.send(
                    f"Could not scan {target.mention}: `{e}`",
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                (
                    f"Scan complete in {target.mention}. "
                    f"Scanned `{scanned}` messages, matched `{matched}`, skipped `{skipped}`."
                ),
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

        role_ids = {
            getattr(Config, "DEFAULT_MODERATION_REVIEW_ROLE_ID", None),
            getattr(Config, "DEFAULT_MODERATION_ADMIN_ROLE_ID", None),
            getattr(Config, "NSFWBAN_MODERATOR_ROLE_ID", None),
        }
        moderation_manager = self._get_moderation_manager()
        if moderation_manager:
            guild_id = str(interaction.guild.id)
            try:
                role_ids.add(await moderation_manager.get_review_role_id(guild_id))
                role_ids.add(await moderation_manager.get_admin_role_id(guild_id))
            except Exception as e:
                logger.warning("Could not read moderation role settings for scam image permissions: %s", e)

        if any(role_id and discord.utils.get(interaction.user.roles, id=role_id) for role_id in role_ids):
            return True
        return False

    async def scan_message(
        self,
        message: discord.Message,
        force_delete: Optional[bool] = None,
        alert_on_burst: bool = True,
        burst_eligible: bool = True,
    ) -> bool:
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
                if alert_on_burst and burst_eligible:
                    await self._maybe_send_repeated_image_burst_alert(message, attachment)
                continue

            detection_id = await asyncio.to_thread(
                self.manager.record_detection,
                message,
                attachment,
                match,
                burst_eligible=burst_eligible,
            )
            should_delete = self.delete_matches if force_delete is None else force_delete
            deleted = False
            delete_error = None
            logger.warning(
                "Scam image match kind=%s label=%s user=%s channel=%s attachment=%s",
                match.kind,
                match.label,
                message.author,
                message.channel,
                attachment.filename,
            )

            if should_delete:
                try:
                    await message.delete()
                    deleted = True
                    await asyncio.to_thread(
                        self.manager.update_detection_delete_result,
                        detection_id,
                        deleted=True,
                        delete_error=None,
                    )
                except discord.Forbidden:
                    delete_error = "missing Manage Messages permission"
                    await asyncio.to_thread(
                        self.manager.update_detection_delete_result,
                        detection_id,
                        deleted=False,
                        delete_error=delete_error,
                    )
                except discord.HTTPException as e:
                    delete_error = str(e)
                    await asyncio.to_thread(
                        self.manager.update_detection_delete_result,
                        detection_id,
                        deleted=False,
                        delete_error=delete_error,
                    )
            else:
                delete_error = "auto-delete disabled"

            await self._send_detection_log(message, attachment, match, deleted=deleted, delete_error=delete_error)
            if alert_on_burst:
                await self._maybe_send_cross_channel_alert(message)
            return True
        return False

    def _image_burst_metadata_key(self, attachment) -> tuple:
        filename = getattr(attachment, "filename", "") or ""
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return (
            extension,
            int(getattr(attachment, "size", 0) or 0),
            getattr(attachment, "width", None),
            getattr(attachment, "height", None),
            getattr(attachment, "content_type", None),
        )

    async def _maybe_send_repeated_image_burst_alert(self, message: discord.Message, attachment):
        if (
            not message.guild
            or not self.image_burst_scan_enabled
            or not self.manager.is_supported_image(attachment.filename)
            or message.channel.id in self.image_burst_ignored_channel_ids
            or self.cross_channel_threshold <= 1
            or self.cross_channel_window_seconds <= 0
        ):
            return

        now = datetime.utcnow()
        window_start = now - timedelta(seconds=self.cross_channel_window_seconds)
        self._image_burst_entries = [
            entry for entry in self._image_burst_entries if entry["created_at"] >= window_start
        ]

        confirmation_key = (str(message.guild.id), str(message.author.id))
        if self._is_image_burst_suppressed(confirmation_key, now):
            return
        if confirmation_key in self._image_burst_confirmation_keys:
            return

        metadata_key = self._image_burst_metadata_key(attachment)
        attachment_id = str(getattr(attachment, "id", attachment.filename))
        message_id = str(message.id)
        if any(
            cached["guild_id"] == confirmation_key[0]
            and cached["user_id"] == confirmation_key[1]
            and cached.get("message_id") == message_id
            and cached.get("attachment_id") == attachment_id
            for cached in self._image_burst_entries
        ):
            return

        entry = {
            "created_at": now,
            "guild_id": confirmation_key[0],
            "user_id": confirmation_key[1],
            "user_name": str(message.author),
            "channel_id": str(message.channel.id),
            "message_id": message_id,
            "attachment_id": attachment_id,
            "attachment_name": attachment.filename,
            "attachment_size": attachment.size,
            "metadata_key": metadata_key,
            "message": message,
            "attachment": attachment,
        }
        self._image_burst_entries.append(entry)

        candidates = [
            cached
            for cached in self._image_burst_entries
            if cached["guild_id"] == entry["guild_id"]
            and cached["user_id"] == entry["user_id"]
        ]
        channel_ids = {cached["channel_id"] for cached in candidates}
        if len(channel_ids) < self.cross_channel_threshold:
            return

        self._image_burst_confirmation_keys.add(confirmation_key)
        try:
            confirmed_entries, match_kind = await self._confirm_repeated_image_entries(
                self._prioritize_image_burst_candidates(candidates, metadata_key)
            )
            confirmed_channel_ids = []
            for confirmed in confirmed_entries:
                channel_id = confirmed.get("channel_id")
                if channel_id and channel_id not in confirmed_channel_ids:
                    confirmed_channel_ids.append(channel_id)
            if len(confirmed_channel_ids) < self.cross_channel_threshold:
                return

            log_channel = await self._get_moderation_log_channel(message.guild)
            if not log_channel:
                self._suppress_image_burst_user(confirmation_key)
                self._clear_image_burst_entries(confirmation_key)
                return

            reservation_token = await asyncio.to_thread(
                self.manager.reserve_cross_channel_alert,
                guild_id=str(message.guild.id),
                user_id=str(message.author.id),
                user_name=str(message.author),
                channel_ids=confirmed_channel_ids,
                message_ids=[
                    str(confirmed.get("message_id"))
                    for confirmed in confirmed_entries
                    if confirmed.get("message_id")
                ],
                threshold=self.cross_channel_threshold,
                window_seconds=self.cross_channel_window_seconds,
                cooldown_minutes=self.cross_channel_alert_cooldown_minutes,
                alert_kind="repeated_image_burst",
            )
            if not reservation_token:
                self._suppress_image_burst_user(confirmation_key)
                self._clear_image_burst_entries(confirmation_key)
                return

            embed = image_burst_alert_embed(
                message,
                confirmed_entries,
                threshold=self.cross_channel_threshold,
                window_seconds=self.cross_channel_window_seconds,
                match_kind=match_kind,
                actions=["Actions pending"],
            )
            review_role_id = await self._get_review_role_id(message.guild)
            content = f"<@&{review_role_id}> Repeated image burst detected" if review_role_id else None
            try:
                alert_message = await log_channel.send(content=content, embed=embed)
            except discord.Forbidden:
                await asyncio.to_thread(
                    self.manager.release_cross_channel_alert_reservation,
                    str(message.guild.id),
                    str(message.author.id),
                    reservation_token,
                    alert_kind="repeated_image_burst",
                )
                logger.warning("Missing permission to send repeated image burst alert in %s", log_channel)
                self._suppress_image_burst_user(confirmation_key)
                self._clear_image_burst_entries(confirmation_key)
                return
            except discord.HTTPException as e:
                await asyncio.to_thread(
                    self.manager.release_cross_channel_alert_reservation,
                    str(message.guild.id),
                    str(message.author.id),
                    reservation_token,
                    alert_kind="repeated_image_burst",
                )
                logger.warning("Could not send repeated image burst alert: %s", e)
                self._suppress_image_burst_user(confirmation_key)
                self._clear_image_burst_entries(confirmation_key)
                return

            action_results = await self._apply_repeated_image_burst_actions(message, confirmed_entries)
            embed = image_burst_alert_embed(
                message,
                confirmed_entries,
                threshold=self.cross_channel_threshold,
                window_seconds=self.cross_channel_window_seconds,
                match_kind=match_kind,
                actions=action_results,
            )
            try:
                await alert_message.edit(embed=embed)
            except discord.HTTPException as e:
                logger.warning("Could not update repeated image burst alert actions: %s", e)
            await asyncio.to_thread(
                self.manager.mark_cross_channel_alert_sent,
                str(message.guild.id),
                str(message.author.id),
                reservation_token,
                alert_kind="repeated_image_burst",
            )
            self._suppress_image_burst_user(confirmation_key)
            self._clear_image_burst_entries(confirmation_key)
        finally:
            self._image_burst_confirmation_keys.discard(confirmation_key)

    async def _apply_repeated_image_burst_actions(self, message: discord.Message, entries: list[dict]) -> list[str]:
        results = []
        author_is_owner = await self.bot.is_owner(message.author)
        if self.image_burst_timeout_enabled:
            if not isinstance(message.author, discord.Member):
                results.append("Timeout skipped: author is not a guild member")
            elif author_is_owner:
                results.append("Timeout skipped: bot owner")
            else:
                timeout_seconds = max(int(self.image_burst_timeout_seconds or 0), 1)
                timeout_until = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
                try:
                    await message.author.edit(
                        timed_out_until=timeout_until,
                        reason="Repeated image burst detected",
                    )
                    results.append(f"Timed out for {timeout_seconds} seconds")
                except discord.Forbidden:
                    results.append("Timeout failed: missing permission or role hierarchy")
                except discord.HTTPException as e:
                    results.append(f"Timeout failed: {e}")
        else:
            results.append("Timeout disabled")

        if self.image_burst_delete_messages:
            if author_is_owner:
                results.append("Message deletion skipped: bot owner")
            else:
                deleted = 0
                failed = 0
                seen_message_ids = set()
                for entry in entries:
                    entry_message = entry.get("message")
                    message_id = entry.get("message_id")
                    if not entry_message or message_id in seen_message_ids:
                        continue
                    seen_message_ids.add(message_id)
                    try:
                        await entry_message.delete()
                        deleted += 1
                    except discord.NotFound:
                        deleted += 1
                    except (discord.Forbidden, discord.HTTPException):
                        failed += 1
                results.append(f"Deleted {deleted} burst messages" if failed == 0 else f"Deleted {deleted} burst messages; failed {failed}")
        else:
            results.append("Message deletion disabled")

        return results

    def _prioritize_image_burst_candidates(self, candidates: list[dict], metadata_key: tuple) -> list[dict]:
        same_metadata = [entry for entry in candidates if entry.get("metadata_key") == metadata_key]
        other_metadata = [entry for entry in candidates if entry.get("metadata_key") != metadata_key]
        selected = same_metadata[-25:]
        remaining = 25 - len(selected)
        if remaining > 0:
            selected.extend(other_metadata[-remaining:])
        return selected

    def _is_image_burst_suppressed(self, confirmation_key: tuple, now: datetime) -> bool:
        for key, suppressed_until in list(self._image_burst_suppressed_until.items()):
            if suppressed_until <= now:
                self._image_burst_suppressed_until.pop(key, None)
        suppressed_until = self._image_burst_suppressed_until.get(confirmation_key)
        if not suppressed_until:
            return False
        return True

    def _suppress_image_burst_user(self, confirmation_key: tuple):
        seconds = max(self.cross_channel_alert_cooldown_minutes, 1) * 60
        self._image_burst_suppressed_until[confirmation_key] = datetime.utcnow() + timedelta(seconds=seconds)

    def _clear_image_burst_entries(self, confirmation_key: tuple):
        guild_id, user_id = confirmation_key
        self._image_burst_entries = [
            entry
            for entry in self._image_burst_entries
            if entry.get("guild_id") != guild_id or entry.get("user_id") != user_id
        ]

    async def _confirm_repeated_image_entries(self, candidates: list[dict]) -> tuple[list[dict], str]:
        readable = []
        for entry in candidates:
            if "signature" not in entry:
                try:
                    body = await entry["attachment"].read(use_cached=True)
                    entry["signature"] = await asyncio.to_thread(
                        self.manager.build_signature,
                        body,
                        "repeated image burst",
                    )
                except (discord.HTTPException, OSError, ValueError):
                    continue
            readable.append(entry)

        exact_groups = {}
        for entry in readable:
            exact_groups.setdefault(entry["signature"].sha256, []).append(entry)
        for group in exact_groups.values():
            if len({entry["channel_id"] for entry in group}) >= self.cross_channel_threshold:
                return group, "Exact SHA-256"

        for seed in readable:
            similar = []
            for entry in readable:
                distance = self.manager.hamming_distance(seed["signature"].dhash, entry["signature"].dhash)
                if distance <= self.dhash_distance:
                    similar.append(entry)
            if len({entry["channel_id"] for entry in similar}) >= self.cross_channel_threshold:
                return similar, f"dHash distance <= {self.dhash_distance}"

        return [], ""

    def _get_moderation_manager(self):
        leaderboard_manager = getattr(self.bot, "leaderboard_manager", None)
        return getattr(leaderboard_manager, "moderation_manager", None) if leaderboard_manager else None

    async def _get_moderation_log_channel(self, guild: discord.Guild):
        moderation_manager = self._get_moderation_manager()
        if not moderation_manager:
            return None
        try:
            log_channel_id = await moderation_manager.get_moderation_log_channel_id(str(guild.id))
        except Exception as e:
            logger.warning("Could not read moderation log channel for scam image detection: %s", e)
            return None
        return guild.get_channel(log_channel_id) if log_channel_id else None

    async def _get_review_role_id(self, guild: discord.Guild):
        moderation_manager = self._get_moderation_manager()
        if moderation_manager:
            try:
                role_id = await moderation_manager.get_review_role_id(str(guild.id))
                if role_id:
                    return role_id
            except Exception as e:
                logger.warning("Could not read moderation review role for scam image alert: %s", e)
        return getattr(Config, "DEFAULT_MODERATION_REVIEW_ROLE_ID", None)

    async def _send_detection_log(self, message, attachment, match, *, deleted: bool, delete_error: Optional[str]):
        if not message.guild:
            return
        log_channel = await self._get_moderation_log_channel(message.guild)
        if not log_channel:
            return
        embed = scam_detection_embed(message, attachment, match, deleted=deleted, delete_error=delete_error)
        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            logger.warning("Missing permission to send scam image detection log in %s", log_channel)
        except discord.HTTPException as e:
            logger.warning("Could not send scam image detection log: %s", e)

    async def _maybe_send_cross_channel_alert(self, message: discord.Message):
        if (
            not message.guild
            or self.cross_channel_threshold <= 1
            or self.cross_channel_window_seconds <= 0
        ):
            return

        now = datetime.utcnow()
        window_start = now - timedelta(seconds=self.cross_channel_window_seconds)
        detections = await asyncio.to_thread(
            self.manager.recent_user_channel_detections,
            str(message.guild.id),
            str(message.author.id),
            window_start,
        )
        channel_ids = []
        for detection in detections:
            channel_id = detection.get("channel_id")
            if channel_id and channel_id not in channel_ids:
                channel_ids.append(channel_id)

        if len(channel_ids) < self.cross_channel_threshold:
            return

        log_channel = await self._get_moderation_log_channel(message.guild)
        if not log_channel:
            return
        embed = scam_cross_channel_alert_embed(
            message,
            detections,
            threshold=self.cross_channel_threshold,
            window_seconds=self.cross_channel_window_seconds,
        )
        review_role_id = await self._get_review_role_id(message.guild)
        content = f"<@&{review_role_id}> Scam image burst detected" if review_role_id else None
        reservation_token = await asyncio.to_thread(
            self.manager.reserve_cross_channel_alert,
            guild_id=str(message.guild.id),
            user_id=str(message.author.id),
            user_name=str(message.author),
            channel_ids=channel_ids,
            message_ids=[str(detection.get("message_id")) for detection in detections if detection.get("message_id")],
            threshold=self.cross_channel_threshold,
            window_seconds=self.cross_channel_window_seconds,
            cooldown_minutes=self.cross_channel_alert_cooldown_minutes,
        )
        if not reservation_token:
            return

        try:
            await log_channel.send(content=content, embed=embed)
            await asyncio.to_thread(
                self.manager.mark_cross_channel_alert_sent,
                str(message.guild.id),
                str(message.author.id),
                reservation_token,
            )
        except discord.Forbidden:
            await asyncio.to_thread(
                self.manager.release_cross_channel_alert_reservation,
                str(message.guild.id),
                str(message.author.id),
                reservation_token,
            )
            logger.warning("Missing permission to send scam image burst alert in %s", log_channel)
        except discord.HTTPException as e:
            await asyncio.to_thread(
                self.manager.release_cross_channel_alert_reservation,
                str(message.guild.id),
                str(message.author.id),
                reservation_token,
            )
            logger.warning("Could not send scam image burst alert: %s", e)

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
