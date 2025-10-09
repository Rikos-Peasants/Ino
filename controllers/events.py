import discord
from discord.ext import commands
from models.role_manager import RoleManager
from models.quest_manager import QuestManager
from views.embeds import EmbedViews
from config import Config
import logging
import asyncio
import random
from typing import List, Optional

logger = logging.getLogger(__name__)

class EventsController:
    """Controller for handling Discord events"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spam_channel_message_count = 0  # Track messages in spam channel
        self.quest_manager = None  # Will be initialized when bot is ready
    
    def register_events(self):
        """Register all Discord events"""
        
        @self.bot.event
        async def on_member_join(member: discord.Member):
            await self._handle_member_join(member)
        
        @self.bot.event
        async def on_member_remove(member: discord.Member):
            await self._handle_member_leave(member)
        
        @self.bot.event
        async def on_member_update(before: discord.Member, after: discord.Member):
            await self._handle_member_update(before, after)
        
        @self.bot.event
        async def on_message(message: discord.Message):
            await self._handle_message(message)
        
        @self.bot.event
        async def on_message_delete(message: discord.Message):
            await self._handle_message_delete(message)
        
        @self.bot.event
        async def on_command_error(ctx: commands.Context, error: commands.CommandError):
            await self._handle_command_error(ctx, error)
        
        @self.bot.event
        async def on_command(ctx: commands.Context):
            """Log when commands are successfully invoked"""
            # Handle DM channels
            channel_name = ctx.channel.name if hasattr(ctx.channel, 'name') else 'DM'
            logger.info(f"Command '{ctx.command.name}' invoked by {ctx.author.display_name} in #{channel_name}")
        
        @self.bot.event
        async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
            await self._handle_reaction_change(reaction, user, added=True)
        
        @self.bot.event
        async def on_reaction_remove(reaction: discord.Reaction, user: discord.User):
            await self._handle_reaction_change(reaction, user, added=False)
        
        @self.bot.event
        async def on_thread_update(before: discord.Thread, after: discord.Thread):
            await self._handle_thread_update(before, after)
        
        @self.bot.event
        async def on_thread_delete(thread: discord.Thread):
            await self._handle_thread_delete(thread)
    
    async def _handle_member_join(self, member: discord.Member):
        """Handle member join events to reapply NSFWBAN role if needed and send welcome message"""
        # Only process events from the configured guild
        if member.guild.id != Config.GUILD_ID:
            return
        
        try:
            # Check if the user is in the NSFWBAN database
            if await self.bot.leaderboard_manager.is_nsfwban_user(member.id):
                # Get the NSFWBAN banned role (the role applied to banned users)
                nsfwban_role = discord.utils.get(member.guild.roles, id=Config.NSFWBAN_BANNED_ROLE_ID)
                
                if nsfwban_role:
                    # Add the banned role back to the user
                    await member.add_roles(nsfwban_role, reason="Reapplying NSFWBAN role on rejoin")
                    logger.info(f"Reapplied NSFWBAN role to {member.display_name} on rejoin")
                    
                    # Also remove the NSFW/restricted role if they somehow have it
                    restricted_role = discord.utils.get(member.guild.roles, id=Config.RESTRICTED_ROLE_ID)
                    if restricted_role and restricted_role in member.roles:
                        await member.remove_roles(restricted_role, reason="NSFWBAN user - removing NSFW access on rejoin")
                        logger.info(f"Removed NSFW role from {member.display_name} on rejoin (NSFWBAN user)")
                    
                    # Get ban info for DM
                    ban_info = await self.bot.leaderboard_manager.get_nsfwban_user_info(member.id)
                    reason = ban_info.get('reason', 'No reason provided') if ban_info else 'No reason provided'
                    
                    # Send DM notification
                    try:
                        dm_embed = EmbedViews.nsfwban_dm_embed(reason, member.guild.name)
                        await member.send(embed=dm_embed)
                    except discord.Forbidden:
                        # User has DMs disabled, that's okay
                        pass
                    except Exception as e:
                        logger.error(f"Failed to send NSFWBAN rejoin DM to {member.display_name}: {e}")
                else:
                    logger.error(f"NSFWBAN role not found when trying to reapply to {member.display_name}")
            
            # Send welcome message if enabled
            await self._send_welcome_message(member)
                    
        except Exception as e:
            logger.error(f"Error handling member join for NSFWBAN reapplication: {e}")
    
    async def _handle_member_leave(self, member: discord.Member):
        """Handle member leave events and send leave message"""
        # Only process events from the configured guild
        if member.guild.id != Config.GUILD_ID:
            return
        
        try:
            # Send leave message if enabled
            await self._send_leave_message(member)
        except Exception as e:
            logger.error(f"Error handling member leave: {e}")
    
    async def _send_welcome_message(self, member: discord.Member):
        """Send welcome message to configured channel"""
        try:
            # Check if welcome system is enabled
            if not await self.bot.leaderboard_manager.is_welcome_enabled(member.guild.id):
                return
            
            # Get welcome channel
            welcome_channel_id = await self.bot.leaderboard_manager.get_welcome_channel(member.guild.id)
            if not welcome_channel_id:
                return
            
            welcome_channel = member.guild.get_channel(welcome_channel_id)
            if not welcome_channel:
                logger.warning(f"Welcome channel {welcome_channel_id} not found")
                return
            
            # Get welcome message template
            welcome_message_data = await self.bot.leaderboard_manager.get_welcome_message(member.guild.id)
            if not welcome_message_data:
                # Default welcome message
                welcome_message_data = {
                    "content": "Welcome {usermention}! 🎉"
                }
            
            # Process message with placeholders
            processed_message = await self._process_welcome_leave_message(welcome_message_data, member, "welcome")
            
            # Send the message
            await welcome_channel.send(**processed_message)
            logger.info(f"Sent welcome message for {member.display_name} in #{welcome_channel.name}")
            
        except Exception as e:
            logger.error(f"Error sending welcome message: {e}")
    
    async def _send_leave_message(self, member: discord.Member):
        """Send leave message to configured channel"""
        try:
            # Check if leave system is enabled
            if not await self.bot.leaderboard_manager.is_leave_enabled(member.guild.id):
                return
            
            # Get leave channel
            leave_channel_id = await self.bot.leaderboard_manager.get_leave_channel(member.guild.id)
            if not leave_channel_id:
                return
            
            leave_channel = member.guild.get_channel(leave_channel_id)
            if not leave_channel:
                logger.warning(f"Leave channel {leave_channel_id} not found")
                return
            
            # Get leave message template
            leave_message_data = await self.bot.leaderboard_manager.get_leave_message(member.guild.id)
            if not leave_message_data:
                # Default leave message
                leave_message_data = {
                    "content": "Goodbye {displayname}! 👋"
                }
            
            # Process message with placeholders
            processed_message = await self._process_welcome_leave_message(leave_message_data, member, "leave")
            
            # Send the message
            await leave_channel.send(**processed_message)
            logger.info(f"Sent leave message for {member.display_name} in #{leave_channel.name}")
            
        except Exception as e:
            logger.error(f"Error sending leave message: {e}")
    
    async def _process_welcome_leave_message(self, message_data: dict, member: discord.Member, message_type: str) -> dict:
        """Process welcome/leave message with placeholders"""
        import copy
        processed_data = copy.deepcopy(message_data)
        
        # Define placeholders
        placeholders = {
            "{usermention}": member.mention,
            "{displayname}": member.display_name,
            "{username}": member.name,
            "{userid}": str(member.id),
            "{userurl}": f"https://discord.com/users/{member.id}",
            "{useravatar}": str(member.display_avatar.url) if member.display_avatar else "",
            "{membercount}": str(member.guild.member_count),
            "{guildname}": member.guild.name,
            "{guildid}": str(member.guild.id)
        }
        
        def replace_placeholders(text):
            """Replace placeholders in text"""
            if not isinstance(text, str):
                return text
            for placeholder, value in placeholders.items():
                text = text.replace(placeholder, value)
            return text
        
        # Process content
        if "content" in processed_data:
            processed_data["content"] = replace_placeholders(processed_data["content"])
        
        # Process embeds
        if "embeds" in processed_data:
            for embed_data in processed_data["embeds"]:
                # Process embed fields
                for field_name in ["title", "description"]:
                    if field_name in embed_data:
                        embed_data[field_name] = replace_placeholders(embed_data[field_name])
                
                # Process embed author
                if "author" in embed_data:
                    for author_field in ["name", "url", "icon_url"]:
                        if author_field in embed_data["author"]:
                            embed_data["author"][author_field] = replace_placeholders(embed_data["author"][author_field])
                
                # Process embed footer
                if "footer" in embed_data:
                    for footer_field in ["text", "icon_url"]:
                        if footer_field in embed_data["footer"]:
                            embed_data["footer"][footer_field] = replace_placeholders(embed_data["footer"][footer_field])
                
                # Process embed fields
                if "fields" in embed_data:
                    for field in embed_data["fields"]:
                        if "name" in field:
                            field["name"] = replace_placeholders(field["name"])
                        if "value" in field:
                            field["value"] = replace_placeholders(field["value"])
                
                # Process embed image and thumbnail
                for image_field in ["image", "thumbnail"]:
                    if image_field in embed_data and "url" in embed_data[image_field]:
                        embed_data[image_field]["url"] = replace_placeholders(embed_data[image_field]["url"])
            
            # Convert embed data to discord.Embed objects
            embeds = []
            for embed_data in processed_data["embeds"]:
                embed = discord.Embed()
                
                # Set basic embed properties
                if "title" in embed_data:
                    embed.title = embed_data["title"]
                if "description" in embed_data:
                    embed.description = embed_data["description"]
                if "color" in embed_data:
                    embed.color = embed_data["color"]
                if "url" in embed_data:
                    embed.url = embed_data["url"]
                if "timestamp" in embed_data:
                    embed.timestamp = embed_data["timestamp"]
                
                # Set embed author
                if "author" in embed_data:
                    author = embed_data["author"]
                    author_kwargs = {"name": author.get("name", "")}
                    if "url" in author and author["url"]:
                        author_kwargs["url"] = author["url"]
                    if "icon_url" in author and author["icon_url"]:
                        author_kwargs["icon_url"] = author["icon_url"]
                    embed.set_author(**author_kwargs)
                
                # Set embed footer
                if "footer" in embed_data:
                    footer = embed_data["footer"]
                    footer_kwargs = {"text": footer.get("text", "")}
                    if "icon_url" in footer and footer["icon_url"]:
                        footer_kwargs["icon_url"] = footer["icon_url"]
                    embed.set_footer(**footer_kwargs)
                
                # Add embed fields
                if "fields" in embed_data:
                    for field in embed_data["fields"]:
                        embed.add_field(
                            name=field.get("name", ""),
                            value=field.get("value", ""),
                            inline=field.get("inline", False)
                        )
                
                # Set embed image
                if "image" in embed_data and "url" in embed_data["image"]:
                    embed.set_image(url=embed_data["image"]["url"])
                
                # Set embed thumbnail
                if "thumbnail" in embed_data and "url" in embed_data["thumbnail"]:
                    embed.set_thumbnail(url=embed_data["thumbnail"]["url"])
                
                embeds.append(embed)
            
            processed_data["embeds"] = embeds
        
        return processed_data
    
    async def _handle_member_join_message(self, message: discord.Message):
        """Handle Discord system messages for member joins and reply with sticker"""
        try:
            # Check if this is a system message for member join
            if message.type == discord.MessageType.new_member:
                # Get the sticker by ID from the guild
                sticker_id = 1391462726781505536
                
                # Try to get the sticker from the guild first
                sticker = None
                if message.guild:
                    sticker = discord.utils.get(message.guild.stickers, id=sticker_id)
                
                if sticker:
                    # Send the sticker as a reply to the member join message
                    await message.reply(stickers=[sticker])
                    logger.info(f"Sent welcome sticker for member join message in #{getattr(message.channel, 'name', 'DM')}")
                else:
                    logger.warning(f"Could not find guild sticker with ID {sticker_id}")
                    
        except discord.Forbidden:
            logger.error("Missing permission to send sticker messages for member joins")
        except discord.HTTPException as e:
            logger.error(f"HTTP error sending sticker for member join message: {e}")
        except Exception as e:
            logger.error(f"Error handling member join message: {e}")
    
    async def _handle_member_update(self, before: discord.Member, after: discord.Member):
        """Handle member role updates"""
        # Only process events from the configured guild
        if after.guild.id != Config.GUILD_ID:
            return
        
        # Get role changes
        roles_added = set(after.roles) - set(before.roles)
        
        # Check if the restricted role was added
        restricted_role = RoleManager.get_restricted_role(after.guild)
        if restricted_role in roles_added:
            # Check if user has banned role
            if RoleManager.has_banned_role(after):
                try:
                    # Remove the restricted role
                    await after.remove_roles(restricted_role, reason="User is banned from this role")
                    
                    # Send DM with access denied embed
                    embed = EmbedViews.access_denied_embed()
                    try:
                        await after.send(embed=embed)
                    except discord.Forbidden:
                        # If DM fails, we could log this or send to a mod channel
                        pass
                        
                except discord.Forbidden:
                    # Bot doesn't have permission to remove roles
                    print(f"Failed to remove role from {after.display_name}: Missing permissions")
                except Exception as e:
                    print(f"Error handling role update for {after.display_name}: {e}")
    
    async def _handle_message(self, message: discord.Message):
        """Handle new messages for image reactions and member join stickers"""
        # Check for member join system messages FIRST (before ignoring bot messages)
        if message.guild and message.guild.id == Config.GUILD_ID:
            await self._handle_member_join_message(message)
        
        # Ignore bot messages for regular processing
        if message.author.bot:
            return
        
        # Log message if it starts with command prefix
        if message.content.startswith('R!'):
            logger.info(f"Received command: {message.content} from {message.author.display_name}")
        
        # IMPORTANT: Process commands first for text commands to work
        await self.bot.process_commands(message)
        
        # Only process messages from the configured guild
        if not message.guild or message.guild.id != Config.GUILD_ID:
            return
        
        # Check for positive Ino mentions first (reward good behavior!)
        await self._check_positive_ino_mention(message)
        
        # Check moderation before other processing
        await self._handle_message_moderation(message)
        
        # Check for spam channel flood detection
        await self._check_spam_channel_flood(message)
        
        # Check if message is in help channel
        if message.channel.id == Config.HELP_CHANNEL_ID:
            await self._handle_help_channel_message(message)
            return
        
        # Check if message is in image reaction channels
        if message.channel.id not in Config.IMAGE_REACTION_CHANNELS:
            return
        
        # Check if message has images or videos
        has_image = False
        image_url = None
        is_tenor_gif = False
        is_video = False
        
        # Check for attachments (uploaded images or videos)
        for attachment in message.attachments:
            # Check for video files
            if any(attachment.filename.lower().endswith(ext) for ext in ['.mp4', '.mov', '.webm', '.avi', '.mkv']):
                has_image = True
                is_video = True
                image_url = attachment.url
                break
            # Check for image files (but not GIFs from tenor)
            elif any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                has_image = True
                image_url = attachment.url
                break
        
        # Check for embedded images/videos (links)
        if not has_image:
            for embed in message.embeds:
                # Check if it's a Tenor GIF by looking at the URL
                embed_url = embed.url or ""
                if "tenor.com" in embed_url.lower():
                    is_tenor_gif = True
                
                # Check for video embeds
                if embed.video:
                    has_image = True
                    is_video = True
                    image_url = embed.video.url if hasattr(embed.video, 'url') else str(embed.url)
                    break
                elif embed.image:
                    has_image = True
                    image_url = embed.image.url
                    # Check if the image URL is from Tenor
                    if "tenor.com" in image_url.lower():
                        is_tenor_gif = True
                    break
                elif embed.thumbnail:
                    has_image = True
                    image_url = embed.thumbnail.url
                    # Check if the thumbnail URL is from Tenor
                    if "tenor.com" in image_url.lower():
                        is_tenor_gif = True
                    break
        
        # React with thumbs up and thumbs down if image/video found
        # BUT: Skip reactions for Tenor GIFs (unless it's a video)
        if has_image and image_url and (not is_tenor_gif or is_video):
            try:
                await message.add_reaction('👍')
                await message.add_reaction('👎')
                await message.add_reaction('🔖')  # Bookmark emoji
                content_type = "video" if is_video else "image"
                logger.info(f"Added reactions to {content_type} in {message.channel.name} by {message.author.display_name}")
                
                # Store the image message in MongoDB
                await self.bot.leaderboard_manager.store_image_message(
                    message=message,
                    image_url=image_url,
                    initial_score=0
                )
                
                # Track the image post in leaderboard
                self.bot.leaderboard_manager.add_image_post(
                    user_id=message.author.id,
                    user_name=message.author.display_name,
                    initial_score=0  # Start with 0, will be updated when reactions happen
                )
                
                # Update quest progress and check achievements
                await self._update_quest_progress_and_achievements(message.author, message)
                
                # Reward InoRep for posting images
                await self._apply_image_post_inorep_reward(message)
                
            except discord.Forbidden:
                logger.error(f"Missing permission to add reactions in {message.channel.name}")
            except Exception as e:
                logger.error(f"Error adding reactions to message: {e}")
        elif has_image and is_tenor_gif and not is_video:
            # Log that we're skipping Tenor GIF
            logger.debug(f"Skipped reactions for Tenor GIF in {message.channel.name} by {message.author.display_name}")
            # Still treat as text message for reminder/penalty purposes
            await self._check_for_chat_reminder(message)
            await self._apply_text_spam_inorep_penalty(message)
        else:
            # This is a text message in an image channel, check if we need to send a reminder
            await self._check_for_chat_reminder(message)
            
            # Penalize InoRep for text spamming in image channels
            await self._apply_text_spam_inorep_penalty(message)
    
    async def _check_for_chat_reminder(self, message: discord.Message):
        """Check if the last 10 messages are text messages and send a chat reminder"""
        try:
            # Get the last 10 messages from the channel
            messages = []
            async for msg in message.channel.history(limit=10):
                messages.append(msg)
            
            # Check if all 10 messages are text messages (no images)
            text_message_count = 0
            for msg in messages:
                # Skip bot messages
                if msg.author.bot:
                    continue
                
                # Check if message has images
                has_image = False
                
                # Check for attachments (uploaded images)
                for attachment in msg.attachments:
                    if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                        has_image = True
                        break
                
                # Check for embedded images (links)
                if not has_image:
                    for embed in msg.embeds:
                        if embed.image or embed.thumbnail:
                            has_image = True
                            break
                
                if not has_image and msg.content.strip():  # Text message with content
                    text_message_count += 1
                else:
                    break  # Found an image or empty message, reset count
            
            # If we have 5 consecutive text messages, send a reminder
            if text_message_count >= 5:
                # Check if we recently sent a reminder (to avoid spam)
                recent_bot_messages = []
                async for msg in message.channel.history(limit=20):
                    if msg.author == self.bot.user:
                        recent_bot_messages.append(msg)
                
                # Check if we already sent a chat reminder in the last 20 messages
                for bot_msg in recent_bot_messages:
                    # Check content or embed title/footer for reminder indicators
                    if bot_msg.content and any(keyword in bot_msg.content.lower() for keyword in [
                        "this isn't a chat channel",
                        "wrong channel",
                        "image channel",
                        "save the chat",
                        "this isn't exactly the channel to chat"
                    ]):
                        return  # Already sent a reminder recently
                    
                    # Check embeds for chat reminder
                    if bot_msg.embeds:
                        for embed in bot_msg.embeds:
                            if embed.footer and "Image Channel Reminder" in embed.footer.text:
                                return  # Already sent a reminder recently
                
                # Format chat channel mentions
                chat_mentions = []
                for channel_id in Config.CHAT_CHANNELS:
                    chat_mentions.append(f"<#{channel_id}>")
                
                chat_channels_text = " or ".join(chat_mentions)
                
                # Multiple message variations for variety - kuudere shrine maiden style
                reminder_variations = [
                    f"This channel is for images only.\nConversations belong in {chat_channels_text}.\nPlease relocate there.",
                    
                    f"...You're using the wrong channel.\nThis space is reserved for images.\nFor chatting, use {chat_channels_text}.",
                    
                    f"I must remind you that this is an image channel.\nText discussions should be moved to {chat_channels_text}.\nThank you for your cooperation.",
                    
                    f"Wrong channel.\nImages here. Conversations there: {chat_channels_text}.\nDon't make me repeat this.",
                    
                    f"As a shrine maiden, I must maintain order.\nThis channel is for images only.\nKindly move your conversation to {chat_channels_text}.",
                    
                    f"...This isn't the place for idle chatter.\nImages belong here, your words belong in {chat_channels_text}.\nPlease comply."
                ]
                
                reminder_description = random.choice(reminder_variations)
                
                # Create embed with Ino's annoyed image
                embed = discord.Embed(
                    description=reminder_description,
                    color=0xE8E8E8  # Light gray/white color for shrine maiden aesthetic
                )
                embed.set_image(url="https://i.ibb.co/B2W5WQ2Y/ef4f7402-aa4b-4440-9ae9-ef1415824688.png")
                embed.set_footer(text="Image Channel Reminder • This message will be deleted in 60 seconds")
                
                # Send the reminder and delete after 60 seconds
                reminder_msg = await message.channel.send(embed=embed)
                logger.info(f"Sent chat reminder in #{message.channel.name} after {text_message_count} consecutive text messages")
                
                # Delete after 60 seconds
                await asyncio.sleep(60)
                try:
                    await reminder_msg.delete()
                    logger.info(f"Deleted chat reminder in #{message.channel.name}")
                except discord.NotFound:
                    pass  # Message already deleted
                except discord.Forbidden:
                    logger.warning(f"Missing permission to delete chat reminder in #{message.channel.name}")
                
        except Exception as e:
            logger.error(f"Error checking for chat reminder: {e}")
    
    async def _handle_help_channel_message(self, message: discord.Message):
        """Handle messages in the help channel by creating a thread with resources"""
        try:
            # Skip if this is a reply to another message (likely a response/answer)
            if message.reference and message.reference.message_id:
                logger.debug(f"Skipping reply message from {message.author.display_name}")
                return
            
            # Check if this message actually looks like a help request
            if not self._is_help_request(message.content):
                logger.debug(f"Message from {message.author.display_name} doesn't appear to be a help request: {message.content[:50]}...")
                return
            
            # Check if user already has an active help thread in this channel (from database)
            existing_thread_data = await self.bot.leaderboard_manager.get_user_active_help_thread(
                message.author.id, message.channel.id
            )
            
            if existing_thread_data:
                # Check if the thread still exists and is active
                try:
                    thread_id = int(existing_thread_data['thread_id'])
                    existing_thread = message.guild.get_thread(thread_id)
                    
                    if existing_thread and not existing_thread.archived:
                        # Thread still exists and is active
                        logger.info(f"User {message.author.display_name} already has an active help thread: {existing_thread.name}")
                        try:
                            await message.reply(
                                f"You already have an active help thread: {existing_thread.mention}\n"
                                f"Please continue your discussion there instead of creating a new one.",
                                delete_after=15
                            )
                        except discord.Forbidden:
                            pass
                        return
                    else:
                        # Thread no longer exists or is archived, deactivate in database
                        await self.bot.leaderboard_manager.deactivate_help_thread(thread_id)
                        logger.info(f"Deactivated non-existent help thread {thread_id} for user {message.author.display_name}")
                except ValueError:
                    # Invalid thread ID in database
                    logger.warning(f"Invalid thread ID in database for user {message.author.display_name}: {existing_thread_data['thread_id']}")
                    await self.bot.leaderboard_manager.deactivate_help_thread(int(existing_thread_data['thread_id']))
            
            # Create a new help thread attached to the user's message
            thread_name = f"Help - {message.author.display_name}"
            
            # Create the thread attached to the user's message
            thread = await message.create_thread(
                name=thread_name,
                auto_archive_duration=60,  # Auto-archive after 1 hour for easier closing
                reason=f"Help thread for {message.author.display_name}"
            )
            
            # Store thread information in database
            await self.bot.leaderboard_manager.create_help_thread(
                message.author.id,
                message.author.display_name,
                message.channel.id,
                thread.id,
                thread_name
            )
            
            # Create the help response message
            help_content = f"""Hey {message.author.mention}! 👋

Here are some useful resources to help you:

**📂 Channel with all projects of rayen:**
<#{Config.PROJECTS_CHANNEL_ID}>

**💻 Riko's Code:**
<https://github.com/rayenfeng/riko_project>

**🎬 Rayen's YouTube:**
<https://www.youtube.com/@JustRayen>

<@&{Config.HELP_ROLE_ID}>

💡 **Thread Management:**
• This thread will automatically close after 1 hour of inactivity
• To close it manually, right-click on the thread and select "Archive Thread"
• You can also use the "🔒" button in the thread settings"""
            
            # Send the help message in the thread
            await thread.send(help_content)
            
            # Send a reference message in the original channel linking to the thread
            try:
                await message.reply(
                    f"I've created a help thread for you: {thread.mention}\n"
                    f"Please continue your discussion there!",
                    delete_after=30
                )
            except discord.Forbidden:
                pass
            
            channel_name = getattr(message.channel, 'name', 'Unknown Channel')
            logger.info(f"Created help thread for {message.author.display_name} in #{channel_name} (Thread ID: {thread.id})")
            
        except discord.Forbidden:
            channel_name = getattr(message.channel, 'name', 'Unknown Channel')
            logger.error(f"Missing permission to create thread in #{channel_name}")
        except Exception as e:
            logger.error(f"Error handling help channel message: {e}")

    async def _handle_thread_update(self, before: discord.Thread, after: discord.Thread):
        """Handle thread updates to keep database synchronized"""
        try:
            # Only handle threads in the help channel
            if after.parent_id != Config.HELP_CHANNEL_ID:
                return
            
            # Get thread data from database
            thread_data = await self.bot.leaderboard_manager.get_help_thread_by_id(after.id)
            if not thread_data:
                return
            
            # Update thread name if changed
            if before.name != after.name:
                await self.bot.leaderboard_manager.update_help_thread(
                    after.id,
                    thread_name=after.name
                )
                logger.info(f"Updated help thread name: {before.name} -> {after.name}")
            
            # Update status if archived/unarchived
            if before.archived != after.archived:
                await self.bot.leaderboard_manager.update_help_thread(
                    after.id,
                    is_active=not after.archived
                )
                status = "archived" if after.archived else "unarchived"
                logger.info(f"Help thread {after.id} {status}")
                
        except Exception as e:
            logger.error(f"Error handling thread update: {e}")

    async def _handle_thread_delete(self, thread: discord.Thread):
        """Handle thread deletion to update database"""
        try:
            # Only handle threads in the help channel
            if thread.parent_id != Config.HELP_CHANNEL_ID:
                return
            
            # Deactivate thread in database
            await self.bot.leaderboard_manager.deactivate_help_thread(thread.id)
            logger.info(f"Deactivated deleted help thread {thread.id}")
            
        except Exception as e:
            logger.error(f"Error handling thread delete: {e}")
    
    def _is_help_request(self, content: str) -> bool:
        """Check if a message looks like a genuine help request"""
        content_lower = content.lower().strip()
        
        # Too short messages are probably not help requests
        if len(content_lower) < 15:
            return False
        
        # Exclude messages that are giving help/advice rather than asking for it
        giving_help_indicators = [
            "you can", "you should", "you need to", "you could", "you might",
            "try this", "try using", "try to", "here's how", "here is how",
            "the way to", "what you need", "what you want", "what works",
            "i recommend", "i suggest", "i think you", "you'll want",
            "should work", "will work", "would work", "that'll", "that will",
            "make sure", "just use", "simply use", "all you need",
            "fastest way", "best way", "easier way", "better to"
        ]
        
        for indicator in giving_help_indicators:
            if indicator in content_lower:
                return False
        
        # Exclude messages that end with advice-giving patterns
        if content_lower.endswith(("should help", "will help", "might help", "helps", "works well", "works better")):
            return False
        
        # Strong help request indicators (only check these if not giving help)
        strong_help_keywords = [
            # Direct help requests
            "help me", "need help", "can someone help", "anyone help me",
            "please help", "could someone help", "can anyone help", "help please"
            
            # Problem/issue indicators
            "having trouble", "having issues", "having problems", "having difficulty",
            "stuck on", "confused about", "not sure how", "don't know how", "dont know how",
            "can't figure", "cant figure", "unable to", "doesn't work", "doesnt work",
            "not working", "broken", "error", "issue with", "problem with",
            
            # Question starters
            "how do i", "how can i", "how should i", "how would i",
            "what is", "what are", "what does", "what's the",
            "where is", "where can", "where do", "where should",
            "when should", "when do", "when is",
            "why is", "why does", "why can't", "why wont", "why won't",
            "which is", "which should", "which one",
            
            # Learning/guidance requests
            "teach me", "show me", "explain", "clarify",
            "tutorial", "guide", "walkthrough", "step by step", "instructions",
        ]
        
        # Check for question marks (strong indicator)
        if "?" in content:
            return True
        
        # Check for strong help keywords
        for keyword in strong_help_keywords:
            if keyword in content_lower:
                return True
        
        # Check for sentence patterns that look like questions or requests
        question_starters = ("can i", "could i", "would i", "should i", "is there", "are there", "do i", "does this", "will this")
        if content_lower.startswith(question_starters):
            return True
        
        return False
    
    async def _check_spam_channel_flood(self, message: discord.Message):
        """Check for message flooding in the spam channel"""
        # Specific channel ID for spam detection
        SPAM_CHANNEL_ID = 1373806584748314634
        
        # Only check messages in the specified spam channel
        if message.channel.id != SPAM_CHANNEL_ID:
            return
        
        # Don't count bot messages or webhook messages
        if message.author.bot or message.webhook_id:
            return
        
        # Don't count empty messages
        if not message.content.strip():
            return
        
        try:
            # Increment message count
            self.spam_channel_message_count += 1
            logger.debug(f"Spam channel message count: {self.spam_channel_message_count}")
            
            # Check if we've reached 10 messages
            if self.spam_channel_message_count >= 10:
                # Send the "nap" message with enhanced spelling
                nap_message = "Shut up, people! I'm trying to nap here. I couldn't care less that you're all flooding my spam channel. 😴💤"
                
                await message.channel.send(nap_message)
                logger.info(f"Sent nap message in #{message.channel.name} after {self.spam_channel_message_count} messages")
                
                # Reset counter to prevent spam
                self.spam_channel_message_count = 0
                
        except Exception as e:
            logger.error(f"Error in spam channel flood detection: {e}")
    
    async def _handle_message_delete(self, message: discord.Message):
        """Handle message deletions to clean up image tracking"""
        # Only process messages from image channels
        if not message.guild or message.guild.id != Config.GUILD_ID:
            return
            
        if message.channel.id not in Config.IMAGE_REACTION_CHANNELS:
            return
            
        # Delete the image message from MongoDB if it exists
        await self.bot.leaderboard_manager.delete_image_message(str(message.id))
    
    async def _handle_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Handle command errors"""
        if isinstance(error, commands.CommandNotFound):
            logger.debug(f"Unknown command: {ctx.invoked_with}")
            return
        elif isinstance(error, commands.CheckFailure):
            # This is triggered by our global check that blocks DMs and other guilds
            # The check already sends a message, so just log it
            logger.info(f"Check failed for command {ctx.command.name} by {ctx.author.display_name}")
            return
        elif isinstance(error, commands.MissingPermissions):
            logger.warning(f"Missing permissions for command {ctx.command.name}: {error}")
            await ctx.send("❌ You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, commands.NotOwner):
            logger.warning(f"Non-owner tried to use owner command {ctx.command.name}: {ctx.author}")
            await ctx.send("❌ This command is only available to bot owners.", ephemeral=True)
        else:
            logger.error(f"Command error in {ctx.command.name}: {error}")
            await ctx.send(f"❌ An error occurred: {str(error)}", ephemeral=True)
    
    async def _handle_reaction_change(self, reaction: discord.Reaction, user: discord.User, added: bool):
        """Handle reaction additions and removals for leaderboard tracking and moderation"""
        try:
            # Ignore bot reactions
            if user.bot:
                return
            
            # Basic guild checks
            if not hasattr(reaction.message, 'guild') or not reaction.message.guild:
                return
            
            if reaction.message.guild.id != Config.GUILD_ID:
                return
            
            # Verify the reaction and message still exist (Discord API reliability check)
            if not await self._verify_reaction_exists(reaction, user, added):
                logger.warning(f"⚠️ Reaction verification failed for {user.display_name} {reaction.emoji} on message {reaction.message.id}")
                return
            
            # Note: Moderation is now handled via UI buttons, not reactions
            
            # Handle bookmark reactions FIRST (works in any channel with images)
            emoji_str = str(reaction.emoji)
            logger.info(f"Reaction detected: '{emoji_str}' (repr: {repr(emoji_str)}) by {user.display_name}")
            
            # Check for bookmark emoji (multiple possible variants)
            bookmark_emojis = ['🔖', '📑', '📌', '🏷️']
            if emoji_str in bookmark_emojis:
                logger.info(f"Processing bookmark reaction '{emoji_str}' by {user.display_name}")
                await self._handle_bookmark_reaction(reaction, user, added)
                return
            
            # Only track scoring reactions in designated image channels
            if reaction.message.channel.id not in Config.IMAGE_REACTION_CHANNELS:
                return
            
            # Only track thumbs up and thumbs down for scoring
            if str(reaction.emoji) not in ['👍', '👎']:
                return
            
            # Check if the message has images
            message = reaction.message
            has_image = False
            
            # Check for attachments (uploaded images)
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    has_image = True
                    break
            
            # Check for embedded images (links)
            if not has_image:
                for embed in message.embeds:
                    if embed.image or embed.thumbnail:
                        has_image = True
                        break
            
            if not has_image:
                return
            
            # Calculate score change
            score_change = 0
            if str(reaction.emoji) == '👍':
                score_change = 1 if added else -1
            elif str(reaction.emoji) == '👎':
                score_change = -1 if added else 1
            
            # Track the user reaction
            await self.bot.leaderboard_manager.track_user_reaction(
                user_id=user.id,
                message_id=str(message.id),
                emoji=str(reaction.emoji),
                added=added
            )
            
            # Update the leaderboard for the image author
            if score_change != 0:
                self.bot.leaderboard_manager.update_image_score(
                    user_id=message.author.id,
                    user_name=message.author.display_name,
                    score_change=score_change
                )
                
                # Update the image message score in MongoDB
                # Count actual human reactions, excluding bot reactions
                thumbs_up = 0
                thumbs_down = 0
                
                for r in message.reactions:
                    if str(r.emoji) == '👍':
                        thumbs_up = r.count
                        # Subtract 1 if bot reacted (bot reactions shouldn't count)
                        async for u in r.users():
                            if u.bot:
                                thumbs_up = max(0, thumbs_up - 1)
                                break
                    elif str(r.emoji) == '👎':
                        thumbs_down = r.count
                        # Subtract 1 if bot reacted (bot reactions shouldn't count)
                        async for u in r.users():
                            if u.bot:
                                thumbs_down = max(0, thumbs_down - 1)
                                break
                
                await self.bot.leaderboard_manager.update_image_message_score(
                    message_id=str(message.id),
                    thumbs_up=thumbs_up,
                    thumbs_down=thumbs_down
                )
                
                # Update quest progress for earning likes (for image author)
                if str(reaction.emoji) == '👍' and added:
                    await self._update_quest_progress_likes(message.author, message, thumbs_up)
                
                # Update quest progress for rating images (for the person who reacted)
                # Only track when reaction is ADDED, not removed
                if added:
                    await self._update_quest_progress_rating(user, message)
                    
                    # Update quest progress for giving likes (for the person who reacted)
                    # Only track thumbs up reactions when ADDED
                    if str(reaction.emoji) == '👍':
                        await self._update_quest_progress_giving_likes(user, message)
                
                action = "added" if added else "removed"
                logger.info(f"Reaction {action}: {reaction.emoji} on {message.author.display_name}'s image (score change: {score_change:+d}), thumbs_up: {thumbs_up}, thumbs_down: {thumbs_down}")
        
        except discord.NotFound:
            logger.warning(f"⚠️ Message or reaction not found during processing: {reaction.message.id}")
        except discord.Forbidden:
            logger.warning(f"⚠️ Insufficient permissions to process reaction on message: {reaction.message.id}")
        except discord.HTTPException as e:
            logger.error(f"❌ Discord API error during reaction processing: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error in reaction handling: {e}")
    
    async def _verify_reaction_exists(self, reaction: discord.Reaction, user: discord.User, added: bool) -> bool:
        """Verify that the reaction and message still exist to ensure API reliability"""
        try:
            # Try to fetch the message to ensure it still exists
            message = await reaction.message.channel.fetch_message(reaction.message.id)
            
            # If we're checking for an added reaction, verify the user actually has this reaction
            if added:
                for msg_reaction in message.reactions:
                    if str(msg_reaction.emoji) == str(reaction.emoji):
                        async for reaction_user in msg_reaction.users():
                            if reaction_user.id == user.id:
                                return True
                # If we reach here, the reaction wasn't found
                return False
            else:
                # For removed reactions, we can't verify the absence easily
                # so we trust the event (Discord should be reliable for removals)
                return True
                
        except discord.NotFound:
            # Message or reaction no longer exists
            return False
        except discord.Forbidden:
            # No permission to access the message
            logger.warning(f"⚠️ No permission to verify reaction on message {reaction.message.id}")
            return False
        except Exception as e:
            logger.error(f"❌ Error verifying reaction: {e}")
            return False
    
    async def _handle_bookmark_reaction(self, reaction: discord.Reaction, user: discord.User, added: bool):
        """Handle bookmark emoji reactions"""
        try:
            message = reaction.message
            
            # Check if the message has images
            has_image = False
            
            # Check for attachments (uploaded images)
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    has_image = True
                    break
            
            # Check for embedded images (links)
            if not has_image:
                for embed in message.embeds:
                    if embed.image or embed.thumbnail:
                        has_image = True
                        break
            
            if not has_image:
                return
            
            if added:
                # Add bookmark
                success = await self.bot.leaderboard_manager.add_bookmark(
                    user.id, 
                    str(message.id), 
                    user.display_name
                )
                
                if success:
                    # Send ephemeral confirmation
                    try:
                        embed = discord.Embed(
                            title="🔖 Bookmark Added",
                            description=f"Successfully bookmarked [this image]({message.jump_url})!",
                            color=0x3498db
                        )
                        embed.set_footer(text="Use /bookmarks to view all your bookmarks")
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        # User has DMs disabled, that's okay
                        pass
                    
                    logger.info(f"User {user.display_name} bookmarked message {message.id}")
                else:
                    # Already bookmarked or failed
                    try:
                        embed = discord.Embed(
                            title="📌 Already Bookmarked",
                            description="This image is already in your bookmarks!",
                            color=0xf39c12
                        )
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        pass
            else:
                # Remove bookmark
                success = await self.bot.leaderboard_manager.remove_bookmark(user.id, str(message.id))
                
                if success:
                    try:
                        embed = discord.Embed(
                            title="🗑️ Bookmark Removed",
                            description="Bookmark removed successfully!",
                            color=0xe74c3c
                        )
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        pass
                    
                    logger.info(f"User {user.display_name} removed bookmark for message {message.id}")
                
        except Exception as e:
            logger.error(f"Error handling bookmark reaction: {e}")
    
    def initialize_quest_manager(self):
        """Initialize the quest manager (called from bot.py when ready)"""
        try:
            self.quest_manager = QuestManager()
            logger.info("Quest Manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Quest Manager: {e}")
    
    async def _update_quest_progress_and_achievements(self, user: discord.User, message: discord.Message):
        """Update quest progress and check achievements when user posts an image"""
        if not self.quest_manager:
            return
            
        try:
            # Update quest progress for posting images
            completed_quests = await self.quest_manager.update_quest_progress(
                user_id=user.id,
                quest_type="post_images",
                count=1
            )
            
            # Update posting streak
            post_streak = await self.quest_manager.update_post_streak(user.id)
            logger.info(f"{user.display_name}'s post streak updated: {post_streak} days")
            
            # Send notifications for completed quests
            for quest in completed_quests:
                try:
                    embed = EmbedViews.quest_completed_embed(quest)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    # User has DMs disabled
                    pass
            
            # Check for new achievements (including streak achievements)
            new_achievements = await self.quest_manager.check_achievements(
                user_id=user.id,
                leaderboard_manager=self.bot.leaderboard_manager
            )
            
            # Send notifications for new achievements
            for achievement in new_achievements:
                try:
                    embed = EmbedViews.achievement_earned_embed(achievement)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    # User has DMs disabled
                    pass
            
            # Add to active events as contestant
            await self.quest_manager.add_event_contestant(
                message_id=str(message.id),
                user_id=user.id,
                user_name=user.display_name
            )
            
        except Exception as e:
            logger.error(f"Error updating quest progress and achievements: {e}")
    
    async def _update_quest_progress_likes(self, user: discord.User, message: discord.Message, thumbs_up_count: int):
        """Update quest progress for earning likes"""
        if not self.quest_manager:
            return
            
        try:
            completed_quests = await self.quest_manager.update_quest_progress(
                user_id=user.id,
                quest_type="earn_likes",
                count=1
            )
            
            # Check for "viral_image" quest (15+ likes on a single image)
            if thumbs_up_count >= 15:
                await self.quest_manager.track_viral_image(
                    user_id=user.id,
                    message_id=str(message.id),
                    like_count=thumbs_up_count
            )
            
            # Send notifications for completed quests
            for quest in completed_quests:
                try:
                    embed = EmbedViews.quest_completed_embed(quest)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass
                    
        except Exception as e:
            logger.error(f"Error updating quest progress for likes: {e}")
    
    async def _update_quest_progress_rating(self, user: discord.User, message: discord.Message):
        """Update quest progress for rating images"""
        if not self.quest_manager or user.bot:
            return
            
        try:
            from config import Config
            
            # Update the stat for tracking achievements
            await self.quest_manager.update_user_stat(user.id, "ratings_given", 1)
            
            # Track regular rating quest
            completed_quests = await self.quest_manager.update_quest_progress(
                user_id=user.id,
                quest_type="rate_images",
                count=1
            )
            
            # Track "support_new_users" quest - like images from different users
            # We need to track which unique users they've liked today
            try:
                await self.quest_manager.track_unique_user_like(
                    user_id=user.id,
                    liked_user_id=message.author.id
                )
                logger.debug(f"Tracked unique user like: {user.display_name} liked image from user {message.author.id}")
            except Exception as e:
                logger.error(f"Failed to track unique user like: {e}")
            
            # Track "explore_channels" quest - react in both image channels
            if message.channel.id in Config.IMAGE_REACTION_CHANNELS:
                try:
                    completed = await self.quest_manager.track_channel_exploration(
                        user_id=user.id,
                        channel_id=message.channel.id
                    )
                    if completed:
                        logger.info(f"✅ Channel exploration quest completed for {user.display_name}!")
                    else:
                        logger.info(f"📍 Tracked channel exploration: {user.display_name} reacted in channel {message.channel.id}")
                except Exception as e:
                    logger.error(f"Failed to track channel exploration: {e}")
            
            # Send notifications for completed quests
            for quest in completed_quests:
                try:
                    embed = EmbedViews.quest_completed_embed(quest)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass
                    
        except Exception as e:
            logger.error(f"Error updating quest progress for rating: {e}")
    
    async def _update_quest_progress_giving_likes(self, user: discord.User, message: discord.Message):
        """Update quest progress for giving likes (thumbs up reactions)"""
        if not self.quest_manager or user.bot:
            return
            
        try:
            # Update the stat for tracking achievements
            await self.quest_manager.update_user_stat(user.id, "likes_given", 1)
            
            # Track "give_likes" quest type (e.g., "Positive Vibes Only")
            completed_quests = await self.quest_manager.update_quest_progress(
                user_id=user.id,
                quest_type="give_likes",
                count=1
            )
            
            # Send notifications for completed quests
            for quest in completed_quests:
                try:
                    embed = EmbedViews.quest_completed_embed(quest)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass
                    
        except Exception as e:
            logger.error(f"Error updating quest progress for giving likes: {e}")
    
    async def _handle_message_moderation(self, message: discord.Message):
        """Handle message moderation using AI scanning"""
        try:
            # Skip if moderation manager not available
            if not hasattr(self.bot, 'leaderboard_manager') or not self.bot.leaderboard_manager:
                return
            
            if not hasattr(self.bot.leaderboard_manager, 'moderation_manager') or not self.bot.leaderboard_manager.moderation_manager:
                return
            
            moderation_manager = self.bot.leaderboard_manager.moderation_manager
            
            # Check if moderation is enabled for this guild
            if not await moderation_manager.is_moderation_enabled(str(message.guild.id)):
                return
            
            # Scan the message
            moderation_result = await moderation_manager.scan_message(message)
            
            if not moderation_result:
                return  # No issues found
            
            # Reduce InoRep for flagged content (severity-based penalty)
            await self._apply_moderation_inorep_penalty(message, moderation_result)
            
            # Handle blacklisted content (auto-rejected)
            if moderation_result.get('status') == 'blacklisted':
                await self._handle_blacklisted_content(message, moderation_result)
                return
            
            # Handle content that needs review
            if moderation_result.get('status') == 'pending_review':
                await self._send_moderation_review(message, moderation_result)
            
        except Exception as e:
            logger.error(f"Error in message moderation: {e}")
    
    async def _handle_blacklisted_content(self, message: discord.Message, moderation_result: dict):
        """Handle when blacklisted content is detected"""
        try:
            # Get moderation log channel
            moderation_manager = self.bot.leaderboard_manager.moderation_manager
            log_channel_id = await moderation_manager.get_moderation_log_channel_id(str(message.guild.id))
            
            if log_channel_id:
                log_channel = message.guild.get_channel(log_channel_id)
                if log_channel:
                    from views.embeds import EmbedViews
                    embed = EmbedViews.moderation_blacklisted_content_embed(moderation_result)
                    await log_channel.send(embed=embed)
            
            # Check if self-harm is flagged and send help resources
            categories = moderation_result.get('categories', {})
            if categories.get('self-harm') or categories.get('self_harm') or categories.get('self-harm/intent') or categories.get('self-harm/instructions'):
                await self._send_self_harm_help(message.author)
            
            # Delete the message (if bot has permissions)
            try:
                await message.delete()
                logger.info(f"Deleted blacklisted content from {message.author.display_name}")
                
                # Send notification in channel that auto-deletes after 60 seconds
                notification_embed = discord.Embed(
                    title="🚫 Blacklisted Content",
                    description=f"{message.author.mention}, your message was automatically removed because it matches previously blacklisted content.\n\n"
                              f"This content has been flagged by our moderation team and is not permitted in this server.",
                    color=discord.Color.red()
                )
                notification_embed.set_footer(text="This message will be deleted in 60 seconds")
                
                notification_msg = await message.channel.send(embed=notification_embed)
                
                # Delete notification after 60 seconds
                await asyncio.sleep(60)
                try:
                    await notification_msg.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                    
            except discord.Forbidden:
                logger.warning("Missing permission to delete blacklisted message")
            except discord.NotFound:
                pass  # Message already deleted
            
        except Exception as e:
            logger.error(f"Error handling blacklisted content: {e}")
    
    async def _send_self_harm_help(self, user: discord.User):
        """Send mental health resources to a user who posted self-harm content"""
        try:
            help_embed = discord.Embed(
                title="💚 We're Here to Help",
                description="We noticed your message may indicate you're going through a difficult time. "
                          "Please know that you're not alone, and there are people who care and want to help.",
                color=discord.Color.green()
            )
            
            help_embed.add_field(
                name="🆘 Crisis Resources",
                value="**National Suicide Prevention Lifeline (US)**\n"
                      "📞 Call or text: **988**\n"
                      "💬 Chat: [suicidepreventionlifeline.org/chat](https://suicidepreventionlifeline.org/chat)\n\n"
                      "**Crisis Text Line (US/Canada/UK)**\n"
                      "💬 Text **HOME** to **741741**\n\n"
                      "**International Association for Suicide Prevention**\n"
                      "🌍 [iasp.info/resources/Crisis_Centres](https://www.iasp.info/resources/Crisis_Centres)",
                inline=False
            )
            
            help_embed.add_field(
                name="🤝 Additional Support",
                value="• **r/SuicideWatch** - Reddit support community\n"
                      "• **7 Cups** - [7cups.com](https://www.7cups.com) - Free emotional support\n"
                      "• **BetterHelp** - [betterhelp.com](https://www.betterhelp.com) - Professional counseling",
                inline=False
            )
            
            help_embed.add_field(
                name="💙 You Matter",
                value="Your life has value and meaning. These feelings are temporary, even when they don't feel that way. "
                      "Please reach out to someone who can help - whether it's one of the resources above, a friend, "
                      "family member, or our server's moderation team.",
                inline=False
            )
            
            help_embed.set_footer(text="These resources are confidential and available 24/7")
            
            await user.send(embed=help_embed)
            logger.info(f"Sent mental health resources to {user.display_name}")
            
        except discord.Forbidden:
            logger.warning(f"Could not send mental health resources DM to {user.display_name} (DMs disabled)")
        except Exception as e:
            logger.error(f"Error sending mental health resources: {e}")
    
    async def _send_moderation_review(self, message: discord.Message, moderation_result: dict):
        """Send moderation review request to staff with UI buttons"""
        try:
            from views.embeds import EmbedViews
            moderation_manager = self.bot.leaderboard_manager.moderation_manager
            
            # Get review role
            review_role_id = await moderation_manager.get_review_role_id(str(message.guild.id))
            if not review_role_id:
                # Use default review role from config
                from config import Config
                review_role_id = Config.DEFAULT_MODERATION_REVIEW_ROLE_ID
            
            # Get moderation log channel
            log_channel_id = await moderation_manager.get_moderation_log_channel_id(str(message.guild.id))
            if not log_channel_id:
                logger.warning("Moderation log channel not configured, cannot send review request")
                return
            
            log_channel = message.guild.get_channel(log_channel_id)
            if not log_channel:
                logger.warning(f"Moderation log channel {log_channel_id} not found")
                return
            
            # Create review embed with enhanced information
            embed = EmbedViews.moderation_flagged_embed(moderation_result)
            
            # Add voting information to the embed
            embed.add_field(
                name="🗳️ Voting System", 
                value="• **2+ Whitelist votes** = Auto-approve (unless majority blacklist)\n"
                      "• **Majority Blacklist** = Auto-reject\n"
                      "• **Tie with 4+ votes** = Admin intervention required\n"
                      "• **Admins** can use `/overrule` to override any decision", 
                inline=False
            )
            
            # Create moderation view with buttons
            if hasattr(self.bot, 'moderation_view_manager') and self.bot.moderation_view_manager:
                view = self.bot.moderation_view_manager.create_view(
                    moderation_result['message_id'], 
                    moderation_result
                )
            else:
                logger.error("Moderation view manager not available")
                return
            
            # Send with role ping and interactive buttons
            content = f"<@&{review_role_id}> 🚨 **Content Flagged for Review**\n" \
                     f"**Author:** <@{moderation_result['author_id']}> • **Channel:** <#{moderation_result['channel_id']}>"
            
            # Send the review request with buttons
            review_message = await log_channel.send(content=content, embed=embed, view=view)
            
            # Store the review message ID in the moderation log for future editing
            await moderation_manager.update_moderation_log(
                moderation_result['message_id'], 
                {"review_message_id": str(review_message.id), "review_channel_id": str(log_channel.id)}
            )
            
            # Check if self-harm is flagged and send help resources
            categories = moderation_result.get('categories', {})
            if categories.get('self-harm') or categories.get('self_harm') or categories.get('self-harm/intent') or categories.get('self-harm/instructions'):
                await self._send_self_harm_help(message.author)
            
            # Delete the original message only if confidence is 75% or higher
            should_delete = moderation_result.get('should_delete', False)
            if should_delete:
                try:
                    await message.delete()
                    logger.info(f"Deleted flagged message from {message.author.display_name} (confidence >= 75%)")
                    
                    # Send notification in channel that auto-deletes after 60 seconds
                    severity = moderation_result.get('severity', 'high')
                    notification_embed = discord.Embed(
                        title="🛡️ Content Moderation",
                        description=f"{message.author.mention}, your message was automatically removed by our AI moderation system and will be reviewed by our moderation team.\n\n"
                                  f"If you believe this was done in error, please wait for a moderator to review your message. They may restore it if appropriate.",
                        color=discord.Color.orange()
                    )
                    notification_embed.set_footer(text="This message will be deleted in 60 seconds")
                    
                    notification_msg = await message.channel.send(embed=notification_embed)
                    
                    # Delete notification after 60 seconds
                    await asyncio.sleep(60)
                    try:
                        await notification_msg.delete()
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    
                except discord.Forbidden:
                    logger.warning("Missing permission to delete flagged message")
                except discord.NotFound:
                    pass  # Message already deleted
            else:
                logger.info(f"Message flagged but not deleted (confidence 50-75%) from {message.author.display_name}")
            
            logger.info(f"Sent moderation review request with UI buttons for message from {message.author.display_name}")
            
        except Exception as e:
            logger.error(f"Error sending moderation review: {e}")
    
    # Old reaction-based moderation system has been replaced with UI buttons
    # See views/moderation_view.py for the new interactive moderation system
    
    async def _apply_moderation_inorep_penalty(self, message: discord.Message, moderation_result: dict):
        """Apply InoRep penalty based on moderation severity"""
        try:
            # Check if InoRep manager is available
            if not hasattr(self.bot.leaderboard_manager, 'inorep_manager') or not self.bot.leaderboard_manager.inorep_manager:
                return
            
            inorep_manager = self.bot.leaderboard_manager.inorep_manager
            
            # Determine penalty based on severity and detection method
            severity = moderation_result.get('severity', 'medium')
            detection_method = moderation_result.get('detection_method', 'ai')
            pattern_reason = moderation_result.get('pattern_reason', '')
            max_confidence = moderation_result.get('max_confidence', 0.5)
            
            # Severity-based penalties
            if detection_method == 'pattern_matching':
                # Pattern-matched content (slurs, extreme harm) - harsh penalty
                penalty = -10
                reason = f"Severe violation detected: {pattern_reason}"
            elif severity == "high":
                # High severity (75%+ confidence, will be deleted)
                penalty = -5
                reason = f"Harmful content flagged ({max_confidence:.0%} confidence)"
            else:  # medium severity (50-75%)
                # Medium severity (flagged for review only)
                penalty = -2
                reason = f"Content flagged for review ({max_confidence:.0%} confidence)"
            
            # Apply the penalty
            await inorep_manager.add_rep(
                user_id=str(message.author.id),
                guild_id=str(message.guild.id),
                user_name=message.author.display_name,
                amount=penalty,
                reason=reason,
                moderator_id="0",  # System action
                moderator_name="Ino's Moderation System"
            )
            
            logger.info(f"Applied InoRep penalty ({penalty}) to {message.author.display_name} for {reason}")
            
        except Exception as e:
            logger.error(f"Error applying InoRep penalty: {e}")
    
    async def _check_positive_ino_mention(self, message: discord.Message) -> bool:
        """
        Check if message contains positive mentions of Ino
        Returns True if positive mention detected
        """
        try:
            content_lower = message.content.lower()
            
            # Expanded positive keywords/phrases about Ino (40+ variations)
            positive_patterns = [
                # Direct compliments (Tier 1 - High praise)
                ('ino is the best', +4),
                ('ino is perfect', +4),
                ('ino best girl', +4),
                ('love you ino', +4),
                ('ino is my favorite', +4),
                ('ino is incredible', +4),
                ('ino is flawless', +4),
                ('ino is outstanding', +4),
                ('ino is exceptional', +4),
                ('ino is phenomenal', +4),
                
                # Direct compliments (Tier 2 - Strong praise)
                ('ino is cute', +3),
                ('ino is adorable', +3),
                ('ino is great', +3),
                ('ino is amazing', +3),
                ('ino is awesome', +3),
                ('ino is wonderful', +3),
                ('ino is beautiful', +3),
                ('ino is pretty', +3),
                ('ino is sweet', +3),
                ('ino is lovely', +3),
                ('ino is fantastic', +3),
                ('ino is brilliant', +3),
                ('ino is gorgeous', +3),
                ('ino is stunning', +3),
                ('ino is charming', +3),
                ('ino is elegant', +3),
                ('ino is graceful', +3),
                ('ino is precious', +3),
                ('ino is delightful', +3),
                ('ino is magnificent', +3),
                ('love ino', +3),
                ('ino best bot', +3),
                ('ino waifu', +3),
                ('ino best waifu', +3),
                ('ino queen', +3),
                ('ino goddess', +3),
                ('ino is life', +3),
                ('ino is love', +3),
                
                # Appreciation (Tier 3 - Gratitude)
                ('appreciate you ino', +3),
                ('you\'re the best ino', +3),
                ('thank you ino', +2),
                ('thanks ino', +2),
                ('appreciate ino', +2),
                ('grateful for ino', +2),
                ('ino you\'re great', +2),
                ('ino you\'re amazing', +2),
                ('ino you\'re awesome', +2),
                ('blessed by ino', +2),
                ('ino saves the day', +2),
                ('ino always helps', +2),
                ('ino never disappoints', +2),
                
                # General positive (Tier 4 - Encouragement)
                ('good job ino', +2),
                ('well done ino', +2),
                ('nice work ino', +2),
                ('proud of ino', +2),
                ('ino rocks', +2),
                ('ino slays', +2),
                ('ino is helpful', +2),
                ('ino is kind', +2),
                ('ino is nice', +2),
                ('ino is cool', +2),
                ('ino is smart', +2),
                ('ino is reliable', +2),
                ('ino is trustworthy', +2),
                ('ino deserves praise', +2),
                ('ino doing great', +2),
                ('keep it up ino', +2),
                
                # Affectionate (Tier 5 - Extra cute)
                ('headpat ino', +2),
                ('pat pat ino', +2),
                ('hug ino', +2),
                ('protecc ino', +2),
                ('ino deserves headpats', +2),
                ('good girl ino', +2),
                ('ino kawaii', +3),
                ('ino chan', +2),
                ('ino sama', +2),
                ('ino senpai', +2),
            ]
            
            # Check negative patterns first (to prevent abuse)
            negative_patterns = [
                # Strong insults (Tier 1 - Severe)
                ('ino is trash', -5),
                ('ino is garbage', -5),
                ('ino is useless', -5),
                ('ino is terrible', -5),
                ('ino is awful', -5),
                ('ino is horrible', -5),
                ('ino is stupid', -5),
                ('ino is dumb', -5),
                ('ino is worthless', -5),
                ('ino is pathetic', -5),
                ('hate ino', -5),
                ('ino sucks', -5),
                ('ino worst', -5),
                ('ino is annoying', -4),
                ('ino is irritating', -4),
                ('ino is cringe', -4),
                
                # Medium insults (Tier 2 - Moderate)
                ('ino is bad', -3),
                ('ino is lame', -3),
                ('ino is boring', -3),
                ('ino is weak', -3),
                ('ino is slow', -3),
                ('ino is broken', -3),
                ('ino doesn\'t work', -3),
                ('ino is buggy', -3),
                ('ino is glitchy', -3),
                ('ino is laggy', -3),
                ('dislike ino', -3),
                ('ino is ugly', -4),
                ('ino is disgusting', -4),
                ('ino is gross', -3),
                
                # Light insults (Tier 3 - Minor)
                ('ino is meh', -2),
                ('ino is okay', -1),
                ('ino is mid', -2),
                ('ino is overrated', -3),
                ('ino could be better', -1),
                ('ino needs work', -1),
                ('ino is confusing', -2),
                ('ino is complicated', -1),
                
                # Dismissive (Tier 4 - Rude)
                ('shut up ino', -4),
                ('stfu ino', -5),
                ('go away ino', -3),
                ('nobody cares ino', -4),
                ('nobody asked ino', -4),
                ('ino be quiet', -3),
                ('ino stop', -2),
                ('ignore ino', -2),
                ('mute ino', -3),
                ('delete ino', -4),
                ('remove ino', -3),
                ('kick ino', -4),
                ('ban ino', -4),
                
                # Comparative insults (Tier 5 - Comparison)
                ('ino worst bot', -4),
                ('ino worst girl', -5),
                ('ino worst waifu', -5),
                ('other bots better', -3),
                ('prefer other bots', -2),
                ('ino not good as', -2),
                ('ino inferior', -3),
                
                # Disrespectful (Tier 6 - Condescending)
                ('ino is disappointing', -3),
                ('expected better ino', -2),
                ('ino let me down', -2),
                ('ino failed', -2),
                ('ino embarrassing', -3),
                ('ino is shameful', -3),
                ('ino is a joke', -4),
                ('ino is a meme', -3),
                ('ino clown', -4),
            ]
            
            # Check negative patterns first
            for pattern, penalty in negative_patterns:
                if pattern in content_lower:
                    # Apply InoRep penalty
                    if hasattr(self.bot.leaderboard_manager, 'inorep_manager'):
                        inorep_manager = self.bot.leaderboard_manager.inorep_manager
                        await inorep_manager.add_rep(
                            user_id=str(message.author.id),
                            guild_id=str(message.guild.id),
                            user_name=message.author.display_name,
                            amount=penalty,
                            reason=f"Said something mean about Ino: '{pattern}'",
                            moderator_id="0",
                            moderator_name="Ino"
                        )
                        logger.info(f"{message.author.display_name} lost {abs(penalty)} InoRep for negative mention: '{pattern}'")
                    return True
            
            # Then check positive patterns
            for pattern, reward in positive_patterns:
                if pattern in content_lower:
                    # Apply InoRep reward
                    if hasattr(self.bot.leaderboard_manager, 'inorep_manager'):
                        inorep_manager = self.bot.leaderboard_manager.inorep_manager
                        await inorep_manager.add_rep(
                            user_id=str(message.author.id),
                            guild_id=str(message.guild.id),
                            user_name=message.author.display_name,
                            amount=reward,
                            reason=f"Said something nice about Ino: '{pattern}'",
                            moderator_id="0",
                            moderator_name="Ino"
                        )
                        logger.info(f"{message.author.display_name} gained {reward} InoRep for positive mention: '{pattern}'")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking positive Ino mention: {e}")
            return False
    
    async def _apply_image_post_inorep_reward(self, message: discord.Message):
        """Reward users for posting images in image channels"""
        try:
            # Check if InoRep manager is available
            if not hasattr(self.bot.leaderboard_manager, 'inorep_manager') or not self.bot.leaderboard_manager.inorep_manager:
                return
            
            from config import Config
            
            # Only reward in image channels
            if message.channel.id not in Config.IMAGE_REACTION_CHANNELS:
                return
            
            # Check if message has images
            has_image = False
            
            # Check for attachments
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    has_image = True
                    break
            
            # Check for embeds with images
            if not has_image:
                for embed in message.embeds:
                    if embed.image or embed.thumbnail:
                        has_image = True
                        break
            
            if has_image:
                inorep_manager = self.bot.leaderboard_manager.inorep_manager
                
                # Reward for posting image
                reward = +6
                
                await inorep_manager.add_rep(
                    user_id=str(message.author.id),
                    guild_id=str(message.guild.id),
                    user_name=message.author.display_name,
                    amount=reward,
                    reason="Posted an image in image channel",
                    moderator_id="0",
                    moderator_name="Ino"
                )
                
                logger.info(f"{message.author.display_name} gained {reward} InoRep for posting image")
            
        except Exception as e:
            logger.error(f"Error applying image post InoRep reward: {e}") 
    
    async def _apply_text_spam_inorep_penalty(self, message: discord.Message):
        """Penalize users for sending text messages in image-only channels (-5 per message)"""
        try:
            # Check if InoRep manager is available
            if not hasattr(self.bot.leaderboard_manager, 'inorep_manager') or not self.bot.leaderboard_manager.inorep_manager:
                return
            
            from config import Config
            
            # Only penalize in image channels
            if message.channel.id not in Config.IMAGE_REACTION_CHANNELS:
                return
            
            # Don't penalize empty messages or commands
            if not message.content or len(message.content.strip()) == 0:
                return  # Empty messages don't get penalized
            
            # Don't penalize bot commands
            if message.content.startswith(getattr(Config, 'COMMAND_PREFIX', 'R!')) or message.content.startswith('/'):
                return
            
            # Don't penalize replies to messages with images (unless they insult Ino)
            if message.reference and message.reference.message_id:
                try:
                    # Fetch the referenced message
                    referenced_msg = await message.channel.fetch_message(message.reference.message_id)
                    
                    # Check if the referenced message has images
                    has_image = False
                    for attachment in referenced_msg.attachments:
                        if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                            has_image = True
                            break
                    
                    if not has_image:
                        for embed in referenced_msg.embeds:
                            if embed.image or embed.thumbnail:
                                has_image = True
                                break
                    
                    # If replying to an image, don't penalize (unless insulting Ino, which is handled separately)
                    if has_image:
                        return
                except:
                    pass  # If we can't fetch the message, continue with penalty
            
            inorep_manager = self.bot.leaderboard_manager.inorep_manager
            
            # Penalty for text spamming in image channel
            penalty = -5
            
            await inorep_manager.add_rep(
                user_id=str(message.author.id),
                guild_id=str(message.guild.id),
                user_name=message.author.display_name,
                amount=penalty,
                reason="Chatting in image-only channel (not allowed)",
                moderator_id="0",
                moderator_name="Ino"
            )
            
            logger.info(f"{message.author.display_name} lost {abs(penalty)} InoRep for chatting in image channel")
            
        except Exception as e:
            logger.error(f"Error applying text spam InoRep penalty: {e}")