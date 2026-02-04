import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import discord

logger = logging.getLogger(__name__)


@dataclass
class MessageRecord:
    content_key: str
    channel_id: int
    created_at: datetime


class UserSafetyMonitor:
    """Detect risky usernames, bios, new accounts, and cross-channel spam."""

    def __init__(
        self,
        bot: discord.Client,
        notification_user_ids: Optional[Iterable[int]] = None,
        spam_channel_threshold: int = 3,
        spam_window_seconds: int = 120,
        spam_action_cooldown_seconds: int = 3600,
    ) -> None:
        self.bot = bot
        from config import Config

        self.notification_user_ids = list(
            notification_user_ids or Config.SAFETY_DM_USER_IDS
        )
        self.spam_channel_threshold = spam_channel_threshold
        self.spam_window = timedelta(seconds=spam_window_seconds)
        self.spam_action_cooldown = timedelta(seconds=spam_action_cooldown_seconds)
        self._recent_messages: Dict[int, List[MessageRecord]] = {}
        self._spam_actioned_at: Dict[int, datetime] = {}
        self._words_config = self._load_words_config()
        self.offensive_categories = self._words_config["offensive_categories"]
        self.offensive_regex_patterns = self._words_config["offensive_regex_patterns"]
        self.crypto_keywords = set(self._words_config["crypto_keywords"])
        self._compiled_offensive_patterns = self._compile_offensive_patterns()

    async def handle_member_join(self, member: discord.Member) -> None:
        """Scan new members for risky signals and notify staff."""
        try:
            alerts = []
            now = datetime.now(timezone.utc)
            account_age = now - member.created_at
            if account_age < timedelta(days=7):
                alerts.append(
                    f"Account age is {account_age.days} day(s) (under 7 days)."
                )

            alerts.extend(await self._scan_member_profile(member))
            if alerts:
                await self._notify_staff(
                    member,
                    "\n".join(alerts),
                    context="Member join checks",
                )
        except Exception as exc:
            logger.error("User safety join check failed for %s: %s", member.id, exc)

    async def handle_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Scan updates for risky names/bios and notify staff."""
        try:
            if before.display_name == after.display_name and before.nick == after.nick:
                if getattr(before, "global_name", None) == getattr(after, "global_name", None):
                    return
            alerts = await self._scan_member_profile(after)
            if alerts:
                await self._notify_staff(
                    after,
                    "\n".join(alerts),
                    context="Member update checks",
                )
        except Exception as exc:
            logger.error("User safety update check failed for %s: %s", after.id, exc)

    async def handle_message(self, message: discord.Message) -> None:
        """Detect repeated cross-channel spam and apply timeout."""
        if not message.guild or message.author.bot:
            return

        content_key = self._normalize_message_for_spam(message.content)
        if not content_key:
            return

        now = datetime.now(timezone.utc)
        self._prune_records(message.author.id, now)
        records = self._recent_messages.setdefault(message.author.id, [])
        records.append(
            MessageRecord(
                content_key=content_key,
                channel_id=message.channel.id,
                created_at=now,
            )
        )

        unique_channels = {
            record.channel_id
            for record in records
            if record.content_key == content_key
        }

        if len(unique_channels) < self.spam_channel_threshold:
            return

        last_action = self._spam_actioned_at.get(message.author.id)
        if last_action and now - last_action < self.spam_action_cooldown:
            return

        await self._apply_spam_timeout(message, content_key, unique_channels)
        self._spam_actioned_at[message.author.id] = now

    async def _apply_spam_timeout(
        self,
        message: discord.Message,
        content_key: str,
        channel_ids: Iterable[int],
    ) -> None:
        timeout_duration = timedelta(days=1)
        reason = "Cross-channel spam (repeated message)"
        try:
            await message.author.timeout(timeout_duration, reason=reason)
            logger.info(
                "Timed out %s for cross-channel spam (channels: %s)",
                message.author.id,
                sorted(channel_ids),
            )
        except discord.Forbidden:
            logger.warning("Missing permission to timeout %s", message.author.id)
        except Exception as exc:
            logger.error("Failed to timeout %s: %s", message.author.id, exc)

        channels_display = ", ".join(f"<#{channel_id}>" for channel_id in sorted(channel_ids))
        await self._notify_staff(
            message.author,
            (
                "Cross-channel spam detected.\n"
                f"Message key: `{content_key}`\n"
                f"Channels: {channels_display}\n"
                "Action: 1-day timeout applied."
            ),
            context="Spam enforcement",
        )

    async def _scan_member_profile(self, member: discord.Member) -> List[str]:
        alerts: List[str] = []

        name_fields = [
            ("display name", member.display_name),
            ("username", member.name),
        ]
        global_name = getattr(member, "global_name", None)
        if global_name:
            name_fields.append(("global name", global_name))
        if member.nick:
            name_fields.append(("nickname", member.nick))

        for label, value in name_fields:
            matched = self._find_offensive_term(value)
            if matched:
                alerts.append(f"Offensive term detected in {label}: {matched}.")
            if self._contains_crypto_terms(value):
                alerts.append(f"Crypto-related term detected in {label}.")

        bio = await self._fetch_user_bio(member)
        if bio and self._contains_crypto_terms(bio):
            alerts.append("Crypto-related term detected in bio.")

        if bio:
            matched = self._find_offensive_term(bio)
            if matched:
                alerts.append("Offensive term detected in bio.")

        return alerts

    async def _fetch_user_bio(self, member: discord.Member) -> Optional[str]:
        bio = getattr(member, "bio", None)
        if bio:
            return bio
        try:
            user = await self.bot.fetch_user(member.id)
            return getattr(user, "bio", None)
        except Exception:
            return None

    def _find_offensive_term(self, text: str) -> Optional[str]:
        normalized = self._normalize_text(text)
        for category, terms in self.offensive_categories.items():
            if any(term in normalized for term in terms):
                return category
        for category, patterns in self._compiled_offensive_patterns.items():
            if any(pattern.search(text) for pattern in patterns):
                return category
        return None

    def _contains_crypto_terms(self, text: str) -> bool:
        cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
        cleaned = re.sub(r"\s+", " ", cleaned)
        for keyword in self.crypto_keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", cleaned):
                return True
        return False

    def _normalize_text(self, text: str) -> str:
        lowered = text.lower()
        substitutions = {
            "0": "o",
            "1": "i",
            "!": "i",
            "|": "i",
            "3": "e",
            "4": "a",
            "@": "a",
            "5": "s",
            "$": "s",
            "7": "t",
            "+": "t",
            "8": "b",
            "9": "g",
            "6": "g",
        }
        for leet, normal in substitutions.items():
            lowered = lowered.replace(leet, normal)
        lowered = re.sub(r"[^a-z0-9]", "", lowered)
        lowered = re.sub(r"(.)\1{2,}", r"\1\1", lowered)
        return lowered

    def _compile_offensive_patterns(self) -> Dict[str, List[re.Pattern]]:
        compiled: Dict[str, List[re.Pattern]] = {}
        for category, patterns in self.offensive_regex_patterns.items():
            compiled[category] = [
                re.compile(pattern, re.IGNORECASE) for pattern in patterns
            ]
        return compiled

    def _load_words_config(self) -> Dict[str, Dict[str, List[str]]]:
        words_path = Path(__file__).with_name("words.json")
        with words_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        required_keys = {"offensive_categories", "offensive_regex_patterns", "crypto_keywords"}
        missing = required_keys - data.keys()
        if missing:
            raise ValueError(f"words.json missing keys: {', '.join(sorted(missing))}")

        return data

    def _normalize_message_for_spam(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text.strip().lower()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"[^a-z0-9\s]", "", cleaned)
        return cleaned

    def _prune_records(self, user_id: int, now: datetime) -> None:
        records = self._recent_messages.get(user_id, [])
        if not records:
            return
        self._recent_messages[user_id] = [
            record for record in records if now - record.created_at <= self.spam_window
        ]

    async def _notify_staff(
        self,
        member: discord.Member,
        details: str,
        context: str,
    ) -> None:
        message = (
            f"{context} alert for {member} (ID: {member.id}).\n"
            f"{details}"
        )
        for user_id in self.notification_user_ids:
            try:
                user = self.bot.get_user(user_id)
                if not user:
                    user = await self.bot.fetch_user(user_id)
                if user:
                    await user.send(message)
            except discord.Forbidden:
                logger.warning("Cannot DM user %s for safety alert", user_id)
            except Exception as exc:
                logger.error("Failed to notify user %s: %s", user_id, exc)
