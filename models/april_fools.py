"""April Fools utilities — active only on April 1st."""
from __future__ import annotations

import discord
from discord.ext import commands
import logging
import random
import io
import asyncio
from datetime import datetime
from typing import Optional


class RoastInterrupt(commands.CommandError):
    """Raised to cancel a command because the bot decided to roast instead."""
    pass

logger = logging.getLogger(__name__)

# Track users who already received the uwuify explanation DM
_uwufied_dm_sent: set[int] = set()

# ── Unicode upside-down text ──────────────────────────────────────────────────
_FLIP_MAP = {
    'a': 'ɐ', 'b': 'q', 'c': 'ɔ', 'd': 'p', 'e': 'ǝ', 'f': 'ɟ',
    'g': 'ƃ', 'h': 'ɥ', 'i': 'ᴉ', 'j': 'ɾ', 'k': 'ʞ', 'l': 'l',
    'm': 'ɯ', 'n': 'u', 'o': 'o', 'p': 'd', 'q': 'b', 'r': 'ɹ',
    's': 's', 't': 'ʇ', 'u': 'n', 'v': 'ʌ', 'w': 'ʍ', 'x': 'x',
    'y': 'ʎ', 'z': 'z',
    'A': '∀', 'B': 'ᗺ', 'C': 'Ɔ', 'D': 'ᗡ', 'E': 'Ǝ', 'F': 'Ⅎ',
    'G': 'פ', 'H': 'H', 'I': 'I', 'J': 'ſ', 'K': 'ʞ', 'L': '˥',
    'M': 'W', 'N': 'N', 'O': 'O', 'P': 'Ԁ', 'Q': 'Q', 'R': 'ᴚ',
    'S': 'S', 'T': '┴', 'U': '∩', 'V': 'Λ', 'W': 'M', 'X': 'X',
    'Y': '⅄', 'Z': 'Z',
    '0': '0', '1': 'Ɩ', '2': 'ᄅ', '3': 'Ɛ', '4': 'ㄣ', '5': 'ϛ',
    '6': '9', '7': 'ㄥ', '8': '8', '9': '6',
    '.': '˙', ',': "'", "'": ',', '!': '¡', '?': '¿',
    '(': ')', ')': '(', '[': ']', ']': '[', '{': '}', '}': '{',
    '<': '>', '>': '<', '_': '‾',
}


def flip_text(text: str) -> str:
    """Return the upside-down (flipped) version of a string."""
    return ''.join(_FLIP_MAP.get(c, c) for c in reversed(text))


# ── Manual toggle ────────────────────────────────────────────────────────────
# Controlled via /modconfig setting:april1st value:true|false
# Cached in memory so is_april_fools() stays synchronous.
_april_fools_active: bool = False


def is_april_fools() -> bool:
    """Return True when the april1st mode is manually enabled."""
    return _april_fools_active


def set_april_fools_mode(value: bool) -> None:
    """Set the in-memory april1st toggle (call after saving to DB)."""
    global _april_fools_active
    _april_fools_active = bool(value)
    logger.info(f"April Fools mode {'ENABLED' if value else 'DISABLED'}")


def flip_embed(embed: discord.Embed) -> discord.Embed:
    """Return a copy of *embed* with every text field upside-down."""
    flipped = discord.Embed(
        title=flip_text(embed.title) if embed.title else embed.title,
        description=flip_text(embed.description) if embed.description else embed.description,
        color=embed.color,
        timestamp=embed.timestamp,
        url=embed.url,
    )
    # Fields
    for field in embed.fields:
        flipped.add_field(
            name=flip_text(str(field.name)) if field.name else field.name,
            value=flip_text(str(field.value)) if field.value else field.value,
            inline=field.inline,
        )
    # Footer
    if embed.footer and embed.footer.text:
        flipped.set_footer(
            text=flip_text(embed.footer.text),
            icon_url=embed.footer.icon_url,
        )
    elif embed.footer:
        flipped.set_footer(text=embed.footer.text, icon_url=embed.footer.icon_url)
    # Author
    if embed.author and embed.author.name:
        flipped.set_author(
            name=flip_text(embed.author.name),
            url=embed.author.url,
            icon_url=embed.author.icon_url,
        )
    # Images / thumbnails
    if embed.image:
        flipped.set_image(url=embed.image.url)
    if embed.thumbnail:
        flipped.set_thumbnail(url=embed.thumbnail.url)
    return flipped


# ── Command roast system ──────────────────────────────────────────────────────
_ROASTS = [
    "nah.",
    "no.",
    "I read your command. I chose not to.",
    "{name}, I've seen better requests from a broken calculator.",
    "Request received. Request ignored.",
    "I considered it. The answer is still no.",
    "{name} really thought that was gonna work.",
    "Command not found. (It was found. I just don't want to.)",
    "Have you tried asking someone who cares?",
    "{name}, babe, no.",
    "Declined. Try being more impressive.",
    "I'm going to pretend that didn't happen.",
    "Error 404: motivation not found.",
    "Sure! Just kidding.",
    "{name} typed all that and for what.",
    "I could do that. I won't.",
    "Wow. Okay. No.",
    "That's... a choice you made. A wrong one.",
    "Command rejected on the grounds of general vibes.",
    "{name}, your request has been carefully reviewed and thoroughly ignored.",
    "Processing... processed... denied.",
    "Maybe in another life.",
    "I don't get paid enough for this.",
    "{name}, I'm going to need you to lower your expectations.",
    "Respectfully, absolutely not.",
    "New response just dropped: no.",
    "I looked at this request and laughed.",
    "{name}, the audacity.",
    "Not today. Not ever, honestly.",
    "Your request is in a queue. The queue is a trash can.",
]


def get_random_roast(display_name: str) -> str:
    """Return a random roast, optionally personalised with the user's name."""
    template = random.choice(_ROASTS)
    return template.format(name=display_name)


async def maybe_roast(ctx) -> bool:
    """50 % chance to roast the user instead of running a prefix/hybrid command.

    Call this in a ``before_invoke`` hook.  Returns True when a roast fired
    (the caller should raise RoastInterrupt), False otherwise.
    """
    if not is_april_fools():
        return False
    if random.random() >= 0.5:
        return False
    roast = get_random_roast(ctx.author.display_name)
    try:
        await ctx.send(roast)
    except Exception as e:
        logger.warning(f"Failed to send roast: {e}")
    return True


async def maybe_roast_interaction(interaction: discord.Interaction) -> bool:
    """50 % chance to roast the user on a slash/app command interaction.

    Use in ``bot.tree.interaction_check``.  Returns True when roast fired
    (return False from the check to cancel the command).
    """
    if not is_april_fools():
        return False
    if random.random() >= 0.5:
        return False
    roast = get_random_roast(interaction.user.display_name)
    try:
        await interaction.response.send_message(roast)
    except Exception as e:
        logger.warning(f"Failed to send interaction roast: {e}")
    return True


# ── April Fools sticker ───────────────────────────────────────────────────────
AF_STICKER_ID = 1488638374607847624

# ── Jake webhook helper ───────────────────────────────────────────────────────
JAKE_AVATAR = "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcS27SkChhy813El9NgBiN-utKRvU-LKbN4oyg&s"
JAKE_NAME = "Jake"

JAKE_RESPONSES = [
    "yo so uh, new video just dropped or whatever lol\n{link}",
    "hey guys jake here. ino is on vacation so i'm running things now. video:\n{link}",
    "idk what i'm doing but there's a new video i think\n{link}",
    "bro i literally just started this job and they're already making me announce stuff\n{link}",
    "new video alert!!!! (ino wrote me a 47 page script. i read the first sentence.)\n{link}",
    "sup. video. watch it. or don't. idk man\n{link}",
    "she said 'jake just post the video link' so.\n{link}",
    "i'm jake. i don't know who riko is. i don't know what a shrine is. new video though:\n{link}",
    "URGENT VIDEO ANNOUNCEMENT (it's not urgent she just told me to make it sound exciting)\n{link}",
    "ino left me a sticky note that says 'announce videos or else'. so here's a video:\n{link}",
    "ok so there's apparently a whole personality i'm supposed to do?? sounds like a lot. video:\n{link}",
    "genuine question: what is a shrine spirit and why did she leave ME in charge\n{link}",
]


async def send_as_jake(
    channel: discord.TextChannel,
    content: str,
    embed: Optional[discord.Embed] = None,
) -> bool:
    """Send a message as the Jake webhook.

    Finds or creates a webhook named 'Jake' in the channel and posts through it.
    Returns True on success, False on failure.
    """
    try:
        webhooks = await channel.webhooks()
        webhook = discord.utils.get(webhooks, name=JAKE_NAME)
        if webhook is None:
            webhook = await channel.create_webhook(name=JAKE_NAME)
            logger.info(f"Created Jake webhook in #{channel.name}")

        kwargs: dict = {"username": JAKE_NAME, "avatar_url": JAKE_AVATAR}
        if content:
            kwargs["content"] = content
        if embed:
            kwargs["embeds"] = [embed]

        await webhook.send(**kwargs)
        return True
    except Exception as e:
        logger.error(f"Failed to send as Jake in #{channel.name}: {e}")
        return False


def get_jake_announcement(video_link: str) -> str:
    """Return a random Jake-style announcement for a video."""
    template = random.choice(JAKE_RESPONSES)
    return template.format(link=video_link)


# ── April Fools quest pool ────────────────────────────────────────────────────
APRIL_FOOLS_QUESTS = [
    {
        "quest_id": "af_existential_ino",
        "name": flip_text("Ino's Crisis"),
        "description": "Post a picture of Ino having an existential crisis. "
                       "She stares into the void. The void stares back.",
        "quest_type": "post_images",
        "category": "april_fools",
        "difficulty": "easy",
        "target_count": 1,
        "reward_points": 0,
        "rarity_chance": 1.0,
        "is_daily": True,
        "is_april_fools": True,
    },
    {
        "quest_id": "af_riko_freakout",
        "name": flip_text("Riko's Freakout"),
        "description": "Post Riko absolutely losing it. "
                       "What did you do to her?? Ino is very, very tired.",
        "quest_type": "post_images",
        "category": "april_fools",
        "difficulty": "easy",
        "target_count": 1,
        "reward_points": 0,
        "rarity_chance": 1.0,
        "is_daily": True,
        "is_april_fools": True,
    },
    {
        "quest_id": "af_chaos_rater",
        "name": flip_text("Chaos Rater"),
        "description": "Give 10 thumbs down today. Spread the chaos. "
                       "Ino has completely given up trying to stop you.",
        "quest_type": "rate_images",
        "category": "april_fools",
        "difficulty": "easy",
        "target_count": 10,
        "reward_points": 0,
        "rarity_chance": 1.0,
        "is_daily": True,
        "is_april_fools": True,
    },
    {
        "quest_id": "af_do_nothing",
        "name": flip_text("Do Nothing"),
        "description": "Post zero images today. Absolutely none. "
                       "This quest completes instantly and rewards 1 point. "
                       "Ino solemnly salutes your restraint.",
        "quest_type": "post_images",
        "category": "april_fools",
        "difficulty": "easy",
        "target_count": 0,
        "reward_points": 1,
        "rarity_chance": 1.0,
        "is_daily": True,
        "is_april_fools": True,
        "completed": True,
        "current_count": 0,
    },
    {
        "quest_id": "af_shrine_offering",
        "name": flip_text("Shrine Offering"),
        "description": "Post 3 images as a tribute to the shrine. "
                       "Ino did NOT ask for this. She is sighing loudly.",
        "quest_type": "post_images",
        "category": "april_fools",
        "difficulty": "easy",
        "target_count": 3,
        "reward_points": 0,
        "rarity_chance": 1.0,
        "is_daily": True,
        "is_april_fools": True,
    },
    {
        "quest_id": "af_confused_art",
        "name": flip_text("What Even Is Art"),
        "description": "Post 2 images that have absolutely nothing to do with each other. "
                       "Random chaos is encouraged. Ino is questioning her career choices.",
        "quest_type": "post_images",
        "category": "april_fools",
        "difficulty": "easy",
        "target_count": 2,
        "reward_points": 0,
        "rarity_chance": 1.0,
        "is_daily": True,
        "is_april_fools": True,
    },
]

# ── April Fools fake badge ─────────────────────────────────────────────────────
APRIL_FOOLS_ACHIEVEMENT = {
    "achievement_id": "april_fools_2026",
    "name": "🃏 " + flip_text("April Fool"),
    "description": flip_text("You existed on April 1st. That's it. That's the whole achievement."),
    "category": "special",
    "rarity": "legendary",
    "reward_points": 0,
    "icon": "🃏",
    "is_secret": False,
    "is_april_fools": True,
    "earned_at": datetime(2026, 4, 1),
}


# ── April Fools Art Challenge Prompts ─────────────────────────────────────────
# 50+ custom drawing prompts for AF mode - Ino/Jake themed
AF_ART_CHALLENGE_PROMPTS = [
    # Ino themed prompts (tired, didn't feel like it, being dramatic)
    "Ino didn't feel like getting out of bed today. Draw her still in pajamas, hair a mess, looking at her phone",
    "Ino is having an existential crisis. Draw her staring into the void while drinking coffee",
    "Ino told you to draw her looking cool but you only have 5 minutes. Draw a quick sketch",
    "Ino forgot to do her hair. Draw her with absolute bedhead and a look of mild despair",
    "Ino is judging your art from her couch. Draw her lounging with a very tired expression",
    "Ino said she 'literally cannot even' today. Draw her dramatically draped over furniture",
    "Ino didn't want to wear her shrine outfit. Draw her in casual clothes looking relieved",
    "Ino is scrolling social media while pretending to work. Draw her 'multitasking'",
    "Ino is tired of being a shrine spirit. Draw her filling out a job application at Starbucks",
    "Ino needs coffee but the machine is broken. Draw her staring at a broken coffee maker",
    "Ino is procrastinating on shrine duties. Draw her doing literally anything else",
    "Ino is eating chips in bed at 3am. Draw her having a self-care moment",
    "Ino is giving you side-eye while holding a mug. Draw her skeptical expression",
    "Ino is wearing sunglasses indoors for no reason. Draw her being unnecessarily cool",
    "Ino is wrapped in 5 blankets watching anime. Draw her cozy setup",
    "Ino is taking a nap in an inconvenient place. Draw her sleeping somewhere weird",
    "Ino is holding a 'will work for snacks' sign. Draw her being dramatic about hunger",
    "Ino is doing her taxes and crying. Draw adulting hitting her hard",
    "Ino is playing video games instead of shrine duties. Draw her gaming setup",
    "Ino is standing in the rain looking dramatic. Draw her being unnecessarily cinematic",
    "Ino is sitting on the floor because the couch is too far. Draw her being lazy",
    "Ino is holding a list of complaints. Draw her being very thorough about what's wrong",
    "Ino is wearing a hoodie 3 sizes too big. Draw her drowning in fabric",
    "Ino is staring at the ceiling contemplating life choices. Draw her being philosophical",
    "Ino is eating instant ramen at 2am. Draw her late-night lifestyle",
    
    # Jake themed prompts (clueless, running things, confused)
    "Jake is trying to run the shrine and failing. Draw him looking confused at paperwork",
    "Jake is eating lunch at Ino's desk without permission. Draw him making himself at home",
    "Jake is reading Ino's 47-page instruction manual. Draw him on page 1 looking lost",
    "Jake is trying to dress like a shrine spirit. Draw his terrible cosplay attempt",
    "Jake is talking to an empty shrine. Draw him asking where everyone is",
    "Jake is wearing Ino's shrine outfit as a joke. Draw him being way too confident",
    "Jake is trying to use shrine magic and nothing happens. Draw him confused why it won't work",
    "Jake is taking a selfie in the shrine. Draw his tourist energy",
    "Jake is napping in Ino's spot. Draw him taking liberties",
    "Jake is eating all the shrine offerings. Draw him snacking disrespectfully",
    "Jake is holding a clipboard pretending to know what he's doing. Draw fake authority",
    "Jake is wearing a tie over a t-shirt for 'professionalism'. Draw his business casual",
    "Jake is confused about what a 'shrine spirit' even is. Draw him googling it",
    "Jake is sitting in Ino's chair spinning around. Draw him enjoying his promotion too much",
    "Jake is trying to answer follower questions with made-up answers. Draw him winging it",
    
    # Riko themed prompts
    "Riko standing in a completely normal position. Draw her being unusually calm",
    "Riko doing taxes and looking stressed. Draw her adulting poorly",
    "Riko trying to cook and creating chaos. Draw kitchen disaster",
    "Riko at a job interview looking nervous. Draw her trying to be professional",
    "Riko waiting in line at the DMV. Draw her being mundane",
    "Riko trying to assemble IKEA furniture. Draw her confusion and frustration",
    "Riko doing laundry and finding mysterious items. Draw her confusion",
    "Riko grocery shopping with a very long list. Draw her being overwhelmed",
    "Riko trying to parallel park. Draw her struggle in real time",
    "Riko at the dentist looking terrified. Draw her medical anxiety",
    "Riko trying to tech support for her parents. Draw her patience being tested",
    
    # Mixed/Other prompts
    "Ino and Jake having a staring contest. Draw the tension",
    "Jake trying to convince Ino to get out of bed. Draw the negotiation",
    "Ino throwing Jake out of her shrine. Draw the eviction",
    "Riko meeting Jake for the first time. Draw the awkward introduction",
    "Ino hiding from her responsibilities behind Jake. Draw her using him as a shield",
    "Jake trying to explain what he thinks a shrine spirit does. Draw his wrong assumptions",
    "Ino and Riko having coffee and gossiping. Draw their friendship",
    "Jake accidentally breaking something in the shrine. Draw his panic",
    "Ino doing Jake's makeup as revenge. Draw the makeover",
    "All three trying to take a group photo and looking chaotic. Draw the disaster",
]

# AF mode art challenge spawn interval (minutes)
AF_ART_CHALLENGE_INTERVAL_MINUTES = 30


# ── Uwuify text transformation ────────────────────────────────────────────────
import re

# Regex patterns for preserving links
TENOR_PATTERN = re.compile(r'https?://tenor\.com/view/[^\s]+', re.IGNORECASE)
GENERIC_URL_PATTERN = re.compile(r'https?://[^\s]+', re.IGNORECASE)
EMOJI_PATTERN = re.compile(r'<a?:\w+:\d+>')  # Discord custom emojis

# Zalgo/combining character ranges to strip
ZALGO_PATTERN = re.compile(
    r'[\u0300-\u036f\u0483-\u0489\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7'
    r'\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e8\u06ea-\u06ed\u0711'
    r'\u0730-\u074a\u07a6-\u07b0\u07eb-\u07f3\u0816-\u0819\u081b-\u0823\u0825-\u0827'
    r'\u0829-\u082d\u0859-\u085b\u08d4-\u08e1\u08e3-\u08ff\u093c\u094d\u0951-\u0954'
    r'\u09bc\u09cd\u09e3\u0a3c-\u0a4d\u0abc\u0acd\u0b3c\u0b4d\u0bcd\u0c4d\u0cbc\u0ccd'
    r'\u0d4d\u0dca\u0e38-\u0e3a\u0e47-\u0e4e\u0eb8-\u0eba\u0ec8-\u0ecd\u0f18\u0f19'
    r'\u0f35\u0f37\u0f39\u0f57\u0f58\u0f72-\u0f76\u0f78\u0f93-\u0f97\u0f99-\u0fad'
    r'\u0fb9\u10f26-\u10f2a\u1d165-\u1d169\u1d16d-\u1d172\u1d17b-\u1d182\u1d185-\u1d18b'
    r'\u1d1aa-\u1d1ad\u1d242-\u1d244\u1e00-\u1eff]+',
    re.UNICODE
)

def clean_zalgo(text: str) -> str:
    """Remove zalgo/glitched combining characters from text."""
    # First pass: remove combining characters
    cleaned = ZALGO_PATTERN.sub('', text)
    # Second pass: normalize unicode
    import unicodedata
    cleaned = unicodedata.normalize('NFKC', cleaned)
    return cleaned


def normalize_unicode_fonts(text: str) -> str:
    """Normalize Unicode font/glyph bypasses (Gothic, Coptic, etc.) back to ASCII.
    
    Examples:
    - 𝔊𝔬𝔱𝔥𝔦𝔠 -> Gothic
    - 𐌂𐌉𐌍Ᏽ -> CING
    - 𝓈𝒸𝓇𝒾𝓅𝓉 -> script
    """
    import unicodedata
    
    # First apply NFKC normalization which handles many mathematical/script variants
    text = unicodedata.normalize('NFKC', text)
    
    # Additional mappings for characters NFKC doesn't fully catch
    # Fullwidth forms, circled letters, etc.
    font_mappings = {
        # Fullwidth ASCII variants
        'Ａ': 'A', 'Ｂ': 'B', 'Ｃ': 'C', 'Ｄ': 'D', 'Ｅ': 'E', 'Ｆ': 'F',
        'Ｇ': 'G', 'Ｈ': 'H', 'Ｉ': 'I', 'Ｊ': 'J', 'Ｋ': 'K', 'Ｌ': 'L',
        'Ｍ': 'M', 'Ｎ': 'N', 'Ｏ': 'O', 'Ｐ': 'P', 'Ｑ': 'Q', 'Ｒ': 'R',
        'Ｓ': 'S', 'Ｔ': 'T', 'Ｕ': 'U', 'Ｖ': 'V', 'Ｗ': 'W', 'Ｘ': 'X',
        'Ｙ': 'Y', 'Ｚ': 'Z',
        'ａ': 'a', 'ｂ': 'b', 'ｃ': 'c', 'ｄ': 'd', 'ｅ': 'e', 'ｆ': 'f',
        'ｇ': 'g', 'ｈ': 'h', 'ｉ': 'i', 'ｊ': 'j', 'ｋ': 'k', 'ｌ': 'l',
        'ｍ': 'm', 'ｎ': 'n', 'ｏ': 'o', 'ｐ': 'p', 'ｑ': 'q', 'ｒ': 'r',
        'ｓ': 's', 'ｔ': 't', 'ｕ': 'u', 'ｖ': 'v', 'ｗ': 'w', 'ｘ': 'x',
        'ｙ': 'y', 'ｚ': 'z',
        # Additional symbol variants that NFKC might miss
        'ᴀ': 'A', 'ʙ': 'B', 'ᴄ': 'C', 'ᴅ': 'D', 'ᴇ': 'E', 'ғ': 'F',
        'ɢ': 'G', 'ʜ': 'H', 'ɪ': 'I', 'ᴊ': 'J', 'ᴋ': 'K', 'ʟ': 'L',
        'ᴍ': 'M', 'ɴ': 'N', 'ᴏ': 'O', 'ᴘ': 'P', 'ǫ': 'Q', 'ʀ': 'R',
        's': 'S', 'ᴛ': 'T', 'ᴜ': 'U', 'ᴠ': 'V', 'ᴡ': 'W', 'x': 'X',
        'ʏ': 'Y', 'ᴢ': 'Z',
        # Coptic letters (used for bypasses like 𐌂𐌉𐌍Ᏽ)
        '𐌂': 'C', '𐌉': 'I', '𐌍': 'N', 'Ᏽ': 'G', '𐌄': 'E',
        '𐌀': 'A', '𐋅': 'H', '𐌁': 'B', 'Ꝋ': 'O', '𐌕': 'S',
        '𐌐': 'P', '𐌓': 'R', '𐌔': 'S', '𐌖': 'U', '𐌚': 'F',
        '𐌑': 'M', '𐌙': 'Y', '𐌃': 'D', '𐌗': 'Q', '𐌘': 'R',
        '𐌆': 'Z', '𐌛': 'S', '𐌜': 'T', '𐌝': 'Y', '𐌞': 'F',
        '𐌟': 'R', '𐌡': 'H', '𐌢': 'H', '𐌣': 'H', '𐌤': 'H',
        '𐌥': 'V', '𐌦': 'V', '𐌧': 'G', '𐌨': 'G', '𐌩': 'N',
        '𐌪': 'N', '𐌫': 'J', '𐌬': 'J', '𐌭': 'TH', '𐌮': 'TH',
        '𐌯': 'PH', '𐌰': 'A', '𐌱': 'B', '𐌲': 'C', '𐌳': 'D',
        '𐌴': 'E', '𐌵': 'V', '𐌶': 'Z', '𐌷': 'H', '𐌸': 'TH',
        '𐌹': 'I', '𐌺': 'K', '𐌻': 'L', '𐌼': 'M', '𐌽': 'N',
        '𐌾': 'J', '𐌿': 'U', '𐍀': 'P', '𐍁': 'Q', '𐍂': 'R',
        '𐍃': 'S', '𐍄': 'T', '𐍅': 'W', '𐍆': 'F', '𐍇': 'X',
        '𐍈': 'H', '𐍉': 'O', '𐍊': 'Z', '𐍋': 'Z', '𐍌': 'Z',
        # Additional Gothic/Coptic lookalikes
        '𐌊': 'K', '𐌲': 'C', '𐌐': 'P', '𐌔': 'S', '𐌆': 'Z',
        'Ꝛ': 'R', 'Ꝙ': 'Q', 'Ꝿ': 'F', 'Ᵹ': 'G', 'Ꞃ': 'R',
        'Ꞅ': 'S', 'Ꞇ': 'T', 'ꝉ': 'd', 'ꝑ': 'p', 'ꝕ': 'q',
    }
    
    result = []
    for char in text:
        # Try mapping first
        if char in font_mappings:
            result.append(font_mappings[char])
        else:
            # Check if it's a Latin letter lookalike from other scripts
            # Coptic, Gothic, etc.
            cat = unicodedata.category(char)
            name = unicodedata.name(char, '')
            
            # If it's a letter but from a non-Latin script that looks like Latin
            if cat.startswith('L') and any(x in name for x in ['GOTHIC', 'COPTIC', 'OLD', 'MEDIUM']):
                # Try to get similar looking ASCII
                # For now, best effort: keep the NFKC result
                result.append(char)
            else:
                result.append(char)
    
    return ''.join(result)


# EXTREME UWU SETTINGS - cranked to maximum cringe
STUTTER_CHANCE = 0.6
FACE_CHANCE = 0.7
NYA_CHANCE = 0.35
SPARKLE_CHANCE = 0.4
MEOW_CHANCE = 0.2
ASTERISK_ACTION_CHANCE = 0.25
W_DASH_CHANCE = 0.5
REPEAT_CHANCE = 0.2
KEYSMASH_CHANCE = 0.1

UWU_FACES = [
    "(・`ω´・)", ";;w;;", "owo", "UwU", ">w<", "^w^", "(o^▽^o)",
    "(˘▽˘)っ♡", "(・ω< )", "(´･ω･`)", "(„ᵕᴗᵕ„)", "(｡♥‿♥｡)",
    "(◕‿◕✿)", "(◕ᴗ◕✿)", "(✿◠‿◠)", "(◕‿◕)", "(◕ᴗ◕)", "(｡◕‿◕｡)",
    "(◕‿◕✿)", "(✿◠‿◠)", "(｡♥‿♥｡)", "(´｡• ᵕ •｡`)", "(｡・//ω//・｡)",
    "rawr x3", ">////<", "nya~", "(´・ω・｀)", "(ꈍᴗꈍ)", "(｡･ω･｡)",
    "(◠‿◠✿)", "~hewwo~", "OwO what's this?", "*notices bulge*", "uwu", "👀", "🥺",
    "(👉👈)", "(*^ω^)", "(＾▽＾)", "(◕‿◕✿)♡", "✧(•̀ᴗ•́)و", "(◍•ᴗ•◍)", "(｡･ω･｡)ﾉ♡",
    "(づ｡◕‿‿◕｡)づ", "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧", "uwu what's this???", "*boops your nose*",
    "*nuzzles*", "*pounces on you*", "nyaa~", "rawr~", "mrrp~", "mrow~",
    "(｡・`ω´・｡)", "(๑°o°๑)", "(⁄ ⁄•⁄ω⁄•⁄ ⁄)", "(´-ω-`)", "(´･ω･`)",
    "(≧◡≦)", "(◕ᴥ◕)", "(✿ ♡‿♡)", "uwu~", "owo~", "OWO", "UwU", "QWQ", "TWT",
    "(｡♥‿♥｡)", "(✿ ♥‿♥)", "(*≧ω≦*)", "(☆ω☆)", "(｡•̀ᴗ-)✧", "(⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)",
    "nya nya~", "OwO✨", "uwu✨", "🥺👉👈", "🐾💕", "(っ˘з(˘⌣˘ )♡"
]

ASTERISK_ACTIONS = [
    "*tilts head*", "*wiggles ears*", "*paws at you*", "*nuzzles closer*",
    "*wags tail excitedly*", "*blinks cutely*", "*fidgets nervously*",
    "*leans on you*", "*perks up*", "*makes grabby hands*", "*squeaks*",
    "*does a happy dance*", "*squirms happily*", "*peeks at you*",
    "*hides face*", "*twirls hair*", "*giggles shyly*", "*purrs softly*",
    "*snuggles*", "*boops*", "*blep*", "*wink wonk*", "*heart eyes*",
    "*sparkle sparkle*", "*tiny uwu noises*", "*happy uwu sounds*",
    "*cuddles*", "*shyly looks away*", "*bounces excitedly*", "*eager wiggles*",
    "*soft paw taps*", "*nuzzle nuzzle*", "*happy tail thumping*", "*tiny meow*",
    "*makes uwu face*", "*uwu intensifies*", "*extreme nuzzling*", "*gives paw*"
]

MEOW_VARIATIONS = ["meow~", "mew~", "mrow~", "mrrow~", "nya~", "nyaa~", "mrrp~", "prrr~", "mya~", "mnya~"]

SPARKLES = ["✨", "💖", "💕", "💗", "🌸", "🎀", "🐾", "⭐", "🌟", "💝", "💫", "🦋"]

KEYSMASHES = ["asdfghjkl", "qwertyuiop", "sjdksjdk", "ahhhh", "wjwkwkw", "eeeeee", "aaaaaa"]

def uwuify_text(text: str) -> str:
    """Transform text into MAXIMUM EXTREME uwu speak.
    
    Maximum cringe rules:
    - Clean zalgo/bypass text first
    - r/l -> w, R/L -> W  
    - 'th' -> 'd' or 'f'
    - 'no' -> 'nyo' (aggressive)
    - 'na' -> 'nya', 'ne' -> 'nye', 'ni' -> 'nyi', 'mu' -> 'myu'
    - EXTREME stuttering ~60% (double/triple/quadruple)
    - Add uwu face ~70% at end
    - Add asterisk actions ~25% randomly
    - Add sparkles ~40% between words
    - Add meow variations ~20%
    - Add w- dashes ~50% (w-what, h-hewwo)
    - Repeat words ~20% (word word)
    - Occasional keysmash ~10%
    - Tildes ~80% on sentences
    """
    if not text:
        return text
    
    # First: clean any zalgo/glitched text
    text = clean_zalgo(text)
    
    # Second: normalize unicode font bypasses (Gothic, Coptic, etc.)
    text = normalize_unicode_fonts(text)
    
    # Extract and store links/emojis to preserve them
    preserved_items = []
    
    # Store tenor links
    tenor_links = TENOR_PATTERN.findall(text)
    for i, link in enumerate(tenor_links):
        placeholder = f"{{TENOR_{i}}}"
        preserved_items.append((placeholder, link))
        text = text.replace(link, placeholder, 1)
    
    # Store other URLs
    other_links = [m for m in GENERIC_URL_PATTERN.findall(text) if not m.startswith("{TENOR_")]
    for i, link in enumerate(other_links):
        placeholder = f"{{URL_{i}}}"
        preserved_items.append((placeholder, link))
        text = text.replace(link, placeholder, 1)
    
    # Store Discord emojis
    emojis = EMOJI_PATTERN.findall(text)
    for i, emoji in enumerate(emojis):
        placeholder = f"{{EMOJI_{i}}}"
        preserved_items.append((placeholder, emoji))
        text = text.replace(emoji, placeholder, 1)
    
    # Transform text
    result = []
    words = text.split(' ')
    
    # Randomly insert asterisk action at start
    if random.random() < ASTERISK_ACTION_CHANCE:
        result.append(random.choice(ASTERISK_ACTIONS))
    
    prev_word = ""
    for word in words:
        # Skip if it's a placeholder
        if word.startswith('{') and word.endswith('}'):
            result.append(word)
            continue
        
        # Check for punctuation at end
        punctuation = ''
        while word and word[-1] in '.,!?;:':
            punctuation = word[-1] + punctuation
            word = word[:-1]
        
        if not word:
            result.append(punctuation)
            continue
        
        # EXTREME stuttering - can be n-n-, n-n-n-, or n-n-n-n-
        if len(word) > 2 and random.random() < STUTTER_CHANCE:
            first_char = word[0].lower()
            if first_char.isalpha():
                roll = random.random()
                if roll < 0.2:
                    # Quadruple stutter!
                    word = f"{first_char}-{first_char}-{first_char}-{first_char}-{word}"
                elif roll < 0.5:
                    # Triple stutter
                    word = f"{first_char}-{first_char}-{first_char}-{word}"
                else:
                    # Double stutter
                    word = f"{first_char}-{first_char}-{word}"
        
        # Transform the word
        transformed = word
        
        # nya-ify: no -> nyo, na -> nya, ne -> nye, ni -> nyi, mu -> myu
        def nya_replace(m):
            s = m.group(0)
            if s.lower() == 'no':
                return 'nyO' if s[1].isupper() else 'nyo'
            elif s.lower() == 'na':
                return 'nyA' if s[1].isupper() else 'nya'
            elif s.lower() == 'ne':
                return 'nyE' if s[1].isupper() else 'nye'
            elif s.lower() == 'ni':
                return 'nyI' if s[1].isupper() else 'nyi'
            elif s.lower() == 'mu':
                return 'myU' if s[1].isupper() else 'myu'
            return s
        
        # Aggressive nya replacement
        transformed = re.sub(r'(?i)\b(no|na|ne|ni|mu)\b', nya_replace, transformed)
        transformed = re.sub(r'(?i)(no|na|ne|ni|mu)(?=[^a-zA-Z])', nya_replace, transformed)
        
        # r/l -> w, R/L -> W
        transformed = transformed.replace('r', 'w').replace('l', 'w')
        transformed = transformed.replace('R', 'W').replace('L', 'W')
        
        # th -> d or f
        new_chars = []
        i = 0
        while i < len(transformed):
            if i < len(transformed) - 1 and transformed[i:i+2].lower() == 'th':
                next_char = transformed[i+2] if i+2 < len(transformed) else ''
                if next_char.lower() in 'aeiou':
                    new_chars.append('d' if transformed[i] == 't' else 'D')
                    i += 2
                    continue
                else:
                    new_chars.append('f' if transformed[i] == 't' else 'F')
                    i += 2
                    continue
            new_chars.append(transformed[i])
            i += 1
        transformed = ''.join(new_chars)
        
        # w- prefix chance (w-what, h-hewwo style)
        if random.random() < W_DASH_CHANCE and len(transformed) > 2:
            first_char = transformed[0].lower()
            if first_char in 'hw' and not transformed.startswith(('w-', 'h-')):
                transformed = f"{first_char}-{transformed}"
        
        # owo/uwu-ify endings more aggressively
        if transformed.lower().endswith('o') and len(transformed) > 1:
            if random.random() < 0.35:
                transformed = transformed[:-1] + ('owo' if transformed[-1].islower() else 'OWO')
        elif transformed.lower().endswith('u') and len(transformed) > 1:
            if random.random() < 0.35:
                transformed = transformed[:-1] + ('uwu' if transformed[-1].islower() else 'UWU')
        
        # Add sparkle before word randomly
        prefix = ''
        if random.random() < SPARKLE_CHANCE:
            prefix = random.choice(SPARKLES) + " "
        
        # Add nya~/meow suffix randomly
        suffix = ''
        if random.random() < NYA_CHANCE and len(transformed) > 2:
            suffixes = [' nya~', ' rawr', ' ~', ' ^w^', ' uwu', ' owo']
            suffix = random.choice(suffixes)
        
        # Word repetition (word word)
        if random.random() < REPEAT_CHANCE and len(transformed) > 2 and transformed != prev_word:
            transformed = f"{transformed} {transformed.lower()}"
        
        result.append(prefix + transformed + suffix + punctuation)
        prev_word = transformed.lower()
        
        # Random meow insertion between words
        if random.random() < MEOW_CHANCE:
            result.append(random.choice(MEOW_VARIATIONS))
    
    text = ' '.join(result)
    
    # Restore preserved items
    for placeholder, original in preserved_items:
        text = text.replace(placeholder, original, 1)
    
    # Add asterisk action in middle or end randomly
    if random.random() < ASTERISK_ACTION_CHANCE:
        text = text + " " + random.choice(ASTERISK_ACTIONS)
    
    # Occasional keysmash at end
    if random.random() < KEYSMASH_CHANCE:
        text = text + " " + random.choice(KEYSMASHES)
    
    # EXTREME tilde addition (~80% chance)
    if random.random() < 0.8 and not any(c in text[-5:] for c in ['~']):
        for punct in ['.', '!', '?']:
            if text.rstrip().endswith(punct):
                text = text.rstrip()[:-1] + punct + '~'
                break
        else:
            text = text + '~'
    
    # Add sparkle cluster at end randomly
    if random.random() < 0.5:
        sparkles = ''.join(random.choice(SPARKLES) for _ in range(random.randint(2, 5)))
        text = text + " " + sparkles
    
    # Add random uwu face at end (70% chance)
    if random.random() < FACE_CHANCE:
        text = text + " " + random.choice(UWU_FACES)
    
    return text


def should_uwuify_message(message: discord.Message) -> bool:
    """Check if a message should be uwuified.
    
    Skip if:
    - Message has only links/media (no text content)
    - Message is from a bot
    - Message is a command (starts with R! or /)
    """
    if message.author.bot:
        return False
    
    content = message.content.strip()
    
    # Skip empty messages
    if not content:
        return False
    
    # Skip commands
    if content.startswith(('R!', '/', '!', '?')):
        return False
    
    # Check if there's any actual text content (not just links)
    # Remove all URLs and see if anything remains
    text_without_links = GENERIC_URL_PATTERN.sub('', content).strip()
    text_without_emojis = EMOJI_PATTERN.sub('', text_without_links).strip()
    
    # If nothing remains after removing links/emojis, skip
    if not text_without_emojis:
        return False
    
    return True


async def uwuify_message_via_webhook(message: discord.Message) -> bool:
    """Delete original message and resend via webhook with uwuified text.
    
    Returns True if successful, False otherwise.
    """
    if not should_uwuify_message(message):
        return False
    
    try:
        # Create or get webhook
        webhooks = await message.channel.webhooks()
        webhook = discord.utils.get(webhooks, name="Ino-UwU")
        
        if webhook is None:
            webhook = await message.channel.create_webhook(name="Ino-UwU")
        
        # Uwuify the content
        uwu_content = uwuify_text(message.content)
        
        # If this was a reply, add a reply indicator at the start
        if message.reference and message.reference.message_id:
            try:
                reply_target = await message.channel.fetch_message(message.reference.message_id)
                reply_indicator = f"> in weply to **{reply_target.author.display_name}** nya~\n"
                uwu_content = reply_indicator + uwu_content
            except Exception:
                pass  # If we can't fetch the reply target, just send without indicator
        
        # Build kwargs for webhook send
        kwargs = {
            "content": uwu_content,
            "username": message.author.display_name,
            "avatar_url": str(message.author.display_avatar.url) if message.author.display_avatar else None,
        }
        
        # Handle attachments - try to re-upload them
        files = []
        for attachment in message.attachments:
            try:
                file_data = await attachment.read()
                files.append(discord.File(io.BytesIO(file_data), filename=attachment.filename))
            except Exception:
                # If we can't read attachment, include its URL in content
                kwargs["content"] += f"\n{attachment.url}"
        
        if files:
            kwargs["files"] = files
        
        # Send via webhook
        await webhook.send(**kwargs)
        
        # Add cute reaction before deleting (to show it's being uwuified)
        try:
            cute_emojis = ['🥺', '👉👈', '✨', '💖', '🐾', 'uwu']
            chosen = random.choice(cute_emojis)
            await message.add_reaction(chosen)
        except Exception:
            pass  # Silently fail if we can't react
        
        # Small delay so the reaction is visible briefly before deletion
        await asyncio.sleep(0.5)
        
        # Delete original message
        await message.delete()
        
        return True
        
    except discord.Forbidden:
        logger.warning(f"Missing permissions to uwuify message in #{message.channel.name}")
    except discord.HTTPException as e:
        logger.warning(f"HTTP error uwuifying message: {e}")
    except Exception as e:
        logger.error(f"Error uwuifying message: {e}")
    
    return False
