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
        # Always set a custom_id to make this a valid persistent view
        if thread_id:
            self.close_button.custom_id = f"close_thread:{thread_id}"
        else:
            self.close_button.custom_id = "close_thread:generic"
    
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
            
            # Check if thread is already archived/closed
            if thread.archived:
                await interaction.response.send_message("❌ This thread is already closed.", ephemeral=True)
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
            try:
                await interaction.edit_original_response(view=self)
            except (discord.NotFound, discord.HTTPException):
                # Interaction might be expired or thread archived, ignore
                pass
            
            logger.info(f"Thread {thread.id} closed by user {interaction.user.id} ({interaction.user.display_name})")
            
        except discord.Forbidden as e:
            # Check if we already responded
            if not interaction.response.is_done():
                if "Thread is archived" in str(e) or "50083" in str(e):
                    await interaction.response.send_message("❌ This thread is already closed.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ I don't have permission to close this thread.", ephemeral=True)
            else:
                logger.warning(f"Thread {thread.id} was already archived when user {interaction.user.id} tried to close it")
        except discord.HTTPException as e:
            # Check if we already responded
            if not interaction.response.is_done():
                if "Unknown interaction" in str(e) or "10062" in str(e):
                    # Interaction expired, log but don't try to respond
                    logger.warning(f"Interaction expired for thread {thread.id} close attempt by user {interaction.user.id}")
                else:
                    await interaction.response.send_message(f"❌ Failed to close thread: {str(e)}", ephemeral=True)
            else:
                logger.warning(f"HTTP exception after response sent for thread {thread.id}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error closing thread {thread.id}: {str(e)}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

    @classmethod
    def from_custom_id(cls, custom_id: str):
        """Create view instance from custom_id for persistent views"""
        try:
            if custom_id.startswith("close_thread:"):
                thread_part = custom_id.split(":", 1)[1]
                if thread_part == "generic":
                    return cls(thread_id=None)
                else:
                    thread_id = int(thread_part)
                    return cls(thread_id=thread_id)
        except (ValueError, IndexError):
            logger.error(f"Invalid custom_id format: {custom_id}")
        return cls()