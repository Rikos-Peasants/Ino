"""Member-facing InoRep commands: /rep, /daily, /thank, /repways.

These are the earning side of the rep system. Moderator-facing rep commands
(granting, removing, mod mode) stay in :mod:`controllers.commands`.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord.ext import commands

from config import Config
from controllers.security import public_command
from models.inorep_status import INOREP_TIERS
from models.rep_economy import tier_label

logger = logging.getLogger(__name__)

ACCENT = 0xF2A65A
SUCCESS = 0x77DD77
WARNING = 0xE8A33D


class RepCommandsController:
    """Registers the commands members use to check and earn rep."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _economy(self):
        return getattr(self.bot, "rep_economy", None)

    async def _reject(self, ctx, message: str) -> None:
        await ctx.send(
            embed=discord.Embed(description=f"❌ {message}", color=0xE05252),
            ephemeral=True,
        )

    def register_commands(self):
        """Attach the rep commands to the bot."""

        @self.bot.hybrid_command(
            name="rep", description="See your InoRep, rank and how close you are to the next tier"
        )
        @public_command
        async def rep_command(ctx, user: Optional[discord.Member] = None):
            economy = self._economy()
            if not economy:
                await self._reject(ctx, "The InoRep system is not available right now.")
                return

            target = user or ctx.author
            if target.bot:
                await self._reject(ctx, "Bots have no reputation to speak of.")
                return

            await ctx.defer()
            profile = await economy.get_profile(target, str(ctx.guild.id))

            tier = profile["tier"]
            embed = discord.Embed(
                title=tier_label(tier),
                # The ladder carries its own colour per tier; use it so /rep
                # looks the same as /inorep check and the profile embeds.
                color=int(tier.get("color", ACCENT)),
            )
            embed.set_author(
                name=target.display_name,
                icon_url=target.display_avatar.url,
            )
            embed.add_field(name="InoRep", value=f"**{profile['rep']:,}**", inline=True)
            embed.add_field(
                name="Rank",
                value=f"#{profile['rank']}" if profile["rank"] else "—",
                inline=True,
            )
            embed.add_field(
                name="Daily streak",
                value=f"🔥 {profile['streak']} day{'s' if profile['streak'] != 1 else ''}",
                inline=True,
            )

            next_tier = profile["next_tier"]
            if next_tier:
                embed.add_field(
                    name=f"Progress to {tier_label(next_tier)}",
                    value=f"`{profile['bar']}` **{profile['to_next']:,}** to go",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Progress",
                    value=f"`{profile['bar']}` Highest tier reached. Ino is impressed.",
                    inline=False,
                )

            hints = []
            if profile["daily_ready"]:
                hints.append("`/daily` is ready to claim")
            if profile["thanks_left"]:
                hints.append(f"{profile['thanks_left']} `/thank` left today")
            if hints:
                embed.set_footer(text=" • ".join(hints))

            await ctx.send(embed=embed)

        @self.bot.hybrid_command(
            name="daily", description="Claim your daily InoRep bonus and build a streak"
        )
        @public_command
        async def daily_command(ctx):
            economy = self._economy()
            if not economy:
                await self._reject(ctx, "The InoRep system is not available right now.")
                return

            await ctx.defer()
            result = await economy.claim_daily(ctx.author, str(ctx.guild.id))

            if not result["claimed"]:
                timestamp = int(result["next_available"].timestamp())
                embed = discord.Embed(
                    title="🌙 Already claimed",
                    description=(
                        f"You have taken today's offering. Come back <t:{timestamp}:R>.\n\n"
                        f"Current streak: 🔥 **{result['streak']}**"
                    ),
                    color=WARNING,
                )
                await ctx.send(embed=embed, ephemeral=True)
                return

            streak = result["streak"]
            bonus = result.get("bonus", 0)
            description = f"**+{result['amount']} InoRep**\n"
            if bonus:
                description += f"`{Config.REP_DAILY_BASE} base + {bonus} streak bonus`\n"
            description += f"\n🔥 **{streak} day streak** • Total: **{result['total']:,}**"

            embed = discord.Embed(
                title="⛩️ Daily offering accepted",
                description=description,
                color=SUCCESS,
            )

            # Show how the streak bonus is growing, until it caps out.
            if bonus < Config.REP_DAILY_STREAK_BONUS_CAP:
                next_bonus = min(
                    Config.REP_DAILY_STREAK_BONUS * streak,
                    Config.REP_DAILY_STREAK_BONUS_CAP,
                )
                embed.set_footer(
                    text=f"Come back tomorrow for +{Config.REP_DAILY_BASE + next_bonus}"
                )
            else:
                embed.set_footer(text="Your streak bonus is maxed out. Keep it alive!")

            award = result.get("award")
            if award and award.tier_changed:
                embed.add_field(
                    name="Rank up!",
                    value=f"You are now **{tier_label(award.tier)}**",
                    inline=False,
                )

            await ctx.send(embed=embed)

        @self.bot.hybrid_command(
            name="thank", description="Give another member InoRep for being helpful"
        )
        @public_command
        async def thank_command(ctx, user: discord.Member, note: Optional[str] = None):
            economy = self._economy()
            if not economy:
                await self._reject(ctx, "The InoRep system is not available right now.")
                return

            await ctx.defer()
            result = await economy.thank(ctx.author, user, str(ctx.guild.id), note)

            if not result["ok"]:
                await self._reject(ctx, result["error"])
                return

            award = result["award"]
            embed = discord.Embed(
                title="🍡 Gratitude offered",
                description=(
                    f"{ctx.author.mention} thanked {user.mention} "
                    f"— **+{award.granted} InoRep**"
                ),
                color=SUCCESS,
            )
            if note:
                embed.add_field(name="For", value=note[:200], inline=False)
            embed.add_field(
                name="Their total", value=f"{award.new_total:,}", inline=True
            )
            embed.set_footer(text=f"{result['remaining']} thanks left today")

            if award.tier_changed:
                embed.add_field(
                    name="Rank up!",
                    value=f"{user.display_name} is now **{tier_label(award.tier)}**",
                    inline=False,
                )

            await ctx.send(embed=embed)

        @self.bot.hybrid_command(
            name="repways", description="See every way to earn InoRep"
        )
        @public_command
        async def repways_command(ctx):
            embed = discord.Embed(
                title="⛩️ How to earn InoRep",
                description="Rep is earned by being present and pleasant. Here is the full list.",
                color=ACCENT,
            )
            embed.add_field(
                name="💬 Chatting",
                value=(
                    f"**+{Config.REP_PER_MESSAGE}** per message "
                    f"(**+{Config.REP_PER_MESSAGE * 2}** in booster channels)\n"
                    f"once every {Config.REP_MESSAGE_COOLDOWN_SECONDS}s, "
                    f"up to {Config.REP_DAILY_MESSAGE_CAP}/day"
                ),
                inline=False,
            )
            embed.add_field(
                name="⛩️ Daily check-in — `/daily`",
                value=(
                    f"**+{Config.REP_DAILY_BASE}** base, plus "
                    f"**+{Config.REP_DAILY_STREAK_BONUS}** per streak day "
                    f"(up to +{Config.REP_DAILY_STREAK_BONUS_CAP})"
                ),
                inline=False,
            )
            embed.add_field(
                name="🍡 Being thanked — `/thank`",
                value=(
                    f"**+{Config.REP_THANK_AMOUNT}** each. You can give "
                    f"{Config.REP_THANK_DAILY_LIMIT} per day, and it costs you nothing."
                ),
                inline=False,
            )
            embed.add_field(
                name="⭐ Getting reactions",
                value=(
                    f"**+{Config.REP_PER_REACTION_RECEIVED}** when someone reacts to your "
                    f"post, up to {Config.REP_REACTION_DAILY_CAP}/day"
                ),
                inline=False,
            )
            embed.add_field(
                name="🎙️ Voice chat",
                value=(
                    f"**+{Config.REP_PER_VOICE_INTERVAL}** per "
                    f"{Config.REP_VOICE_INTERVAL_MINUTES} minutes in voice"
                ),
                inline=False,
            )
            embed.add_field(
                name="🎨 Activities",
                value=(
                    f"**+{Config.REP_IMAGE_POST_BONUS}** per image posted\n"
                    f"**+{Config.REP_QUEST_COMPLETE_BONUS}** per quest completed\n"
                    f"**+{Config.REP_ART_CHALLENGE_BONUS}** per art challenge completed"
                ),
                inline=False,
            )

            embed.add_field(
                name="🏅 Ranks",
                value=(
                    "Your standing with Ino runs from "
                    f"**{tier_label(INOREP_TIERS[-1])}** all the way up to "
                    f"**{tier_label(INOREP_TIERS[0])}**.\n"
                    "Run `/inorep statuses` for the full ladder, or `/rep` for yours."
                ),
                inline=False,
            )

            if Config.PATREON_ROLE_ID:
                embed.set_footer(
                    text=f"Patreon supporters earn {Config.REP_PATREON_MULTIPLIER}x rep."
                )
            await ctx.send(embed=embed)

        logger.info("✅ Rep commands registered")
