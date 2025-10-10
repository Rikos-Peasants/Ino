import discord
from datetime import datetime
import logging
import math

logger = logging.getLogger(__name__)

class PaginatedAchievementsView(discord.ui.View):
    """Interactive paginated view for user achievements"""
    
    def __init__(self, achievements: list, user_name: str, user_id: int, per_page: int = 4):
        super().__init__(timeout=300)  # 5 minute timeout
        self.achievements = achievements
        self.user_name = user_name
        self.user_id = user_id
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = max(1, math.ceil(len(achievements) / per_page))
        
        # Update button states
        self._update_buttons()
    
    def _update_buttons(self):
        """Update button states based on current page"""
        # Enable/disable buttons based on current page
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "prev_page":
                    item.disabled = self.current_page == 0
                elif item.custom_id == "next_page":
                    item.disabled = self.current_page >= self.total_pages - 1
    
    def get_current_page_achievements(self):
        """Get achievements for the current page"""
        start_idx = self.current_page * self.per_page
        end_idx = start_idx + self.per_page
        return self.achievements[start_idx:end_idx]
    
    def create_embed(self):
        """Create embed for current page"""
        embed = discord.Embed(
            title="🏆 Achievements",
            description=f"**{self.user_name}'s** earned achievements",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        
        if not self.achievements:
            embed.add_field(
                name="No Achievements Yet",
                value="Keep posting and rating images to earn achievements!",
                inline=False
            )
        else:
            current_achievements = self.get_current_page_achievements()
            total_points = sum(a['reward_points'] for a in self.achievements)
            
            for achievement in current_achievements:
                icon = achievement.get('icon', '🏆')
                points = achievement['reward_points']
                earned_date = achievement['earned_at'].strftime('%m/%d/%Y')
                
                embed.add_field(
                    name=f"{icon} {achievement['name']} ({points} pts)",
                    value=f"{achievement['description']}\nEarned: {earned_date}",
                    inline=True
                )
            
            # Add empty fields to maintain grid layout if needed
            while len(current_achievements) % 2 != 0 and len(current_achievements) < 4:
                embed.add_field(name="\u200b", value="\u200b", inline=True)
            
            # Footer with page info and totals
            page_info = f"Page {self.current_page + 1}/{self.total_pages}"
            total_info = f"Total Achievements: {len(self.achievements)} • Total Points: {total_points}"
            embed.set_footer(text=f"{page_info} • {total_info}")
        
        return embed
    
    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary, custom_id="prev_page")
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to previous page"""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your command!", ephemeral=True)
            return
        
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()
    
    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.secondary, custom_id="next_page")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to next page"""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your command!", ephemeral=True)
            return
        
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._update_buttons()
            embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()
    
    @discord.ui.button(label="🗑️ Close", style=discord.ButtonStyle.danger, custom_id="close")
    async def close_view(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Close the achievements view"""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your command!", ephemeral=True)
            return
        
        # Disable all buttons and update message
        for item in self.children:
            item.disabled = True
        
        embed = self.create_embed()
        embed.set_footer(text=f"{embed.footer.text} • View closed")
        
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()
    
    async def on_timeout(self):
        """Called when the view times out"""
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        # Note: We can't edit the message here since we don't have access to it
        # The timeout will be handled by the command that created this view
        self.stop()