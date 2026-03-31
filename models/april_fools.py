"""April Fools utilities — active only on April 1st."""
from __future__ import annotations

import discord
import logging
import random
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

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


# ── Date helpers ──────────────────────────────────────────────────────────────
def is_april_fools() -> bool:
    """Return True if today is April 1st (local server time)."""
    now = datetime.now()
    return now.month == 4 and now.day == 1


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
