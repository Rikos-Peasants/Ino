import discord
from discord.ext import commands, tasks
import asyncio
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from config import Config
from views.forum_thread_view import ForumThreadView

if TYPE_CHECKING:
    from controllers.events import EventsController
    from controllers.commands import CommandsController
    from controllers.scheduler import SchedulerController
    from models.youtube_monitor import YouTubeMonitor

# Always import RandomAnnouncer for runtime use
from models.random_announcer import RandomAnnouncer

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RikoBot(commands.Bot):
    """Riko Discord Bot"""
    
    def __init__(self):
        # Define intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True
        intents.guilds = True
        
        # Initialize bot with hybrid command support
        super().__init__(
            command_prefix="R!",
            intents=intents,
            case_insensitive=True,
            help_command=None,
            activity=discord.Activity(type=discord.ActivityType.watching, name="Discord members"),
            status=discord.Status.online
        )
        
        # 50 % chance to roast the user instead of running any command (April 1st only)
        @self.before_invoke
        async def roast_before_invoke(ctx):
            from models.april_fools import maybe_roast, RoastInterrupt
            if await maybe_roast(ctx):
                raise RoastInterrupt()

        # Same roast check for ALL slash / app commands
        @self.tree.interaction_check
        async def roast_interaction_check(interaction: discord.Interaction) -> bool:
            from models.april_fools import maybe_roast_interaction
            if await maybe_roast_interaction(interaction):
                return False
            return True

        # Add a check to restrict the bot to the Rayen server only
        @self.check
        async def globally_block_dms_and_other_guilds(ctx):
            """Block all commands in DMs and guilds other than the configured one"""
            # Allow in the configured guild
            if ctx.guild and ctx.guild.id == Config.GUILD_ID:
                return True
            
            # Block in DMs
            if not ctx.guild:
                await ctx.send("❌ Sorry, this bot only works in discord.gg/RayenAI")
                return False
            
            # Block in other guilds
            await ctx.send("❌ Sorry, this bot only works in discord.gg/RayenAI")
            return False
        
        # Initialize components with proper typing
        self.leaderboard_manager: Optional[object] = None
        self.events_controller: Optional['EventsController'] = None
        self.commands_controller: Optional['CommandsController'] = None
        self.scheduler_controller: Optional['SchedulerController'] = None
        self.youtube_monitor: Optional['YouTubeMonitor'] = None
        self.random_announcer: Optional['RandomAnnouncer'] = None
        self.moderation_view_manager: Optional[object] = None
        
        # Initialize leaderboard manager first (required by other components)
        try:
            from models.mongo_leaderboard_manager import MongoLeaderboardManager
            self.leaderboard_manager = MongoLeaderboardManager()
            logger.info("✅ MongoDB leaderboard manager initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize MongoDB leaderboard manager: {e}")
            # Fallback to JSON-based leaderboard manager
            try:
                from models.leaderboard_manager import LeaderboardManager
                self.leaderboard_manager = LeaderboardManager()
                logger.info("✅ JSON leaderboard manager initialized as fallback")
            except Exception as e2:
                logger.error(f"❌ Failed to initialize fallback leaderboard manager: {e2}")
                self.leaderboard_manager = None
        
        # Initialize YouTube monitor
        try:
            from models.youtube_monitor import YouTubeMonitor
            from models.mongo_leaderboard_manager import MongoLeaderboardManager
            # Only pass MongoDB manager if it's the right type
            if isinstance(self.leaderboard_manager, MongoLeaderboardManager):
                self.youtube_monitor = YouTubeMonitor(self.leaderboard_manager)
            else:
                self.youtube_monitor = YouTubeMonitor(None)
            # Set bot reference for Discord operations
            self.youtube_monitor.bot = self
            logger.info("✅ YouTube monitor initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize YouTube monitor: {e}")
            self.youtube_monitor = None
        
        # Initialize Random Announcer (TEMPORARY FOR RESEARCH)
        try:
            self.random_announcer = RandomAnnouncer(self, self.leaderboard_manager)
            logger.info("✅ Random announcer initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize random announcer: {e}")
            self.random_announcer = None
        
        # Initialize controllers
        from controllers.events import EventsController
        from controllers.commands import CommandsController  
        from controllers.scheduler import SchedulerController
        
        self.events_controller = EventsController(self)
        self.commands_controller = CommandsController(self)
        self.scheduler_controller = SchedulerController(self)
        
        # Initialize moderation view manager
        try:
            from views.moderation_view import ModerationViewManager
            self.moderation_view_manager = ModerationViewManager(self)
            # Setup persistent views
            self.moderation_view_manager.setup_persistent_views()
            logger.info("✅ Moderation view manager initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize moderation view manager: {e}")
            self.moderation_view_manager = None
        
        # Initialize art challenge manager and view manager
        self.art_challenge_manager = None
        self.art_challenge_view_manager = None
        try:
            from models.art_challenge_manager import ArtChallengeManager
            from views.art_challenge_view import ArtChallengeViewManager
            self.art_challenge_manager = ArtChallengeManager()
            self.art_challenge_view_manager = ArtChallengeViewManager(self)
            self.art_challenge_view_manager.set_art_manager(self.art_challenge_manager)
            logger.info("✅ Art challenge manager initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize art challenge manager: {e}")
            self.art_challenge_manager = None
            self.art_challenge_view_manager = None
    
    async def setup_hook(self):
        """Initial setup when bot is starting"""
        logger.info("Setting up bot...")
        
        # Register events and commands
        if self.events_controller:
            self.events_controller.register_events()
        if self.commands_controller:
            self.commands_controller.register_commands()
        
        # Initialize quest manager after bot is ready
        if self.events_controller:
            self.events_controller.initialize_quest_manager()
        
        logger.info("Bot setup completed")
    
    async def on_ready(self):
        """Bot is ready and connected"""
        if not self.user:
            logger.error("Bot user is None - something went wrong during login")
            return
            
        logger.info(f"✅ Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"✅ Connected to {len(self.guilds)} guilds")
        
        # Debug: List all available commands
        logger.info("📋 Available commands:")
        for cmd_name in sorted(self.all_commands.keys()):
            logger.info(f"  - Text command: R!{cmd_name}")
        
        # Debug: List all app commands
        for cmd in self.tree.get_commands():
            description = getattr(cmd, 'description', 'No description') if hasattr(cmd, 'description') else 'No description'
            logger.info(f"  - App command: /{cmd.name} - {description}")
        
        # Sync commands to enable slash command functionality
        logger.info("Syncing hybrid commands...")
        try:
            # Sync to the configured guild first (instant updates for development)
            if Config.GUILD_ID:
                guild = discord.Object(id=Config.GUILD_ID)
                synced_guild = await self.tree.sync(guild=guild)
                logger.info(f"✅ Synced {len(synced_guild)} commands to guild {Config.GUILD_ID}")
                for cmd in synced_guild:
                    logger.info(f"   - /{cmd.name}: {cmd.description}")
            
            # Also sync globally (takes up to 1 hour to propagate)
            synced_global = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced_global)} commands globally")
            
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}")
            logger.error(f"   Make sure bot has 'applications.commands' scope!")
        
        # Register persistent views
        try:
            # Register ForumThreadView for persistent view handling
            # This allows Discord.py to recreate views after bot restart
            self.add_view(ForumThreadView())
            logger.info("✅ Persistent view registration completed")
        except Exception as e:
            logger.error(f"❌ Failed to register persistent views: {e}")
        
        # Register art challenge persistent views
        try:
            if self.art_challenge_view_manager:
                self.art_challenge_view_manager.setup_persistent_views()
                logger.info("✅ Art challenge persistent views registered")
        except Exception as e:
            logger.error(f"❌ Failed to register art challenge views: {e}")
        
        # Start scheduler tasks for best image posting
        if self.scheduler_controller:
            self.scheduler_controller.start_tasks()
            logger.info("Started scheduled tasks for best image posting")
            logger.info("Best images will be posted back to their original channels")
        
        # Check and award achievements for all users on startup
        await self.check_all_achievements_on_startup()
        
        # Automatically scan and store all historical images
        await self.scan_historical_images()
        
        # Start status cycling (only if not already running)
        if not self.cycle_status.is_running():
            self.cycle_status.start()
            logger.info("Status cycling started")
        
        # Restore april1st toggle from persistent storage and instantly apply
        try:
            lm = self.leaderboard_manager
            if lm and hasattr(lm, 'moderation_manager') and lm.moderation_manager:
                stored = await lm.moderation_manager.get_moderation_setting(
                    str(Config.GUILD_ID), 'april1st', False
                )
                if stored:
                    from models.april_fools import set_april_fools_mode, AF_ART_CHALLENGE_PROMPTS
                    import random
                    set_april_fools_mode(True)
                    logger.info("🃏 April Fools mode restored from DB: ENABLED")
                    await self._apply_jake_profile()
                    
                    # Spawn initial AF art challenges immediately
                    try:
                        art_manager = getattr(self, 'art_challenge_manager', None)
                        art_view_manager = getattr(self, 'art_challenge_view_manager', None)
                        if art_manager and art_view_manager:
                            guild = self.get_guild(Config.GUILD_ID)
                            if guild:
                                channels_to_challenge = [
                                    (Config.ART_CHALLENGE_CHANNEL_SFW, "safe"),
                                    (Config.ART_CHALLENGE_CHANNEL_NSFW, "questionable"),
                                ]
                                for channel_id, rating in channels_to_challenge:
                                    channel = guild.get_channel(channel_id)
                                    if channel and not art_manager.get_active_challenge(channel_id):
                                        prompt = random.choice(AF_ART_CHALLENGE_PROMPTS)
                                        challenge_data = await art_manager.create_april_fools_challenge(
                                            channel_id=channel_id,
                                            guild_id=guild.id,
                                            prompt=prompt,
                                            rating=rating
                                        )
                                        if challenge_data:
                                            await art_view_manager.post_challenge(channel, challenge_data)
                                            logger.info(f"🎨 Initial AF challenge spawned in #{channel.name}")
                    except Exception as e:
                        logger.error(f"Error spawning initial AF challenges on startup: {e}")
        except Exception as e:
            logger.warning(f"Could not restore april1st setting: {e}")

        logger.info("🚀 Bot is fully ready and operational!")
    
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle interactions including moderation buttons"""
        try:
            # Handle moderation button interactions first (for validation only)
            if (interaction.type == discord.InteractionType.component 
                and self.moderation_view_manager):
                # Just validate, don't fully handle (let Discord.py handle callbacks)
                handled = await self.moderation_view_manager.handle_interaction(interaction)
                if handled:
                    return  # Error case handled
            
            # Continue with default Discord.py processing for all other cases
            # This includes both command tree and UI component callbacks
            
        except discord.InteractionResponded:
            # Interaction was already responded to
            pass
        except Exception as e:
            logger.error(f"Error handling interaction: {e}")
            if not interaction.response.is_done():
                try:
                    await interaction.response.send_message(
                        "❌ An error occurred processing your request.", 
                        ephemeral=True
                    )
                except:
                    pass
    
    @tasks.loop(minutes=2)  # Change status every 2 minutes
    async def cycle_status(self):
        """Cycle through different bot statuses"""
        if not self.user:
            return
            
        # Funny status messages
        self.status_messages = [
            ("watching", "over {users} Riko Simps"),
            ("listening", "to Rayen's New Proposals"),
            ("watching", "Angel be mad at Taishi"),
            ("listening", "to random people yap in DMs"),
            ("watching", "new messages & ideas pile up"),
            ("playing", "with role permissions"),
            ("watching", "for troublemakers"),
            ("listening", "to the sound of silence"),
            ("watching", "paint dry (more fun than modding)"),
            ("playing", "hide and seek with bugs"),
            ("listening", "to the screams of banned users"),
            ("watching", "chaos unfold in general chat"),
            ("playing", "therapist for drama queens"),
            ("watching", "people argue about pineapple on pizza"),
            ("listening", "to excuses from rule breakers"),
            ("watching", "memes get overused"),
            ("playing", "whack-a-mole with spammers"),
            ("watching", "people simp for anime characters"),
            ("listening", "to theories about everything"),
            ("watching", "the admin's sanity deteriorate")
        ]
        
        import random
        activity_type, status_text = random.choice(self.status_messages)
        
        # Replace {users} placeholder with actual member count
        if "{users}" in status_text:
            total_members = sum(guild.member_count for guild in self.guilds if guild.member_count)
            status_text = status_text.format(users=total_members)
        
        # Map activity type strings to Discord activity types
        activity_map = {
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "playing": discord.ActivityType.playing
        }
        
        activity = discord.Activity(type=activity_map[activity_type], name=status_text)
        await self.change_presence(activity=activity, status=discord.Status.online)
        logger.debug(f"Changed status to: {activity_type} {status_text}")
    
    @cycle_status.before_loop
    async def before_cycle_status(self):
        """Wait for bot to be ready before starting status cycling"""
        await self.wait_until_ready()
    
    async def check_all_achievements_on_startup(self):
        """Check and award achievements for all users on bot startup (in chunks to avoid blocking)"""
        try:
            logger.info("🏆 Starting achievement check for all users...")
            
            # Check if quest manager is available
            if not self.events_controller or not self.events_controller.quest_manager:
                logger.warning("Quest manager not available, skipping achievement check")
                return
            
            # Check if leaderboard manager is available
            if not self.leaderboard_manager:
                logger.warning("Leaderboard manager not available, skipping achievement check")
                return
            
            quest_manager = self.events_controller.quest_manager
            
            # Get all users who have posted images (they're in the leaderboard)
            from models.mongo_leaderboard_manager import MongoLeaderboardManager
            if isinstance(self.leaderboard_manager, MongoLeaderboardManager):
                # Get all user IDs first (lightweight query)
                all_users = list(self.leaderboard_manager.collection.find({}, {"user_id": 1, "user_name": 1}))
                total_user_count = len(all_users)
                
                logger.info(f"   Found {total_user_count} users to check")
                
                total_users = 0
                total_achievements = 0
                
                # Process users in chunks of 10 to avoid blocking
                CHUNK_SIZE = 10
                
                for i in range(0, len(all_users), CHUNK_SIZE):
                    chunk = all_users[i:i + CHUNK_SIZE]
                    
                    for user_doc in chunk:
                        user_id = int(user_doc["user_id"])
                        total_users += 1
                        
                    try:
                        # Check achievements for this user
                        new_achievements = await quest_manager.check_achievements(
                            user_id=user_id,
                            leaderboard_manager=self.leaderboard_manager
                        )
                        
                        # Only log if achievements were actually awarded
                        if new_achievements and len(new_achievements) > 0:
                            total_achievements += len(new_achievements)
                            user_name = user_doc.get("user_name", f"User {user_id}")
                            logger.info(f"   ✅ Awarded {len(new_achievements)} achievement(s) to {user_name}")
                            
                            # Log each achievement (limit to 3 to reduce spam)
                            for idx, achievement in enumerate(new_achievements):
                                if idx < 3:
                                    logger.info(f"      {achievement.get('icon', '🏆')} {achievement['name']} (+{achievement['reward_points']} pts)")
                                elif idx == 3:
                                    logger.info(f"      ... and {len(new_achievements) - 3} more")
                                    break
                        
                    except Exception as e:
                        logger.error(f"   ❌ Error checking achievements for user {user_id}: {e}")
                        continue
                    
                    # Yield control back to the event loop after each chunk
                    await asyncio.sleep(0.1)
                    
                    # Log progress every 50 users
                    if total_users % 50 == 0:
                        logger.info(f"   Progress: {total_users}/{total_user_count} users checked...")
                
                logger.info(f"🏆 Achievement check complete: Checked {total_users} users, awarded {total_achievements} achievements")
            else:
                logger.warning("MongoDB leaderboard manager not in use, skipping achievement check")
        
        except Exception as e:
            logger.error(f"Error during achievement check on startup: {e}")
    
    async def scan_historical_images(self):
        """Scan and store all historical images from image channels on startup"""
        try:
            logger.info("🔍 Scanning historical images from image channels...")
            
            from config import Config
            from datetime import datetime, timedelta
            
            guild = self.get_guild(Config.GUILD_ID)
            if not guild:
                logger.error(f"Could not find guild {Config.GUILD_ID}")
                return
            
            total_processed = 0
            total_skipped = 0
            
            # Scan images from the past 90 days (adjust as needed)
            cutoff_date = datetime.now() - timedelta(days=90)
            
            for channel_id in Config.IMAGE_REACTION_CHANNELS:
                channel = guild.get_channel(channel_id)
                if not channel:
                    logger.warning(f"Could not find channel {channel_id}")
                    continue
                
                logger.info(f"  Scanning #{channel.name} (ID: {channel_id})...")
                channel_processed = 0
                channel_skipped = 0
                
                try:
                    async for message in channel.history(limit=None, after=cutoff_date):
                        # Check if message has images
                        has_image = False
                        image_url = None
                        
                        # Check attachments
                        for attachment in message.attachments:
                            if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.mov', '.webm']):
                                has_image = True
                                image_url = attachment.url
                                break
                        
                        # Check embeds
                        if not has_image:
                            for embed in message.embeds:
                                if embed.image or embed.thumbnail or embed.video:
                                    has_image = True
                                    if embed.image:
                                        image_url = embed.image.url
                                    elif embed.thumbnail:
                                        image_url = embed.thumbnail.url
                                    elif embed.video:
                                        image_url = str(embed.video.url) if hasattr(embed.video, 'url') else str(embed.url)
                                    break
                        
                        if has_image and image_url:
                            # Check if already in database
                            exists = await self.leaderboard_manager.image_message_exists(str(message.id))
                            
                            if not exists:
                                # Count reactions
                                thumbs_up = 0
                                thumbs_down = 0
                                
                                for reaction in message.reactions:
                                    if str(reaction.emoji) == '👍':
                                        thumbs_up = reaction.count
                                        # Subtract bot reactions
                                        async for user in reaction.users():
                                            if user.bot:
                                                thumbs_up = max(0, thumbs_up - 1)
                                                break
                                    elif str(reaction.emoji) == '👎':
                                        thumbs_down = reaction.count
                                        # Subtract bot reactions
                                        async for user in reaction.users():
                                            if user.bot:
                                                thumbs_down = max(0, thumbs_down - 1)
                                                break
                                
                                net_score = thumbs_up - thumbs_down
                                
                                # Store the image
                                await self.leaderboard_manager.store_image_message(
                                    message=message,
                                    image_url=image_url,
                                    initial_score=net_score
                                )
                                
                                # Update score
                                await self.leaderboard_manager.update_image_message_score(
                                    message_id=str(message.id),
                                    thumbs_up=thumbs_up,
                                    thumbs_down=thumbs_down
                                )
                                
                                # Add to leaderboard
                                self.leaderboard_manager.add_image_post(
                                    user_id=message.author.id,
                                    user_name=message.author.display_name,
                                    initial_score=net_score
                                )
                                
                                channel_processed += 1
                            else:
                                channel_skipped += 1
                    
                    logger.info(f"    ✅ #{channel.name}: {channel_processed} new, {channel_skipped} skipped")
                    total_processed += channel_processed
                    total_skipped += channel_skipped
                    
                except Exception as e:
                    logger.error(f"    ❌ Error scanning #{channel.name}: {e}")
                    continue
            
            logger.info(f"✅ Historical image scan complete: {total_processed} images added, {total_skipped} already in database")
            
        except Exception as e:
            logger.error(f"Error in scan_historical_images: {e}")

    async def _apply_jake_profile(self):
        """Download Jake's avatar, apply it, set nickname, and randomise the server icon."""
        import aiohttp, os, random
        from models.april_fools import JAKE_AVATAR, JAKE_NAME
        from config import Config

        # 1. Bot avatar → Jake
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(JAKE_AVATAR, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        avatar_bytes = await resp.read()
                        await self.user.edit(avatar=avatar_bytes)
                        logger.info("🃏 Jake avatar applied")
        except discord.HTTPException as e:
            logger.warning(f"🃏 Avatar change rate-limited or failed: {e}")
        except Exception as e:
            logger.warning(f"🃏 Failed to apply Jake avatar: {e}")

        guild = self.get_guild(Config.GUILD_ID)

        # 2. Server nickname → Jake
        try:
            if guild and guild.me:
                await guild.me.edit(nick=JAKE_NAME)
                logger.info(f"🃏 Nickname set to {JAKE_NAME}")
        except Exception as e:
            logger.warning(f"🃏 Failed to set Jake nickname: {e}")

        # 3. Server icon → random 1-9.png
        try:
            avatars_dir = os.path.join(os.path.dirname(__file__), "assets", "april_fools_avatars")
            pick = random.randint(1, 9)
            icon_path = os.path.join(avatars_dir, f"{pick}.png")
            if guild and os.path.isfile(icon_path):
                with open(icon_path, "rb") as f:
                    await guild.edit(icon=f.read())
                logger.info(f"🃏 Server icon changed to {pick}.png")
        except discord.HTTPException as e:
            logger.warning(f"🃏 Server icon change rate-limited or failed: {e}")
        except Exception as e:
            logger.warning(f"🃏 Failed to change server icon: {e}")

    async def _restore_profile(self):
        """Restore default avatar, clear nickname, and restore server icon."""
        import os
        from config import Config

        # 1. Bot avatar → default
        try:
            default_path = os.path.join(
                os.path.dirname(__file__), "assets", "april_fools_avatars", "default.png"
            )
            if os.path.isfile(default_path):
                with open(default_path, "rb") as f:
                    avatar_bytes = f.read()
                await self.user.edit(avatar=avatar_bytes)
                logger.info("✅ Default avatar restored")
        except discord.HTTPException as e:
            logger.warning(f"Avatar restore rate-limited or failed: {e}")
        except Exception as e:
            logger.warning(f"Failed to restore avatar: {e}")

        guild = self.get_guild(Config.GUILD_ID)

        # 2. Nickname → clear
        try:
            if guild and guild.me:
                await guild.me.edit(nick=None)
                logger.info("✅ Nickname cleared")
        except Exception as e:
            logger.warning(f"Failed to clear nickname: {e}")

        # 3. Server icon → default.png
        try:
            default_icon = os.path.join(
                os.path.dirname(__file__), "assets", "april_fools_avatars", "default.png"
            )
            if guild and os.path.isfile(default_icon):
                with open(default_icon, "rb") as f:
                    await guild.edit(icon=f.read())
                logger.info("✅ Server icon restored")
        except discord.HTTPException as e:
            logger.warning(f"Server icon restore rate-limited or failed: {e}")
        except Exception as e:
            logger.warning(f"Failed to restore server icon: {e}")

    async def close(self):
        """Clean shutdown"""
        logger.info("Bot is shutting down...")
        
        # Stop status cycling
        if self.cycle_status.is_running():
            self.cycle_status.cancel()
        
        # Stop scheduler tasks
        if self.scheduler_controller:
            self.scheduler_controller.stop_tasks()
        

        
        # Close MongoDB connection
        if hasattr(self, 'leaderboard_manager') and self.leaderboard_manager:
            # Check if it's MongoDB manager which has close method
            from models.mongo_leaderboard_manager import MongoLeaderboardManager
            if isinstance(self.leaderboard_manager, MongoLeaderboardManager):
                self.leaderboard_manager.close()
                logger.info("MongoDB connection closed")
        
        # Call parent close
        await super().close()
        logger.info("Bot shutdown complete")

async def main():
    """Main function to run the bot"""
    try:
        # Validate configuration
        Config.validate()
        
        # Create and run bot
        bot = RikoBot()
        if Config.TOKEN:
            await bot.start(Config.TOKEN)
        else:
            logger.error("Discord token is not configured")
        
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
    except discord.LoginFailure:
        logger.error("Invalid bot token")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    asyncio.run(main())