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
            # Check if quest manager is available
            events_controller = getattr(self.bot, 'events_controller', None)
            if not events_controller or not hasattr(events_controller, 'quest_manager') or not events_controller.quest_manager:
                return
            
            quest_manager = events_controller.quest_manager
            
            # Check for broken streaks
            await quest_manager.check_and_break_streaks()
            logger.info("Daily streak check completed")
            
        except Exception as e:
            logger.error(f"Error in daily streak check: {e}")
    
    @check_streaks.before_loop
    async def before_streaks_task(self):
        """Wait until the bot is ready before starting streaks task"""
        await self.bot.wait_until_ready()
    
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
        """Wait for bot to be ready before starting YouTube video checking"""
        await self.bot.wait_until_ready() 