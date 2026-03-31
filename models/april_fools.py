"""April Fools utilities — active only on April 1st."""
from __future__ import annotations

import discord
from discord.ext import commands
import logging
import random
from datetime import datetime
from typing import Optional


class RoastInterrupt(commands.CommandError):
    """Raised to cancel a command because the bot decided to roast instead."""
    pass

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
