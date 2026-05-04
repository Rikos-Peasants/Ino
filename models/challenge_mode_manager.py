import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pymongo import MongoClient, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from pymongo.collection import Collection
from pymongo.database import Database

logger = logging.getLogger(__name__)


class ChallengeModeManager:
    """Manages 1v1 wagering challenges between users"""

    STATE_PENDING = "pending"
    STATE_ACTIVE = "active"
    STATE_VOTING = "voting"
    STATE_COMPLETED = "completed"
    STATE_CANCELLED = "cancelled"
    STATE_EXPIRED = "expired"

    MIN_WAGER = 10
    MAX_WAGER = 10000
    VOTING_DURATION_HOURS = 1
    CHALLENGE_EXPIRY_HOURS = 24

    def __init__(self, connection_url: Optional[str] = None, database_name: str = "Riko"):
        from config import Config
        self.connection_url = connection_url or Config.MONGO_URI
        self.database_name = database_name
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None
        self.challenges_collection: Optional[Collection] = None
        self._connect()

    def _connect(self):
        try:
            self.client = MongoClient(self.connection_url, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ismaster')
            self.db = self.client[self.database_name]
            self.challenges_collection = self.db['challenge_mode_duels']
            self.challenges_collection.create_index([("state", 1), ("created_at", 1)])
            self.challenges_collection.create_index([("challenger_id", 1)])
            self.challenges_collection.create_index([("opponent_id", 1)])
            logger.info("Connected to MongoDB for Challenge Mode Manager")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"Failed to connect to MongoDB: {e}")

    def _ensure_connected(self) -> bool:
        if self.client is None or self.challenges_collection is None:
            return False
        try:
            self.client.admin.command('ismaster')
            return True
        except Exception:
            return False

    def create_challenge(self, challenger_id: int, challenger_name: str,
                         opponent_id: int, opponent_name: str, wager: int,
                         channel_id: int, guild_id: int,
                         challenge_theme: Optional[str] = None) -> Optional[Dict]:
        if not self._ensure_connected():
            return None
        if wager < self.MIN_WAGER or wager > self.MAX_WAGER:
            return None

        challenge_data = {
            "challenger_id": challenger_id, "challenger_name": challenger_name,
            "opponent_id": opponent_id, "opponent_name": opponent_name,
            "wager": wager, "channel_id": channel_id, "guild_id": guild_id,
            "challenge_theme": challenge_theme,
            "state": self.STATE_PENDING,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(hours=self.CHALLENGE_EXPIRY_HOURS),
            "challenger_submission": None, "opponent_submission": None,
            "challenger_votes": 0, "opponent_votes": 0,
            "voters": [], "winner_id": None,
            "message_id": None, "voting_message_id": None,
            "fishy_active": False, "fishy_required_item": None,
        }
        try:
            result = self.challenges_collection.insert_one(challenge_data)
            challenge_data["_id"] = result.inserted_id
            challenge_data["challenge_id"] = str(result.inserted_id)
            logger.info(f"Created challenge: {challenger_name} vs {opponent_name} for {wager} pts")
            return challenge_data
        except Exception as e:
            logger.error(f"Error creating challenge: {e}")
            return None

    def accept_challenge(self, challenge_id: str, opponent_id: int) -> bool:
        if not self._ensure_connected():
            return False
        try:
            from bson import ObjectId
            result = self.challenges_collection.update_one(
                {"_id": ObjectId(challenge_id), "opponent_id": opponent_id, "state": self.STATE_PENDING},
                {"$set": {"state": self.STATE_ACTIVE, "accepted_at": datetime.utcnow()}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error accepting challenge: {e}")
            return False

    def decline_challenge(self, challenge_id: str, opponent_id: int) -> bool:
        if not self._ensure_connected():
            return False
        try:
            from bson import ObjectId
            result = self.challenges_collection.update_one(
                {"_id": ObjectId(challenge_id), "opponent_id": opponent_id, "state": self.STATE_PENDING},
                {"$set": {"state": self.STATE_CANCELLED, "cancelled_at": datetime.utcnow()}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error declining challenge: {e}")
            return False

    def submit_entry(self, challenge_id: str, user_id: int, image_url: str, message_id: int) -> Dict:
        if not self._ensure_connected():
            return {"success": False, "error": "Database not connected"}
        challenge = self.get_challenge(challenge_id)
        if not challenge:
            return {"success": False, "error": "Challenge not found"}
        if challenge.get("state") != self.STATE_ACTIVE:
            return {"success": False, "error": "Challenge is not active"}

        if user_id == challenge.get("challenger_id"):
            field = "challenger_submission"
        elif user_id == challenge.get("opponent_id"):
            field = "opponent_submission"
        else:
            return {"success": False, "error": "You are not part of this challenge"}

        submission_data = {"image_url": image_url, "message_id": message_id, "submitted_at": datetime.utcnow()}
        try:
            from bson import ObjectId
            self.challenges_collection.update_one(
                {"_id": ObjectId(challenge_id)},
                {"$set": {field: submission_data}}
            )
            updated = self.get_challenge(challenge_id)
            if updated.get("challenger_submission") and updated.get("opponent_submission"):
                self.challenges_collection.update_one(
                    {"_id": ObjectId(challenge_id)},
                    {"$set": {"state": self.STATE_VOTING, "voting_started_at": datetime.utcnow(),
                              "voting_ends_at": datetime.utcnow() + timedelta(hours=self.VOTING_DURATION_HOURS)}}
                )
            return {"success": True, "submission": submission_data}
        except Exception as e:
            logger.error(f"Error submitting entry: {e}")
            return {"success": False, "error": str(e)}

    def record_vote(self, challenge_id: str, voter_id: int, vote_for: str) -> Dict:
        if not self._ensure_connected():
            return {"success": False, "error": "Database not connected"}
        challenge = self.get_challenge(challenge_id)
        if not challenge:
            return {"success": False, "error": "Challenge not found"}
        if challenge.get("state") != self.STATE_VOTING:
            return {"success": False, "error": "Voting is not active"}
        if datetime.utcnow() > challenge.get("voting_ends_at", datetime.max):
            return {"success": False, "error": "Voting has ended"}
        voters = challenge.get("voters", [])
        if voter_id in voters:
            return {"success": False, "error": "You already voted"}
        if voter_id in (challenge.get("challenger_id"), challenge.get("opponent_id")):
            return {"success": False, "error": "Participants cannot vote"}

        inc_field = "challenger_votes" if vote_for == "challenger" else "opponent_votes"
        try:
            from bson import ObjectId
            self.challenges_collection.update_one(
                {"_id": ObjectId(challenge_id)},
                {"$inc": {inc_field: 1}, "$push": {"voters": voter_id}}
            )
            return {"success": True}
        except Exception as e:
            logger.error(f"Error recording vote: {e}")
            return {"success": False, "error": str(e)}

    def resolve_challenge(self, challenge_id: str) -> Optional[Dict]:
        if not self._ensure_connected():
            return None
        challenge = self.get_challenge(challenge_id)
        if not challenge or challenge.get("state") not in [self.STATE_VOTING, self.STATE_ACTIVE]:
            return None

        cv = challenge.get("challenger_votes", 0)
        ov = challenge.get("opponent_votes", 0)
        if cv > ov:
            winner_id = challenge.get("challenger_id")
        elif ov > cv:
            winner_id = challenge.get("opponent_id")
        else:
            winner_id = None

        try:
            from bson import ObjectId
            self.challenges_collection.update_one(
                {"_id": ObjectId(challenge_id)},
                {"$set": {"state": self.STATE_COMPLETED, "winner_id": winner_id,
                          "completed_at": datetime.utcnow(), "final_challenger_votes": cv,
                          "final_opponent_votes": ov}}
            )
            challenge["winner_id"] = winner_id
            challenge["state"] = self.STATE_COMPLETED
            return challenge
        except Exception as e:
            logger.error(f"Error resolving challenge: {e}")
            return None

    def get_challenge(self, challenge_id: str) -> Optional[Dict]:
        if not self._ensure_connected():
            return None
        try:
            from bson import ObjectId
            challenge = self.challenges_collection.find_one({"_id": ObjectId(challenge_id)})
            if challenge:
                challenge["challenge_id"] = str(challenge["_id"])
            return challenge
        except Exception as e:
            logger.error(f"Error getting challenge: {e}")
            return None

    def get_pending_challenges_for_user(self, user_id: int) -> List[Dict]:
        if not self._ensure_connected():
            return []
        try:
            challenges = list(self.challenges_collection.find({
                "opponent_id": user_id, "state": self.STATE_PENDING,
                "expires_at": {"$gt": datetime.utcnow()}
            }))
            for c in challenges:
                c["challenge_id"] = str(c["_id"])
            return challenges
        except Exception as e:
            logger.error(f"Error getting pending challenges: {e}")
            return []

    def get_active_challenges(self) -> List[Dict]:
        if not self._ensure_connected():
            return []
        try:
            challenges = list(self.challenges_collection.find({
                "state": {"$in": [self.STATE_ACTIVE, self.STATE_VOTING]}
            }))
            for c in challenges:
                c["challenge_id"] = str(c["_id"])
            return challenges
        except Exception as e:
            logger.error(f"Error getting active challenges: {e}")
            return []

    def get_expired_voting_challenges(self) -> List[Dict]:
        if not self._ensure_connected():
            return []
        try:
            challenges = list(self.challenges_collection.find({
                "state": self.STATE_VOTING,
                "voting_ends_at": {"$lte": datetime.utcnow()}
            }))
            for c in challenges:
                c["challenge_id"] = str(c["_id"])
            return challenges
        except Exception as e:
            logger.error(f"Error getting expired voting challenges: {e}")
            return []

    def get_user_challenge_stats(self, user_id: int) -> Dict:
        if not self._ensure_connected():
            return {"wins": 0, "losses": 0, "draws": 0, "total_wagered": 0, "total_won": 0}
        try:
            completed = list(self.challenges_collection.find({
                "state": self.STATE_COMPLETED,
                "$or": [{"challenger_id": user_id}, {"opponent_id": user_id}]
            }))
            stats = {"wins": 0, "losses": 0, "draws": 0, "total_wagered": 0, "total_won": 0}
            for c in completed:
                wager = c.get("wager", 0)
                stats["total_wagered"] += wager
                if c.get("winner_id") == user_id:
                    stats["wins"] += 1
                    stats["total_won"] += wager * 2
                elif c.get("winner_id") is None:
                    stats["draws"] += 1
                    stats["total_won"] += wager
                else:
                    stats["losses"] += 1
            return stats
        except Exception as e:
            logger.error(f"Error getting user challenge stats: {e}")
            return {"wins": 0, "losses": 0, "draws": 0, "total_wagered": 0, "total_won": 0}

    def set_fishy(self, challenge_id: str, required_item: str) -> bool:
        if not self._ensure_connected():
            return False
        try:
            from bson import ObjectId
            self.challenges_collection.update_one(
                {"_id": ObjectId(challenge_id)},
                {"$set": {"fishy_active": True, "fishy_required_item": required_item}}
            )
            return True
        except Exception as e:
            logger.error(f"Error setting fishy: {e}")
            return False

    def update_message_id(self, challenge_id: str, message_id: int) -> bool:
        if not self._ensure_connected():
            return False
        try:
            from bson import ObjectId
            self.challenges_collection.update_one(
                {"_id": ObjectId(challenge_id)},
                {"$set": {"message_id": message_id}}
            )
            return True
        except Exception as e:
            logger.error(f"Error updating message ID: {e}")
            return False
