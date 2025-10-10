import os
from dotenv import load_dotenv
from typing import Optional, List

# Load environment variables
load_dotenv()

def get_int_env(key: str, default: Optional[int] = None) -> int:
    """Get an integer from environment variables with proper error handling"""
    value = os.getenv(key)
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"Environment variable {key} is required but not set")
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Environment variable {key} must be a valid integer, got: {value}")

class Config:
    # Command prefix for text commands
    COMMAND_PREFIX = os.getenv('COMMAND_PREFIX', 'R!')
    TOKEN = os.getenv('DISCORD_TOKEN')
    GUILD_ID = get_int_env('GUILD_ID')
    BANNED_ROLE_ID = get_int_env('BANNED_ROLE_ID')
    RESTRICTED_ROLE_ID = get_int_env('RESTRICTED_ROLE_ID')
    MONGO_URI = os.getenv('MONGO_URI')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')  # For YouTube video announcements
    YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')  # For YouTube Data API
    OPENAI_KEY = os.getenv('OPENAI_KEY')  # For content moderation (primary)
    GOOGLE_NL_API_KEY = os.getenv('GOOGLE_NL_API_KEY')  # For secondary moderation check
    
    # Moderation system default role IDs (can be configured per guild)
    DEFAULT_MODERATION_REVIEW_ROLE_ID = 1372477845997359244  # Seraphs role (default reviewers)
    DEFAULT_MODERATION_ADMIN_ROLE_ID = 1282192809746628658   # Admin role (default overrule)
    
    # NSFWBAN system role IDs
    NSFWBAN_MODERATOR_ROLE_ID = 1372477845997359244  # Role that can use nsfwban commands
    NSFWBAN_BANNED_ROLE_ID = get_int_env('BANNED_ROLE_ID')  # Role given to NSFWBAN'd users (same as BANNED_ROLE_ID)
    
    # Patreon system
    PATREON_ROLE_ID = get_int_env('PATREON_ROLE_ID', None)  # "Riko's Agent" role for Patreon supporters (1.5x quest points)
    PATREON_URL = "https://www.patreon.com/RayenAI"  # Patreon page URL
    PATREON_POINTS_MULTIPLIER = 1.5  # Points multiplier for Patreon supporters
    
    # Image reaction channels
    IMAGE_REACTION_CHANNELS = [
        1282209034916855809,
        1378693276206370969
    ]
    
    # Chat channels for redirecting conversations (also booster channels for 2x points)
    CHAT_CHANNELS = [
        1278117139428933647,
        1278117139428933649
    ]
    
    # Booster text channels (2 points per message instead of 1)
    BOOSTER_TEXT_CHANNELS = [
        1278117139428933647,
        1278117139428933649
    ]
    
    # Voice channel exclusions (no points earned in these channels)
    EXCLUDED_VOICE_CHANNELS = [
        1282209583086964766,
        1424015547661811945
    ]
    
    # Point system configuration
    POINTS_PER_MESSAGE = 1  # Regular text channels
    POINTS_PER_MESSAGE_BOOSTER = 2  # Booster text channels
    POINTS_PER_MINUTE_VC = 2  # Voice channel participation
    
    # Help channel monitoring
    HELP_CHANNEL_ID = 1301366087975178312  # "I need help" channel
    PROJECTS_CHANNEL_ID = 1278117139428933645  # Channel with all projects of rayen
    HELP_ROLE_ID = 1347922925218435114  # Role to ping for help requests
    FORUM_CHANNEL_ID = 1426180987234287687  # Forum channel for automated pings on thread creation
    
    # YouTube monitoring roles
    YOUTUBE_ROLE_ID = 1375737416325009552  # Default role for YouTube videos
    SHORTS_ROLE_ID = 1392619703603822773  # Role to ping for YouTube Shorts (≤60 seconds)
    
    # Warning log channel (can be configured with /setlogchannel)
    WARNING_LOG_CHANNEL_ID: Optional[int] = None  # Will be set dynamically
    
    @classmethod
    def validate(cls):
        """Validate that all required environment variables are set"""
        required_vars = [
            ('DISCORD_TOKEN', cls.TOKEN),
            ('GUILD_ID', cls.GUILD_ID),
            ('BANNED_ROLE_ID', cls.BANNED_ROLE_ID),
            ('RESTRICTED_ROLE_ID', cls.RESTRICTED_ROLE_ID),
            ('MONGO_URI', cls.MONGO_URI)
        ]
        
        # Optional but recommended vars
        optional_vars = [
            ('OPENAI_KEY', cls.OPENAI_KEY),
            ('GOOGLE_NL_API_KEY', cls.GOOGLE_NL_API_KEY),
            ('GEMINI_API_KEY', cls.GEMINI_API_KEY),
            ('YOUTUBE_API_KEY', cls.YOUTUBE_API_KEY)
        ]
        
        missing_vars = [var_name for var_name, var_value in required_vars if not var_value]
        missing_optional = [var_name for var_name, var_value in optional_vars if not var_value]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        if missing_optional:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Missing optional environment variables (some features may not work): {', '.join(missing_optional)}")