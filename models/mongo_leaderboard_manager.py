import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging
from pymongo import MongoClient, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

logger = logging.getLogger(__name__)

class MongoLeaderboardManager:
    """Manages user image statistics and leaderboard data using MongoDB"""
    
    def __init__(self, connection_url: str = None, database_name: str = "Riko", collection_name: str = "images"):
        # Import here to avoid circular imports
        from config import Config
        
        self.connection_url = connection_url or Config.MONGO_URI
        self.database_name = database_name
        self.collection_name = collection_name
        self.client = None
        self.db = None
        self.collection = None
        self.images_collection = None  # New collection for storing image messages
        self.nsfwban_collection = None  # New collection for NSFWBAN data
        self.warnings_collection = None  # New collection for warnings
        self.settings_collection = None  # New collection for bot settings
        self.bookmarks_collection = None  # New collection for user bookmarks
        self.user_reactions_collection = None  # New collection for tracking user reactions
        self.moderation_manager = None  # Moderation manager instance
        self.inorep_manager = None  # InoRep manager instance
        self._connect()
    
    def _connect(self):
        """Connect to MongoDB"""
        try:
            self.client = MongoClient(self.connection_url, serverSelectionTimeoutMS=5000)
            # Test the connection
            self.client.admin.command('ismaster')
            self.db = self.client[self.database_name]
            self.collection = self.db[self.collection_name]
            self.images_collection = self.db['image_messages']  # New collection
            self.nsfwban_collection = self.db['nsfwban_users']  # New collection for NSFWBAN
            self.warnings_collection = self.db['warnings']  # New collection for warnings
            self.settings_collection = self.db['settings']  # New collection for bot settings
            self.bookmarks_collection = self.db['bookmarks']  # New collection for user bookmarks
            self.user_reactions_collection = self.db['user_reactions']  # New collection for tracking user reactions
            
            # Create indexes for better performance
            self.collection.create_index("user_id", unique=True)
            self.collection.create_index([("total_score", DESCENDING)])
            
            # Create indexes for image messages
            self.images_collection.create_index([("message_id", 1)], unique=True)
            self.images_collection.create_index([("channel_id", 1), ("created_at", -1)])
            self.images_collection.create_index([("score", -1)])
            
            # Create indexes for NSFWBAN users
            self.nsfwban_collection.create_index([("user_id", 1)], unique=True)
            self.nsfwban_collection.create_index([("banned_at", -1)])
            
            # Create indexes for warnings
            self.warnings_collection.create_index([("user_id", 1)])
            self.warnings_collection.create_index([("guild_id", 1)])
            self.warnings_collection.create_index([("created_at", -1)])
            
            # Create indexes for settings
            self.settings_collection.create_index([("guild_id", 1), ("setting_name", 1)], unique=True)
            
            # Create indexes for bookmarks
            self.bookmarks_collection.create_index([("user_id", 1), ("message_id", 1)], unique=True)
            self.bookmarks_collection.create_index([("user_id", 1), ("created_at", -1)])
            self.bookmarks_collection.create_index([("message_id", 1)])
            
            # Create indexes for user reactions
            self.user_reactions_collection.create_index([("user_id", 1), ("message_id", 1), ("emoji", 1)], unique=True)
            self.user_reactions_collection.create_index([("user_id", 1), ("created_at", -1)])
            self.user_reactions_collection.create_index([("message_id", 1)])
            
            logger.info(f"Connected to MongoDB database '{self.database_name}', collections: {self.collection_name}, image_messages, nsfwban_users, warnings, settings, bookmarks, user_reactions")
            
            # Initialize moderation manager
            try:
                from models.moderation_manager import ModerationManager
                self.moderation_manager = ModerationManager(self.client, self.database_name)
                logger.info("Moderation manager initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize moderation manager: {e}")
                self.moderation_manager = None
            
            # Initialize InoRep manager
            try:
                from models.inorep_manager import InoRepManager
                self.inorep_manager = InoRepManager(self.client, self.database_name)
                logger.info("InoRep manager initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize InoRep manager: {e}")
                self.inorep_manager = None
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise Exception(f"MongoDB connection failed: {e}")

    # NSFWBAN Management Methods
    async def add_nsfwban_user(self, user_id: int, user_name: str, banned_by_id: int, banned_by_name: str, guild_id: int = None, reason: str = None) -> bool:
        """Add a user to the NSFWBAN list"""
        try:
            doc = {
                "user_id": str(user_id),
                "user_name": user_name,
                "banned_by_id": str(banned_by_id),
                "banned_by_name": banned_by_name,
                "guild_id": str(guild_id) if guild_id else None,
                "reason": reason or "No reason provided",
                "banned_at": datetime.now(),
                "is_active": True
            }
            
            result = self.nsfwban_collection.update_one(
                {"user_id": str(user_id)},
                {"$set": doc},
                upsert=True
            )
            
            logger.info(f"Added {user_name} to NSFWBAN list by {banned_by_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding user to NSFWBAN list: {e}")
            return False

    async def remove_nsfwban_user(self, user_id: int) -> bool:
        """Remove a user from the NSFWBAN list"""
        try:
            result = self.nsfwban_collection.update_one(
                {"user_id": str(user_id)},
                {"$set": {"is_active": False, "unbanned_at": datetime.now()}}
            )
            
            if result.modified_count > 0:
                logger.info(f"Removed user {user_id} from NSFWBAN list")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error removing user from NSFWBAN list: {e}")
            return False

    async def is_nsfwban_user(self, user_id: int) -> bool:
        """Check if a user is in the NSFWBAN list"""
        try:
            result = self.nsfwban_collection.find_one({
                "user_id": str(user_id),
                "is_active": True
            })
            return result is not None
            
        except Exception as e:
            logger.error(f"Error checking NSFWBAN status: {e}")
            return False

    async def get_nsfwban_user_info(self, user_id: int) -> Optional[Dict]:
        """Get NSFWBAN information for a user"""
        try:
            result = self.nsfwban_collection.find_one({
                "user_id": str(user_id),
                "is_active": True
            })
            return result
            
        except Exception as e:
            logger.error(f"Error getting NSFWBAN user info: {e}")
            return None

    async def get_all_nsfwban_users(self) -> List[Dict]:
        """Get all active NSFWBAN users"""
        try:
            cursor = self.nsfwban_collection.find({"is_active": True}).sort("banned_at", -1)
            return list(cursor)
            
        except Exception as e:
            logger.error(f"Error getting all NSFWBAN users: {e}")
            return []

    async def image_message_exists(self, message_id: str) -> bool:
        """Check if an image message already exists in the database"""
        try:
            result = self.images_collection.find_one({"message_id": str(message_id)})
            return result is not None
        except Exception as e:
            logger.error(f"Error checking if image message exists: {e}")
            return False

    async def store_image_message(self, message, image_url: str, initial_score: int = 0):
        """Store an image message in the database"""
        try:
            # Create document for the image message
            doc = {
                "message_id": str(message.id),
                "channel_id": str(message.channel.id),
                "author_id": str(message.author.id),
                "author_name": message.author.display_name,
                "content": message.content,
                "image_url": image_url,
                "score": initial_score,
                "thumbs_up": 0,
                "thumbs_down": 0,
                "created_at": message.created_at,
                "jump_url": message.jump_url
            }
            
            # Use upsert to handle potential duplicates
            result = self.images_collection.update_one(
                {"message_id": doc["message_id"]},
                {"$set": doc},
                upsert=True
            )
            
            logger.info(f"Stored image message from {message.author.display_name} in #{message.channel.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error storing image message: {e}")
            return False

    async def update_image_message_score(self, message_id: str, thumbs_up: int, thumbs_down: int):
        """Update the score for an image message"""
        try:
            net_score = thumbs_up - thumbs_down
            result = self.images_collection.update_one(
                {"message_id": str(message_id)},
                {
                    "$set": {
                        "score": net_score,
                        "thumbs_up": thumbs_up,
                        "thumbs_down": thumbs_down,
                        "last_updated": datetime.now()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Updated score for message {message_id}: {net_score} (👍{thumbs_up} - 👎{thumbs_down})")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error updating image message score: {e}")
            return False

    async def get_best_image(self, channel_id: str, start_date: datetime, end_date: datetime) -> Optional[Dict]:
        """Get the best image in a channel for a given time period"""
        try:
            # Log the query parameters for debugging
            logger.info(f"Searching for best image in channel {channel_id} from {start_date} to {end_date}")
            
            # First, let's see how many images we have in this time period
            count = self.images_collection.count_documents({
                "channel_id": str(channel_id),
                "created_at": {
                    "$gte": start_date,
                    "$lt": end_date
                }
            })
            
            logger.info(f"Found {count} images in the specified time period")
            
            if count == 0:
                logger.info("No images found in the time period")
                return None
            
            # Query for the highest scored image in the time period
            result = self.images_collection.find_one(
                {
                    "channel_id": str(channel_id),
                    "created_at": {
                        "$gte": start_date,
                        "$lt": end_date
                    }
                },
                sort=[("score", DESCENDING)]
            )
            
            if result:
                logger.info(f"Best image found: Message ID {result['message_id']}, Score: {result['score']}, Author: {result['author_name']}")
                
                # Also log the top 3 images for comparison
                top_images = list(self.images_collection.find(
                    {
                        "channel_id": str(channel_id),
                        "created_at": {
                            "$gte": start_date,
                            "$lt": end_date
                        }
                    },
                    sort=[("score", DESCENDING)]
                ).limit(3))
                
                logger.info("Top 3 images in period:")
                for i, img in enumerate(top_images, 1):
                    logger.info(f"  {i}. Score: {img['score']}, Author: {img['author_name']}, ID: {img['message_id']}")
            else:
                logger.warning("Query returned no results despite having images in the collection")
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting best image: {e}")
            return None

    async def delete_image_message(self, message_id: str):
        """Delete an image message from the database"""
        try:
            result = self.images_collection.delete_one({"message_id": str(message_id)})
            if result.deleted_count > 0:
                logger.info(f"Deleted image message {message_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error deleting image message: {e}")
            return False
    
    def add_image_post(self, user_id: int, user_name: str, initial_score: int = 0):
        """Record when a user posts an image"""
        try:
            # Use upsert to either create or update user data
            result = self.collection.update_one(
                {"user_id": str(user_id)},
                {
                    "$set": {
                        "user_name": user_name,
                        "last_updated": datetime.now().isoformat()
                    },
                    "$inc": {
                        "image_count": 1,
                        "total_score": initial_score
                    },
                    "$setOnInsert": {
                        "user_id": str(user_id),
                        "created_at": datetime.now().isoformat()
                    }
                },
                upsert=True
            )
            
            # Get updated document to log the new count
            updated_doc = self.collection.find_one({"user_id": str(user_id)})
            if updated_doc:
                logger.info(f"Added image post for {user_name} (new count: {updated_doc['image_count']})")
            
        except Exception as e:
            logger.error(f"Error adding image post for {user_name}: {e}")
    
    def update_image_score(self, user_id: int, user_name: str, score_change: int):
        """Update a user's score when reactions change"""
        try:
            result = self.collection.update_one(
                {"user_id": str(user_id)},
                {
                    "$set": {
                        "user_name": user_name,
                        "last_updated": datetime.now().isoformat()
                    },
                    "$inc": {
                        "total_score": score_change
                    },
                    "$setOnInsert": {
                        "user_id": str(user_id),
                        "image_count": 1,
                        "created_at": datetime.now().isoformat()
                    }
                },
                upsert=True
            )
            
            # Get updated document to log the new score
            updated_doc = self.collection.find_one({"user_id": str(user_id)})
            if updated_doc:
                logger.debug(f"Updated score for {user_name}: {score_change:+d} (total: {updated_doc['total_score']})")
            
        except Exception as e:
            logger.error(f"Error updating score for {user_name}: {e}")
    
    def get_leaderboard(self, limit: int = 10, sort_by: str = "total_score") -> List[Tuple[str, int, int, int]]:
        """Get leaderboard data sorted by specified criteria
        
        Args:
            limit: Maximum number of entries to return
            sort_by: Sort criteria - 'total_score', 'avg_score', or 'image_count'
        """
        try:
            # For avg_score, we need to calculate it and sort in memory
            if sort_by == "avg_score":
                # Get all users and calculate average scores
                cursor = self.collection.find({})
                users_with_avg = []
                
                for doc in cursor:
                    total_score = doc.get("total_score", 0)
                    image_count = doc.get("image_count", 0)
                    avg_score = total_score / image_count if image_count > 0 else 0
                    
                    users_with_avg.append({
                        "user_name": doc.get("user_name", "Unknown"),
                        "user_id": int(doc["user_id"]),
                        "total_score": total_score,
                        "image_count": image_count,
                        "avg_score": avg_score
                    })
                
                # Sort by average score
                users_with_avg.sort(key=lambda x: x["avg_score"], reverse=True)
                
                # Convert to leaderboard format
                leaderboard = [
                    (u["user_name"], u["user_id"], u["total_score"], u["image_count"])
                    for u in users_with_avg[:limit]
                ]
                
            else:
                # Direct MongoDB sort for total_score or image_count
                sort_field = "image_count" if sort_by == "image_count" else "total_score"
                cursor = self.collection.find({}).sort(sort_field, DESCENDING).limit(limit)
                
                leaderboard = []
                for doc in cursor:
                    leaderboard.append((
                        doc.get("user_name", "Unknown"),
                        int(doc["user_id"]),
                        doc.get("total_score", 0),
                        doc.get("image_count", 0)
                    ))
            
            return leaderboard
            
        except Exception as e:
            logger.error(f"Error getting leaderboard: {e}")
            return []
    
    def get_user_stats(self, user_id: int) -> Optional[Dict]:
        """Get stats for a specific user"""
        try:
            doc = self.collection.find_one({"user_id": str(user_id)})
            if doc:
                return {
                    "name": doc.get("user_name", "Unknown"),
                    "total_score": doc.get("total_score", 0),
                    "image_count": doc.get("image_count", 0),
                    "last_updated": doc.get("last_updated", ""),
                    "created_at": doc.get("created_at", "")
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting user stats for {user_id}: {e}")
            return None
    
    def reset_leaderboard(self) -> bool:
        """Reset all leaderboard data (admin function)"""
        try:
            # Create backup collection name with timestamp
            backup_collection_name = f"{self.collection_name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Copy all documents to backup collection
            pipeline = [{"$out": backup_collection_name}]
            list(self.collection.aggregate(pipeline))
            
            # Delete all documents from main collection
            result = self.collection.delete_many({})
            
            logger.info(f"Leaderboard reset successfully. {result.deleted_count} documents removed. Backup saved to '{backup_collection_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Error resetting leaderboard: {e}")
            return False
    
    def get_stats_summary(self) -> Dict:
        """Get summary statistics"""
        try:
            pipeline = [
                {
                    "$group": {
                        "_id": None,
                        "total_users": {"$sum": 1},
                        "total_images": {"$sum": "$image_count"},
                        "total_score": {"$sum": "$total_score"}
                    }
                }
            ]
            
            result = list(self.collection.aggregate(pipeline))
            
            if result:
                stats = result[0]
                total_images = stats.get("total_images", 0)
                total_score = stats.get("total_score", 0)
                average_score = total_score / total_images if total_images > 0 else 0
                
                return {
                    "total_users": stats.get("total_users", 0),
                    "total_images": total_images,
                    "total_score": total_score,
                    "average_score": round(average_score, 2)
                }
            else:
                return {
                    "total_users": 0,
                    "total_images": 0,
                    "total_score": 0,
                    "average_score": 0
                }
                
        except Exception as e:
            logger.error(f"Error getting stats summary: {e}")
            return {
                "total_users": 0,
                "total_images": 0,
                "total_score": 0,
                "average_score": 0
            }
    
    def migrate_from_json(self, json_data: Dict) -> bool:
        """Migrate data from JSON format to MongoDB"""
        try:
            if "users" not in json_data:
                logger.warning("No users data found in JSON")
                return False
            
            documents = []
            for user_id, user_data in json_data["users"].items():
                doc = {
                    "user_id": user_id,
                    "user_name": user_data.get("name", "Unknown"),
                    "total_score": user_data.get("total_score", 0),
                    "image_count": user_data.get("image_count", 0),
                    "last_updated": user_data.get("last_updated", datetime.now().isoformat()),
                    "created_at": datetime.now().isoformat(),
                    "migrated_from_json": True,
                    "migration_date": datetime.now().isoformat()
                }
                documents.append(doc)
            
            if documents:
                # Insert all documents, replacing existing ones
                for doc in documents:
                    self.collection.replace_one(
                        {"user_id": doc["user_id"]},
                        doc,
                        upsert=True
                    )
                
                logger.info(f"Successfully migrated {len(documents)} users from JSON to MongoDB")
                return True
            else:
                logger.warning("No documents to migrate")
                return False
                
        except Exception as e:
            logger.error(f"Error migrating from JSON: {e}")
            return False
    
    def close(self):
        """Close the MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

    # Warning System Methods
    async def add_warning(self, guild_id: int, user_id: int, user_name: str, moderator_id: int, moderator_name: str, reason: str) -> Dict:
        """Add a warning to a user and return the warning count and action taken"""
        try:
            # Create warning document
            warning_doc = {
                "guild_id": str(guild_id),
                "user_id": str(user_id),
                "user_name": user_name,
                "moderator_id": str(moderator_id),
                "moderator_name": moderator_name,
                "reason": reason,
                "created_at": datetime.now(),
                "is_active": True
            }
            
            # Insert the warning
            self.warnings_collection.insert_one(warning_doc)
            
            # Get current warning count
            warning_count = await self.get_warning_count(guild_id, user_id)
            
            # Determine action based on warning count
            action = self._get_warning_action(warning_count)
            
            logger.info(f"Added warning #{warning_count} to user {user_name} by {moderator_name}: {reason}")
            
            return {
                "warning_count": warning_count,
                "action": action,
                "warning_id": str(warning_doc.get("_id", ""))
            }
            
        except Exception as e:
            logger.error(f"Error adding warning: {e}")
            return {"warning_count": 0, "action": "none", "warning_id": ""}

    async def get_warning_count(self, guild_id: int, user_id: int) -> int:
        """Get the number of active warnings for a user"""
        try:
            count = self.warnings_collection.count_documents({
                "guild_id": str(guild_id),
                "user_id": str(user_id),
                "is_active": True
            })
            return count
        except Exception as e:
            logger.error(f"Error getting warning count: {e}")
            return 0

    async def get_user_warnings(self, guild_id: int, user_id: int, limit: int = 10) -> List[Dict]:
        """Get warnings for a specific user"""
        try:
            cursor = self.warnings_collection.find({
                "guild_id": str(guild_id),
                "user_id": str(user_id),
                "is_active": True
            }).sort("created_at", -1).limit(limit)
            
            return list(cursor)
        except Exception as e:
            logger.error(f"Error getting user warnings: {e}")
            return []

    async def remove_warning(self, warning_id: str) -> bool:
        """Remove/deactivate a specific warning"""
        try:
            from bson import ObjectId
            result = self.warnings_collection.update_one(
                {"_id": ObjectId(warning_id)},
                {"$set": {"is_active": False, "removed_at": datetime.now()}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error removing warning: {e}")
            return False

    async def clear_user_warnings(self, guild_id: int, user_id: int) -> int:
        """Clear all warnings for a user and return the number cleared"""
        try:
            result = self.warnings_collection.update_many(
                {
                    "guild_id": str(guild_id),
                    "user_id": str(user_id),
                    "is_active": True
                },
                {"$set": {"is_active": False, "cleared_at": datetime.now()}}
            )
            return result.modified_count
        except Exception as e:
            logger.error(f"Error clearing user warnings: {e}")
            return 0

    def _get_warning_action(self, warning_count: int) -> str:
        """Determine the action to take based on warning count"""
        if warning_count == 1:
            return "warning"
        elif warning_count == 2:
            return "timeout_1h"
        elif warning_count == 3:
            return "timeout_4h"
        elif warning_count == 4:
            return "timeout_1w"
        elif warning_count >= 5:
            return "kick"
        else:
            return "none"

    # Settings Management Methods
    async def get_guild_setting(self, guild_id: int, setting_name: str, default_value=None):
        """Get a guild-specific setting from the database"""
        try:
            query = {"setting_name": setting_name}
            if guild_id:
                query["guild_id"] = guild_id
            
            result = self.settings_collection.find_one(query)
            
            if result:
                return result.get("setting_value", default_value)
            
            return default_value
            
        except Exception as e:
            logger.error(f"Error getting guild setting {setting_name}: {e}")
            return default_value

    async def set_guild_setting(self, guild_id: int, setting_name: str, setting_value):
        """Set a guild-specific setting in the database"""
        try:
            query = {"setting_name": setting_name}
            if guild_id:
                query["guild_id"] = guild_id
                
            if setting_value is None:
                # Remove the setting if value is None
                result = self.settings_collection.delete_one(query)
                logger.info(f"Removed guild setting {setting_name}")
                return True
            else:
                # Update or insert the setting
                update_doc = {
                    "$set": {
                        "guild_id": guild_id,
                        "setting_name": setting_name,
                        "setting_value": setting_value,
                        "updated_at": datetime.utcnow()
                    }
                }
                
                result = self.settings_collection.update_one(
                    query,
                    update_doc,
                    upsert=True
                )
                
                logger.info(f"Updated guild setting {setting_name}")
                return True
            
        except Exception as e:
            logger.error(f"Error setting guild setting {setting_name}: {e}")
            return False

    async def get_warning_log_channel(self, guild_id: int) -> Optional[int]:
        """Get the warning log channel for a guild"""
        channel_id = await self.get_guild_setting(guild_id, "warning_log_channel")
        return int(channel_id) if channel_id else None

    async def set_warning_log_channel(self, guild_id: int, channel_id: int) -> bool:
        """Set the warning log channel for a guild"""
        return await self.set_guild_setting(guild_id, "warning_log_channel", str(channel_id)) 

    # BOOKMARK MANAGEMENT METHODS
    async def add_bookmark(self, user_id: int, message_id: str, user_name: str = None) -> bool:
        """Add a bookmark for a user"""
        try:
            # Get the image message details
            image_data = self.images_collection.find_one({"message_id": str(message_id)})
            if not image_data:
                logger.warning(f"Cannot bookmark message {message_id}: Image not found in database")
                return False
            
            # Create bookmark document
            bookmark_doc = {
                "user_id": str(user_id),
                "message_id": str(message_id),
                "user_name": user_name or "Unknown",
                "image_url": image_data.get("image_url", ""),
                "image_author": image_data.get("author_name", "Unknown"),
                "image_content": image_data.get("content", ""),
                "channel_id": image_data.get("channel_id", ""),
                "jump_url": image_data.get("jump_url", ""),
                "created_at": datetime.now(),
                "image_created_at": image_data.get("created_at")
            }
            
            # Use upsert to prevent duplicates
            result = self.bookmarks_collection.update_one(
                {"user_id": str(user_id), "message_id": str(message_id)},
                {"$set": bookmark_doc},
                upsert=True
            )
            
            if result.upserted_id or result.modified_count > 0:
                logger.info(f"Added bookmark for user {user_id}: message {message_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error adding bookmark: {e}")
            return False

    async def remove_bookmark(self, user_id: int, message_id: str) -> bool:
        """Remove a bookmark for a user"""
        try:
            result = self.bookmarks_collection.delete_one({
                "user_id": str(user_id),
                "message_id": str(message_id)
            })
            
            if result.deleted_count > 0:
                logger.info(f"Removed bookmark for user {user_id}: message {message_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error removing bookmark: {e}")
            return False

    async def is_bookmarked(self, user_id: int, message_id: str) -> bool:
        """Check if a message is bookmarked by a user"""
        try:
            result = self.bookmarks_collection.find_one({
                "user_id": str(user_id),
                "message_id": str(message_id)
            })
            return result is not None
            
        except Exception as e:
            logger.error(f"Error checking bookmark status: {e}")
            return False

    async def get_user_bookmarks(self, user_id: int, limit: int = 20, skip: int = 0) -> List[Dict]:
        """Get bookmarks for a user with pagination"""
        try:
            cursor = self.bookmarks_collection.find({
                "user_id": str(user_id)
            }).sort("created_at", -1).skip(skip).limit(limit)
            
            bookmarks = list(cursor)
            logger.info(f"Retrieved {len(bookmarks)} bookmarks for user {user_id}")
            return bookmarks
            
        except Exception as e:
            logger.error(f"Error getting user bookmarks: {e}")
            return []

    async def get_bookmark_count(self, user_id: int) -> int:
        """Get the total number of bookmarks for a user"""
        try:
            count = self.bookmarks_collection.count_documents({
                "user_id": str(user_id)
            })
            return count
            
        except Exception as e:
            logger.error(f"Error getting bookmark count: {e}")
            return 0

    async def clear_user_bookmarks(self, user_id: int) -> int:
        """Clear all bookmarks for a user"""
        try:
            result = self.bookmarks_collection.delete_many({
                "user_id": str(user_id)
            })
            
            logger.info(f"Cleared {result.deleted_count} bookmarks for user {user_id}")
            return result.deleted_count
            
        except Exception as e:
            logger.error(f"Error clearing user bookmarks: {e}")
            return 0

    # USER REACTIONS TRACKING METHODS
    async def track_user_reaction(self, user_id: int, message_id: str, emoji: str, added: bool) -> bool:
        """Track when a user adds or removes a reaction"""
        try:
            if added:
                # Add reaction record
                reaction_doc = {
                    "user_id": str(user_id),
                    "message_id": str(message_id),
                    "emoji": emoji,
                    "created_at": datetime.now()
                }
                
                result = self.user_reactions_collection.update_one(
                    {"user_id": str(user_id), "message_id": str(message_id), "emoji": emoji},
                    {"$set": reaction_doc},
                    upsert=True
                )
                
                logger.info(f"Tracked reaction: User {user_id} {emoji} on message {message_id}")
                return True
            else:
                # Remove reaction record
                result = self.user_reactions_collection.delete_one({
                    "user_id": str(user_id),
                    "message_id": str(message_id),
                    "emoji": emoji
                })
                
                if result.deleted_count > 0:
                    logger.info(f"Removed reaction tracking: User {user_id} {emoji} on message {message_id}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Error tracking user reaction: {e}")
            return False

    async def get_user_liked_images(self, user_id: int, limit: int = 20, skip: int = 0) -> List[Dict]:
        """Get images that a user has liked (reacted with 👍)"""
        try:
            # Get message IDs that user liked
            liked_reactions = self.user_reactions_collection.find({
                "user_id": str(user_id),
                "emoji": "👍"
            }).sort("created_at", -1).skip(skip).limit(limit)
            
            liked_message_ids = [reaction["message_id"] for reaction in liked_reactions]
            
            if not liked_message_ids:
                return []
            
            # Get the actual image data for these messages
            images = list(self.images_collection.find({
                "message_id": {"$in": liked_message_ids}
            }).sort("created_at", -1))
            
            logger.info(f"Retrieved {len(images)} liked images for user {user_id}")
            return images
            
        except Exception as e:
            logger.error(f"Error getting user liked images: {e}")
            return []

    async def get_user_liked_images_count(self, user_id: int) -> int:
        """Get the total number of images a user has liked"""
        try:
            count = self.user_reactions_collection.count_documents({
                "user_id": str(user_id),
                "emoji": "👍"
            })
            return count
            
        except Exception as e:
            logger.error(f"Error getting user liked images count: {e}")
            return 0 

    async def verify_reaction_exists(self, user_id: int, message_id: str, emoji: str) -> bool:
        """Verify if a reaction exists in the database"""
        try:
            result = self.user_reactions_collection.find_one({
                "user_id": str(user_id),
                "message_id": str(message_id),
                "emoji": emoji
            })
            return result is not None
            
        except Exception as e:
            logger.error(f"Error verifying reaction exists: {e}")
            return False

    def get_message_reactions_count(self, message_id: str, emoji: str) -> int:
        """Get the count of specific reactions for a message from database"""
        try:
            count = self.user_reactions_collection.count_documents({
                "message_id": str(message_id),
                "emoji": emoji
            })
            return count
            
        except Exception as e:
            logger.error(f"Error getting message reactions count: {e}")
            return 0

    async def audit_reaction_discrepancies(self, message_id: str, discord_thumbs_up: int, discord_thumbs_down: int) -> Dict:
        """Audit discrepancies between Discord reactions and database records"""
        try:
            db_thumbs_up = self.get_message_reactions_count(message_id, "👍")
            db_thumbs_down = self.get_message_reactions_count(message_id, "👎")
            
            discrepancies = {
                "message_id": message_id,
                "discord_thumbs_up": discord_thumbs_up,
                "db_thumbs_up": db_thumbs_up,
                "discord_thumbs_down": discord_thumbs_down,
                "db_thumbs_down": db_thumbs_down,
                "thumbs_up_diff": discord_thumbs_up - db_thumbs_up,
                "thumbs_down_diff": discord_thumbs_down - db_thumbs_down,
                "has_discrepancy": (discord_thumbs_up != db_thumbs_up) or (discord_thumbs_down != db_thumbs_down)
            }
            
            if discrepancies["has_discrepancy"]:
                logger.warning(f"🔍 Reaction discrepancy detected for message {message_id}: "
                             f"Discord(👍:{discord_thumbs_up}, 👎:{discord_thumbs_down}) vs "
                             f"DB(👍:{db_thumbs_up}, 👎:{db_thumbs_down})")
            
            return discrepancies
            
        except Exception as e:
            logger.error(f"Error auditing reaction discrepancies: {e}")
            return {"error": str(e)}

    async def get_user_reaction_stats(self, user_id: int) -> Dict:
        """Get comprehensive reaction statistics for a user"""
        try:
            pipeline = [
                {"$match": {"user_id": str(user_id)}},
                {"$group": {
                    "_id": "$emoji",
                    "count": {"$sum": 1},
                    "latest_reaction": {"$max": "$created_at"}
                }},
                {"$sort": {"count": -1}}
            ]
            
            results = list(self.user_reactions_collection.aggregate(pipeline))
            
            total_reactions = sum(result["count"] for result in results)
            
            stats = {
                "user_id": user_id,
                "total_reactions": total_reactions,
                "emoji_breakdown": {result["_id"]: result["count"] for result in results},
                "most_used_emoji": results[0]["_id"] if results else None,
                "latest_reaction_date": max((result["latest_reaction"] for result in results), default=None)
            }
            
            logger.info(f"Retrieved reaction stats for user {user_id}: {total_reactions} total reactions")
            return stats
            
        except Exception as e:
            logger.error(f"Error getting user reaction stats: {e}")
            return {"error": str(e)}

    async def get_message_all_reactions(self, message_id: str) -> Dict:
        """Get all reactions for a specific message with user details"""
        try:
            reactions = list(self.user_reactions_collection.find({
                "message_id": str(message_id)
            }).sort("created_at", 1))
            
            if not reactions:
                return {"message_id": message_id, "reactions": [], "total_count": 0}
            
            # Group by emoji
            emoji_groups = {}
            for reaction in reactions:
                emoji = reaction["emoji"]
                if emoji not in emoji_groups:
                    emoji_groups[emoji] = []
                emoji_groups[emoji].append({
                    "user_id": reaction["user_id"],
                    "created_at": reaction["created_at"]
                })
            
            result = {
                "message_id": message_id,
                "reactions": emoji_groups,
                "total_count": len(reactions),
                "emoji_counts": {emoji: len(users) for emoji, users in emoji_groups.items()}
            }
            
            logger.info(f"Retrieved {len(reactions)} reactions for message {message_id}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting message reactions: {e}")
            return {"error": str(e)}

    async def get_top_reacted_messages(self, limit: int = 10, emoji: str = None) -> List[Dict]:
        """Get the most reacted messages, optionally filtered by emoji"""
        try:
            match_stage = {}
            if emoji:
                match_stage["emoji"] = emoji
            
            pipeline = [
                {"$match": match_stage},
                {"$group": {
                    "_id": "$message_id",
                    "reaction_count": {"$sum": 1},
                    "unique_emojis": {"$addToSet": "$emoji"},
                    "latest_reaction": {"$max": "$created_at"}
                }},
                {"$sort": {"reaction_count": -1}},
                {"$limit": limit}
            ]
            
            results = list(self.user_reactions_collection.aggregate(pipeline))
            
            # Enrich with image message data if available
            for result in results:
                message_id = result["_id"]
                image_data = self.images_collection.find_one({"message_id": message_id})
                if image_data:
                    result["image_data"] = {
                        "author_id": image_data.get("author_id"),
                        "author_name": image_data.get("author_name"),
                        "channel_id": image_data.get("channel_id"),
                        "created_at": image_data.get("created_at"),
                        "image_url": image_data.get("image_url")
                    }
            
            logger.info(f"Retrieved top {len(results)} reacted messages")
            return results
            
        except Exception as e:
            logger.error(f"Error getting top reacted messages: {e}")
            return []

    async def bulk_track_reactions(self, reactions_data: List[Dict]) -> Dict:
        """Bulk insert/update multiple reactions for efficiency"""
        try:
            if not reactions_data:
                return {"inserted": 0, "updated": 0, "errors": 0}
            
            operations = []
            for reaction in reactions_data:
                filter_doc = {
                    "user_id": str(reaction["user_id"]),
                    "message_id": str(reaction["message_id"]),
                    "emoji": reaction["emoji"]
                }
                
                update_doc = {
                    "$set": {
                        "user_id": str(reaction["user_id"]),
                        "message_id": str(reaction["message_id"]),
                        "emoji": reaction["emoji"],
                        "created_at": reaction.get("created_at", datetime.now())
                    }
                }
                
                operations.append({
                    "updateOne": {
                        "filter": filter_doc,
                        "update": update_doc,
                        "upsert": True
                    }
                })
            
            # Execute bulk operations
            result = self.user_reactions_collection.bulk_write(operations, ordered=False)
            
            stats = {
                "inserted": result.upserted_count,
                "updated": result.modified_count,
                "errors": 0,
                "total_processed": len(reactions_data)
            }
            
            logger.info(f"Bulk reaction tracking complete: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Error in bulk reaction tracking: {e}")
            return {"inserted": 0, "updated": 0, "errors": 1, "error": str(e)}

    async def get_reaction_analytics(self, days_back: int = 7) -> Dict:
        """Get comprehensive reaction analytics for the specified time period"""
        try:
            from datetime import timedelta
            
            start_date = datetime.now() - timedelta(days=days_back)
            
            pipeline = [
                {"$match": {"created_at": {"$gte": start_date}}},
                {"$group": {
                    "_id": {
                        "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                        "emoji": "$emoji"
                    },
                    "count": {"$sum": 1}
                }},
                {"$sort": {"_id.date": 1}}
            ]
            
            results = list(self.user_reactions_collection.aggregate(pipeline))
            
            # Process results into analytics
            daily_stats = {}
            emoji_totals = {}
            
            for result in results:
                date = result["_id"]["date"]
                emoji = result["_id"]["emoji"]
                count = result["count"]
                
                if date not in daily_stats:
                    daily_stats[date] = {}
                daily_stats[date][emoji] = count
                
                if emoji not in emoji_totals:
                    emoji_totals[emoji] = 0
                emoji_totals[emoji] += count
            
            # Get total unique users and messages
            total_users = len(self.user_reactions_collection.distinct("user_id", {"created_at": {"$gte": start_date}}))
            total_messages = len(self.user_reactions_collection.distinct("message_id", {"created_at": {"$gte": start_date}}))
            total_reactions = sum(emoji_totals.values())
            
            analytics = {
                "period": f"Last {days_back} days",
                "start_date": start_date.isoformat(),
                "end_date": datetime.now().isoformat(),
                "total_reactions": total_reactions,
                "total_unique_users": total_users,
                "total_unique_messages": total_messages,
                "daily_breakdown": daily_stats,
                "emoji_totals": dict(sorted(emoji_totals.items(), key=lambda x: x[1], reverse=True)),
                "average_reactions_per_day": total_reactions / days_back if days_back > 0 else 0
            }
            
            logger.info(f"Generated reaction analytics for {days_back} days: {total_reactions} total reactions")
            return analytics
            
        except Exception as e:
            logger.error(f"Error generating reaction analytics: {e}")
            return {"error": str(e)}

    # WELCOME/LEAVE SYSTEM METHODS
    async def set_welcome_channel(self, guild_id: int, channel_id: int) -> bool:
        """Set the welcome channel for a guild"""
        try:
            return await self.set_guild_setting(guild_id, "welcome_channel", channel_id)
        except Exception as e:
            logger.error(f"Error setting welcome channel: {e}")
            return False

    async def set_leave_channel(self, guild_id: int, channel_id: int) -> bool:
        """Set the leave channel for a guild"""
        try:
            return await self.set_guild_setting(guild_id, "leave_channel", channel_id)
        except Exception as e:
            logger.error(f"Error setting leave channel: {e}")
            return False

    async def get_welcome_channel(self, guild_id: int) -> Optional[int]:
        """Get the welcome channel for a guild"""
        try:
            channel_id = await self.get_guild_setting(guild_id, "welcome_channel")
            return int(channel_id) if channel_id else None
        except Exception as e:
            logger.error(f"Error getting welcome channel: {e}")
            return None

    async def get_leave_channel(self, guild_id: int) -> Optional[int]:
        """Get the leave channel for a guild"""
        try:
            channel_id = await self.get_guild_setting(guild_id, "leave_channel")
            return int(channel_id) if channel_id else None
        except Exception as e:
            logger.error(f"Error getting leave channel: {e}")
            return None

    async def disable_welcome_system(self, guild_id: int) -> bool:
        """Disable the welcome system for a guild"""
        try:
            return await self.set_guild_setting(guild_id, "welcome_enabled", False)
        except Exception as e:
            logger.error(f"Error disabling welcome system: {e}")
            return False

    async def disable_leave_system(self, guild_id: int) -> bool:
        """Disable the leave system for a guild"""
        try:
            return await self.set_guild_setting(guild_id, "leave_enabled", False)
        except Exception as e:
            logger.error(f"Error disabling leave system: {e}")
            return False

    async def enable_welcome_system(self, guild_id: int) -> bool:
        """Enable the welcome system for a guild"""
        try:
            return await self.set_guild_setting(guild_id, "welcome_enabled", True)
        except Exception as e:
            logger.error(f"Error enabling welcome system: {e}")
            return False

    async def enable_leave_system(self, guild_id: int) -> bool:
        """Enable the leave system for a guild"""
        try:
            return await self.set_guild_setting(guild_id, "leave_enabled", True)
        except Exception as e:
            logger.error(f"Error enabling leave system: {e}")
            return False

    async def is_welcome_enabled(self, guild_id: int) -> bool:
        """Check if welcome system is enabled for a guild"""
        try:
            enabled = await self.get_guild_setting(guild_id, "welcome_enabled", True)  # Default to True
            return bool(enabled)
        except Exception as e:
            logger.error(f"Error checking welcome system status: {e}")
            return True

    async def is_leave_enabled(self, guild_id: int) -> bool:
        """Check if leave system is enabled for a guild"""
        try:
            enabled = await self.get_guild_setting(guild_id, "leave_enabled", True)  # Default to True
            return bool(enabled)
        except Exception as e:
            logger.error(f"Error checking leave system status: {e}")
            return True

    async def set_welcome_message(self, guild_id: int, message_data: Dict) -> bool:
        """Set the welcome message template for a guild"""
        try:
            return await self.set_guild_setting(guild_id, "welcome_message", message_data)
        except Exception as e:
            logger.error(f"Error setting welcome message: {e}")
            return False

    async def set_leave_message(self, guild_id: int, message_data: Dict) -> bool:
        """Set the leave message template for a guild"""
        try:
            return await self.set_guild_setting(guild_id, "leave_message", message_data)
        except Exception as e:
            logger.error(f"Error setting leave message: {e}")
            return False

    async def get_welcome_message(self, guild_id: int) -> Optional[Dict]:
        """Get the welcome message template for a guild"""
        try:
            return await self.get_guild_setting(guild_id, "welcome_message")
        except Exception as e:
            logger.error(f"Error getting welcome message: {e}")
            return None

    async def get_leave_message(self, guild_id: int) -> Optional[Dict]:
        """Get the leave message template for a guild"""
        try:
            return await self.get_guild_setting(guild_id, "leave_message")
        except Exception as e:
            logger.error(f"Error getting leave message: {e}")
            return None


    # GENERAL POINT SYSTEM METHODS
    async def add_points(self, user_id: int, user_name: str, points: int, point_type: str = "general", reason: str = None):
        """Add points to a user for various activities (text messages, voice chat, etc.)"""
        try:
            # Initialize user_points collection if not exists
            if not hasattr(self, 'user_points_collection'):
                self.user_points_collection = self.db['user_points']
                # Create index for better performance
                self.user_points_collection.create_index([("user_id", 1)])
            
            # Update user's total points
            result = self.user_points_collection.update_one(
                {"user_id": str(user_id)},
                {
                    "$set": {
                        "user_name": user_name,
                        "last_updated": datetime.now()
                    },
                    "$inc": {
                        "total_points": points,
                        f"points_{point_type}": points
                    },
                    "$setOnInsert": {
                        "user_id": str(user_id),
                        "created_at": datetime.now()
                    }
                },
                upsert=True
            )
            
            # Log the point addition
            if not hasattr(self, 'point_history_collection'):
                self.point_history_collection = self.db['point_history']
                # Create index for better performance
                self.point_history_collection.create_index([("user_id", 1), ("timestamp", -1)])
            
            self.point_history_collection.insert_one({
                "user_id": str(user_id),
                "user_name": user_name,
                "points": points,
                "point_type": point_type,
                "reason": reason,
                "timestamp": datetime.now()
            })
            
            logger.debug(f"Added {points} {point_type} points to {user_name}: {reason}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding points: {e}")
            return False

    async def get_user_points(self, user_id: int) -> Dict:
        """Get a user's total points and breakdown"""
        try:
            if not hasattr(self, 'user_points_collection'):
                self.user_points_collection = self.db['user_points']
            
            result = self.user_points_collection.find_one({"user_id": str(user_id)})
            if result:
                return {
                    "total_points": result.get("total_points", 0),
                    "text_points": result.get("points_text", 0),
                    "voice_points": result.get("points_voice", 0),
                    "booster_points": result.get("points_booster", 0),
                    "last_updated": result.get("last_updated")
                }
            else:
                return {
                    "total_points": 0,
                    "text_points": 0,
                    "voice_points": 0,
                    "booster_points": 0,
                    "last_updated": None
                }
                
        except Exception as e:
            logger.error(f"Error getting user points: {e}")
            return {"total_points": 0, "text_points": 0, "voice_points": 0, "booster_points": 0, "last_updated": None}

    async def get_points_leaderboard(self, limit: int = 10) -> List[Tuple[str, int, int, int, int]]:
        """Get points leaderboard (user_name, total_points, text_points, voice_points, booster_points)"""
        try:
            if not hasattr(self, 'user_points_collection'):
                self.user_points_collection = self.db['user_points']
            
            cursor = self.user_points_collection.find().sort("total_points", -1).limit(limit)
            leaderboard = []
            
            for user in cursor:
                leaderboard.append((
                    user.get("user_name", "Unknown"),
                    user.get("total_points", 0),
                    user.get("points_text", 0),
                    user.get("points_voice", 0),
                    user.get("points_booster", 0)
                ))
            
            return leaderboard
            
        except Exception as e:
            logger.error(f"Error getting points leaderboard: {e}")
            return []

    async def get_combined_leaderboard(self, limit: int = 10, quest_manager=None) -> List[Dict]:
        """Get combined leaderboard with both general points and quest points (optimized)"""
        try:
            # Get general points leaderboard - limit to top performers only
            if not hasattr(self, 'user_points_collection'):
                self.user_points_collection = self.db['user_points']
            
            # Use aggregation pipeline to get top users by general points efficiently
            general_pipeline = [
                {"$sort": {"total_points": -1}},
                {"$limit": limit * 3},  # Get more than needed to account for quest points
                {"$project": {
                    "user_id": 1,
                    "user_name": 1,
                    "total_points": 1,
                    "points_text": 1,
                    "points_voice": 1,
                    "points_booster": 1
                }}
            ]
            
            general_points = {}
            for user in self.user_points_collection.aggregate(general_pipeline):
                user_id = user.get("user_id")
                general_points[user_id] = {
                    "user_name": user.get("user_name", "Unknown"),
                    "general_points": user.get("total_points", 0),
                    "text_points": user.get("points_text", 0),
                    "voice_points": user.get("points_voice", 0),
                    "booster_points": user.get("points_booster", 0)
                }
            
            # Get quest points if quest manager is available - optimized approach
            quest_points = {}
            if quest_manager:
                try:
                    # Use aggregation to get quest points more efficiently
                    quest_pipeline = [
                        {"$match": {"completed": True}},
                        {"$group": {
                            "_id": "$user_id",
                            "total_quest_points": {"$sum": "$points"}
                        }},
                        {"$sort": {"total_quest_points": -1}},
                        {"$limit": limit * 2}  # Limit quest users too
                    ]
                    
                    for result in quest_manager.user_quests_collection.aggregate(quest_pipeline):
                        user_id = result["_id"]
                        quest_points[user_id] = result["total_quest_points"]
                    
                    # Add achievement points efficiently
                    achievement_pipeline = [
                        {"$group": {
                            "_id": "$user_id",
                            "total_achievement_points": {"$sum": "$points"}
                        }},
                        {"$sort": {"total_achievement_points": -1}},
                        {"$limit": limit * 2}
                    ]
                    
                    for result in quest_manager.user_achievements_collection.aggregate(achievement_pipeline):
                        user_id = result["_id"]
                        quest_points[user_id] = quest_points.get(user_id, 0) + result["total_achievement_points"]
                        
                except Exception as e:
                    logger.error(f"Error getting quest points: {e}")
            
            # Combine the data
            combined_data = {}
            all_user_ids = set(general_points.keys()) | set(quest_points.keys())
            
            for user_id in all_user_ids:
                general_data = general_points.get(user_id, {})
                user_quest_points = quest_points.get(user_id, 0)
                user_general_points = general_data.get("general_points", 0)
                
                combined_data[user_id] = {
                    "user_id": user_id,
                    "user_name": general_data.get("user_name", "Unknown"),
                    "total_points": user_general_points + user_quest_points,
                    "general_points": user_general_points,
                    "quest_points": user_quest_points,
                    "text_points": general_data.get("text_points", 0),
                    "voice_points": general_data.get("voice_points", 0),
                    "booster_points": general_data.get("booster_points", 0)
                }
            
            # Sort by total points and return top entries
            sorted_users = sorted(combined_data.values(), key=lambda x: x["total_points"], reverse=True)
            return sorted_users[:limit]
            
        except Exception as e:
            logger.error(f"Error getting combined leaderboard: {e}")
            return []