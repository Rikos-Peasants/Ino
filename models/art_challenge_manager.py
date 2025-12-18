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
    CHALLENGE_TYPE_MIXED = "mixed"
    CHALLENGE_TYPE_EDIT = "edit"
    
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
    
    # Tags that are too specific, meta, or impossible to draw without context
    EXCLUDED_TAGS = {
        # Meta/copyright tags
        "official alternate costume", "official alternate hairstyle", "official alternate hair length",
        "alternate costume", "alternate hairstyle", "alternate hair color", "alternate eye color",
        "borrowed character", "crossover", "parody", "copyright request", "character request",
        "tagme", "commentary", "translated", "translation request", "check translation",
        "image sample", "sample", "watermark", "web address", "artist name", "signature",
        "dated", "revision", "variant set", "image set", "manga", "comic", "4koma",
        # Too specific character references
        "cosplay", "seiyuu connection", "voice actor connection", "real life insert",
        # Technical/quality tags
        "highres", "absurdres", "incredibly absurdres", "huge filesize", "lowres",
        "bad anatomy", "bad hands", "bad feet", "bad proportions", "error",
        "jpeg artifacts", "compression artifacts", "blurry", "out of frame",
        # Too abstract/meta
        "what", "everyone", "solo focus", "third-party edit", "edit", "photoshop", "stitched",
        # Impossible to verify without knowing character
        "character name", "series name", "artist request",
        # Other problematic tags
        "unknown", "unfinished", "wip", "sketch", "lineart", "monochrome",
        "traditional media", "photo", "real life", "3d", "animated", "video",
        "sound", "audio", "has audio",
    }
    
    async def get_random_tags(self, count: int = 3, tag_type: str = "general") -> Optional[List[str]]:
        """Get random tags from serika.art for tag-based challenges"""
        params = {
            "limit": 200,  # Get more to have enough after filtering
            "type": tag_type,
            "sort": "count",
            "min_count": 50  # Only popular tags
        }
        
        tags_data = await self._serika_request("/tags", params)
        if tags_data and isinstance(tags_data, list):
            # Filter out excluded/problematic tags
            filtered_tags = [
                tag.get("name") for tag in tags_data 
                if tag.get("name") and tag.get("name").lower() not in self.EXCLUDED_TAGS
                and not any(excluded in tag.get("name", "").lower() for excluded in self.EXCLUDED_TAGS)
            ]
            
            if len(filtered_tags) >= count:
                selected = random.sample(filtered_tags, count)
                return selected
        
        # Fallback if API fails or not enough tags
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
    
    def _compute_image_hash(self, image_bytes: bytes) -> Optional[str]:
        """Compute a perceptual hash for an image to detect duplicates.
        
        Uses average hash (aHash) for fast comparison.
        Returns a hex string hash or None if computation fails.
        """
        try:
            from PIL import Image
            import io
            import hashlib
            
            # Open and convert to grayscale
            img = Image.open(io.BytesIO(image_bytes)).convert('L')
            
            # Resize to 16x16 for perceptual hash (more precision than 8x8)
            img = img.resize((16, 16), Image.Resampling.LANCZOS)
            
            # Get pixel data
            pixels = list(img.getdata())
            
            # Compute average
            avg = sum(pixels) / len(pixels)
            
            # Create binary hash based on average
            bits = ''.join('1' if pixel > avg else '0' for pixel in pixels)
            
            # Convert to hex
            hash_value = hex(int(bits, 2))[2:].zfill(64)  # 256 bits = 64 hex chars
            
            return hash_value
        except Exception as e:
            logger.warning(f"Failed to compute image hash: {e}")
            return None
    
    def _compute_exact_hash(self, image_bytes: bytes) -> str:
        """Compute MD5 hash for exact duplicate detection"""
        import hashlib
        return hashlib.md5(image_bytes).hexdigest()
    
    def _compare_image_hashes(self, hash1: str, hash2: str) -> float:
        """Compare two perceptual hashes and return similarity (0.0-1.0).
        
        Uses Hamming distance - lower distance = more similar.
        Returns 1.0 for identical, 0.0 for completely different.
        """
        if not hash1 or not hash2 or len(hash1) != len(hash2):
            return 0.0
        
        try:
            # Convert hex to binary
            bin1 = bin(int(hash1, 16))[2:].zfill(256)
            bin2 = bin(int(hash2, 16))[2:].zfill(256)
            
            # Calculate Hamming distance
            hamming_distance = sum(c1 != c2 for c1, c2 in zip(bin1, bin2))
            
            # Convert to similarity (256 bits total)
            similarity = 1.0 - (hamming_distance / 256.0)
            
            return similarity
        except Exception as e:
            logger.warning(f"Failed to compare hashes: {e}")
            return 0.0
    
    async def check_image_similarity(self, reference_url: str, submission_url: str) -> dict:
        """Check if submission is too similar to reference image (potential reupload).
        
        Returns:
            dict with 'is_duplicate', 'similarity_score', 'is_exact_match'
        """
        try:
            # Download both images
            reference_bytes = await self.download_image_bytes(reference_url)
            submission_bytes = await self.download_image_bytes(submission_url)
            
            if not reference_bytes or not submission_bytes:
                return {"is_duplicate": False, "similarity_score": 0.0, "is_exact_match": False}
            
            # Check for exact match first (MD5)
            ref_exact_hash = self._compute_exact_hash(reference_bytes)
            sub_exact_hash = self._compute_exact_hash(submission_bytes)
            
            if ref_exact_hash == sub_exact_hash:
                logger.warning(f"Exact duplicate detected! Same MD5 hash.")
                return {"is_duplicate": True, "similarity_score": 1.0, "is_exact_match": True}
            
            # Compute perceptual hashes
            ref_phash = self._compute_image_hash(reference_bytes)
            sub_phash = self._compute_image_hash(submission_bytes)
            
            if not ref_phash or not sub_phash:
                return {"is_duplicate": False, "similarity_score": 0.0, "is_exact_match": False}
            
            # Compare hashes
            similarity = self._compare_image_hashes(ref_phash, sub_phash)
            
            # Threshold: 95% similarity is considered a duplicate/reupload
            is_duplicate = similarity >= 0.95
            
            if is_duplicate:
                logger.warning(f"Near-duplicate detected! Similarity: {similarity:.2%}")
            
            return {
                "is_duplicate": is_duplicate,
                "similarity_score": similarity,
                "is_exact_match": False
            }
            
        except Exception as e:
            logger.error(f"Error checking image similarity: {e}")
            return {"is_duplicate": False, "similarity_score": 0.0, "is_exact_match": False}
    
    # ==================== GEMINI AI VERIFICATION ====================
    
    async def _generate_edit_item(self, image_url: str) -> Optional[str]:
        """Use Gemini AI to decide what item should be added to an image for edit challenge"""
        if not self.gemini_api_key:
            logger.error("Gemini API key not configured for edit item generation")
            return None
        
        try:
            # Download the image
            image_bytes = await self.download_image_bytes(image_url)
            if not image_bytes:
                return None
            
            # Initialize Gemini client
            client = genai.Client(api_key=self.gemini_api_key)
            
            prompt = """Look at this image and suggest ONE creative item/object that would be fun and interesting to add to it.

The item should:
- Be something that would complement or contrast interestingly with the image
- Be specific enough to be recognizable (e.g., "a glowing lantern" not just "light")
- Be achievable to draw/edit in (not too complex)
- Be fun and creative

Respond with ONLY the item name in lowercase, nothing else. Examples:
- a tiny dragon
- floating bubbles
- a mysterious black cat
- sparkles and stars
- a treasure chest
- a magic portal"""

            parts = [
                types.Part.from_bytes(mime_type="image/jpeg", data=image_bytes),
                types.Part.from_text(text=prompt)
            ]
            
            contents = [
                types.Content(
                    role="user",
                    parts=parts
                )
            ]
            
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.9  # Higher temperature for more creative suggestions
                )
            )
            
            item = response.text.strip().lower()
            # Clean up the response
            if item.startswith("- "):
                item = item[2:]
            if len(item) > 50:  # Too long, probably got extra text
                return None
            
            logger.info(f"AI suggested edit item: {item}")
            return item
            
        except Exception as e:
            logger.error(f"Error generating edit item: {e}")
            return None
    
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
            
            # For remake and edit challenges, check if user just re-uploaded the reference image
            if challenge_type in [self.CHALLENGE_TYPE_REMAKE, self.CHALLENGE_TYPE_EDIT]:
                reference_url = challenge_data.get("reference_image_url")
                if reference_url:
                    similarity_check = await self.check_image_similarity(reference_url, submission_image_url)
                    if similarity_check.get("is_duplicate"):
                        similarity_score = similarity_check.get("similarity_score", 1.0)
                        is_exact = similarity_check.get("is_exact_match", False)
                        
                        return {
                            "verified": False,
                            "confidence": 1.0,  # High confidence this is a duplicate
                            "reasoning": f"This submission appears to be the same as the reference image (similarity: {similarity_score:.0%}). Please create your own artwork instead of re-uploading the original!",
                            "matched_elements": [],
                            "missing_elements": ["Original artwork", "Creative interpretation"],
                            "quality_notes": "Duplicate/reupload detected",
                            "is_duplicate": True,
                            "is_exact_match": is_exact,
                            "similarity_score": similarity_score
                        }
            
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
                    types.Part.from_text(text="REFERENCE IMAGE (to be remade):"),
                    types.Part.from_bytes(mime_type="image/jpeg", data=reference_bytes),
                    types.Part.from_text(text="SUBMISSION (artist's remake):"),
                    types.Part.from_bytes(mime_type="image/jpeg", data=submission_bytes),
                    types.Part.from_text(text=verification_prompt)
                ]
            
            elif challenge_type == self.CHALLENGE_TYPE_MIXED:
                # For mixed challenges, we need BOTH reference images
                reference_url_1 = challenge_data.get("reference_image_url")
                reference_url_2 = challenge_data.get("reference_image_url_2")
                
                reference_bytes_1 = await self.download_image_bytes(reference_url_1)
                reference_bytes_2 = await self.download_image_bytes(reference_url_2)
                
                if not reference_bytes_1 or not reference_bytes_2:
                    return {"verified": False, "reasoning": "Could not download reference images", "confidence": 0}
                
                verification_prompt = f"""
Challenge Type: MIXED
Task: Verify if the submitted image creatively combines elements from BOTH reference images.

Reference Image 1 and Reference Image 2 are the two images that participants were asked to mix together.
The submission should contain elements from BOTH images creatively combined into one artwork.

Please verify if this submission successfully mixes elements from both reference images.
"""
                parts = [
                    types.Part.from_text(text="REFERENCE IMAGE 1 (first image to mix):"),
                    types.Part.from_bytes(mime_type="image/jpeg", data=reference_bytes_1),
                    types.Part.from_text(text="REFERENCE IMAGE 2 (second image to mix):"),
                    types.Part.from_bytes(mime_type="image/jpeg", data=reference_bytes_2),
                    types.Part.from_text(text="SUBMISSION (artist's mixed artwork):"),
                    types.Part.from_bytes(mime_type="image/jpeg", data=submission_bytes),
                    types.Part.from_text(text=verification_prompt)
                ]
            
            elif challenge_type == self.CHALLENGE_TYPE_EDIT:
                # For edit challenges, check if the required item was added
                reference_url = challenge_data.get("reference_image_url")
                required_item = challenge_data.get("required_item", "something new")
                reference_bytes = await self.download_image_bytes(reference_url)
                
                if not reference_bytes:
                    return {"verified": False, "reasoning": "Could not download reference image", "confidence": 0}
                
                verification_prompt = f"""
Challenge Type: EDIT
Required Item to Add: {required_item}
Task: Verify if the submitted image is an edited version of the reference with "{required_item}" added to it.

The reference image shows the original that participants were asked to modify.
The submission should be the same image (or a recreation of it) with "{required_item}" added.

Check if:
1. The submission is based on/similar to the reference image
2. The required item "{required_item}" has been added to the image
3. The item is clearly visible and recognizable

Please verify if this submission meets the challenge requirements.
"""
                parts = [
                    types.Part.from_text(text="REFERENCE IMAGE (original to edit):"),
                    types.Part.from_bytes(mime_type="image/jpeg", data=reference_bytes),
                    types.Part.from_text(text=f"SUBMISSION (should have '{required_item}' added):"),
                    types.Part.from_bytes(mime_type="image/jpeg", data=submission_bytes),
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
                    types.Part.from_text(text="SUBMISSION IMAGE:"),
                    types.Part.from_bytes(mime_type="image/jpeg", data=submission_bytes),
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
    
    def get_todays_channel(self) -> Tuple[int, str]:
        """Get which channel should have challenges today and the appropriate rating.
        
        Alternates between SFW and NSFW channels based on the day of year.
        
        Returns:
            Tuple of (channel_id, rating) where rating is 'safe' or 'questionable'
        """
        from config import Config
        
        day_of_year = datetime.now().timetuple().tm_yday
        
        # Alternate between channels based on day
        # Even days = SFW channel, Odd days = NSFW channel
        if day_of_year % 2 == 0:
            channel_id = getattr(Config, 'ART_CHALLENGE_CHANNEL_SFW', Config.ART_CHALLENGE_CHANNELS[0])
            rating = "safe"
        else:
            channel_id = getattr(Config, 'ART_CHALLENGE_CHANNEL_NSFW', Config.ART_CHALLENGE_CHANNELS[1] if len(Config.ART_CHALLENGE_CHANNELS) > 1 else Config.ART_CHALLENGE_CHANNELS[0])
            rating = "questionable"
        
        logger.debug(f"Today's challenge channel: {channel_id} (rating: {rating}, day {day_of_year})")
        return channel_id, rating
    
    def get_channel_rating(self, channel_id: int) -> str:
        """Get the appropriate rating for a specific channel.
        
        Args:
            channel_id: The channel ID to check
            
        Returns:
            'safe' for SFW channels, 'questionable' for NSFW channels
        """
        from config import Config
        
        nsfw_channel = getattr(Config, 'ART_CHALLENGE_CHANNEL_NSFW', None)
        if nsfw_channel and channel_id == nsfw_channel:
            return "questionable"
        return "safe"
    
    def should_drop_challenge(self) -> bool:
        """Determine if a challenge should drop now (pseudo-random based on time)
        
        Target: 2-24 challenges per day (average ~8-12)
        With 15-minute checks = 96 checks per day
        Base probability ~10% = ~10 challenges per day average
        """
        now = datetime.now()
        hour = now.hour
        day = now.weekday()
        
        # Base probability: 10% per check (96 checks/day * 10% = ~10 challenges/day average)
        base_probability = 0.10
        
        # Apply time-based weights
        hour_weight = self.hour_weights.get(hour, 1.0)
        day_weight = self.day_weights.get(day, 1.0)
        
        # Final probability
        final_probability = base_probability * hour_weight * day_weight
        
        # Cap at 25% max probability (ensures max ~24 per day)
        final_probability = min(final_probability, 0.25)
        
        # Minimum 2% to ensure at least some drops even during low-activity times
        final_probability = max(final_probability, 0.02)
        
        roll = random.random()
        should_drop = roll < final_probability
        
        logger.debug(f"Challenge drop check: hour={hour}, day={day}, prob={final_probability:.2%}, roll={roll:.2f}, drop={should_drop}")
        
        return should_drop
    
    async def create_challenge(self, channel_id: int, guild_id: int, 
                                challenge_type: Optional[str] = None,
                                rating: str = "safe") -> Optional[Dict]:
        """Create a new art challenge
        
        Args:
            channel_id: The channel to create the challenge in
            guild_id: The guild ID
            challenge_type: 'remake', 'tags', 'mixed', or 'edit', random if None
            rating: Image rating - 'safe' for SFW, 'questionable' for NSFW channels
        """
        if not self._ensure_connected():
            logger.error("Database not connected")
            return None
        
        # Determine challenge type if not specified
        if challenge_type is None:
            # Random choice between all four types
            challenge_type = random.choice([self.CHALLENGE_TYPE_REMAKE, self.CHALLENGE_TYPE_TAGS, self.CHALLENGE_TYPE_MIXED, self.CHALLENGE_TYPE_EDIT])
        
        challenge_data = {
            "channel_id": channel_id,
            "guild_id": guild_id,
            "challenge_type": challenge_type,
            "rating": rating,  # Store the rating used
            "state": self.STATE_ACTIVE,
            "created_at": datetime.utcnow(),
            "end_time": datetime.utcnow() + timedelta(hours=1),  # 1 hour duration
            "message_id": None,  # Will be set after posting
            "submissions_count": 0,
            "verified_count": 0,
            "reward_points": 50 if challenge_type not in [self.CHALLENGE_TYPE_MIXED, self.CHALLENGE_TYPE_EDIT] else 75  # Mixed/Edit are harder, more points
        }
        
        try:
            if challenge_type == self.CHALLENGE_TYPE_REMAKE:
                # Get a random image for remake challenge with appropriate rating
                images = await self.get_random_image(ratings=rating, count=1, no_ai=True)
                if not images or len(images) == 0:
                    logger.error(f"Failed to get random image for remake challenge (rating: {rating})")
                    return None
                
                image_data = images[0] if isinstance(images, list) else images
                challenge_data["reference_image_url"] = image_data.get("url") or image_data.get("thumbnail_url")
                challenge_data["reference_image_id"] = image_data.get("id")
                challenge_data["reference_tags"] = [t.get("name") for t in image_data.get("tags", [])]
                challenge_data["challenge_title"] = "🎨 Remake This Image!"
                challenge_data["challenge_description"] = "Create your own artistic interpretation of this image! Any style is welcome - digital, traditional, sketch, anime, realistic - just capture the essence!"
            
            elif challenge_type == self.CHALLENGE_TYPE_MIXED:
                # Get TWO random images for mixed challenge
                images = await self.get_random_image(ratings=rating, count=2, no_ai=True)
                if not images or len(images) < 2:
                    # Try getting them separately if count=2 doesn't work
                    image1 = await self.get_random_image(ratings=rating, count=1, no_ai=True)
                    image2 = await self.get_random_image(ratings=rating, count=1, no_ai=True)
                    if not image1 or not image2:
                        logger.error(f"Failed to get random images for mixed challenge (rating: {rating})")
                        return None
                    images = [image1[0] if isinstance(image1, list) else image1, 
                              image2[0] if isinstance(image2, list) else image2]
                
                image1_data = images[0] if isinstance(images, list) else images
                image2_data = images[1] if isinstance(images, list) and len(images) > 1 else images
                
                challenge_data["reference_image_url"] = image1_data.get("url") or image1_data.get("thumbnail_url")
                challenge_data["reference_image_url_2"] = image2_data.get("url") or image2_data.get("thumbnail_url")
                challenge_data["reference_image_id"] = image1_data.get("id")
                challenge_data["reference_image_id_2"] = image2_data.get("id")
                challenge_data["reference_tags"] = [t.get("name") for t in image1_data.get("tags", [])]
                challenge_data["reference_tags_2"] = [t.get("name") for t in image2_data.get("tags", [])]
                challenge_data["challenge_title"] = "🔀 Mix These Images!"
                challenge_data["challenge_description"] = "Combine elements from BOTH images into one creative artwork! Merge characters, settings, styles, or concepts - be creative with how you blend them together!"
            
            elif challenge_type == self.CHALLENGE_TYPE_EDIT:
                # Get a random image and have AI pick an item to add
                images = await self.get_random_image(ratings=rating, count=1, no_ai=True)
                if not images or len(images) == 0:
                    logger.error(f"Failed to get random image for edit challenge (rating: {rating})")
                    return None
                
                image_data = images[0] if isinstance(images, list) else images
                reference_url = image_data.get("url") or image_data.get("thumbnail_url")
                
                # Use AI to decide what item should be added
                item_to_add = await self._generate_edit_item(reference_url)
                if not item_to_add:
                    # Fallback items if AI fails
                    fallback_items = ["a glowing crystal", "a mysterious cat", "floating bubbles", "a rainbow", 
                                     "a tiny dragon", "sparkles", "a magic wand", "a cute ghost", "fairy lights",
                                     "a treasure chest", "butterflies", "a crown", "a sword", "flowers"]
                    item_to_add = random.choice(fallback_items)
                
                challenge_data["reference_image_url"] = reference_url
                challenge_data["reference_image_id"] = image_data.get("id")
                challenge_data["reference_tags"] = [t.get("name") for t in image_data.get("tags", [])]
                challenge_data["required_item"] = item_to_add
                challenge_data["challenge_title"] = "✏️ Edit This Image!"
                challenge_data["challenge_description"] = f"Take this image and add **{item_to_add}** to it! Edit, draw over, or recreate it with the new element added."
                
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
    
    async def select_best_submission(self, challenge_id: str, challenge_data: dict) -> Optional[Dict]:
        """Use AI to select the best submission from all verified entries
        
        Returns the winning submission dict with user_id, image_url, and reasoning
        """
        if not self._ensure_connected():
            return None
        
        # Get all verified submissions
        submissions = self.get_challenge_submissions(challenge_id)
        verified_submissions = [s for s in submissions if s.get("verified")]
        
        if len(verified_submissions) == 0:
            return None
        
        if len(verified_submissions) == 1:
            # Only one verified submission - they win by default
            winner = verified_submissions[0]
            return {
                "user_id": winner.get("user_id"),
                "image_url": winner.get("image_url"),
                "reasoning": "Only verified submission - winner by default!"
            }
        
        try:
            # Download all submission images
            submission_data = []
            async with aiohttp.ClientSession() as session:
                for sub in verified_submissions[:10]:  # Limit to 10 to avoid token limits
                    try:
                        async with session.get(sub.get("image_url")) as resp:
                            if resp.status == 200:
                                image_bytes = await resp.read()
                                submission_data.append({
                                    "user_id": sub.get("user_id"),
                                    "image_url": sub.get("image_url"),
                                    "image_bytes": image_bytes
                                })
                    except Exception as e:
                        logger.warning(f"Failed to download submission image: {e}")
                        continue
            
            if len(submission_data) < 1:
                return None
            
            if len(submission_data) == 1:
                return {
                    "user_id": submission_data[0]["user_id"],
                    "image_url": submission_data[0]["image_url"],
                    "reasoning": "Only downloadable submission - winner by default!"
                }
            
            # Build the prompt for AI judging
            challenge_type = challenge_data.get("challenge_type")
            
            if challenge_type == self.CHALLENGE_TYPE_REMAKE:
                context = f"This was a REMAKE challenge where artists recreated a reference image in their own style."
            elif challenge_type == self.CHALLENGE_TYPE_EDIT:
                required_item = challenge_data.get("required_item", "an item")
                context = f"This was an EDIT challenge where artists added '{required_item}' to a reference image."
            elif challenge_type == self.CHALLENGE_TYPE_MIXED:
                context = f"This was a MIXED challenge combining elements from two reference images."
            else:
                tags = challenge_data.get("required_tags", [])
                context = f"This was a TAG challenge requiring these elements: {', '.join(tags)}."
            
            judging_prompt = f"""You are judging an art challenge competition.

{context}

You are shown {len(submission_data)} verified submissions. Please select the BEST one based on:
1. Creativity and originality
2. Artistic quality and effort
3. How well it meets the challenge requirements
4. Overall appeal and execution

Respond in JSON format:
{{
    "winner_index": <0-based index of the winning submission>,
    "reasoning": "<brief explanation of why this submission won>"
}}

The submissions are numbered 0 to {len(submission_data) - 1}."""
            
            # Build parts with all submission images
            parts = []
            for i, sub in enumerate(submission_data):
                parts.append(types.Part.from_text(text=f"SUBMISSION #{i}:"))
                parts.append(types.Part.from_bytes(mime_type="image/jpeg", data=sub["image_bytes"]))
            
            parts.append(types.Part.from_text(text=judging_prompt))
            
            # Initialize Gemini client
            client = genai.Client(api_key=self.gemini_api_key)
            
            contents = [
                types.Content(
                    role="user",
                    parts=parts
                )
            ]
            
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.5
                )
            )
            
            response_text = response.text.strip()
            
            # Parse the response
            try:
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                
                result = json.loads(response_text)
                winner_index = result.get("winner_index", 0)
                
                if 0 <= winner_index < len(submission_data):
                    winner = submission_data[winner_index]
                    return {
                        "user_id": winner["user_id"],
                        "image_url": winner["image_url"],
                        "reasoning": result.get("reasoning", "Selected as the best submission!")
                    }
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse winner selection JSON: {response_text[:200]}")
            
            # Fallback: pick first submission
            return {
                "user_id": submission_data[0]["user_id"],
                "image_url": submission_data[0]["image_url"],
                "reasoning": "Selected as winner!"
            }
            
        except Exception as e:
            logger.error(f"Error selecting best submission: {e}")
            # Fallback to first verified submission
            if verified_submissions:
                return {
                    "user_id": verified_submissions[0].get("user_id"),
                    "image_url": verified_submissions[0].get("image_url"),
                    "reasoning": "Selected as winner!"
                }
            return None
    
    def award_winner_bonus(self, user_id: int, bonus_points: int = 100):
        """Award bonus points to the challenge winner's stats"""
        if not self._ensure_connected():
            return
        
        try:
            self.challenge_stats_collection.update_one(
                {"user_id": user_id},
                {"$inc": {"total_points": bonus_points, "challenge_wins": 1}},
                upsert=True
            )
            logger.info(f"Awarded {bonus_points} bonus points to winner {user_id}")
        except Exception as e:
            logger.error(f"Error awarding winner bonus: {e}")
    
    def get_user_submission(self, challenge_id: str, user_id: int) -> Optional[Dict]:
        """Get a user's submission to a specific challenge (most recent)
        
        Returns the submission dict with all verification results
        """
        if not self._ensure_connected():
            return None
        
        try:
            submission = self.submissions_collection.find_one(
                {
                    "challenge_id": challenge_id,
                    "user_id": user_id
                },
                sort=[("submitted_at", DESCENDING)]
            )
            return submission
        except Exception as e:
            logger.error(f"Error getting user submission: {e}")
            return None
    
    # ==================== SUBMISSION MANAGEMENT ====================
    
    async def submit_entry(self, challenge_id: str, user_id: int, 
                           image_url: str, message_id: int) -> Dict:
        """Submit an entry to a challenge
        
        Users can submit multiple times:
        - If they haven't had a verified submission yet, they can earn points
        - Once verified, further submissions don't award points
        - Failed submissions can be retried
        """
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
        
        # Check if user has already had a VERIFIED submission (they already got points)
        existing_verified = self.submissions_collection.find_one({
            "challenge_id": challenge_id,
            "user_id": user_id,
            "verified": True
        })
        
        # Count user's total submissions to this challenge
        submission_count = self.submissions_collection.count_documents({
            "challenge_id": challenge_id,
            "user_id": user_id
        })
        
        # Allow resubmission but track it
        is_resubmission = submission_count > 0
        already_verified = existing_verified is not None
        
        try:
            # Verify the submission with AI
            verification_result = await self.verify_submission(challenge, image_url)
            
            # Check if this is a duplicate/reupload (cheating attempt)
            is_duplicate = verification_result.get("is_duplicate", False)
            
            # Determine if verified (confidence >= 0.6)
            is_verified = verification_result.get("verified", False) and verification_result.get("confidence", 0) >= 0.6
            
            # Points logic:
            # - If duplicate: -20 points penalty
            # - If verified and not already verified: +reward_points
            # - Otherwise: 0 points
            if is_duplicate:
                points_awarded = -20  # Penalty for re-uploading the original image
                logger.warning(f"User {user_id} attempted to submit duplicate image. Applying -20 point penalty.")
            elif is_verified and not already_verified:
                points_awarded = challenge.get("reward_points", 50)
            else:
                points_awarded = 0
            
            submission_data = {
                "challenge_id": challenge_id,
                "user_id": user_id,
                "image_url": image_url,
                "message_id": message_id,
                "submitted_at": datetime.utcnow(),
                "verified": is_verified,
                "verification_result": verification_result,
                "points_awarded": points_awarded,
                "submission_number": submission_count + 1,
                "is_resubmission": is_resubmission,
                "is_duplicate": is_duplicate
            }
            
            # Use upsert to handle resubmissions - replaces existing submission
            self.submissions_collection.update_one(
                {"challenge_id": challenge_id, "user_id": user_id},
                {"$set": submission_data},
                upsert=True
            )
            
            # Update challenge stats
            from bson import ObjectId
            update_fields = {"$inc": {"submissions_count": 1}}
            if is_verified and not already_verified:
                # Only increment verified count if this is their first verified submission
                update_fields["$inc"]["verified_count"] = 1
            
            self.challenges_collection.update_one(
                {"_id": ObjectId(challenge_id)},
                update_fields
            )
            
            # Update user stats (only count points if awarded)
            self._update_user_stats(user_id, is_verified and not already_verified, points_awarded)
            
            return {
                "success": True,
                "verified": is_verified,
                "verification_result": verification_result,
                "points_awarded": points_awarded,
                "is_resubmission": is_resubmission,
                "already_verified": already_verified,
                "submission_number": submission_count + 1,
                "is_duplicate": is_duplicate
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
