import discord
from discord.ext import commands, tasks
import asyncio
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from config import Config

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
        
        # Start scheduler tasks for best image posting
        if self.scheduler_controller:
            self.scheduler_controller.start_tasks()
            logger.info("Started scheduled tasks for best image posting")
            logger.info("Best images will be posted back to their original channels")
        
        # Check and award achievements for all users on startup
        await self.check_all_achievements_on_startup()
        
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
                            
                            if new_achievements:
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