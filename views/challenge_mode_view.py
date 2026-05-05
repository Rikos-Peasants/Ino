import discord
from discord.ui import View, Button
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from models.challenge_mode_manager import ChallengeModeManager

logger = logging.getLogger(__name__)


class ChallengeModeEmbed:
    @staticmethod
    def create_challenge_embed(challenge_data: dict) -> discord.Embed:
        embed = discord.Embed(
            title="⚔️ 1v1 Art Duel!",
            description=f"<@{challenge_data['challenger_id']}> has challenged <@{challenge_data['opponent_id']}> to an art duel!",
            color=discord.Color.from_rgb(255, 69, 0)
        )
        embed.add_field(name="💰 Wager", value=f"**{challenge_data['wager']}** points", inline=True)
        theme = challenge_data.get("challenge_theme")
        if theme:
            embed.add_field(name="🎯 Theme", value=theme, inline=True)
        deadline = challenge_data.get("submission_deadline")
        if deadline:
            embed.add_field(name="⏰ Submit By", value=f"<t:{int(deadline.timestamp())}:R>", inline=True)
        else:
            embed.add_field(name="⏰ Status", value="Waiting for opponent to accept...", inline=False)
        embed.set_footer(text="Opponent: Click Accept or Decline below")
        embed.timestamp = datetime.utcnow()
        return embed

    @staticmethod
    def create_voting_embed(challenge_data: dict) -> discord.Embed:
        cv = challenge_data.get("challenger_votes", 0)
        ov = challenge_data.get("opponent_votes", 0)
        embed = discord.Embed(
            title="⚔️ Art Duel - VOTE NOW!",
            description=f"**<@{challenge_data['challenger_id']}>** VS **<@{challenge_data['opponent_id']}>**\n\nVote for the best artwork!",
            color=discord.Color.gold()
        )
        embed.add_field(name="🟢 Challenger", value=f"<@{challenge_data['challenger_id']}> - **{cv}** votes", inline=True)
        embed.add_field(name="🔵 Opponent", value=f"<@{challenge_data['opponent_id']}> - **{ov}** votes", inline=True)
        embed.add_field(name="💰 Wager", value=f"**{challenge_data['wager']}** pts", inline=True)
        ends_at = challenge_data.get("voting_ends_at")
        if ends_at:
            embed.add_field(name="⏰ Voting Ends", value=f"<t:{int(ends_at.timestamp())}:R>", inline=False)
        fishy = challenge_data.get("fishy_required_item")
        if fishy:
            embed.add_field(name="🐟 Fishy Requirement!", value=f"Both must include: **{fishy}**", inline=False)
        embed.set_footer(text="Vote by clicking below!")
        embed.timestamp = datetime.utcnow()
        return embed

    @staticmethod
    def create_result_embed(challenge_data: dict) -> discord.Embed:
        winner_id = challenge_data.get("winner_id")
        wager = challenge_data.get("wager", 0)
        if winner_id:
            embed = discord.Embed(
                title="🏆 Duel Complete!",
                description=f"**<@{winner_id}>** wins the duel and earns **{wager * 2}** points!",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="🤝 Duel Complete - Draw!",
                description=f"It's a tie! Both players get their **{wager}** points back.",
                color=discord.Color.blue()
            )
        embed.add_field(name="🟢 Challenger", value=f"<@{challenge_data['challenger_id']}> - {challenge_data.get('final_challenger_votes', 0)} votes", inline=True)
        embed.add_field(name="🔵 Opponent", value=f"<@{challenge_data['opponent_id']}> - {challenge_data.get('final_opponent_votes', 0)} votes", inline=True)
        embed.timestamp = datetime.utcnow()
        return embed


class ChallengeAcceptView(View):
    def __init__(self, challenge_id: str, challenge_manager: 'ChallengeModeManager'):
        super().__init__(timeout=None)
        self.challenge_id = challenge_id
        self.challenge_manager = challenge_manager

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅", custom_id="challenge:accept")
    async def accept(self, interaction: discord.Interaction, button: Button):
        challenge = self.challenge_manager.get_challenge(self.challenge_id)
        if not challenge or challenge.get("state") != "pending":
            await interaction.response.send_message("❌ This challenge is no longer available.", ephemeral=True)
            return
        if interaction.user.id != challenge.get("opponent_id"):
            await interaction.response.send_message("❌ Only the challenged opponent can accept.", ephemeral=True)
            return

        updated = self.challenge_manager.accept_challenge(self.challenge_id, interaction.user.id)
        if updated:
            theme = updated.get("challenge_theme", "Free theme")
            deadline = updated.get("submission_deadline")
            deadline_str = f"<t:{int(deadline.timestamp())}:R>" if deadline else "4 hours"
            await interaction.response.send_message(
                f"✅ **Challenge accepted!**\n"
                f"🎯 **Theme: {theme}**\n"
                f"📸 Both players: reply to your artwork image with `!duelsubmit` to submit!\n"
                f"⏰ Deadline: {deadline_str}", ephemeral=False)
        else:
            await interaction.response.send_message("❌ Failed to accept challenge.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="❌", custom_id="challenge:decline")
    async def decline(self, interaction: discord.Interaction, button: Button):
        challenge = self.challenge_manager.get_challenge(self.challenge_id)
        if not challenge or challenge.get("state") != "pending":
            await interaction.response.send_message("❌ This challenge is no longer available.", ephemeral=True)
            return
        if interaction.user.id != challenge.get("opponent_id"):
            await interaction.response.send_message("❌ Only the challenged opponent can decline.", ephemeral=True)
            return

        self.challenge_manager.decline_challenge(self.challenge_id, interaction.user.id)
        await interaction.response.send_message("❌ Challenge declined.", ephemeral=False)


class ChallengeVoteView(View):
    def __init__(self, challenge_id: str, challenge_manager: 'ChallengeModeManager'):
        super().__init__(timeout=None)
        self.challenge_id = challenge_id
        self.challenge_manager = challenge_manager

    @discord.ui.button(label="Vote Challenger", style=discord.ButtonStyle.primary, emoji="🟢", custom_id="challenge:vote_challenger")
    async def vote_challenger(self, interaction: discord.Interaction, button: Button):
        result = self.challenge_manager.record_vote(self.challenge_id, interaction.user.id, "challenger")
        if result.get("success"):
            await interaction.response.send_message("✅ Vote recorded for Challenger!", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {result.get('error')}", ephemeral=True)

    @discord.ui.button(label="Vote Opponent", style=discord.ButtonStyle.primary, emoji="🔵", custom_id="challenge:vote_opponent")
    async def vote_opponent(self, interaction: discord.Interaction, button: Button):
        result = self.challenge_manager.record_vote(self.challenge_id, interaction.user.id, "opponent")
        if result.get("success"):
            await interaction.response.send_message("✅ Vote recorded for Opponent!", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {result.get('error')}", ephemeral=True)
