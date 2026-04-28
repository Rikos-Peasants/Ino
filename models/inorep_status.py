"""InoRep relationship tiers and helpers."""

from __future__ import annotations

from typing import Dict, List, Optional


INOREP_TIERS: List[Dict[str, object]] = [
    {"threshold": 10000, "status": "🌠 Ino's Mythic Constellation", "relationship": "🌌 Mythic", "color": 0xFFFFFF, "message": "Impossible devotion. Ino is pretending to stay composed, but the shrine records are glowing."},
    {"threshold": 8500, "status": "🛕 Ino's Eternal Shrine Keeper", "relationship": "⛩️ Eternal Trust", "color": 0xFFF8DC, "message": "You are basically part of the shrine's foundation now. Try not to let it go to your head."},
    {"threshold": 7000, "status": "🌌 Ino's Astral Guardian", "relationship": "✨ Astral Bond", "color": 0xF8F8FF, "message": "Your bond with Ino has wandered off into the stars. Dramatic, but honestly deserved."},
    {"threshold": 6000, "status": "☀️ Ino's Radiant Paragon", "relationship": "🌞 Radiant", "color": 0xFFFACD, "message": "Ino trusts you with shrine duties, sacred secrets, and probably the good snacks."},
    {"threshold": 5000, "status": "⚡ Ino's Cosmic Entity", "relationship": "🌌 Cosmic", "color": 0xFFFFFF, "message": "YOU ARE A GOD! Your bond with Ino transcends reality itself. Legends will be told of your devotion!"},
    {"threshold": 3500, "status": "🌟 Ino's Transcendent Guardian", "relationship": "✨ Divine Unity", "color": 0xFFFAFA, "message": "ABSOLUTE PERFECTION! You've transcended mortal bonds. Ino's love for you is eternal and infinite!"},
    {"threshold": 2500, "status": "👼 Ino's Celestial Being", "relationship": "🕊️ Celestial", "color": 0xFFE4B5, "message": "HEAVENLY! You are a divine presence in Ino's life. She worships the ground you walk on!"},
    {"threshold": 2000, "status": "👑 Ino's Divine Champion", "relationship": "💎 Eternal Bond", "color": 0xFFD700, "message": "LEGENDARY! You are a living legend! Ino considers you family. Your devotion is unmatched!"},
    {"threshold": 1500, "status": "🏆 Ino's Legendary Hero", "relationship": "👑 Legendary", "color": 0xFFB700, "message": "PHENOMENAL! You've achieved legendary status! Ino sees you as her ultimate protector!"},
    {"threshold": 1200, "status": "⚜️ Ino's Royal Guardian", "relationship": "👸 Royalty", "color": 0xFFA500, "message": "EXTRAORDINARY! Ino sees you as royalty. Your dedication is truly royal!"},
    {"threshold": 1000, "status": "💫 Ino's Elite Champion", "relationship": "🎖️ Elite", "color": 0xFF8C00, "message": "OUTSTANDING! You're among Ino's most elite supporters. She holds you in the highest regard!"},
    {"threshold": 800, "status": "💖 Ino's Soulmate", "relationship": "💕 True Love", "color": 0xFF69B4, "message": "INCREDIBLE! Ino trusts you completely. You're basically married to her at this point!"},
    {"threshold": 650, "status": "💝 Ino's Beloved", "relationship": "💗 Deep Affection", "color": 0xFF1493, "message": "Amazing dedication! Ino thinks about you all the time. You mean the world to her!"},
    {"threshold": 500, "status": "💘 Ino's Darling", "relationship": "💓 Strong Love", "color": 0xDA70D6, "message": "Exceptional! Ino has fallen for you. You're truly special to her!"},
    {"threshold": 400, "status": "💞 Ino's Sweetheart", "relationship": "💟 Devoted Love", "color": 0xD946EF, "message": "Incredible! Ino's heart skips a beat when she sees you. You're amazing!"},
    {"threshold": 300, "status": "🌹 Ino's True Love", "relationship": "🌺 Romance", "color": 0xC71585, "message": "Outstanding! Ino is head over heels for you! You're her true love!"},
    {"threshold": 250, "status": "🌸 Ino's Precious One", "relationship": "💖 Adoration", "color": 0xBA55D3, "message": "Wonderful! Ino cherishes every moment with you. You brighten her day!"},
    {"threshold": 200, "status": "✨ Ino's Favorite Person", "relationship": "💝 Special Bond", "color": 0x9370DB, "message": "Fantastic! Ino really, really likes you! You're at the top of her list!"},
    {"threshold": 150, "status": "🎀 Ino's Cherished Friend", "relationship": "🎁 Treasured", "color": 0x8B5CF6, "message": "Superb! Ino cherishes your friendship deeply. You're very special to her!"},
    {"threshold": 125, "status": "🌟 Ino's Trusted Ally", "relationship": "🤝 Close Friendship", "color": 0x7B68EE, "message": "Great work! Ino trusts you and enjoys your company!"},
    {"threshold": 100, "status": "⭐ Ino's Loyal Companion", "relationship": "💙 Trusted Friend", "color": 0x6A5ACD, "message": "Excellent! Ino values your loyalty and friendship greatly!"},
    {"threshold": 80, "status": "🌈 Ino's Devoted Friend", "relationship": "🌟 Devotion", "color": 0x5B86E5, "message": "Wonderful! Ino sees you as a devoted friend. Keep it up!"},
    {"threshold": 60, "status": "🌟 Ino's Good Friend", "relationship": "😊 Friendship", "color": 0x4169E1, "message": "You're doing excellent! Ino considers you a real friend!"},
    {"threshold": 45, "status": "⭐ Ino's Friend", "relationship": "😄 Friendly", "color": 0x1E90FF, "message": "You're doing great! Ino loves hanging out with you!"},
    {"threshold": 35, "status": "😊 Ino's Buddy", "relationship": "🙂 Companion", "color": 0x00CED1, "message": "Good job! Ino thinks you're pretty cool!"},
    {"threshold": 25, "status": "🌱 Ino's Pal", "relationship": "😌 Friendly", "color": 0x20B2AA, "message": "Nice! Ino enjoys your presence. You're a good person!"},
    {"threshold": 15, "status": "😊 Good Standing", "relationship": "👋 Known", "color": 0x32CD32, "message": "Keep being nice to Ino!"},
    {"threshold": 8, "status": "🙂 Positive", "relationship": "🤝 Recognized", "color": 0x3498DB, "message": "You're making a good impression on Ino!"},
    {"threshold": 3, "status": "😊 Noticed", "relationship": "👀 Observed", "color": 0x52B788, "message": "Ino is starting to notice you in a good way!"},
    {"threshold": 1, "status": "😐 Positive Neutral", "relationship": "🌤️ Hopeful", "color": 0xF1C40F, "message": "Not bad! Ino notices your efforts."},
    {"threshold": 0, "status": "😐 Neutral", "relationship": "❓ Stranger", "color": 0xBDC3C7, "message": "You're a blank slate. Ino doesn't know what to think of you yet..."},
    {"threshold": -1, "status": "😐 Barely Negative", "relationship": "🧐 Questioned", "color": 0xF39C12, "message": "You're just barely on Ino's radar for the wrong reasons..."},
    {"threshold": -3, "status": "😐 Slight Concern", "relationship": "🤨 Watchful", "color": 0xE67E22, "message": "Hmm... Ino is keeping an eye on you."},
    {"threshold": -6, "status": "😕 Slightly Annoying", "relationship": "😒 Annoyed", "color": 0xE74C3C, "message": "Ino is starting to find you a bit irritating."},
    {"threshold": -10, "status": "😠 On Thin Ice", "relationship": "💢 Irritated", "color": 0xD63031, "message": "Ino is getting upset with you. Better watch yourself..."},
    {"threshold": -15, "status": "😡 Problematic", "relationship": "😤 Angry", "color": 0xC0392B, "message": "You're becoming a real problem. Ino is quite upset!"},
    {"threshold": -20, "status": "😡 Ino's Irritant", "relationship": "😠 Disliked", "color": 0xA93226, "message": "You're really pushing it! Ino is NOT happy with you!"},
    {"threshold": -25, "status": "🤬 Troublesome", "relationship": "😖 Frustrated", "color": 0x922B21, "message": "You're causing trouble! Ino is fed up with your behavior!"},
    {"threshold": -35, "status": "🤬 Ino's Nuisance", "relationship": "😡 Hostile", "color": 0x7B241C, "message": "Ino really doesn't like you. You've been very rude!"},
    {"threshold": -50, "status": "💢 Ino's Problem", "relationship": "🚫 Avoided", "color": 0x641E16, "message": "You're a genuine problem! Ino actively avoids you!"},
    {"threshold": -70, "status": "💢 Ino's Nemesis", "relationship": "⚔️ Enemy", "color": 0x4A0E0E, "message": "Ino actively dislikes you! You've crossed too many lines!"},
    {"threshold": -100, "status": "👿 Ino's Antagonist", "relationship": "⚡ Adversary", "color": 0x3D0909, "message": "Terrible! Ino considers you a genuine threat. Why are you so mean?!"},
    {"threshold": -140, "status": "💀 Ino's Arch-Enemy", "relationship": "☠️ Sworn Enemy", "color": 0x2C0505, "message": "Absolutely awful! Ino despises you with a passion!"},
    {"threshold": -200, "status": "🔥 Ino's Tormentor", "relationship": "👹 Demon", "color": 0x1A0000, "message": "You're horrible! Ino wants nothing to do with you. Redemption seems impossible!"},
    {"threshold": -300, "status": "⚰️ Ino's Nightmare", "relationship": "💀 Cursed", "color": 0x0D0000, "message": "Unspeakably bad! Ino has nightmares about you! How do you live with yourself?!"},
    {"threshold": -500, "status": "🗡️ Ino's Bane", "relationship": "⚡ Apocalyptic", "color": 0x080000, "message": "LEGENDARY HATRED! You are Ino's worst nightmare. She wishes you didn't exist!"},
    {"threshold": -750, "status": "👹 Ino's Destroyer", "relationship": "💔 Shattered", "color": 0x050000, "message": "CATASTROPHIC! You've broken her spirit. Ino will never forgive you!"},
    {"threshold": -1000, "status": "☠️ Ino's Plague", "relationship": "🦠 Plague", "color": 0x020000, "message": "DEVASTATING! You are a plague upon Ino's existence. Pure evil incarnate!"},
    {"threshold": -2000, "status": "⚰️ Ino's Eternal Nemesis", "relationship": "🌑 Void", "color": 0x010000, "message": "ABSOLUTE EVIL! You are beyond redemption. Ino's hatred for you transcends all bounds!"},
    {"threshold": -3500, "status": "👁️ Ino's Eldritch Horror", "relationship": "🕳️ Abyss", "color": 0x000000, "message": "INCOMPREHENSIBLE! Your cruelty defies description. Ino cannot fathom your existence."},
    {"threshold": -5000, "status": "🌑 Ino's Shrine Calamity", "relationship": "💥 Calamity", "color": 0x000000, "message": "You are a natural disaster with legs. Ino has written your name in the emergency scrolls."},
    {"threshold": -7000, "status": "🕯️ Ino's Forbidden Omen", "relationship": "🚷 Forbidden", "color": 0x000000, "message": "The shrine lanterns dim when you appear. That is not a compliment."},
    {"threshold": -8500, "status": "🕳️ Ino's Reality Error", "relationship": "❌ Corrupted", "color": 0x000000, "message": "Your InoRep is so bad it has started bending the UI. Impressive. Horrible, but impressive."},
    {"threshold": -10000, "status": "🚨 Ino's Skill Issue Incarnate", "relationship": "💀 Terminal Skill Issue", "color": 0x000000, "message": "Skill issue detected at mythological scale. Ino has stopped sighing and started documenting evidence."},
]


def get_inorep_tier(rep: int, user_id: Optional[int] = None) -> Dict[str, object]:
    if user_id == 1415740507748958328 and rep >= 1000000000:
        return {
            "threshold": 1000000000,
            "status": "Riko Herself",
            "relationship": "Riko",
            "color": 0xFFFFFF,
            "message": "Ofcourse she gets kinda irritated at you, but deep down she appreciates your company.",
        }

    for tier in INOREP_TIERS:
        if rep >= int(tier["threshold"]):
            return tier

    return INOREP_TIERS[-1]


def get_next_inorep_threshold(rep: int) -> Optional[int]:
    thresholds = sorted(int(tier["threshold"]) for tier in INOREP_TIERS)
    for threshold in thresholds:
        if threshold > rep:
            return threshold
    return None


def get_previous_inorep_threshold(rep: int) -> Optional[int]:
    thresholds = sorted(int(tier["threshold"]) for tier in INOREP_TIERS)
    previous = None
    for threshold in thresholds:
        if threshold <= rep:
            previous = threshold
        else:
            break
    return previous
