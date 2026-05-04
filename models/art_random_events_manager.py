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
    - 'Look of disgust' - Debuff for losing 100+ points in a day
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
    ]

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
        self.gemini_api_key = Config.GEMINI_API_KEY
        self._connect()

    def _connect(self):
        try:
            self.client = MongoClient(self.connection_url, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ismaster')
            self.db = self.client[self.database_name]
            self.events_collection = self.db['art_random_events']
            self.debuffs_collection = self.db['art_debuffs']
            self.events_collection.create_index([("created_at", 1)])
            self.debuffs_collection.create_index([("user_id", 1)])
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
        """Roll for a fishy jumpscare. Returns fish type if triggered, None otherwise.
        Base chance: 5% per challenge creation"""
        if random.random() < 0.05:
            fish = random.choice(self.FISH_TYPES)
            logger.info(f"Fishy Jumpscare triggered: {fish}")
            return fish
        return None

    def get_random_fish(self) -> str:
        return random.choice(self.FISH_TYPES)

    # ==================== LOOK OF DISGUST (DEBUFF) ====================

    def check_and_apply_debuff(self, user_id: int, daily_points_lost: int) -> Optional[Dict]:
        """Check if user qualifies for the 'Look of disgust' debuff.
        Triggers when a user loses 100+ points in a single day."""
        if daily_points_lost <= self.DEBUFF_POINTS_THRESHOLD:
            debuff_data = {
                "user_id": user_id,
                "applied_at": datetime.utcnow(),
                "expires_at": datetime.utcnow() + timedelta(hours=self.DEBUFF_DURATION_HOURS),
                "multiplier": self.DEBUFF_EARNINGS_MULTIPLIER,
                "reason": f"Lost {abs(daily_points_lost)}+ points in one day",
                "active": True
            }
            try:
                self.debuffs_collection.update_one(
                    {"user_id": user_id},
                    {"$set": debuff_data},
                    upsert=True
                )
                logger.info(f"Applied 'Look of disgust' debuff to user {user_id}")
                return debuff_data
            except Exception as e:
                logger.error(f"Error applying debuff: {e}")
        return None

    def get_active_debuff(self, user_id: int) -> Optional[Dict]:
        if not self._ensure_connected():
            return None
        try:
            debuff = self.debuffs_collection.find_one({
                "user_id": user_id, "active": True,
                "expires_at": {"$gt": datetime.utcnow()}
            })
            return debuff
        except Exception as e:
            logger.error(f"Error getting active debuff: {e}")
            return None

    def get_earnings_multiplier(self, user_id: int) -> float:
        debuff = self.get_active_debuff(user_id)
        if debuff:
            return debuff.get("multiplier", 1.0)
        return 1.0

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
