import discord
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class CombinedLeaderboardView(discord.ui.View):
    """Interactive view for switching between different leaderboards"""
    
    def __init__(self, ctx, leaderboard_manager, quest_manager, initial_type="points"):
        super().__init__(timeout=300)  # 5 minute timeout
        self.ctx = ctx
        self.leaderboard_manager = leaderboard_manager
        self.quest_manager = quest_manager
        self.current_board = initial_type  # Use provided initial type
        self.image_sort_by = "total_score"  # Default sort for images leaderboard
        
        # Add dropdown for image sorting (only shown when on images board)
        if initial_type == "images":
            self.add_item(ImageSortSelect(self))
        
        # Set initial button styles based on initial_type
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if (initial_type == "images" and item.custom_id == "images_lb") or \
                   (initial_type == "points" and item.custom_id == "combined_points_lb") or \
                   (initial_type == "inorep" and item.custom_id == "inorep_lb"):
                    item.style = discord.ButtonStyle.primary
                else:
                    item.style = discord.ButtonStyle.secondary
    
    @discord.ui.button(label="📸 Images", style=discord.ButtonStyle.primary, custom_id="images_lb")
    async def images_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show Images leaderboard"""
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your command!", ephemeral=True)
            return
        
        try:
            self.current_board = "images"
            
            # Update button styles
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.style = discord.ButtonStyle.primary if item.custom_id == "images_lb" else discord.ButtonStyle.secondary
            
            # Add or show dropdown for images
            has_dropdown = any(isinstance(item, ImageSortSelect) for item in self.children)
            if not has_dropdown:
                self.add_item(ImageSortSelect(self))
            
            # Get leaderboard data with current sort
            from models.april_fools import is_april_fools
            af_mode = is_april_fools()
            leaderboard_data = self.leaderboard_manager.get_leaderboard(limit=10, sort_by=self.image_sort_by, reverse=af_mode)
            
            # Import here to avoid circular import
            from views.embeds import EmbedViews
            if af_mode:
                embed = EmbedViews.april_fools_leaderboard_embed(leaderboard_data, self.ctx.author.id, board_type="images")
            else:
                sort_display = {"total_score": "Total Score", "avg_score": "Average Score", "image_count": "Image Count"}
                embed = EmbedViews.leaderboard_embed(leaderboard_data, f"all time - {sort_display.get(self.image_sort_by, 'Total Score')}")
            
            # Add stats summary
            stats = self.leaderboard_manager.get_stats_summary()
            embed.add_field(
                name="📊 Server Stats",
                value=f"**Total Users:** {stats['total_users']}\n"
                      f"**Total Images:** {stats['total_images']}\n"
                      f"**Average Score:** {stats['average_score']}",
                inline=False
            )
            
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.error(f"Error showing images leaderboard: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)
    
    @discord.ui.button(label="🏆 Points", style=discord.ButtonStyle.primary, custom_id="combined_points_lb")
    async def combined_points_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show Combined Points leaderboard (general + quest points)"""
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your command!", ephemeral=True)
            return
        
        # Defer the response to prevent timeout
        await interaction.response.defer()
        
        try:
            self.current_board = "points"
            
            # Update button styles
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.style = discord.ButtonStyle.primary if item.custom_id == "combined_points_lb" else discord.ButtonStyle.secondary
            
            # Remove dropdown when not on images board
            items_to_remove = [item for item in self.children if isinstance(item, ImageSortSelect)]
            for item in items_to_remove:
                self.remove_item(item)
            
            # Get combined points leaderboard
            leaderboard = await self.leaderboard_manager.get_combined_leaderboard(limit=10, quest_manager=self.quest_manager)
            
            # Import here to avoid circular import
            from views.embeds import EmbedViews
            from models.april_fools import is_april_fools
            if is_april_fools():
                leaderboard = list(reversed(leaderboard))
                embed = EmbedViews.april_fools_leaderboard_embed(leaderboard, self.ctx.author.id, board_type="points")
            else:
                embed = EmbedViews.combined_points_leaderboard_embed(leaderboard, self.ctx.author.id)
            
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)
        except Exception as e:
            logger.error(f"Error showing combined points leaderboard: {e}")
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)
    

    
    @discord.ui.button(label="🎭 InoRep", style=discord.ButtonStyle.secondary, custom_id="inorep_lb")
    async def inorep_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show InoRep leaderboard"""
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your command!", ephemeral=True)
            return
        
        # Defer the response to prevent timeout
        await interaction.response.defer()
        
        try:
            if not self.leaderboard_manager.inorep_manager:
                await interaction.followup.send("❌ InoRep system is not available!", ephemeral=True)
                return
            
            self.current_board = "inorep"
            
            # Update button styles
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.style = discord.ButtonStyle.primary if item.custom_id == "inorep_lb" else discord.ButtonStyle.secondary
            
            # Remove dropdown when not on images board
            items_to_remove = [item for item in self.children if isinstance(item, ImageSortSelect)]
            for item in items_to_remove:
                self.remove_item(item)
            
            # Get InoRep leaderboard (best, or worst-first on April Fools)
            from models.april_fools import is_april_fools
            af_mode = is_april_fools()
            leaderboard_data = await self.leaderboard_manager.inorep_manager.get_leaderboard(
                str(self.ctx.guild.id),
                limit=10,
                reverse=af_mode
            )
            
            # Import here to avoid circular import
            from views.embeds import EmbedViews
            if af_mode:
                embed = EmbedViews.april_fools_leaderboard_embed(leaderboard_data, self.ctx.author.id, board_type="inorep")
            else:
                embed = EmbedViews.inorep_leaderboard_embed(leaderboard_data, worst=False)
            
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)
        except Exception as e:
            logger.error(f"Error showing InoRep leaderboard: {e}")
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)
    
    async def on_timeout(self):
        """Disable buttons when view times out"""
        try:
            for item in self.children:
                item.disabled = True
        except:
            pass


class ImageSortSelect(discord.ui.Select):
    """Dropdown to select sorting method for images leaderboard"""
    
    def __init__(self, parent_view):
        self.parent_view = parent_view
        options = [
            discord.SelectOption(
                label="🏆 Total Score",
                value="total_score",
                description="Sort by total net upvotes",
                default=True
            ),
            discord.SelectOption(
                label="📊 Average Score",
                value="avg_score",
                description="Sort by average score per image"
            ),
            discord.SelectOption(
                label="📸 Image Count",
                value="image_count",
                description="Sort by number of images posted"
            )
        ]
        super().__init__(
            placeholder="🔽 Sort images by...",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle sort selection"""
        if interaction.user.id != self.parent_view.ctx.author.id:
            await interaction.response.send_message("❌ This is not your command!", ephemeral=True)
            return
        
        # Defer the response to prevent timeout
        await interaction.response.defer()
        
        try:
            # Update sort preference
            self.parent_view.image_sort_by = self.values[0]
            
            # Update dropdown default
            for option in self.options:
                option.default = (option.value == self.values[0])
            
            # Get sorted leaderboard data
            from models.april_fools import is_april_fools
            af_mode = is_april_fools()
            leaderboard_data = self.parent_view.leaderboard_manager.get_leaderboard(
                limit=10,
                sort_by=self.values[0],
                reverse=af_mode
            )
            
            # Import here to avoid circular import
            from views.embeds import EmbedViews
            if af_mode:
                embed = EmbedViews.april_fools_leaderboard_embed(leaderboard_data, self.parent_view.ctx.author.id, board_type="images")
            else:
                sort_display = {"total_score": "Total Score", "avg_score": "Average Score", "image_count": "Image Count"}
                embed = EmbedViews.leaderboard_embed(
                    leaderboard_data,
                    f"all time - {sort_display.get(self.values[0], 'Total Score')}"
                )
            
            # Add stats summary
            stats = self.parent_view.leaderboard_manager.get_stats_summary()
            embed.add_field(
                name="📊 Server Stats",
                value=f"**Total Users:** {stats['total_users']}\n"
                      f"**Total Images:** {stats['total_images']}\n"
                      f"**Average Score:** {stats['average_score']}",
                inline=False
            )
            
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self.parent_view)
            
        except Exception as e:
            logger.error(f"Error changing sort: {e}")
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

