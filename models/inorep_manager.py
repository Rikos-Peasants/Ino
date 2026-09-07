import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, List
from pymongo import MongoClient, DESCENDING, ReturnDocument

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
            user_data = await asyncio.to_thread(
                self.inorep_collection.find_one,
                {"user_id": user_id, "guild_id": guild_id}
            )

            if user_data:
                return user_data.get('rep', 0)

            return 0  # Default starting rep

        except Exception as e:
            logger.error(f"Error getting user rep: {e}")
            return 0

    async def add_rep(self, user_id: str, guild_id: str, user_name: str, amount: int, reason: str, moderator_id: str, moderator_name: str) -> bool:
        """Add reputation points to a user (can be negative for warnings).

        Uses a single atomic ``$inc``: rep is now awarded from several concurrent
        paths (chat, reactions, voice, quests), and a read-then-write would drop
        awards that interleave.
        """
        try:
            # mod_mode grants immunity from point reduction, so negative changes
            # to those users are skipped entirely.
            if amount < 0:
                user_data = await asyncio.to_thread(
                    self.inorep_collection.find_one,
                    {"user_id": user_id, "guild_id": guild_id},
                    {"mod_mode": 1}
                )
                if user_data and user_data.get('mod_mode', False):
                    logger.info(f"Skipped negative rep for {user_name} because mod_mode is enabled (immune from point reduction).")
                    return True  # Pretend it was successful

            updated = await asyncio.to_thread(
                self.inorep_collection.find_one_and_update,
                {"user_id": user_id, "guild_id": guild_id},
                {
                    "$inc": {"rep": amount},
                    "$set": {
                        "user_id": user_id,
                        "guild_id": guild_id,
                        "user_name": user_name,
                        "last_updated": datetime.utcnow()
                    }
                },
                None,          # projection
                None,          # sort
                True,          # upsert
                ReturnDocument.AFTER,
            )

            new_rep = (updated or {}).get('rep', amount)

            # Log the change in history
            await self._add_rep_history(
                user_id=user_id,
                guild_id=guild_id,
                user_name=user_name,
                amount=amount,
                reason=reason,
                moderator_id=moderator_id,
                moderator_name=moderator_name,
                old_rep=new_rep - amount,
                new_rep=new_rep
            )

            logger.debug(f"Added {amount} rep to {user_name} (new total: {new_rep})")
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

            await asyncio.to_thread(
                self.inorep_history_collection.insert_one, history_entry
            )

        except Exception as e:
            logger.error(f"Error adding rep history: {e}")

    async def get_user_rep_history(self, user_id: str, guild_id: str, limit: int = 10) -> List[Dict]:
        """Get a user's reputation change history"""
        def _query():
            return list(self.inorep_history_collection.find({
                "user_id": user_id,
                "guild_id": guild_id
            }).sort("created_at", DESCENDING).limit(limit))

        try:
            return await asyncio.to_thread(_query)
        except Exception as e:
            logger.error(f"Error getting rep history: {e}")
            return []

    async def get_leaderboard(self, guild_id: str, limit: int = 10, reverse: bool = False, skip: int = 0) -> List[Dict]:
        """
        Get InoRep leaderboard

        Args:
            guild_id: The guild ID
            limit: Number of results to return
            reverse: If True, return worst offenders (lowest rep) instead of best
            skip: Number of entries to skip, for pagination
        """
        sort_direction = 1 if reverse else -1  # 1 = ascending (worst), -1 = descending (best)

        def _query():
            return list(
                self.inorep_collection.find({"guild_id": guild_id})
                .sort("rep", sort_direction)
                .skip(skip)
                .limit(limit)
            )

        try:
            return await asyncio.to_thread(_query)
        except Exception as e:
            logger.error(f"Error getting leaderboard: {e}")
            return []

    async def count_users(self, guild_id: str) -> int:
        """Total number of users with a rep record, for pagination."""
        try:
            return await asyncio.to_thread(
                self.inorep_collection.count_documents, {"guild_id": guild_id}
            )
        except Exception as e:
            logger.error(f"Error counting rep users: {e}")
            return 0

    async def set_mod_mode(self, user_id: str, guild_id: str, enabled: bool) -> bool:
        """Enable or disable moderator mode for a user"""
        try:
            await asyncio.to_thread(
                self.inorep_collection.update_one,
                {"user_id": user_id, "guild_id": guild_id},
                {"$set": {"mod_mode": enabled}},
                True,  # upsert
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

