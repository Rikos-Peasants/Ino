import os
import asyncio
import aiohttp
import base64
import json
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pymongo import MongoClient, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from pymongo.collection import Collection
from pymongo.database import Database
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class ArtChallengeManager:
    """Manages art challenges that drop randomly in image channels"""
    
    # Challenge types
    CHALLENGE_TYPE_REMAKE = "remake"
    CHALLENGE_TYPE_TAGS = "tags"
    
    # Challenge states
    STATE_ACTIVE = "active"
    STATE_ENDED = "ended"
    STATE_JUDGING = "judging"
    
    def __init__(self, connection_url: Optional[str] = None, database_name: str = "Riko"):
        from config import Config
        
        self.connection_url = connection_url or Config.MONGO_URI
        self.database_name = database_name
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None
        self.challenges_collection: Optional[Collection] = None
        self.submissions_collection: Optional[Collection] = None
        self.challenge_stats_collection: Optional[Collection] = None
        
        # API Configuration
        self.serika_api_key = os.getenv('SERIKA_ART_KEY')
        self.serika_base_url = os.getenv('SERIKA_ART_URL_BASE', 'https://serika.art/api/v1')
        self.gemini_api_key = Config.GEMINI_API_KEY
        
        # Load art verification prompt
        self.art_system_prompt = self._load_system_prompt()
        
        # Challenge scheduling weights (pseudo-random)
        # Hour of day -> weight multiplier (higher = more likely)
        self.hour_weights = {
            # Peak hours (more challenges)
            12: 1.5, 13: 1.5, 14: 1.5,  # Noon
            18: 2.0, 19: 2.0, 20: 2.0, 21: 2.0,  # Evening peak
            22: 1.5, 23: 1.5,  # Late night
            # Off-peak hours (fewer challenges)
            0: 0.5, 1: 0.3, 2: 0.2, 3: 0.2, 4: 0.2, 5: 0.3,  # Night
            6: 0.5, 7: 0.7, 8: 0.8, 9: 0.9, 10: 1.0, 11: 1.2,  # Morning
            15: 1.0, 16: 1.0, 17: 1.2  # Afternoon
        }
        
        # Day of week weights (0=Monday, 6=Sunday)
        self.day_weights = {
            0: 0.8,  # Monday
            1: 0.9,  # Tuesday  
            2: 1.0,  # Wednesday
            3: 1.0,  # Thursday
            4: 1.3,  # Friday
            5: 1.5,  # Saturday
            6: 1.4   # Sunday
        }
        
        self._connect()
    
    def _load_system_prompt(self) -> str:
        """Load the art verification system prompt"""
        try:
            prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'system-art.txt')
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load system-art.txt: {e}")
            return "You are an art verification assistant. Verify if submissions meet challenge requirements. Respond in JSON format with 'verified' (bool) and 'reasoning' (string)."
    
    def _connect(self):
        """Connect to MongoDB"""
        try:
            self.client = MongoClient(self.connection_url, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ismaster')
            self.db = self.client[self.database_name]
            
            # Initialize collections
            self.challenges_collection = self.db['art_challenges']
            self.submissions_collection = self.db['art_challenge_submissions']
            self.challenge_stats_collection = self.db['art_challenge_stats']
            
            # Create indexes
            self.challenges_collection.create_index([("state", 1), ("end_time", 1)])
            self.challenges_collection.create_index([("channel_id", 1), ("state", 1)])
            self.submissions_collection.create_index([("challenge_id", 1), ("user_id", 1)], unique=True)
            self.submissions_collection.create_index([("challenge_id", 1), ("verified", 1)])
            self.challenge_stats_collection.create_index([("user_id", 1)], unique=True)
            
            logger.info("Connected to MongoDB for Art Challenge Manager")
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise Exception(f"MongoDB connection failed: {e}")
    
    def _ensure_connected(self) -> bool:
        """Ensure database connection is available"""
        return (self.db is not None and 
                self.challenges_collection is not None and 
                self.submissions_collection is not None)
    
    # ==================== SERIKA.ART API ====================
    
    async def _serika_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make a request to the serika.art API"""
        if not self.serika_api_key:
            logger.error("Serika API key not configured")
            return None
        
        url = f"{self.serika_base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.serika_api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            return data.get("data")
                    else:
                        logger.error(f"Serika API error: {response.status} - {await response.text()}")
                        return None
        except asyncio.TimeoutError:
            logger.error(f"Serika API timeout for {endpoint}")
            return None
        except Exception as e:
            logger.error(f"Serika API error: {e}")
            return None
    
    async def get_random_image(self, ratings: str = "safe", count: int = 1, 
                                tags: Optional[str] = None, 
                                exclude_tags: Optional[str] = None,
                                no_ai: bool = False) -> Optional[List[Dict]]:
        """Get random image(s) from serika.art"""
        params = {
            "count": count,
            "ratings": ratings
        }
        if tags:
            params["tags"] = tags
        if exclude_tags:
            params["exclude_tags"] = exclude_tags
        if no_ai:
            params["no_ai"] = "true"
        
        return await self._serika_request("/random", params)
    
    async def get_random_tags(self, count: int = 3, tag_type: str = "general") -> Optional[List[str]]:
        """Get random tags from serika.art for tag-based challenges"""
        params = {
            "limit": 100,
            "type": tag_type,
            "sort": "count",
            "min_count": 50  # Only popular tags
        }
        
        tags_data = await self._serika_request("/tags", params)
        if tags_data and isinstance(tags_data, list):
            # Randomly select from the popular tags
            selected = random.sample(tags_data, min(count, len(tags_data)))
            return [tag.get("name") for tag in selected if tag.get("name")]
        return None
    
    async def download_image_bytes(self, url: str) -> Optional[bytes]:
        """Download image from URL and return bytes"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        return await response.read()
                    logger.error(f"Failed to download image: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
            return None
    
    # ==================== GEMINI AI VERIFICATION ====================
    
    async def verify_submission(self, challenge_data: Dict, submission_image_url: str) -> Dict:
        """Verify a submission using Gemini AI"""
        if not self.gemini_api_key:
            logger.error("Gemini API key not configured")
            return {"verified": False, "reasoning": "AI verification not available", "confidence": 0}
        
        try:
            # Download the submission image
            submission_bytes = await self.download_image_bytes(submission_image_url)
            if not submission_bytes:
                return {"verified": False, "reasoning": "Could not download submission image", "confidence": 0}
            
            # Prepare the verification prompt based on challenge type
            challenge_type = challenge_data.get("challenge_type")
            
            if challenge_type == self.CHALLENGE_TYPE_REMAKE:
                # For remake challenges, we need the reference image too
                reference_url = challenge_data.get("reference_image_url")
                reference_bytes = await self.download_image_bytes(reference_url)
                
                if not reference_bytes:
                    return {"verified": False, "reasoning": "Could not download reference image", "confidence": 0}
                
                verification_prompt = f"""
Challenge Type: REMAKE
Task: Verify if the submitted image is a creative remake of the reference image.

The reference image shows the original that participants were asked to remake in their own style.
The submission is the artist's interpretation.

Please verify if this submission meets the challenge requirements.
"""
                parts = [
                    types.Part.from_bytes(mime_type="image/jpeg", data=reference_bytes),
                    types.Part.from_text(text="REFERENCE IMAGE (to be remade):"),
                    types.Part.from_bytes(mime_type="image/jpeg", data=submission_bytes),
                    types.Part.from_text(text="SUBMISSION (artist's remake):"),
                    types.Part.from_text(text=verification_prompt)
                ]
            else:
                # Tag-based challenge
                required_tags = challenge_data.get("required_tags", [])
                verification_prompt = f"""
Challenge Type: TAGS
Required Tags: {', '.join(required_tags)}
Task: Verify if the submitted image contains ALL of these required tags/elements.

Please verify if this submission includes all the required elements.
"""
                parts = [
                    types.Part.from_bytes(mime_type="image/jpeg", data=submission_bytes),
                    types.Part.from_text(text="SUBMISSION IMAGE:"),
                    types.Part.from_text(text=verification_prompt)
                ]
            
            # Initialize Gemini client
            client = genai.Client(api_key=self.gemini_api_key)
            
            # Create the content with system prompt
            contents = [
                types.Content(
                    role="user",
                    parts=parts
                )
            ]
            
            # Generate response
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=self.art_system_prompt,
                    temperature=0.3  # Lower temperature for more consistent verification
                )
            )
            
            # Parse the response
            response_text = response.text.strip()
            
            # Try to extract JSON from the response
            try:
                # Handle potential markdown code blocks
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                
                result = json.loads(response_text)
                return {
                    "verified": result.get("verified", False),
                    "confidence": result.get("confidence", 0.5),
                    "reasoning": result.get("reasoning", "No reasoning provided"),
                    "matched_elements": result.get("matched_elements", []),
                    "missing_elements": result.get("missing_elements", []),
                    "quality_notes": result.get("quality_notes", "")
                }
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse Gemini response as JSON: {response_text[:200]}")
                # Attempt basic verification from text
                verified = "verified" in response_text.lower() and "true" in response_text.lower()
                return {
                    "verified": verified,
                    "confidence": 0.5,
                    "reasoning": response_text[:500],
                    "matched_elements": [],
                    "missing_elements": []
                }
                
        except Exception as e:
            logger.error(f"Error verifying submission with Gemini: {e}")
            return {"verified": False, "reasoning": f"Verification error: {str(e)}", "confidence": 0}
    
    # ==================== CHALLENGE MANAGEMENT ====================
    
    def should_drop_challenge(self) -> bool:
        """Determine if a challenge should drop now (pseudo-random based on time)"""
        now = datetime.now()
        hour = now.hour
        day = now.weekday()
        
        # Base probability: 15% per check (if checking every 30 minutes = ~8 challenges per day average)
        base_probability = 0.15
        
        # Apply time-based weights
        hour_weight = self.hour_weights.get(hour, 1.0)
        day_weight = self.day_weights.get(day, 1.0)
        
        # Final probability
        final_probability = base_probability * hour_weight * day_weight
        
        # Cap at 40% max probability
        final_probability = min(final_probability, 0.4)
        
        roll = random.random()
        should_drop = roll < final_probability
        
        logger.debug(f"Challenge drop check: hour={hour}, day={day}, prob={final_probability:.2%}, roll={roll:.2f}, drop={should_drop}")
        
        return should_drop
    
    async def create_challenge(self, channel_id: int, guild_id: int, 
                                challenge_type: Optional[str] = None) -> Optional[Dict]:
        """Create a new art challenge"""
        if not self._ensure_connected():
            logger.error("Database not connected")
            return None
        
        # Determine challenge type if not specified
        if challenge_type is None:
            # 50/50 chance for remake vs tags
            challenge_type = random.choice([self.CHALLENGE_TYPE_REMAKE, self.CHALLENGE_TYPE_TAGS])
        
        challenge_data = {
            "channel_id": channel_id,
            "guild_id": guild_id,
            "challenge_type": challenge_type,
            "state": self.STATE_ACTIVE,
            "created_at": datetime.utcnow(),
            "end_time": datetime.utcnow() + timedelta(hours=1),  # 1 hour duration
            "message_id": None,  # Will be set after posting
            "submissions_count": 0,
            "verified_count": 0,
            "reward_points": 50  # Base reward for completing challenge
        }
        
        try:
            if challenge_type == self.CHALLENGE_TYPE_REMAKE:
                # Get a random image for remake challenge
                images = await self.get_random_image(ratings="safe", count=1, no_ai=True)
                if not images or len(images) == 0:
                    logger.error("Failed to get random image for remake challenge")
                    return None
                
                image_data = images[0] if isinstance(images, list) else images
                challenge_data["reference_image_url"] = image_data.get("url") or image_data.get("thumbnail_url")
                challenge_data["reference_image_id"] = image_data.get("id")
                challenge_data["reference_tags"] = [t.get("name") for t in image_data.get("tags", [])]
                challenge_data["challenge_title"] = "🎨 Remake This Image!"
                challenge_data["challenge_description"] = "Create your own artistic interpretation of this image! Any style is welcome - digital, traditional, sketch, anime, realistic - just capture the essence!"
                
            else:  # Tag-based challenge
                # Get random tags for the challenge
                tags = await self.get_random_tags(count=3, tag_type="general")
                if not tags or len(tags) < 2:
                    # Fallback tags if API fails
                    fallback_tags = ["nature", "character", "fantasy", "sci-fi", "cute", "dark", 
                                    "colorful", "minimalist", "portrait", "landscape", "action", "peaceful"]
                    tags = random.sample(fallback_tags, 3)
                
                challenge_data["required_tags"] = tags
                challenge_data["challenge_title"] = "🏷️ Tag Challenge!"
                challenge_data["challenge_description"] = f"Create an image that includes ALL of these elements: **{', '.join(tags)}**"
            
            # Insert into database
            result = self.challenges_collection.insert_one(challenge_data)
            challenge_data["_id"] = result.inserted_id
            challenge_data["challenge_id"] = str(result.inserted_id)
            
            logger.info(f"Created art challenge: {challenge_type} in channel {channel_id}")
            return challenge_data
            
        except Exception as e:
            logger.error(f"Error creating challenge: {e}")
            return None
    
    def update_challenge_message(self, challenge_id: str, message_id: int) -> bool:
        """Update the challenge with its Discord message ID"""
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
            logger.error(f"Error updating challenge message ID: {e}")
            return False
    
    def get_active_challenge(self, channel_id: int) -> Optional[Dict]:
        """Get the currently active challenge in a channel"""
        if not self._ensure_connected():
            return None
        
        try:
            challenge = self.challenges_collection.find_one({
                "channel_id": channel_id,
                "state": self.STATE_ACTIVE,
                "end_time": {"$gt": datetime.utcnow()}
            })
            if challenge:
                challenge["challenge_id"] = str(challenge["_id"])
            return challenge
        except Exception as e:
            logger.error(f"Error getting active challenge: {e}")
            return None
    
    def get_challenge_by_id(self, challenge_id: str) -> Optional[Dict]:
        """Get a challenge by its ID"""
        if not self._ensure_connected():
            return None
        
        try:
            from bson import ObjectId
            challenge = self.challenges_collection.find_one({"_id": ObjectId(challenge_id)})
            if challenge:
                challenge["challenge_id"] = str(challenge["_id"])
            return challenge
        except Exception as e:
            logger.error(f"Error getting challenge by ID: {e}")
            return None
    
    def get_expired_challenges(self) -> List[Dict]:
        """Get all challenges that have expired but not yet ended"""
        if not self._ensure_connected():
            return []
        
        try:
            challenges = list(self.challenges_collection.find({
                "state": self.STATE_ACTIVE,
                "end_time": {"$lte": datetime.utcnow()}
            }))
            for c in challenges:
                c["challenge_id"] = str(c["_id"])
            return challenges
        except Exception as e:
            logger.error(f"Error getting expired challenges: {e}")
            return []
    
    def end_challenge(self, challenge_id: str) -> bool:
        """Mark a challenge as ended"""
        if not self._ensure_connected():
            return False
        
        try:
            from bson import ObjectId
            self.challenges_collection.update_one(
                {"_id": ObjectId(challenge_id)},
                {"$set": {"state": self.STATE_ENDED, "ended_at": datetime.utcnow()}}
            )
            return True
        except Exception as e:
            logger.error(f"Error ending challenge: {e}")
            return False
    
    # ==================== SUBMISSION MANAGEMENT ====================
    
    async def submit_entry(self, challenge_id: str, user_id: int, 
                           image_url: str, message_id: int) -> Dict:
        """Submit an entry to a challenge"""
        if not self._ensure_connected():
            return {"success": False, "error": "Database not connected"}
        
        # Get the challenge
        challenge = self.get_challenge_by_id(challenge_id)
        if not challenge:
            return {"success": False, "error": "Challenge not found"}
        
        if challenge.get("state") != self.STATE_ACTIVE:
            return {"success": False, "error": "This challenge has ended"}
        
        if datetime.utcnow() > challenge.get("end_time"):
            return {"success": False, "error": "Time's up! This challenge has expired"}
        
        # Check if user already submitted
        existing = self.submissions_collection.find_one({
            "challenge_id": challenge_id,
            "user_id": user_id
        })
        if existing:
            return {"success": False, "error": "You've already submitted to this challenge!"}
        
        try:
            # Verify the submission with AI
            verification_result = await self.verify_submission(challenge, image_url)
            
            # Determine if verified (confidence >= 0.6)
            is_verified = verification_result.get("verified", False) and verification_result.get("confidence", 0) >= 0.6
            
            submission_data = {
                "challenge_id": challenge_id,
                "user_id": user_id,
                "image_url": image_url,
                "message_id": message_id,
                "submitted_at": datetime.utcnow(),
                "verified": is_verified,
                "verification_result": verification_result,
                "points_awarded": challenge.get("reward_points", 50) if is_verified else 0
            }
            
            self.submissions_collection.insert_one(submission_data)
            
            # Update challenge stats
            from bson import ObjectId
            update_fields = {"$inc": {"submissions_count": 1}}
            if is_verified:
                update_fields["$inc"]["verified_count"] = 1
            
            self.challenges_collection.update_one(
                {"_id": ObjectId(challenge_id)},
                update_fields
            )
            
            # Update user stats
            self._update_user_stats(user_id, is_verified, submission_data.get("points_awarded", 0))
            
            return {
                "success": True,
                "verified": is_verified,
                "verification_result": verification_result,
                "points_awarded": submission_data.get("points_awarded", 0)
            }
            
        except Exception as e:
            logger.error(f"Error submitting entry: {e}")
            return {"success": False, "error": str(e)}
    
    def _update_user_stats(self, user_id: int, verified: bool, points: int):
        """Update user's art challenge statistics"""
        if not self._ensure_connected():
            return
        
        try:
            update = {
                "$inc": {
                    "total_submissions": 1,
                    "total_points": points
                }
            }
            if verified:
                update["$inc"]["verified_submissions"] = 1
            
            self.challenge_stats_collection.update_one(
                {"user_id": user_id},
                update,
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error updating user stats: {e}")
    
    def get_challenge_submissions(self, challenge_id: str) -> List[Dict]:
        """Get all submissions for a challenge"""
        if not self._ensure_connected():
            return []
        
        try:
            submissions = list(self.submissions_collection.find(
                {"challenge_id": challenge_id}
            ).sort("submitted_at", DESCENDING))
            return submissions
        except Exception as e:
            logger.error(f"Error getting submissions: {e}")
            return []
    
    def get_user_challenge_stats(self, user_id: int) -> Optional[Dict]:
        """Get a user's art challenge statistics"""
        if not self._ensure_connected():
            return None
        
        try:
            stats = self.challenge_stats_collection.find_one({"user_id": user_id})
            return stats
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return None
    
    def get_challenge_leaderboard(self, limit: int = 10) -> List[Dict]:
        """Get the art challenge leaderboard"""
        if not self._ensure_connected():
            return []
        
        try:
            leaderboard = list(self.challenge_stats_collection.find().sort(
                [("total_points", DESCENDING), ("verified_submissions", DESCENDING)]
            ).limit(limit))
            return leaderboard
        except Exception as e:
            logger.error(f"Error getting leaderboard: {e}")
            return []
