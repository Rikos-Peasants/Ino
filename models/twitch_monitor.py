import logging
import aiohttp
import discord
from discord.ext import commands
from typing import Optional, Dict, List, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from models.mongo_leaderboard_manager import MongoLeaderboardManager

logger = logging.getLogger(__name__)

class TwitchMonitor:
    """Monitors Twitch channels for live streams and generates simple announcements."""
    
    def __init__(self, mongodb_manager: Optional['MongoLeaderboardManager'] = None):
        self.monitored_channels: List[Dict[str, Any]] = []
        self.mongodb_manager = mongodb_manager
        self.bot: Optional[commands.Bot] = None
        
        from config import Config
        self.client_id = Config.TWITCH_CLIENT
        self.client_secret = Config.TWITCH_SECRET
        self.access_token = None
        self.token_expires_at = 0

    async def get_access_token(self) -> Optional[str]:
        """Fetch or refresh Twitch App Access Token."""
        if not self.client_id or not self.client_secret:
            logger.error("Twitch Client ID or Secret not configured.")
            return None
            
        import time
        if self.access_token and time.time() < self.token_expires_at:
            return self.access_token
            
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://id.twitch.tv/oauth2/token?client_id={self.client_id}&client_secret={self.client_secret}&grant_type=client_credentials"
                async with session.post(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.access_token = data.get('access_token')
                        self.token_expires_at = time.time() + data.get('expires_in', 3600) - 60
                        logger.info("Successfully fetched Twitch access token.")
                        return self.access_token
                    else:
                        text = await response.text()
                        logger.error(f"Failed to fetch Twitch access token: {text}")
                        return None
        except Exception as e:
            logger.error(f"Error fetching Twitch access token: {e}")
            return None

    async def load_monitored_channels(self):
        """Load monitored channels from MongoDB."""
        try:
            self.monitored_channels = []
            
            if self.mongodb_manager and hasattr(self.mongodb_manager, 'settings_collection'):
                if self.mongodb_manager.settings_collection is not None:
                    cursor = self.mongodb_manager.settings_collection.find({
                        "setting_name": {"$regex": "^twitch_monitor_"}
                    })
                    
                    for setting in cursor:
                        setting_value = setting.get('setting_value')
                        if setting_value and setting_value.get('enabled', True):
                            self.monitored_channels.append(setting_value)
                            
            if not self.monitored_channels:
                logger.info("No monitored Twitch channels found in database.")
                
            logger.info(f"Loaded {len(self.monitored_channels)} monitored Twitch channels from database.")
        except Exception as e:
            logger.error(f"Error loading monitored Twitch channels: {e}")
            self.monitored_channels = []

    async def add_monitored_channel(self, twitch_username: str, discord_channel_id: int, role_id: int, guild_id: int) -> bool:
        """Add a Twitch channel to monitor."""
        try:
            # Validate Twitch channel exists using Official API
            token = await self.get_access_token()
            if not token:
                logger.error("Cannot add channel without valid Twitch access token.")
                return False
                
            headers = {
                'Client-ID': self.client_id,
                'Authorization': f'Bearer {token}'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.twitch.tv/helix/users?login={twitch_username}", headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to validate Twitch user: {await response.text()}")
                        return False
                    data = await response.json()
                    if not data.get("data"):
                        logger.warning(f"Twitch channel not found: {twitch_username}")
                        return False
                    
                    twitch_username = data["data"][0]["login"]
            
            setting = {
                'twitch_username': twitch_username,
                'discord_channel_id': discord_channel_id,
                'role_id': role_id,
                'guild_id': guild_id,
                'is_live': False,
                'added_at': datetime.utcnow().isoformat(),
                'enabled': True
            }
            
            # Save to database
            if self.mongodb_manager:
                await self.mongodb_manager.set_guild_setting(
                    guild_id=guild_id,
                    setting_name=f"twitch_monitor_{twitch_username}",
                    setting_value=setting
                )
            
            # Update local memory (replace if already exists, else append)
            existing_idx = next((i for i, c in enumerate(self.monitored_channels) if c['twitch_username'] == twitch_username), None)
            if existing_idx is not None:
                self.monitored_channels[existing_idx] = setting
            else:
                self.monitored_channels.append(setting)
                
            logger.info(f"Added Twitch channel monitoring: {twitch_username} -> Discord channel {discord_channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding monitored Twitch channel: {e}")
            return False

    async def remove_monitored_channel(self, twitch_username: str) -> bool:
        """Remove a Twitch channel from monitoring."""
        try:
            channel_to_remove = next((c for c in self.monitored_channels if c['twitch_username'] == twitch_username), None)
            
            if not channel_to_remove:
                return False
            
            # Remove from database
            if self.mongodb_manager:
                await self.mongodb_manager.set_guild_setting(
                    guild_id=channel_to_remove['guild_id'],
                    setting_name=f"twitch_monitor_{twitch_username}",
                    setting_value=None
                )
            
            self.monitored_channels.remove(channel_to_remove)
            logger.info(f"Removed Twitch channel monitoring: {twitch_username}")
            return True
            
        except Exception as e:
            logger.error(f"Error removing monitored Twitch channel: {e}")
            return False

    async def update_channel_state(self, twitch_username: str, is_live: bool):
        """Update the live state of a channel to prevent duplicate pings."""
        for channel in self.monitored_channels:
            if channel['twitch_username'] == twitch_username:
                if channel.get('is_live') != is_live:
                    channel['is_live'] = is_live
                    if self.mongodb_manager:
                        await self.mongodb_manager.set_guild_setting(
                            guild_id=channel['guild_id'],
                            setting_name=f"twitch_monitor_{twitch_username}",
                            setting_value=channel
                        )
                break

    async def check_streams(self) -> List[Dict[str, Any]]:
        """Check all monitored Twitch channels for new live streams."""
        new_streams = []
        
        if not self.monitored_channels:
            return new_streams
            
        token = await self.get_access_token()
        if not token:
            return new_streams
            
        logger.info(f"Starting to check {len(self.monitored_channels)} Twitch channels for new streams")
        
        # Batch requests up to 100 logins at a time
        headers = {
            'Client-ID': self.client_id,
            'Authorization': f'Bearer {token}'
        }
        
        active_channels = [c for c in self.monitored_channels if c.get('enabled', True)]
        
        # Build query parameters
        query_params = []
        for channel in active_channels:
            query_params.append(f"user_login={channel['twitch_username']}")
            
        if not query_params:
            return new_streams
            
        chunk_size = 100
        for i in range(0, len(query_params), chunk_size):
            chunk = query_params[i:i+chunk_size]
            query_string = "&".join(chunk)
            
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"https://api.twitch.tv/helix/streams?{query_string}"
                    async with session.get(url, headers=headers) as response:
                        if response.status != 200:
                            logger.error(f"Failed to fetch streams: {await response.text()}")
                            continue
                            
                        data = await response.json()
                        streams_data = data.get("data", [])
                        
                        # Create a dictionary of live streams
                        live_streams = {stream["user_login"].lower(): stream for stream in streams_data if stream["type"] == "live"}
                        
                        for channel in active_channels:
                            username = channel['twitch_username'].lower()
                            # If we checked this username in this chunk
                            if f"user_login={username}" not in [q.lower() for q in chunk]:
                                continue
                                
                            is_currently_live = username in live_streams
                            was_live_previously = channel.get('is_live', False)
                            
                            if is_currently_live and not was_live_previously:
                                logger.info(f"Twitch channel {username} just went live!")
                                stream_info = live_streams[username]
                                
                                stream_data = {
                                    'twitch_username': stream_info.get("user_name", username),
                                    'title': stream_info.get("title", "Streaming Now"),
                                    'game': stream_info.get("game_name", ""),
                                    'link': f"https://www.twitch.tv/{username}",
                                    'config': channel
                                }
                                new_streams.append(stream_data)
                                
                            elif not is_currently_live and was_live_previously:
                                logger.info(f"Twitch channel {username} went offline.")
                                await self.update_channel_state(username, False)
                                
            except Exception as e:
                logger.error(f"Error checking Twitch streams: {e}")
                
        return new_streams

    async def get_monitored_channels_list(self) -> List[Dict[str, Any]]:
        """Get list of all monitored Twitch channels."""
        await self.load_monitored_channels()
        return self.monitored_channels

    async def announce_stream(self, stream: Dict[str, Any]):
        """Announce a Twitch stream to Discord."""
        try:
            config = stream.get('config', {})
            discord_channel_id = config.get('discord_channel_id')
            guild_id = config.get('guild_id')
            role_id = config.get('role_id')
            
            if not discord_channel_id or not guild_id:
                logger.error(f"Missing Discord channel ID or guild ID in config: {config}")
                return
            
            if not self.bot:
                logger.error("Bot instance not available for Discord operations")
                return
            
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logger.error(f"Could not find guild {guild_id}")
                return
            
            channel = guild.get_channel(discord_channel_id)
            if not channel:
                logger.error(f"Could not find Discord channel {discord_channel_id} in guild {guild_id}")
                return
                
            username = stream['twitch_username']
            title = stream['title']
            link = stream['link']
            game = stream.get('game', '')
            
            role_mention = f"<@&{role_id}>" if role_id else ""
            
            # Simple text announcement as requested
            game_text = f" playing **{game}**" if game else ""
            msg = f"Hey {role_mention}, **{username}** is live on Twitch{game_text}!\n\n**{title}**\n{link}"
            
            # Remove any double spaces
            msg = " ".join(msg.split())
            msg = msg.replace(" \n", "\n")
            
            await channel.send(msg)
            
            # Update state to prevent duplicate pings
            await self.update_channel_state(username, True)
            logger.info(f"Successfully announced Twitch stream for {username}")
            
        except Exception as e:
            logger.error(f"Error sending Twitch announcement for {stream.get('twitch_username')}: {e}")
