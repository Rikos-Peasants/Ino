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
    from models.twitch_monitor import TwitchMonitor

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
        self.twitch_monitor: Optional['TwitchMonitor'] = None
        self.random_announcer: Optional['RandomAnnouncer'] = None
        self.moderation_view_manager: Optional[object] = None
        self.scam_image_manager: Optional[object] = None
        self.scam_image_controller: Optional[object] = None
        self.donation_manager: Optional[object] = None
        self.donation_controller: Optional[object] = None
        self.web_server: Optional[object] = None
        
        # Initialize leaderboard manager first (required by other components)
        try:
            from models.mongo_leaderboard_manager import MongoLeaderboardManager
            self.leaderboard_manager = MongoLeaderboardManager()
            logger.info("✅ MongoDB leaderboard manager initialized successfully")
            try:
                from models.scam_image_manager import ScamImageManager
                self.scam_image_manager = ScamImageManager(self.leaderboard_manager.db)
                logger.info("✅ Scam image manager initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize scam image manager: {e}")
                self.scam_image_manager = None
            try:
                from models.donation_manager import DonationManager
                self.donation_manager = DonationManager(self.leaderboard_manager.db)
                logger.info("✅ Donation manager initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize donation manager: {e}")
                self.donation_manager = None
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
        
        # Initialize Twitch monitor
        try:
            from models.twitch_monitor import TwitchMonitor
            from models.mongo_leaderboard_manager import MongoLeaderboardManager
            if isinstance(self.leaderboard_manager, MongoLeaderboardManager):
                self.twitch_monitor = TwitchMonitor(self.leaderboard_manager)
            else:
                self.twitch_monitor = TwitchMonitor(None)
            self.twitch_monitor.bot = self
            logger.info("✅ Twitch monitor initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Twitch monitor: {e}")
            self.twitch_monitor = None
        
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

        if self.scam_image_manager:
            try:
                from controllers.scam_image_controller import ScamImageController
                self.scam_image_controller = ScamImageController(self, self.scam_image_manager)
                logger.info("✅ Scam image controller initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize scam image controller: {e}")
                self.scam_image_controller = None
        
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

        # Initialize challenge mode manager (1v1 duels)
        try:
            from models.challenge_mode_manager import ChallengeModeManager
            self.challenge_mode_manager = ChallengeModeManager()
            logger.info("✅ Challenge mode manager initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize challenge mode manager: {e}")
            self.challenge_mode_manager = None

        # Initialize custom roles manager
        try:
            from models.custom_roles_manager import CustomRolesManager
            self.custom_roles_manager = CustomRolesManager()
            logger.info("✅ Custom roles manager initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize custom roles manager: {e}")
            self.custom_roles_manager = None

        # Initialize art random events manager
        try:
            from models.art_random_events_manager import ArtRandomEventsManager
            self.art_random_events_manager = ArtRandomEventsManager()
            logger.info("✅ Art random events manager initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize art random events manager: {e}")
            self.art_random_events_manager = None

        # Initialize donation controller (goal channel + progress bar commands)
        if self.donation_manager:
            try:
                from controllers.donation_controller import DonationController
                self.donation_controller = DonationController(self)
                logger.info("✅ Donation controller initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize donation controller: {e}")
                self.donation_controller = None

        # Initialize the public web server (leaderboards, donations, Ko-fi hook)
        if Config.WEB_ENABLED:
            try:
                from web.server import RikoWebServer
                self.web_server = RikoWebServer(self)
                logger.info("✅ Web server initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize web server: {e}")
                self.web_server = None
    
    async def setup_hook(self):
        """Initial setup when bot is starting"""
        logger.info("Setting up bot...")
        
        # Register events and commands
        if self.events_controller:
            self.events_controller.register_events()
        if self.commands_controller:
            self.commands_controller.register_commands()
        if self.scam_image_controller:
            self.scam_image_controller.register_commands()
        if self.donation_controller:
            self.donation_controller.register_commands()

        # Initialize quest manager after bot is ready
        if self.events_controller:
            self.events_controller.initialize_quest_manager()

        # Start the web server here rather than in on_ready so /healthz answers
        # as soon as the process is up, even if the gateway is still connecting.
        if self.web_server:
            try:
                await self.web_server.start()
            except Exception as e:
                logger.error(f"❌ Failed to start web server: {e}")
                self.web_server = None

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
        
        # Register challenge mode persistent views
        try:
            from views.challenge_mode_view import ChallengeAcceptView, ChallengeVoteView
            challenge_manager = getattr(self, 'challenge_mode_manager', None)
            if challenge_manager:
                accept_view = ChallengeAcceptView("", challenge_manager)
                vote_view = ChallengeVoteView("", challenge_manager)
                self.add_view(accept_view)
                self.add_view(vote_view)
                logger.info("✅ Challenge mode persistent views registered")
        except Exception as e:
            logger.error(f"❌ Failed to register challenge mode views: {e}")
        
        # Start scheduler tasks for best image posting
        if self.scheduler_controller:
            self.scheduler_controller.start_tasks()
            logger.info("Started scheduled tasks for best image posting")
            logger.info("Best images will be posted back to their original channels")
        
        # Both of these walk hundreds of users and thousands of messages using
        # synchronous pymongo calls. Awaiting them here held the event loop for
        # around two minutes, during which the bot ignored commands and the web
        # server took 19 seconds to answer a request that normally takes 0.2.
        # They run in the background instead and report when they finish.
        asyncio.create_task(self.check_all_achievements_on_startup())
        asyncio.create_task(self.scan_historical_images())

        # Send language prompt DMs to opted-in users who haven't set their languages yet
        if self.events_controller:
            try:
                asyncio.create_task(self.events_controller._send_language_prompt_all_users())
            except Exception as e:
                logger.error(f"Error sending language prompt DMs: {e}")
        
        # Make sure a goal row exists so the website renders from the database
        # rather than the in-memory fallback before anyone runs /setup-dono.
        if self.donation_manager:
            try:
                goal = await self.donation_manager.ensure_default_goal()
                logger.info(f"✅ Active donation goal: {goal.get('title')} (${goal.get('target_usd')})")
            except Exception as e:
                logger.error(f"Error ensuring default donation goal: {e}")

        # Keep the donation progress bar current even if a webhook was missed
        if self.donation_controller:
            try:
                self.donation_controller.start_tasks()
                logger.info("Donation progress refresh task started")
            except Exception as e:
                logger.error(f"Error starting donation tasks: {e}")

        # Start status cycling (only if not already running)
        if not self.cycle_status.is_running():
            self.cycle_status.start()
            logger.info("Status cycling started")
        
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
                # Get all user IDs first (lightweight query). Run it in a
                # thread so the driver's blocking round trip does not stall
                # the gateway heartbeat or the web server.
                all_users = await asyncio.to_thread(
                    lambda: list(
                        self.leaderboard_manager.collection.find(
                            {}, {"user_id": 1, "user_name": 1}
                        )
                    )
                )
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

                        # Hand the loop back between users, not just between
                        # chunks. check_achievements issues several blocking
                        # queries, so ten of them back to back is a visible
                        # stall for everything else on the loop.
                        await asyncio.sleep(0)

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

            # The image-message API only exists on the MongoDB manager. When Mongo is
            # unreachable the bot falls back to the JSON manager, which has no such
            # methods, so calling them here would raise AttributeError mid-scan.
            required_methods = (
                "image_message_exists",
                "store_image_message",
                "update_image_message_score",
            )
            if not self.leaderboard_manager or not all(
                hasattr(self.leaderboard_manager, name) for name in required_methods
            ):
                logger.warning(
                    "Leaderboard manager does not support image message storage, "
                    "skipping historical image scan"
                )
                return

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

    async def close(self):
        """Clean shutdown"""
        logger.info("Bot is shutting down...")
        
        # Stop status cycling
        if self.cycle_status.is_running():
            self.cycle_status.cancel()
        
        # Stop scheduler tasks
        if self.scheduler_controller:
            self.scheduler_controller.stop_tasks()

        # Stop donation refresh task
        if self.donation_controller:
            self.donation_controller.stop_tasks()

        # Shut the web server down before closing the DB it reads from
        if self.web_server:
            try:
                await self.web_server.stop()
            except Exception as e:
                logger.error(f"Error stopping web server: {e}")


        
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
