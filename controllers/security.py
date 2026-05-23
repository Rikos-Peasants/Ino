import discord
from discord.ext import commands
from functools import wraps
from enum import Enum
import logging
from config import Config

logger = logging.getLogger(__name__)

class SecurityLevel(Enum):
    """Security levels for bot commands"""
    PUBLIC = "public"          # Anyone can use
    MODERATOR = "moderator"    # Requires manage_guild or specific moderator roles
    ADMIN = "admin"           # Requires administrator permission or bot owner
    OWNER = "owner"           # Bot owners only

class CommandSecurity:
    """Centralized command security system"""
    
    # Define command categories by security level
    COMMAND_PERMISSIONS = {
        # PUBLIC - Safe, read-only commands anyone can use
        SecurityLevel.PUBLIC: {
            'leaderboard', 'stats', 'uptime', 'quests', 'achievements', 'streaks', 
            'events', 'bookmarks', 'bookmark', 'unbookmark', 'liked_images', 
            'closethread', 'debug', 'inorep', 'patreon', 'pointsleaderboard'  # inorep group and subcommands
        },
        
        # MODERATOR - Requires manage_guild permission or specific roles
        SecurityLevel.MODERATOR: {
            'warn', 'warnings', 'clearwarnings', 'setlogchannel',
            'greet', 'welcome', 'leave', 'disable', 'embed', 'add', 'remove'  # greet & inorep subcommands
        },
        
        # ADMIN - Requires administrator permission or bot owner
        SecurityLevel.ADMIN: {
            'purge', 'humans', 'bots', 'media', 'embeds', 'all', 'user', 'contains',  # purge subcommands
            'nsfwban', 'nsfwunban', 'modconfig', 'overrule', 'modstats'
        },
        
        # OWNER - Bot owners only
        SecurityLevel.OWNER: {
            'testowner', 'processold', 'bestweek', 'bestmonth', 'bestyear', 'dbstatus',
            'backfillmessages', 'testbest', 'updatescore', 'debugreactions', 'youtube', 'list', 'add',
            'remove', 'test', 'help', 'validate', 'createevent', 'endevent',
            'debug_events', 'force_check_expired', 'process_old_reactions', 
            'rebuild_likes_db', 'test_bookmark', 'clear_bookmarks'
        }
    }
    
    @staticmethod
    def get_command_security_level(command_name: str) -> SecurityLevel:
        """Get the security level for a command"""
        for level, commands in CommandSecurity.COMMAND_PERMISSIONS.items():
            if command_name.lower() in commands:
                return level
        
        # Default to ADMIN for unknown commands (secure by default)
        logger.warning(f"Unknown command '{command_name}' defaulting to ADMIN security level")
        return SecurityLevel.ADMIN
    
    @staticmethod
    async def check_permissions(ctx, required_level: SecurityLevel) -> tuple[bool, str]:
        """
        Check if user has required permissions for the security level
        Returns (is_allowed, error_message)
        """
        user = ctx.author
        
        if Config.SANDBOX_MODE:
            channel_id = getattr(getattr(ctx, "channel", None), "id", None)
            if not Config.is_sandbox_channel_allowed(channel_id):
                return False, "This bot is only available in the approved sandbox channels."

            if required_level != SecurityLevel.PUBLIC:
                return False, "Sandbox mode only allows public persona/community commands."

        # Bot owners can always use any command outside sandbox mode
        if await ctx.bot.is_owner(user):
            return True, ""
        
        # PUBLIC commands - anyone can use
        if required_level == SecurityLevel.PUBLIC:
            return True, ""
        
        # Check guild context for permission-based commands
        if not ctx.guild:
            return False, "❌ This command can only be used in a server."
        
        # MODERATOR level - requires manage_guild permission or specific roles
        if required_level == SecurityLevel.MODERATOR:
            # Administrators have all moderator permissions
            if user.guild_permissions.administrator:
                return True, ""
            
            # Check manage_guild permission
            if user.guild_permissions.manage_guild:
                return True, ""
            
            # Check for specific moderator roles (NSFWBAN moderator role)
            if hasattr(Config, 'NSFWBAN_MODERATOR_ROLE_ID'):
                moderator_role = discord.utils.get(user.roles, id=Config.NSFWBAN_MODERATOR_ROLE_ID)
                if moderator_role:
                    return True, ""
            
            return False, "You need **Manage Server** permission or a moderator role to use this command."
        
        # ADMIN level - requires administrator permission
        if required_level == SecurityLevel.ADMIN:
            if user.guild_permissions.administrator:
                return True, ""
            
            return False, "You need **Administrator** permission to use this command."
        
        # OWNER level - bot owners only
        if required_level == SecurityLevel.OWNER:
            return False, "This command is restricted to bot owners only."
        
        return False, "Unknown permission level."
    
    @staticmethod
    def require_security_level(level: SecurityLevel):
        """
        Decorator to enforce security level on commands
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(ctx, *args, **kwargs):
                # Check permissions
                is_allowed, error_message = await CommandSecurity.check_permissions(ctx, level)
                
                if not is_allowed:
                    # Send error message based on command type
                    if hasattr(ctx, 'followup'):
                        await ctx.followup.send(error_message, ephemeral=True)
                    else:
                        await ctx.send(error_message, ephemeral=True)
                    return
                
                # Execute the original command
                return await func(ctx, *args, **kwargs)
            
            return wrapper
        return decorator
    
    @staticmethod
    def secure_command(command_name: str = None):
        """
        Decorator that automatically applies security based on command name
        """
        def decorator(func):
            # Determine command name
            cmd_name = command_name or func.__name__.replace('_command', '').replace('_cmd', '')
            
            # Get security level for this command
            security_level = CommandSecurity.get_command_security_level(cmd_name)
            
            # Apply security decorator
            return CommandSecurity.require_security_level(security_level)(func)
        
        return decorator
    
    @staticmethod
    def get_security_info(command_name: str) -> dict:
        """Get human-readable security information for a command"""
        level = CommandSecurity.get_command_security_level(command_name)
        
        info = {
            'level': level.value,
            'description': '',
            'required_permissions': []
        }
        
        if level == SecurityLevel.PUBLIC:
            info['description'] = "Available to everyone"
            info['required_permissions'] = ["None"]
        elif level == SecurityLevel.MODERATOR:
            info['description'] = "Requires moderation permissions"
            info['required_permissions'] = ["Manage Server permission", "OR Moderator role"]
        elif level == SecurityLevel.ADMIN:
            info['description'] = "Requires administrative permissions"
            info['required_permissions'] = ["Administrator permission", "OR Bot owner"]
        elif level == SecurityLevel.OWNER:
            info['description'] = "Bot owners only"
            info['required_permissions'] = ["Bot owner status"]
        
        return info
    
    @staticmethod
    async def get_user_rank(user: discord.Member, bot) -> SecurityLevel:
        """
        Get the effective rank/security level of a user
        Returns the highest rank the user has
        """
        # Bot owners are highest rank
        if await bot.is_owner(user):
            return SecurityLevel.OWNER
        
        # Check for administrator permission
        if user.guild_permissions.administrator:
            return SecurityLevel.ADMIN
        
        # Check for moderator permissions
        if user.guild_permissions.manage_guild:
            return SecurityLevel.MODERATOR
        
        # Check for specific moderator roles
        if hasattr(Config, 'NSFWBAN_MODERATOR_ROLE_ID'):
            moderator_role = discord.utils.get(user.roles, id=Config.NSFWBAN_MODERATOR_ROLE_ID)
            if moderator_role:
                return SecurityLevel.MODERATOR
        
        # Default to public
        return SecurityLevel.PUBLIC
    
    @staticmethod
    async def can_modify_user(moderator: discord.Member, target: discord.Member, bot) -> tuple[bool, str]:
        """
        Check if a moderator can modify a target user (for InoRep, warnings, etc.)
        Returns (can_modify, error_message)
        """
        # Get ranks
        moderator_rank = await CommandSecurity.get_user_rank(moderator, bot)
        target_rank = await CommandSecurity.get_user_rank(target, bot)
        
        # Bot owners can modify anyone (including other owners)
        if moderator_rank == SecurityLevel.OWNER:
            return True, ""
        
        # Define rank hierarchy (higher number = higher rank)
        rank_values = {
            SecurityLevel.PUBLIC: 0,
            SecurityLevel.MODERATOR: 1,
            SecurityLevel.ADMIN: 2,
            SecurityLevel.OWNER: 3
        }
        
        moderator_rank_value = rank_values.get(moderator_rank, 0)
        target_rank_value = rank_values.get(target_rank, 0)
        
        # Can't modify someone of equal or higher rank
        if target_rank_value >= moderator_rank_value:
            if target_rank == SecurityLevel.OWNER:
                return False, "❌ You cannot modify the reputation of a bot owner!"
            elif target_rank == SecurityLevel.ADMIN:
                return False, "❌ You cannot modify the reputation of an administrator!"
            elif target_rank == SecurityLevel.MODERATOR:
                return False, "❌ You cannot modify the reputation of another moderator!"
        
        return True, ""

# Convenience decorators for common security levels
def public_command(func):
    """Decorator for public commands (anyone can use)"""
    return CommandSecurity.require_security_level(SecurityLevel.PUBLIC)(func)

def moderator_command(func):
    """Decorator for moderator commands"""
    return CommandSecurity.require_security_level(SecurityLevel.MODERATOR)(func)

def admin_command(func):
    """Decorator for admin commands"""
    return CommandSecurity.require_security_level(SecurityLevel.ADMIN)(func)

def owner_command(func):
    """Decorator for owner-only commands"""
    return CommandSecurity.require_security_level(SecurityLevel.OWNER)(func)
