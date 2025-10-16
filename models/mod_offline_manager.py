import discord
import logging
from typing import Dict, Set, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class ModOfflineManager:
    """Manages moderator offline status and handles offline ping responses"""
    
    def __init__(self):
        # Set of user IDs who are currently logged off
        self.offline_mods: Set[int] = set()
        # Store mod info for offline responses
        self.mod_info: Dict[int, Dict] = {}
    
    def set_mod_offline(self, user_id: int, user_name: str, avatar_url: str) -> bool:
        """Set a moderator as offline"""
        try:
            self.offline_mods.add(user_id)
            self.mod_info[user_id] = {
                'name': user_name,
                'avatar_url': avatar_url,
                'offline_since': datetime.utcnow()
            }
            logger.info(f"Moderator {user_name} ({user_id}) set as offline")
            return True
        except Exception as e:
            logger.error(f"Error setting mod offline: {e}")
            return False
    
    def set_mod_online(self, user_id: int) -> bool:
        """Set a moderator as online (remove from offline list)"""
        try:
            if user_id in self.offline_mods:
                self.offline_mods.remove(user_id)
                if user_id in self.mod_info:
                    mod_name = self.mod_info[user_id].get('name', 'Unknown')
                    del self.mod_info[user_id]
                    logger.info(f"Moderator {mod_name} ({user_id}) set as online")
                return True
            return False
        except Exception as e:
            logger.error(f"Error setting mod online: {e}")
            return False
    
    def is_mod_offline(self, user_id: int) -> bool:
        """Check if a moderator is currently offline"""
        return user_id in self.offline_mods
    
    def get_offline_mods(self) -> Set[int]:
        """Get set of all offline moderator IDs"""
        return self.offline_mods.copy()
    
    def create_offline_embed(self, user_id: int) -> Optional[discord.Embed]:
        """Create an offline embed for a specific moderator"""
        try:
            if user_id not in self.mod_info:
                return None
            
            mod_data = self.mod_info[user_id]
            
            embed = discord.Embed(
                title=mod_data['name'],
                description="is **OFFLINE**",
                color=0x808080  # Gray color for offline
            )
            
            # Set thumbnail to mod's avatar
            if mod_data.get('avatar_url'):
                embed.set_thumbnail(url=mod_data['avatar_url'])
            
            # Add footer
            embed.set_footer(text="Please contact a different member of staff")
            
            return embed
            
        except Exception as e:
            logger.error(f"Error creating offline embed: {e}")
            return None
    
    def get_mod_info(self, user_id: int) -> Optional[Dict]:
        """Get stored info for an offline moderator"""
        return self.mod_info.get(user_id)
    
    def clear_all_offline(self) -> int:
        """Clear all offline moderators (for admin use)"""
        count = len(self.offline_mods)
        self.offline_mods.clear()
        self.mod_info.clear()
        logger.info(f"Cleared {count} offline moderators")
        return count