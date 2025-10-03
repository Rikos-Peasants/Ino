import os
import asyncio
import logging
import re
import string
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
import aiohttp
import discord
from pymongo import MongoClient, DESCENDING
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

class ModerationManager:
    """Manages AI-powered content moderation using OpenAI's Moderation API"""
    
    def __init__(self, mongo_client: MongoClient, database_name: str = "Riko"):
        # Import here to avoid circular imports
        from config import Config
        
        self.openai_api_key = Config.OPENAI_KEY
        self.google_nl_api_key = Config.GOOGLE_NL_API_KEY
        self.db = mongo_client[database_name]
        
        # Collections for moderation system
        self.moderation_logs_collection = self.db['moderation_logs']
        self.moderation_decisions_collection = self.db['moderation_decisions']
        self.moderation_settings_collection = self.db['moderation_settings']
        
        # Create indexes for better performance
        self._create_indexes()
        
        # API endpoints
        self.openai_moderation_endpoint = "https://api.openai.com/v1/moderations"
        self.google_nl_endpoint = "https://language.googleapis.com/v1/documents:moderateText"
        
        logger.info("Moderation Manager initialized with dual-API support")
    
    def _create_indexes(self):
        """Create database indexes for moderation collections"""
        try:
            # Moderation logs indexes
            self.moderation_logs_collection.create_index([("message_id", 1)], unique=True)
            self.moderation_logs_collection.create_index([("guild_id", 1), ("created_at", -1)])
            self.moderation_logs_collection.create_index([("status", 1)])
            self.moderation_logs_collection.create_index([("flagged", 1)])
            
            # Moderation decisions indexes
            self.moderation_decisions_collection.create_index([("content_hash", 1)], unique=True)
            self.moderation_decisions_collection.create_index([("decision", 1)])
            self.moderation_decisions_collection.create_index([("created_at", -1)])
            
            # Moderation settings indexes
            self.moderation_settings_collection.create_index([("guild_id", 1), ("setting_name", 1)], unique=True)
            
            logger.info("Moderation indexes created successfully")
            
        except Exception as e:
            logger.error(f"Error creating moderation indexes: {e}")
    
    def _normalize_content(self, content: str) -> str:
        """
        Normalize content for better similarity detection
        Handles leet speak, character substitution, spacing tricks, etc.
        """
        # Convert to lowercase
        normalized = content.lower()
        
        # Remove URLs, mentions, and channel references
        normalized = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', normalized)
        normalized = re.sub(r'<@[!&]?[0-9]+>', '', normalized)  # Remove mentions
        normalized = re.sub(r'<#[0-9]+>', '', normalized)  # Remove channel references
        normalized = re.sub(r'<:[a-zA-Z0-9_]+:[0-9]+>', '', normalized)  # Remove custom emojis
        
        # Comprehensive leet speak and character substitution normalization
        # This catches things like "n4gger", "f@ck", "sh1t", etc.
        substitutions = {
            '0': 'o', '1': 'i', '!': 'i', '|': 'i', 
            '3': 'e', '4': 'a', '@': 'a', 
            '5': 's', '$': 's', 
            '7': 't', '+': 't',
            '8': 'b',
            '9': 'g',
            '6': 'g',
            '(': 'c',
            '<': 'c',
            '\/': 'v',
            '|\/|': 'm',
            '><': 'x',
            '/-\\': 'a',
        }
        
        for leet, normal in substitutions.items():
            normalized = normalized.replace(leet, normal)
        
        # Remove all non-alphanumeric except spaces (after substitutions)
        normalized = re.sub(r'[^a-z0-9\s]', '', normalized)
        
        # Remove excessive whitespace (including spaces between letters like "n i g g e r")
        normalized = re.sub(r'\s+', '', normalized)  # Remove ALL spaces for better matching
        
        # Remove repeated characters (aaa -> a, but keep double letters like "ee" in "tree")
        normalized = re.sub(r'(.)\1{2,}', r'\1\1', normalized)  # aaa -> aa
        
        return normalized
    
    def _generate_content_variants(self, content: str) -> Set[str]:
        """
        Generate multiple variants of content for hash checking
        Catches evasion techniques like spacing, vowel removal, repetition, etc.
        """
        variants = set()
        
        # Base normalized version (already handles leet speak and character substitution)
        normalized = self._normalize_content(content)
        variants.add(normalized)
        
        # If already short, don't generate too many variants
        if len(normalized) < 3:
            return variants
        
        # Variant 1: Remove all vowels (common obfuscation like "fck", "sht")
        no_vowels = re.sub(r'[aeiou]', '', normalized)
        if no_vowels and len(no_vowels) >= 2:
            variants.add(no_vowels)
        
        # Variant 2: Keep only first letter of repeated chars (helllo -> helo)
        no_repeats = re.sub(r'(.)\1+', r'\1', normalized)
        if no_repeats != normalized:
            variants.add(no_repeats)
        
        # Variant 3: Phonetic variants (common sound-alike evasions)
        # Example: "ck" -> "k", "ph" -> "f"
        phonetic = normalized
        phonetic = phonetic.replace('ck', 'k')
        phonetic = phonetic.replace('ph', 'f')
        phonetic = phonetic.replace('kk', 'k')
        phonetic = phonetic.replace('gg', 'g')
        if phonetic != normalized:
            variants.add(phonetic)
        
        # Variant 4: First and last chars only (extreme shortening)
        if len(normalized) >= 4:
            extreme_short = normalized[0] + normalized[-1]
            variants.add(extreme_short)
        
        # Variant 5: Consonant skeleton (keep only consonants in order)
        consonants = re.sub(r'[aeiou]', '', normalized)
        if consonants and len(consonants) >= 2:
            variants.add(consonants)
        
        return variants
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts using SequenceMatcher"""
        return SequenceMatcher(None, text1, text2).ratio()
    
    def _contains_slurs_or_extreme_harm(self, content: str) -> Tuple[bool, str]:
        """
        Check for known slurs and extreme harmful content with evasion detection
        Uses multiple checks to avoid false positives (e.g., "night" shouldn't match)
        Returns: (is_harmful, reason)
        """
        # First, create a version WITH spaces preserved for word boundary checking
        content_lower = content.lower()
        
        # Apply leet speak normalization but KEEP spaces for word boundary detection
        substitutions = {
            '0': 'o', '1': 'i', '!': 'i', '|': 'i', 
            '3': 'e', '4': 'a', '@': 'a', 
            '5': 's', '$': 's', 
            '7': 't', '+': 't',
            '8': 'b', '9': 'g', '6': 'g',
        }
        spaced_normalized = content_lower
        for leet, normal in substitutions.items():
            spaced_normalized = spaced_normalized.replace(leet, normal)
        
        # Remove special chars but KEEP spaces
        spaced_normalized = re.sub(r'[^a-z0-9\s]', '', spaced_normalized)
        spaced_normalized = re.sub(r'\s+', ' ', spaced_normalized).strip()
        
        # Patterns that need WHOLE WORD matching (to avoid false positives)
        exact_word_patterns = {
            # Racial slurs - must be standalone words
            r'\bnigger\b': 'racial slur',
            r'\bnigga\b': 'racial slur',
            r'\bfaggot\b': 'homophobic slur',
            r'\bfag\b': 'homophobic slur',  # Only as whole word (not "flagrant")
            r'\btranny\b': 'transphobic slur',
            r'\bretard\b': 'ableist slur',
            r'\bretarded\b': 'ableist slur',
        }
        
        # Check exact word patterns on spaced version
        for pattern, reason in exact_word_patterns.items():
            if re.search(pattern, spaced_normalized):
                logger.warning(f"Detected harmful content via word boundary matching: '{pattern}' -> {reason}")
                return True, reason
        
        # Now check with ALL spaces removed for evasion like "n i g g e r"
        no_space_normalized = spaced_normalized.replace(' ', '')
        
        # Patterns to check on space-removed version (catches "k y s" -> "kys")
        no_space_patterns = {
            'killyourself': 'suicide encouragement',
            'kys': 'suicide encouragement',
            'neckyourself': 'suicide encouragement',
            'ropeyourself': 'suicide encouragement',
            'illkillyou': 'violent threat',
            'imgonnakillyou': 'violent threat',
            'illmurderyou': 'violent threat',
        }
        
        # Check on space-removed version
        for pattern, reason in no_space_patterns.items():
            if pattern in no_space_normalized:
                logger.warning(f"Detected harmful content via phrase matching: '{pattern}' -> {reason}")
                return True, reason
        
        # Special check: If a slur appears with spaces between EVERY letter (evasion)
        # e.g., "n i g g e r" becomes "nigger" after removing spaces
        for slur_pattern, reason in exact_word_patterns.items():
            # Remove the \b markers for this check
            slur_word = slur_pattern.replace(r'\b', '')
            # Check if the slur is the entire word or surrounded by spaces
            if no_space_normalized == slur_word or f' {slur_word} ' in f' {no_space_normalized} ':
                logger.warning(f"Detected harmful content via space evasion: '{slur_word}' -> {reason}")
                return True, reason
        
        return False, ""
    
    async def _check_similar_decisions(self, content: str, similarity_threshold: float = 0.85) -> Optional[Dict]:
        """Check for existing decisions on similar content"""
        try:
            # Generate variants of the current content
            content_variants = self._generate_content_variants(content)
            
            # First, check for exact hash matches on any variant
            for variant in content_variants:
                variant_hash = hash(variant)
                existing_decision = await self.get_moderation_decision(variant_hash)
                if existing_decision:
                    logger.info(f"Found exact hash match for content variant: '{variant}'")
                    return existing_decision
            
            # If no exact matches, check for fuzzy similarity on recent decisions
            # Get recent decisions for fuzzy matching (last 1000 to avoid performance issues)
            recent_decisions = list(self.moderation_decisions_collection.find({}).sort("created_at", -1).limit(1000))
            
            normalized_content = self._normalize_content(content)
            
            for decision in recent_decisions:
                # We need to reconstruct the content from logs to compare
                # For now, we'll store original_content in decisions to enable this
                decision_content = decision.get('original_content', '')
                if decision_content:
                    decision_normalized = self._normalize_content(decision_content)
                    
                    # Check similarity
                    similarity = self._calculate_similarity(normalized_content, decision_normalized)
                    if similarity >= similarity_threshold:
                        logger.info(f"Found similar content (similarity: {similarity:.2f}): '{decision_content}' matches '{content}'")
                        return decision
            
            return None
            
        except Exception as e:
            logger.error(f"Error checking similar decisions: {e}")
            return None
    
    def _is_serious_harm(self, openai_categories: Dict, openai_scores: Dict, google_categories: Dict = None) -> Tuple[bool, float]:
        """
        Determine if content is seriously harmful vs just light profanity
        
        Serious harm includes:
        - Hate speech / slurs
        - Self-harm / suicide encouragement
        - Violence / threats
        - Sexual harassment
        - Targeted harassment
        
        Light profanity (allowed):
        - General swearing (fuck, shit, damn, etc.)
        - Mild toxicity without targeting
        
        Returns:
            Tuple[is_serious, adjusted_confidence]
        """
        # Categories that indicate SERIOUS harm (should be moderated)
        serious_categories_openai = {
            'hate',
            'hate/threatening', 
            'self-harm',
            'self-harm/intent',
            'self-harm/instructions',
            'violence',
            'violence/graphic',
            'harassment/threatening',
            'sexual/minors'
        }
        
        # Light categories that are okay if alone
        light_categories_openai = {
            'sexual',  # Generic "sexual" without minors/harassment is often just swearing
            'harassment',  # Generic harassment without threats
        }
        
        # Check OpenAI categories for serious harm
        flagged_serious = []
        flagged_light = []
        
        for category, is_flagged in openai_categories.items():
            if is_flagged:
                score = openai_scores.get(category, 0.0)
                
                if category in serious_categories_openai:
                    flagged_serious.append((category, score))
                elif category in light_categories_openai:
                    flagged_light.append((category, score))
        
        # If Google NL provided results, check those too
        if google_categories:
            serious_categories_google = {
                'Violent',
                'Death, Harm & Tragedy',
                'Firearms & Weapons',
                'Illicit Drugs'
            }
            
            for category, confidence in google_categories.items():
                if confidence > 0.6 and category in serious_categories_google:
                    flagged_serious.append((f"Google:{category}", confidence))
        
        # If ANY serious category is flagged, it's serious harm
        if flagged_serious:
            max_serious = max(score for _, score in flagged_serious)
            logger.info(f"Serious harm detected: {flagged_serious}")
            return True, max_serious
        
        # If ONLY light categories are flagged, it's probably just swearing
        if flagged_light and not flagged_serious:
            max_light = max(score for _, score in flagged_light)
            # Reduce confidence for light profanity
            adjusted = max_light * 0.3  # Reduce by 70%
            logger.info(f"Only light profanity detected: {flagged_light}. Confidence reduced from {max_light:.1%} to {adjusted:.1%}")
            return False, adjusted
        
        # No serious harm detected
        return False, 0.0
    
    async def _check_with_google_nl(self, content: str) -> Optional[Dict]:
        """
        Secondary moderation check using Google Natural Language API
        Returns moderation categories and confidence scores
        """
        if not self.google_nl_api_key:
            logger.warning("Google Natural Language API key not configured")
            return None
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.google_nl_endpoint}?key={self.google_nl_api_key}"
                
                data = {
                    "document": {
                        "type": "PLAIN_TEXT",
                        "content": content
                    }
                }
                
                async with session.post(url, json=data) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Google NL API error: {response.status} - {error_text}")
                        return None
                    
                    result = await response.json()
                    
                    if not result.get('moderationCategories'):
                        return None
                    
                    # Extract categories with confidence >= 0.5 (moderate to high)
                    flagged_categories = {}
                    max_confidence = 0.0
                    
                    for category in result['moderationCategories']:
                        confidence = category.get('confidence', 0.0)
                        name = category.get('name', 'Unknown')
                        
                        flagged_categories[name] = confidence
                        max_confidence = max(max_confidence, confidence)
                    
                    logger.info(f"Google NL moderation check: max_confidence={max_confidence:.2%}, categories={len(flagged_categories)}")
                    
                    return {
                        'flagged_categories': flagged_categories,
                        'max_confidence': max_confidence,
                        'raw_result': result
                    }
                    
        except Exception as e:
            logger.error(f"Error calling Google Natural Language API: {e}")
            return None
    
    async def scan_message(self, message: discord.Message) -> Optional[Dict]:
        """
        Scan a message using OpenAI's Moderation API
        
        Returns:
            Dict containing moderation results or None if not flagged
        """
        if not self.openai_api_key:
            logger.warning("OpenAI API key not configured, skipping moderation")
            return None
        
        try:
            # Skip if message is empty or only contains mentions/emojis
            clean_content = message.clean_content.strip()
            if not clean_content or len(clean_content) < 3:
                return None
            
            # FIRST: Check for known slurs and extreme harm with evasion detection
            # This catches things AI might miss like "n4gger", "k y s", etc.
            contains_slur, slur_reason = self._contains_slurs_or_extreme_harm(clean_content)
            if contains_slur:
                logger.warning(f"Known harmful content detected via pattern matching: {slur_reason}")
                
                # Generate hash for tracking
                content_variants = self._generate_content_variants(clean_content)
                primary_variant = self._normalize_content(clean_content)
                content_hash = hash(primary_variant)
                
                # Create moderation data with maximum severity
                moderation_data = {
                    "message_id": str(message.id),
                    "guild_id": str(message.guild.id) if message.guild else None,
                    "channel_id": str(message.channel.id),
                    "author_id": str(message.author.id),
                    "author_name": message.author.display_name,
                    "content": clean_content,
                    "content_hash": content_hash,
                    "flagged": True,
                    "max_confidence": 1.0,  # Maximum confidence for known patterns
                    "severity": "high",
                    "should_delete": True,
                    "categories": {"pattern_match": True},
                    "category_scores": {"pattern_match": 1.0},
                    "detection_method": "pattern_matching",
                    "pattern_reason": slur_reason,
                    "google_nl_confidence": None,
                    "google_nl_categories": None,
                    "moderation_source": "pattern_match",
                    "status": "pending_review",
                    "existing_decision": None,
                    "created_at": datetime.utcnow(),
                    "jump_url": message.jump_url
                }
                
                # Store in database
                await self.store_moderation_log(moderation_data)
                
                logger.info(f"Pattern-matched harmful content flagged for deletion: {slur_reason}")
                return moderation_data
            
            # Call OpenAI Moderation API
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "input": clean_content
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.openai_moderation_endpoint, headers=headers, json=data) as response:
                    if response.status != 200:
                        logger.error(f"OpenAI Moderation API error: {response.status}")
                        return None
                    
                    result = await response.json()
                    
                    if not result.get('results'):
                        return None
                    
                    moderation_result = result['results'][0]
                    
                    # Get the maximum confidence score from all categories
                    category_scores = moderation_result.get('category_scores', {})
                    max_confidence = max(category_scores.values()) if category_scores else 0.0
                    
                    # Apply confidence-based thresholds:
                    # < 50%: Do nothing
                    # 50-75%: Flag but don't delete
                    # >= 75%: Flag and mark for deletion
                    
                    if max_confidence < 0.50:
                        # Below 50% confidence - ignore
                        return None
                    
                    # Secondary check with Google Natural Language API for all flagged content (50-100%)
                    google_result = None
                    google_max_confidence = 0.0
                    
                    logger.info(f"OpenAI flagged content at {max_confidence:.1%} confidence. Running secondary check with Google NL...")
                    google_result = await self._check_with_google_nl(clean_content)
                    
                    if google_result:
                        google_max_confidence = google_result['max_confidence']
                        logger.info(f"Google NL secondary check: {google_max_confidence:.1%} confidence")
                        
                        # Use the HIGHER confidence from both APIs
                        combined_confidence = max(max_confidence, google_max_confidence)
                        logger.info(f"Combined confidence: OpenAI={max_confidence:.1%}, Google={google_max_confidence:.1%}, Final={combined_confidence:.1%}")
                        max_confidence = combined_confidence
                    
                    # Check if this is serious harm vs light profanity
                    google_categories = google_result['flagged_categories'] if google_result else None
                    is_serious, adjusted_confidence = self._is_serious_harm(
                        moderation_result.get('categories', {}),
                        category_scores,
                        google_categories
                    )
                    
                    # If it's ONLY light profanity, allow it (reduce confidence)
                    if not is_serious and adjusted_confidence < 0.50:
                        logger.info(f"Light profanity detected and allowed. Confidence adjusted to {adjusted_confidence:.1%}")
                        return None  # Don't flag light profanity
                    
                    # If serious harm was detected, use that confidence
                    if is_serious:
                        max_confidence = adjusted_confidence
                        logger.info(f"Serious harm confirmed. Using adjusted confidence: {max_confidence:.1%}")
                    
                    # Determine severity based on final confidence
                    if max_confidence >= 0.75:
                        severity = "high"  # Should be deleted
                        should_delete = True
                    else:  # 0.50 <= max_confidence < 0.75
                        severity = "medium"  # Flag for review only
                        should_delete = False
                    
                    # Use enhanced similarity detection to check for existing decisions
                    existing_decision = await self._check_similar_decisions(clean_content)
                    
                    # Generate primary content hash from the best normalized variant
                    content_variants = self._generate_content_variants(clean_content)
                    primary_variant = self._normalize_content(clean_content)
                    content_hash = hash(primary_variant)
                    
                    moderation_data = {
                        "message_id": str(message.id),
                        "guild_id": str(message.guild.id) if message.guild else None,
                        "channel_id": str(message.channel.id),
                        "author_id": str(message.author.id),
                        "author_name": message.author.display_name,
                        "content": clean_content,
                        "content_hash": content_hash,
                        "flagged": True,
                        "max_confidence": max_confidence,
                        "severity": severity,
                        "should_delete": should_delete,
                        "categories": moderation_result.get('categories', {}),
                        "category_scores": category_scores,
                        "google_nl_confidence": google_max_confidence if google_result else None,
                        "google_nl_categories": google_result['flagged_categories'] if google_result else None,
                        "moderation_source": "dual" if google_result else "openai_only",
                        "status": "auto_approved" if existing_decision and existing_decision['decision'] == "whitelist" else "pending_review",
                        "existing_decision": existing_decision['decision'] if existing_decision else None,
                        "created_at": datetime.utcnow(),
                        "jump_url": message.jump_url
                    }
                    
                    # Store in database
                    await self.store_moderation_log(moderation_data)
                    
                    # If we have an existing whitelist decision, auto-approve
                    if existing_decision and existing_decision['decision'] == "whitelist":
                        logger.info(f"Auto-approved flagged message from {message.author.display_name} (whitelisted content, confidence: {max_confidence:.1%})")
                        return None
                    
                    # If we have an existing blacklist decision, take action
                    if existing_decision and existing_decision['decision'] == "blacklist":
                        moderation_data['status'] = "blacklisted"
                        moderation_data['should_delete'] = True  # Always delete blacklisted content
                        await self.update_moderation_log(str(message.id), {"status": "blacklisted"})
                        logger.info(f"Blacklisted content detected from {message.author.display_name}")
                        return moderation_data
                    
                    logger.info(f"Message flagged for review from {message.author.display_name} in #{message.channel.name} (confidence: {max_confidence:.1%}, severity: {severity})")
                    return moderation_data
                    
                    return None
                    
        except Exception as e:
            logger.error(f"Error scanning message for moderation: {e}")
            return None
    
    async def store_moderation_log(self, moderation_data: Dict) -> bool:
        """Store moderation log in database"""
        try:
            self.moderation_logs_collection.replace_one(
                {"message_id": moderation_data["message_id"]},
                moderation_data,
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error storing moderation log: {e}")
            return False
    
    async def update_moderation_log(self, message_id: str, update_data: Dict) -> bool:
        """Update moderation log"""
        try:
            result = self.moderation_logs_collection.update_one(
                {"message_id": message_id},
                {"$set": {**update_data, "updated_at": datetime.utcnow()}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating moderation log: {e}")
            return False
    
    async def get_moderation_log(self, message_id: str) -> Optional[Dict]:
        """Get moderation log by message ID"""
        try:
            return self.moderation_logs_collection.find_one({"message_id": message_id})
        except Exception as e:
            logger.error(f"Error getting moderation log: {e}")
            return None
    
    async def get_pending_moderation_logs(self, guild_id: str, limit: int = 10) -> List[Dict]:
        """Get pending moderation logs for review"""
        try:
            cursor = self.moderation_logs_collection.find({
                "guild_id": guild_id,
                "status": "pending_review"
            }).sort("created_at", DESCENDING).limit(limit)
            
            return list(cursor)
        except Exception as e:
            logger.error(f"Error getting pending moderation logs: {e}")
            return []
    
    async def store_moderation_decision(self, content_hash: int, decision: str, moderator_id: str, moderator_name: str, reason: str = None, original_content: str = None) -> bool:
        """Store moderation decision (whitelist/blacklist) with enhanced similarity support"""
        try:
            # Generate multiple hash variants if original content is provided
            hash_variants = [content_hash]  # Always include the primary hash
            
            if original_content:
                content_variants = self._generate_content_variants(original_content)
                for variant in content_variants:
                    variant_hash = hash(variant)
                    if variant_hash != content_hash:  # Avoid duplicates
                        hash_variants.append(variant_hash)
            
            decision_data = {
                "content_hash": content_hash,
                "hash_variants": hash_variants,  # Store all hash variants
                "original_content": original_content or "",  # Store for fuzzy matching
                "decision": decision,  # "whitelist" or "blacklist"
                "moderator_id": moderator_id,
                "moderator_name": moderator_name,
                "reason": reason or "No reason provided",
                "created_at": datetime.utcnow()
            }
            
            # Store the primary decision
            self.moderation_decisions_collection.replace_one(
                {"content_hash": content_hash},
                decision_data,
                upsert=True
            )
            
            # Store decisions for all hash variants to enable fast lookups
            for variant_hash in hash_variants:
                if variant_hash != content_hash:  # Primary already stored above
                    variant_decision_data = decision_data.copy()
                    variant_decision_data["content_hash"] = variant_hash
                    variant_decision_data["is_variant"] = True  # Mark as variant
                    variant_decision_data["primary_hash"] = content_hash  # Reference to primary
                    
                    self.moderation_decisions_collection.replace_one(
                        {"content_hash": variant_hash},
                        variant_decision_data,
                        upsert=True
                    )
            
            logger.info(f"Stored moderation decision for {len(hash_variants)} content variants")
            return True
            
        except Exception as e:
            logger.error(f"Error storing moderation decision: {e}")
            return False
    
    async def get_moderation_decision(self, content_hash: int) -> Optional[Dict]:
        """Get existing moderation decision for content"""
        try:
            return self.moderation_decisions_collection.find_one({"content_hash": content_hash})
        except Exception as e:
            logger.error(f"Error getting moderation decision: {e}")
            return None
    
    async def approve_message(self, message_id: str, moderator_id: str, moderator_name: str, whitelist: bool = False) -> bool:
        """Approve a flagged message"""
        try:
            log_data = await self.get_moderation_log(message_id)
            if not log_data:
                return False
            
            update_data = {
                "status": "approved",
                "moderator_id": moderator_id,
                "moderator_name": moderator_name,
                "reviewed_at": datetime.utcnow()
            }
            
            # If whitelisting, store decision for future
            if whitelist:
                await self.store_moderation_decision(
                    log_data['content_hash'],
                    "whitelist",
                    moderator_id,
                    moderator_name,
                    "Whitelisted by community/staff vote",
                    log_data.get('content', '')
                )
                update_data["whitelisted"] = True
            
            return await self.update_moderation_log(message_id, update_data)
            
        except Exception as e:
            logger.error(f"Error approving message: {e}")
            return False
    
    async def reject_message(self, message_id: str, moderator_id: str, moderator_name: str, blacklist: bool = False, reason: str = None) -> bool:
        """Reject a flagged message"""
        try:
            log_data = await self.get_moderation_log(message_id)
            if not log_data:
                return False
            
            update_data = {
                "status": "rejected",
                "moderator_id": moderator_id,
                "moderator_name": moderator_name,
                "reviewed_at": datetime.utcnow(),
                "rejection_reason": reason or "Inappropriate content"
            }
            
            # If blacklisting, store decision for future
            if blacklist:
                await self.store_moderation_decision(
                    log_data['content_hash'],
                    "blacklist",
                    moderator_id,
                    moderator_name,
                    reason or "Blacklisted by community/staff vote",
                    log_data.get('content', '')
                )
                update_data["blacklisted"] = True
            
            return await self.update_moderation_log(message_id, update_data)
            
        except Exception as e:
            logger.error(f"Error rejecting message: {e}")
            return False
    
    async def overrule_decision(self, message_id: str, is_allowed: bool, admin_id: str, admin_name: str, reason: str = None) -> bool:
        """Admin overrule of moderation decision"""
        try:
            log_data = await self.get_moderation_log(message_id)
            if not log_data:
                return False
            
            update_data = {
                "status": "overruled_approved" if is_allowed else "overruled_rejected",
                "overrule_admin_id": admin_id,
                "overrule_admin_name": admin_name,
                "overrule_reason": reason or "Admin overrule",
                "overruled_at": datetime.utcnow()
            }
            
            # Update the decision in the decisions collection
            await self.store_moderation_decision(
                log_data['content_hash'],
                "whitelist" if is_allowed else "blacklist",
                admin_id,
                admin_name,
                f"Admin overrule: {reason or 'No reason provided'}",
                log_data.get('content', '')
            )
            
            return await self.update_moderation_log(message_id, update_data)
            
        except Exception as e:
            logger.error(f"Error overruling decision: {e}")
            return False
    
    # Settings Management
    async def set_moderation_setting(self, guild_id: str, setting_name: str, setting_value) -> bool:
        """Set a moderation setting for a guild"""
        try:
            self.moderation_settings_collection.replace_one(
                {"guild_id": guild_id, "setting_name": setting_name},
                {
                    "guild_id": guild_id,
                    "setting_name": setting_name,
                    "setting_value": setting_value,
                    "updated_at": datetime.utcnow()
                },
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error setting moderation setting: {e}")
            return False
    
    async def get_moderation_setting(self, guild_id: str, setting_name: str, default_value=None):
        """Get a moderation setting for a guild"""
        try:
            result = self.moderation_settings_collection.find_one({
                "guild_id": guild_id,
                "setting_name": setting_name
            })
            return result["setting_value"] if result else default_value
        except Exception as e:
            logger.error(f"Error getting moderation setting: {e}")
            return default_value
    
    async def is_moderation_enabled(self, guild_id: str) -> bool:
        """Check if moderation is enabled for a guild"""
        return await self.get_moderation_setting(guild_id, "moderation_enabled", False)
    
    async def get_review_role_id(self, guild_id: str) -> Optional[int]:
        """Get the role ID that can review moderation"""
        role_id = await self.get_moderation_setting(guild_id, "review_role_id")
        return int(role_id) if role_id else None
    
    async def get_admin_role_id(self, guild_id: str) -> Optional[int]:
        """Get the role ID that can overrule decisions"""
        role_id = await self.get_moderation_setting(guild_id, "admin_role_id")
        return int(role_id) if role_id else None
    
    async def get_moderation_log_channel_id(self, guild_id: str) -> Optional[int]:
        """Get the channel ID for moderation logs"""
        channel_id = await self.get_moderation_setting(guild_id, "moderation_log_channel_id")
        return int(channel_id) if channel_id else None
    
    async def get_moderation_stats(self, guild_id: str, days: int = 30) -> Dict:
        """Get moderation statistics for a guild"""
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            pipeline = [
                {"$match": {
                    "guild_id": guild_id,
                    "created_at": {"$gte": start_date}
                }},
                {"$group": {
                    "_id": "$status",
                    "count": {"$sum": 1}
                }}
            ]
            
            results = list(self.moderation_logs_collection.aggregate(pipeline))
            stats = {item["_id"]: item["count"] for item in results}
            
            # Get total flagged messages
            total_flagged = self.moderation_logs_collection.count_documents({
                "guild_id": guild_id,
                "flagged": True,
                "created_at": {"$gte": start_date}
            })
            
            # Get blacklisted content hits
            blacklisted_hits = self.moderation_logs_collection.count_documents({
                "guild_id": guild_id,
                "status": "blacklisted",
                "created_at": {"$gte": start_date}
            })
            
            return {
                "total_flagged": total_flagged,
                "pending_review": stats.get("pending_review", 0),
                "approved": stats.get("approved", 0),
                "rejected": stats.get("rejected", 0),
                "blacklisted_hits": blacklisted_hits,
                "auto_approved": stats.get("auto_approved", 0),
                "overruled": stats.get("overruled_approved", 0) + stats.get("overruled_rejected", 0)
            }
            
        except Exception as e:
            logger.error(f"Error getting moderation stats: {e}")
            return {}

    def close(self):
        """Close MongoDB connection"""
        # Connection is managed by the parent mongo client
        pass