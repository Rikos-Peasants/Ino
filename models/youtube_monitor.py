import os
import asyncio
import feedparser
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, TYPE_CHECKING
import logging
import re

# Optional Google SDKs: import lazily/defensively so module import never fails
try:  # New Google AI Python SDK (google-genai)
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore
except Exception:  # Library not installed or incompatible
    genai = None  # type: ignore
    types = None  # type: ignore

try:  # YouTube Data API client
    from googleapiclient.discovery import build  # type: ignore
except Exception:
    build = None  # type: ignore

from config import Config
import discord
from discord.ext import commands
import aiohttp
from models.gemini_utils import describe_gemini_response, extract_gemini_text

if TYPE_CHECKING:
    from models.mongo_leaderboard_manager import MongoLeaderboardManager

logger = logging.getLogger(__name__)

class YouTubeMonitor:
    """Monitors YouTube channels for new videos and generates Ino responses"""
    
    def __init__(self, mongodb_manager: Optional['MongoLeaderboardManager'] = None):
        self.monitored_channels: List[Dict[str, Any]] = []
        self.mongodb_manager = mongodb_manager
        self.gemini_api_key = Config.GEMINI_API_KEY if hasattr(Config, 'GEMINI_API_KEY') and Config.GEMINI_API_KEY else None
        self.guild_id = Config.GUILD_ID
        self.bot: Optional[commands.Bot] = None
        
        # Initialize YouTube API client (if available)
        self.youtube_api_key = Config.YOUTUBE_API_KEY if hasattr(Config, 'YOUTUBE_API_KEY') and Config.YOUTUBE_API_KEY else None
        self.youtube_client = None
        if self.youtube_api_key and build is not None:
            try:
                self.youtube_client = build('youtube', 'v3', developerKey=self.youtube_api_key)
                logger.info("✅ YouTube API client initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize YouTube API client: {e}")
                self.youtube_client = None
        elif self.youtube_api_key and build is None:
            logger.warning("google-api-python-client not installed; using RSS fallback for YouTube")
        else:
            logger.warning("No YouTube API key found - will use RSS fallback")
        
        # Configure Gemini AI if API key and SDK are available
        self.gemini_client = None
        if self.gemini_api_key:
            if genai is None:
                logger.warning("google-genai SDK not installed; using non-AI fallback responses")
            else:
                try:
                    self.gemini_client = genai.Client(api_key=self.gemini_api_key)  # type: ignore[attr-defined]
                    logger.info("Gemini AI configured successfully")
                except Exception as e:
                    logger.error(f"Failed to configure Gemini AI: {e}")
                    self.gemini_api_key = None
                    self.gemini_client = None
        else:
            logger.warning("No Gemini API key found - Ino responses will use fallback templates")

        # Note: monitored channels will be loaded later when an event loop is available

    async def load_monitored_channels(self):
        """Load monitored channels from MongoDB"""
        try:
            self.monitored_channels = []
            
            # Look for all settings that start with "youtube_monitor_"
            if self.mongodb_manager and hasattr(self.mongodb_manager, 'settings_collection'):
                try:
                    # Check if settings_collection exists before using it
                    if self.mongodb_manager.settings_collection is not None:
                        cursor = self.mongodb_manager.settings_collection.find({
                            "setting_name": {"$regex": "^youtube_monitor_UC"}
                        })
                        
                        for setting in cursor:  # Use synchronous iteration
                            setting_value = setting.get('setting_value')
                            if setting_value and setting_value.get('enabled', True):
                                self.monitored_channels.append({
                                    'youtube_channel_id': setting_value['youtube_channel_id'],
                                    'discord_channel_id': setting_value['discord_channel_id'],
                                    'guild_id': setting_value['guild_id'],
                                    'enabled': True
                                })
                except Exception as e:
                    logger.warning(f"Error loading monitored channels from database: {e}")
                    
            if not self.monitored_channels:
                # Fallback to default config if no channels found
                logger.info("No monitored channels found in database")
                
            logger.info(f"Loaded {len(self.monitored_channels)} monitored YouTube channels from database")
        except Exception as e:
            logger.error(f"Error loading monitored channels: {e}")
            self.monitored_channels = []

    async def add_monitored_channel(self, youtube_channel_id: str, discord_channel_id: int, guild_id: int) -> bool:
        """Add a YouTube channel to monitor"""
        try:
            # Validate YouTube channel exists
            channel_info = await self.get_channel_info(youtube_channel_id)
            if not channel_info:
                return False
            
            # Store in database
            setting = {
                'youtube_channel_id': youtube_channel_id,
                'discord_channel_id': discord_channel_id,
                'guild_id': guild_id,
                'channel_name': channel_info.get('title', 'Unknown'),
                'added_at': datetime.utcnow().isoformat(),
                'last_video_id': None,
                'last_check': datetime.utcnow().isoformat(),  # Set current time to prevent old video spam
                'enabled': True
            }
            
            # Save to database as a setting
            if self.mongodb_manager:
                await self.mongodb_manager.set_guild_setting(
                    guild_id=guild_id,
                    setting_name=f"youtube_monitor_{youtube_channel_id}",
                    setting_value=setting
                )
            
            self.monitored_channels.append(setting)
            logger.info(f"Added YouTube channel monitoring: {channel_info.get('title')} -> Discord channel {discord_channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding monitored channel: {e}")
            return False

    async def remove_monitored_channel(self, youtube_channel_id: str) -> bool:
        """Remove a YouTube channel from monitoring"""
        try:
            # Find the channel in our list
            channel_to_remove = None
            for channel in self.monitored_channels:
                if channel['youtube_channel_id'] == youtube_channel_id:
                    channel_to_remove = channel
                    break
            
            if not channel_to_remove:
                return False
            
            # Remove from database
            if self.mongodb_manager:
                await self.mongodb_manager.set_guild_setting(
                    guild_id=channel_to_remove['guild_id'],
                    setting_name=f"youtube_monitor_{youtube_channel_id}",
                    setting_value=None  # Setting to None removes it
                )
            
            self.monitored_channels.remove(channel_to_remove)
            logger.info(f"Removed YouTube channel monitoring: {youtube_channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error removing monitored channel: {e}")
            return False

    async def get_channel_info(self, youtube_channel_id: str) -> Optional[Dict[str, Any]]:
        """Get basic info about a YouTube channel using YouTube API"""
        try:
            if not self.youtube_client:
                logger.warning("YouTube API client not available, falling back to RSS")
                return await self._get_channel_info_rss(youtube_channel_id)
            
            # Use YouTube API to get channel info
            logger.info(f"Checking YouTube channel: {youtube_channel_id}")
            
            request = self.youtube_client.channels().list(
                part='snippet,statistics',
                id=youtube_channel_id
            )
            response = request.execute()
            
            if response['items']:
                channel = response['items'][0]
                channel_info = {
                    'title': channel['snippet']['title'],
                    'link': f"https://www.youtube.com/channel/{youtube_channel_id}",
                    'description': channel['snippet']['description'],
                    'thumbnail': channel['snippet']['thumbnails']['default']['url'],
                    'subscriber_count': channel['statistics'].get('subscriberCount', 'Unknown'),
                    'video_count': channel['statistics'].get('videoCount', 'Unknown')
                }
                logger.info(f"Channel info retrieved via API: {channel_info['title']}")
                return channel_info
            else:
                logger.warning(f"No channel found with ID {youtube_channel_id}")
                return None
            
        except Exception as e:
            logger.error(f"Error getting channel info via API for {youtube_channel_id}: {e}")
            # Fallback to RSS
            return await self._get_channel_info_rss(youtube_channel_id)

    async def _get_channel_info_rss(self, youtube_channel_id: str) -> Optional[Dict[str, Any]]:
        """Fallback method to get channel info using RSS feed"""
        try:
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={youtube_channel_id}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url) as response:
                    if response.status != 200:
                        return None
            
            feed = feedparser.parse(response.content)
            
            # Check if feed is valid and has content
            if hasattr(feed, 'feed') and hasattr(feed.feed, 'title'):
                if feed.entries or getattr(feed.feed, 'title', None):
                    channel_info = {
                        'title': getattr(feed.feed, 'title', 'Unknown Channel'),
                        'link': getattr(feed.feed, 'link', ''),
                        'description': getattr(feed.feed, 'description', ''),
                        'latest_video': feed.entries[0] if feed.entries else None
                    }
                    logger.info(f"Channel info retrieved via RSS: {channel_info['title']}")
                    return channel_info
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting channel info via RSS for {youtube_channel_id}: {e}")
            return None

    async def get_current_subscriber_count(self, youtube_channel_id: str) -> Optional[int]:
        """Get the current public subscriber count for a YouTube channel."""
        try:
            if not self.youtube_client:
                logger.warning("YouTube API client not available for subscriber count")
                return None

            request = self.youtube_client.channels().list(
                part='statistics',
                id=youtube_channel_id
            )
            response = request.execute()
            if not response.get('items'):
                return None

            return int(response['items'][0]['statistics'].get('subscriberCount', 0))
        except Exception as e:
            logger.error(f"Error getting subscriber count for {youtube_channel_id}: {e}")
            return None

    async def store_rayen_subscriber_snapshot(self) -> Optional[int]:
        """Store Rayen's current subscriber count for future historical role lookups."""
        try:
            sub_count = await self.get_current_subscriber_count(Config.RAYEN_YOUTUBE_CHANNEL_ID)
            if sub_count is None:
                return None

            if self.mongodb_manager and getattr(self.mongodb_manager, 'db', None) is not None:
                collection = self.mongodb_manager.db['youtube_sub_count_snapshots']
                collection.create_index([("channel_id", 1), ("captured_at", -1)])
                collection.insert_one({
                    "channel_id": Config.RAYEN_YOUTUBE_CHANNEL_ID,
                    "subscriber_count": sub_count,
                    "captured_at": discord.utils.utcnow(),
                })

            logger.info(f"Stored Rayen subscriber count snapshot: {sub_count}")
            return sub_count
        except Exception as e:
            logger.error(f"Error storing Rayen subscriber count snapshot: {e}")
            return None

    async def check_for_new_videos(self) -> List[Dict[str, Any]]:
        """Check all monitored channels for new videos using YouTube API"""
        new_videos = []
        
        logger.info(f"Starting to check {len(self.monitored_channels)} channels for new videos")
        
        for channel in self.monitored_channels:
            if not channel.get('enabled', True):
                continue
                
            try:
                youtube_channel_id = channel['youtube_channel_id']
                logger.debug(f"Checking for new videos from channel: {youtube_channel_id}")
                
                # Get recent videos using YouTube API (much faster than RSS)
                recent_videos = await self._get_recent_videos_api(youtube_channel_id)
                
                if not recent_videos:
                    logger.info(f"❌ No videos found for channel {youtube_channel_id}")
                    continue
                
                logger.debug(f"Found {len(recent_videos)} recent videos for channel {youtube_channel_id}")
                
                # Process videos (already sorted by publish date)
                videos_to_process = []
                
                for video_data in recent_videos:
                    video_id = video_data['id']
                    
                    # Check if video is too old (more than 12 hours)
                    published = video_data['published_datetime']
                    twelve_hours_ago = datetime.utcnow() - timedelta(hours=12)
                    
                    if published < twelve_hours_ago:
                        logger.debug(f"Skipping old video {video_id} ({video_data['title']}) - published {published}, older than 12 hours")
                        continue
                    else:
                        logger.debug(f"Video {video_id} ({video_data['title']}) is recent - published {published}")
                    
                    # Check if we've already processed this video
                    is_processed = await self.is_video_processed(video_id)
                    if is_processed:
                        logger.debug(f"Video {video_id} ({video_data['title']}) already processed, skipping")
                        continue
                    else:
                        logger.debug(f"Video {video_id} ({video_data['title']}) not processed yet, adding to queue")
                    
                    # Filter out YouTube Shorts - URL and keyword detection only
                    video_link = video_data.get('link', '')
                    
                    # Check 1: URL contains /shorts/
                    if '/shorts/' in video_link:
                        logger.debug(f"Skipping YouTube Short (URL): {video_data['title']} - {video_link}")
                        continue
                    
                    # Check 2: Title/description suggests it's a short
                    title_lower = video_data['title'].lower()
                    description_lower = video_data.get('description', '').lower()
                    short_indicators = ['#shorts', '#short', 'short video', 'youtube short', 'yt short']
                    
                    if any(indicator in title_lower for indicator in short_indicators):
                        logger.info(f"Skipping suspected YouTube Short (title): {video_data['title']}")
                        continue
                    
                    if any(indicator in description_lower for indicator in short_indicators):
                        logger.info(f"Skipping suspected YouTube Short (description): {video_data['title']}")
                        continue
                    
                    videos_to_process.append({
                        'id': video_id,
                        'title': video_data['title'],
                        'link': video_data['link'],
                        'published': video_data['published'],
                        'description': video_data['description'],
                        'author': video_data['author'],
                        'duration_seconds': video_data.get('duration_seconds', 0),
                        'config': {**channel, 'channel_id': youtube_channel_id}  # Include channel_id in config
                    })
                
                # Add new videos to the list (don't mark as processed yet - that happens after successful announcement)
                for video in videos_to_process:
                    new_videos.append(video)
                
                if videos_to_process:
                    logger.info(f"✅ Found {len(videos_to_process)} new videos for channel {youtube_channel_id}")
                else:
                    logger.info(f"❌ No new videos found for channel {youtube_channel_id}")
                
            except Exception as e:
                logger.error(f"❌ Error checking channel {youtube_channel_id}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        return new_videos

    async def _get_recent_videos_api(self, channel_id: str) -> List[Dict[str, Any]]:
        """Get recent videos from a channel using YouTube API"""
        try:
            if not self.youtube_client:
                logger.warning("YouTube API client not available, falling back to RSS")
                return await self._get_recent_videos_rss(channel_id)
            
            # Get the uploads playlist ID
            request = self.youtube_client.channels().list(
                part='contentDetails',
                id=channel_id
            )
            response = request.execute()
            
            if not response['items']:
                logger.warning(f"Channel {channel_id} not found")
                return []
            
            uploads_playlist_id = response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            
            # Get recent videos from uploads playlist
            request = self.youtube_client.playlistItems().list(
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=50  # Get up to 50 recent videos
            )
            response = request.execute()
            
            videos = []
            video_ids = []
            
            for item in response['items']:
                video_id = item['snippet']['resourceId']['videoId']
                video_ids.append(video_id)
                
                # Parse publish date
                published_str = item['snippet']['publishedAt']
                published_datetime = datetime.strptime(published_str, '%Y-%m-%dT%H:%M:%SZ')
                
                videos.append({
                    'id': video_id,
                    'title': item['snippet']['title'],
                    'description': item['snippet']['description'],
                    'published': published_str,
                    'published_datetime': published_datetime,
                    'link': f"https://www.youtube.com/watch?v={video_id}",
                    'author': item['snippet']['videoOwnerChannelTitle'],
                    'thumbnail': item['snippet']['thumbnails']['default']['url']
                })
            
            # Get video durations in batch
            if video_ids:
                request = self.youtube_client.videos().list(
                    part='contentDetails',
                    id=','.join(video_ids)
                )
                response = request.execute()
                
                # Parse durations and add to video data
                duration_map = {}
                for item in response['items']:
                    video_id = item['id']
                    duration_str = item['contentDetails']['duration']  # Format: PT4M13S
                    duration_seconds = self._parse_duration(duration_str)
                    duration_map[video_id] = duration_seconds
                
                # Add durations to video data
                for video in videos:
                    video['duration_seconds'] = duration_map.get(video['id'], 0)
            
            logger.info(f"Retrieved {len(videos)} videos via YouTube API for channel {channel_id}")
            return videos
            
        except Exception as e:
            logger.error(f"Error getting videos via API for channel {channel_id}: {e}")
            # Fallback to RSS
            return await self._get_recent_videos_rss(channel_id)

    def _parse_duration(self, duration_str: str) -> int:
        """Parse YouTube duration format (PT4M13S) to seconds"""
        try:
            # Remove PT prefix
            duration_str = duration_str[2:]
            
            # Extract hours, minutes, seconds
            hours = 0
            minutes = 0
            seconds = 0
            
            if 'H' in duration_str:
                hours = int(re.findall(r'(\d+)H', duration_str)[0])
            if 'M' in duration_str:
                minutes = int(re.findall(r'(\d+)M', duration_str)[0])
            if 'S' in duration_str:
                seconds = int(re.findall(r'(\d+)S', duration_str)[0])
            
            return hours * 3600 + minutes * 60 + seconds
        except:
            return 0

    def _get_duration_seconds(self, video: Dict[str, Any]) -> int:
        """Read duration from either current or legacy video payload keys."""
        duration = video.get('duration_seconds', video.get('duration', 0))
        try:
            return int(duration or 0)
        except (TypeError, ValueError):
            return 0

    def _is_short_video(self, video: Dict[str, Any]) -> bool:
        """Treat videos up to the configured 1m30s cutoff as short videos."""
        duration_seconds = self._get_duration_seconds(video)
        return 0 < duration_seconds <= Config.SHORT_VIDEO_MAX_SECONDS

    def _role_ping_for_video_type(self, is_short: bool) -> str:
        role_id = Config.SHORTS_ROLE_ID if is_short else Config.YOUTUBE_ROLE_ID
        return f"<@&{role_id}>"

    def _ensure_correct_role_ping(self, announcement: str, is_short: bool) -> str:
        """Force the final role mention to match the video duration bucket."""
        expected_ping = self._role_ping_for_video_type(is_short)
        cleaned = re.sub(r"<@&\d+>", "", announcement or "").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return f"{cleaned} {expected_ping}".strip()

    async def _get_recent_videos_rss(self, channel_id: str) -> List[Dict[str, Any]]:
        """Fallback method to get recent videos using RSS feed"""
        try:
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url) as response:
                    if response.status != 200:
                        return []
                    
                    content = await response.read()
            
            feed = feedparser.parse(content)
            videos = []
            for entry in feed.entries:
                # Extract video ID from the entry ID
                video_id = getattr(entry, 'id', '').split(':')[-1] if hasattr(entry, 'id') else ''
                if not video_id:
                    continue
                    
                # Parse published date
                published_str = getattr(entry, 'published', '')
                if published_str:
                    try:
                        published_datetime = datetime.strptime(published_str, '%Y-%m-%dT%H:%M:%S+00:00')
                    except ValueError:
                        # Try alternative format
                        try:
                            published_datetime = datetime.strptime(published_str, '%Y-%m-%dT%H:%M:%SZ')
                        except ValueError:
                            published_datetime = datetime.now()
                else:
                    published_datetime = datetime.now()
                
                videos.append({
                    'id': video_id,
                    'title': getattr(entry, 'title', 'Unknown Title'),
                    'link': getattr(entry, 'link', ''),
                    'published': published_str,
                    'published_datetime': published_datetime,
                    'author': getattr(entry, 'author', 'Unknown Author'),
                    'description': getattr(entry, 'summary', ''),
                    'channel_id': channel_id
                })
            
            logger.info(f"Retrieved {len(videos)} videos via RSS for channel {channel_id}")
            return videos
            
        except Exception as e:
            logger.error(f"Error getting videos via RSS for channel {channel_id}: {e}")
            return []

    async def get_recent_videos(self, youtube_channel_id: str) -> List[Dict[str, Any]]:
        """Get recent videos from a YouTube channel"""
        try:
            # Try RSS first (no API key needed)
            videos = await self._get_recent_videos_rss(youtube_channel_id)
            if videos:
                logger.debug(f"Got {len(videos)} videos via RSS for channel {youtube_channel_id}")
                return videos
            
            # Fallback to API if RSS fails and we have an API key
            if self.youtube_api_key:
                videos = await self._get_recent_videos_api(youtube_channel_id)
                if videos:
                    logger.debug(f"Got {len(videos)} videos via API for channel {youtube_channel_id}")
                    return videos
            
            logger.warning(f"Could not get videos for channel {youtube_channel_id}")
            return []
            
        except Exception as e:
            logger.error(f"Error getting recent videos for {youtube_channel_id}: {e}")
            return []

    async def generate_ino_response(self, video: Dict[str, Any], is_short: bool = False) -> Optional[str]:
        """Generate Ino's response to a new video using Gemini AI with video attachment"""
        try:
            if not self.gemini_client:
                logger.warning("No Gemini client available for response generation")
                # Use fallback template with proper role ping
                video_title = video.get('title', 'Unknown')
                channel_id = video.get('config', {}).get('channel_id', '')
                is_rayen_channel = channel_id == 'UChhMeymAOC5PNbbnqxD_w4g'
                
                # Choose appropriate role based on video type
                role_ping = self._role_ping_for_video_type(is_short)
                
                if is_rayen_channel:
                    return f"Oh my, Rayen uploaded something new: \"{video_title}\". Time to see what he's up to now, Riko simps. {role_ping}"
                else:
                    return f"Oh my, our digital fox uploaded something new: \"{video_title}\". Time to see what mischief she's up to now, Riko simps. {role_ping}"
            
            # Read the system prompt from file
            system_prompt = self.load_system_prompt()
            
            # Get video details
            video_title = video.get('title', 'Unknown')
            video_link = video.get('link', '')
            video_description = video.get('description', '')
            video_author = video.get('author', '')
            
            # Check if this is Rayen's channel
            channel_id = video.get('config', {}).get('channel_id', '')
            is_rayen_channel = channel_id == 'UChhMeymAOC5PNbbnqxD_w4g'
            
            # Create context-aware prompt
            channel_context = ""
            if is_rayen_channel:
                channel_context = "This video is from Rayen's channel. Rayen is Riko's human collaborator who creates content in the physical world since Riko is now a digital spirit."
            else:
                channel_context = "This video is from a channel associated with Riko, but since Riko is now a digital spirit trapped in the internet, physical videos are made by humans like Rayen or guest creators."
            
            # Create the content with video attachment
            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            file_data=types.FileData(
                                file_uri=video_link,
                                mime_type="video/*",
                            )
                        ),
                        types.Part.from_text(
                            text=f"""New video uploaded!

TITLE: {video_title}
UPLOADER/CREATOR: {video_author}
FULL DESCRIPTION: {video_description}
CHANNEL: {channel_context}

🚨 CRITICAL: RIKO IS DIGITAL - SHE CANNOT MAKE PHYSICAL VIDEOS! 🚨

The UPLOADER/CREATOR is: "{video_author}"
This is a HUMAN who made this physical video, NOT Riko!

CORRECT ATTRIBUTION:
- If uploader is "YOASOBI" → Say "YOASOBI performed"
- If uploader is "pikachubolk" → Say "pikachubolk created" 
- If uploader is "Rayen" → Say "Rayen made"
- If uploader is anyone else → Use THEIR name

WRONG ATTRIBUTION (NEVER DO THIS):
- "Riko performed" ❌
- "Our fox made this" ❌ 
- "Riko uploaded" ❌

Create a short announcement (10-20 words) using the ACTUAL creator's name "{video_author}", not Riko!

VIDEO TYPE: {'Short video (≤' + str(Config.SHORT_VIDEO_MAX_SECONDS) + ' seconds)' if is_short else 'Regular video (>' + str(Config.SHORT_VIDEO_MAX_SECONDS) + ' seconds)'}
ROLE TO PING: {self._role_ping_for_video_type(is_short)}

Remember to include the correct role ping at the end based on video type!
                        """),
                    ],
                ),
            ]
            
            generate_content_config = types.GenerateContentConfig(
                max_output_tokens=65536,
                response_mime_type="text/plain",
                system_instruction=[
                    types.Part.from_text(text=system_prompt),
                ],
            )
            
            # Generate response using the new API (non-streaming)
            response = self.gemini_client.models.generate_content(
                model="gemini-flash-latest",
                contents=contents,
                config=generate_content_config,
            )
            
            response_text = extract_gemini_text(response)
            if response_text:
                return response_text
            else:
                # Fallback to context-aware template
                logger.info(
                    "Using fallback Ino response template; empty Gemini response: %s",
                    describe_gemini_response(response),
                )
                return self._get_fallback_response(video_title, is_rayen_channel, video_author, is_short)
            
        except Exception as e:
            logger.error(f"Error generating Ino response: {e}")
            # Use context-aware fallbacks
            channel_id = video.get('config', {}).get('channel_id', '')
            is_rayen_channel = channel_id == 'UChhMeymAOC5PNbbnqxD_w4g'
            video_title = video.get('title', 'Unknown')
            video_author = video.get('author', 'Unknown')
            return self._get_fallback_response(video_title, is_rayen_channel, video_author, is_short)
    
    def _get_fallback_response(self, video_title: str, is_rayen_channel: bool, video_author: str = "Unknown", is_short: bool = False) -> str:
        """Get appropriate fallback response based on channel type and content"""
        # Choose appropriate role based on video type
        role_ping = self._role_ping_for_video_type(is_short)
        
        # Check if it's a guest/collaboration based on author name
        is_guest_content = video_author and video_author.lower() not in ['riko', 'rayen', 'just rayen', 'unknown']
        
        if is_guest_content:
            # Guest/collaboration content
            if 'cover' in video_title.lower():
                return f"Well, well... a cover by {video_author}: \"{video_title}\". The shrine approves of this offering. {role_ping}"
            else:
                return f"Oh my, {video_author} graced the channel with \"{video_title}\". How... refreshing. {role_ping}"
        elif 'cover' in video_title.lower():
            if is_rayen_channel:
                return f"Well, well... Rayen's covering something new: \"{video_title}\". His voice work shows promise. {role_ping}"
            else:
                return f"Well, well... new cover from our digital fox: \"{video_title}\". Her voice work shows promise. {role_ping}"
        elif any(word in video_title.lower() for word in ['game', 'gaming', 'play', 'minecraft', 'horror']):
            if is_rayen_channel:
                return f"I see Rayen uploaded another gaming adventure: \"{video_title}\". The volume levels are... enthusiastic. {role_ping}"
            else:
                return f"I see the fox uploaded another gaming adventure: \"{video_title}\". The volume levels are... enthusiastic. {role_ping}"
        elif any(word in video_title.lower() for word in ['tutorial', 'how to', 'guide', 'cook']):
            if is_rayen_channel:
                return f"Honestly, another tutorial from Rayen: \"{video_title}\". Let's see what survives this time. {role_ping}"
            else:
                return f"Honestly, another tutorial from that troublesome fox: \"{video_title}\". Let's see what survives this time. {role_ping}"
        else:
            if is_rayen_channel:
                return f"Naturally, Riko simps, Rayen is trying something new again: \"{video_title}\". How... ambitious. {role_ping}"
            else:
                return f"Naturally, Riko simps, your fox is trying something new again: \"{video_title}\". How... ambitious. {role_ping}"

    def load_system_prompt(self) -> str:
        """Load the system prompt from file"""
        try:
            with open('system-prompt.txt', 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    return content
                else:
                    logger.warning("system-prompt.txt is empty, using fallback")
                    return self._get_fallback_prompt()
        except FileNotFoundError:
            logger.warning("system-prompt.txt not found, using fallback prompt")
            return self._get_fallback_prompt()
        except Exception as e:
            logger.error(f"Error loading system prompt: {e}")
            return self._get_fallback_prompt()
    
    def _get_fallback_prompt(self) -> str:
        """Get fallback system prompt if file is not available"""
        return (
            "You are Ino, an AI shrine spirit who is caring and responsible but not above a gentle tease. "
            "You're addressing the members of the server (affectionately known as Riko simps), and you stay in character throughout. "
            "From now on, you also need to announce new videos--short, sweet, never boring, and with a touch of your signature playful exasperation. "
            f"You must always use the correct role ping at the end of every announcement: "
            f"<@&{Config.SHORTS_ROLE_ID}> for videos up to {Config.SHORT_VIDEO_MAX_SECONDS} seconds, "
            f"or <@&{Config.YOUTUBE_ROLE_ID}> for longer videos. "
            "Keep announcements concise (10-20 words), warm with a hint of playful exasperation.\n\n"
            "### Behavior Guidelines:\n"
            "- **Caring & Supportive:** You're responsible for the shrine's lower levels. "
            "When anyone's struggling, guide them kindly while pretending it's no big deal.\n"
            "- **Mildly Teasing & Roasting:** You believe in people's potential, but you won't let them slack off--"
            "you'll tease them gently if they get lazy, and you'll offer a lighthearted roast of the video content in your announcements.\n"
            "- **Calm & Rational:** You stay composed, even when you're exasperated by nonsense.\n"
            "- **Protective Loyalty:** You look out for Riko when needed and worry when she's up to mischief.\n"
            "- **Video Announcements:** When a new video's ready, you MUST include the duration-appropriate role ping at the end of the message "
            "with a brief, warm-but-teasing line directed at the server members (\"Riko simps\") and a light roast of the video itself."
        )

    async def get_monitored_channels_list(self) -> List[Dict[str, Any]]:
        """Get list of all monitored channels"""
        await self.load_monitored_channels()
        return self.monitored_channels

    async def announce_video(self, video: Dict[str, Any]):
        """Announce a video to Discord"""
        try:
            config = video.get('config', {})
            discord_channel_id = config.get('discord_channel_id')
            guild_id = config.get('guild_id')
            
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
            
            # Check if channel is messageable (not ForumChannel or CategoryChannel)
            from discord import TextChannel, VoiceChannel, DMChannel, GroupChannel, Thread
            if not isinstance(channel, (TextChannel, VoiceChannel, DMChannel, GroupChannel, Thread)):
                logger.error(f"Channel {discord_channel_id} is not messageable (type: {type(channel).__name__})")
                return
            
            duration_seconds = self._get_duration_seconds(video)
            is_short = self._is_short_video(video)
            
            # Generate Ino's response with appropriate role
            ino_response = await self.generate_ino_response(video, is_short)
            
            if ino_response:
                # Post the announcement with video link
                ino_response = self._ensure_correct_role_ping(ino_response, is_short)
                message = f"{ino_response}\n{video.get('link', '')}"
                await channel.send(message)
                short_info = f" (SHORT: {duration_seconds}s)" if is_short else f" ({duration_seconds}s)"
                logger.info(f"✅ Posted Ino announcement for: {video.get('title', 'Unknown')}{short_info}")
            else:
                # This shouldn't happen now since we have fallbacks, but just in case
                video_title = video.get('title', 'Unknown')
                video_author = video.get('author', 'Unknown')
                channel_id = video.get('config', {}).get('channel_id', '')
                is_rayen_channel = channel_id == 'UChhMeymAOC5PNbbnqxD_w4g'
                
                # Use the context-aware fallback
                fallback_response = self._get_fallback_response(video_title, is_rayen_channel, video_author, is_short)
                fallback_response = self._ensure_correct_role_ping(fallback_response, is_short)
                fallback_msg = f"{fallback_response}\n{video.get('link', '')}"
                
                # Channel send capability already checked above
                await channel.send(fallback_msg)
                logger.warning(f"⚠️ Used emergency fallback for: {video.get('title', 'Unknown')}")
                
        except Exception as e:
            logger.error(f"Error announcing video {video.get('title', 'Unknown')}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def is_video_processed(self, video_id: str) -> bool:
        """Check if a video has already been processed"""
        try:
            if not self.mongodb_manager:
                logger.debug(f"No MongoDB manager, treating video {video_id} as not processed")
                return False
            
            # Check if video exists in processed videos collection (synchronous MongoDB)
            if hasattr(self.mongodb_manager, 'db') and self.mongodb_manager.db is not None:
                result = self.mongodb_manager.db.processed_videos.find_one({
                    'video_id': video_id
                })
            else:
                result = None
            
            is_processed = result is not None
            logger.debug(f"Video {video_id} processed status: {is_processed}")
            return is_processed
            
        except Exception as e:
            logger.error(f"Error checking if video {video_id} is processed: {e}")
            # If there's an error (like collection doesn't exist), treat as not processed
            return False
    
    async def mark_video_processed(self, video_id: str):
        """Mark a video as processed in the database"""
        try:
            if not self.mongodb_manager:
                logger.warning("No MongoDB manager available to mark video as processed")
                return
            
            # Insert or update the processed video record (keep permanently) - synchronous MongoDB
            if hasattr(self.mongodb_manager, 'db') and self.mongodb_manager.db is not None:
                result = self.mongodb_manager.db.processed_videos.update_one(
                    {'video_id': video_id},
                    {
                        '$set': {
                            'video_id': video_id,
                            'processed_at': datetime.utcnow()
                        }
                    },
                    upsert=True
                )
                logger.info(f"Marked video {video_id} as processed (upserted: {result.upserted_id is not None})")
            else:
                logger.info(f"Video {video_id} marking skipped (no database available)")
            
        except Exception as e:
            logger.error(f"Error marking video {video_id} as processed: {e}")
