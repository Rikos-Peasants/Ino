import discord
from discord.ui import View, Button, Modal, TextInput
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING
import logging
import asyncio

if TYPE_CHECKING:
    from models.art_challenge_manager import ArtChallengeManager

logger = logging.getLogger(__name__)


class ArtChallengeEmbed:
    """Creates embeds for art challenges"""
    
    @staticmethod
    def create_challenge_embed(challenge_data: dict) -> discord.Embed:
        """Create an embed for an art challenge announcement"""
        challenge_type = challenge_data.get("challenge_type")
        end_time = challenge_data.get("end_time")
        
        # Calculate time remaining
        if isinstance(end_time, datetime):
            time_remaining = end_time - datetime.utcnow()
            minutes_remaining = max(0, int(time_remaining.total_seconds() / 60))
        else:
            minutes_remaining = 60
        
        if challenge_type == "remake":
            embed = discord.Embed(
                title=challenge_data.get("challenge_title", "🎨 Remake This Image!"),
                description=challenge_data.get("challenge_description", "Create your own artistic interpretation!"),
                color=discord.Color.from_rgb(255, 136, 0)  # Orange
            )
            
            # Set the reference image
            reference_url = challenge_data.get("reference_image_url")
            if reference_url:
                embed.set_image(url=reference_url)
            
            # Add tags from the reference image
            ref_tags = challenge_data.get("reference_tags", [])
            if ref_tags:
                embed.add_field(
                    name="📌 Reference Tags",
                    value=", ".join(ref_tags[:10]) if ref_tags else "No tags",
                    inline=False
                )
        else:
            # Tag-based challenge
            required_tags = challenge_data.get("required_tags", [])
            
            embed = discord.Embed(
                title=challenge_data.get("challenge_title", "🏷️ Tag Challenge!"),
                description=challenge_data.get("challenge_description", f"Create an image with these tags!"),
                color=discord.Color.from_rgb(138, 43, 226)  # Purple
            )
            
            embed.add_field(
                name="🎯 Required Elements",
                value="\n".join([f"• **{tag}**" for tag in required_tags]),
                inline=False
            )
        
        # Common fields
        embed.add_field(
            name="⏰ Time Remaining",
            value=f"**{minutes_remaining}** minutes",
            inline=True
        )
        
        embed.add_field(
            name="🏆 Reward",
            value=f"**{challenge_data.get('reward_points', 50)}** points",
            inline=True
        )
        
        embed.add_field(
            name="📤 How to Submit",
            value="Post your artwork in this channel and click the **Submit** button below!",
            inline=False
        )
        
        embed.set_footer(text="🤖 AI-verified submissions | Good luck, artists!")
        embed.timestamp = datetime.utcnow()
        
        return embed
    
    @staticmethod
    def create_submission_result_embed(result: dict, user: discord.Member) -> discord.Embed:
        """Create an embed showing the submission verification result"""
        verified = result.get("verified", False)
        verification = result.get("verification_result", {})
        points = result.get("points_awarded", 0)
        
        if verified:
            embed = discord.Embed(
                title="✅ Submission Verified!",
                description=f"Congratulations {user.mention}! Your artwork passed verification!",
                color=discord.Color.green()
            )
            embed.add_field(
                name="🏆 Points Earned",
                value=f"**+{points}** points",
                inline=True
            )
        else:
            embed = discord.Embed(
                title="❌ Verification Failed",
                description=f"Sorry {user.mention}, your submission didn't meet the challenge requirements.",
                color=discord.Color.red()
            )
        
        # Add confidence score
        confidence = verification.get("confidence", 0)
        embed.add_field(
            name="🎯 Confidence",
            value=f"{confidence:.0%}",
            inline=True
        )
        
        # Add reasoning
        reasoning = verification.get("reasoning", "No details available")
        if len(reasoning) > 500:
            reasoning = reasoning[:497] + "..."
        embed.add_field(
            name="📝 AI Analysis",
            value=reasoning,
            inline=False
        )
        
        # Add matched elements
        matched = verification.get("matched_elements", [])
        if matched:
            embed.add_field(
                name="✓ Matched Elements",
                value=", ".join(matched[:10]),
                inline=False
            )
        
        # Add missing elements
        missing = verification.get("missing_elements", [])
        if missing:
            embed.add_field(
                name="✗ Missing Elements",
                value=", ".join(missing[:10]),
                inline=False
            )
        
        # Quality notes
        quality = verification.get("quality_notes", "")
        if quality:
            embed.add_field(
                name="🎨 Quality Notes",
                value=quality,
                inline=False
            )
        
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        embed.timestamp = datetime.utcnow()
        
        return embed
    
    @staticmethod
    def create_challenge_ended_embed(challenge_data: dict, submissions: list) -> discord.Embed:
        """Create an embed for when a challenge ends"""
        challenge_type = challenge_data.get("challenge_type")
        verified_count = len([s for s in submissions if s.get("verified")])
        total_count = len(submissions)
        
        embed = discord.Embed(
            title="🏁 Challenge Ended!",
            description=f"The art challenge has concluded!",
            color=discord.Color.gold()
        )
        
        if challenge_type == "remake":
            embed.add_field(
                name="📸 Challenge Type",
                value="Remake Challenge",
                inline=True
            )
        else:
            tags = challenge_data.get("required_tags", [])
            embed.add_field(
                name="🏷️ Challenge Type",
                value=f"Tags: {', '.join(tags)}",
                inline=True
            )
        
        embed.add_field(
            name="📊 Submissions",
            value=f"**{total_count}** total",
            inline=True
        )
        
        embed.add_field(
            name="✅ Verified",
            value=f"**{verified_count}** passed",
            inline=True
        )
        
        # Add winners if any
        if verified_count > 0:
            verified_submissions = [s for s in submissions if s.get("verified")]
            # Sort by submission time (first to verify wins)
            verified_submissions.sort(key=lambda x: x.get("submitted_at", datetime.max))
            
            winners_text = ""
            for i, sub in enumerate(verified_submissions[:3], 1):
                medal = ["🥇", "🥈", "🥉"][i-1]
                winners_text += f"{medal} <@{sub.get('user_id')}>\n"
            
            if winners_text:
                embed.add_field(
                    name="🏆 First Verified Submissions",
                    value=winners_text,
                    inline=False
                )
        
        embed.set_footer(text="Thanks for participating!")
        embed.timestamp = datetime.utcnow()
        
        return embed
    
    @staticmethod
    def create_stats_embed(user: discord.Member, stats: dict) -> discord.Embed:
        """Create an embed showing a user's art challenge statistics"""
        embed = discord.Embed(
            title=f"🎨 Art Challenge Stats",
            description=f"Statistics for {user.mention}",
            color=discord.Color.blue()
        )
        
        total_submissions = stats.get("total_submissions", 0)
        verified_submissions = stats.get("verified_submissions", 0)
        total_points = stats.get("total_points", 0)
        
        # Calculate success rate
        success_rate = (verified_submissions / total_submissions * 100) if total_submissions > 0 else 0
        
        embed.add_field(
            name="📤 Total Submissions",
            value=f"**{total_submissions}**",
            inline=True
        )
        
        embed.add_field(
            name="✅ Verified",
            value=f"**{verified_submissions}**",
            inline=True
        )
        
        embed.add_field(
            name="📈 Success Rate",
            value=f"**{success_rate:.1f}%**",
            inline=True
        )
        
        embed.add_field(
            name="🏆 Total Points",
            value=f"**{total_points}**",
            inline=True
        )
        
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        embed.timestamp = datetime.utcnow()
        
        return embed
    
    @staticmethod
    def create_leaderboard_embed(leaderboard: list, bot) -> discord.Embed:
        """Create an embed showing the art challenge leaderboard"""
        embed = discord.Embed(
            title="🏆 Art Challenge Leaderboard",
            description="Top artists by challenge points",
            color=discord.Color.gold()
        )
        
        if not leaderboard:
            embed.description = "No challenge data yet! Be the first to participate!"
            return embed
        
        leaderboard_text = ""
        medals = ["🥇", "🥈", "🥉"]
        
        for i, entry in enumerate(leaderboard[:10], 1):
            user_id = entry.get("user_id")
            points = entry.get("total_points", 0)
            verified = entry.get("verified_submissions", 0)
            
            medal = medals[i-1] if i <= 3 else f"**{i}.**"
            leaderboard_text += f"{medal} <@{user_id}> - **{points}** pts ({verified} verified)\n"
        
        embed.add_field(
            name="Rankings",
            value=leaderboard_text or "No data",
            inline=False
        )
        
        embed.set_footer(text="Complete art challenges to earn points!")
        embed.timestamp = datetime.utcnow()
        
        return embed


class SubmitArtworkModal(Modal):
    """Modal for submitting artwork URL (backup if no image attached)"""
    
    def __init__(self, challenge_id: str, art_manager: 'ArtChallengeManager'):
        super().__init__(title="Submit Your Artwork")
        self.challenge_id = challenge_id
        self.art_manager = art_manager
        
        self.image_url = TextInput(
            label="Image URL",
            placeholder="Paste the direct URL to your artwork image...",
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.image_url)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle the modal submission"""
        url = self.image_url.value.strip()
        
        # Basic URL validation
        if not url.startswith(('http://', 'https://')):
            await interaction.response.send_message(
                "❌ Please provide a valid image URL starting with http:// or https://",
                ephemeral=True
            )
            return
        
        # Defer the response since verification takes time
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            result = await self.art_manager.submit_entry(
                challenge_id=self.challenge_id,
                user_id=interaction.user.id,
                image_url=url,
                message_id=0  # No message for URL submissions
            )
            
            if result.get("success"):
                embed = ArtChallengeEmbed.create_submission_result_embed(result, interaction.user)
                await interaction.followup.send(embed=embed, ephemeral=False)
            else:
                await interaction.followup.send(
                    f"❌ {result.get('error', 'Failed to submit entry')}",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error in artwork submission modal: {e}")
            await interaction.followup.send(
                "❌ An error occurred while submitting your artwork.",
                ephemeral=True
            )


class ArtChallengeView(View):
    """Persistent view for art challenge interactions"""
    
    def __init__(self, challenge_id: str = None, art_manager: 'ArtChallengeManager' = None):
        super().__init__(timeout=None)  # Persistent view
        self.challenge_id = challenge_id
        self.art_manager = art_manager
    
    @discord.ui.button(
        label="Submit Artwork",
        style=discord.ButtonStyle.primary,
        emoji="🎨",
        custom_id="art_challenge:submit"
    )
    async def submit_button(self, interaction: discord.Interaction, button: Button):
        """Handle the submit button click"""
        # Get the challenge ID from the message if not set
        if not self.challenge_id:
            # Try to get from message custom_id or content
            await interaction.response.send_message(
                "❌ Could not identify the challenge. Please try again.",
                ephemeral=True
            )
            return
        
        # Check if challenge is still active
        if self.art_manager:
            challenge = self.art_manager.get_challenge_by_id(self.challenge_id)
            if not challenge or challenge.get("state") != "active":
                await interaction.response.send_message(
                    "❌ This challenge has ended!",
                    ephemeral=True
                )
                return
            
            if datetime.utcnow() > challenge.get("end_time"):
                await interaction.response.send_message(
                    "❌ Time's up! This challenge has expired.",
                    ephemeral=True
                )
                return
        
        # Show instructions for submission
        await interaction.response.send_message(
            "🎨 **How to Submit:**\n\n"
            "1. **Post your artwork** as an image in this channel\n"
            "2. **Reply to your image** with: `!submit`\n\n"
            "Or use `/artsubmit` with your image attached!\n\n"
            "⏰ Make sure to submit before the challenge ends!",
            ephemeral=True
        )
    
    @discord.ui.button(
        label="View Stats",
        style=discord.ButtonStyle.secondary,
        emoji="📊",
        custom_id="art_challenge:stats"
    )
    async def stats_button(self, interaction: discord.Interaction, button: Button):
        """Show the user's art challenge stats"""
        if not self.art_manager:
            await interaction.response.send_message(
                "❌ Stats unavailable at this time.",
                ephemeral=True
            )
            return
        
        stats = self.art_manager.get_user_challenge_stats(interaction.user.id)
        
        if not stats:
            await interaction.response.send_message(
                "📊 You haven't participated in any art challenges yet!\n"
                "Submit your first artwork to get started!",
                ephemeral=True
            )
            return
        
        embed = ArtChallengeEmbed.create_stats_embed(interaction.user, stats)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(
        label="Leaderboard",
        style=discord.ButtonStyle.secondary,
        emoji="🏆",
        custom_id="art_challenge:leaderboard"
    )
    async def leaderboard_button(self, interaction: discord.Interaction, button: Button):
        """Show the art challenge leaderboard"""
        if not self.art_manager:
            await interaction.response.send_message(
                "❌ Leaderboard unavailable at this time.",
                ephemeral=True
            )
            return
        
        leaderboard = self.art_manager.get_challenge_leaderboard(10)
        embed = ArtChallengeEmbed.create_leaderboard_embed(leaderboard, interaction.client)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ArtChallengeViewManager:
    """Manages art challenge views and persistence"""
    
    def __init__(self, bot):
        self.bot = bot
        self.art_manager: Optional['ArtChallengeManager'] = None
    
    def set_art_manager(self, manager: 'ArtChallengeManager'):
        """Set the art challenge manager"""
        self.art_manager = manager
    
    def setup_persistent_views(self):
        """Register persistent views with the bot"""
        # Create a view without specific challenge ID for persistence
        view = ArtChallengeView()
        view.art_manager = self.art_manager
        self.bot.add_view(view)
        logger.info("✅ Art challenge persistent views registered")
    
    def create_challenge_view(self, challenge_id: str) -> ArtChallengeView:
        """Create a new view for a specific challenge"""
        view = ArtChallengeView(challenge_id=challenge_id, art_manager=self.art_manager)
        return view
    
    async def post_challenge(self, channel: discord.TextChannel, challenge_data: dict) -> Optional[discord.Message]:
        """Post a new challenge to a channel"""
        try:
            embed = ArtChallengeEmbed.create_challenge_embed(challenge_data)
            view = self.create_challenge_view(challenge_data.get("challenge_id"))
            
            message = await channel.send(
                content="🚨 **NEW ART CHALLENGE!** 🚨",
                embed=embed,
                view=view
            )
            
            # Update the challenge with the message ID
            if self.art_manager:
                self.art_manager.update_challenge_message(
                    challenge_data.get("challenge_id"),
                    message.id
                )
            
            return message
            
        except Exception as e:
            logger.error(f"Error posting challenge: {e}")
            return None
    
    async def end_challenge(self, channel: discord.TextChannel, challenge_data: dict):
        """Post the challenge ended message"""
        try:
            submissions = []
            if self.art_manager:
                submissions = self.art_manager.get_challenge_submissions(challenge_data.get("challenge_id"))
            
            embed = ArtChallengeEmbed.create_challenge_ended_embed(challenge_data, submissions)
            await channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error posting challenge end: {e}")
