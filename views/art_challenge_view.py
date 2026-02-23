import discord
from discord.ui import View, Button, Modal, TextInput
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING, List
import logging
import asyncio
import aiohttp
import io

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
        
        # Create Discord timestamp for end time
        if isinstance(end_time, datetime):
            # Convert to Unix timestamp for Discord
            unix_timestamp = int(end_time.timestamp())
            time_display = f"<t:{unix_timestamp}:R>"  # Relative time (e.g., "in 59 minutes")
        else:
            # Fallback: 1 hour from now
            unix_timestamp = int((datetime.utcnow() + timedelta(hours=1)).timestamp())
            time_display = f"<t:{unix_timestamp}:R>"
        
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
        
        elif challenge_type in ["mixed", "scene_move"]:
            # Mixed or scene-move challenge - combine two images
            character_name = challenge_data.get("character_to_move", "the character")
            default_title = "🔀 Mix These Images!" if challenge_type == "mixed" else f"🧳 Move {character_name} to This Scene!"
            default_description = "Combine elements from BOTH images!" if challenge_type == "mixed" else "Move the character from image 1 into image 2."
            embed = discord.Embed(
                title=challenge_data.get("challenge_title", default_title),
                description=challenge_data.get("challenge_description", default_description),
                color=discord.Color.from_rgb(0, 191, 255)  # Deep sky blue
            )
            
            # Combined tags from both images
            ref_tags_1 = challenge_data.get("reference_tags", [])
            ref_tags_2 = challenge_data.get("reference_tags_2", [])
            all_tags = list(set(ref_tags_1[:5] + ref_tags_2[:5]))  # Combine unique tags
            if all_tags:
                embed.add_field(
                    name="📌 Combined Reference Tags",
                    value=", ".join(all_tags[:10]) if all_tags else "No tags",
                    inline=False
                )

            if challenge_type == "scene_move":
                embed.add_field(
                    name="🎯 Goal",
                    value=f"Place **{character_name}** from Image 1 into the scenery shown in Image 2.",
                    inline=False
                )
            
            # Mark that this needs image files uploaded
            challenge_data["_needs_image_files"] = True
        
        elif challenge_type == "palette":
            palette_name = challenge_data.get("palette_name", "Random Palette")
            palette_colors = challenge_data.get("required_palette", [])
            embed = discord.Embed(
                title=challenge_data.get("challenge_title", "🎨 Palette Lock Challenge!"),
                description=challenge_data.get("challenge_description", "Create artwork using only the required palette."),
                color=discord.Color.from_rgb(255, 105, 180)
            )
            if palette_colors:
                embed.add_field(
                    name=f"🖌️ Required Palette: {palette_name}",
                    value="\n".join([f"• `{c}`" for c in palette_colors]),
                    inline=False
                )

        elif challenge_type == "time_shift":
            shift_direction = challenge_data.get("time_shift_direction", "future")
            embed = discord.Embed(
                title=challenge_data.get("challenge_title", "⏳ Time Shift Challenge!"),
                description=challenge_data.get("challenge_description", "Transform the reference character across time."),
                color=discord.Color.from_rgb(255, 165, 0)
            )
            reference_url = challenge_data.get("reference_image_url")
            if reference_url:
                embed.set_image(url=reference_url)
            embed.add_field(
                name="🕰️ Direction",
                value=f"**{shift_direction.title()} Self**",
                inline=False
            )
            embed.add_field(
                name="🔞 Safety Rule",
                value="Must remain adult-only (18+). No minor/loli/shota depictions.",
                inline=False
            )

        elif challenge_type == "edit":
            # Edit challenge - modify image and add an item
            embed = discord.Embed(
                title=challenge_data.get("challenge_title", "✏️ Edit This Image!"),
                description=challenge_data.get("challenge_description", "Edit the image and add the required item!"),
                color=discord.Color.from_rgb(50, 205, 50)  # Lime green
            )
            
            # Set the reference image
            reference_url = challenge_data.get("reference_image_url")
            if reference_url:
                embed.set_image(url=reference_url)
            
            # Show the required item to add
            required_item = challenge_data.get("required_item", "something creative")
            embed.add_field(
                name="✨ Item to Add",
                value=f"**{required_item}**",
                inline=False
            )
            
            # Add reference tags
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
        
        # Common fields - use Discord timestamp for live countdown
        embed.add_field(
            name="⏰ Ends",
            value=time_display,
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
        is_resubmission = result.get("is_resubmission", False)
        already_verified = result.get("already_verified", False)
        submission_number = result.get("submission_number", 1)
        is_duplicate = result.get("is_duplicate", False) or verification.get("is_duplicate", False)
        
        # Check for duplicate/cheating attempt first
        if is_duplicate:
            similarity = verification.get("similarity_score", 1.0)
            embed = discord.Embed(
                title="🚫 Duplicate Detected!",
                description=f"{user.mention}, you submitted the same image as the reference!\n\n**This is not allowed!** You must create your own artwork.",
                color=discord.Color.dark_red()
            )
            embed.add_field(
                name="⚠️ Penalty Applied",
                value=f"**{points}** points",
                inline=True
            )
            embed.add_field(
                name="📊 Similarity",
                value=f"{similarity:.0%} match",
                inline=True
            )
            embed.add_field(
                name="💡 What to do",
                value="Create your own artistic interpretation! Any style is welcome - digital, traditional, sketch, anime, realistic - just make it YOUR artwork!",
                inline=False
            )
            embed.set_footer(text="⚠️ Re-uploading the reference image is considered cheating")
            embed.timestamp = datetime.utcnow()
            return embed
        
        if verified:
            if already_verified:
                # They already got points before, this is just a flex
                embed = discord.Embed(
                    title="✅ Submission Verified! (No Points)",
                    description=f"{user.mention}, your artwork passed verification!\n\n*You already received points for this challenge.*",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="ℹ️ Note",
                    value="You can only earn points once per challenge.",
                    inline=False
                )
            else:
                embed = discord.Embed(
                    title="✅ Submission Verified!",
                    description=f"Congratulations {user.mention}! Your artwork passed verification!",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="🏆 Points Earned",
                    value=f"**+{points}** general points\n**+{points}** art challenge points",
                    inline=True
                )
                if is_resubmission:
                    embed.add_field(
                        name="🔄 Retry Success!",
                        value=f"Nice! You got it on attempt #{submission_number}!",
                        inline=True
                    )
        else:
            embed = discord.Embed(
                title="❌ Verification Failed",
                description=f"Sorry {user.mention}, your submission didn't meet the challenge requirements.",
                color=discord.Color.red()
            )
            if not already_verified:
                embed.add_field(
                    name="💡 Tip",
                    value="You can try again! Submit another image to retry.",
                    inline=False
                )
            else:
                embed.add_field(
                    name="ℹ️ Note",
                    value="You already earned points for this challenge, so no worries!",
                    inline=False
                )
        
        # Show submission number if it's a resubmission
        if submission_number > 1:
            embed.add_field(
                name="🔢 Attempt",
                value=f"#{submission_number}",
                inline=True
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
    def create_challenge_ended_embed(challenge_data: dict, submissions: list, winner_data: dict = None) -> discord.Embed:
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
        elif challenge_type == "edit":
            required_item = challenge_data.get("required_item", "item")
            embed.add_field(
                name="✏️ Challenge Type",
                value=f"Edit Challenge (add: {required_item})",
                inline=True
            )
        elif challenge_type == "mixed":
            embed.add_field(
                name="🔀 Challenge Type",
                value="Mixed Challenge",
                inline=True
            )
        elif challenge_type == "scene_move":
            embed.add_field(
                name="🧳 Challenge Type",
                value=f"Scene Move Challenge (Move {challenge_data.get('character_to_move', 'Character')})",
                inline=True
            )
        elif challenge_type == "palette":
            palette_name = challenge_data.get("palette_name", "Palette")
            palette_colors = challenge_data.get("required_palette", [])
            embed.add_field(
                name="🎨 Challenge Type",
                value=f"Palette Lock ({palette_name}): {', '.join(palette_colors)}",
                inline=True
            )
        elif challenge_type == "time_shift":
            shift_direction = challenge_data.get("time_shift_direction", "future")
            embed.add_field(
                name="⏳ Challenge Type",
                value=f"Time Shift Challenge ({shift_direction.title()} Self)",
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
        
        # Add AI-selected winner if any
        if winner_data:
            winner_text = f"🏆 <@{winner_data.get('user_id')}> (+100 bonus points!)\n"
            reasoning = winner_data.get('reasoning', '')
            if reasoning:
                winner_text += f"*{reasoning}*"
            
            embed.add_field(
                name="👑 Challenge Winner",
                value=winner_text,
                inline=False
            )
            
            # Set winner's submission as thumbnail
            winner_image = winner_data.get("image_url")
            if winner_image:
                embed.set_thumbnail(url=winner_image)
        
        # Add all verified participants
        if verified_count > 0:
            verified_submissions = [s for s in submissions if s.get("verified")]
            verified_submissions.sort(key=lambda x: x.get("submitted_at", datetime.max))
            
            # List all verified participants (excluding winner)
            winner_id = winner_data.get("user_id") if winner_data else None
            participants = [s for s in verified_submissions if s.get("user_id") != winner_id]
            
            if participants:
                participants_text = ", ".join([f"<@{s.get('user_id')}>" for s in participants[:10]])
                if len(participants) > 10:
                    participants_text += f" +{len(participants) - 10} more"
                
                embed.add_field(
                    name="✨ Verified Participants",
                    value=participants_text,
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
        
        # Defer the response to prevent interaction timeout during database query
        await interaction.response.defer(ephemeral=True)
        
        stats = self.art_manager.get_user_challenge_stats(interaction.user.id)
        
        if not stats:
            await interaction.followup.send(
                "📊 You haven't participated in any art challenges yet!\n"
                "Submit your first artwork to get started!",
                ephemeral=True
            )
            return
        
        embed = ArtChallengeEmbed.create_stats_embed(interaction.user, stats)
        await interaction.followup.send(embed=embed, ephemeral=True)
    
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
        
        # Defer the response to prevent interaction timeout during database query
        await interaction.response.defer(ephemeral=True)
        
        leaderboard = self.art_manager.get_challenge_leaderboard(10)
        embed = ArtChallengeEmbed.create_leaderboard_embed(leaderboard, interaction.client)
        await interaction.followup.send(embed=embed, ephemeral=True)


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
            
            # Check for flags set by embed creation
            needs_image_files = challenge_data.pop("_needs_image_files", False)
            embeds = [embed]
            
            # Check if NSFW channel or mixed challenge - upload images as files
            rating = challenge_data.get("rating", "safe")
            is_nsfw = rating == "questionable"
            challenge_type = challenge_data.get("challenge_type")
            files: List[discord.File] = []
            
            # Determine if we need to upload images as files
            should_upload_files = is_nsfw or needs_image_files
            
            if should_upload_files:
                # Collect image URLs from challenge data
                image_urls = []
                
                if challenge_data.get("reference_image_url"):
                    image_urls.append(("image_1.jpg", challenge_data.get("reference_image_url")))
                if challenge_data.get("reference_image_url_2"):
                    image_urls.append(("image_2.jpg", challenge_data.get("reference_image_url_2")))
                
                # Download and create files
                async with aiohttp.ClientSession() as session:
                    for filename, url in image_urls:
                        try:
                            async with session.get(url, timeout=30) as response:
                                if response.status == 200:
                                    image_data = await response.read()
                                    # Spoiler for NSFW, regular for SFW
                                    final_filename = f"SPOILER_{filename}" if is_nsfw else filename
                                    file = discord.File(
                                        io.BytesIO(image_data),
                                        filename=final_filename
                                    )
                                    files.append(file)
                        except Exception as e:
                            logger.error(f"Error downloading image: {e}")
                
                # Clear images from embeds since we're uploading separately
                embed._image = None
                
                # Add note about images
                if is_nsfw:
                    embed.add_field(
                        name="\u26a0\ufe0f Note",
                        value="Reference images are spoilered above \u2b06\ufe0f",
                        inline=False
                    )
                elif needs_image_files:
                    embed.add_field(
                        name="\ud83d\uddbc\ufe0f Reference Images",
                        value="See the images above \u2b06\ufe0f",
                        inline=False
                    )
            
            message = await channel.send(
                content="\ud83d\udea8 **NEW ART CHALLENGE!** \ud83d\udea8",
                embeds=embeds,
                files=files if files else None,
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
        """Post the challenge ended message and select winner"""
        try:
            submissions = []
            winner_data = None
            
            if self.art_manager:
                challenge_id = challenge_data.get("challenge_id")
                submissions = self.art_manager.get_challenge_submissions(challenge_id)
                
                # Select the best submission using AI
                winner_data = await self.art_manager.select_best_submission(challenge_id, challenge_data)
                
                if winner_data:
                    # Award bonus points to winner
                    winner_id = winner_data.get("user_id")
                    self.art_manager.award_winner_bonus(winner_id, 100)
                    
                    # Also award to main leaderboard
                    try:
                        from models.mongo_leaderboard_manager import MongoLeaderboardManager
                        leaderboard = MongoLeaderboardManager()
                        winner_member = channel.guild.get_member(winner_id)
                        if winner_member:
                            await leaderboard.add_points(
                                user_id=winner_id,
                                user_name=winner_member.display_name,
                                points=100,
                                point_type="art_challenge_winner",
                                reason="Art challenge winner bonus"
                            )
                    except Exception as e:
                        logger.error(f"Error awarding winner leaderboard points: {e}")
            
            embed = ArtChallengeEmbed.create_challenge_ended_embed(challenge_data, submissions, winner_data)
            await channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error posting challenge end: {e}")
