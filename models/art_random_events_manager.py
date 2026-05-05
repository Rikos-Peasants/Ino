import os
import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pymongo import MongoClient, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from pymongo.collection import Collection
from pymongo.database import Database

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None

from models.gemini_utils import describe_gemini_response, extract_gemini_text

logger = logging.getLogger(__name__)


class ArtRandomEventsManager:
    """Manages random events in the art challenge system:
    - 'Wait who was that?' - Random character commissions artwork and rates it
    - 'A Fishy Jumpscare' - Rare fish catch that must be included in challenges
    - Debuffs & Buffs - Various earned/random status effects
    """

    # Fish types for the Fishy Jumpscare
    FISH_TYPES = [
        "a glowing anglerfish", "a tiny clownfish", "a majestic koi fish",
        "a derpy pufferfish", "a shimmering betta fish", "a neon tetra",
        "a grumpy catfish", "a spotted pufferfish", "a golden goldfish",
        "a swordtail fish", "a rainbow guppy", "a celestial pearl danio",
        "a galaxy rasbora", "a sparkling gourami", "a royal gramma",
        "a mandarin dragonet", "a flame angelfish", "a blue tang",
        "a moorish idol", "a lionfish", "a seahorse", "a leafy sea dragon",
        "a cookie cutter shark (tiny!)", "a blobfish", "a sunfish (mola mola)",
        "a flying fish", "an oarfish", "a barreleye fish", "a vampire squid",
        "a dumbo octopus", "a yeti crab", "a pistol shrimp",
    ]

    # Characters for "Wait who was that?"
    COMMISSION_CHARACTERS = [
        {"name": "Frieren", "personality": "an ancient elf mage who is calm, wise, and slightly detached. She appreciates subtle beauty and magical elements."},
        {"name": "Fern", "personality": "a stoic young mage who is mature beyond her years. She values precision, effort, and quiet determination."},
        {"name": "Maomao", "personality": "a curious apothecary who is analytical and eccentric. She loves unusual details, herbs, and scientific accuracy."},
        {"name": "Violet Evergarden", "personality": "a former soldier learning emotions. She values heartfelt expression, beautiful lettering, and emotional depth."},
        {"name": "Spike Spiegel", "personality": "a laid-back bounty hunter with a cool demeanor. He appreciates style, jazz aesthetics, and effortless cool."},
        {"name": "Lelouch vi Britannia", "personality": "a strategic genius with dramatic flair. He values grand compositions, symbolic elements, and commanding presence."},
        {"name": "Holo the Wise Wolf", "personality": "a playful harvest deity who loves apples and banter. She appreciates rustic charm, harvest themes, and clever details."},
        {"name": "Reigen Arataka", "personality": "a charismatic con-man with a heart of gold. He values confidence, dramatic posing, and 'special techniques'."},
        {"name": "Mob", "personality": "a shy but powerful esper. He is sincere, humble, and notices the effort behind every piece."},
        {"name": "Anya Forger", "personality": "an energetic mind-reading child. She gets way too excited about action and funny faces and gives very literal reactions."},
    ]

    # ==================== EFFECT DEFINITIONS ====================

    # Debuff definitions: {key: {name, emoji, description, multiplier, block_points, duration_hours, trigger}}
    DEBUFFS = {
        "look_of_disgust": {
            "name": "Look of Disgust",
            "emoji": "😒",
            "description": "50% earnings for 24h — earned by losing 100+ pts in one day.",
            "multiplier": 0.5,
            "block_points": False,
            "duration_hours": 24,
        },
        "artists_block": {
            "name": "Artist's Block",
            "emoji": "🥱",
            "description": "0% earnings for 1h — stare at the blank canvas.",
            "multiplier": 0.0,
            "block_points": True,
            "duration_hours": 1,
        },
        "cold_shoulder": {
            "name": "Cold Shoulder",
            "emoji": "🥶",
            "description": "75% earnings for 6h — earned by losing a duel.",
            "multiplier": 0.75,
            "block_points": False,
            "duration_hours": 6,
        },
        "the_jinx": {
            "name": "The Jinx",
            "emoji": "😈",
            "description": "Next failed submission costs -15 pts.",
            "multiplier": 1.0,
            "block_points": False,
            "duration_hours": 12,
            "one_shot_on_fail": True,
        },
        "frierens_disappointment": {
            "name": "Frieren's Disappointment",
            "emoji": "😑",
            "description": "Frieren saw your art. She says nothing. 60% earnings for 3h.",
            "multiplier": 0.6,
            "block_points": False,
            "duration_hours": 3,
        },
    }

    # Buff definitions
    BUFFS = {
        "inos_blessing": {
            "name": "Ino's Blessing",
            "emoji": "✨",
            "description": "2x points on your next verified submission!",
            "multiplier": 2.0,
            "duration_hours": 48,
            "one_shot": True,
        },
        "artistic_flow": {
            "name": "Artistic Flow",
            "emoji": "🎨",
            "description": "1.5x earnings for 2h — you're in the zone!",
            "multiplier": 1.5,
            "duration_hours": 2,
            "one_shot": False,
        },
        "crowd_favorite": {
            "name": "Crowd Favorite",
            "emoji": "🌟",
            "description": "1.5x earnings for 3h — the crowd loves you!",
            "multiplier": 1.5,
            "duration_hours": 3,
            "one_shot": False,
        },
        "momentum": {
            "name": "Momentum",
            "emoji": "⚡",
            "description": "1.25x earnings for 4h — keep the streak going!",
            "multiplier": 1.25,
            "duration_hours": 4,
            "one_shot": False,
        },
        "fish_blessing": {
            "name": "Fish Blessing",
            "emoji": "🐟",
            "description": "Including the fishy earned you 1.5x points for 1h!",
            "multiplier": 1.5,
            "duration_hours": 1,
            "one_shot": False,
        },
    }

    # Legacy threshold kept for backward compat
    DEBUFF_POINTS_THRESHOLD = -100
    DEBUFF_EARNINGS_MULTIPLIER = 0.5
    DEBUFF_DURATION_HOURS = 24

    def __init__(self, connection_url: Optional[str] = None, database_name: str = "Riko"):
        from config import Config
        self.connection_url = connection_url or Config.MONGO_URI
        self.database_name = database_name
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None
        self.events_collection: Optional[Collection] = None
        self.debuffs_collection: Optional[Collection] = None
        self.buffs_collection: Optional[Collection] = None
        self.gemini_api_key = Config.GEMINI_API_KEY
        self._connect()

    def _connect(self):
        try:
            self.client = MongoClient(self.connection_url, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ismaster')
            self.db = self.client[self.database_name]
            self.events_collection = self.db['art_random_events']
            self.debuffs_collection = self.db['art_debuffs']
            self.buffs_collection = self.db['art_buffs']
            self.events_collection.create_index([("created_at", 1)])
            self.debuffs_collection.create_index([("user_id", 1)])
            self.buffs_collection.create_index([("user_id", 1)])
            logger.info("Connected to MongoDB for Art Random Events Manager")
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

    # ==================== WAIT WHO WAS THAT ====================

    async def generate_character_commission(self, image_url: str) -> Optional[Dict]:
        """A random character 'commissions' artwork and rates it"""
        if not self.gemini_api_key:
            return None

        character = random.choice(self.COMMISSION_CHARACTERS)
        try:
            image_bytes = await self._download_image(image_url)
            if not image_bytes:
                return None

            client = genai.Client(api_key=self.gemini_api_key)
            prompt = f"""You are roleplaying as {character['name']}. Your personality: {character['personality']}

You just received this artwork as a commission. React in-character and rate it!

Respond in JSON format:
{{"reaction": "<in-character reaction to the artwork, 2-4 sentences, be entertaining and in-character>",
  "rating": <number 1-10>,
  "comment": "<brief artistic critique in character, 1-2 sentences>"}}"""

            parts = [
                types.Part.from_bytes(mime_type="image/jpeg", data=image_bytes),
                types.Part.from_text(text=prompt)
            ]

            response = client.models.generate_content(
                model="gemini-flash-latest",
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(temperature=0.9)
            )

            response_text = extract_gemini_text(response)
            if not response_text:
                return None

            import json
            try:
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                result = json.loads(response_text)
                result["character_name"] = character["name"]
                result["character_personality"] = character["personality"]
                return result
            except json.JSONDecodeError:
                return {"character_name": character["name"], "reaction": response_text[:500], "rating": 7, "comment": "Interesting work!"}

        except Exception as e:
            logger.error(f"Error generating character commission: {e}")
            return None

    # ==================== A FISHY JUMPSCARE ====================

    def roll_fishy_jumpscare(self) -> Optional[str]:
        """Roll for a fishy jumpscare. Returns fish type if triggered, None otherwise."""
        if random.random() < 0.05:
            fish = random.choice(self.FISH_TYPES)
            logger.info(f"Fishy Jumpscare triggered: {fish}")
            return fish
        return None

    def get_random_fish(self) -> str:
        return random.choice(self.FISH_TYPES)

    # ==================== DEBUFFS ====================

    def apply_debuff(self, user_id: int, debuff_key: str) -> Optional[Dict]:
        """Apply a named debuff to a user"""
        if not self._ensure_connected():
            return None
        defn = self.DEBUFFS.get(debuff_key)
        if not defn:
            return None
        # Don't stack the same debuff
        existing = self.debuffs_collection.find_one({"user_id": user_id, "debuff_key": debuff_key,
                                                      "active": True, "expires_at": {"$gt": datetime.utcnow()}})
        if existing:
            return existing
        debuff_data = {
            "user_id": user_id,
            "debuff_key": debuff_key,
            "name": defn["name"],
            "emoji": defn["emoji"],
            "multiplier": defn["multiplier"],
            "block_points": defn.get("block_points", False),
            "one_shot_on_fail": defn.get("one_shot_on_fail", False),
            "applied_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(hours=defn["duration_hours"]),
            "active": True,
        }
        try:
            self.debuffs_collection.insert_one(debuff_data)
            logger.info(f"{defn['emoji']} Applied debuff '{defn['name']}' to user {user_id}")
            return debuff_data
        except Exception as e:
            logger.error(f"Error applying debuff: {e}")
            return None

    def check_and_apply_debuff(self, user_id: int, daily_points_lost: int) -> Optional[Dict]:
        """Legacy: trigger 'look_of_disgust' when 100+ pts lost"""
        if daily_points_lost <= self.DEBUFF_POINTS_THRESHOLD:
            return self.apply_debuff(user_id, "look_of_disgust")
        return None

    def get_active_debuffs(self, user_id: int) -> List[Dict]:
        """Get all active debuffs for a user"""
        if not self._ensure_connected():
            return []
        try:
            return list(self.debuffs_collection.find({
                "user_id": user_id, "active": True,
                "expires_at": {"$gt": datetime.utcnow()}
            }))
        except Exception as e:
            logger.error(f"Error getting active debuffs: {e}")
            return []

    def get_active_debuff(self, user_id: int) -> Optional[Dict]:
        """Get worst active debuff (lowest multiplier)"""
        debuffs = self.get_active_debuffs(user_id)
        if not debuffs:
            return None
        return min(debuffs, key=lambda d: d.get("multiplier", 1.0))

    def clear_expired_debuffs(self):
        if not self._ensure_connected():
            return
        try:
            self.debuffs_collection.update_many(
                {"active": True, "expires_at": {"$lte": datetime.utcnow()}},
                {"$set": {"active": False}}
            )
        except Exception as e:
            logger.error(f"Error clearing expired debuffs: {e}")

    # ==================== BUFFS ====================

    def apply_buff(self, user_id: int, buff_key: str) -> Optional[Dict]:
        """Apply a named buff to a user"""
        if not self._ensure_connected():
            return None
        defn = self.BUFFS.get(buff_key)
        if not defn:
            return None
        # Don't stack the same buff
        existing = self.buffs_collection.find_one({"user_id": user_id, "buff_key": buff_key,
                                                    "active": True, "expires_at": {"$gt": datetime.utcnow()}})
        if existing:
            return existing
        buff_data = {
            "user_id": user_id,
            "buff_key": buff_key,
            "name": defn["name"],
            "emoji": defn["emoji"],
            "multiplier": defn["multiplier"],
            "one_shot": defn.get("one_shot", False),
            "applied_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(hours=defn["duration_hours"]),
            "active": True,
        }
        try:
            self.buffs_collection.insert_one(buff_data)
            logger.info(f"{defn['emoji']} Applied buff '{defn['name']}' to user {user_id}")
            return buff_data
        except Exception as e:
            logger.error(f"Error applying buff: {e}")
            return None

    def get_active_buffs(self, user_id: int) -> List[Dict]:
        """Get all active buffs for a user"""
        if not self._ensure_connected():
            return []
        try:
            return list(self.buffs_collection.find({
                "user_id": user_id, "active": True,
                "expires_at": {"$gt": datetime.utcnow()}
            }))
        except Exception as e:
            logger.error(f"Error getting active buffs: {e}")
            return []

    def consume_one_shot_buff(self, user_id: int):
        """Deactivate one-shot buffs after they've been used"""
        if not self._ensure_connected():
            return
        try:
            self.buffs_collection.update_many(
                {"user_id": user_id, "one_shot": True, "active": True,
                 "expires_at": {"$gt": datetime.utcnow()}},
                {"$set": {"active": False}}
            )
        except Exception as e:
            logger.error(f"Error consuming one-shot buff: {e}")

    def clear_expired_buffs(self):
        if not self._ensure_connected():
            return
        try:
            self.buffs_collection.update_many(
                {"active": True, "expires_at": {"$lte": datetime.utcnow()}},
                {"$set": {"active": False}}
            )
        except Exception as e:
            logger.error(f"Error clearing expired buffs: {e}")

    def roll_random_buff_on_success(self, user_id: int) -> Optional[Dict]:
        """5% chance to grant 'artistic_flow' buff after a verified submission"""
        if random.random() < 0.05:
            return self.apply_buff(user_id, "artistic_flow")
        return None

    # ==================== COMBINED MULTIPLIER ====================

    def get_earnings_multiplier(self, user_id: int) -> float:
        """Return the effective earnings multiplier considering all active buffs and debuffs.
        Debuffs and buffs stack multiplicatively. Block-points debuffs override to 0."""
        active_debuffs = self.get_active_debuffs(user_id)
        active_buffs = self.get_active_buffs(user_id)

        # If any debuff blocks points entirely, return 0
        for d in active_debuffs:
            if d.get("block_points"):
                return 0.0

        multiplier = 1.0
        for d in active_debuffs:
            multiplier *= d.get("multiplier", 1.0)
        for b in active_buffs:
            multiplier *= b.get("multiplier", 1.0)

        return round(multiplier, 4)

    def get_all_active_effects(self, user_id: int) -> Dict:
        """Return all active buffs and debuffs for display"""
        return {
            "debuffs": self.get_active_debuffs(user_id),
            "buffs": self.get_active_buffs(user_id),
            "multiplier": self.get_earnings_multiplier(user_id),
        }

    # ==================== HELPERS ====================

    async def _download_image(self, image_url: str) -> Optional[bytes]:
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=30) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
        return None

