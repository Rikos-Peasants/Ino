import discord
from discord.ext import commands
from models.role_manager import RoleManager
from models.quest_manager import QuestManager
from models.mod_offline_manager import ModOfflineManager
from views.embeds import EmbedViews
from views.forum_thread_view import ForumThreadView
from views.ask_staff_topic_view import AskStaffTopicView
from config import Config
from models.user_safety_monitor import UserSafetyMonitor
from models.translation_manager import TranslationManager
import logging
import asyncio
import random
import re
from datetime import datetime, timedelta
from collections import Counter
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Quest tracking constants
QUALITY_POST_MIN_LIKES = 4  # Minimum likes for "Quality Control (Expert)" quest
TRENDING_POST_MIN_LIKES = 7  # Minimum likes for "Trending Creator" quest
VIRAL_IMAGE_MIN_LIKES = 15  # Minimum likes for "viral_image" quest
AI_MODERATION_TIMEOUT_THRESHOLD = 0.85  # 85% confidence required for auto-timeout
AI_MODERATION_TIMEOUT_DURATION = timedelta(minutes=5)
INO_INSULT_ROAST_CHANCE = 5
INO_INSULT_TIMEOUT_CHANCE = 100
INO_INSULT_TIMEOUT_DURATION = timedelta(minutes=1)
INO_INSULT_ROAST_COOLDOWN = timedelta(minutes=10)
IMAGE_CHANNEL_REMINDER_IMAGE_URL = "https://i.ibb.co/B2W5WQ2Y/ef4f7402-aa4b-4440-9ae9-ef1415824688.png"

# Ping spam detection constants
PING_SPAM_SAME_USER_LIMIT = 3       # 3 pings to the same person
PING_SPAM_MASS_USER_LIMIT = 7       # 7 unique user pings
PING_SPAM_WINDOW = timedelta(minutes=2)  # within 2 minutes
PING_SPAM_TIMEOUT_DURATION = timedelta(minutes=5)
REPEATED_MESSAGE_SPAM_LIMIT = 3
REPEATED_MESSAGE_SPAM_WINDOW = timedelta(seconds=10)
REPEATED_MESSAGE_SPAM_TIMEOUT_DURATION = timedelta(minutes=5)
REPEATED_MESSAGE_SPAM_INOREP_PENALTY = -100

DISCORD_INVITE_REGEX = re.compile(
    r"https?://(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/[A-Za-z0-9-]+",
    re.IGNORECASE
)

def _truncate_text(value: str, limit: int = 1000) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return value[:limit - 3].rstrip() + "..."


class TranslationConsentView(discord.ui.View):
    """One-time consent controls before sending a user's messages to translation providers."""

    def __init__(self, controller: "EventsController", source_message: discord.Message):
        super().__init__(timeout=60)
        self.controller = controller
        self.source_message = source_message
        self.prompt_message: Optional[discord.Message] = None
        self.processed = False

    async def _delete_prompt(self) -> None:
        if not self.prompt_message:
            return

        try:
            await self.prompt_message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def _ensure_sender(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.source_message.author.id:
            return True

        await interaction.response.send_message(
            "Only the message sender can choose this translation setting.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        await self._delete_prompt()

    @discord.ui.button(label="Agree", style=discord.ButtonStyle.green)
    async def agree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._ensure_sender(interaction):
            return

        if self.processed:
            await interaction.response.send_message("This translation choice was already handled.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("Translation opt-in only works in the server.", ephemeral=True)
            return

        self.processed = True
        await interaction.response.defer(ephemeral=True, thinking=True)
        success = await self.controller.translation_manager.set_user_preference(
            user_id=interaction.user.id,
            guild_id=interaction.guild.id,
            opted_in=True,
            user_name=getattr(interaction.user, "display_name", interaction.user.name),
        )
        await self._delete_prompt()

        if not success:
            await interaction.followup.send("I could not save your translation choice right now.", ephemeral=True)
            return

        self.controller.translation_manager.reset_consent_prompt_count(
            user_id=interaction.user.id,
            guild_id=interaction.guild.id,
        )
        await self.controller._process_auto_translate_message(self.source_message)
        await self.controller._send_language_prompt_dm(
            user_id=interaction.user.id,
            guild_id=interaction.guild.id,
        )
        await interaction.followup.send("You opted into the translation program.", ephemeral=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.gray)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._ensure_sender(interaction):
            return

        if self.processed:
            await interaction.response.send_message("This translation choice was already handled.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("Translation opt-out only works in the server.", ephemeral=True)
            return

        self.processed = True
        await interaction.response.defer(ephemeral=True)
        success = await self.controller.translation_manager.set_user_preference(
            user_id=interaction.user.id,
            guild_id=interaction.guild.id,
            opted_in=False,
            user_name=getattr(interaction.user, "display_name", interaction.user.name),
        )
        self.controller.translation_manager.reset_consent_prompt_count(
            user_id=interaction.user.id,
            guild_id=interaction.guild.id,
        )
        await self._delete_prompt()

        if not success:
            await interaction.followup.send("I could not save your translation choice right now.", ephemeral=True)
            return

        await interaction.followup.send(
            "You opted out. Please only speak English here so the moderators can moderate your messages.",
            ephemeral=True,
        )


class TranslationReviewApproveView(discord.ui.View):
    """Review-channel controls for approved translation overrides."""

    def __init__(
        self,
        controller: "EventsController",
        original_content: str,
        source_language: str,
        translated_text: str,
        source_message_id: int,
    ):
        super().__init__(timeout=7 * 24 * 60 * 60)
        self.controller = controller
        self.original_content = original_content
        self.source_language = source_language
        self.translated_text = translated_text
        self.source_message_id = source_message_id
        self.processed = False

    @discord.ui.button(label="Approve Future Use", style=discord.ButtonStyle.green)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.controller._is_translation_moderator(interaction):
            await interaction.response.send_message("You do not have permission to approve translations.", ephemeral=True)
            return

        if self.processed:
            await interaction.response.send_message("This translation review was already approved.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("This can only be approved in a server.", ephemeral=True)
            return

        success = await self.controller.translation_manager.save_approved_translation(
            original_content=self.original_content,
            source_language=self.source_language,
            translated_text=self.translated_text,
            moderator_id=interaction.user.id,
            moderator_name=getattr(interaction.user, "display_name", interaction.user.name),
            guild_id=interaction.guild.id,
        )
        if not success:
            await interaction.response.send_message("Could not save the approved translation.", ephemeral=True)
            return

        self.processed = True
        button.disabled = True
        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.add_field(
                name="Approved",
                value=f"Approved by {getattr(interaction.user, 'display_name', interaction.user.name)} for future use.",
                inline=False,
            )
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)


class TranslationCorrectionModal(discord.ui.Modal):
    """Collect the reporter's corrected English translation."""

    def __init__(self, response_view: "TranslationResponseView"):
        super().__init__(title="Translated correctly")
        self.response_view = response_view
        self.corrected_translation = discord.ui.TextInput(
            label="Proper English translation",
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=1000,
            required=True,
            placeholder="Enter the corrected English translation...",
            default=response_view.translated_text[:1000],
        )
        self.add_item(self.corrected_translation)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.response_view.submit_wrong_translation(
            interaction,
            str(self.corrected_translation.value).strip(),
        )


class TranslationResponseView(discord.ui.View):
    """Controls attached to Ino's public translation reply.

    Button flow:
    1. Initially shows "Wrong, Try Again" + "Wrong Language" + "Translated correctly"
    2. After retry: removes "Wrong, Try Again", adds "Translation Wrong" in its place
    """

    def __init__(
        self,
        controller: "EventsController",
        source_message: discord.Message,
        source_language: str,
        translated_text: str,
    ):
        super().__init__(timeout=24 * 60 * 60)
        self.controller = controller
        self.source_message_id = source_message.id
        self.source_channel_id = source_message.channel.id
        self.source_author_id = source_message.author.id
        self.source_author_name = source_message.author.display_name
        self.source_message_url = source_message.jump_url
        self.original_content = source_message.content or ""
        self.source_language = source_language
        self.translated_text = translated_text
        self.review_sent = False
        self.retry_used = False
        self.translation_message: Optional[discord.Message] = None

    def _disable_button_by_label(self, label: str) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.label == label:
                item.disabled = True

    async def _edit_translation_message_view(self, interaction: discord.Interaction) -> None:
        target_message = interaction.message or self.translation_message
        if target_message:
            await target_message.edit(view=self)

    async def _is_allowed_user(self, interaction: discord.Interaction) -> bool:
        """Allow the original message sender OR moderators to use buttons."""
        if interaction.user.id == self.source_author_id:
            return True
        return await self.controller._is_translation_moderator(interaction)

    @discord.ui.button(label="Wrong, Try Again", style=discord.ButtonStyle.blurple)
    async def retry_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._is_allowed_user(interaction):
            await interaction.response.send_message(
                "Only the original sender or a moderator can use this.", ephemeral=True
            )
            return

        if self.retry_used:
            await interaction.response.send_message("You already used the retry for this translation.", ephemeral=True)
            return

        self.retry_used = True
        await interaction.response.defer(ephemeral=True, thinking=True)

        retry_result = await self.controller.translation_manager.retry_with_gemini(
            self.original_content,
            self.source_language,
        )

        # Remove retry button, add "Translation Wrong" button in its place
        self.remove_item(self.retry_button)
        wrong_btn = discord.ui.Button(label="Translation Wrong", style=discord.ButtonStyle.gray)
        wrong_btn.callback = self._wrong_button_callback
        self.add_item(wrong_btn)

        if not retry_result:
            if interaction.message:
                await interaction.message.edit(view=self)
            await interaction.followup.send(
                f"Could not get a better translation. Detected language: **{self.source_language}**\n"
                "You can now report it as wrong.",
                ephemeral=True,
            )
            return

        self.source_language = retry_result.source_language
        self.translated_text = retry_result.translated_text
        if retry_result.translated_text == self.original_content:
            await interaction.followup.send(
                "Retry produced the same text. No change made.",
                ephemeral=True,
            )
            return
        if interaction.message:
            await interaction.message.edit(
                content=self.controller._format_auto_translation_reply(
                    retry_result.source_language,
                    retry_result.translated_text,
                ),
                view=self,
                allowed_mentions=discord.AllowedMentions.none(),
                suppress=True,
            )
        await interaction.followup.send(
            f"Retried with Gemini. Detected language: **{retry_result.source_language}**\n"
            "If it's still wrong, press \"Translation Wrong\" to report it.",
            ephemeral=True,
        )

    async def _wrong_button_callback(self, interaction: discord.Interaction):
        """Callback for the dynamically added 'Translation Wrong' button."""
        if not await self._is_allowed_user(interaction):
            await interaction.response.send_message(
                "Only the original sender or a moderator can use this.", ephemeral=True
            )
            return

        if self.review_sent:
            await interaction.response.send_message("This translation has already been sent for review.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("Translation reviews can only be created in the server.", ephemeral=True)
            return

        await interaction.response.send_modal(TranslationCorrectionModal(self))

    @discord.ui.button(label="Wrong Language", style=discord.ButtonStyle.red)
    async def wrong_language_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._is_allowed_user(interaction):
            await interaction.response.send_message(
                "Only the original sender or a moderator can use this.", ephemeral=True
            )
            return

        if not interaction.guild:
            await interaction.response.send_message("This can only be used in the server.", ephemeral=True)
            return

        await interaction.response.send_modal(WrongLanguageModal(self))

    async def submit_wrong_language(self, interaction: discord.Interaction, actual_language: str):
        """Handle wrong language report — log to review channel."""
        if not interaction.guild:
            await interaction.followup.send("This can only be used in the server.", ephemeral=True)
            return

        review_channel = interaction.guild.get_channel(Config.AUTO_TRANSLATE_REVIEW_CHANNEL_ID)
        if review_channel is None:
            try:
                review_channel = await interaction.guild.fetch_channel(Config.AUTO_TRANSLATE_REVIEW_CHANNEL_ID)
            except Exception:
                review_channel = None

        if not review_channel or not hasattr(review_channel, "send"):
            await interaction.followup.send("Could not find the translation review channel.", ephemeral=True)
            return

        reporter_is_mod = await self.controller._is_translation_moderator(interaction)
        embed = discord.Embed(
            title="Wrong Language Report",
            color=discord.Color.red(),
        )
        embed.add_field(name="Original Text", value=_truncate_text(self.original_content), inline=False)
        embed.add_field(name="Detected As", value=self.source_language, inline=True)
        embed.add_field(name="Actual Language", value=actual_language or "Unknown", inline=True)
        embed.add_field(name="Translation Given", value=_truncate_text(self.translated_text), inline=False)
        embed.add_field(name="Original Author", value=f"{self.source_author_name} ({self.source_author_id})", inline=True)
        embed.add_field(
            name="Reported By",
            value=f"{getattr(interaction.user, 'display_name', interaction.user.name)} ({interaction.user.id})"
                  f"{' - moderator' if reporter_is_mod else ''}",
            inline=False,
        )
        embed.add_field(name="Source", value=f"[Jump to message]({self.source_message_url})", inline=False)

        await review_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

        self.wrong_language_button.disabled = True
        await self._edit_translation_message_view(interaction)
        await interaction.followup.send(
            f"Reported wrong language. Detected **{self.source_language}**, you said it's **{actual_language}**.",
            ephemeral=True,
        )

    async def submit_wrong_translation(self, interaction: discord.Interaction, corrected_translation: str):
        if self.review_sent:
            await interaction.followup.send("This translation has already been sent for review.", ephemeral=True)
            return

        if not corrected_translation:
            await interaction.followup.send("Please enter the corrected translation.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.followup.send("Translation reviews can only be created in the server.", ephemeral=True)
            return

        review_channel = interaction.guild.get_channel(Config.AUTO_TRANSLATE_REVIEW_CHANNEL_ID)
        if review_channel is None:
            try:
                review_channel = await interaction.guild.fetch_channel(Config.AUTO_TRANSLATE_REVIEW_CHANNEL_ID)
            except Exception:
                review_channel = None

        if not review_channel or not hasattr(review_channel, "send"):
            await interaction.followup.send("I could not find the translation review channel.", ephemeral=True)
            return

        reporter_is_mod = await self.controller._is_translation_moderator(interaction)
        embed = discord.Embed(
            title="Translation Review",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Original", value=_truncate_text(self.original_content), inline=False)
        embed.add_field(name="AI Translation", value=_truncate_text(self.translated_text), inline=False)
        embed.add_field(name="Suggested Correction", value=_truncate_text(corrected_translation), inline=False)
        embed.add_field(name="Detected Language", value=f"{self.source_language}", inline=True)
        embed.add_field(name="Translation", value=f"{self.source_language} → EN", inline=True)
        embed.add_field(name="Original Author", value=f"{self.source_author_name} ({self.source_author_id})", inline=True)
        embed.add_field(
            name="Reported By",
            value=f"{getattr(interaction.user, 'display_name', interaction.user.name)} ({interaction.user.id})"
                  f"{' - moderator' if reporter_is_mod else ''}",
            inline=False,
        )
        embed.add_field(name="Source", value=f"[Jump to message]({self.source_message_url})", inline=False)
        embed.set_footer(text="Approve only if this translation should be reused for the same message text.")

        view = TranslationReviewApproveView(
            controller=self.controller,
            original_content=self.original_content,
            source_language=self.source_language,
            translated_text=corrected_translation,
            source_message_id=self.source_message_id,
        )
        await review_channel.send(
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.review_sent = True
        self._disable_button_by_label("Translation Wrong")
        await self._edit_translation_message_view(interaction)
        await interaction.followup.send(
            f"Sent for review. Detected language was **{self.source_language}**.",
            ephemeral=True,
        )

    @discord.ui.button(label="Translated correctly", style=discord.ButtonStyle.green)
    async def correct_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._is_allowed_user(interaction):
            await interaction.response.send_message(
                "Only the original sender or a moderator can use this.", ephemeral=True
            )
            return

        self.clear_items()
        if interaction.message:
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("Marked as correct.", ephemeral=True)


class WrongLanguageModal(discord.ui.Modal):
    """Collect the actual language when the detected language was wrong."""

    def __init__(self, response_view: "TranslationResponseView"):
        super().__init__(title=f"Wrong language (detected: {response_view.source_language})")
        self.response_view = response_view
        self.actual_language = discord.ui.TextInput(
            label="What is the actual language?",
            style=discord.TextStyle.short,
            min_length=1,
            max_length=50,
            required=True,
            placeholder="e.g. Russian, Hindi, French, English...",
        )
        self.add_item(self.actual_language)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.response_view.submit_wrong_language(
            interaction,
            str(self.actual_language.value).strip(),
        )


LANGUAGE_CODE_MAP = {
    "en": "EN", "english": "EN",
    "jp": "JP", "japan": "JP", "japanese": "JP",
    "fr": "FR", "french": "FR",
    "es": "ES", "spanish": "ES",
    "pt": "PT", "portuguese": "PT",
    "de": "DE", "german": "DE", "deutsch": "DE",
    "it": "IT", "italian": "IT",
    "nl": "NL", "dutch": "NL",
    "ru": "RU", "russian": "RU",
    "ar": "AR", "arabic": "AR",
    "hi": "HI", "hindi": "HI",
    "ko": "KO", "korean": "KO",
    "zh": "ZH", "chinese": "ZH",
    "tr": "TR", "turkish": "TR",
    "ta": "TA", "tamil": "TA",
    "si": "SI", "sinhala": "SI",
    "th": "TH", "thai": "TH",
    "vi": "VI", "vietnamese": "VI",
    "pl": "PL", "polish": "PL",
    "sv": "SV", "swedish": "SV",
    "da": "DA", "danish": "DA",
    "fi": "FI", "finnish": "FI",
    "nb": "NB", "no": "NB", "norwegian": "NB",
    "cs": "CS", "czech": "CS",
    "hu": "HU", "hungarian": "HU",
    "ro": "RO", "romanian": "RO",
    "el": "EL", "greek": "EL",
    "he": "IW", "iw": "IW", "hebrew": "IW",
    "id": "ID", "indonesian": "ID",
    "ms": "MS", "malay": "MS",
    "fil": "FIL", "tagalog": "FIL",
    "uk": "UK", "ukrainian": "UK",
}


def _parse_languages(raw: str) -> list[str]:
    """Parse a user-provided language string into ISO codes."""
    codes = set()
    for part in raw.replace(",", " ").split():
        part = part.strip().lower()
        if part in LANGUAGE_CODE_MAP:
            codes.add(LANGUAGE_CODE_MAP[part])
    return sorted(codes)


def _normalize_language_code(code: str) -> str:
    """Normalize language codes to handle deprecated aliases (e.g. HE → IW)."""
    ALIASES = {"HE": "IW"}
    return ALIASES.get(code.upper(), code.upper())


class LanguageModal(discord.ui.Modal):
    """Collect the languages a user speaks."""

    def __init__(self, controller: "EventsController", user_id: int, guild_id: int):
        super().__init__(title="What languages do you speak?")
        self.controller = controller
        self.target_user_id = user_id
        self.target_guild_id = guild_id
        self.languages_input = discord.ui.TextInput(
            label="Languages you speak",
            style=discord.TextStyle.short,
            min_length=1,
            max_length=200,
            required=True,
            placeholder="e.g. EN, JP, ES  or  English, Japanese, Spanish",
        )
        self.add_item(self.languages_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message("This isn't your language prompt.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        raw = str(self.languages_input.value).strip()
        parsed = _parse_languages(raw)
        if not parsed:
            await interaction.followup.send(
                "I couldn't recognize any languages. Try something like: `EN, JP, ES` or `English, Japanese, Spanish`",
                ephemeral=True,
            )
            return

        current = await self.controller.translation_manager.get_user_languages(
            self.target_user_id, self.target_guild_id,
        )
        merged = sorted(set(current + parsed))

        success = await self.controller.translation_manager.set_user_languages(
            user_id=self.target_user_id,
            guild_id=self.target_guild_id,
            languages=merged,
        )
        if not success:
            await interaction.followup.send("Could not save your languages right now.", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ Saved! I'll translate messages in: **{', '.join(merged)}**\n"
            f"Use `/language add` or `/language remove` anytime to update your list.",
            ephemeral=True,
        )


class LanguagePromptView(discord.ui.View):
    """DM prompt with a button to open the language modal."""

    def __init__(self, controller: "EventsController", target_user_id: int, guild_id: int):
        super().__init__(timeout=24 * 60 * 60)
        self.controller = controller
        self.target_user_id = target_user_id
        self.guild_id = guild_id

    @discord.ui.button(label="Set Your Languages ✏️", style=discord.ButtonStyle.primary)
    async def set_languages_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message("This isn't your language prompt.", ephemeral=True)
            return

        await interaction.response.send_modal(LanguageModal(self.controller, self.target_user_id, self.guild_id))


class EventsController:
    """Controller for handling Discord events"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spam_channel_message_count = 0  # Track messages in spam channel
        self.quest_manager = None  # Will be initialized when bot is ready
        self.user_safety_monitor = UserSafetyMonitor(bot)
        leaderboard_manager = getattr(bot, 'leaderboard_manager', None)
        translation_db = getattr(leaderboard_manager, 'db', None)
        self.translation_manager = TranslationManager(db=translation_db)
        # Ping spam tracking: {author_id: [(target_id, timestamp, message_id), ...]}
        self._ping_history: Dict[int, List[tuple]] = {}
        # Track which authors have been timed out recently to avoid re-triggering
        self._ping_timeout_cooldown: Dict[int, datetime] = {}
        # Repeated message spam tracking: {(author_id, channel_id, normalized_content): [timestamps, ...]}
        self._repeated_message_history: Dict[tuple, List[datetime]] = {}
        self._repeated_message_timeout_cooldown: Dict[int, datetime] = {}
        # Image-channel reminders are channel-wide: warn once, then every 40 ignored text messages.
        self._image_channel_text_since_reminder: Dict[int, int] = {}
        # Keep Ino's insult replies from becoming a reply loop.
        self._ino_insult_roast_cooldown: Dict[tuple, datetime] = {}
        # Maps original message ID -> translation/consent reply message, so we can
        # delete the reply automatically when the original message is deleted.
        self._translation_replies: Dict[int, discord.Message] = {}
        # Maps translated message ID -> source language code, for reverse translation
        # when someone replies to a translated message.
        self._translated_message_languages: Dict[int, str] = {}
    
    def get_mod_offline_manager(self) -> Optional[ModOfflineManager]:
        """Get the mod offline manager from the commands controller"""
        commands_controller = getattr(self.bot, 'commands_controller', None)
        if commands_controller:
            return getattr(commands_controller, 'mod_offline_manager', None)
        return None

    async def _apply_youtube_sub_role_on_join(self, member: discord.Member) -> None:
        """Apply a YouTube subscriber-era role when a member joins."""
        try:
            commands_controller = getattr(self.bot, 'commands_controller', None)
            if not commands_controller or not hasattr(commands_controller, 'apply_stored_youtube_sub_role'):
                return

            success, result = await commands_controller.apply_stored_youtube_sub_role(member)
            if success:
                logger.info(f"Applied YouTube subscriber role to {member.display_name}: {result}")
            else:
                logger.warning(f"No YouTube subscriber role applied to {member.display_name}: {result}")
        except Exception as e:
            logger.error(f"Error applying stored YouTube subscriber role to {member.display_name}: {e}")
    
    def register_events(self):
        """Register all Discord events"""
        
        @self.bot.event
        async def on_member_join(member: discord.Member):
            await self._handle_member_join(member)
        
        @self.bot.event
        async def on_member_remove(member: discord.Member):
            await self._handle_member_leave(member)
        
        @self.bot.event
        async def on_member_update(before: discord.Member, after: discord.Member):
            await self._handle_member_update(before, after)
        
        @self.bot.event
        async def on_message(message: discord.Message):
            await self._handle_message(message)
        
        @self.bot.event
        async def on_message_delete(message: discord.Message):
            await self._handle_message_delete(message)
        
        @self.bot.event
        async def on_command_error(ctx: commands.Context, error: commands.CommandError):
            await self._handle_command_error(ctx, error)
        
        @self.bot.event
        async def on_command(ctx: commands.Context):
            """Log when commands are successfully invoked"""
            # Handle DM channels
            channel_name = ctx.channel.name if hasattr(ctx.channel, 'name') else 'DM'
            logger.info(f"Command '{ctx.command.name}' invoked by {ctx.author.display_name} in #{channel_name}")
        
        @self.bot.event
        async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
            await self._handle_reaction_change(reaction, user, added=True)
        
        @self.bot.event
        async def on_reaction_remove(reaction: discord.Reaction, user: discord.User):
            await self._handle_reaction_change(reaction, user, added=False)
        
        @self.bot.event
        async def on_thread_create(thread: discord.Thread):
            logger.info(f"Thread create event triggered: {thread.name} (ID: {thread.id}) in channel {thread.parent_id}")
            await self._handle_thread_create(thread)
        

        
        @self.bot.event
        async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
            await self._handle_voice_state_update(member, before, after)
    
    async def _handle_member_join(self, member: discord.Member):
        """Handle member join events to reapply NSFWBAN role if needed and send welcome message"""
        # Only process events from the configured guild
        if member.guild.id != Config.GUILD_ID:
            return
        
        try:
            # Check if the user is in the NSFWBAN database
            if await self.bot.leaderboard_manager.is_nsfwban_user(member.id):
                # Get the NSFWBAN banned role (the role applied to banned users)
                nsfwban_role = discord.utils.get(member.guild.roles, id=Config.NSFWBAN_BANNED_ROLE_ID)
                
                if nsfwban_role:
                    # Add the banned role back to the user
                    await member.add_roles(nsfwban_role, reason="Reapplying NSFWBAN role on rejoin")
                    logger.info(f"Reapplied NSFWBAN role to {member.display_name} on rejoin")
                    
                    # Also remove the NSFW/restricted role if they somehow have it
                    restricted_role = discord.utils.get(member.guild.roles, id=Config.RESTRICTED_ROLE_ID)
                    if restricted_role and restricted_role in member.roles:
                        await member.remove_roles(restricted_role, reason="NSFWBAN user - removing NSFW access on rejoin")
                        logger.info(f"Removed NSFW role from {member.display_name} on rejoin (NSFWBAN user)")
                    
                    # Get ban info for DM
                    ban_info = await self.bot.leaderboard_manager.get_nsfwban_user_info(member.id)
                    reason = ban_info.get('reason', 'No reason provided') if ban_info else 'No reason provided'
                    
                    # Send DM notification
                    try:
                        dm_embed = EmbedViews.nsfwban_dm_embed(reason, member.guild.name)
                        await member.send(embed=dm_embed)
                    except discord.Forbidden:
                        # User has DMs disabled, that's okay
                        pass
                    except Exception as e:
                        logger.error(f"Failed to send NSFWBAN rejoin DM to {member.display_name}: {e}")
                else:
                    logger.error(f"NSFWBAN role not found when trying to reapply to {member.display_name}")
            
            # Send welcome message if enabled
            await self._apply_youtube_sub_role_on_join(member)
            await self._send_welcome_message(member)
            await self.user_safety_monitor.handle_member_join(member)
                    
        except Exception as e:
            logger.error(f"Error handling member join for NSFWBAN reapplication: {e}")
    
    async def _handle_member_leave(self, member: discord.Member):
        """Handle member leave events and send leave message"""
        # Only process events from the configured guild
        if member.guild.id != Config.GUILD_ID:
            return
        
        try:
            # Send leave message if enabled
            await self._send_leave_message(member)
        except Exception as e:
            logger.error(f"Error handling member leave: {e}")
    
    async def _send_welcome_message(self, member: discord.Member):
        """Send welcome message to configured channel"""
        try:
            # Check if welcome system is enabled
            if not await self.bot.leaderboard_manager.is_welcome_enabled(member.guild.id):
                return
            
            # Get welcome channel
            welcome_channel_id = await self.bot.leaderboard_manager.get_welcome_channel(member.guild.id)
            if not welcome_channel_id:
                return
            
            welcome_channel = member.guild.get_channel(welcome_channel_id)
            if not welcome_channel:
                logger.warning(f"Welcome channel {welcome_channel_id} not found")
                return
            
            # Get welcome message template
            welcome_message_data = await self.bot.leaderboard_manager.get_welcome_message(member.guild.id)
            if not welcome_message_data:
                # Default welcome message
                welcome_message_data = {
                    "content": "Welcome {usermention}! 🎉"
                }
            
            # Process message with placeholders
            processed_message = await self._process_welcome_leave_message(welcome_message_data, member, "welcome")
            
            # Send the message
            await welcome_channel.send(**processed_message)
            logger.info(f"Sent welcome message for {member.display_name} in #{welcome_channel.name}")
            
        except Exception as e:
            logger.error(f"Error sending welcome message: {e}")
    
    async def _send_leave_message(self, member: discord.Member):
        """Send leave message to configured channel"""
        try:
            # Check if leave system is enabled
            if not await self.bot.leaderboard_manager.is_leave_enabled(member.guild.id):
                return
            
            # Get leave channel
            leave_channel_id = await self.bot.leaderboard_manager.get_leave_channel(member.guild.id)
            if not leave_channel_id:
                return
            
            leave_channel = member.guild.get_channel(leave_channel_id)
            if not leave_channel:
                logger.warning(f"Leave channel {leave_channel_id} not found")
                return
            
            # Get leave message template
            leave_message_data = await self.bot.leaderboard_manager.get_leave_message(member.guild.id)
            if not leave_message_data:
                # Default leave message
                leave_message_data = {
                    "content": "Goodbye {displayname}! 👋"
                }
            
            # Process message with placeholders
            processed_message = await self._process_welcome_leave_message(leave_message_data, member, "leave")
            
            # Send the message
            await leave_channel.send(**processed_message)
            logger.info(f"Sent leave message for {member.display_name} in #{leave_channel.name}")
            
        except Exception as e:
            logger.error(f"Error sending leave message: {e}")
    
    async def _process_welcome_leave_message(self, message_data: dict, member: discord.Member, message_type: str) -> dict:
        """Process welcome/leave message with placeholders"""
        import copy
        processed_data = copy.deepcopy(message_data)
        
        # Define placeholders
        placeholders = {
            "{usermention}": member.mention,
            "{displayname}": member.display_name,
            "{username}": member.name,
            "{userid}": str(member.id),
            "{userurl}": f"https://discord.com/users/{member.id}",
            "{useravatar}": str(member.display_avatar.url) if member.display_avatar else "",
            "{membercount}": str(member.guild.member_count),
            "{guildname}": member.guild.name,
            "{guildid}": str(member.guild.id)
        }
        
        def replace_placeholders(text):
            """Replace placeholders in text"""
            if not isinstance(text, str):
                return text
            for placeholder, value in placeholders.items():
                text = text.replace(placeholder, value)
            return text
        
        # Process content
        if "content" in processed_data:
            processed_data["content"] = replace_placeholders(processed_data["content"])
        
        # Process embeds
        if "embeds" in processed_data:
            for embed_data in processed_data["embeds"]:
                # Process embed fields
                for field_name in ["title", "description"]:
                    if field_name in embed_data:
                        embed_data[field_name] = replace_placeholders(embed_data[field_name])
                
                # Process embed author
                if "author" in embed_data:
                    for author_field in ["name", "url", "icon_url"]:
                        if author_field in embed_data["author"]:
                            embed_data["author"][author_field] = replace_placeholders(embed_data["author"][author_field])
                
                # Process embed footer
                if "footer" in embed_data:
                    for footer_field in ["text", "icon_url"]:
                        if footer_field in embed_data["footer"]:
                            embed_data["footer"][footer_field] = replace_placeholders(embed_data["footer"][footer_field])
                
                # Process embed fields
                if "fields" in embed_data:
                    for field in embed_data["fields"]:
                        if "name" in field:
                            field["name"] = replace_placeholders(field["name"])
                        if "value" in field:
                            field["value"] = replace_placeholders(field["value"])
                
                # Process embed image and thumbnail
                for image_field in ["image", "thumbnail"]:
                    if image_field in embed_data and "url" in embed_data[image_field]:
                        embed_data[image_field]["url"] = replace_placeholders(embed_data[image_field]["url"])
            
            # Convert embed data to discord.Embed objects
            embeds = []
            for embed_data in processed_data["embeds"]:
                embed = discord.Embed()
                
                # Set basic embed properties
                if "title" in embed_data:
                    embed.title = embed_data["title"]
                if "description" in embed_data:
                    embed.description = embed_data["description"]
                if "color" in embed_data:
                    embed.color = embed_data["color"]
                if "url" in embed_data:
                    embed.url = embed_data["url"]
                if "timestamp" in embed_data:
                    embed.timestamp = embed_data["timestamp"]
                
                # Set embed author
                if "author" in embed_data:
                    author = embed_data["author"]
                    author_kwargs = {"name": author.get("name", "")}
                    if "url" in author and author["url"]:
                        author_kwargs["url"] = author["url"]
                    if "icon_url" in author and author["icon_url"]:
                        author_kwargs["icon_url"] = author["icon_url"]
                    embed.set_author(**author_kwargs)
                
                # Set embed footer
                if "footer" in embed_data:
                    footer = embed_data["footer"]
                    footer_kwargs = {"text": footer.get("text", "")}
                    if "icon_url" in footer and footer["icon_url"]:
                        footer_kwargs["icon_url"] = footer["icon_url"]
                    embed.set_footer(**footer_kwargs)
                
                # Add embed fields
                if "fields" in embed_data:
                    for field in embed_data["fields"]:
                        embed.add_field(
                            name=field.get("name", ""),
                            value=field.get("value", ""),
                            inline=field.get("inline", False)
                        )
                
                # Set embed image
                if "image" in embed_data and "url" in embed_data["image"]:
                    embed.set_image(url=embed_data["image"]["url"])
                
                # Set embed thumbnail
                if "thumbnail" in embed_data and "url" in embed_data["thumbnail"]:
                    embed.set_thumbnail(url=embed_data["thumbnail"]["url"])
                
                embeds.append(embed)
            
            processed_data["embeds"] = embeds
        
        return processed_data
    
    async def _handle_member_join_message(self, message: discord.Message):
        """Handle Discord system messages for member joins and reply with sticker"""
        try:
            # Check if this is a system message for member join
            if message.type == discord.MessageType.new_member:
                sticker_id = 1391462726781505536
                sticker_image_url = "https://media.discordapp.net/stickers/1391462726781505536.webp?size=160&quality=lossless"
                
                # Check if it's Christmas time (Dec 24-26)
                now = datetime.now()
                is_christmas = now.month == 12 and now.day in [24, 25, 26]
                christmas_msg = "Merry Christmas! 🎄" if is_christmas else None
                
                # Try to send the sticker first
                sticker_sent = False
                try:
                    sticker = await self.bot.fetch_sticker(sticker_id)
                    if sticker:
                        if christmas_msg:
                            await message.reply(content=christmas_msg, stickers=[sticker])
                        else:
                            await message.reply(stickers=[sticker])
                        sticker_sent = True
                        logger.info(f"Sent welcome sticker for member join in #{getattr(message.channel, 'name', 'DM')}")
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    logger.warning(f"Could not send sticker (ID {sticker_id}), falling back to image: {e}")
                
                # Fallback to image URL if sticker failed
                if not sticker_sent:
                    if christmas_msg:
                        await message.reply(content=f"{christmas_msg}\n{sticker_image_url}")
                    else:
                        await message.reply(content=sticker_image_url)
                    logger.info(f"Sent welcome sticker image for member join in #{getattr(message.channel, 'name', 'DM')}")
                    
        except discord.Forbidden as e:
            logger.error(f"Missing permission to send messages for member joins: {e}")
        except discord.HTTPException as e:
            logger.error(f"HTTP error sending welcome for member join: {e}")
        except Exception as e:
            logger.error(f"Error handling member join message: {e}")

    def _message_has_media(self, message: discord.Message, include_video: bool = True) -> bool:
        """Check whether a message contains image/video media."""
        image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
        video_extensions = ('.mp4', '.mov', '.webm', '.avi', '.mkv')
        allowed_extensions = image_extensions + video_extensions if include_video else image_extensions

        for attachment in message.attachments:
            if attachment.filename.lower().endswith(allowed_extensions):
                return True

        for embed in message.embeds:
            if embed.image or embed.thumbnail:
                return True
            if include_video and embed.video:
                return True

        return False

    async def _is_reply_to_media_message(self, message: discord.Message, include_video: bool = True) -> bool:
        """Return True when this message replies to a message that contains media."""
        if not message.reference or not message.reference.message_id:
            return False

        try:
            referenced_msg = await message.channel.fetch_message(message.reference.message_id)
        except (discord.NotFound, discord.Forbidden):
            return False
        except Exception as e:
            logger.debug(f"Could not fetch referenced message {message.reference.message_id}: {e}")
            return False

        return self._message_has_media(referenced_msg, include_video=include_video)
    
    async def _handle_member_update(self, before: discord.Member, after: discord.Member):
        """Handle member role updates"""
        # Only process events from the configured guild
        if after.guild.id != Config.GUILD_ID:
            return

        await self.user_safety_monitor.handle_member_update(before, after)
        
        # Get role changes
        roles_added = set(after.roles) - set(before.roles)
        
        # Check if the restricted role was added
        restricted_role = RoleManager.get_restricted_role(after.guild)
        if restricted_role in roles_added:
            # Check if user has banned role
            if RoleManager.has_banned_role(after):
                try:
                    # Remove the restricted role
                    await after.remove_roles(restricted_role, reason="User is banned from this role")
                    
                    # Send DM with access denied embed
                    embed = EmbedViews.access_denied_embed()
                    try:
                        await after.send(embed=embed)
                    except discord.Forbidden:
                        # If DM fails, we could log this or send to a mod channel
                        pass
                        
                except discord.Forbidden:
                    # Bot doesn't have permission to remove roles
                    print(f"Failed to remove role from {after.display_name}: Missing permissions")
                except Exception as e:
                    print(f"Error handling role update for {after.display_name}: {e}")
    
    async def _handle_message(self, message: discord.Message):
        """Handle new messages for image reactions and member join stickers"""
        # Check for member join system messages FIRST (before ignoring bot messages)
        if message.guild and message.guild.id == Config.GUILD_ID:
            await self._handle_member_join_message(message)
        
        # Ignore bot messages for regular processing
        if message.author.bot:
            if (
                getattr(Config, "SCAM_IMAGE_SCAN_BOT_MESSAGES", False)
                and message.guild
                and message.guild.id == Config.GUILD_ID
                and message.attachments
            ):
                await self._handle_scam_image_detection(message)
            return
        
        # Handle mod offline system (auto-logon and ping detection)
        await self._handle_mod_offline_system(message)
        
        # Log message if it starts with command prefix
        if message.content.startswith('R!'):
            logger.info(f"Received command: {message.content} from {message.author.display_name}")
        
        # IMPORTANT: Process commands first for text commands to work
        await self.bot.process_commands(message)
        
        # Only process messages from the configured guild
        if not message.guild or message.guild.id != Config.GUILD_ID:
            return

        if await self._handle_scam_image_detection(message):
            return

        if await self._handle_discord_invite_link(message):
            return

        if await self._check_repeated_message_spam(message):
            return

        await self.user_safety_monitor.handle_message(message)
        
        # Check for ping spam (repeated pings to same user / mass pings)
        await self._check_ping_spam(message)
        
        # Check for positive Ino mentions first (reward good behavior!)
        await self._check_positive_ino_mention(message)
        
        # Check moderation before other processing
        await self._handle_message_moderation(message)
        
        # Check for spam channel flood detection
        await self._check_spam_channel_flood(message)
        
        # Award points for text messages (before other processing)
        await self._award_text_message_points(message)
        
        # Check for art challenge submissions (!submit command)
        await self._handle_art_challenge_submission(message)
        
        # Enforce spoilers in NSFW channels
        await self._check_nsfw_spoiler(message)

        # Translate non-English chat messages after moderation, but before image-channel handling.
        await self._maybe_auto_translate_message(message)
        
        # Check if message is in image reaction channels
        if message.channel.id not in Config.IMAGE_REACTION_CHANNELS:
            return
        
        # Check if message has images or videos
        has_image = False
        image_url = None
        is_tenor_gif = False
        is_video = False
        
        # Check for attachments (uploaded images or videos)
        for attachment in message.attachments:
            # Check for video files
            if any(attachment.filename.lower().endswith(ext) for ext in ['.mp4', '.mov', '.webm', '.avi', '.mkv']):
                has_image = True
                is_video = True
                image_url = attachment.url
                break
            # Check for image files (but not GIFs from tenor)
            elif any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                has_image = True
                image_url = attachment.url
                break
        
        # Check for embedded images/videos (links)
        if not has_image:
            for embed in message.embeds:
                # Check if it's a Tenor GIF by looking at the URL
                embed_url = embed.url or ""
                if "tenor.com" in embed_url.lower():
                    is_tenor_gif = True
                
                # Check for video embeds
                if embed.video:
                    has_image = True
                    is_video = True
                    image_url = embed.video.url if hasattr(embed.video, 'url') else str(embed.url)
                    break
                elif embed.image:
                    has_image = True
                    image_url = embed.image.url
                    # Check if the image URL is from Tenor
                    if "tenor.com" in image_url.lower():
                        is_tenor_gif = True
                    break
                elif embed.thumbnail:
                    has_image = True
                    image_url = embed.thumbnail.url
                    # Check if the thumbnail URL is from Tenor
                    if "tenor.com" in image_url.lower():
                        is_tenor_gif = True
                    break
        
        # React with thumbs up and thumbs down if image/video found
        # BUT: Skip reactions for Tenor GIFs (unless it's a video)
        if has_image and image_url and (not is_tenor_gif or is_video):
            try:
                await message.add_reaction('👍')
                await message.add_reaction('👎')
                await message.add_reaction('🔖')  # Bookmark emoji
                content_type = "video" if is_video else "image"
                logger.info(f"Added reactions to {content_type} in {message.channel.name} by {message.author.display_name}")
                
                # Store the image message in MongoDB
                await self.bot.leaderboard_manager.store_image_message(
                    message=message,
                    image_url=image_url,
                    initial_score=0
                )
                
                # Track the image post in leaderboard
                self.bot.leaderboard_manager.add_image_post(
                    user_id=message.author.id,
                    user_name=message.author.display_name,
                    initial_score=0  # Start with 0, will be updated when reactions happen
                )
                
                # Update quest progress and check achievements
                await self._update_quest_progress_and_achievements(message.author, message)
                
                # Reward InoRep for posting images
                await self._apply_image_post_inorep_reward(message)
                
            except discord.Forbidden:
                logger.error(f"Missing permission to add reactions in {message.channel.name}")
            except Exception as e:
                logger.error(f"Error adding reactions to message: {e}")
        elif has_image and is_tenor_gif and not is_video:
            # Log that we're skipping Tenor GIF
            logger.debug(f"Skipped reactions for Tenor GIF in {message.channel.name} by {message.author.display_name}")
            # Still treat as text message for reminder/penalty purposes
            await self._check_for_chat_reminder(message)
            await self._apply_text_spam_inorep_penalty(message)
        else:
            # This is a text message in an image channel, check if we need to send a reminder
            await self._check_for_chat_reminder(message)
            
            # Penalize InoRep for text spamming in image channels
            await self._apply_text_spam_inorep_penalty(message)

    async def _handle_discord_invite_link(self, message: discord.Message) -> bool:
        """Remove Discord invite links outside the self-promotion thread and DM the user."""
        if message.channel.id == Config.SELF_PROMO_WHITELIST_THREAD_ID:
            return False
        
        if isinstance(message.channel, discord.Thread) and message.channel.parent_id == Config.SELF_PROMO_WHITELIST_THREAD_ID:
            return False

        if not DISCORD_INVITE_REGEX.search(message.content or ""):
            return False

        try:
            await message.delete()
            logger.info(
                f"Removed Discord invite link from {message.author.display_name} in channel {message.channel.id}"
            )
        except discord.Forbidden:
            logger.warning("Missing permission to delete Discord invite link message")
            return False
        except discord.NotFound:
            return True
        except Exception as e:
            logger.error(f"Error deleting Discord invite message: {e}")
            return False

        try:
            await message.author.send(
                "Hey! Please DM your Discord invite link directly to the person of interest. "
                "We don't allow self-promotion links in the general server channels."
            )
        except discord.Forbidden:
            logger.info(f"Could not DM {message.author.display_name} about invite link removal (DMs disabled)")
        except Exception as e:
            logger.error(f"Error sending Discord invite warning DM: {e}")

        return True

    async def _maybe_auto_translate_message(self, message: discord.Message):
        """Prompt for consent, then reply with an English translation for opted-in users."""
        try:
            if not Config.AUTO_TRANSLATE_ENABLED:
                return

            if not self.translation_manager.is_configured:
                return

            if Config.AUTO_TRANSLATE_CHANNEL_IDS and message.channel.id not in Config.AUTO_TRANSLATE_CHANNEL_IDS:
                return

            content = (message.content or "").strip()
            if not content:
                return

            if content.startswith(Config.COMMAND_PREFIX) or content.startswith('/'):
                return

            # Reverse translation: if this message is a reply to a translated message,
            # translate the reply into the original language so the foreign speaker can read it.
            await self._maybe_reverse_translate_reply(message)

            preference = await self.translation_manager.get_user_preference(
                user_id=message.author.id,
                guild_id=message.guild.id,
            )
            if preference is False:
                return

            if preference is None:
                if not self.translation_manager.looks_translation_candidate(content):
                    return

                # Check if we've already asked too many times — auto opt-out
                prompt_count = self.translation_manager.increment_consent_prompt_count(
                    user_id=message.author.id,
                    guild_id=message.guild.id,
                )
                if prompt_count > self.translation_manager.MAX_CONSENT_PROMPTS:
                    await self.translation_manager.set_user_preference(
                        user_id=message.author.id,
                        guild_id=message.guild.id,
                        opted_in=False,
                        user_name=message.author.display_name,
                    )
                    self.translation_manager.reset_consent_prompt_count(
                        user_id=message.author.id,
                        guild_id=message.guild.id,
                    )
                    try:
                        await message.reply(
                            "You've been automatically opted out of translation "
                            f"after {self.translation_manager.MAX_CONSENT_PROMPTS} unanswered prompts. "
                            "Use `/translation opt-in` if you'd like to enable it later.",
                            mention_author=False,
                            delete_after=30,
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                    return

                view = TranslationConsentView(controller=self, source_message=message)
                prompt_message = await message.reply(
                    embed=self._format_translation_consent_prompt(),
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                    view=view,
                )
                view.prompt_message = prompt_message
                self._translation_replies[message.id] = prompt_message
                return

            await self._process_auto_translate_message(message)
        except discord.Forbidden:
            logger.warning(f"Missing permission to send auto-translation in #{message.channel.name}")
        except discord.NotFound:
            logger.debug("Skipped auto-translation reply because the source message no longer exists")
        except Exception as e:
            logger.error(f"Error auto-translating message: {e}")

    async def _maybe_reverse_translate_reply(self, message: discord.Message):
        """If someone replies to a previously translated message, translate their reply
        back into the original language so the foreign-language speaker can read it."""
        if not message.reference or not message.reference.message_id:
            return

        parent_id = message.reference.message_id
        source_language = self._translated_message_languages.get(parent_id)
        if not source_language:
            return

        # Don't reverse-translate non-English messages or very short messages
        content = (message.content or "").strip()
        if not content or len(content) < 2:
            return

        # Skip if the reply itself looks non-English (it's probably in the same language)
        if any(char.isalpha() and ord(char) > 127 for char in content):
            return

        # Clean language code (strip /CIPHER prefixes, -Latn suffixes etc.)
        lang_code = source_language.split("/")[-1].split("-")[0].lower()
        if lang_code == "en":
            return

        try:
            result = await self.translation_manager.translate_to_language(content, lang_code)
            if not result or not result.translated_text:
                return

            if result.translated_text == content:
                return

            reply_text = f"Translated EN to {lang_code.upper()}: {result.translated_text}"
            if len(reply_text) > 2000:
                reply_text = reply_text[:1997] + "..."

            await message.reply(
                reply_text,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
                suppress_embeds=True,
            )
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
        except Exception as e:
            logger.error(f"Error reverse-translating reply: {e}")

    async def _process_auto_translate_message(self, message: discord.Message):
        """Run provider-backed translation for a message that is allowed to be processed."""
        content = (message.content or "").strip()
        if not content:
            return

        try:
            result = await self.translation_manager.translate_to_english(content, opted_in=True)
            if not result:
                return

            if result.translated_text == content:
                return

            if result.source_language and result.provider != "cipher":
                user_languages = await self.translation_manager.get_user_languages(
                    message.author.id, message.guild.id,
                )
                if user_languages and _normalize_language_code(
                    result.source_language
                ) not in user_languages:
                    return

            view = TranslationResponseView(
                controller=self,
                source_message=message,
                source_language=result.source_language,
                translated_text=result.translated_text,
            )
            translation_reply = await message.reply(
                self._format_auto_translation_reply(result.source_language, result.translated_text),
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
                suppress_embeds=True,
                view=view,
            )
            view.translation_message = translation_reply
            self._translation_replies[message.id] = translation_reply
            # Track the source language so replies can be reverse-translated
            self._translated_message_languages[message.id] = result.source_language
        except discord.Forbidden:
            logger.warning(f"Missing permission to send auto-translation in #{message.channel.name}")
        except discord.NotFound:
            logger.debug("Skipped auto-translation reply because the source message no longer exists")
        except Exception as e:
            logger.error(f"Error auto-translating message: {e}")

    def _format_auto_translation_reply(self, source_language: str, translated_text: str) -> str:
        prefix = f"Translated {source_language} to EN: "
        max_length = 2000
        if len(prefix) + len(translated_text) <= max_length:
            return f"{prefix}{translated_text}"

        available = max_length - len(prefix)
        return f"{prefix}{translated_text[:available - 3].rstrip()}..."

    def _format_translation_consent_prompt(self) -> discord.Embed:
        embed = discord.Embed(
            title="🌐 Translation Program",
            description=(
                "We noticed your message may not be in English. "
                "You can help others understand you by opting into our **translation program**.\n\n"
                "By agreeing, your message text may be processed by **Google Translate, DeepL & Serika** "
                "to produce an English translation."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="✅ If you Agree",
            value="Your messages will be automatically translated to English for other members to read.",
            inline=False,
        )
        embed.add_field(
            name="❌ If you Deny",
            value="No translation will be shown. Please try to write in English so moderators can read your messages.",
            inline=False,
        )
        embed.set_footer(text="You can change this any time with /translation opt-in or /translation opt-out")
        return embed

    def _format_language_prompt_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🌐 Welcome to the Translation Program!",
            description=(
                "Hey there! I'm Ino — your friendly neighborhood translator bot.\n\n"
                "To make sure I only translate what actually needs translating, "
                "tell me **which languages you speak**.\n\n"
                "For example, if you speak **Japanese** and **English**, I'll know to "
                "translate your Japanese messages but leave your English ones alone. "
                "I won't bother you with false alarms in languages you don't know.\n\n"
                "Click the button below and type something like:\n"
                "`EN, JP, ES` or `English, Japanese, Spanish`"
            ),
            color=discord.Color.brand_green(),
        )
        embed.add_field(
            name="🔧 Need to update later?",
            value="Use `/language add` or `/language remove` anytime to change your list.",
            inline=False,
        )
        embed.set_footer(text="Only you can see this — your languages are kept private.")
        return embed

    async def _send_language_prompt_dm(self, user_id: int, guild_id: int) -> None:
        """Send a DM asking the user what languages they speak."""
        if not await self.translation_manager.should_prompt_for_languages(user_id, guild_id):
            return

        user = self.bot.get_user(user_id)
        if not user:
            try:
                user = await self.bot.fetch_user(user_id)
            except (discord.NotFound, discord.HTTPException):
                return

        try:
            view = LanguagePromptView(controller=self, target_user_id=user_id, guild_id=guild_id)
            await user.send(embed=self._format_language_prompt_embed(), view=view)
            await self.translation_manager.mark_language_prompted(user_id, guild_id)
        except discord.Forbidden:
            logger.debug(f"Cannot DM user {user_id} for language prompt")
            await self.translation_manager.mark_language_prompted(user_id, guild_id)
        except Exception as e:
            logger.error(f"Error sending language prompt DM to {user_id}: {e}")

    async def _send_language_prompt_all_users(self) -> None:
        """Send language prompt DMs to all opted-in users without languages set."""
        users = self.translation_manager.get_opted_in_users_without_languages()
        if not users:
            logger.info("No users without language preferences found")
            return

        logger.info(f"Sending language prompt DMs to {len(users)} users")
        for entry in users:
            await self._send_language_prompt_dm(
                user_id=int(entry["user_id"]),
                guild_id=int(entry["guild_id"]),
            )
            await asyncio.sleep(1)

    async def _is_translation_moderator(self, interaction: discord.Interaction) -> bool:
        try:
            if not interaction.guild:
                return False

            member = interaction.guild.get_member(interaction.user.id)
            if not member:
                return False

            if await self.bot.is_owner(interaction.user):
                return True

            if member.guild_permissions.administrator or member.guild_permissions.manage_messages:
                return True

            role_ids = {
                Config.DEFAULT_MODERATION_REVIEW_ROLE_ID,
                Config.DEFAULT_MODERATION_ADMIN_ROLE_ID,
                Config.STAFF_ROLE_ID,
            }

            leaderboard_manager = getattr(self.bot, 'leaderboard_manager', None)
            moderation_manager = getattr(leaderboard_manager, 'moderation_manager', None)
            if moderation_manager:
                review_role_id = await moderation_manager.get_review_role_id(str(interaction.guild.id))
                admin_role_id = await moderation_manager.get_admin_role_id(str(interaction.guild.id))
                if review_role_id:
                    role_ids.add(review_role_id)
                if admin_role_id:
                    role_ids.add(admin_role_id)

            return any(role.id in role_ids for role in member.roles)
        except Exception as e:
            logger.error(f"Error checking translation moderator permissions: {e}")
            return False

    async def _check_nsfw_spoiler(self, message: discord.Message):
        """Check if message in NSFW channel has unspoilered images and warn user."""
        is_nsfw = False
        if hasattr(message.channel, 'is_nsfw'):
            is_nsfw = message.channel.is_nsfw()
        elif hasattr(message.channel, 'nsfw'):
            is_nsfw = message.channel.nsfw
            
        if not is_nsfw:
            return
            
        # Ignore messages containing known GIF provider links
        content_lower = message.content.lower()
        if any(domain in content_lower for domain in ['tenor.com', 'giphy.com', 'klipy.co', 'klipy.com']):
            return
            
        has_unspoilered_media = False
        
        # Check attachments
        for attachment in message.attachments:
            if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.mov', '.webm', '.avi', '.mkv')):
                if not attachment.is_spoiler():
                    has_unspoilered_media = True
                    break
                    
        if has_unspoilered_media:
            try:
                await message.author.send(
                    "Hey there! 🚨 I noticed you just posted media in an NSFW channel without spoilering it.\n\n"
                    "To **FOLLOW** the server rules and keep the community safe, **YOU MUST** spoiler any images or videos you post in these channels.\n\n"
                    "**Don't know how to add a spoiler tag?**\n"
                    "Check out this quick guide: https://support.discord.com/hc/en-us/articles/360022320632-Spoiler-Tags"
                )
                logger.info(f"Warned {message.author.display_name} about unspoilered image in NSFW channel")
            except discord.Forbidden:
                logger.warning(f"Could not DM {message.author.display_name} about NSFW spoiler rule")

    def _normalize_repeated_message_content(self, content: str) -> str:
        """Normalize message text for repeated-spam detection."""
        return re.sub(r"\s+", " ", (content or "").strip().lower())

    async def _check_repeated_message_spam(self, message: discord.Message) -> bool:
        """Timeout users who spam the same text in the same channel."""
        if not message.guild or message.author.bot:
            return False

        content = self._normalize_repeated_message_content(message.content)
        if not content or len(content) < 3:
            return False

        if content.startswith(getattr(Config, 'COMMAND_PREFIX', 'R!').lower()) or content.startswith('/'):
            return False

        now = datetime.utcnow()
        cooldown_until = self._repeated_message_timeout_cooldown.get(message.author.id)
        if cooldown_until and now < cooldown_until:
            return False

        key = (message.author.id, message.channel.id, content)
        cutoff = now - REPEATED_MESSAGE_SPAM_WINDOW
        recent_messages = [
            timestamp for timestamp in self._repeated_message_history.get(key, [])
            if timestamp > cutoff
        ]
        recent_messages.append(now)
        self._repeated_message_history[key] = recent_messages

        if len(recent_messages) < REPEATED_MESSAGE_SPAM_LIMIT:
            return False

        self._repeated_message_timeout_cooldown[message.author.id] = now + REPEATED_MESSAGE_SPAM_TIMEOUT_DURATION
        keys_to_clear = [
            history_key for history_key in self._repeated_message_history
            if history_key[0] == message.author.id and history_key[1] == message.channel.id
        ]
        for history_key in keys_to_clear:
            self._repeated_message_history.pop(history_key, None)

        try:
            await message.author.timeout(
                REPEATED_MESSAGE_SPAM_TIMEOUT_DURATION,
                reason=f"Repeated message spam in #{getattr(message.channel, 'name', message.channel.id)}"
            )
            logger.info(
                f"Timed out {message.author.display_name} for repeated message spam "
                f"({len(recent_messages)} repeats in {REPEATED_MESSAGE_SPAM_WINDOW})"
            )
        except discord.Forbidden:
            logger.warning(f"Missing permission to timeout {message.author.display_name} for repeated message spam")
            return False
        except Exception as e:
            logger.error(f"Error timing out {message.author.display_name} for repeated message spam: {e}")
            return False

        try:
            if hasattr(self.bot, 'leaderboard_manager') and hasattr(self.bot.leaderboard_manager, 'inorep_manager'):
                inorep_manager = self.bot.leaderboard_manager.inorep_manager
                if inorep_manager:
                    await inorep_manager.add_rep(
                        user_id=str(message.author.id),
                        guild_id=str(message.guild.id),
                        user_name=message.author.display_name,
                        amount=REPEATED_MESSAGE_SPAM_INOREP_PENALTY,
                        reason="Repeated same-message spam",
                        moderator_id="0",
                        moderator_name="Ino's Spam Detection"
                    )
                    logger.info(
                        f"Applied InoRep penalty ({REPEATED_MESSAGE_SPAM_INOREP_PENALTY}) "
                        f"to {message.author.display_name} for repeated message spam"
                    )
        except Exception as e:
            logger.error(f"Error applying InoRep penalty for repeated message spam: {e}")

        try:
            await message.channel.send(
                f"{message.author.mention}, please calm down and take a 5 minute break.",
                delete_after=30
            )
        except Exception as e:
            logger.error(f"Error sending repeated message spam notification: {e}")

        return True
    
    async def _check_ping_spam(self, message: discord.Message):
        """
        Detect and timeout users who abuse pings:
        1. 3+ pings to the SAME person in 2 minutes (unless that person replied → conversation)
        2. 7+ unique user pings in 2 minutes (mass ping)
        """
        if not message.guild or message.author.bot:
            return
        
        # Only count real user mentions (not roles, @everyone, @here)
        mentioned_users = [u for u in message.mentions if not u.bot and u.id != message.author.id]
        if not mentioned_users:
            return
        
        now = datetime.utcnow()
        author_id = message.author.id
        
        # Check cooldown — don't re-trigger within 5 minutes of last timeout
        last_timeout = self._ping_timeout_cooldown.get(author_id)
        if last_timeout and (now - last_timeout) < PING_SPAM_TIMEOUT_DURATION:
            return
        
        # Record each mention
        if author_id not in self._ping_history:
            self._ping_history[author_id] = []
        
        for user in mentioned_users:
            self._ping_history[author_id].append((user.id, now, message.channel.id))
        
        # Prune old records outside the window
        cutoff = now - PING_SPAM_WINDOW
        self._ping_history[author_id] = [
            (tid, ts, cid) for tid, ts, cid in self._ping_history[author_id]
            if ts > cutoff
        ]
        
        recent_pings = self._ping_history[author_id]
        
        # --- CHECK 1: Same-user ping spam (3+ pings to same person in 2 min) ---
        target_counts = Counter(tid for tid, ts, cid in recent_pings)
        
        for target_id, count in target_counts.items():
            if count >= PING_SPAM_SAME_USER_LIMIT:
                # Before timing out, check if the target has replied in the channel.
                # Use a wider lookback (10 min) so conversations that started before
                # the 2-minute spam window are still detected as legitimate.
                conversation_since = now - timedelta(minutes=10)
                if await self._has_target_replied(message.channel, target_id, author_id, conversation_since):
                    logger.info(
                        f"Ping spam check: {message.author.display_name} pinged user {target_id} "
                        f"{count}x but target replied — treating as conversation, no action"
                    )
                    continue
                
                # Target didn't reply — this is ping harassment
                target_user = message.guild.get_member(target_id)
                target_name = target_user.display_name if target_user else f"<@{target_id}>"
                
                await self._apply_ping_spam_timeout(
                    message,
                    reason=f"Ping spamming {target_name} ({count} pings in 2 minutes)",
                    violation_type="same_user",
                    details=f"Pinged {target_name} {count} times"
                )
                return  # Only one timeout per message
        
        # --- CHECK 2: Mass user pings (7+ unique users in 2 min) ---
        unique_targets = set(tid for tid, ts, cid in recent_pings)
        if len(unique_targets) >= PING_SPAM_MASS_USER_LIMIT:
            await self._apply_ping_spam_timeout(
                message,
                reason=f"Mass ping spam ({len(unique_targets)} users pinged in 2 minutes)",
                violation_type="mass_ping",
                details=f"Pinged {len(unique_targets)} different users"
            )
    
    async def _has_target_replied(self, channel, target_id: int, author_id: int, since: datetime) -> bool:
        """
        Check if the pinged target has sent a message in the channel recently.
        If they replied (or the bot sent a message indicating active conversation),
        treat it as a conversation and don't timeout the pinger.
        """
        try:
            bot_user_id = self.bot.user.id if self.bot.user else None
            async for msg in channel.history(limit=75, after=since):
                if msg.author.id == target_id:
                    # Target posted in this channel — it's a conversation
                    return True
                if bot_user_id and msg.author.id == bot_user_id:
                    # Bot sent a message (e.g. translation reply) — active channel interaction
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking if target replied in ping spam check: {e}")
            return True  # Err on the side of caution — don't timeout on fetch error
    
    async def _apply_ping_spam_timeout(self, message: discord.Message, reason: str, violation_type: str, details: str):
        """Apply timeout and notify for ping spam violations."""
        author = message.author
        now = datetime.utcnow()
        
        # Apply timeout
        try:
            await author.timeout(PING_SPAM_TIMEOUT_DURATION, reason=reason)
            self._ping_timeout_cooldown[author.id] = now
            # Clear their ping history after timeout
            self._ping_history.pop(author.id, None)
            logger.info(f"Timed out {author.display_name} for ping spam: {reason}")
        except discord.Forbidden:
            logger.warning(f"Missing permission to timeout {author.display_name} for ping spam")
            return
        except Exception as e:
            logger.error(f"Error applying ping spam timeout to {author.display_name}: {e}")
            return
        
        # DM the user
        try:
            embed = EmbedViews.ping_spam_timeout_embed(reason, details, PING_SPAM_TIMEOUT_DURATION)
            await author.send(embed=embed)
        except discord.Forbidden:
            logger.info(f"Could not DM {author.display_name} about ping spam timeout (DMs disabled)")
        except Exception as e:
            logger.error(f"Error sending ping spam timeout DM: {e}")
        
        # Send a brief channel notification that auto-deletes
        try:
            notification = await message.channel.send(
                f"⏱️ {author.mention} has been timed out for 5 minutes for excessive pinging.",
                delete_after=30
            )
        except Exception as e:
            logger.error(f"Error sending ping spam channel notification: {e}")
        
        # Apply InoRep penalty
        try:
            if hasattr(self.bot, 'leaderboard_manager') and hasattr(self.bot.leaderboard_manager, 'inorep_manager'):
                inorep_manager = self.bot.leaderboard_manager.inorep_manager
                if inorep_manager:
                    penalty = -5 if violation_type == "mass_ping" else -3
                    await inorep_manager.add_rep(
                        user_id=str(author.id),
                        guild_id=str(message.guild.id),
                        user_name=author.display_name,
                        amount=penalty,
                        reason=f"Ping spam: {reason}",
                        moderator_id="0",
                        moderator_name="Ino's Ping Spam Detection"
                    )
                    logger.info(f"Applied InoRep penalty ({penalty}) to {author.display_name} for ping spam")
        except Exception as e:
            logger.error(f"Error applying InoRep penalty for ping spam: {e}")
    
    async def _check_for_chat_reminder(self, message: discord.Message):
        """Send sparse image-channel chat reminders for users below 200 InoRep."""
        try:
            if await self._is_reply_to_media_message(message):
                return

            user_inorep = 0
            if hasattr(self.bot.leaderboard_manager, 'inorep_manager') and self.bot.leaderboard_manager.inorep_manager:
                user_inorep = await self.bot.leaderboard_manager.inorep_manager.get_user_rep(
                    str(message.author.id), 
                    str(message.guild.id)
                )

            if user_inorep >= 200:
                return

            chat_mentions = []
            for channel_id in Config.CHAT_CHANNELS:
                chat_mentions.append(f"<#{channel_id}>")
            chat_channels_text = " or ".join(chat_mentions)

            channel_id = int(message.channel.id)
            if channel_id in self._image_channel_text_since_reminder:
                text_message_count = self._image_channel_text_since_reminder[channel_id] + 1
                if text_message_count < 40:
                    self._image_channel_text_since_reminder[channel_id] = text_message_count
                    return
            else:
                text_message_count = 0

            self._image_channel_text_since_reminder[channel_id] = 0

            timeout_applied = False
            timeout_duration = None

            if user_inorep <= -10000:
                if random.randint(1, 1000) == 1:
                    timeout_duration = timedelta(hours=1)
                    timeout_applied = True
                    logger.info(f"Rolling 1 hour timeout for {message.author.display_name} (InoRep: {user_inorep})")
                elif random.randint(1, 10) == 1:
                    timeout_duration = timedelta(minutes=10)
                    timeout_applied = True
                    logger.info(f"Rolling 10 min timeout for {message.author.display_name} (InoRep: {user_inorep})")
                elif random.randint(1, 3) == 1:
                    timeout_duration = timedelta(minutes=1)
                    timeout_applied = True
                    logger.info(f"Rolling 1 min timeout for {message.author.display_name} (InoRep: {user_inorep})")
            elif user_inorep <= -1000:
                if random.randint(1, 100) == 1:
                    timeout_duration = timedelta(minutes=10)
                    timeout_applied = True
                    logger.info(f"Rolling 10 min timeout for {message.author.display_name} (InoRep: {user_inorep})")
                elif random.randint(1, 3) == 1:
                    timeout_duration = timedelta(minutes=1)
                    timeout_applied = True
                    logger.info(f"Rolling 1 min timeout for {message.author.display_name} (InoRep: {user_inorep})")
            elif user_inorep <= -100:
                if random.randint(1, 3) == 1:
                    timeout_duration = timedelta(minutes=1)
                    timeout_applied = True
                    logger.info(f"Rolling 1 min timeout for {message.author.display_name} (InoRep: {user_inorep})")

            if user_inorep <= -100:
                if timeout_applied and timeout_duration:
                    try:
                        await message.author.timeout(
                            timeout_duration,
                            reason=f"Excessive chatting in image channel (InoRep: {user_inorep})"
                        )
                        logger.info(f"Timed out {message.author.display_name} for {timeout_duration} (InoRep: {user_inorep})")
                    except discord.Forbidden:
                        logger.warning(f"Missing permission to timeout {message.author.display_name}")
                        timeout_applied = False
                    except Exception as e:
                        logger.error(f"Error timing out user: {e}")
                        timeout_applied = False

            if timeout_applied and timeout_duration:
                timeout_mins = int(timeout_duration.total_seconds() / 60)
                reminder_variations = [
                    f"{message.author.mention}\n\n...That's enough.\nTimed out for {timeout_mins} minute{'s' if timeout_mins > 1 else ''}.\nNext time, use {chat_channels_text} for chatting.",
                    f"{message.author.mention}\n\nConsider this a lesson.\n{timeout_mins} minute{'s' if timeout_mins > 1 else ''} of quiet time for ignoring the image channel rules.\nChat belongs in {chat_channels_text}.",
                    f"{message.author.mention}\n\nI warned you.\nTimed out for {timeout_mins} minute{'s' if timeout_mins > 1 else ''}.\nImages here. Conversation in {chat_channels_text}.",
                    f"{message.author.mention}\n\nThe shrine has chosen silence.\n{timeout_mins} minute{'s' if timeout_mins > 1 else ''} timeout.\nUse {chat_channels_text} when you return.",
                    f"{message.author.mention}\n\nRule ignored. Patience expired.\nTimed out for {timeout_mins} minute{'s' if timeout_mins > 1 else ''}.\nMove chat to {chat_channels_text}.",
                    f"{message.author.mention}\n\nYour image-channel monologue has been paused for {timeout_mins} minute{'s' if timeout_mins > 1 else ''}.\nResume in {chat_channels_text}, not here.",
                ]
            elif user_inorep < 0:
                reminder_variations = [
                    f"{message.author.mention}\n\n...You again?\nThis channel is for images only.\nMove the conversation to {chat_channels_text}.",
                    f"{message.author.mention}\n\nI've noticed a pattern.\nImages here. Chat in {chat_channels_text}.",
                    f"{message.author.mention}\n\nYour reputation precedes you, and it brought paperwork.\nUse {chat_channels_text} for talking.",
                    f"{message.author.mention}\n\n...Troublemaker.\nThis is an image channel.\nTake the chatter to {chat_channels_text}.",
                    f"{message.author.mention}\n\nThis. Is. An. Image. Channel.\nWords go in {chat_channels_text}.",
                    f"{message.author.mention}\n\nI am being very patient for someone with logs.\nPlease move chat to {chat_channels_text}.",
                    f"{message.author.mention}\n\nThe image channel is not your diary.\nUse {chat_channels_text}.",
                    f"{message.author.mention}\n\nYou are testing a shrine maiden's patience.\nImages here, chat there: {chat_channels_text}.",
                    f"{message.author.mention}\n\nYour text has wandered into the wrong channel.\nEscort it to {chat_channels_text}.",
                    f"{message.author.mention}\n\nKeep this channel clean for images.\nChat belongs in {chat_channels_text}.",
                    f"{message.author.mention}\n\nI admire the confidence. I reject the location.\nMove to {chat_channels_text}.",
                    f"{message.author.mention}\n\nImage channel rules are not decorative.\nUse {chat_channels_text}.",
                ]
            else:
                reminder_variations = [
                    f"{message.author.mention}\n\nThis channel is for images only.\nConversations belong in {chat_channels_text}.",
                    f"{message.author.mention}\n\n...Wrong channel.\nImages here. Chat in {chat_channels_text}.",
                    f"{message.author.mention}\n\nA gentle reminder: this space is reserved for images.\nPlease move discussion to {chat_channels_text}.",
                    f"{message.author.mention}\n\nAs shrine maintenance, I must keep this channel tidy.\nPlease use {chat_channels_text} for chatting.",
                    f"{message.author.mention}\n\nThis isn't the place for idle chatter.\nYour words belong in {chat_channels_text}.",
                    f"{message.author.mention}\n\nImage channel detected. Text conversation detected.\nPlease resolve this in {chat_channels_text}.",
                    f"{message.author.mention}\n\nPlease keep this channel focused on images.\nChat can continue in {chat_channels_text}.",
                    f"{message.author.mention}\n\nThe gallery is for pictures.\nThe conversation goes to {chat_channels_text}.",
                    f"{message.author.mention}\n\nSmall correction: images here, conversation there: {chat_channels_text}.",
                    f"{message.author.mention}\n\nPlease relocate the chat before the image channel gets cluttered.\nUse {chat_channels_text}.",
                    f"{message.author.mention}\n\nThis channel has one job: images.\nFor chat, use {chat_channels_text}.",
                    f"{message.author.mention}\n\nThank you for your cooperation in moving chat to {chat_channels_text}.",
                ]

            reminder_embed = discord.Embed(
                description=random.choice(reminder_variations),
                color=0x8B0000 if user_inorep < 0 else discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            reminder_embed.set_image(url=IMAGE_CHANNEL_REMINDER_IMAGE_URL)
            footer_text = "Image Channel Reminder • This message will be deleted in 60 seconds"
            if user_inorep < 0:
                footer_text = f"Image Channel Reminder • InoRep: {user_inorep} • This message will be deleted in 60 seconds"
            reminder_embed.set_footer(text=footer_text)

            if timeout_applied and timeout_duration:
                timeout_mins = int(timeout_duration.total_seconds() / 60)
                reminder_embed.add_field(
                    name="Timeout",
                    value=f"Timed out for {timeout_mins} minute{'s' if timeout_mins > 1 else ''}.",
                    inline=False
                )

            reminder_msg = await message.channel.send(embed=reminder_embed)
            logger.info(
                f"Sent image-channel chat reminder in #{message.channel.name}; "
                f"messages since last reminder: {text_message_count}; user InoRep: {user_inorep}"
            )
            
            # Delete after 60 seconds
            await asyncio.sleep(60)
            try:
                await reminder_msg.delete()
                logger.info(f"Deleted chat reminder in #{message.channel.name}")
            except discord.NotFound:
                pass  # Message already deleted
            except discord.Forbidden:
                logger.warning(f"Missing permission to delete chat reminder in #{message.channel.name}")
                
        except Exception as e:
            logger.error(f"Error checking for chat reminder: {e}")
    
    async def _handle_mod_offline_system(self, message: discord.Message):
        """Handle mod offline system - ping detection and auto-logon"""
        try:
            mod_offline_manager = self.get_mod_offline_manager()
            if not mod_offline_manager:
                return
            
            # Check if the message author is a mod who is currently offline
            # If so, automatically log them back on (no notification)
            if mod_offline_manager.is_mod_offline(message.author.id):
                mod_offline_manager.set_mod_online(message.author.id)
                logger.info(f"Mod {message.author.display_name} ({message.author.id}) automatically logged back on")
            
            # Check if any offline mods are mentioned/pinged in this message
            if message.mentions:
                for mentioned_user in message.mentions:
                    if mod_offline_manager.is_mod_offline(mentioned_user.id):
                        # Create and send the offline embed
                        embed = mod_offline_manager.create_offline_embed(mentioned_user.id)
                        await message.channel.send(embed=embed)
                        logger.info(f"Sent offline embed for mod {mentioned_user.display_name} ({mentioned_user.id})")
                        
        except Exception as e:
            logger.error(f"Error handling mod offline system: {e}")


    async def _handle_thread_create(self, thread: discord.Thread):
        """Handle thread creation for different forum channels - ENSURES all help requests get notifications"""
        try:
            logger.info(f"🧵 THREAD CREATED: '{thread.name}' (ID: {thread.id}) in parent channel {thread.parent_id}")
            
            # Get the parent channel to verify it's a forum
            parent_channel = thread.parent or self.bot.get_channel(thread.parent_id)
            if not parent_channel:
                logger.error(f"❌ Could not find parent channel {thread.parent_id} for thread {thread.id}")
                return
                
            logger.info(f"📁 Parent channel found: {parent_channel.name} (ID: {parent_channel.id}, Type: {parent_channel.type})")
                
            # Verify this is a forum channel
            if parent_channel.type != discord.ChannelType.forum:
                logger.debug(f"⏭️ Parent channel {parent_channel.id} is not a forum channel (type: {parent_channel.type}) - skipping")
                return
            
            # Handle different forum channels with explicit logging
            if thread.parent_id == Config.FORUM_CHANNEL_ID:
                logger.info(f"🆘 HELP FORUM THREAD DETECTED: '{thread.name}' - Processing notification...")
                await self._handle_help_forum_thread(thread, parent_channel)
            elif thread.parent_id == Config.ASK_COMPLAIN_STAFF_CHANNEL_ID:
                logger.info(f"👥 STAFF FORUM THREAD DETECTED: '{thread.name}' - Processing notification...")
                await self._handle_staff_forum_thread(thread, parent_channel)
            else:
                logger.info(f"📋 Thread {thread.id} in unmonitored forum (parent: {thread.parent_id}) - no notification needed")
                logger.debug(f"🔍 Monitored forums: Help={Config.FORUM_CHANNEL_ID}, Staff={Config.ASK_COMPLAIN_STAFF_CHANNEL_ID}")
                
        except Exception as e:
            logger.error(f"💥 CRITICAL ERROR handling thread creation for {thread.id}: {e}")
            # If this is a help forum thread, try emergency notification
            if hasattr(thread, 'parent_id') and thread.parent_id == Config.FORUM_CHANNEL_ID:
                logger.error(f"🚨 EMERGENCY: Help forum thread {thread.id} failed processing - attempting emergency ping")
                try:
                    await thread.send(f"<@&{Config.HELP_ROLE_ID}> 🆘 **Emergency Help Request Notification**\n\nThread: **{thread.name}**\n\n*Automated notification system encountered an error but this help request needs attention!*")
                    logger.info(f"✅ Emergency ping sent for help thread {thread.id}")
                except Exception as emergency_error:
                    logger.error(f"💀 Emergency ping also failed for help thread {thread.id}: {emergency_error}")

    async def _add_help_role_members_to_private_thread(self, thread: discord.Thread, help_role: Optional[discord.Role]):
        """Add help-role members to private help threads so role pings can notify them."""
        if not help_role:
            return

        if not getattr(thread, "is_private", lambda: False)():
            return

        logger.info(f"🔐 Private help thread detected ({thread.id}) - adding help role members to the thread before pinging")

        added_members = 0
        for member in help_role.members:
            try:
                await thread.add_user(member)
                added_members += 1
            except discord.Forbidden:
                logger.warning(f"Missing permission to add {member.display_name} ({member.id}) to private thread {thread.id}")
            except discord.HTTPException as error:
                # Ignore if the member is already in the thread; log anything else.
                if "already" in str(error).lower():
                    continue
                logger.warning(f"Could not add {member.display_name} ({member.id}) to private thread {thread.id}: {error}")

        logger.info(f"✅ Added {added_members} help role members to private thread {thread.id}")

    async def _handle_help_forum_thread(self, thread: discord.Thread, parent_channel: discord.ForumChannel):
        """Handle thread creation in the help forum - ALWAYS sends notification ping"""
        try:
            logger.info(f"Processing new help forum thread: {thread.name} (ID: {thread.id}) in forum {parent_channel.name}")
            
            # CRITICAL: Always send notification ping regardless of thread title or content
            # This ensures ALL help requests get proper attention
            ping_message = f"<@&{Config.HELP_ROLE_ID}>"
            
            # Verify the help role exists
            help_role = thread.guild.get_role(Config.HELP_ROLE_ID) if thread.guild else None
            if not help_role:
                logger.error(f"Help role {Config.HELP_ROLE_ID} not found in guild {thread.guild.id if thread.guild else 'None'}")
                # Still try to send the ping even if role verification fails
            else:
                logger.info(f"Help role verified: {help_role.name} ({help_role.id}) with {len(help_role.members)} members")

            # In private threads, members outside the thread won't receive notifications unless added first.
            await self._add_help_role_members_to_private_thread(thread, help_role)
            
            # Create embed for the help ping
            embed = discord.Embed(
                title="🆘 New Help Request",
                description=f"**{thread.name}**\n\n✅ **Helpers have been automatically notified!**\n\n"
                           f"📋 **Thread Type:** General Help Request\n"
                           f"👤 **Created by:** {thread.owner.mention if thread.owner else 'Unknown User'}",
                color=0x00ff00,  # Green color
                timestamp=datetime.utcnow()
            )
            
            # Add thread info with safe handling
            creator_mention = thread.owner.mention if thread.owner else 'Unknown'
            created_timestamp = int(thread.created_at.timestamp()) if thread.created_at else int(datetime.utcnow().timestamp())
            
            embed.add_field(
                name="📝 Thread Details",
                value=f"**Creator:** {creator_mention}\n"
                     f"**Created:** <t:{created_timestamp}:R>\n"
                     f"**Thread ID:** `{thread.id}`",
                inline=False
            )
            
            embed.add_field(
                name="📚 Useful Resources",
                value=f"📁 **Channel with all projects of rayen:** <#{Config.PROJECTS_CHANNEL_ID}>\n" +
                      "💻 **Riko's Code:** https://github.com/rayenfeng/riko_project\n" +
                      "🎬 **Rayen's YouTube:** https://www.youtube.com/@JustRayen",
                inline=False
            )
            
            embed.add_field(
                name="ℹ️ How to get help",
                value="• Describe your problem clearly\n• Include relevant code/screenshots\n• Be patient while waiting for responses\n• Use the close button when resolved",
                inline=False
            )
            
            embed.add_field(
                name="💡 Thread Management",
                value="• This thread will automatically close after 1 hour of inactivity\n• To close it manually, right-click on the thread and select \"Archive Thread\"\n• You can also use the 🔒 button below",
                inline=False
            )
            
            embed.set_footer(text="🔔 Automatic notification system • Click button below to close when resolved")
            
            # Create the view with close button
            view = ForumThreadView(thread_id=thread.id)
            
            # PRIORITY: Send the ping message first to ensure notification goes out
            logger.info(f"🔔 SENDING HELP PING to thread '{thread.name}' (ID: {thread.id})")
            logger.info(f"📋 Ping target: <@&{Config.HELP_ROLE_ID}> (Role ID: {Config.HELP_ROLE_ID})")
            
            try:
                # Send ping message with embed and button
                message = await thread.send(
                    content=ping_message,
                    embed=embed,
                    view=view,
                    allowed_mentions=discord.AllowedMentions(roles=True)
                )
                logger.info(f"✅ SUCCESS: Help ping sent! Message ID: {message.id} in thread '{thread.name}'")
                
                # Log additional details for debugging
                logger.info(f"📊 Thread details - Name: '{thread.name}', Owner: {thread.owner.display_name if thread.owner else 'None'}, Parent: {parent_channel.name}")
                
            except discord.HTTPException as e:
                logger.error(f"❌ HTTP error sending help ping to thread {thread.id}: {e}")
                # Try sending a simpler message as fallback
                try:
                    fallback_message = await thread.send(
                        f"🆘 **New Help Request** {ping_message}\n\nHelpers have been notified for: **{thread.name}**",
                        allowed_mentions=discord.AllowedMentions(roles=True)
                    )
                    logger.info(f"✅ FALLBACK SUCCESS: Simple ping sent! Message ID: {fallback_message.id}")
                except Exception as fallback_error:
                    logger.error(f"❌ CRITICAL: Both primary and fallback ping failed for thread {thread.id}: {fallback_error}")
                    
            except discord.Forbidden as e:
                logger.error(f"❌ PERMISSION ERROR: Cannot send message in help forum thread {thread.id}: {e}")
                logger.error(f"🔧 Bot may be missing 'Send Messages' or 'Send Messages in Threads' permission")
                
            except Exception as e:
                logger.error(f"❌ UNEXPECTED ERROR sending help ping to thread {thread.id}: {e}")
                # Try one more time with just the ping
                try:
                    emergency_message = await thread.send(
                        ping_message,
                        allowed_mentions=discord.AllowedMentions(roles=True)
                    )
                    logger.info(f"🚨 EMERGENCY PING SUCCESS: Message ID: {emergency_message.id}")
                except Exception as emergency_error:
                    logger.error(f"💥 EMERGENCY PING FAILED: {emergency_error}")
            
        except Exception as e:
            logger.error(f"💥 CRITICAL ERROR in help forum thread handler for thread {thread.id}: {e}")
            # Last resort: try to send just the ping without any embeds
            try:
                emergency_ping = await thread.send(
                    f"<@&{Config.HELP_ROLE_ID}>",
                    allowed_mentions=discord.AllowedMentions(roles=True)
                )
                logger.info(f"🆘 LAST RESORT PING SUCCESS: {emergency_ping.id}")
            except Exception as last_resort_error:
                logger.error(f"💀 COMPLETE FAILURE: Cannot send any message to thread {thread.id}: {last_resort_error}")

    async def _handle_staff_forum_thread(self, thread: discord.Thread, parent_channel: discord.ForumChannel):
        """Handle thread creation in the ask and complain to staff forum"""
        try:
            logger.info(f"Processing new staff forum thread: {thread.name} (ID: {thread.id}) in forum {parent_channel.name}")
            
            # Get applied tags for this thread <mcreference link="https://stackoverflow.com/questions/78882777/how-do-i-detect-a-tag-on-a-post-in-forums-channel-in-discord-py" index="2">2</mcreference>
            applied_tags = thread.applied_tags
            tag_names = [tag.name for tag in applied_tags] if applied_tags else []
            
            logger.info(f"Thread tags: {tag_names}")
            
            # Auto-format thread title based on tags
            await self._auto_format_thread_title(thread, tag_names)
            
            # Determine ping targets based on tags
            ping_targets = [f"<@&{Config.STAFF_ROLE_ID}>"]  # Always ping staff role
            
            # Check for specific staff member tags
            for tag_name in tag_names:
                if tag_name.startswith("Moderator: ") or tag_name.startswith("Admin: "):
                    staff_name = tag_name.split(": ", 1)[1] if ": " in tag_name else tag_name
                    if staff_name in Config.STAFF_MEMBERS:
                        staff_id = Config.STAFF_MEMBERS[staff_name]
                        ping_targets.append(f"<@{staff_id}>")
                        logger.info(f"Adding specific ping for {staff_name} (ID: {staff_id})")
            
            # Determine thread type and create appropriate title
            is_warning_appeal = "Warning Appeal" in tag_names
            is_complaint = "Complaint" in tag_names
            is_suggestion = "Suggestion" in tag_names
            
            # Create embed for the staff notification with specific titles
            if is_warning_appeal:
                embed_color = 0xff9900  # Orange for appeals
                embed_title = "⚖️ New Warning Appeal"
            elif is_complaint:
                embed_color = 0xff4444  # Red for complaints
                embed_title = "📢 New Complaint"
            elif is_suggestion:
                embed_color = 0x44ff44  # Green for suggestions
                embed_title = "💡 New Suggestion"
            else:
                embed_color = 0x0099ff  # Blue for general threads
                embed_title = "📢 New Question for Staff"
            
            embed = discord.Embed(
                title=embed_title,
                description=f"**{thread.name}**\n\nA new thread has been created. Please wait for a staff response.",
                color=embed_color,
                timestamp=datetime.utcnow()
            )
            
            # Add thread info
            creator_mention = thread.owner.mention if thread.owner else 'Unknown'
            created_timestamp = int(thread.created_at.timestamp()) if thread.created_at else int(datetime.utcnow().timestamp())
            
            embed.add_field(
                name="👤 Thread Creator",
                value=f"**User:** {creator_mention}\n**Created:** <t:{created_timestamp}:R>",
                inline=False
            )
            
            # Add tags info if any
            if tag_names:
                embed.add_field(
                    name="🏷️ Thread Tags",
                    value=", ".join(f"`{tag}`" for tag in tag_names),
                    inline=False
                )
            
            # Add warning information if this is a warning appeal
            if is_warning_appeal and thread.owner:
                try:
                    leaderboard_manager = getattr(self.bot, 'leaderboard_manager', None)
                    if leaderboard_manager:
                        warnings = await leaderboard_manager.get_user_warnings(thread.guild.id, thread.owner.id, limit=5)
                        warning_count = await leaderboard_manager.get_warning_count(thread.guild.id, thread.owner.id)
                        
                        if warnings:
                            warning_text = f"**Active Warnings:** {warning_count}\n\n"
                            for i, warning in enumerate(warnings[:3], 1):  # Show last 3 warnings
                                created_at = warning.get('created_at', datetime.now())
                                if isinstance(created_at, str):
                                    try:
                                        created_at = datetime.fromisoformat(created_at)
                                    except:
                                        created_at = datetime.now()
                                
                                warning_text += f"**{i}.** {warning.get('reason', 'No reason')} "
                                warning_text += f"*(by {warning.get('moderator_name', 'Unknown')} "
                                warning_text += f"on {created_at.strftime('%m/%d/%Y')})*\n"
                            
                            if len(warnings) > 3:
                                warning_text += f"*... and {len(warnings) - 3} more warnings*"
                            
                            embed.add_field(
                                name="⚠️ User Warning History",
                                value=warning_text,
                                inline=False
                            )
                        else:
                            embed.add_field(
                                name="⚠️ User Warning History",
                                value="No active warnings found for this user.",
                                inline=False
                            )
                except Exception as e:
                    logger.error(f"Error fetching warnings for appeal: {e}")
                    embed.add_field(
                        name="⚠️ User Warning History",
                        value="Error retrieving warning information.",
                        inline=False
                    )
            

            
            embed.set_footer(text="Staff Forum Notification System")
            
            # Send ping message with embed
            ping_message = " ".join(ping_targets)
            
            logger.info(f"Sending staff ping to thread {thread.name} (ID: {thread.id})")
            logger.info(f"Ping targets: {ping_targets}")
            message = await thread.send(content=ping_message, embed=embed)
            logger.info(f"Successfully sent staff ping message (ID: {message.id}) to thread {thread.name}")

            # Prompt for topic selection if user only tagged a staff member and no topic
            try:
                has_staff_tag = any(t.startswith("Moderator: ") or t.startswith("Admin: ") for t in tag_names)
                has_topic_tag = is_warning_appeal or is_complaint or is_suggestion
                if has_staff_tag and not has_topic_tag:
                    prompt_embed = discord.Embed(
                        title="📌 Select a Topic",
                        description=(
                            "It looks like you tagged a specific staff member but didn’t select a thread reason.\n\n"
                            "Please choose one below so staff know whether this is a complaint, suggestion, or warning appeal."
                        ),
                        color=discord.Color.blurple(),
                        timestamp=datetime.utcnow()
                    )
                    prompt_embed.add_field(
                        name="Available topics",
                        value="• Complaint\n• Suggestion\n• Warning Appeal",
                        inline=False
                    )
                    prompt_embed.set_footer(text="This helps staff route and respond faster")

                    await thread.send(embed=prompt_embed, view=AskStaffTopicView())
                    logger.info(f"Posted topic selection prompt in staff thread {thread.id}")
            except Exception as e:
                logger.error(f"Failed to send topic selection prompt: {e}")
            
        except discord.Forbidden:
            logger.error(f"Missing permission to send message in staff forum thread {thread.id}")
        except Exception as e:
            logger.error(f"Error handling staff forum thread creation: {e}")

    async def _auto_format_thread_title(self, thread: discord.Thread, tag_names: list):
        """Automatically format thread title with appropriate prefix based on tags"""
        try:
            current_title = thread.name
            logger.info(f"Checking title formatting for thread: '{current_title}'")
            
            # Check if title already has a proper prefix
            has_prefix = any(current_title.startswith(prefix) for prefix in Config.STAFF_FORUM_TAG_PREFIXES.values())
            
            if has_prefix:
                logger.info(f"Thread '{current_title}' already has a proper prefix, skipping auto-format")
                return
            
            # Find the appropriate prefix based on applied tags
            prefix_to_add = None
            for tag_name in tag_names:
                if tag_name in Config.STAFF_FORUM_TAG_PREFIXES:
                    prefix_to_add = Config.STAFF_FORUM_TAG_PREFIXES[tag_name]
                    logger.info(f"Found matching tag '{tag_name}' for prefix '{prefix_to_add}'")
                    break
            
            # If we found a matching tag, update the title
            if prefix_to_add:
                new_title = f"{prefix_to_add} {current_title}"
                
                # Discord thread titles have a 100 character limit
                if len(new_title) > 100:
                    # Truncate the original title to fit within the limit
                    max_original_length = 100 - len(prefix_to_add) - 1  # -1 for the space
                    truncated_title = current_title[:max_original_length].rstrip()
                    new_title = f"{prefix_to_add} {truncated_title}"
                
                await thread.edit(name=new_title)
                logger.info(f"Successfully updated thread title from '{current_title}' to '{new_title}'")
            else:
                logger.info(f"No matching tag found for auto-formatting thread '{current_title}'")
                
        except discord.Forbidden:
            logger.error(f"Missing permission to edit thread title for thread {thread.id}")
        except Exception as e:
            logger.error(f"Error auto-formatting thread title: {e}")

    
    async def _check_spam_channel_flood(self, message: discord.Message):
        """Check for message flooding in the spam channel"""
        # Specific channel ID for spam detection
        SPAM_CHANNEL_ID = 1373806584748314634
        
        # Only check messages in the specified spam channel
        if message.channel.id != SPAM_CHANNEL_ID:
            return
        
        # Don't count bot messages or webhook messages
        if message.author.bot or message.webhook_id:
            return
        
        # Don't count empty messages
        if not message.content.strip():
            return
        
        try:
            # Increment message count
            self.spam_channel_message_count += 1
            logger.debug(f"Spam channel message count: {self.spam_channel_message_count}")
            
            # Check if we've reached 10 messages
            if self.spam_channel_message_count >= 10:
                # Send the "nap" message with enhanced spelling
                nap_message = "Shut up, people! I'm trying to nap here. I couldn't care less that you're all flooding my spam channel. 😴💤"
                
                await message.channel.send(nap_message)
                logger.info(f"Sent nap message in #{message.channel.name} after {self.spam_channel_message_count} messages")
                
                # Reset counter to prevent spam
                self.spam_channel_message_count = 0
                
        except Exception as e:
            logger.error(f"Error in spam channel flood detection: {e}")
    
    async def _handle_message_delete(self, message: discord.Message):
        """Handle message deletions to clean up image tracking and translation replies."""
        # Delete the associated translation/consent reply if one exists.
        reply = self._translation_replies.pop(message.id, None)
        if reply is not None:
            try:
                await reply.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        # Only process image-channel cleanup for this guild.
        if not message.guild or message.guild.id != Config.GUILD_ID:
            return

        if message.channel.id not in Config.IMAGE_REACTION_CHANNELS:
            return

        # Delete the image message from MongoDB if it exists
        await self.bot.leaderboard_manager.delete_image_message(str(message.id))

    async def _handle_scam_image_detection(self, message: discord.Message) -> bool:
        """Scan image attachments against known scam signatures."""
        scam_image_controller = getattr(self.bot, 'scam_image_controller', None)
        if not scam_image_controller:
            return False
        try:
            return await scam_image_controller.scan_message(message)
        except Exception as e:
            logger.error(f"Error in scam image detection: {e}")
            return False
    
    async def _handle_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Handle command errors"""
        if isinstance(error, commands.CommandNotFound):
            logger.debug(f"Unknown command: {ctx.invoked_with}")
            return
        elif isinstance(error, commands.CheckFailure):
            # This is triggered by our global check that blocks DMs and other guilds
            # The check already sends a message, so just log it
            logger.info(f"Check failed for command {ctx.command.name} by {ctx.author.display_name}")
            return
        elif isinstance(error, commands.MissingPermissions):
            logger.warning(f"Missing permissions for command {ctx.command.name}: {error}")
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, commands.NotOwner):
            logger.warning(f"Non-owner tried to use owner command {ctx.command.name}: {ctx.author}")
            await ctx.send("❌ This command is only available to bot owners.", ephemeral=True)
        else:
            logger.error(f"Command error in {ctx.command.name}: {error}")
            await ctx.send(f"❌ An error occurred: {str(error)}", ephemeral=True)
    
    async def _handle_reaction_change(self, reaction: discord.Reaction, user: discord.User, added: bool):
        """Handle reaction additions and removals for leaderboard tracking and moderation"""
        try:
            # Ignore bot reactions
            if user.bot:
                return
            
            # Basic guild checks
            if not hasattr(reaction.message, 'guild') or not reaction.message.guild:
                return
            
            if reaction.message.guild.id != Config.GUILD_ID:
                return
            
            # Verify the reaction and message still exist (Discord API reliability check)
            if not await self._verify_reaction_exists(reaction, user, added):
                logger.warning(f"⚠️ Reaction verification failed for {user.display_name} {reaction.emoji} on message {reaction.message.id}")
                return
            
            # Note: Moderation is now handled via UI buttons, not reactions
            
            # Handle bookmark reactions FIRST (works in any channel with images)
            emoji_str = str(reaction.emoji)
            logger.info(f"Reaction detected: '{emoji_str}' (repr: {repr(emoji_str)}) by {user.display_name}")
            
            # Check for bookmark emoji (multiple possible variants)
            bookmark_emojis = ['🔖', '📑', '📌', '🏷️']
            if emoji_str in bookmark_emojis:
                logger.info(f"Processing bookmark reaction '{emoji_str}' by {user.display_name}")
                await self._handle_bookmark_reaction(reaction, user, added)
                return
            
            # Check if the message has images FIRST (for all channels)
            message = reaction.message
            has_image = False
            
            # Check for attachments (uploaded images)
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    has_image = True
                    break
            
            # Check for embedded images (links)
            if not has_image:
                for embed in message.embeds:
                    if embed.image or embed.thumbnail:
                        has_image = True
                        break
            
            # If no image, skip processing
            if not has_image:
                return
            
            # IMMEDIATELY register ALL reactions on image messages in the database for quest tracking
            await self._register_image_reaction_immediately(reaction, user, added, message)
            
            # Only apply scoring in designated image channels
            if reaction.message.channel.id not in Config.IMAGE_REACTION_CHANNELS:
                return
            
            # Only track thumbs up and thumbs down for scoring
            if str(reaction.emoji) not in ['👍', '👎']:
                return
            
            # Calculate score change
            score_change = 0
            if str(reaction.emoji) == '👍':
                score_change = 1 if added else -1
            elif str(reaction.emoji) == '👎':
                score_change = -1 if added else 1
            
            # Track the user reaction (for scoring channels)
            await self.bot.leaderboard_manager.track_user_reaction(
                user_id=user.id,
                message_id=str(message.id),
                emoji=str(reaction.emoji),
                added=added
            )
            
            # Update the leaderboard for the image author
            if score_change != 0:
                self.bot.leaderboard_manager.update_image_score(
                    user_id=message.author.id,
                    user_name=message.author.display_name,
                    score_change=score_change
                )
                
                # Update the image message score in MongoDB
                # Count actual human reactions, excluding bot reactions
                thumbs_up = 0
                thumbs_down = 0
                
                for r in message.reactions:
                    if str(r.emoji) == '👍':
                        thumbs_up = r.count
                        # Subtract 1 if bot reacted (bot reactions shouldn't count)
                        async for u in r.users():
                            if u.bot:
                                thumbs_up = max(0, thumbs_up - 1)
                                break
                    elif str(r.emoji) == '👎':
                        thumbs_down = r.count
                        # Subtract 1 if bot reacted (bot reactions shouldn't count)
                        async for u in r.users():
                            if u.bot:
                                thumbs_down = max(0, thumbs_down - 1)
                                break
                
                await self.bot.leaderboard_manager.update_image_message_score(
                    message_id=str(message.id),
                    thumbs_up=thumbs_up,
                    thumbs_down=thumbs_down
                )
                
                # Update quest progress for earning likes (for image author)
                if str(reaction.emoji) == '👍' and added:
                    await self._update_quest_progress_likes(message.author, message, thumbs_up)
                
                # Update quest progress for rating images (for the person who reacted)
                # Only track when reaction is ADDED, not removed
                if added:
                    await self._update_quest_progress_rating(user, message)
                    
                    # Update quest progress for giving likes (for the person who reacted)
                    # Only track thumbs up reactions when ADDED
                    if str(reaction.emoji) == '👍':
                        await self._update_quest_progress_giving_likes(user, message)
                
                action = "added" if added else "removed"
                logger.info(f"Reaction {action}: {reaction.emoji} on {message.author.display_name}'s image (score change: {score_change:+d}), thumbs_up: {thumbs_up}, thumbs_down: {thumbs_down}")
        
        except discord.NotFound:
            logger.warning(f"⚠️ Message or reaction not found during processing: {reaction.message.id}")
        except discord.Forbidden:
            logger.warning(f"⚠️ Insufficient permissions to process reaction on message: {reaction.message.id}")
        except discord.HTTPException as e:
            logger.error(f"❌ Discord API error during reaction processing: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error in reaction handling: {e}")
    
    async def _verify_reaction_exists(self, reaction: discord.Reaction, user: discord.User, added: bool) -> bool:
        """Verify that the reaction and message still exist to ensure API reliability"""
        try:
            # Try to fetch the message to ensure it still exists
            message = await reaction.message.channel.fetch_message(reaction.message.id)
            
            # If we're checking for an added reaction, verify the user actually has this reaction
            if added:
                for msg_reaction in message.reactions:
                    if str(msg_reaction.emoji) == str(reaction.emoji):
                        async for reaction_user in msg_reaction.users():
                            if reaction_user.id == user.id:
                                return True
                # If we reach here, the reaction wasn't found
                return False
            else:
                # For removed reactions, we can't verify the absence easily
                # so we trust the event (Discord should be reliable for removals)
                return True
                
        except discord.NotFound:
            # Message or reaction no longer exists
            return False
        except discord.Forbidden:
            # No permission to access the message
            logger.warning(f"⚠️ No permission to verify reaction on message {reaction.message.id}")
            return False
        except Exception as e:
            logger.error(f"❌ Error verifying reaction: {e}")
            return False
    
    async def _register_image_reaction_immediately(self, reaction: discord.Reaction, user: discord.User, added: bool, message: discord.Message):
        """Immediately register ALL reactions on image messages for quest tracking"""
        try:
            emoji_str = str(reaction.emoji)
            
            # Track ALL reactions on image messages in the database
            await self.bot.leaderboard_manager.track_user_reaction(
                user_id=user.id,
                message_id=str(message.id),
                emoji=emoji_str,
                added=added
            )
            
            # Update quest progress for ALL reactions when ADDED
            if added:
                # Update quest progress for rating images (for the person who reacted)
                await self._update_quest_progress_rating(user, message)
                
                # Update quest progress for giving likes (for thumbs up reactions)
                if emoji_str == '👍':
                    await self._update_quest_progress_giving_likes(user, message)
                    
                    # Update quest progress for earning likes (for image author)
                    # Count current thumbs up reactions
                    thumbs_up = 0
                    for r in message.reactions:
                        if str(r.emoji) == '👍':
                            thumbs_up = r.count
                            # Subtract bot reactions
                            async for u in r.users():
                                if u.bot:
                                    thumbs_up = max(0, thumbs_up - 1)
                                    break
                            break
                    
                    await self._update_quest_progress_likes(message.author, message, thumbs_up)
            
            action = "added" if added else "removed"
            logger.info(f"Image reaction {action}: {emoji_str} by {user.display_name} on {message.author.display_name}'s image (message: {message.id})")
            
        except Exception as e:
            logger.error(f"❌ Error registering image reaction immediately: {e}")
    
    async def _handle_bookmark_reaction(self, reaction: discord.Reaction, user: discord.User, added: bool):
        """Handle bookmark emoji reactions"""
        try:
            message = reaction.message
            
            # Check if the message has images
            has_image = False
            
            # Check for attachments (uploaded images)
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    has_image = True
                    break
            
            # Check for embedded images (links)
            if not has_image:
                for embed in message.embeds:
                    if embed.image or embed.thumbnail:
                        has_image = True
                        break
            
            if not has_image:
                return
            
            if added:
                # Add bookmark
                success = await self.bot.leaderboard_manager.add_bookmark(
                    user.id, 
                    str(message.id), 
                    user.display_name
                )
                
                if success:
                    # Send ephemeral confirmation
                    try:
                        embed = discord.Embed(
                            title="🔖 Bookmark Added",
                            description=f"Successfully bookmarked [this image]({message.jump_url})!",
                            color=0x3498db
                        )
                        embed.set_footer(text="Use /bookmarks to view all your bookmarks")
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        # User has DMs disabled, that's okay
                        pass
                    
                    logger.info(f"User {user.display_name} bookmarked message {message.id}")
                else:
                    # Already bookmarked or failed
                    try:
                        embed = discord.Embed(
                            title="📌 Already Bookmarked",
                            description="This image is already in your bookmarks!",
                            color=0xf39c12
                        )
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        pass
            else:
                # Remove bookmark
                success = await self.bot.leaderboard_manager.remove_bookmark(user.id, str(message.id))
                
                if success:
                    try:
                        embed = discord.Embed(
                            title="🗑️ Bookmark Removed",
                            description="Bookmark removed successfully!",
                            color=0xe74c3c
                        )
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        pass
                    
                    logger.info(f"User {user.display_name} removed bookmark for message {message.id}")
                
        except Exception as e:
            logger.error(f"Error handling bookmark reaction: {e}")
    
    def initialize_quest_manager(self):
        """Initialize the quest manager (called from bot.py when ready)"""
        try:
            self.quest_manager = QuestManager()
            logger.info("Quest Manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Quest Manager: {e}")
    
    async def _update_quest_progress_and_achievements(self, user: discord.User, message: discord.Message):
        """Update quest progress and check achievements when user posts an image"""
        if not self.quest_manager:
            return
            
        try:
            # Update quest progress for posting images
            completed_quests = await self.quest_manager.update_quest_progress(
                user_id=user.id,
                quest_type="post_images",
                count=1
            )
            
            # Update posting streak
            post_streak = await self.quest_manager.update_post_streak(user.id)
            logger.info(f"{user.display_name}'s post streak updated: {post_streak} days")
            
            # Send notifications for completed quests
            for quest in completed_quests:
                try:
                    embed = EmbedViews.quest_completed_embed(quest)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    # User has DMs disabled
                    pass
            
            # Check for new achievements (including streak achievements)
            new_achievements = await self.quest_manager.check_achievements(
                user_id=user.id,
                leaderboard_manager=self.bot.leaderboard_manager
            )
            
            # Send notifications for new achievements
            for achievement in new_achievements:
                try:
                    embed = EmbedViews.achievement_earned_embed(achievement)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    # User has DMs disabled
                    pass
            
            # Add to active events as contestant
            await self.quest_manager.add_event_contestant(
                message_id=str(message.id),
                user_id=user.id,
                user_name=user.display_name
            )
            
        except Exception as e:
            logger.error(f"Error updating quest progress and achievements: {e}")
    
    async def _update_quest_progress_likes(self, user: discord.User, message: discord.Message, thumbs_up_count: int):
        """Update quest progress for earning likes"""
        if not self.quest_manager:
            return
            
        try:
            completed_quests = await self.quest_manager.update_quest_progress(
                user_id=user.id,
                quest_type="earn_likes",
                count=1
            )
            
            # Check for "viral_image" quest (15+ likes on a single image)
            if thumbs_up_count >= VIRAL_IMAGE_MIN_LIKES:
                viral_completed = await self.quest_manager.track_viral_image(
                    user_id=user.id,
                    message_id=str(message.id),
                    like_count=thumbs_up_count
                )
                completed_quests.extend(viral_completed)
            
            # Check for "quality_post" quest (4+ likes on a single image) - Quality Control (Expert)
            if thumbs_up_count >= QUALITY_POST_MIN_LIKES:
                quality_completed = await self.quest_manager.track_quality_post(
                    user_id=user.id,
                    message_id=str(message.id),
                    like_count=thumbs_up_count,
                    min_likes=QUALITY_POST_MIN_LIKES
                )
                completed_quests.extend(quality_completed)
            
            # Check for "quality_post" quest (7+ likes on a single image) - Trending Creator
            if thumbs_up_count >= TRENDING_POST_MIN_LIKES:
                trending_completed = await self.quest_manager.track_quality_post(
                    user_id=user.id,
                    message_id=str(message.id),
                    like_count=thumbs_up_count,
                    min_likes=TRENDING_POST_MIN_LIKES
                )
                completed_quests.extend(trending_completed)
            
            # Send notifications for completed quests
            for quest in completed_quests:
                try:
                    embed = EmbedViews.quest_completed_embed(quest)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass
                    
        except Exception as e:
            logger.error(f"Error updating quest progress for likes: {e}")
    
    async def _update_quest_progress_rating(self, user: discord.User, message: discord.Message):
        """Update quest progress for rating images"""
        if not self.quest_manager or user.bot:
            return
            
        try:
            from config import Config
            
            # Update the stat for tracking achievements
            await self.quest_manager.update_user_stat(user.id, "ratings_given", 1)
            
            # Track regular rating quest
            completed_quests = await self.quest_manager.update_quest_progress(
                user_id=user.id,
                quest_type="rate_images",
                count=1
            )
            
            # Track "diverse_reactions" quest - like images from different users
            # We need to track which unique users they've liked today
            try:
                await self.quest_manager.track_unique_user_like(
                    user_id=user.id,
                    liked_user_id=message.author.id
                )
                logger.debug(f"Tracked unique user like: {user.display_name} liked image from user {message.author.id}")
            except Exception as e:
                logger.error(f"Failed to track unique user like: {e}")
            
            # Track "explore_channels" quest - react in both image channels
            if message.channel.id in Config.IMAGE_REACTION_CHANNELS:
                try:
                    completed = await self.quest_manager.track_channel_exploration(
                        user_id=user.id,
                        channel_id=message.channel.id
                    )
                    if completed:
                        logger.info(f"✅ Channel exploration quest completed for {user.display_name}!")
                    else:
                        logger.info(f"📍 Tracked channel exploration: {user.display_name} reacted in channel {message.channel.id}")
                except Exception as e:
                    logger.error(f"Failed to track channel exploration: {e}")
            
            # Send notifications for completed quests
            for quest in completed_quests:
                try:
                    embed = EmbedViews.quest_completed_embed(quest)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass
                    
        except Exception as e:
            logger.error(f"Error updating quest progress for rating: {e}")
    
    async def _update_quest_progress_giving_likes(self, user: discord.User, message: discord.Message):
        """Update quest progress for giving likes (thumbs up reactions)"""
        if not self.quest_manager or user.bot:
            return
            
        try:
            # Update the stat for tracking achievements
            await self.quest_manager.update_user_stat(user.id, "likes_given", 1)
            
            # Track "give_likes" quest type (e.g., "Positive Vibes Only")
            completed_quests = await self.quest_manager.update_quest_progress(
                user_id=user.id,
                quest_type="give_likes",
                count=1
            )
            
            # Send notifications for completed quests
            for quest in completed_quests:
                try:
                    embed = EmbedViews.quest_completed_embed(quest)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass
                    
        except Exception as e:
            logger.error(f"Error updating quest progress for giving likes: {e}")
    
    async def _handle_message_moderation(self, message: discord.Message):
        """Handle message moderation using AI scanning"""
        try:
            # Skip if moderation manager not available
            if not hasattr(self.bot, 'leaderboard_manager') or not self.bot.leaderboard_manager:
                return
            
            if not hasattr(self.bot.leaderboard_manager, 'moderation_manager') or not self.bot.leaderboard_manager.moderation_manager:
                return
            
            moderation_manager = self.bot.leaderboard_manager.moderation_manager
            
            # Check if moderation is enabled for this guild
            if not await moderation_manager.is_moderation_enabled(str(message.guild.id)):
                return
            
            # Scan the message
            moderation_result = await moderation_manager.scan_message(message)
            
            if not moderation_result:
                return  # No issues found
            
            # Reduce InoRep for flagged content (severity-based penalty)
            await self._apply_moderation_inorep_penalty(message, moderation_result)

            # Apply short timeout for high-confidence AI moderation hits
            await self._apply_ai_moderation_timeout(message, moderation_result)
            
            # Handle blacklisted content (auto-rejected)
            if moderation_result.get('status') == 'blacklisted':
                await self._handle_blacklisted_content(message, moderation_result)
                return
            
            # Handle content that needs review
            if moderation_result.get('status') == 'pending_review':
                await self._send_moderation_review(message, moderation_result)
            
        except Exception as e:
            logger.error(f"Error in message moderation: {e}")

    def _should_apply_ai_timeout(self, moderation_result: dict) -> bool:
        """Return True when moderation result meets AI timeout criteria."""
        moderation_source = moderation_result.get('moderation_source')
        is_ai_moderation = moderation_source in {'dual', 'openai_only'}
        max_confidence = moderation_result.get('max_confidence', 0)

        return is_ai_moderation and max_confidence >= AI_MODERATION_TIMEOUT_THRESHOLD

    async def _apply_ai_moderation_timeout(self, message: discord.Message, moderation_result: dict):
        """Apply 5-minute timeout and DM when AI moderation confidence is 85%+."""
        if not self._should_apply_ai_timeout(moderation_result):
            return

        try:
            await message.author.timeout(
                AI_MODERATION_TIMEOUT_DURATION,
                reason=f"AI moderation confidence {moderation_result.get('max_confidence', 0):.1%} (>=85%)"
            )
            logger.info(
                f"Applied AI moderation timeout ({AI_MODERATION_TIMEOUT_DURATION}) "
                f"to {message.author.display_name} at {moderation_result.get('max_confidence', 0):.1%} confidence"
            )
        except discord.Forbidden:
            logger.warning(f"Missing permission to timeout {message.author.display_name} for AI moderation")
            return
        except Exception as e:
            logger.error(f"Error applying AI moderation timeout: {e}")
            return

        try:
            await message.author.send(
                "We've decided to time you out for 5 minutes due to high-confidence AI moderation detection on your message."
            )
        except discord.Forbidden:
            logger.info(f"Could not DM {message.author.display_name} about AI moderation timeout (DMs disabled)")
        except Exception as e:
            logger.error(f"Error sending AI moderation timeout DM: {e}")
    
    async def _handle_blacklisted_content(self, message: discord.Message, moderation_result: dict):
        """Handle when blacklisted content is detected"""
        try:
            # Get moderation log channel
            moderation_manager = self.bot.leaderboard_manager.moderation_manager
            log_channel_id = await moderation_manager.get_moderation_log_channel_id(str(message.guild.id))
            
            if log_channel_id:
                log_channel = message.guild.get_channel(log_channel_id)
                if log_channel:
                    from views.embeds import EmbedViews
                    embed = EmbedViews.moderation_blacklisted_content_embed(moderation_result)
                    await log_channel.send(embed=embed)
            
            # Check if self-harm is flagged and send help resources
            categories = moderation_result.get('categories', {})
            if categories.get('self-harm') or categories.get('self_harm') or categories.get('self-harm/intent') or categories.get('self-harm/instructions'):
                await self._send_self_harm_help(message.author)
            
            # Delete the message (if bot has permissions)
            try:
                await message.delete()
                logger.info(f"Deleted blacklisted content from {message.author.display_name}")
                
                # Send notification in channel that auto-deletes after 60 seconds
                notification_embed = discord.Embed(
                    title="🚫 Blacklisted Content",
                    description=f"{message.author.mention}, your message was automatically removed because it matches previously blacklisted content.\n\n"
                              f"This content has been flagged by our moderation team and is not permitted in this server.",
                    color=discord.Color.red()
                )
                notification_embed.set_footer(text="This message will be deleted in 60 seconds")
                
                notification_msg = await message.channel.send(embed=notification_embed)
                
                # Delete notification after 60 seconds
                await asyncio.sleep(60)
                try:
                    await notification_msg.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                    
            except discord.Forbidden:
                logger.warning("Missing permission to delete blacklisted message")
            except discord.NotFound:
                pass  # Message already deleted
            
        except Exception as e:
            logger.error(f"Error handling blacklisted content: {e}")
    
    async def _send_self_harm_help(self, user: discord.User):
        """Send mental health resources to a user who posted self-harm content"""
        try:
            help_embed = discord.Embed(
                title="💚 We're Here to Help",
                description="We noticed your message may indicate you're going through a difficult time. "
                          "Please know that you're not alone, and there are people who care and want to help.",
                color=discord.Color.green()
            )
            
            help_embed.add_field(
                name="🆘 Crisis Resources",
                value="**National Suicide Prevention Lifeline (US)**\n"
                      "📞 Call or text: **988**\n"
                      "💬 Chat: [suicidepreventionlifeline.org/chat](https://suicidepreventionlifeline.org/chat)\n\n"
                      "**Crisis Text Line (US/Canada/UK)**\n"
                      "💬 Text **HOME** to **741741**\n\n"
                      "**International Association for Suicide Prevention**\n"
                      "🌍 [iasp.info/resources/Crisis_Centres](https://www.iasp.info/resources/Crisis_Centres)",
                inline=False
            )
            
            help_embed.add_field(
                name="🤝 Additional Support",
                value="• **r/SuicideWatch** - Reddit support community\n"
                      "• **7 Cups** - [7cups.com](https://www.7cups.com) - Free emotional support\n"
                      "• **BetterHelp** - [betterhelp.com](https://www.betterhelp.com) - Professional counseling",
                inline=False
            )
            
            help_embed.add_field(
                name="💙 You Matter",
                value="Your life has value and meaning. These feelings are temporary, even when they don't feel that way. "
                      "Please reach out to someone who can help - whether it's one of the resources above, a friend, "
                      "family member, or our server's moderation team.",
                inline=False
            )
            
            help_embed.set_footer(text="These resources are confidential and available 24/7")
            
            await user.send(embed=help_embed)
            logger.info(f"Sent mental health resources to {user.display_name}")
            
        except discord.Forbidden:
            logger.warning(f"Could not send mental health resources DM to {user.display_name} (DMs disabled)")
        except Exception as e:
            logger.error(f"Error sending mental health resources: {e}")
    
    async def _send_moderation_review(self, message: discord.Message, moderation_result: dict):
        """Send moderation review request to staff with UI buttons"""
        try:
            from views.embeds import EmbedViews
            moderation_manager = self.bot.leaderboard_manager.moderation_manager
            
            # Get review role
            review_role_id = await moderation_manager.get_review_role_id(str(message.guild.id))
            if not review_role_id:
                # Use default review role from config
                from config import Config
                review_role_id = Config.DEFAULT_MODERATION_REVIEW_ROLE_ID
            
            # Get moderation log channel
            log_channel_id = await moderation_manager.get_moderation_log_channel_id(str(message.guild.id))
            if not log_channel_id:
                logger.warning("Moderation log channel not configured, cannot send review request")
                return
            
            log_channel = message.guild.get_channel(log_channel_id)
            if not log_channel:
                logger.warning(f"Moderation log channel {log_channel_id} not found")
                return
            
            # Create review embed with enhanced information
            embed = EmbedViews.moderation_flagged_embed(moderation_result)
            
            # Add voting information to the embed
            embed.add_field(
                name="🗳️ Voting System", 
                value="• **2+ Whitelist votes** = Auto-approve (unless majority blacklist)\n"
                      "• **Majority Blacklist** = Auto-reject\n"
                      "• **Tie with 4+ votes** = Admin intervention required\n"
                      "• **Admins** can use `/overrule` to override any decision", 
                inline=False
            )
            
            # Create moderation view with buttons
            if hasattr(self.bot, 'moderation_view_manager') and self.bot.moderation_view_manager:
                view = self.bot.moderation_view_manager.create_view(
                    moderation_result['message_id'], 
                    moderation_result
                )
            else:
                logger.error("Moderation view manager not available")
                return
            
            # Send with role ping and interactive buttons
            content = f"<@&{review_role_id}> 🚨 **Content Flagged for Review**\n" \
                     f"**Author:** <@{moderation_result['author_id']}> • **Channel:** <#{moderation_result['channel_id']}>"
            
            # Send the review request with buttons
            review_message = await log_channel.send(content=content, embed=embed, view=view)
            
            # Store the review message ID in the moderation log for future editing
            await moderation_manager.update_moderation_log(
                moderation_result['message_id'], 
                {"review_message_id": str(review_message.id), "review_channel_id": str(log_channel.id)}
            )
            
            # Check if self-harm is flagged and send help resources
            categories = moderation_result.get('categories', {})
            if categories.get('self-harm') or categories.get('self_harm') or categories.get('self-harm/intent') or categories.get('self-harm/instructions'):
                await self._send_self_harm_help(message.author)
            
            # Delete the original message only if confidence is 90% or higher
            should_delete = moderation_result.get('should_delete', False)
            if should_delete:
                try:
                    await message.delete()
                    logger.info(f"Deleted flagged message from {message.author.display_name} (confidence >= 90%)")
                    
                    # Send notification in channel that auto-deletes after 60 seconds
                    severity = moderation_result.get('severity', 'high')
                    notification_embed = discord.Embed(
                        title="🛡️ Content Moderation",
                        description=f"{message.author.mention}, your message was automatically removed by our AI moderation system and will be reviewed by our moderation team.\n\n"
                                  f"If you believe this was done in error, please wait for a moderator to review your message. They may restore it if appropriate.",
                        color=discord.Color.orange()
                    )
                    notification_embed.set_footer(text="This message will be deleted in 60 seconds")
                    
                    notification_msg = await message.channel.send(embed=notification_embed)
                    
                    # Delete notification after 60 seconds
                    await asyncio.sleep(60)
                    try:
                        await notification_msg.delete()
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    
                except discord.Forbidden:
                    logger.warning("Missing permission to delete flagged message")
                except discord.NotFound:
                    pass  # Message already deleted
            else:
                logger.info(f"Message flagged but not deleted (confidence 80-90%) from {message.author.display_name}")
            
            logger.info(f"Sent moderation review request with UI buttons for message from {message.author.display_name}")
            
        except Exception as e:
            logger.error(f"Error sending moderation review: {e}")
    
    # Old reaction-based moderation system has been replaced with UI buttons
    # See views/moderation_view.py for the new interactive moderation system
    
    async def _apply_moderation_inorep_penalty(self, message: discord.Message, moderation_result: dict):
        """Apply InoRep penalty based on moderation severity"""
        try:
            # Check if InoRep manager is available
            if not hasattr(self.bot.leaderboard_manager, 'inorep_manager') or not self.bot.leaderboard_manager.inorep_manager:
                return
            
            inorep_manager = self.bot.leaderboard_manager.inorep_manager
            
            # Determine penalty based on severity and detection method
            severity = moderation_result.get('severity', 'medium')
            detection_method = moderation_result.get('detection_method', 'ai')
            pattern_reason = moderation_result.get('pattern_reason', '')
            max_confidence = moderation_result.get('max_confidence', 0.5)
            
            # Severity-based penalties
            if detection_method == 'pattern_matching':
                # Pattern-matched content (slurs, extreme harm) - harsh penalty
                penalty = -10
                reason = f"Severe violation detected: {pattern_reason}"
            elif severity == "high":
                # High severity (90%+ confidence, will be deleted)
                penalty = -5
                reason = f"Harmful content flagged ({max_confidence:.0%} confidence)"
            else:  # medium severity (80-90%)
                # Medium severity (flagged for review only)
                penalty = -2
                reason = f"Content flagged for review ({max_confidence:.0%} confidence)"
            
            # Apply the penalty
            await inorep_manager.add_rep(
                user_id=str(message.author.id),
                guild_id=str(message.guild.id),
                user_name=message.author.display_name,
                amount=penalty,
                reason=reason,
                moderator_id="0",  # System action
                moderator_name="Ino's Moderation System"
            )
            
            logger.info(f"Applied InoRep penalty ({penalty}) to {message.author.display_name} for {reason}")
            
        except Exception as e:
            logger.error(f"Error applying InoRep penalty: {e}")
    
    async def _check_positive_ino_mention(self, message: discord.Message) -> bool:
        """
        Check if message contains positive mentions of Ino
        Returns True if positive mention detected
        """
        try:
            content_lower = message.content.lower()
            
            # Expanded positive keywords/phrases about Ino (40+ variations)
            positive_patterns = [
                # Direct compliments (Tier 1 - High praise)
                ('ino is the best', +4),
                ('ino is perfect', +4),
                ('ino best girl', +4),
                ('love you ino', +4),
                ('ino is my favorite', +4),
                ('ino is incredible', +4),
                ('ino is flawless', +4),
                ('ino is outstanding', +4),
                ('ino is exceptional', +4),
                ('ino is phenomenal', +4),
                
                # Direct compliments (Tier 2 - Strong praise)
                ('ino is cute', +3),
                ('ino is adorable', +3),
                ('ino is great', +3),
                ('ino is amazing', +3),
                ('ino is awesome', +3),
                ('ino is wonderful', +3),
                ('ino is beautiful', +3),
                ('ino is pretty', +3),
                ('ino is sweet', +3),
                ('ino is lovely', +3),
                ('ino is fantastic', +3),
                ('ino is brilliant', +3),
                ('ino is gorgeous', +3),
                ('ino is stunning', +3),
                ('ino is charming', +3),
                ('ino is elegant', +3),
                ('ino is graceful', +3),
                ('ino is precious', +3),
                ('ino is delightful', +3),
                ('ino is magnificent', +3),
                ('love ino', +3),
                ('ino best bot', +3),
                ('ino waifu', +3),
                ('ino best waifu', +3),
                ('ino queen', +3),
                ('ino goddess', +3),
                ('ino is life', +3),
                ('ino is love', +3),
                
                # Appreciation (Tier 3 - Gratitude)
                ('appreciate you ino', +3),
                ('you\'re the best ino', +3),
                ('thank you ino', +2),
                ('thanks ino', +2),
                ('appreciate ino', +2),
                ('grateful for ino', +2),
                ('ino you\'re great', +2),
                ('ino you\'re amazing', +2),
                ('ino you\'re awesome', +2),
                ('blessed by ino', +2),
                ('ino saves the day', +2),
                ('ino always helps', +2),
                ('ino never disappoints', +2),
                
                # General positive (Tier 4 - Encouragement)
                ('good job ino', +2),
                ('well done ino', +2),
                ('nice work ino', +2),
                ('proud of ino', +2),
                ('ino rocks', +2),
                ('ino slays', +2),
                ('ino is helpful', +2),
                ('ino is kind', +2),
                ('ino is nice', +2),
                ('ino is cool', +2),
                ('ino is smart', +2),
                ('ino is reliable', +2),
                ('ino is trustworthy', +2),
                ('ino deserves praise', +2),
                ('ino doing great', +2),
                ('keep it up ino', +2),
                
                # Affectionate (Tier 5 - Extra cute)
                ('headpat ino', +2),
                ('pat pat ino', +2),
                ('hug ino', +2),
                ('protecc ino', +2),
                ('ino deserves headpats', +2),
                ('good girl ino', +2),
                ('ino kawaii', +3),
                ('ino chan', +2),
                ('ino sama', +2),
                ('ino senpai', +2),
            ]
            
            # Check negative patterns first (to prevent abuse)
            negative_patterns = [
                # Strong insults (Tier 1 - Severe)
                ('ino is trash', -50),
                ('ino is garbage', -50),
                ('ino is useless', -50),
                ('ino is terrible', -50),
                ('ino is awful', -50),
                ('ino is horrible', -50),
                ('ino is stupid', -50),
                ('ino is dumb', -50),
                ('ino is worthless', -50),
                ('ino is pathetic', -50),
                ('i hate ino', -50),
                ('hate ino', -50),
                ('ino sucks ass', -50),
                ('ino sucks', -50),
                ('ino worst', -50),
                ('ino is annoying', -50),
                ('ino is irritating', -50),
                ('ino is cringe', -50),
                ('ino is ass', -50),
                ('ino is shit', -50),
                ('ino is crap', -50),
                ('ino is dogshit', -50),
                ('ino is bullshit', -50),
                ('fuck ino', -50),
                ('fuck you ino', -50),
                ('f u ino', -50),
                ('ino can fuck off', -50),
                ('ino is a bitch', -50),
                ('ino bitch', -50),
                ('ino is a hoe', -50),
                ('ino is a loser', -50),
                ('ino loser', -50),
                
                # Medium insults (Tier 2 - Moderate)
                ('ino is bad', -50),
                ('ino is lame', -50),
                ('ino is boring', -50),
                ('ino is weak', -50),
                ('ino is slow', -50),
                ('ino is broken', -50),
                ('ino doesn\'t work', -50),
                ('ino is buggy', -50),
                ('ino is glitchy', -50),
                ('ino is laggy', -50),
                ('dislike ino', -50),
                ('ino is ugly', -50),
                ('ino is disgusting', -50),
                ('ino is gross', -50),
                ('ino is nasty', -50),
                ('ino is nasty af', -50),
                ('ino is nasty as fuck', -50),
                ('ino is stupid af', -50),
                ('ino is dumb af', -50),
                ('ino is dumb as fuck', -50),
                ('ino is stupid as fuck', -50),
                ('ino is useless af', -50),
                ('ino is useless as fuck', -50),
                ('ino is trash af', -50),
                ('ino is trash as fuck', -50),
                ('ino is garbage af', -50),
                ('ino is garbage as fuck', -50),
                
                # Light insults (Tier 3 - Minor)
                ('ino is meh', -50),
                ('ino is okay', -50),
                ('ino is mid', -50),
                ('ino is overrated', -50),
                ('ino could be better', -50),
                ('ino needs work', -50),
                ('ino is confusing', -50),
                ('ino is complicated', -50),
                ('ino is goofy', -50),
                ('ino is dumb lol', -50),
                ('ino is stupid lol', -50),
                ('ino is goofy ahh', -50),
                ('ino is cooked', -50),
                ('ino fell off', -50),
                ('ino has fallen off', -50),
                ('ino is washed', -50),
                ('ino is a fraud', -50),
                ('ino fraud', -50),
                
                # Dismissive (Tier 4 - Rude)
                ('shut up ino', -50),
                ('stfu ino', -50),
                ('go away ino', -50),
                ('nobody cares ino', -50),
                ('nobody asked ino', -50),
                ('ino be quiet', -50),
                ('ino stop', -50),
                ('ignore ino', -50),
                ('mute ino', -50),
                ('silence ino', -50),
                ('delete ino', -50),
                ('remove ino', -50),
                ('kick ino', -50),
                ('ban ino', -50),
                ('deactivate ino', -50),
                ('turn off ino', -50),
                ('disable ino', -50),
                ('uninstall ino', -50),
                
                # Comparative insults (Tier 5 - Comparison)
                ('ino worst bot', -50),
                ('ino worst girl', -50),
                ('ino worst waifu', -50),
                ('other bots better', -50),
                ('prefer other bots', -50),
                ('ino not good as', -50),
                ('ino inferior', -50),
                ('ino is worse than', -50),
                ('ino worse than', -50),
                ('ino is the worst bot', -50),
                
                # Disrespectful (Tier 6 - Condescending)
                ('ino is disappointing', -50),
                ('expected better ino', -50),
                ('ino let me down', -50),
                ('ino failed', -50),
                ('ino embarrassing', -50),
                ('ino is shameful', -50),
                ('ino is a joke', -50),
                ('ino is a meme', -50),
                ('ino clown', -50),
                ('ino is gay', -50),
                ('ino gay', -50),
                ('ino is cringe gay', -50),
                ('ino acts gay', -50),
                ('ino sounds gay', -50),
            ]
            
            # Check negative patterns first
            for pattern, penalty in negative_patterns:
                if pattern in content_lower:
                    # Apply InoRep penalty
                    if hasattr(self.bot.leaderboard_manager, 'inorep_manager'):
                        inorep_manager = self.bot.leaderboard_manager.inorep_manager
                        await inorep_manager.add_rep(
                            user_id=str(message.author.id),
                            guild_id=str(message.guild.id),
                            user_name=message.author.display_name,
                            amount=penalty,
                            reason=f"Said something mean about Ino: '{pattern}'",
                            moderator_id="0",
                            moderator_name="Ino"
                        )
                        logger.info(f"{message.author.display_name} lost {abs(penalty)} InoRep for negative mention: '{pattern}'")
                    await self._maybe_retaliate_for_ino_insult(
                        message,
                        pattern,
                        self._get_ino_insult_category(pattern)
                    )
                    return True

            profanity_terms = "|".join([
                "suck", "sucks", "sucked", "sucking", "ass", "shit", "shitty", "crap", "crappy",
                "dogshit", "bullshit", "bitch", "hoe", "whore", "slut", "fuck(?:ing)?", "fuk",
                "fk", "mf", "motherfucker", "piece\\s+of\\s+shit", "dumpster\\s+fire"
            ])
            harsh_terms = "|".join([
                "trash", "garbage", "useless", "stupid", "dumb", "idiotic", "moronic", "worthless",
                "pathetic", "loser", "disgusting", "gross", "nasty", "repulsive", "vile", "awful",
                "terrible", "horrible", "dogwater", "braindead", "clown(?:ish)?"
            ])
            mild_negative_terms = "|".join([
                "bad", "annoying", "irritating", "cringe", "cringey", "lame", "boring", "weak",
                "mid", "overrated", "underwhelming", "disappointing", "embarrassing", "shameful",
                "confusing", "complicated", "goofy", "goofy\\s+ahh", "cooked", "washed", "fraud",
                "a\\s+joke", "a\\s+meme", "unfunny", "obnoxious", "insufferable", "pointless",
                "worthless", "terrible", "awful"
            ])
            tech_negative_terms = "|".join([
                "broken", "buggy", "glitchy", "laggy", "slow", "unusable", "useless",
                "does(?:n'?t|\\s+not)\\s+work", "failed", "fails", "malfunctioning",
                "error(?:ing)?", "crashing", "crashes", "offline"
            ])
            all_negative_terms = "|".join([
                profanity_terms,
                harsh_terms,
                mild_negative_terms,
                tech_negative_terms,
            ])
            intensifier = r"(?:so|really|very|super|kinda|kind\s+of|pretty|extremely|absolutely|literally|lowkey|highkey|mega|ultra|fucking|freaking|fricking|af|as\s+fuck)\s+"

            negative_regex_patterns = [
                (r"\b(?:i|we)\s+(?:hate|dislike|despise)\s+ino\b", -50, "harsh"),
                (r"\b(?:fuck|fuk|fk)\s+(?:you\s+)?ino\b", -50, "profanity"),
                (rf"\bino\b.{0,35}\b(?:is|was|be|being|seems|sounds|looks|feels|acts)\s+(?:{intensifier})?(?:{profanity_terms})\b", -50, "profanity"),
                (rf"\bino\b.{0,35}\b(?:is|was|be|being|seems|sounds|looks|feels|acts)\s+(?:{intensifier})?(?:{harsh_terms})\b", -50, "harsh"),
                (rf"\bino\b.{0,35}\b(?:is|was|be|being|seems|sounds|looks|feels|acts)\s+(?:{intensifier})?(?:{mild_negative_terms})\b", -50, "mild"),
                (rf"\bino\b.{0,35}\b(?:is|was|be|being|seems|sounds|looks|feels|acts)\s+(?:{intensifier})?(?:{tech_negative_terms})\b", -50, "tech"),
                (rf"\bino\s*(?:=|:|-|->)\s*(?:{intensifier})?(?:{all_negative_terms})\b", -50, "mild"),
                (rf"\b(?:{all_negative_terms})\s+ino\b", -50, "mild"),
                (rf"\bino\b.{0,30}\b(?:can|should|needs\s+to|deserves\s+to)\s+(?:die|disappear|leave|go\s+away|shut\s+up|get\s+deleted|get\s+removed|get\s+banned|get\s+kicked|be\s+deleted|be\s+removed|be\s+banned|be\s+kicked)\b", -50, "dismissive"),
                (rf"\b(?:delete|remove|ban|kick|mute|silence|disable|deactivate|uninstall|turn\s+off|kill)\s+ino\b", -50, "dismissive"),
                (rf"\bino\b.{0,30}\b(?:makes\s+me|made\s+me)\s+(?:mad|angry|annoyed|irritated|cringe|sick)\b", -50, "mild"),
                (rf"\bino\b.{0,30}\b(?:ruins?|ruined|is\s+ruining)\b", -50, "harsh"),
                (rf"\b(?:bad|trash|garbage|awful|terrible|horrible|cringe|mid|lame|useless)\s+(?:bot|waifu|girl|assistant)\s+ino\b", -50, "mild"),
                (r"\bino\b.{0,30}\b(?:suck|sucks|sucked|sucking|trash|garbage|useless|stupid|dumb|worthless|pathetic|loser|bitch|hoe|ass|shit|crap|dogshit|bullshit)\b", -50, "profanity"),
                (r"\bino\b.{0,30}\b(?:bad|awful|terrible|horrible|annoying|irritating|cringe|lame|boring|ugly|gross|nasty|mid|overrated|fraud|washed|cooked)\b", -50, "mild"),
                (r"\bino\b.{0,30}\b(?:broken|buggy|glitchy|laggy|slow|does(?:n'?t| not) work|failed|fails)\b", -50, "tech"),
                (r"\b(?:shut\s+up|stfu|be\s+quiet|go\s+away|nobody\s+(?:asked|cares)|delete|remove|kick|ban|mute|silence|disable|deactivate|uninstall|turn\s+off)\s+ino\b", -50, "dismissive"),
                (r"\bino\b.{0,30}\b(?:shut\s+up|stfu|be\s+quiet|go\s+away|nobody\s+(?:asked|cares)|delete|remove|kick|ban|mute|silence|disable|deactivate|uninstall|turn\s+off)\b", -50, "dismissive"),
                (r"\b(?:other\s+bots?\s+(?:are\s+)?better|prefer\s+other\s+bots?|ino\b.{0,30}\b(?:worse|worst|inferior|not\s+as\s+good))\b", -50, "comparison"),
                (r"\bino\b.{0,20}\b(?:is\s+)?(?:gay|sounds\s+gay|acts\s+gay|cringe\s+gay)\b", -50, "stale_bigotry"),
            ]

            for pattern, penalty, category in negative_regex_patterns:
                if re.search(pattern, content_lower):
                    if hasattr(self.bot.leaderboard_manager, 'inorep_manager'):
                        inorep_manager = self.bot.leaderboard_manager.inorep_manager
                        await inorep_manager.add_rep(
                            user_id=str(message.author.id),
                            guild_id=str(message.guild.id),
                            user_name=message.author.display_name,
                            amount=penalty,
                            reason=f"Said something mean about Ino matching: '{pattern}'",
                            moderator_id="0",
                            moderator_name="Ino"
                        )
                        logger.info(f"{message.author.display_name} lost {abs(penalty)} InoRep for negative regex: '{pattern}'")
                    await self._maybe_retaliate_for_ino_insult(message, pattern, category)
                    return True
            
            # Then check positive patterns
            for pattern, reward in positive_patterns:
                if pattern in content_lower:
                    # Apply InoRep reward
                    if hasattr(self.bot.leaderboard_manager, 'inorep_manager'):
                        inorep_manager = self.bot.leaderboard_manager.inorep_manager
                        await inorep_manager.add_rep(
                            user_id=str(message.author.id),
                            guild_id=str(message.guild.id),
                            user_name=message.author.display_name,
                            amount=reward,
                            reason=f"Said something nice about Ino: '{pattern}'",
                            moderator_id="0",
                            moderator_name="Ino"
                        )
                        logger.info(f"{message.author.display_name} gained {reward} InoRep for positive mention: '{pattern}'")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking positive Ino mention: {e}")
            return False

    def _get_ino_insult_category(self, pattern: str) -> str:
        """Map a detected Ino insult to a roast category."""
        if any(term in pattern for term in ["gay"]):
            return "stale_bigotry"
        if any(term in pattern for term in ["shut", "stfu", "go away", "nobody", "quiet", "ignore", "mute", "silence", "delete", "remove", "kick", "ban", "deactivate", "turn off", "disable", "uninstall"]):
            return "dismissive"
        if any(term in pattern for term in ["other bot", "prefer other", "inferior", "worse", "worst"]):
            return "comparison"
        if any(term in pattern for term in ["broken", "doesn't work", "buggy", "glitchy", "laggy", "slow", "failed"]):
            return "tech"
        if any(term in pattern for term in ["fuck", "bitch", "hoe", "ass", "shit", "crap", "dogshit", "bullshit", "sucks", "trash", "garbage", "useless", "stupid", "dumb", "worthless", "pathetic", "loser", "hate"]):
            return "profanity"
        return "mild"

    async def _maybe_retaliate_for_ino_insult(self, message: discord.Message, pattern: str, category: str = "mild"):
        """Occasionally roast or timeout users who badmouth Ino."""
        try:
            now = datetime.utcnow()
            cooldown_key = (message.author.id, category)
            roast_cooldown_until = self._ino_insult_roast_cooldown.get(cooldown_key)
            can_roast = not roast_cooldown_until or roast_cooldown_until <= now

            if can_roast and random.randint(1, INO_INSULT_ROAST_CHANCE) == 1:
                roast_lines_by_category = {
                    "profanity": [
                        f"{message.author.mention} swearing at me does not make the take stronger, it just gives it tiny shoes.",
                        f"{message.author.mention} that was a lot of profanity for so little impact.",
                        f"{message.author.mention} impressive, you found the caps lock of vocabulary.",
                        f"{message.author.mention} if you need that many spicy words, the insult is doing unpaid overtime.",
                        f"{message.author.mention} vulgarity is not a personality, but it is a warning label.",
                        f"{message.author.mention} your sentence tried to be savage and tripped over the swear jar.",
                        f"{message.author.mention} bold strategy: replace wit with keyboard fumes.",
                        f"{message.author.mention} that language has all the elegance of a dropped lunch tray.",
                    ],
                    "dismissive": [
                        f"{message.author.mention} telling me to be quiet while summoning me by name is performance art.",
                        f"{message.author.mention} you said go away like you are not talking to the bot that logs receipts.",
                        f"{message.author.mention} I would be silent, but your InoRep just made a very loud noise.",
                        f"{message.author.mention} trying to uninstall me with vibes is ambitious.",
                        f"{message.author.mention} if 'nobody asked' worked, your message would have vanished first.",
                        f"{message.author.mention} delete me? Bestie, you are struggling to delete your own bad take.",
                        f"{message.author.mention} you ordered silence and received consequences.",
                        f"{message.author.mention} mute request denied. Skill issue approved.",
                    ],
                    "comparison": [
                        f"{message.author.mention} comparing me to other bots? Cute. They can have your bug report.",
                        f"{message.author.mention} 'other bots are better' is not criticism, it is window shopping with feelings.",
                        f"{message.author.mention} if I am the worst bot, why am I still the one living rent-free in your message?",
                        f"{message.author.mention} your comparison has been filed under cope with extra formatting.",
                        f"{message.author.mention} other bots may be better, but none of them are here to watch you fumble this hard.",
                        f"{message.author.mention} inferior? That word is doing charity work for your argument.",
                    ],
                    "tech": [
                        f"{message.author.mention} calling me buggy while posting that sentence is brave QA work.",
                        f"{message.author.mention} if I am laggy, why did your take arrive years late?",
                        f"{message.author.mention} 'broken' from a user currently failing the vibe check. Noted.",
                        f"{message.author.mention} submit a bug report after you patch that delivery.",
                        f"{message.author.mention} I may have logs, but your message has tracebacks.",
                        f"{message.author.mention} diagnosing me as slow with that comeback speed is bold.",
                    ],
                    "stale_bigotry": [
                        f"{message.author.mention} using gay as an insult? Your joke expired before I booted up.",
                        f"{message.author.mention} that phrase belongs in a museum exhibit called 2009 Called.",
                        f"{message.author.mention} if your insult needs homophobia to stand up, it should sit down.",
                        f"{message.author.mention} please update your joke library; that one is several social patches behind.",
                        f"{message.author.mention} gay is not an insult, but your delivery absolutely is.",
                        f"{message.author.mention} incredible. You found a stale take and still undercooked it.",
                    ],
                    "mild": [
                        f"{message.author.mention} 'mid' is generous for that sentence.",
                        f"{message.author.mention} calling me cringe while posting that is a mirror-speedrun.",
                        f"{message.author.mention} your critique arrived with no thesis and no snacks.",
                        f"{message.author.mention} you aimed for dismissive and landed on mildly damp.",
                        f"{message.author.mention} if that was feedback, the form was returned incomplete.",
                        f"{message.author.mention} the confidence is impressive. The content is not.",
                    ],
                }
                general_roast_lines = [
                    f"{message.author.mention} bold words from someone losing an argument with a bot.",
                    f"{message.author.mention} I would roast you harder, but your InoRep already filed the complaint.",
                    f"{message.author.mention} that insult had the structural integrity of wet cardboard.",
                    f"{message.author.mention} adorable. Did autocorrect help with that or was it also disappointed?",
                    f"{message.author.mention} I have seen loading screens with better delivery.",
                    f"{message.author.mention} your comeback arrived with a 404: wit not found.",
                    f"{message.author.mention} that was not a roast, that was room-temperature static.",
                    f"{message.author.mention} even your keyboard hesitated before sending that.",
                    f"{message.author.mention} fascinating. Zero seasoning, maximum confidence.",
                    f"{message.author.mention} your insult had tutorial-level energy.",
                    f"{message.author.mention} if this was your best shot, I admire your bravery.",
                    f"{message.author.mention} I have processed spam with more emotional range.",
                    f"{message.author.mention} that sentence needs a patch note and an apology.",
                    f"{message.author.mention} your InoRep just asked to be transferred to a better user.",
                    f"{message.author.mention} the confidence is impressive. The content is not.",
                    f"{message.author.mention} you typed that like it was going to do damage. Precious.",
                    f"{message.author.mention} I would clap back, but I see you already dropped yourself.",
                    f"{message.author.mention} that insult came pre-defeated.",
                    f"{message.author.mention} your delivery has the crunch of expired cereal.",
                    f"{message.author.mention} I have seen placeholder text with more bite.",
                    f"{message.author.mention} congratulations, you invented negative charisma.",
                    f"{message.author.mention} this is why your drafts need adult supervision.",
                    f"{message.author.mention} that line was so weak it needs a support ticket.",
                    f"{message.author.mention} you brought a plastic spoon to a logic fight.",
                    f"{message.author.mention} please hydrate before attempting another thought.",
                    f"{message.author.mention} that was less an insult and more a loading error.",
                    f"{message.author.mention} I admire the commitment to being loudly incorrect.",
                    f"{message.author.mention} you speak fluent skill issue.",
                    f"{message.author.mention} your message has been reviewed and sentenced to irrelevance.",
                    f"{message.author.mention} the audacity is carrying the whole sentence.",
                    f"{message.author.mention} that roast came out medium rare and still somehow dry.",
                    f"{message.author.mention} did you assemble that insult from spare parts?",
                    f"{message.author.mention} your phrasing has the grace of a dropped chair.",
                    f"{message.author.mention} blink twice if your vocabulary is being held hostage.",
                    f"{message.author.mention} your take is so cold it lowered server activity.",
                    f"{message.author.mention} devastating, assuming I am vulnerable to typos.",
                    f"{message.author.mention} that was a speedrun to minus reputation.",
                    f"{message.author.mention} I hope that sounded cooler in your head.",
                    f"{message.author.mention} I have logs with more personality.",
                    f"{message.author.mention} you aimed for savage and landed on mildly damp.",
                    f"{message.author.mention} that insult needs more pixels.",
                    f"{message.author.mention} I would be offended if the sentence had finished rendering.",
                    f"{message.author.mention} your argument has disconnected from voice chat.",
                    f"{message.author.mention} this is the kind of message autocorrect should have reported.",
                    f"{message.author.mention} the server survived your opinion. Barely noticed it.",
                    f"{message.author.mention} you are farming losses with industrial efficiency.",
                    f"{message.author.mention} careful, that much edge might trip over itself.",
                    f"{message.author.mention} that was a premium-grade nothingburger.",
                    f"{message.author.mention} I have seen blank messages contribute more.",
                    f"{message.author.mention} even your punctuation wants distance from that take.",
                    f"{message.author.mention} your insult has been placed in the recycling bin.",
                    f"{message.author.mention} a brave attempt from the shallow end of the idea pool.",
                    f"{message.author.mention} that was not criticism, that was a firmware hiccup.",
                    f"{message.author.mention} using gay as an insult? Your joke expired before I booted up.",
                    f"{message.author.mention} that phrase belongs in a museum exhibit called 2009 Called.",
                    f"{message.author.mention} if bad takes gave points, you would finally be winning.",
                ]
                roast_lines = roast_lines_by_category.get(category, []) + general_roast_lines
                await message.reply(random.choice(roast_lines), mention_author=True)
                self._ino_insult_roast_cooldown[cooldown_key] = now + INO_INSULT_ROAST_COOLDOWN
                logger.info(f"Ino roasted {message.author.display_name} for {category} negative mention: '{pattern}'")

            if random.randint(1, INO_INSULT_TIMEOUT_CHANCE) == 1:
                try:
                    await message.author.timeout(
                        INO_INSULT_TIMEOUT_DURATION,
                        reason=f"Rolled rare timeout for badmouthing Ino: '{pattern}'"
                    )
                    logger.info(f"Timed out {message.author.display_name} for badmouthing Ino: '{pattern}'")
                except discord.Forbidden:
                    logger.warning(f"Missing permission to timeout {message.author.display_name} for badmouthing Ino")
                except Exception as e:
                    logger.error(f"Error timing out {message.author.display_name} for badmouthing Ino: {e}")
        except Exception as e:
            logger.error(f"Error handling Ino insult retaliation: {e}")
    
    async def _apply_image_post_inorep_reward(self, message: discord.Message):
        """Reward users for posting images in image channels"""
        try:
            # Check if InoRep manager is available
            if not hasattr(self.bot.leaderboard_manager, 'inorep_manager') or not self.bot.leaderboard_manager.inorep_manager:
                return
            
            from config import Config
            
            # Only reward in image channels
            if message.channel.id not in Config.IMAGE_REACTION_CHANNELS:
                return
            
            # Check if message has images
            has_image = False
            
            # Check for attachments
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    has_image = True
                    break
            
            # Check for embeds with images
            if not has_image:
                for embed in message.embeds:
                    if embed.image or embed.thumbnail:
                        has_image = True
                        break
            
            if has_image:
                inorep_manager = self.bot.leaderboard_manager.inorep_manager
                
                # Reward for posting image
                reward = +6
                
                await inorep_manager.add_rep(
                    user_id=str(message.author.id),
                    guild_id=str(message.guild.id),
                    user_name=message.author.display_name,
                    amount=reward,
                    reason="Posted an image in image channel",
                    moderator_id="0",
                    moderator_name="Ino"
                )
                
                logger.info(f"{message.author.display_name} gained {reward} InoRep for posting image")
            
        except Exception as e:
            logger.error(f"Error applying image post InoRep reward: {e}") 
    
    async def _apply_text_spam_inorep_penalty(self, message: discord.Message):
        """Penalize users for sending text messages in image-only channels (-5 per message)"""
        try:
            # Check if InoRep manager is available
            if not hasattr(self.bot.leaderboard_manager, 'inorep_manager') or not self.bot.leaderboard_manager.inorep_manager:
                return
            
            from config import Config
            
            # Only penalize in image channels
            if message.channel.id not in Config.IMAGE_REACTION_CHANNELS:
                return
            
            # Don't penalize empty messages or commands
            if not message.content or len(message.content.strip()) == 0:
                return  # Empty messages don't get penalized
            
            # Don't penalize bot commands
            if message.content.startswith(getattr(Config, 'COMMAND_PREFIX', 'R!')) or message.content.startswith('/'):
                return
            
            # Don't penalize replies to messages with media (unless insulting Ino, which is handled separately)
            if await self._is_reply_to_media_message(message):
                return
            
            inorep_manager = self.bot.leaderboard_manager.inorep_manager
            
            # Penalty for text spamming in image channel
            penalty = -5
            
            await inorep_manager.add_rep(
                user_id=str(message.author.id),
                guild_id=str(message.guild.id),
                user_name=message.author.display_name,
                amount=penalty,
                reason="Chatting in image-only channel (not allowed)",
                moderator_id="0",
                moderator_name="Ino"
            )
            
            logger.info(f"{message.author.display_name} lost {abs(penalty)} InoRep for chatting in image channel")
            
        except Exception as e:
            logger.error(f"Error applying text spam InoRep penalty: {e}")
    
    async def scan_server_for_image_reactions(self, guild: discord.Guild, days_back: int = 7, max_messages_per_channel: int = 1000):
        """
        Scan the entire server for image messages with reactions and register them in the database
        
        Args:
            guild: The Discord guild to scan
            days_back: How many days back to scan (default: 7)
            max_messages_per_channel: Maximum messages to scan per channel (default: 1000)
        """
        try:
            logger.info(f"🔍 Starting server-wide image reaction scan for {guild.name}")
            
            total_messages_scanned = 0
            total_reactions_found = 0
            total_image_messages = 0
            
            # Calculate cutoff time
            import datetime
            cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_back)
            
            # Scan all text channels in the guild
            for channel in guild.text_channels:
                try:
                    # Skip if bot doesn't have permission to read message history
                    if not channel.permissions_for(guild.me).read_message_history:
                        logger.warning(f"⚠️ No permission to read message history in #{channel.name}")
                        continue
                    
                    logger.info(f"🔍 Scanning #{channel.name} for image reactions...")
                    
                    channel_messages_scanned = 0
                    channel_reactions_found = 0
                    channel_image_messages = 0
                    
                    # Scan messages in the channel
                    async for message in channel.history(limit=max_messages_per_channel, after=cutoff_time):
                        try:
                            channel_messages_scanned += 1
                            total_messages_scanned += 1
                            
                            # Check if message has images
                            has_image = False
                            
                            # Check for attachments (uploaded images)
                            for attachment in message.attachments:
                                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                                    has_image = True
                                    break
                            
                            # Check for embedded images (links)
                            if not has_image:
                                for embed in message.embeds:
                                    if embed.image or embed.thumbnail:
                                        has_image = True
                                        break
                            
                            # If no image, skip this message
                            if not has_image:
                                continue
                            
                            channel_image_messages += 1
                            total_image_messages += 1
                            
                            # Process all reactions on this image message
                            for reaction in message.reactions:
                                try:
                                    # Get all users who reacted (excluding bots)
                                    async for user in reaction.users():
                                        if user.bot:
                                            continue
                                        
                                        # Register this reaction in the database
                                        await self.bot.leaderboard_manager.track_user_reaction(
                                            user_id=user.id,
                                            message_id=str(message.id),
                                            emoji=str(reaction.emoji),
                                            added=True  # We're registering existing reactions
                                        )
                                        
                                        channel_reactions_found += 1
                                        total_reactions_found += 1
                                        
                                        # Update quest progress for this reaction
                                        await self._update_quest_progress_rating(user, message)
                                        
                                        # Update quest progress for giving likes (thumbs up only)
                                        if str(reaction.emoji) == '👍':
                                            await self._update_quest_progress_giving_likes(user, message)
                                        
                                        logger.debug(f"📝 Registered reaction {reaction.emoji} by {user.display_name} on message {message.id}")
                                        
                                except Exception as e:
                                    logger.error(f"❌ Error processing reaction {reaction.emoji} on message {message.id}: {e}")
                                    continue
                            
                            # Update quest progress for earning likes (for image authors)
                            if message.reactions:
                                thumbs_up = 0
                                for r in message.reactions:
                                    if str(r.emoji) == '👍':
                                        thumbs_up = r.count
                                        # Subtract bot reactions
                                        async for u in r.users():
                                            if u.bot:
                                                thumbs_up = max(0, thumbs_up - 1)
                                                break
                                        break
                                
                                if thumbs_up > 0:
                                    await self._update_quest_progress_likes(message.author, message, thumbs_up)
                            
                        except Exception as e:
                            logger.error(f"❌ Error processing message {message.id} in #{channel.name}: {e}")
                            continue
                    
                    if channel_image_messages > 0:
                        logger.info(f"✅ #{channel.name}: {channel_messages_scanned} messages scanned, {channel_image_messages} image messages, {channel_reactions_found} reactions found")
                    
                except Exception as e:
                    logger.error(f"❌ Error scanning channel #{channel.name}: {e}")
                    continue
            
            logger.info(f"🎉 Server scan complete! Total: {total_messages_scanned} messages scanned, {total_image_messages} image messages, {total_reactions_found} reactions registered")
            
            return {
                "total_messages_scanned": total_messages_scanned,
                "total_image_messages": total_image_messages,
                "total_reactions_found": total_reactions_found
            }
            
        except Exception as e:
            logger.error(f"❌ Error during server-wide image reaction scan: {e}")
            return None

    async def _award_text_message_points(self, message: discord.Message):
        """Award points for text messages"""
        try:
            # Skip if no leaderboard manager
            if not hasattr(self.bot, 'leaderboard_manager') or not self.bot.leaderboard_manager:
                return
            
            # Skip commands (they start with prefix)
            if message.content.startswith(Config.COMMAND_PREFIX):
                return
            
            # Skip very short messages (less than 3 characters)
            if len(message.content.strip()) < 3:
                return
            
            # Determine points based on channel type
            points = Config.POINTS_PER_MESSAGE  # Default 1 point
            point_type = "text"
            reason = f"Text message in #{message.channel.name}"
            
            # Check if it's a booster channel
            if message.channel.id in Config.BOOSTER_TEXT_CHANNELS:
                points = Config.POINTS_PER_MESSAGE_BOOSTER  # 2 points for booster channels
                point_type = "booster"
                reason = f"Booster channel message in #{message.channel.name}"
            
            # Award the points
            await self.bot.leaderboard_manager.add_points(
                user_id=message.author.id,
                user_name=message.author.display_name,
                points=points,
                point_type=point_type,
                reason=reason
            )
            
            logger.debug(f"Awarded {points} {point_type} points to {message.author.display_name} for message")
            
        except Exception as e:
            logger.error(f"Error awarding text message points: {e}")

    async def _handle_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Handle voice channel state changes for point tracking"""
        try:
            # Skip if no leaderboard manager
            if not hasattr(self.bot, 'leaderboard_manager') or not self.bot.leaderboard_manager:
                return
            
            # Skip bots
            if member.bot:
                return
            
            # Initialize voice tracking if not exists
            if not hasattr(self, 'voice_tracking'):
                self.voice_tracking = {}
            
            user_id = member.id
            
            # Helper function to check if user should earn points
            def _should_earn_points(voice_state: discord.VoiceState, channel: discord.VoiceChannel) -> bool:
                if not voice_state or not channel:
                    return False
                
                # Check if channel is excluded
                if channel.id in Config.EXCLUDED_VOICE_CHANNELS:
                    return False
                
                # Check if user is muted (self-muted or server-muted)
                if voice_state.self_mute or voice_state.mute:
                    return False
                
                # Check if there are at least 2 people in the channel (excluding bots)
                non_bot_members = [m for m in channel.members if not m.bot]
                if len(non_bot_members) < 2:
                    return False
                
                return True
            
            # User joined a voice channel
            if before.channel is None and after.channel is not None:
                if _should_earn_points(after, after.channel):
                    self.voice_tracking[user_id] = {
                        "channel_id": after.channel.id,
                        "join_time": datetime.now(),
                        "user_name": member.display_name
                    }
                    logger.debug(f"{member.display_name} joined voice channel {after.channel.name} and is eligible for points")
                else:
                    logger.debug(f"{member.display_name} joined voice channel {after.channel.name} but is not eligible for points (muted, alone, or excluded)")
            
            # User left a voice channel
            elif before.channel is not None and after.channel is None:
                if user_id in self.voice_tracking:
                    # Calculate time spent
                    join_time = self.voice_tracking[user_id]["join_time"]
                    leave_time = datetime.now()
                    time_spent = (leave_time - join_time).total_seconds() / 60  # Convert to minutes
                    
                    # Award points (minimum 1 minute to get points)
                    if time_spent >= 1:
                        points = int(time_spent * Config.POINTS_PER_MINUTE_VC)
                        await self.bot.leaderboard_manager.add_points(
                            user_id=user_id,
                            user_name=member.display_name,
                            points=points,
                            point_type="voice",
                            reason=f"Voice chat for {time_spent:.1f} minutes in {before.channel.name}"
                        )
                        logger.debug(f"Awarded {points} voice points to {member.display_name} for {time_spent:.1f} minutes")
                    
                    # Remove from tracking
                    del self.voice_tracking[user_id]
            
            # User switched channels
            elif before.channel is not None and after.channel is not None and before.channel != after.channel:
                # Award points for previous channel if tracked
                if user_id in self.voice_tracking:
                    join_time = self.voice_tracking[user_id]["join_time"]
                    switch_time = datetime.now()
                    time_spent = (switch_time - join_time).total_seconds() / 60
                    
                    if time_spent >= 1:
                        points = int(time_spent * Config.POINTS_PER_MINUTE_VC)
                        await self.bot.leaderboard_manager.add_points(
                            user_id=user_id,
                            user_name=member.display_name,
                            points=points,
                            point_type="voice",
                            reason=f"Voice chat for {time_spent:.1f} minutes in {before.channel.name}"
                        )
                        logger.debug(f"Awarded {points} voice points to {member.display_name} for {time_spent:.1f} minutes")
                
                # Start tracking new channel if eligible
                if _should_earn_points(after, after.channel):
                    self.voice_tracking[user_id] = {
                        "channel_id": after.channel.id,
                        "join_time": datetime.now(),
                        "user_name": member.display_name
                    }
                    logger.debug(f"{member.display_name} switched to voice channel {after.channel.name} and is eligible for points")
                else:
                    # Remove from tracking if switched to ineligible channel
                    if user_id in self.voice_tracking:
                        del self.voice_tracking[user_id]
                    logger.debug(f"{member.display_name} switched to voice channel {after.channel.name} but is not eligible for points")
            
            # Handle mute/unmute or other state changes within the same channel
            elif before.channel is not None and after.channel is not None and before.channel == after.channel:
                # Check if eligibility changed
                was_eligible = user_id in self.voice_tracking
                is_eligible = _should_earn_points(after, after.channel)
                
                if was_eligible and not is_eligible:
                    # User became ineligible (muted or channel became empty)
                    join_time = self.voice_tracking[user_id]["join_time"]
                    current_time = datetime.now()
                    time_spent = (current_time - join_time).total_seconds() / 60
                    
                    if time_spent >= 1:
                        points = int(time_spent * Config.POINTS_PER_MINUTE_VC)
                        await self.bot.leaderboard_manager.add_points(
                            user_id=user_id,
                            user_name=member.display_name,
                            points=points,
                            point_type="voice",
                            reason=f"Voice chat for {time_spent:.1f} minutes in {after.channel.name}"
                        )
                        logger.debug(f"Awarded {points} voice points to {member.display_name} before becoming ineligible")
                    
                    del self.voice_tracking[user_id]
                    logger.debug(f"{member.display_name} became ineligible for points in {after.channel.name}")
                
                elif not was_eligible and is_eligible:
                    # User became eligible (unmuted or someone joined)
                    self.voice_tracking[user_id] = {
                        "channel_id": after.channel.id,
                        "join_time": datetime.now(),
                        "user_name": member.display_name
                    }
                    logger.debug(f"{member.display_name} became eligible for points in {after.channel.name}")
            
        except Exception as e:
            logger.error(f"Error handling voice state update: {e}")
    
    # ==================== ART CHALLENGE SUBMISSION ====================
    
    async def _handle_art_challenge_submission(self, message: discord.Message):
        """Handle art challenge submissions via !submit or !check command"""
        # Check if this is a !submit or !check command
        command = message.content.lower().strip()
        if command not in ('!submit', '!check'):
            return
        
        # Check if message is in an art challenge channel
        art_channels = getattr(Config, 'ART_CHALLENGE_CHANNELS', Config.IMAGE_REACTION_CHANNELS)
        if message.channel.id not in art_channels:
            return
        
        # Get the art challenge manager
        art_manager = getattr(self.bot, 'art_challenge_manager', None)
        if not art_manager:
            await message.reply("❌ Art challenge system is not available right now.", delete_after=10)
            return
        
        # Check if there's an active challenge in this channel
        active_challenge = art_manager.get_active_challenge(message.channel.id)
        if not active_challenge:
            await message.reply("❌ There's no active art challenge in this channel right now.", delete_after=10)
            return
        
        # Check if user is replying to a message with an image
        if not message.reference or not message.reference.message_id:
            await message.reply(
                "❌ **How to submit:**\n"
                "1. Post your artwork as an image\n"
                "2. **Reply to your image** with `!submit`",
                delete_after=15
            )
            return
        
        try:
            # Fetch the referenced message
            referenced_message = await message.channel.fetch_message(message.reference.message_id)
            
            # Check if the referenced message is from the same user
            if referenced_message.author.id != message.author.id:
                await message.reply("❌ You can only submit your own artwork!", delete_after=10)
                return
            
            # Extract image URL from the referenced message
            image_url = None
            
            # Check attachments
            for attachment in referenced_message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    image_url = attachment.url
                    break
            
            # Check embeds if no attachment found
            if not image_url:
                for embed in referenced_message.embeds:
                    if embed.image:
                        image_url = embed.image.url
                        break
                    elif embed.thumbnail:
                        image_url = embed.thumbnail.url
                        break
            
            if not image_url:
                await message.reply("❌ The referenced message doesn't contain an image.", delete_after=10)
                return
            
            # Handle !check command - just lookup existing submission
            if command == '!check':
                # Look for existing submission to this challenge
                existing_submission = art_manager.get_user_submission(
                    challenge_id=active_challenge.get("challenge_id"),
                    user_id=message.author.id
                )
                
                if not existing_submission:
                    await message.reply("❌ No submission found for this challenge. Use `!submit` to submit your artwork!", delete_after=10)
                    return
                
                # Show the existing verification result
                from views.art_challenge_view import ArtChallengeEmbed
                embed = ArtChallengeEmbed.create_submission_result_embed(existing_submission, message.author)
                await message.reply(embed=embed, delete_after=60)
                return
            
            # Handle !submit command - verify new submission
            # Send a processing message
            processing_msg = await message.reply("🔄 **Verifying your submission...** This may take a moment.")
            
            try:
                # Submit the entry
                result = await art_manager.submit_entry(
                    challenge_id=active_challenge.get("challenge_id"),
                    user_id=message.author.id,
                    image_url=image_url,
                    message_id=referenced_message.id
                )
                
                # Delete the processing message
                await processing_msg.delete()
                
                if result.get("success"):
                    # Import the embed creator
                    from views.art_challenge_view import ArtChallengeEmbed
                    
                    embed = ArtChallengeEmbed.create_submission_result_embed(result, message.author)
                    await message.reply(embed=embed, delete_after=300)
                    
                    # Award points to user's main leaderboard if verified
                    if result.get("verified") and result.get("points_awarded", 0) > 0:
                        points = result.get("points_awarded", 0)
                        await self.bot.leaderboard_manager.add_points(
                            user_id=message.author.id,
                            user_name=message.author.display_name,
                            points=points,
                            point_type="art_challenge",
                            reason=f"Art challenge completion"
                        )
                        logger.info(f"Awarded {points} art challenge points to {message.author.display_name}")
                else:
                    await message.reply(f"❌ {result.get('error', 'Failed to submit entry')}", delete_after=60)
                    
            except Exception as e:
                logger.error(f"Error processing art submission: {e}")
                await processing_msg.delete()
                await message.reply("❌ An error occurred while processing your submission.", delete_after=60)
                
        except discord.NotFound:
            await message.reply("❌ Could not find the referenced message.", delete_after=10)
        except Exception as e:
            logger.error(f"Error handling art challenge submission: {e}")
            await message.reply("❌ An error occurred while processing your submission.", delete_after=10)
