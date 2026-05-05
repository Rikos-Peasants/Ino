import logging
from datetime import datetime
from typing import Dict, List, Optional
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from pymongo.collection import Collection
from pymongo.database import Database

logger = logging.getLogger(__name__)


class CustomRolesManager:
    """Manages custom roles for top rankers in art challenges and challenge mode"""

    # Art point tier roles (multiple can be held)
    ROLE_TIERS = [
        {"name": "Art Novice",         "role_id": 1341002732220641411, "min_points": 50,    "max_points": 199},
        {"name": "Art Apprentice",     "role_id": 1341002753659961476, "min_points": 200,   "max_points": 499},
        {"name": "Art Enthusiast",     "role_id": 1341002773558390855, "min_points": 500,   "max_points": 999},
        {"name": "Art Adept",          "role_id": 1341002793219268698, "min_points": 1000,  "max_points": 1999},
        {"name": "Artisan",            "role_id": 1341002813932245043, "min_points": 2000,  "max_points": 3999},
        {"name": "Master Artist",      "role_id": 1341002833494089768, "min_points": 4000,  "max_points": 7999},
        {"name": "Grandmaster Artist", "role_id": 1341002852675428423, "min_points": 8000,  "max_points": 14999},
        {"name": "Legendary Artist",   "role_id": 1341002871422324766, "min_points": 15000, "max_points": float("inf")},
    ]

    # Duel win tier roles
    DUELIST_TIERS = [
        {"name": "Duelist",      "role_id": 1341002889872011335, "min_wins": 5,  "max_wins": 19},
        {"name": "Ace Duelist",  "role_id": 1341002908999221268, "min_wins": 20, "max_wins": 49},
        {"name": "Duel Master",  "role_id": 1341002928037101608, "min_wins": 50, "max_wins": float("inf")},
    ]

    # Top-rank roles — only ONE person holds each at a time
    TOP_RANK_ROLES = {
        "most_messages": {"role_id": 1500831659602346004, "name": "Most Messages"},
        "most_vc":       {"role_id": 1500831523342127167, "name": "I really like VC"},
        "most_liked":    {"role_id": 1500831437727858929, "name": "Most Liked by Ino"},
        "most_points":   {"role_id": 1426165540451516447, "name": "Most Points"},
    }

    # Names to exclude from "Most Liked by Ino" competition
    MOST_LIKED_EXCLUDED_NAMES = ["riko"]

    def __init__(self, connection_url: Optional[str] = None, database_name: str = "Riko"):
        from config import Config
        self.connection_url = connection_url or Config.MONGO_URI
        self.database_name = database_name
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None
        self.role_assignments_collection: Optional[Collection] = None
        self.top_rank_holders_collection: Optional[Collection] = None
        self._connect()

    def _connect(self):
        try:
            self.client = MongoClient(self.connection_url, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ismaster')
            self.db = self.client[self.database_name]
            self.role_assignments_collection = self.db['custom_role_assignments']
            self.top_rank_holders_collection = self.db['top_rank_holders']
            self.role_assignments_collection.create_index([("user_id", 1), ("role_type", 1)], unique=True)
            self.top_rank_holders_collection.create_index([("category", 1)], unique=True)
            logger.info("Connected to MongoDB for Custom Roles Manager")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"Failed to connect to MongoDB: {e}")

    def _ensure_connected(self) -> bool:
        if self.client is None:
            return False
        try:
            self.client.admin.command('ismaster')
            return True
        except Exception:
            return False

    # ==================== TIER ROLE HELPERS ====================

    def get_artist_role(self, total_points: int) -> Optional[Dict]:
        for tier in self.ROLE_TIERS:
            if tier["min_points"] <= total_points <= tier["max_points"]:
                return tier
        return None

    def get_duelist_role(self, total_wins: int) -> Optional[Dict]:
        for tier in self.DUELIST_TIERS:
            if tier["min_wins"] <= total_wins <= tier["max_wins"]:
                return tier
        return None

    def get_all_tier_role_ids(self) -> List[int]:
        return [t["role_id"] for t in self.ROLE_TIERS] + [t["role_id"] for t in self.DUELIST_TIERS]

    def get_artist_role_ids(self) -> List[int]:
        return [t["role_id"] for t in self.ROLE_TIERS]

    def get_duelist_role_ids(self) -> List[int]:
        return [t["role_id"] for t in self.DUELIST_TIERS]

    # ==================== TOP-RANK HOLDER TRACKING ====================

    def get_top_rank_holder(self, category: str) -> Optional[int]:
        """Return the user_id currently holding a top-rank role, or None"""
        if not self._ensure_connected():
            return None
        try:
            doc = self.top_rank_holders_collection.find_one({"category": category})
            return doc["user_id"] if doc else None
        except Exception as e:
            logger.error(f"Error getting top rank holder for {category}: {e}")
            return None

    def set_top_rank_holder(self, category: str, user_id: Optional[int]):
        """Record who currently holds a top-rank role (None = nobody)"""
        if not self._ensure_connected():
            return
        try:
            self.top_rank_holders_collection.update_one(
                {"category": category},
                {"$set": {"category": category, "user_id": user_id, "updated_at": datetime.utcnow()}},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error setting top rank holder for {category}: {e}")

    def get_all_top_rank_role_ids(self) -> List[int]:
        return [v["role_id"] for v in self.TOP_RANK_ROLES.values()]
