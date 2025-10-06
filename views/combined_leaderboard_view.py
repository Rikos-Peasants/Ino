import discord
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class CombinedLeaderboardView(discord.ui.View):
    """Interactive view for switching between different leaderboards"""
    
    def __init__(self, ctx, leaderboard_manager, quest_manager, initial_type="images"):
        super().__init__(timeout=300)  # 5 minute timeout
        self.ctx = ctx
        self.leaderboard_manager = leaderboard_manager
        self.quest_manager = quest_manager
        self.current_board = initial_type  # Use provided initial type
        
        # Set initial button styles based on initial_type
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if (initial_type == "images" and item.custom_id == "images_lb") or \
                   (initial_type == "points" and item.custom_id == "points_lb") or \
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
            
            # Get leaderboard data
            leaderboard_data = self.leaderboard_manager.get_leaderboard(limit=10)
            
            # Import here to avoid circular import
            from views.embeds import EmbedViews
            embed = EmbedViews.leaderboard_embed(leaderboard_data, "all time")
            
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
            await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
    
    @discord.ui.button(label="💎 Quest Points", style=discord.ButtonStyle.secondary, custom_id="points_lb")
    async def points_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show Quest Points leaderboard"""
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your command!", ephemeral=True)
            return
        
        try:
            if not self.quest_manager:
                await interaction.response.send_message("❌ Quest system is not available!", ephemeral=True)
                return
            
            self.current_board = "points"
            
            # Update button styles
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.style = discord.ButtonStyle.primary if item.custom_id == "points_lb" else discord.ButtonStyle.secondary
            
            # Get quest points leaderboard
            leaderboard = await self.quest_manager.get_quest_points_leaderboard(limit=10, guild=self.ctx.guild)
            
            # Import here to avoid circular import
            from views.embeds import EmbedViews
            embed = EmbedViews.quest_points_leaderboard_embed(leaderboard, self.ctx.author.id)
            
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.error(f"Error showing quest points leaderboard: {e}")
            await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
    
    @discord.ui.button(label="🎭 InoRep", style=discord.ButtonStyle.secondary, custom_id="inorep_lb")
    async def inorep_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show InoRep leaderboard"""
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ This is not your command!", ephemeral=True)
            return
        
        try:
            if not self.leaderboard_manager.inorep_manager:
                await interaction.response.send_message("❌ InoRep system is not available!", ephemeral=True)
                return
            
            self.current_board = "inorep"
            
            # Update button styles
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.style = discord.ButtonStyle.primary if item.custom_id == "inorep_lb" else discord.ButtonStyle.secondary
            
            # Get InoRep leaderboard (best)
            leaderboard_data = await self.leaderboard_manager.inorep_manager.get_leaderboard(
                str(self.ctx.guild.id),
                limit=10,
                reverse=False
            )
            
            # Import here to avoid circular import
            from views.embeds import EmbedViews
            embed = EmbedViews.inorep_leaderboard_embed(leaderboard_data, worst=False)
            
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.error(f"Error showing InoRep leaderboard: {e}")
            await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
    
    async def on_timeout(self):
        """Disable buttons when view times out"""
        try:
            for item in self.children:
                item.disabled = True
        except:
            pass

