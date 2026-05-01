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
    TWITCH_CLIENT = os.getenv('TWITCH_CLIENT')
    TWITCH_SECRET = os.getenv('TWITCH_SECRET')
    
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
    
    # Channel monitoring
    PROJECTS_CHANNEL_ID = 1278117139428933645  # Channel with all projects of rayen
    HELP_ROLE_ID = 1347922925218435114  # Role to ping for help requests
    FORUM_CHANNEL_ID = 1426180987234287687  # Forum channel for automated pings on thread creation
    
    # Ask and complain to staff channel
    ASK_COMPLAIN_STAFF_CHANNEL_ID = 1426179557299453972  # Ask and complain to staff forum channel
    STAFF_ROLE_ID = 1372477845997359244  # Staff role to ping for all threads

    # Self-promotion moderation
    SELF_PROMO_WHITELIST_THREAD_ID = 1345520586012754001  # Thread where Discord invite links are allowed
    
    # Staff member IDs for specific pings
    STAFF_MEMBERS = {
        "Angel": 226050139226112000,
        "Mitch": 784822151529627708,
        "Seika": 742066956194152449,
        "Taishi": 121269547452989440
    }

    # Safety monitoring DM targets
    SAFETY_DM_USER_IDS = [
        742066956194152449,
        784822151529627708
    ]
    
    # Tag to title prefix mapping for staff forum auto-formatting
    STAFF_FORUM_TAG_PREFIXES = {
        "Complaint": "[Complaint]",
        "Suggestion": "[Suggestion]", 
        "Warning Appeal": "[Appeal]"
    }
    
    # YouTube monitoring roles
    YOUTUBE_ROLE_ID = 1375737416325009552  # Default role for YouTube videos
    SHORTS_ROLE_ID = 1392619703603822773  # Role to ping for short videos
    SHORT_VIDEO_MAX_SECONDS = 90  # Videos up to 1m30s use the short-video ping

    # Rayen YouTube subscriber-era roles
    RAYEN_YOUTUBE_CHANNEL_ID = "UChhMeymAOC5PNbbnqxD_w4g"
    YOUTUBE_SUB_ROLE_TIERS = [
        {"min_subs": 0, "max_subs": 49, "role_id": 1498718228707410132, "label": "0 - 50 subs"},
        {"min_subs": 50, "max_subs": 99, "role_id": 1498720787224330292, "label": "50 - 100 subs"},
        {"min_subs": 100, "max_subs": 499, "role_id": 1498720952614256711, "label": "100 - 500 subs"},
        {"min_subs": 500, "max_subs": 999, "role_id": 1498720952614256711, "label": "500 - 1000 subs"},
        {"min_subs": 1000, "max_subs": 1999, "role_id": 1498721031810973696, "label": "1000 - 2000 subs"},
        {"min_subs": 2000, "max_subs": 4999, "role_id": 1498721488914616360, "label": "2000 - 5000 subs"},
        {"min_subs": 5000, "max_subs": 9999, "role_id": 1498721627712782478, "label": "5000 - 10000 subs"},
        {"min_subs": 10000, "max_subs": 19999, "role_id": 1498721717462503514, "label": "10000 - 20000 subs"},
        {"min_subs": 20000, "max_subs": 49999, "role_id": 1498721915458814053, "label": "20000 - 50000 subs"},
        {"min_subs": 50000, "max_subs": None, "role_id": 1498723293044146228, "label": "50000+ subs"},
    ]
    # Historical milestones. Null dates are ignored until filled in.
    YOUTUBE_SUB_MILESTONE_DATES = [
        {"subs": 0, "reached_at": "2024-05-22T00:00:00Z"},
        {"subs": 50, "reached_at": "2024-07-01T00:00:00Z"},
        {"subs": 100, "reached_at": "2024-08-25T00:00:00Z"},
        {"subs": 200, "reached_at": "2024-09-22T00:00:00Z"},
        {"subs": 300, "reached_at": "2024-10-08T00:00:00Z"},
        {"subs": 400, "reached_at": "2024-10-15T00:00:00Z"},
        {"subs": 500, "reached_at": "2024-10-22T00:00:00Z"},
        {"subs": 600, "reached_at": "2024-11-02T00:00:00Z"},
        {"subs": 700, "reached_at": "2024-11-09T00:00:00Z"},
        {"subs": 800, "reached_at": "2024-11-23T00:00:00Z"},
        {"subs": 900, "reached_at": "2024-12-06T00:00:00Z"},
        {"subs": 1000, "reached_at": "2024-12-20T00:00:00Z"},
        {"subs": 2000, "reached_at": "2025-03-04T00:00:00Z"},
        {"subs": 3000, "reached_at": "2025-03-21T00:00:00Z"},
        {"subs": 4000, "reached_at": "2025-04-16T00:00:00Z"},
        {"subs": 5000, "reached_at": "2025-07-06T00:00:00Z"},
        {"subs": 6000, "reached_at": "2025-07-20T00:00:00Z"},
        {"subs": 7000, "reached_at": "2025-07-25T00:00:00Z"},
        {"subs": 8000, "reached_at": "2025-08-02T00:00:00Z"},
        {"subs": 9000, "reached_at": "2025-08-11T00:00:00Z"},
        {"subs": 10000, "reached_at": "2025-08-18T00:00:00Z"},
        {"subs": 11000, "reached_at": "2025-09-02T00:00:00Z"},
        {"subs": 12000, "reached_at": "2025-09-25T00:00:00Z"},
        {"subs": 13000, "reached_at": "2025-09-30T00:00:00Z"},
        {"subs": 14000, "reached_at": "2025-12-15T00:00:00Z"},
        {"subs": 15000, "reached_at": "2026-01-05T00:00:00Z"},
        {"subs": 16000, "reached_at": "2026-01-12T00:00:00Z"},
        {"subs": 17000, "reached_at": "2026-01-19T00:00:00Z"},
        {"subs": 18000, "reached_at": "2026-01-19T00:00:00Z"},
        {"subs": 19000, "reached_at": "2026-01-19T00:00:00Z"},
        {"subs": 20000, "reached_at": "2026-01-19T00:00:00Z"},
        {"subs": 21000, "reached_at": "2026-01-19T00:00:00Z"},
        {"subs": 22000, "reached_at": "2026-01-26T00:00:00Z"},
        {"subs": 23000, "reached_at": "2026-01-26T00:00:00Z"},
        {"subs": 24000, "reached_at": "2026-01-26T00:00:00Z"},
        {"subs": 25000, "reached_at": "2026-02-02T00:00:00Z"},
        {"subs": 26000, "reached_at": "2026-02-02T00:00:00Z"},
        {"subs": 27000, "reached_at": "2026-02-09T00:00:00Z"},
        {"subs": 28000, "reached_at": "2026-02-16T00:00:00Z"},
        {"subs": 29000, "reached_at": "2026-02-23T00:00:00Z"},
        {"subs": 30000, "reached_at": "2026-04-06T00:00:00Z"},
        {"subs": 31000, "reached_at": "2026-04-12T00:00:00Z"},
        {"subs": 32000, "reached_at": "2026-04-17T00:00:00Z"},
        {"subs": 33000, "reached_at": "2026-04-23T00:00:00Z"},
        {"subs": 34000, "reached_at": "2026-04-25T00:00:00Z"},
    ]
    
    # Warning log channel (can be configured with /setlogchannel)
    WARNING_LOG_CHANNEL_ID: Optional[int] = None  # Will be set dynamically
    
    # Art Challenge System Configuration
    # SFW channel gets "safe" rated images only
    ART_CHALLENGE_CHANNEL_SFW = 1282209034916855809
    # NSFW channel gets "questionable" rated images (not explicit)
    ART_CHALLENGE_CHANNEL_NSFW = 1378693276206370969
    ART_CHALLENGE_CHANNELS = [
        ART_CHALLENGE_CHANNEL_SFW,
        ART_CHALLENGE_CHANNEL_NSFW
    ]
    ART_CHALLENGE_DURATION_HOURS = 4  # Each challenge lasts 4 hours
    ART_CHALLENGE_BASE_REWARD = 50  # Base points for completing a challenge
    # Art Challenge Schedule (UTC times when challenges START)
    ART_CHALLENGE_START_TIMES = [2, 8, 14, 20]  # 02:00, 08:00, 14:00, 20:00 UTC
    
    # Serika.art API Configuration  
    SERIKA_ART_KEY = os.getenv('SERIKA_ART_KEY')
    SERIKA_ART_URL_BASE = os.getenv('SERIKA_ART_URL_BASE', 'https://serika.art/api/v1')
    
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
            ('YOUTUBE_API_KEY', cls.YOUTUBE_API_KEY),
            ('SERIKA_ART_KEY', cls.SERIKA_ART_KEY)
        ]
        
        missing_vars = [var_name for var_name, var_value in required_vars if not var_value]
        missing_optional = [var_name for var_name, var_value in optional_vars if not var_value]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        if missing_optional:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Missing optional environment variables (some features may not work): {', '.join(missing_optional)}")
