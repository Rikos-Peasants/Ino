import logging
from datetime import datetime
from typing import Optional, Dict, List
from pymongo import MongoClient, DESCENDING

logger = logging.getLogger(__name__)

class InoRepManager:
    """Manages InoRep (Ino Reputation) system - for tracking who's been rude to Ino (just for fun!)"""
    
    def __init__(self, mongo_client: MongoClient, database_name: str = "Riko"):
        self.db = mongo_client[database_name]
        self.inorep_collection = self.db['inorep']
        self.inorep_history_collection = self.db['inorep_history']
        
        # Create indexes for better performance
        self._create_indexes()
        
        logger.info("InoRep Manager initialized")
    
    def _create_indexes(self):
        """Create database indexes for InoRep collections"""
        try:
            # InoRep indexes
            self.inorep_collection.create_index([("user_id", 1), ("guild_id", 1)], unique=True)
            self.inorep_collection.create_index([("rep", -1)])
            self.inorep_collection.create_index([("mod_mode", 1)])
            
            # History indexes
            self.inorep_history_collection.create_index([("user_id", 1), ("created_at", -1)])
            self.inorep_history_collection.create_index([("guild_id", 1), ("created_at", -1)])
            
            logger.info("InoRep indexes created successfully")
            
        except Exception as e:
            logger.error(f"Error creating InoRep indexes: {e}")
    
    async def get_user_rep(self, user_id: str, guild_id: str) -> int:
        """Get a user's InoRep score (defaults to 0 if not found)"""
        try:
            user_data = self.inorep_collection.find_one({
                "user_id": user_id,
                "guild_id": guild_id
            })
            
            if user_data:
                return user_data.get('rep', 0)
            
            return 0  # Default starting rep
            
        except Exception as e:
            logger.error(f"Error getting user rep: {e}")
            return 0
    
    async def add_rep(self, user_id: str, guild_id: str, user_name: str, amount: int, reason: str, moderator_id: str, moderator_name: str) -> bool:
        """Add reputation points to a user (can be negative for warnings)"""
        try:
            # Check if the user has mod_mode enabled (immunity from point reduction)
            # When mod_mode=True, skip negative reputation changes (prevents depletion)
            user_data = self.inorep_collection.find_one({
                "user_id": user_id,
                "guild_id": guild_id
            })

            if amount < 0 and user_data and user_data.get('mod_mode', False):
                logger.info(f"Skipped negative rep for {user_name} because mod_mode is enabled (immune from point reduction).")
                return True # Pretend it was successful

            current_rep = await self.get_user_rep(user_id, guild_id)
            new_rep = current_rep + amount
            
            # Update or create user rep record
            self.inorep_collection.update_one(
                {
                    "user_id": user_id,
                    "guild_id": guild_id
                },
                {
                    "$set": {
                        "user_id": user_id,
                        "guild_id": guild_id,
                        "user_name": user_name,
                        "rep": new_rep,
                        "last_updated": datetime.utcnow()
                    }
                },
                upsert=True
            )
            
            # Log the change in history
            await self._add_rep_history(
                user_id=user_id,
                guild_id=guild_id,
                user_name=user_name,
                amount=amount,
                reason=reason,
                moderator_id=moderator_id,
                moderator_name=moderator_name,
                old_rep=current_rep,
                new_rep=new_rep
            )
            
            logger.info(f"Added {amount} rep to {user_name} (new total: {new_rep})")
            return True
            
        except Exception as e:
            logger.error(f"Error adding rep: {e}")
            return False
    
    async def _add_rep_history(self, user_id: str, guild_id: str, user_name: str, amount: int, reason: str, moderator_id: str, moderator_name: str, old_rep: int, new_rep: int):
        """Log reputation change to history"""
        try:
            history_entry = {
                "user_id": user_id,
                "guild_id": guild_id,
                "user_name": user_name,
                "amount": amount,
                "reason": reason,
                "moderator_id": moderator_id,
                "moderator_name": moderator_name,
                "old_rep": old_rep,
                "new_rep": new_rep,
                "created_at": datetime.utcnow()
            }
            
            self.inorep_history_collection.insert_one(history_entry)
            
        except Exception as e:
            logger.error(f"Error adding rep history: {e}")
    
    async def get_user_rep_history(self, user_id: str, guild_id: str, limit: int = 10) -> List[Dict]:
        """Get a user's reputation change history"""
        try:
            cursor = self.inorep_history_collection.find({
                "user_id": user_id,
                "guild_id": guild_id
            }).sort("created_at", DESCENDING).limit(limit)
            
            return list(cursor)
            
        except Exception as e:
            logger.error(f"Error getting rep history: {e}")
            return []
    
    async def get_leaderboard(self, guild_id: str, limit: int = 10, reverse: bool = False) -> List[Dict]:
        """
        Get InoRep leaderboard
        
        Args:
            guild_id: The guild ID
            limit: Number of results to return
            reverse: If True, return worst offenders (lowest rep) instead of best
        """
        try:
            sort_direction = 1 if reverse else -1  # 1 = ascending (worst), -1 = descending (best)
            
            cursor = self.inorep_collection.find({
                "guild_id": guild_id
            }).sort("rep", sort_direction).limit(limit)
            
            return list(cursor)
            
        except Exception as e:
            logger.error(f"Error getting leaderboard: {e}")
            return []

    async def set_mod_mode(self, user_id: str, guild_id: str, enabled: bool) -> bool:
        """Enable or disable moderator mode for a user"""
        try:
            self.inorep_collection.update_one(
                {
                    "user_id": user_id,
                    "guild_id": guild_id
                },
                {
                    "$set": {
                        "mod_mode": enabled
                    }
                },
                upsert=True
            )
            logger.info(f"Set mod_mode for user {user_id} to {enabled}")
            return True
        except Exception as e:
            logger.error(f"Error setting mod_mode: {e}")
            return False
    
    def close(self):
        """Close MongoDB connection"""
        # Connection is managed by the parent mongo client
        pass

