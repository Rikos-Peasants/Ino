"""Light-hearted commands, written in Ino's voice.

A few of these animate by editing the reply a couple of times before settling on
the result. Animation is deliberately capped at three edits with ~0.7s between
them: enough to feel alive, short enough that Discord's rate limiter never
becomes the bottleneck.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
import random
from typing import Optional

import discord
from discord.ext import commands

from controllers.security import public_command
from models.fortune_teller import static_fortune_for

logger = logging.getLogger(__name__)

ACCENT = 0xF2A65A
ANIM_STEP_SECONDS = 0.7

EIGHTBALL_ANSWERS = [
    ("Without a doubt.", 0x77DD77),
    ("The shrine says yes.", 0x77DD77),
    ("Obviously. Were you not paying attention?", 0x77DD77),
    ("The signs are favourable.", 0x77DD77),
    ("Probably. Do not quote me.", 0xE8A33D),
    ("Ask again when I care more.", 0xE8A33D),
    ("The spirits are arguing about it.", 0xE8A33D),
    ("That is genuinely none of my business.", 0xE8A33D),
    ("Absolutely not.", 0xE05252),
    ("No. And stop asking.", 0xE05252),
    ("The omens are dreadful.", 0xE05252),
    ("Not in this timeline.", 0xE05252),
]

VIBES = [
    (95, "immaculate", "🌸", "The shrine bows slightly. This is rare."),
    (80, "radiant", "✨", "Ino approves, and she does not approve easily."),
    (65, "solid", "🍡", "Nothing to fix here. Carry on."),
    (50, "acceptable", "⛩️", "Perfectly ordinary. There is no shame in it."),
    (35, "wobbly", "🍂", "Drink some water. Genuinely."),
    (20, "concerning", "🌀", "Something is off. You know what it is."),
    (0, "cursed", "🕯️", "Ino has lit a candle for you. That is all she can do."),
]

RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
RPS_EMOJI = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}

WOULD_YOU_RATHER = [
    ("always speak in rhyme", "never be able to use the letter E"),
    ("have every song stuck in your head for a week", "hear no music for a year"),
    ("be famous for something embarrassing", "be forgotten entirely"),
    ("know when you will die", "know how"),
    ("fight one horse-sized duck", "one hundred duck-sized horses"),
    ("have unlimited money but no friends", "great friends and constant rent anxiety"),
    ("read minds but never turn it off", "be invisible but never seen again"),
    ("live in permanent summer", "permanent autumn"),
]


def _stable_percent(*parts: str) -> int:
    """Deterministic 0-100 from the inputs, so the same query always agrees."""
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:8], 16) % 101


def _bar(percent: int, width: int = 14) -> str:
    filled = round(percent / 100 * width)
    return "█" * filled + "░" * (width - filled)


class FunCommandsController:
    """Registers the fun commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _animate(self, ctx, frames: list[discord.Embed]) -> discord.Message:
        """Send the first frame, then edit through the rest."""
        message = await ctx.send(embed=frames[0])
        # ctx.send returns None for some interaction paths; recover the message.
        if message is None:
            try:
                message = await ctx.original_response()
            except Exception:
                return None

        for frame in frames[1:]:
            await asyncio.sleep(ANIM_STEP_SECONDS)
            try:
                await message.edit(embed=frame)
            except discord.HTTPException as exc:
                logger.debug("Animation frame dropped: %s", exc)
                break
        return message

    def register_commands(self):
        """Attach all fun commands to the bot."""

        @self.bot.hybrid_command(name="8ball", description="Ask Ino a yes/no question")
        @public_command
        async def eightball_command(ctx, *, question: str):
            answer, color = random.choice(EIGHTBALL_ANSWERS)

            thinking = discord.Embed(
                title="🎱 Consulting the shrine…",
                description=f"> {question[:200]}",
                color=0x4A4A5A,
            )
            settled = discord.Embed(
                title="🎱 The shrine has spoken",
                description=f"> {question[:200]}\n\n**{answer}**",
                color=color,
            )
            settled.set_footer(text=f"Asked by {ctx.author.display_name}")
            await self._animate(ctx, [thinking, settled])

        @self.bot.hybrid_command(name="roll", description="Roll dice, e.g. 2d20 or just 20")
        @public_command
        async def roll_command(ctx, dice: str = "1d20"):
            spec = dice.lower().strip().replace(" ", "")
            if spec.isdigit():
                spec = f"1d{spec}"

            try:
                count_raw, _, sides_raw = spec.partition("d")
                count = int(count_raw or 1)
                sides = int(sides_raw)
            except ValueError:
                await ctx.send(
                    "❌ I need something like `2d20`, `d6`, or just `20`.", ephemeral=True
                )
                return

            if not (1 <= count <= 25) or not (2 <= sides <= 1000):
                await ctx.send(
                    "❌ Between 1 and 25 dice, with 2 to 1000 sides. Be reasonable.",
                    ephemeral=True,
                )
                return

            rolls = [random.randint(1, sides) for _ in range(count)]
            total = sum(rolls)

            embed = discord.Embed(title=f"🎲 {count}d{sides}", color=ACCENT)
            if count > 1:
                embed.description = (
                    f"`{'` `'.join(str(r) for r in rolls)}`\n\n**Total: {total}**"
                )
            else:
                embed.description = f"# {total}"

            # Nat 20s and nat 1s deserve acknowledgement.
            if sides == 20 and count == 1:
                if total == 20:
                    embed.set_footer(text="Natural 20. Do not let it go to your head.")
                    embed.color = 0x77DD77
                elif total == 1:
                    embed.set_footer(text="Natural 1. The shrine looks away politely.")
                    embed.color = 0xE05252

            await ctx.send(embed=embed)

        @self.bot.hybrid_command(name="coinflip", description="Flip a coin")
        @public_command
        async def coinflip_command(ctx):
            result = random.choice(("Heads", "Tails"))
            frames = [
                discord.Embed(title="🪙 Flipping…", color=0x4A4A5A),
                discord.Embed(title="🪙 …spinning…", color=0x6A6A7A),
                discord.Embed(
                    title=f"🪙 {result}",
                    color=ACCENT,
                ),
            ]
            frames[-1].set_footer(text=f"Flipped by {ctx.author.display_name}")
            await self._animate(ctx, frames)

        @self.bot.hybrid_command(
            name="ship", description="Measure the compatibility of two members"
        )
        @public_command
        async def ship_command(ctx, first: discord.Member, second: Optional[discord.Member] = None):
            left, right = (ctx.author, first) if second is None else (first, second)

            if left.id == right.id:
                await ctx.send(
                    "❌ Self-love is important, but that is not what this is for.",
                    ephemeral=True,
                )
                return

            # Order-independent so /ship a b and /ship b a agree.
            key = sorted([str(left.id), str(right.id)])
            percent = _stable_percent(*key)

            name = left.display_name[: len(left.display_name) // 2] + right.display_name[len(right.display_name) // 2 :]

            if percent >= 90:
                verdict, emoji = "The shrine is already planning the ceremony.", "💞"
            elif percent >= 70:
                verdict, emoji = "There is something here. Obviously.", "💗"
            elif percent >= 50:
                verdict, emoji = "Promising, with effort.", "💛"
            elif percent >= 30:
                verdict, emoji = "Friends. Firmly friends.", "🤝"
            else:
                verdict, emoji = "Ino advises against this.", "💔"

            frames = [
                discord.Embed(
                    title="💘 Consulting the red thread…",
                    description=f"**{left.display_name}** × **{right.display_name}**",
                    color=0x4A4A5A,
                ),
                discord.Embed(
                    title=f"{emoji} {percent}%",
                    description=(
                        f"**{left.display_name}** × **{right.display_name}**\n"
                        f"Ship name: **{name}**\n\n"
                        f"`{_bar(percent)}`\n\n{verdict}"
                    ),
                    color=ACCENT,
                ),
            ]
            await self._animate(ctx, frames)

        @self.bot.hybrid_command(name="vibecheck", description="Submit to a vibe check")
        @public_command
        async def vibecheck_command(ctx, user: Optional[discord.Member] = None):
            target = user or ctx.author
            # Stable per person per day, so it cannot be rerolled.
            today = datetime.date.today().isoformat()
            percent = _stable_percent(str(target.id), today)

            for threshold, label, emoji, note in VIBES:
                if percent >= threshold:
                    break

            embed = discord.Embed(
                title=f"{emoji} Vibes: {label}",
                description=f"`{_bar(percent)}` **{percent}%**\n\n{note}",
                color=ACCENT,
            )
            embed.set_author(
                name=target.display_name, icon_url=target.display_avatar.url
            )
            embed.set_footer(text="Rechecked at midnight. No rerolls.")
            await ctx.send(embed=embed)

        @self.bot.hybrid_command(name="fortune", description="Receive today's fortune from the shrine")
        @public_command
        async def fortune_command(ctx):
            await ctx.defer()

            teller = getattr(self.bot, "fortune_teller", None)
            if teller is None:
                # No database or router wired up; still answer, deterministically.
                text = static_fortune_for(str(ctx.author.id))
                source, fresh = "shrine", True
            else:
                result = await teller.get_fortune(ctx.author.id, ctx.author.display_name)
                text, source, fresh = result["text"], result["source"], result["fresh"]

            embed = discord.Embed(
                title="🏮 Your fortune",
                description=f"*{text}*",
                color=ACCENT,
            )
            embed.set_author(
                name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url
            )
            # Say plainly that it is fixed, so nobody re-runs it hoping for better.
            embed.set_footer(
                text=(
                    "Drawn just now · one slip per day"
                    if fresh
                    else "Today's slip · a new one is drawn at midnight UTC"
                )
            )
            await ctx.send(embed=embed)

        @self.bot.hybrid_command(name="choose", description="Let Ino pick between options")
        @public_command
        async def choose_command(ctx, *, options: str):
            # Comma-separated, falling back to whitespace for single words.
            choices = [part.strip() for part in options.split(",") if part.strip()]
            if len(choices) < 2:
                choices = [part for part in options.split() if part]

            if len(choices) < 2:
                await ctx.send(
                    "❌ Give me at least two options, separated by commas.", ephemeral=True
                )
                return
            if len(choices) > 20:
                await ctx.send("❌ Twenty options is already too many.", ephemeral=True)
                return

            pick = random.choice(choices)
            frames = [
                discord.Embed(
                    title="🤔 Weighing your options…",
                    description="\n".join(f"• {c[:80]}" for c in choices[:10]),
                    color=0x4A4A5A,
                ),
                discord.Embed(
                    title="⛩️ Ino chooses",
                    description=f"# {pick[:200]}",
                    color=ACCENT,
                ),
            ]
            frames[-1].set_footer(text=f"…out of {len(choices)} options")
            await self._animate(ctx, frames)

        @self.bot.hybrid_command(name="rps", description="Rock, paper, scissors against Ino")
        @public_command
        async def rps_command(ctx, choice: str):
            player = choice.lower().strip()
            if player not in RPS_BEATS:
                await ctx.send(
                    "❌ Pick `rock`, `paper`, or `scissors`.", ephemeral=True
                )
                return

            ino = random.choice(list(RPS_BEATS))
            if player == ino:
                outcome, color = "A draw. How unsatisfying.", 0xE8A33D
            elif RPS_BEATS[player] == ino:
                outcome, color = "You win. Enjoy it.", 0x77DD77
            else:
                outcome, color = "Ino wins. Naturally.", 0xE05252

            frames = [
                discord.Embed(title="✊ Rock… paper…", color=0x4A4A5A),
                discord.Embed(
                    title=f"{RPS_EMOJI[player]} vs {RPS_EMOJI[ino]}",
                    description=(
                        f"You played **{player}**, Ino played **{ino}**.\n\n**{outcome}**"
                    ),
                    color=color,
                ),
            ]
            await self._animate(ctx, frames)

        @self.bot.hybrid_command(
            name="wouldyourather", description="A dilemma, with live voting"
        )
        @public_command
        async def wyr_command(ctx):
            left, right = random.choice(WOULD_YOU_RATHER)
            embed = discord.Embed(
                title="🤷 Would you rather…",
                description=f"🅰️ {left}\n\n**or**\n\n🅱️ {right}",
                color=ACCENT,
            )
            embed.set_footer(text="React to vote.")
            message = await ctx.send(embed=embed)
            if message is None:
                try:
                    message = await ctx.original_response()
                except Exception:
                    return
            for emoji in ("🅰️", "🅱️"):
                try:
                    await message.add_reaction(emoji)
                except discord.HTTPException:
                    break

        @self.bot.hybrid_command(name="avatar", description="Show a member's avatar in full size")
        @public_command
        async def avatar_command(ctx, user: Optional[discord.Member] = None):
            target = user or ctx.author
            embed = discord.Embed(title=f"{target.display_name}", color=ACCENT)
            embed.set_image(url=target.display_avatar.url)
            embed.description = f"[Open original]({target.display_avatar.url})"
            await ctx.send(embed=embed)

        logger.info("✅ Fun commands registered")
