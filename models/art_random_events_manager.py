import os
import asyncio
import random
import logging
import aiohttp
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
    - 'Wait who was that?' - Random character commissions artwork and requires resubmission with character
    - 'A Fishy Jumpscare' - Rare fish catch that must be included in challenges
    - 'The Art Critique' - Harsh critic gives feedback and reduces points
    - 'The Time Warp' - Challenge time is suddenly reduced
    - 'The Copycat' - AI detects suspicious similarity to another artwork
    - 'The Golden Hour' - Points are doubled for this submission
    - 'The Curse' - Random debuff applied to user
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

    # Fallback characters if serika.art fetch fails
    FALLBACK_CHARACTERS = [
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

    # Cache for character tags from serika.art
    _cached_characters: Optional[List[Dict]] = None
    _characters_cache_time: Optional[datetime] = None
    _CHARACTER_CACHE_TTL_HOURS = 24

    async def _fetch_character_tags_from_serika(self) -> List[Dict]:
        """Fetch character tags from serika.art API"""
        # Check cache first
        if (self._cached_characters and self._characters_cache_time and
            datetime.utcnow() - self._characters_cache_time < timedelta(hours=self._CHARACTER_CACHE_TTL_HOURS)):
            return self._cached_characters

        try:
            from config import Config
            serika_api_key = getattr(Config, 'SERIKA_API_KEY', None)
            serika_base_url = getattr(Config, 'SERIKA_BASE_URL', 'https://serika.art/api/v1')

            if not serika_api_key:
                logger.warning("Serika API key not configured, using fallback characters")
                return self.FALLBACK_CHARACTERS

            url = f"{serika_base_url}/tags"
            params = {
                "limit": 100,
                "type": "character",
                "sort": "count",
                "min_count": 100  # Popular characters only
            }
            headers = {
                "Authorization": f"Bearer {serika_api_key}",
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success") and data.get("data"):
                            tags = data.get("data", [])
                            characters = []
                            for tag in tags:
                                tag_name = tag.get("name")
                                if tag_name:
                                    # Clean up tag name and create personality description
                                    character_name = tag_name.replace("_", " ").title()
                                    personality = self._generate_character_personality(character_name, tag)
                                    characters.append({
                                        "name": character_name,
                                        "personality": personality,
                                        "tag": tag_name
                                    })
                            if characters:
                                self._cached_characters = characters
                                self._characters_cache_time = datetime.utcnow()
                                logger.info(f"Fetched {len(characters)} characters from serika.art")
                                return characters
                    else:
                        logger.error(f"Failed to fetch character tags: {response.status}")
        except Exception as e:
            logger.error(f"Error fetching character tags from serika.art: {e}")

        # Return fallback if fetch failed
        return self.FALLBACK_CHARACTERS

    def _generate_character_personality(self, character_name: str, tag_data: dict) -> str:
        """Generate a personality description based on character tag data"""
        # Create varied personalities based on character name patterns
        import random

        # Common anime character archetype personalities
        personalities = [
            f"a popular character who appreciates detailed artwork and subtle artistic choices.",
            f"a fan-favorite character who values creative interpretations and bold artistic visions.",
            f"a beloved character with discerning taste in art, always looking for unique style and expression.",
            f"an iconic character who rewards artists for capturing their essence and personality accurately.",
            f"a well-known character who enjoys seeing different artistic takes on their design.",
            f"a famous character with high standards for quality and composition in commissioned artwork.",
            f"a popular character who gets excited by dynamic poses, expressive features, and creative backgrounds.",
            f"a beloved character who appreciates both cute and cool interpretations equally.",
            f"a character with a strong fanbase who rewards attention to costume details and accessories.",
            f"an iconic figure who values emotional impact and storytelling through artwork.",
        ]

        return random.choice(personalities)

    async def get_random_character(self) -> Dict:
        """Get a random character from serika.art (or fallback)"""
        characters = await self._fetch_character_tags_from_serika()
        if characters:
            return random.choice(characters)
        return random.choice(self.FALLBACK_CHARACTERS)

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

        # Get random character from serika.art tags (or fallback)
        character = await self.get_random_character()
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

    # ==================== NEW RANDOM EVENTS ====================

    # Event 1: The Art Critique - Harsh critic reduces points (10% chance)
    CRITICS = [
        {"name": "Gordon Ramsay", "style": "scathing, profanity-laced, culinary-inspired metaphors"},
        {"name": "Anton Ego", "style": "cold, analytical, searching for heart and authenticity"},
        {"name": "The Arbiter", "style": "stern, judgmental, comparing to classical masters"},
        {"name": "Void Critic", "style": "nihilistic, questioning the point of art itself"},
        {"name": "Hype Beast", "style": "disappointed influencer, complaining about lack of clout"},
    ]

    async def roll_art_critique(self, image_url: str) -> Optional[Dict]:
        """Roll for art critique event (10% chance). Returns critique data if triggered."""
        if random.random() < 0.10:
            critic = random.choice(self.CRITICS)
            try:
                critique = await self._generate_critique(image_url, critic)
                if critique:
                    logger.info(f"🎭 Art Critique by {critic['name']} triggered")
                    return {"critic": critic["name"], "critique": critique, "points_penalty": 0.5}
            except Exception as e:
                logger.error(f"Error generating critique: {e}")
        return None

    async def _generate_critique(self, image_url: str, critic: Dict) -> Optional[str]:
        """Generate AI critique from the critic"""
        if not genai or not self.gemini_api_key:
            return None
        try:
            from models.gemini_utils import upload_image_to_gemini
            image_part = await upload_image_to_gemini(image_url, self.gemini_api_key)
            if not image_part:
                return None

            prompt = f"You are {critic['name']}, an extremely harsh art critic known for {critic['style']}.\n\nAnalyze this artwork and deliver a brutal but constructive critique in 2-3 sentences. Be devastating but specific about what needs improvement. Don't hold back."

            client = genai.Client(api_key=self.gemini_api_key)
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.0-flash",
                contents=[prompt, image_part]
            )
            return extract_gemini_text(response)[:300]
        except Exception as e:
            logger.error(f"Error generating critique: {e}")
            return None

    # Event 2: The Time Warp - Challenge time reduced (8% chance)
    def roll_time_warp(self) -> Optional[Dict]:
        """Roll for time warp event (8% chance). Returns time reduction if triggered."""
        if random.random() < 0.08:
            reductions = [15, 30, 45, 60]  # minutes
            reduction = random.choice(reductions)
            logger.info(f"⏰ Time Warp triggered! Challenge time reduced by {reduction} minutes")
            return {"reduction_minutes": reduction, "message": f"⏰ TIME WARP! Challenge time suddenly reduced by {reduction} minutes!"}
        return None

    # Event 3: The Copycat - Suspicious similarity detected (7% chance)
    COPYCAT_MESSAGES = [
        "🐱 COPYCAT DETECTED! AI senses suspicious similarity to existing artwork. Verification delayed for investigation...",
        "🐱 DÉJÀ VU? This looks eerily familiar... Similarity check triggered!",
        "🐱 SIMILARITY ALERT! AI detected potential reference copying. Under review...",
    ]

    def roll_copycat(self) -> Optional[Dict]:
        """Roll for copycat detection event (7% chance)."""
        if random.random() < 0.07:
            message = random.choice(self.COPYCAT_MESSAGES)
            delay_minutes = random.choice([5, 10, 15])
            logger.info(f"🐱 Copycat event triggered! Verification delayed by {delay_minutes} minutes")
            return {"delay_minutes": delay_minutes, "message": message}
        return None

    # Event 4: The Golden Hour - Points doubled (6% chance)
    GOLDEN_HOUR_MESSAGES = [
        "✨ GOLDEN HOUR! The art gods smile upon you! Points DOUBLED for this submission!",
        "✨ LUCKY STREAK! A beam of artistic fortune strikes! Double points awarded!",
        "✨ ARTISTIC BLESSING! The muse is pleased! Points multiplied by 2x!",
    ]

    def roll_golden_hour(self) -> Optional[Dict]:
        """Roll for golden hour event (6% chance). Returns multiplier if triggered."""
        if random.random() < 0.06:
            message = random.choice(self.GOLDEN_HOUR_MESSAGES)
            logger.info("✨ Golden Hour triggered! Points doubled")
            return {"multiplier": 2.0, "message": message}
        return None

    # Event 5: The Curse - Random debuff applied (5% chance)
    CURSE_DEBUFFS = ["look_of_disgust", "crickets", "forgotten_artist", "shadowbanned"]
    CURSE_MESSAGES = [
        "🔮 THE CURSE! Dark artistic forces have cursed you with a debuff!",
        "🔮 MISFORTUNE STRIKES! The art spirits are displeased... debuff applied!",
        "🔮 HEXED! A mysterious curse has befallen your artistic journey!",
    ]

    def roll_curse(self, user_id: int) -> Optional[Dict]:
        """Roll for curse event (5% chance). Applies random debuff if triggered."""
        if random.random() < 0.05:
            debuff_key = random.choice(self.CURSE_DEBUFFS)
            debuff = self.apply_debuff(user_id, debuff_key)
            if debuff:
                message = random.choice(self.CURSE_MESSAGES)
                logger.info(f"🔮 Curse triggered! Applied debuff: {debuff_key} to user {user_id}")
                return {"debuff": debuff, "message": message}
        return None

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

    def consume_one_shot_fail_debuff(self, user_id: int):
        """Deactivate one-shot-on-fail debuffs after they've been triggered"""
        if not self._ensure_connected():
            return
        try:
            self.debuffs_collection.update_many(
                {"user_id": user_id, "one_shot_on_fail": True, "active": True,
                 "expires_at": {"$gt": datetime.utcnow()}},
                {"$set": {"active": False}}
            )
        except Exception as e:
            logger.error(f"Error consuming one-shot-on-fail debuff: {e}")

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

