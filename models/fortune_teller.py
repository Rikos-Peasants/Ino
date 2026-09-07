"""Daily fortunes.

Three properties matter:

* **Stable.** One fortune per person per UTC day. Re-running ``/fortune`` shows
  the same slip, so it cannot be rerolled until it says something flattering.
* **Dynamic.** Ino writes them through the AI router when a provider is up, so
  the pool is not a fixed list people memorise.
* **Always answers.** If every provider is down, a deterministic pick from the
  static pool stands in — chosen by hashing the user and the date, so it is
  stable for the day too.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Written to be readable in any order, and never to promise anything specific
# enough to be wrong.
STATIC_FORTUNES: tuple[str, ...] = (
    "A stranger will misread your tone today. It will be funny.",
    "Something you lost will resurface at the least useful moment.",
    "You will win an argument nobody was having.",
    "Your next idea is better than you think. Your next three are not.",
    "Someone is about to send you a message you will reread four times.",
    "Beware of Tuesdays. No further detail is available.",
    "The shrine foresees snacks. Act accordingly.",
    "You will be right, and nobody will notice. As usual.",
    "An old grudge becomes funny this week.",
    "Today rewards patience. Tomorrow rewards the opposite.",
    "You will open a tab you meant to read and close it three days later.",
    "A small kindness you forgot about is still working on your behalf.",
    "The thing you are avoiding takes eleven minutes.",
    "Someone will quote you back to yourself, badly.",
    "Your bravest act today will be sending the message without editing it.",
    "You will find the bug. It will be a typo. You will be furious.",
    "A song you have not heard since childhood is waiting in a queue somewhere.",
    "Do not trust the first draft. Do not discard it either.",
    "You are one honest sentence away from ending a long misunderstanding.",
    "Something expensive will almost break, and then not.",
    "The group chat is wrong and you are the only one who knows.",
    "You will be offered advice you already gave someone else.",
    "Rest is not a reward for finishing. Take it now.",
    "An old file will contain exactly what you need, and a great deal of shame.",
    "Someone is drafting a compliment about you and will never send it.",
    "The shortcut costs more than the long way. It always did.",
    "You will laugh at something you should not, in a quiet room.",
    "A door you assumed was locked has been open the entire time.",
    "Your instincts are correct today. Your reasoning is not. Follow the instincts.",
    "Somebody remembers a small thing you said and has thought about it for years.",
    "You will nearly send that message. The shrine advises against it. Barely.",
    "The person who annoys you most this week is right about one thing.",
    "You will be interrupted at the exact moment it starts working.",
    "There is a simpler version of your plan. It is one step, not five.",
    "An apology you have been rehearsing is shorter than you think.",
    "Today you will teach someone something without realising it.",
    "The answer is in the thing you already tried, done properly.",
    "You will overprepare for something that is cancelled.",
    "Someone will assume you are confident. Let them.",
    "A stray thought at 2am will turn out to be the good one.",
    "You will meet a deadline by abandoning the part nobody wanted.",
    "The compliment you dismissed was sincere.",
    "Check the thing you are certain about. Only that one.",
    "You will spend an hour on a decision worth four minutes.",
    "Somebody is waiting for you to go first.",
    "The shrine notes you have not had water in some time.",
    "A conversation you dread will last ninety seconds.",
    "You will be the reason someone's day improves, and never find out.",
    "Something is finishing. You have not noticed yet.",
    "Your standards are fine. Your deadline is the problem.",
)

FORTUNE_SYSTEM_PROMPT = """You are Ino, a shrine spirit who writes fortune slips.

Write exactly ONE fortune. Rules:
- One or two sentences, under 25 words.
- Dry, wry, a little uncanny. Observational, never cruel.
- Never mention the person's name, Discord, or that you are an AI.
- No emoji. No quotation marks. No preamble. Output only the fortune itself.
- Do not predict death, illness, money amounts, or anything genuinely alarming.
- It should feel oddly specific but apply to anyone."""

FORTUNE_THEMES = (
    "something small they have been putting off",
    "an old message or file resurfacing",
    "a misunderstanding that resolves itself",
    "being right at an inconvenient moment",
    "a stranger's passing kindness",
    "the gap between a plan and what happens",
    "something they are better at than they think",
    "a habit catching up with them, gently",
    "an unexpected quiet moment",
    "advice they should take from themselves",
    "a thing that is almost finished",
    "being noticed when they did not expect it",
)


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _seed_for(user_id: str, day: str) -> int:
    """Stable integer seed from a user and a date."""
    digest = hashlib.sha256(f"{user_id}:{day}".encode()).hexdigest()
    return int(digest[:16], 16)


def static_fortune_for(user_id: str, day: Optional[str] = None) -> str:
    """Deterministic pick from the static pool for this user on this day."""
    day = day or _today_key()
    index = _seed_for(user_id, day) % len(STATIC_FORTUNES)
    return STATIC_FORTUNES[index]


class FortuneTeller:
    """Serves one fortune per user per day, generated when possible."""

    def __init__(self, db: Any = None, ai_router: Any = None):
        self.collection = db["daily_fortunes"] if db is not None else None
        self.ai_router = ai_router

        if self.collection is not None:
            try:
                self.collection.create_index([("user_id", 1), ("day", 1)], unique=True)
                # Fortunes are worthless the day after; let Mongo reap them.
                self.collection.create_index("created_at", expireAfterSeconds=60 * 60 * 24 * 3)
            except Exception as exc:
                logger.error("Could not create daily_fortunes indexes: %s", exc)

    # ------------------------------------------------------------------

    async def get_fortune(self, user_id: str, display_name: str = "") -> dict[str, Any]:
        """Return ``{"text": str, "source": "ai"|"shrine", "fresh": bool}``."""
        day = _today_key()
        user_id = str(user_id)

        cached = await self._load(user_id, day)
        if cached:
            return {"text": cached["text"], "source": cached.get("source", "shrine"), "fresh": False}

        text, source = await self._generate(user_id, day)
        await self._store(user_id, day, text, source)
        return {"text": text, "source": source, "fresh": True}

    # ------------------------------------------------------------------

    async def _generate(self, user_id: str, day: str) -> tuple[str, str]:
        """Ask the router for a fortune, falling back to the static pool."""
        if self.ai_router is not None and self.ai_router.available:
            # Seeded so the prompt is stable for this user-day: if the AI call
            # fails and is retried later the same theme comes back, rather than
            # the fortune quietly changing character mid-day.
            rng = random.Random(_seed_for(user_id, day))
            theme = rng.choice(FORTUNE_THEMES)

            try:
                result = await self.ai_router.generate(
                    f"Write today's fortune. Theme to riff on: {theme}.",
                    system_prompt=FORTUNE_SYSTEM_PROMPT,
                    # Generous for a 25-word answer. Providers bill any thinking
                    # against this budget, and a tight cap was cutting fortunes
                    # off mid-sentence.
                    max_tokens=200,
                    temperature=1.0,
                )
                cleaned = self._clean(result.text)
                if cleaned:
                    return cleaned, "ai"
                logger.info("Fortune generation returned nothing usable; using the static pool")
            except Exception as exc:
                logger.warning("Fortune generation failed: %s", exc)

        return static_fortune_for(user_id, day), "shrine"

    @staticmethod
    def _clean(text: str) -> Optional[str]:
        """Strip the wrappers models like to add, and sanity-check the result."""
        if not text:
            return None

        cleaned = text.strip()
        # Models often answer with a quoted line, or a "Fortune:" label.
        for prefix in ("fortune:", "your fortune:", "today's fortune:"):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
        cleaned = cleaned.strip('"').strip("'").strip()
        # Only ever one line on a slip.
        cleaned = cleaned.split("\n")[0].strip()

        # A refusal or a rambling answer is worse than the static pool.
        if not 15 <= len(cleaned) <= 240:
            return None

        # A fortune cut off mid-sentence is the worst possible output, and it
        # happens whenever a provider spends the token budget thinking. Every
        # real fortune ends a sentence, so anything that does not is a truncation.
        if not cleaned.endswith((".", "!", "?", "…")):
            logger.info("Discarding truncated fortune: %r", cleaned)
            return None

        return cleaned

    # ------------------------------------------------------------------

    async def _load(self, user_id: str, day: str) -> Optional[dict[str, Any]]:
        if self.collection is None:
            return None
        try:
            return await asyncio.to_thread(
                self.collection.find_one, {"user_id": user_id, "day": day}
            )
        except Exception as exc:
            logger.error("Could not read fortune for %s: %s", user_id, exc)
            return None

    async def _store(self, user_id: str, day: str, text: str, source: str) -> None:
        if self.collection is None:
            return
        try:
            await asyncio.to_thread(
                self.collection.update_one,
                {"user_id": user_id, "day": day},
                {
                    "$set": {
                        "user_id": user_id,
                        "day": day,
                        "text": text,
                        "source": source,
                    },
                    "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
                },
                True,  # upsert
            )
        except Exception as exc:
            # Losing the write only means the fortune may change on a retry.
            logger.error("Could not persist fortune for %s: %s", user_id, exc)
