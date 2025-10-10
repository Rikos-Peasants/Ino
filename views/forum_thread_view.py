import discord
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ForumThreadView(discord.ui.View):
    """Persistent view for forum thread management with close button"""
    
    def __init__(self, thread_id: Optional[int] = None):
        super().__init__(timeout=None)  # Persistent view - no timeout
        self.thread_id = thread_id
        
        # Set custom ID for persistence across bot restarts
        if thread_id:
            self.close_button.custom_id = f"close_thread:{thread_id}"
    
    @discord.ui.button(
        label="🔒 Close Thread", 
        style=discord.ButtonStyle.red, 
        emoji="🔒"
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle thread closure"""
        try:
            # Get the thread from the interaction
            thread = interaction.channel
            
            # Verify this is actually a thread
            if not isinstance(thread, discord.Thread):
                await interaction.response.send_message("❌ This can only be used in threads.", ephemeral=True)
                return
            
            # Check if user has permission to close the thread
            # Allow thread creator, moderators, or users with manage threads permission
            can_close = (
                thread.owner_id == interaction.user.id or  # Thread creator
                interaction.user.guild_permissions.manage_threads or  # Manage threads permission
                interaction.user.guild_permissions.administrator  # Administrator
            )
            
            if not can_close:
                await interaction.response.send_message(
                    "❌ You can only close threads you created or if you have manage threads permission.", 
                    ephemeral=True
                )
                return
            
            # Check if thread is already archived/closed
            if thread.archived:
                await interaction.response.send_message("❌ This thread is already closed.", ephemeral=True)
                return
            
            # Close the thread
            await thread.edit(
                archived=True, 
                reason=f"Thread closed by {interaction.user.display_name}"
            )
            
            # Send confirmation message
            await interaction.response.send_message(
                f"✅ Thread '{thread.name}' has been closed by {interaction.user.mention}.",
                ephemeral=False
            )
            
            # Disable the button after use
            button.disabled = True
            await interaction.edit_original_response(view=self)
            
            logger.info(f"Thread {thread.id} closed by user {interaction.user.id} ({interaction.user.display_name})")
            
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to close this thread.", 
                ephemeral=True
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Failed to close thread: {str(e)}", 
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error closing thread: {e}")
            await interaction.response.send_message(
                "❌ An unexpected error occurred while closing the thread.", 
                ephemeral=True
            )

    @classmethod
    def from_custom_id(cls, custom_id: str):
        """Create view instance from custom_id for persistent views"""
        try:
            if custom_id.startswith("close_thread:"):
                thread_id = int(custom_id.split(":", 1)[1])
                return cls(thread_id=thread_id)
        except (ValueError, IndexError):
            logger.error(f"Invalid custom_id format: {custom_id}")
        return cls()