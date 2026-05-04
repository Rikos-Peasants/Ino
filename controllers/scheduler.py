import discord
from discord.ext import commands, tasks
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Union, Any
from config import Config
from views.embeds import EmbedViews

logger = logging.getLogger(__name__)

class ImageMessage:
    """Wrapper class for image messages to work with embed views"""
    def __init__(self, data: dict):
        self.id = int(data['message_id'])
        self.channel: Optional[discord.abc.GuildChannel] = None
        self.author: Optional[Union[discord.User, 'DummyUser']] = None
        self.created_at = data['created_at']
        self.jump_url = data['jump_url']
        self.attachments = []
        self.embeds = []

class DummyUser:
    """Dummy user class for when user is not found"""
    def __init__(self, name: str):
        self.display_name = name
        self.display_avatar = None

class SchedulerController:
    """Controller for handling scheduled tasks like best image posts"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    def start_tasks(self):
        """Start all scheduled tasks"""
        logger.info("Starting scheduled tasks...")
        
        # Start all tasks (only if not already running)
        if not self.weekly_best_image.is_running():
            self.weekly_best_image.start()
        
        if not self.monthly_best_image.is_running():
            self.monthly_best_image.start()
        
        if not self.yearly_best_image.is_running():
            self.yearly_best_image.start()
        
        if not self.check_expired_events.is_running():
            self.check_expired_events.start()
        
        if not self.check_streaks.is_running():
            self.check_streaks.start()
        
        if not self.check_youtube_videos.is_running():
            self.check_youtube_videos.start()
            
        if not self.check_twitch_streams.is_running():
            self.check_twitch_streams.start()

        if not self.store_youtube_subscriber_count.is_running():
            self.store_youtube_subscriber_count.start()
        
        if not self.check_historical_reactions.is_running():
            self.check_historical_reactions.start()
        
        if not self.check_art_challenges.is_running():
            self.check_art_challenges.start()
        
        if not self.check_duel_challenges.is_running():
            self.check_duel_challenges.start()
        
        if not self.check_custom_roles.is_running():
            self.check_custom_roles.start()
        
        if not self.check_debuffs.is_running():
            self.check_debuffs.start()
    
    def stop_tasks(self):
        """Stop all scheduled tasks"""
        logger.info("Stopping scheduled tasks...")
        
        # Stop all tasks
        if self.weekly_best_image.is_running():
            self.weekly_best_image.cancel()
        
        if self.monthly_best_image.is_running():
            self.monthly_best_image.cancel()
        
        if self.yearly_best_image.is_running():
            self.yearly_best_image.cancel()
        
        if self.check_expired_events.is_running():
            self.check_expired_events.cancel()
        
        if self.check_streaks.is_running():
            self.check_streaks.cancel()
        
        if self.check_youtube_videos.is_running():
            self.check_youtube_videos.cancel()
            
        if self.check_twitch_streams.is_running():
            self.check_twitch_streams.cancel()

        if self.store_youtube_subscriber_count.is_running():
            self.store_youtube_subscriber_count.cancel()
        
        if self.check_historical_reactions.is_running():
            self.check_historical_reactions.cancel()
        
        if self.check_art_challenges.is_running():
            self.check_art_challenges.cancel()
        
        if self.check_duel_challenges.is_running():
            self.check_duel_challenges.cancel()
        
        if self.check_custom_roles.is_running():
            self.check_custom_roles.cancel()
        
        if self.check_debuffs.is_running():
            self.check_debuffs.cancel()
    
    @tasks.loop(hours=24)  # Check daily
    async def weekly_best_image(self):
        """Post the best image of the week every Sunday"""
        try:
            now = datetime.now()
            logger.debug(f"Weekly best image task check: {now.strftime('%A %Y-%m-%d %H:%M')} (weekday: {now.weekday()}, hour: {now.hour})")
            
            # Check if it's Sunday (weekday 6) AND it's around midnight to avoid running multiple times
            if now.weekday() == 6 and now.hour == 0:  # Sunday at midnight
                logger.info("✅ Starting weekly best image selection...")
                
                # Get the date range for the PREVIOUS complete week (Monday to Sunday)
                # Sunday is the end of the week, so we want last Monday to last Sunday
                end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)  # Start of today (Sunday)
                start_date = end_date - timedelta(days=6)  # Monday of last week
                
                logger.info(f"Looking for best images from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
                
                await self._post_best_image("week", start_date, end_date)
            else:
                logger.debug(f"⏭️ Skipping weekly best image - not Sunday at midnight (current: {now.strftime('%A %H:%M')})")
                
        except Exception as e:
            logger.error(f"Error in weekly best image task: {e}")
    
    @tasks.loop(hours=24)  # Check daily
    async def monthly_best_image(self):
        """Post the best image of the month on the first day of each month"""
        try:
            now = datetime.now()
            # Check if it's the first day of the month AND it's around midnight
            if now.day == 1 and now.hour == 0:
                logger.info("Starting monthly best image selection...")
                
                # Get the date range for the PREVIOUS complete month
                end_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)  # Start of current month
                
                # Go back to the first day of last month
                if now.month == 1:
                    start_date = now.replace(year=now.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
                else:
                    start_date = now.replace(month=now.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
                
                logger.info(f"Looking for best images from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
                
                await self._post_best_image("month", start_date, end_date)
                
        except Exception as e:
            logger.error(f"Error in monthly best image task: {e}")
    
    @tasks.loop(hours=24)  # Check daily
    async def yearly_best_image(self):
        """Post the best image of the year on the first day of January"""
        try:
            now = datetime.now()
            # Check if it's the first day of January AND it's around midnight
            if now.month == 1 and now.day == 1 and now.hour == 0:
                logger.info("Starting yearly best image selection...")
                
                # Get the date range for the PREVIOUS complete year
                end_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)  # Start of current year
                start_date = now.replace(year=now.year-1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)  # Start of previous year
                
                logger.info(f"Looking for best images from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
                
                await self._post_best_image("year", start_date, end_date)
                
        except Exception as e:
            logger.error(f"Error in yearly best image task: {e}")
    
    async def _post_best_image(self, period: str, start_date: datetime, end_date: datetime):
        """Find and post the best image for the given period"""
        try:
            guild = self.bot.get_guild(Config.GUILD_ID)
            if not guild:
                logger.error(f"Could not find guild {Config.GUILD_ID}")
                return
            
            logger.info(f"Finding best {period} image from {start_date.strftime('%Y-%m-%d %H:%M')} to {end_date.strftime('%Y-%m-%d %H:%M')}")
            
            # Get leaderboard manager
            leaderboard_manager = getattr(self.bot, 'leaderboard_manager', None)
            if not leaderboard_manager:
                logger.error("Leaderboard manager not available")
                return
            
            # Find the best image from each channel separately
            for channel_id in Config.IMAGE_REACTION_CHANNELS:
                channel = guild.get_channel(channel_id)
                if not channel:
                    logger.warning(f"Could not find channel {channel_id}")
                    continue
                
                # Check if channel is a messageable channel
                if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
                    logger.warning(f"Channel {channel_id} is not a messageable channel")
                    continue
                
                logger.info(f"Finding best image in #{channel.name} (ID: {channel_id}) for {period}")
                
                # Get the best image from MongoDB
                if hasattr(leaderboard_manager, 'get_best_image'):
                    best_image = await leaderboard_manager.get_best_image(
                        channel_id=str(channel_id),
                        start_date=start_date,
                        end_date=end_date
                    )
                else:
                    logger.error("get_best_image method not available on leaderboard manager")
                    continue
                
                if not best_image:
                    logger.info(f"No images found for {period}ly best image in #{channel.name}")
                    # Post a "no winner" message in this channel
                    embed = EmbedViews.no_winner_embed(period)
                    embed.add_field(
                        name="📍 Channel",
                        value=f"#{channel.name}",
                        inline=False
                    )
                    embed.add_field(
                        name="🔍 Search Period",
                        value=f"From {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}",
                        inline=False
                    )
                    await channel.send(embed=embed)
                    continue
                
                logger.info(f"Found winning image in #{channel.name}: {best_image['author_name']} with score {best_image['score']}")
                
                # Create message object
                message = ImageMessage(best_image)
                message.channel = channel
                
                # Get the author
                try:
                    user = await self.bot.fetch_user(int(best_image['author_id']))
                    message.author = user
                    logger.info(f"Found author: {user.display_name}")
                except Exception as e:
                    logger.warning(f"Could not fetch user {best_image['author_id']}: {e}")
                    # If user not found, create a dummy user
                    message.author = DummyUser(best_image['author_name'])
                
                # Create and post the winning image embed using custom embed creation
                # Since we don't have the actual Discord message, create a custom embed
                embed = discord.Embed(
                    title=f"{'🥇' if period == 'week' else '👑' if period == 'month' else '🏆'} Best Image of the {period.title()}!",
                    description=f"Congratulations to **{best_image['author_name']}** for the most upvoted image!\n\n"
                               f"**Net Score:** {best_image['score']} upvotes (👍 - 👎)\n"
                               f"**Channel:** #{channel.name}\n"
                               f"**Posted:** {best_image['created_at'].strftime('%B %d, %Y')}",
                    color=discord.Color.gold() if period == 'week' else discord.Color.purple() if period == 'month' else discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                
                # Add the image URL from our database
                embed.set_image(url=best_image['image_url'])
                
                embed.add_field(
                    name="🏆 Winner in this Channel",
                    value=f"Most upvoted image in #{channel.name}",
                    inline=False
                )
                
                # Add reaction counts
                embed.add_field(
                    name="👍 Upvotes",
                    value=str(best_image['thumbs_up']),
                    inline=True
                )
                embed.add_field(
                    name="👎 Downvotes",
                    value=str(best_image['thumbs_down']),
                    inline=True
                )
                
                # Add search period info
                embed.add_field(
                    name="🔍 Search Period",
                    value=f"From {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}",
                    inline=False
                )
                
                logger.info(f"Posting winning image embed in #{channel.name}")
                await channel.send(embed=embed)
                
                # Award achievement if quest manager is available
                events_controller = getattr(self.bot, 'events_controller', None)
                if events_controller and hasattr(events_controller, 'quest_manager') and events_controller.quest_manager:
                    try:
                        author_id = int(best_image['author_id'])
                        achievement = await events_controller.quest_manager.award_competition_achievement(
                            user_id=author_id,
                            user_name=best_image['author_name'],
                            competition_type=period
                        )
                        if achievement:
                            try:
                                author = await self.bot.fetch_user(author_id)
                                embed_achievement = EmbedViews.achievement_earned_embed(achievement)
                                await author.send(embed=embed_achievement)
                            except discord.Forbidden:
                                pass
                            except Exception as e:
                                logger.error(f"Error sending achievement DM: {e}")
                    except Exception as e:
                        logger.error(f"Error awarding achievement: {e}")
                
                logger.info(f"Posted {period}ly best image in #{channel.name} by {best_image['author_name']} with {best_image['score']} net upvotes")
                
        except Exception as e:
            logger.error(f"Error posting {period}ly best image: {e}")
    
    @weekly_best_image.before_loop
    async def before_weekly_task(self):
        """Wait until the bot is ready before starting weekly task"""
        await self.bot.wait_until_ready()
        # Add a small delay to prevent immediate execution on startup
        import asyncio
        await asyncio.sleep(60)  # Wait 1 minute after bot is ready
    
    @monthly_best_image.before_loop
    async def before_monthly_task(self):
        """Wait until the bot is ready before starting monthly task"""
        await self.bot.wait_until_ready()
        # Add a small delay to prevent immediate execution on startup
        import asyncio
        await asyncio.sleep(60)  # Wait 1 minute after bot is ready
    
    @tasks.loop(hours=1)  # Check every hour
    async def check_expired_events(self):
        """Check for expired events and automatically end them"""
        try:
            # Check if quest manager is available
            events_controller = getattr(self.bot, 'events_controller', None)
            if not events_controller or not hasattr(events_controller, 'quest_manager') or not events_controller.quest_manager:
                return
            
            quest_manager = events_controller.quest_manager
            now = datetime.now()
            
            # Find events that have expired but are still active
            expired_events = list(quest_manager.events_collection.find({
                "is_active": True,
                "end_date": {"$lt": now}
            }))
            
            for event in expired_events:
                logger.info(f"Auto-ending expired event: {event['name']}")
                
                # End the event
                leaderboard_manager = getattr(self.bot, 'leaderboard_manager', None)
                if leaderboard_manager:
                    result = await quest_manager.end_event(
                        event_id=str(event['_id']),
                        leaderboard_manager=leaderboard_manager
                    )
                
                    if result:
                        # Find a channel to announce the winner
                        guild = self.bot.get_guild(Config.GUILD_ID)
                        if guild:
                            # Try to use the first image channel for announcements
                            for channel_id in Config.IMAGE_REACTION_CHANNELS:
                                channel = guild.get_channel(channel_id)
                                if channel and isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
                                    embed = EmbedViews.event_winner_embed(result['event'], result['winner'])
                                    await channel.send(embed=embed)
                                    break
                        
                        logger.info(f"Successfully ended expired event: {event['name']}")
                    else:
                        logger.error(f"Failed to end expired event: {event['name']}")
                    
        except Exception as e:
            logger.error(f"Error checking expired events: {e}")

    @yearly_best_image.before_loop
    async def before_yearly_task(self):
        """Wait until the bot is ready before starting yearly task"""
        await self.bot.wait_until_ready()
        # Add a small delay to prevent immediate execution on startup
        import asyncio
        await asyncio.sleep(60)  # Wait 1 minute after bot is ready
    
    @check_expired_events.before_loop
    async def before_expired_events_task(self):
        """Wait until the bot is ready before starting expired events task"""
        await self.bot.wait_until_ready()
    
    @tasks.loop(hours=24)  # Check daily at midnight
    async def check_streaks(self):
        """Check and update user streaks daily"""
        try:
            now = datetime.now()
            
            # Only run at midnight (between 00:00 and 01:00) to avoid running on startup
            if not (0 <= now.hour < 1):
                logger.debug(f"Skipping streak check - not midnight (current hour: {now.hour})")
                return
            
            # Check if quest manager is available
            events_controller = getattr(self.bot, 'events_controller', None)
            if not events_controller or not hasattr(events_controller, 'quest_manager') or not events_controller.quest_manager:
                return
            
            quest_manager = events_controller.quest_manager
            
            # Check for broken streaks
            await quest_manager.check_and_break_streaks()
            logger.info("Daily streak check completed at midnight")
            
        except Exception as e:
            logger.error(f"Error in daily streak check: {e}")
    
    @check_streaks.before_loop
    async def before_streaks_task(self):
        """Wait until the bot is ready and then wait until midnight before starting streaks task"""
        await self.bot.wait_until_ready()
        
        # Wait until the next midnight to start the streak checking
        now = datetime.now()
        next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        wait_seconds = (next_midnight - now).total_seconds()
        
        logger.info(f"Streak checker will start at next midnight ({next_midnight.strftime('%Y-%m-%d %H:%M:%S')})")
        logger.info(f"Waiting {wait_seconds/3600:.1f} hours until midnight...")
        
        await asyncio.sleep(wait_seconds)
    
    @tasks.loop(minutes=1)  # Check every minute for new videos
    async def check_youtube_videos(self):
        """Check for new YouTube videos and announce them"""
        logger.info("Checking for new YouTube videos...")
        
        try:
            # Use the bot's YouTube monitor instance
            youtube_monitor = getattr(self.bot, 'youtube_monitor', None)
            if not youtube_monitor:
                logger.warning("YouTube monitor not available on bot instance")
                return
            
            # Load monitored channels (this is safe to call repeatedly)
            await youtube_monitor.load_monitored_channels()
            
            # Log how many channels we're monitoring
            channel_count = len(youtube_monitor.monitored_channels)
            logger.info(f"Monitoring {channel_count} YouTube channels")
            
            if channel_count == 0:
                logger.debug("No channels to monitor")
                return
            
            new_videos = await youtube_monitor.check_for_new_videos()
            
            if new_videos:
                logger.info(f"🎬 Found {len(new_videos)} new videos to announce")
                for video in new_videos:
                    try:
                        await youtube_monitor.announce_video(video)
                        # Mark video as processed only after successful announcement
                        await youtube_monitor.mark_video_processed(video['id'])
                        logger.info(f"✅ Announced video: {video.get('title', 'Unknown')}")
                    except Exception as e:
                        logger.error(f"❌ Failed to announce video {video.get('title', 'Unknown')}: {e}")
                        # Don't mark as processed if announcement failed, so it will be retried
            else:
                logger.debug("No new videos found")
                
        except Exception as e:
            logger.error(f"Error in YouTube video checking task: {e}")
    
    @check_youtube_videos.before_loop
    async def before_youtube_videos_task(self):
        """Wait for bot to be ready before starting YouTube monitoring"""
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def check_twitch_streams(self):
        """Check for new Twitch streams and announce them"""
        logger.info("Checking for live Twitch streams...")
        
        try:
            twitch_monitor = getattr(self.bot, 'twitch_monitor', None)
            if not twitch_monitor:
                logger.warning("Twitch monitor not available on bot instance")
                return
            
            await twitch_monitor.load_monitored_channels()
            
            channel_count = len(twitch_monitor.monitored_channels)
            logger.debug(f"Monitoring {channel_count} Twitch channels")
            
            if channel_count == 0:
                return
            
            new_streams = await twitch_monitor.check_streams()
            
            if new_streams:
                logger.info(f"🎮 Found {len(new_streams)} new Twitch streams to announce")
                for stream in new_streams:
                    try:
                        await twitch_monitor.announce_stream(stream)
                    except Exception as e:
                        logger.error(f"❌ Failed to announce Twitch stream {stream.get('title', 'Unknown')}: {e}")
            else:
                logger.debug("No new Twitch streams found")
                
        except Exception as e:
            logger.error(f"Error in Twitch stream checking task: {e}")

    @check_twitch_streams.before_loop
    async def before_twitch_streams_task(self):
        """Wait for bot to be ready before starting Twitch monitoring"""
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=10)
    async def store_youtube_subscriber_count(self):
        """Store Rayen's live YouTube subscriber count for future historical lookups."""
        try:
            youtube_monitor = getattr(self.bot, 'youtube_monitor', None)
            if not youtube_monitor:
                logger.warning("YouTube monitor not available for subscriber count snapshot")
                return

            await youtube_monitor.store_rayen_subscriber_snapshot()
        except Exception as e:
            logger.error(f"Error storing YouTube subscriber count snapshot: {e}")

    @store_youtube_subscriber_count.before_loop
    async def before_store_youtube_subscriber_count(self):
        """Wait for the bot to be ready before storing subscriber count snapshots."""
        await self.bot.wait_until_ready()
    
    @tasks.loop(minutes=30)  # Check every 30 minutes for historical reactions
    async def check_historical_reactions(self):
        """Check for new reactions on posts up to 4 hours old"""
        try:
            logger.debug("🔍 Starting historical reaction check...")
            
            # Get current time and 4 hours ago
            now = datetime.now()
            four_hours_ago = now - timedelta(hours=4)
            
            # Track statistics
            total_messages_checked = 0
            total_reactions_found = 0
            total_reactions_added = 0
            
            # Check each configured image reaction channel
            for channel_id in Config.IMAGE_REACTION_CHANNELS:
                try:
                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        logger.warning(f"⚠️ Could not find channel {channel_id}")
                        continue
                    
                    logger.debug(f"🔍 Checking channel #{channel.name} for historical reactions...")
                    
                    # Get messages from the last 4 hours
                    async for message in channel.history(limit=None, after=four_hours_ago):
                        total_messages_checked += 1
                        
                        # Skip messages without images
                        if not await self._message_has_images(message):
                            continue
                        
                        # Check reactions on this message
                        reactions_added = await self._process_message_reactions(message)
                        total_reactions_found += len(message.reactions)
                        total_reactions_added += reactions_added
                        
                        # Small delay to avoid rate limits
                        await asyncio.sleep(0.1)
                
                except Exception as e:
                    logger.error(f"❌ Error checking channel {channel_id}: {e}")
                    continue
            
            if total_reactions_added > 0:
                logger.info(f"✅ Historical reaction check complete: {total_messages_checked} messages checked, {total_reactions_found} reactions found, {total_reactions_added} new reactions added")
            else:
                logger.debug(f"✅ Historical reaction check complete: {total_messages_checked} messages checked, no new reactions found")
                
        except Exception as e:
            logger.error(f"❌ Error in historical reaction check: {e}")
    
    async def _message_has_images(self, message: discord.Message) -> bool:
        """Check if a message contains images"""
        # Check for attachments (uploaded images)
        for attachment in message.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                return True
        
        # Check for embedded images (links)
        for embed in message.embeds:
            if embed.image or embed.thumbnail:
                return True
        
        return False
    
    async def _process_message_reactions(self, message: discord.Message) -> int:
        """Process all reactions on a message and track any missing ones"""
        reactions_added = 0
        
        try:
            # First, audit the message for discrepancies
            thumbs_up_count = 0
            thumbs_down_count = 0
            
            for reaction in message.reactions:
                emoji_str = str(reaction.emoji)
                if emoji_str == '👍':
                    thumbs_up_count = reaction.count
                    # Subtract bot reactions
                    async for u in reaction.users():
                        if u.bot:
                            thumbs_up_count = max(0, thumbs_up_count - 1)
                            break
                elif emoji_str == '👎':
                    thumbs_down_count = reaction.count
                    # Subtract bot reactions
                    async for u in reaction.users():
                        if u.bot:
                            thumbs_down_count = max(0, thumbs_down_count - 1)
                            break
            
            # Audit for discrepancies
            if hasattr(self.bot.leaderboard_manager, 'audit_reaction_discrepancies'):
                audit_result = await self.bot.leaderboard_manager.audit_reaction_discrepancies(
                    str(message.id), thumbs_up_count, thumbs_down_count
                )
            
            # Only process thumbs up and thumbs down reactions for scoring
            for reaction in message.reactions:
                if str(reaction.emoji) not in ['👍', '👎']:
                    continue
                
                # Get all users who reacted (excluding bots)
                async for user in reaction.users():
                    if user.bot:
                        continue
                    
                    # Check if this reaction is already tracked in our database
                    # PyMongo's find_one is synchronous; do not await it
                    existing_reaction = self.bot.leaderboard_manager.user_reactions_collection.find_one({
                        "user_id": str(user.id),
                        "message_id": str(message.id),
                        "emoji": str(reaction.emoji)
                    })
                    
                    if not existing_reaction:
                        # This reaction is not tracked, add it
                        await self.bot.leaderboard_manager.track_user_reaction(
                            user_id=user.id,
                            message_id=str(message.id),
                            emoji=str(reaction.emoji),
                            added=True
                        )
                        
                        # Update scores and quest progress
                        await self._update_scores_and_quests(message, user, str(reaction.emoji))
                        
                        reactions_added += 1
                        logger.info(f"📝 Added missing reaction: {user.display_name} {reaction.emoji} on message {message.id}")
            
            # Update the message score in database to match Discord
            await self.bot.leaderboard_manager.update_image_message_score(
                str(message.id), thumbs_up_count, thumbs_down_count
            )
        
        except Exception as e:
            logger.error(f"❌ Error processing reactions for message {message.id}: {e}")
        
        return reactions_added
    
    async def _update_scores_and_quests(self, message: discord.Message, user: discord.User, emoji: str):
        """Update leaderboard scores and quest progress for a reaction"""
        try:
            # Calculate score change
            score_change = 0
            if emoji == '👍':
                score_change = 1
            elif emoji == '👎':
                score_change = -1
            
            if score_change != 0:
                # Update the leaderboard for the image author
                self.bot.leaderboard_manager.update_image_score(
                    user_id=message.author.id,
                    user_name=message.author.display_name,
                    score_change=score_change
                )
                
                # Update the image message score in MongoDB
                thumbs_up = 0
                thumbs_down = 0
                
                for r in message.reactions:
                    if str(r.emoji) == '👍':
                        thumbs_up = r.count
                        # Subtract 1 if bot reacted
                        async for u in r.users():
                            if u.bot:
                                thumbs_up = max(0, thumbs_up - 1)
                                break
                    elif str(r.emoji) == '👎':
                        thumbs_down = r.count
                        # Subtract 1 if bot reacted
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
                if emoji == '👍':
                    if hasattr(self.bot, 'events_controller') and self.bot.events_controller:
                        await self.bot.events_controller._update_quest_progress_likes(message.author, message, thumbs_up)
                
                # Update quest progress for rating images (for the person who reacted)
                if hasattr(self.bot, 'events_controller') and self.bot.events_controller:
                    await self.bot.events_controller._update_quest_progress_rating(user, message)
                    
                    # Update quest progress for giving likes (for thumbs up reactions)
                    if emoji == '👍':
                        await self.bot.events_controller._update_quest_progress_giving_likes(user, message)
        
        except Exception as e:
            logger.error(f"❌ Error updating scores and quests: {e}")
    
    # ==================== ART CHALLENGE TASKS ====================
    
    @tasks.loop(minutes=1)  # Check every minute for precise timing
    async def check_art_challenges(self):
        """Check for art challenge drops at specific times and handle expired challenges"""
        try:
            # Get the art challenge manager
            art_manager = getattr(self.bot, 'art_challenge_manager', None)
            art_view_manager = getattr(self.bot, 'art_challenge_view_manager', None)
            
            if not art_manager or not art_view_manager:
                return
            
            # Get the guild
            guild = self.bot.get_guild(Config.GUILD_ID)
            if not guild:
                return
            
            # 1. First, handle any expired challenges
            expired_challenges = art_manager.get_expired_challenges()
            for challenge in expired_challenges:
                try:
                    channel_id = challenge.get("channel_id")
                    channel = guild.get_channel(channel_id)
                    
                    if channel:
                        await art_view_manager.end_challenge(channel, challenge)
                        logger.info(f"🏁 Ended art challenge in #{channel.name}")
                    
                    art_manager.end_challenge(challenge.get("challenge_id"))
                    
                except Exception as e:
                    logger.error(f"Error ending challenge {challenge.get('challenge_id')}: {e}")
            
            # 2. Check if it's time to start a NEW challenge
            if not art_manager.is_challenge_start_time():
                return  # Not a start time, skip
            
            logger.info("🎨 Challenge start time detected! Checking for new challenge drops...")
            
            # Get the current window info
            window_info = art_manager.get_current_challenge_window()
            
            if not window_info:
                logger.warning("No challenge window active at start time (this shouldn't happen)")
                return
            
            start_hour, end_hour, channel_type, rating, channel_id = window_info
            
            channel = guild.get_channel(channel_id)
            if not channel:
                logger.error(f"Challenge channel {channel_id} not found")
                return
            
            # Check if there's already an active challenge in THIS channel
            active = art_manager.get_active_challenge(channel_id)
            if active:
                logger.info(f"⏭️ Already active challenge in #{channel.name}, skipping")
                return
            
            # Create and post new challenge
            logger.info(f"🎨 Creating new {channel_type.upper()} challenge (rating: {rating})")
            challenge_data = await art_manager.create_challenge(
                channel_id=channel_id,
                guild_id=guild.id,
                rating=rating
            )
            
            if challenge_data:
                message = await art_view_manager.post_challenge(channel, challenge_data)
                if message:
                    logger.info(f"✅ Started {channel_type.upper()} challenge in #{channel.name} at {start_hour:02d}:00 UTC (ends at {end_hour:02d}:00 UTC)")
                else:
                    logger.error(f"Failed to post challenge message in #{channel.name}")
            else:
                logger.error(f"Failed to create challenge for #{channel.name}")
        
        except Exception as e:
            logger.error(f"Error in art challenge task: {e}")
    
    @check_art_challenges.before_loop
    async def before_check_art_challenges(self):
        """Wait for bot to be ready before checking art challenges"""
        await self.bot.wait_until_ready()
        # Add a small delay to ensure all managers are initialized
        await asyncio.sleep(10)
    
    @check_historical_reactions.before_loop
    async def before_historical_reactions_task(self):
        """Wait for bot to be ready before starting historical reaction checking"""
        await self.bot.wait_until_ready()

    # ==================== DUEL CHALLENGE TASKS ====================

    @tasks.loop(minutes=1)  # Check every minute for precise timing
    async def check_duel_challenges(self):
        """Check for expired duel voting periods and resolve them"""
        try:
            challenge_manager = getattr(self.bot, 'challenge_mode_manager', None)
            if not challenge_manager:
                return

            guild = self.bot.get_guild(Config.GUILD_ID)
            if not guild:
                return

            # Get expired voting challenges
            expired_duels = challenge_manager.get_expired_voting_challenges()
            for duel in expired_duels:
                try:
                    # Resolve the duel
                    resolved = challenge_manager.resolve_challenge(duel["challenge_id"])
                    if not resolved:
                        continue

                    # Get the channel
                    channel = guild.get_channel(duel.get("channel_id"))
                    if not channel:
                        continue

                    # Announce the result
                    from views.challenge_mode_view import ChallengeModeEmbed
                    embed = ChallengeModeEmbed.create_result_embed(resolved)
                    await channel.send(embed=embed)

                    # Award points to winner
                    winner_id = resolved.get("winner_id")
                    if winner_id:
                        wager = resolved.get("wager", 0)
                        leaderboard_manager = getattr(self.bot, 'leaderboard_manager', None)
                        if leaderboard_manager:
                            try:
                                # Check for debuff
                                events_manager = getattr(self.bot, 'art_random_events_manager', None)
                                multiplier = 1.0
                                if events_manager:
                                    multiplier = events_manager.get_earnings_multiplier(winner_id)
                                
                                final_winnings = int(wager * 2 * multiplier)
                                winner_member = guild.get_member(winner_id)
                                if winner_member:
                                    await leaderboard_manager.add_points(
                                        user_id=winner_id,
                                        user_name=winner_member.display_name,
                                        points=final_winnings,
                                        point_type="duel_win",
                                        reason=f"Won 1v1 duel (wager: {wager} pts)"
                                    )
                                    logger.info(f"✅ Awarded {final_winnings} points to {winner_member.display_name} for winning duel")
                                    if multiplier < 1.0:
                                        await channel.send(f"⚠️ <@{winner_id}> earned {final_winnings} pts instead of {wager*2} due to debuff.")
                            except Exception as e:
                                logger.error(f"Error awarding duel winner points: {e}")

                    logger.info(f"⚔️ Resolved duel between <@{duel.get('challenger_id')}> and <@{duel.get('opponent_id')}>")

                except Exception as e:
                    logger.error(f"Error resolving duel {duel.get('challenge_id')}: {e}")

        except Exception as e:
            logger.error(f"Error in duel challenge task: {e}")

    @check_duel_challenges.before_loop
    async def before_duel_challenges_task(self):
        """Wait for bot to be ready before checking duels"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)

    # ==================== CUSTOM ROLES TASKS ====================

    @tasks.loop(hours=6)  # Check every 6 hours
    async def check_custom_roles(self):
        """Update custom roles for top rankers"""
        try:
            roles_manager = getattr(self.bot, 'custom_roles_manager', None)
            art_manager = getattr(self.bot, 'art_challenge_manager', None)
            challenge_manager = getattr(self.bot, 'challenge_mode_manager', None)
            if not roles_manager or not art_manager or not challenge_manager:
                return

            guild = self.bot.get_guild(Config.GUILD_ID)
            if not guild:
                return

            logger.info("🔄 Checking and updating custom roles...")

            # Get all tier role IDs
            artist_role_ids = roles_manager.get_artist_role_ids()
            duelist_role_ids = roles_manager.get_duelist_role_ids()
            all_tier_role_ids = roles_manager.get_all_tier_role_ids()

            # Get all members who have tier roles
            members_with_roles = []
            for role_id in all_tier_role_ids:
                role = guild.get_role(role_id)
                if role:
                    members_with_roles.extend(role.members)

            # Update each member's roles
            for member in members_with_roles:
                try:
                    # Get their stats
                    art_stats = art_manager.get_user_challenge_stats(member.id)
                    duel_stats = challenge_manager.get_user_challenge_stats(member.id)

                    total_art_points = art_stats.get("total_points", 0)
                    total_duel_wins = duel_stats.get("wins", 0)

                    # Determine correct roles
                    artist_role = roles_manager.get_artist_role(total_art_points)
                    duelist_role = roles_manager.get_duelist_role(total_duel_wins)

                    # Remove all tier roles
                    for role_id in all_tier_role_ids:
                        role = guild.get_role(role_id)
                        if role and role in member.roles:
                            await member.remove_roles(role, reason="Updating custom role tier")

                    # Add correct roles
                    if artist_role:
                        role = guild.get_role(artist_role["role_id"])
                        if role:
                            await member.add_roles(role, reason=f"Artist role: {artist_role['name']}")

                    if duelist_role:
                        role = guild.get_role(duelist_role["role_id"])
                        if role:
                            await member.add_roles(role, reason=f"Duelist role: {duelist_role['name']}")

                except Exception as e:
                    logger.error(f"Error updating roles for {member.display_name}: {e}")

            logger.info("✅ Custom roles check completed")

        except Exception as e:
            logger.error(f"Error in custom roles task: {e}")

    @check_custom_roles.before_loop
    async def before_custom_roles_task(self):
        """Wait for bot to be ready before checking custom roles"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)

    # ==================== DEBUFF TASKS ====================

    @tasks.loop(hours=1)  # Check every hour
    async def check_debuffs(self):
        """Clear expired debuffs"""
        try:
            events_manager = getattr(self.bot, 'art_random_events_manager', None)
            if not events_manager:
                return

            events_manager.clear_expired_debuffs()

        except Exception as e:
            logger.error(f"Error in debuff task: {e}")

    @check_debuffs.before_loop
    async def before_debuffs_task(self):
        """Wait for bot to be ready before checking debuffs"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)
