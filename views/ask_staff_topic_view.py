import discord
import logging
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)

class AskStaffTopicView(discord.ui.View):
    """Interactive view to let thread creators select a staff forum topic tag.
    Provides buttons for Complaint, Suggestion, and Warning Appeal.
    """
    def __init__(self, timeout: int = 600):
        super().__init__(timeout=timeout)

    def _user_can_set(self, interaction: discord.Interaction) -> bool:
        """Only allow thread creator, staff, or admins to set topic."""
        try:
            # Thread owner can set
            owner_ok = hasattr(interaction.channel, 'owner_id') and interaction.user.id == interaction.channel.owner_id
            if owner_ok:
                return True

            member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
            if not member:
                return False

            # Staff role can set
            if discord.utils.get(member.roles, id=Config.STAFF_ROLE_ID):
                return True

            # Admins can set
            if member.guild_permissions.administrator:
                return True
        except Exception:
            pass
        return False

    async def _apply_topic(self, interaction: discord.Interaction, topic_name: str):
        """Apply the selected topic tag to the forum thread and optionally prefix title."""
        try:
            if not self._user_can_set(interaction):
                await interaction.response.send_message(
                    "❌ Only the thread creator or staff can set the topic.", ephemeral=True
                )
                return

            # Must be used inside a forum thread
            if not isinstance(interaction.channel, discord.Thread) or interaction.channel.parent is None:
                await interaction.response.send_message(
                    "❌ This can only be used inside a forum thread.", ephemeral=True
                )
                return

            forum_channel: discord.ForumChannel = interaction.channel.parent
            available_tags = getattr(forum_channel, 'available_tags', [])
            target_tag = None
            for t in available_tags:
                if t.name == topic_name:
                    target_tag = t
                    break

            if not target_tag:
                await interaction.response.send_message(
                    "❌ Topic tag is not configured for this forum.", ephemeral=True
                )
                return

            current_tags = interaction.channel.applied_tags or []
            # Check by ID to avoid duplicates
            if any(getattr(t, 'id', None) == getattr(target_tag, 'id', None) for t in current_tags):
                try:
                    await interaction.response.send_message(
                        f"✅ Topic already set to {topic_name}.", ephemeral=True
                    )
                except discord.InteractionResponded:
                    await interaction.followup.send(
                        f"✅ Topic already set to {topic_name}.", ephemeral=True
                    )
                return

            new_tags = current_tags + [target_tag]
            await interaction.channel.edit(applied_tags=new_tags)

            # Optionally update title prefix if missing
            try:
                prefix = Config.STAFF_FORUM_TAG_PREFIXES.get(topic_name)
                if prefix:
                    title = interaction.channel.name
                    has_prefix = any(title.startswith(p) for p in Config.STAFF_FORUM_TAG_PREFIXES.values())
                    if not has_prefix:
                        new_title = f"{prefix} {title}"
                        if len(new_title) > 100:
                            max_original_length = 100 - len(prefix) - 1
                            new_title = f"{prefix} {title[:max_original_length].rstrip()}"
                        await interaction.channel.edit(name=new_title)
            except Exception as e:
                logger.debug(f"Failed to update thread title prefix: {e}")

            # Confirm to the user
            try:
                await interaction.response.send_message(
                    f"✅ Set thread topic to **{topic_name}**.", ephemeral=True
                )
            except discord.InteractionResponded:
                await interaction.followup.send(
                    f"✅ Set thread topic to **{topic_name}**.", ephemeral=True
                )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to edit thread tags.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to set topic: {e}", ephemeral=True
            )

    @discord.ui.button(label="Complaint", style=discord.ButtonStyle.primary, emoji="📢", custom_id="askstaff_topic:complaint")
    async def complaint(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply_topic(interaction, "Complaint")

    @discord.ui.button(label="Suggestion", style=discord.ButtonStyle.primary, emoji="💡", custom_id="askstaff_topic:suggestion")
    async def suggestion(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply_topic(interaction, "Suggestion")

    @discord.ui.button(label="Warning Appeal", style=discord.ButtonStyle.primary, emoji="⚖️", custom_id="askstaff_topic:appeal")
    async def appeal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply_topic(interaction, "Warning Appeal")