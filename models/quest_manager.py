import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
import logging
from pymongo import MongoClient, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from pymongo.collection import Collection
from pymongo.database import Database
import random
import discord

logger = logging.getLogger(__name__)

class QuestManager:
    """Manages daily quests, achievements, events, and streaks system"""
    
    def __init__(self, connection_url: Optional[str] = None, database_name: str = "Riko"):
        # Import here to avoid circular imports
        from config import Config
        
        self.connection_url = connection_url or Config.MONGO_URI
        self.database_name = database_name
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None
        self.quests_collection: Optional[Collection] = None
        self.achievements_collection: Optional[Collection] = None
        self.events_collection: Optional[Collection] = None
        self.user_quests_collection: Optional[Collection] = None
        self.user_achievements_collection: Optional[Collection] = None
        self.user_stats_collection: Optional[Collection] = None
        self.user_streaks_collection: Optional[Collection] = None
        self._connect()
        self._initialize_quests_and_achievements()
    
    def _connect(self):
        """Connect to MongoDB"""
        try:
            self.client = MongoClient(self.connection_url, serverSelectionTimeoutMS=5000)
            # Test the connection
            self.client.admin.command('ismaster')
            self.db = self.client[self.database_name]
            
            # Initialize collections
            self.quests_collection = self.db['quests']
            self.achievements_collection = self.db['achievements']
            self.events_collection = self.db['events']
            self.user_quests_collection = self.db['user_quests']
            self.user_achievements_collection = self.db['user_achievements']
            self.user_stats_collection = self.db['user_quest_stats']
            self.user_streaks_collection = self.db['user_streaks']
            
            # Create indexes
            self.quests_collection.create_index([("quest_type", 1), ("is_daily", 1)])
            self.achievements_collection.create_index([("achievement_type", 1)])
            self.events_collection.create_index([("start_date", -1), ("end_date", -1)])
            self.user_quests_collection.create_index([("user_id", 1), ("date", -1)])
            self.user_achievements_collection.create_index([("user_id", 1), ("achievement_id", 1)], unique=True)
            self.user_stats_collection.create_index([("user_id", 1)], unique=True)
            self.user_streaks_collection.create_index([("user_id", 1)], unique=True)
            
            logger.info(f"Connected to MongoDB for Quest Manager")
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise Exception(f"MongoDB connection failed: {e}")
    
    def _ensure_connected(self) -> bool:
        """Ensure database connection is available"""
        return (self.db is not None and 
                self.quests_collection is not None and 
                self.achievements_collection is not None and 
                self.events_collection is not None and 
                self.user_quests_collection is not None and 
                self.user_achievements_collection is not None and 
                self.user_stats_collection is not None and 
                self.user_streaks_collection is not None)
    
    def _initialize_quests_and_achievements(self):
        """Initialize default quests and achievements if they don't exist"""
        if not self._ensure_connected():
            logger.error("Cannot initialize quests and achievements: Database not connected")
            return
        # Daily Quests with difficulty levels and categories
        daily_quests = [
            # ========== POSTING QUESTS ==========
            {
                "quest_id": "daily_post_1",
                "name": "First Steps",
                "description": "Post 1 image",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "easy",
                "target_count": 1,
                "reward_points": 10,
                "rarity_chance": 1.0,  # 100% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_post_3",
                "name": "Active Poster",
                "description": "Post 3 images",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "medium",
                "target_count": 3,
                "reward_points": 30,
                "rarity_chance": 0.8,  # 80% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_post_5",
                "name": "Content Creator",
                "description": "Post 5 images",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "hard",
                "target_count": 5,
                "reward_points": 50,
                "rarity_chance": 0.5,  # 50% chance
                "is_daily": True
            },
            
            # ========== ENGAGEMENT QUESTS ==========
            {
                "quest_id": "daily_like_5",
                "name": "Rising Star",
                "description": "Earn 5 likes on your images",
                "quest_type": "earn_likes",
                "category": "engagement",
                "difficulty": "easy",
                "target_count": 5,
                "reward_points": 15,
                "rarity_chance": 0.9,  # 90% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_like_10",
                "name": "Popular Creator",
                "description": "Earn 10 likes on your images",
                "quest_type": "earn_likes",
                "category": "engagement",
                "difficulty": "medium",
                "target_count": 10,
                "reward_points": 35,
                "rarity_chance": 0.7,  # 70% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_like_20",
                "name": "Community Favorite",
                "description": "Earn 20 likes on your images",
                "quest_type": "earn_likes",
                "category": "engagement",
                "difficulty": "hard",
                "target_count": 20,
                "reward_points": 60,
                "rarity_chance": 0.4,  # 40% chance
                "is_daily": True
            },
            
            # ========== RATING QUESTS ==========
            {
                "quest_id": "daily_rate_5",
                "name": "Art Appreciator",
                "description": "Rate 5 images (👍 or 👎)",
                "quest_type": "rate_images",
                "category": "rating",
                "difficulty": "easy",
                "target_count": 5,
                "reward_points": 12,
                "rarity_chance": 1.0,  # 100% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_rate_10",
                "name": "Active Critic",
                "description": "Rate 10 images (👍 or 👎)",
                "quest_type": "rate_images",
                "category": "rating",
                "difficulty": "medium",
                "target_count": 10,
                "reward_points": 25,
                "rarity_chance": 0.8,  # 80% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_rate_20",
                "name": "Master Curator",
                "description": "Rate 20 images (👍 or 👎)",
                "quest_type": "rate_images",
                "category": "rating",
                "difficulty": "hard",
                "target_count": 20,
                "reward_points": 45,
                "rarity_chance": 0.6,  # 60% chance
                "is_daily": True
            },
            
            # ========== COMBO QUESTS ==========
            {
                "quest_id": "daily_combo_post_rate",
                "name": "Content & Critic",
                "description": "Post 2 images AND rate 10 images",
                "quest_type": "combo",
                "category": "combo",
                "difficulty": "medium",
                "target_count": 1,  # Special handling needed
                "reward_points": 40,
                "rarity_chance": 0.6,  # 60% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_hot_streak",
                "name": "Hot Streak",
                "description": "Post 3 images that each get at least 3 likes",
                "quest_type": "hot_images",
                "category": "special",
                "difficulty": "hard",
                "target_count": 3,
                "reward_points": 70,
                "rarity_chance": 0.3,  # 30% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_support_others",
                "name": "Community Support",
                "description": "Give likes to 15 different images",
                "quest_type": "like_diverse",
                "category": "community",
                "difficulty": "medium",
                "target_count": 15,
                "reward_points": 35,
                "rarity_chance": 0.7,  # 70% chance
                "is_daily": True
            },
            # Creative/Fun Quests
            {
                "quest_id": "daily_early_bird",
                "name": "Early Bird",
                "description": "Post an image before 10 AM (server time)",
                "quest_type": "early_post",
                "category": "time_based",
                "difficulty": "medium",
                "target_count": 1,
                "reward_points": 30,
                "rarity_chance": 0.5,  # 50% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_night_owl",
                "name": "Night Owl",
                "description": "Post an image after 10 PM (server time)",
                "quest_type": "late_post",
                "category": "time_based",
                "difficulty": "medium",
                "target_count": 1,
                "reward_points": 30,
                "rarity_chance": 0.5,  # 50% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_triple_threat",
                "name": "Triple Threat",
                "description": "Post 3 images in different channels",
                "quest_type": "diverse_posts",
                "category": "special",
                "difficulty": "hard",
                "target_count": 3,
                "reward_points": 55,
                "rarity_chance": 0.4,  # 40% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_generous_rater",
                "name": "Generous Rater",
                "description": "Give out 20 thumbs up today",
                "quest_type": "give_likes",
                "category": "community",
                "difficulty": "medium",
                "target_count": 20,
                "reward_points": 30,
                "rarity_chance": 0.7,  # 70% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_critic",
                "name": "Honest Critic",
                "description": "Rate 30 images (any combination of 👍👎)",
                "quest_type": "rate_images",
                "category": "rating",
                "difficulty": "hard",
                "target_count": 30,
                "reward_points": 50,
                "rarity_chance": 0.5,  # 50% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_social_butterfly",
                "name": "Social Butterfly",
                "description": "React to images from 10 different users",
                "quest_type": "diverse_reactions",
                "category": "community",
                "difficulty": "medium",
                "target_count": 10,
                "reward_points": 40,
                "rarity_chance": 0.6,  # 60% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_marathon",
                "name": "Image Marathon",
                "description": "Post 7 images in a single day",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "very_hard",
                "target_count": 7,
                "reward_points": 80,
                "rarity_chance": 0.3,  # 30% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_quality_over_quantity",
                "name": "Quality Over Quantity",
                "description": "Post 1 image that gets at least 6 likes",
                "quest_type": "quality_post",
                "category": "special",
                "difficulty": "hard",
                "target_count": 1,
                "reward_points": 50,
                "rarity_chance": 0.45,  # 45% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_curator",
                "name": "Image Curator",
                "description": "Rate 50 images (curator level)",
                "quest_type": "rate_images",
                "category": "rating",
                "difficulty": "very_hard",
                "target_count": 50,
                "reward_points": 75,
                "rarity_chance": 0.25,  # 25% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_balanced",
                "name": "Balanced Creator",
                "description": "Post 2 images AND rate 15 images",
                "quest_type": "combo",
                "category": "combo",
                "difficulty": "medium",
                "target_count": 1,
                "reward_points": 45,
                "rarity_chance": 0.65,  # 65% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_popularity_contest",
                "name": "Popularity Contest",
                "description": "Get a total of 12 likes across all your images today",
                "quest_type": "earn_likes",
                "category": "engagement",
                "difficulty": "very_hard",
                "target_count": 12,
                "reward_points": 70,
                "rarity_chance": 0.3,  # 30% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_explorer",
                "name": "Channel Explorer",
                "description": "React to images in both image channels",
                "quest_type": "explore_channels",
                "category": "community",
                "difficulty": "easy",
                "target_count": 2,
                "reward_points": 20,
                "rarity_chance": 0.8,  # 80% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_consistency",
                "name": "Consistency is Key",
                "description": "Post at least 1 image (streaks matter!)",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "easy",
                "target_count": 1,
                "reward_points": 15,
                "rarity_chance": 0.95,  # 95% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_engagement_king",
                "name": "Engagement King/Queen",
                "description": "Get 10 likes on a single image",
                "quest_type": "viral_image",
                "category": "special",
                "difficulty": "very_hard",
                "target_count": 1,
                "reward_points": 85,
                "rarity_chance": 0.25,  # 25% chance
                "is_daily": True
            },
            {
                "quest_id": "daily_supportive",
                "name": "Supportive Community Member",
                "description": "Like images from 5 different new users today",
                "quest_type": "support_new_users",
                "category": "community",
                "difficulty": "medium",
                "target_count": 5,
                "reward_points": 35,
                "rarity_chance": 0.6,  # 60% chance
                "is_daily": True
            },
            
            # ========== NEW QUESTS - SMALL COMMUNITY FRIENDLY ==========
            # Easy Posting Quests
            {
                "quest_id": "daily_morning_glory",
                "name": "Morning Glory",
                "description": "Post your first image before noon",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "easy",
                "target_count": 1,
                "reward_points": 10,
                "rarity_chance": 0.9,
                "is_daily": True
            },
            {
                "quest_id": "daily_afternoon_delight",
                "name": "Afternoon Delight",
                "description": "Post 2 images between 12 PM and 6 PM",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "easy",
                "target_count": 2,
                "reward_points": 18,
                "rarity_chance": 0.85,
                "is_daily": True
            },
            {
                "quest_id": "daily_steady_pace",
                "name": "Steady Pace",
                "description": "Post 4 images throughout the day",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "medium",
                "target_count": 4,
                "reward_points": 35,
                "rarity_chance": 0.7,
                "is_daily": True
            },
            {
                "quest_id": "daily_prolific",
                "name": "Prolific Creator",
                "description": "Post 6 images today",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "hard",
                "target_count": 6,
                "reward_points": 55,
                "rarity_chance": 0.5,
                "is_daily": True
            },
            {
                "quest_id": "daily_dedicated",
                "name": "Dedicated Poster",
                "description": "Post 8 images in one day",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "very_hard",
                "target_count": 8,
                "reward_points": 85,
                "rarity_chance": 0.3,
                "is_daily": True
            },
            
            # Small Community Engagement Quests
            {
                "quest_id": "daily_first_like",
                "name": "First Impression",
                "description": "Get your first like of the day",
                "quest_type": "earn_likes",
                "category": "engagement",
                "difficulty": "easy",
                "target_count": 1,
                "reward_points": 8,
                "rarity_chance": 0.95,
                "is_daily": True
            },
            {
                "quest_id": "daily_popular_pick",
                "name": "Popular Pick",
                "description": "Get 3 likes on any single image",
                "quest_type": "viral_image",
                "category": "engagement",
                "difficulty": "easy",
                "target_count": 1,
                "reward_points": 22,
                "rarity_chance": 0.8,
                "is_daily": True
            },
            {
                "quest_id": "daily_crowd_pleaser",
                "name": "Crowd Pleaser",
                "description": "Get 5 likes on a single image",
                "quest_type": "viral_image",
                "category": "engagement",
                "difficulty": "medium",
                "target_count": 1,
                "reward_points": 38,
                "rarity_chance": 0.6,
                "is_daily": True
            },
            {
                "quest_id": "daily_fan_favorite",
                "name": "Fan Favorite",
                "description": "Get 8 likes on one image",
                "quest_type": "viral_image",
                "category": "engagement",
                "difficulty": "hard",
                "target_count": 1,
                "reward_points": 60,
                "rarity_chance": 0.4,
                "is_daily": True
            },
            {
                "quest_id": "daily_community_star",
                "name": "Community Star",
                "description": "Get 12 likes on a single image",
                "quest_type": "viral_image",
                "category": "engagement",
                "difficulty": "very_hard",
                "target_count": 1,
                "reward_points": 95,
                "rarity_chance": 0.2,
                "is_daily": True
            },
            {
                "quest_id": "daily_total_likes_3",
                "name": "Rising Star",
                "description": "Get 3 total likes across all your images",
                "quest_type": "earn_likes",
                "category": "engagement",
                "difficulty": "easy",
                "target_count": 3,
                "reward_points": 15,
                "rarity_chance": 0.9,
                "is_daily": True
            },
            {
                "quest_id": "daily_total_likes_8",
                "name": "Popular Creator",
                "description": "Get 8 total likes today",
                "quest_type": "earn_likes",
                "category": "engagement",
                "difficulty": "medium",
                "target_count": 8,
                "reward_points": 42,
                "rarity_chance": 0.65,
                "is_daily": True
            },
            {
                "quest_id": "daily_total_likes_15",
                "name": "Community Darling",
                "description": "Get 15 total likes today",
                "quest_type": "earn_likes",
                "category": "engagement",
                "difficulty": "hard",
                "target_count": 15,
                "reward_points": 75,
                "rarity_chance": 0.35,
                "is_daily": True
            },
            
            # Rating & Community Interaction
            {
                "quest_id": "daily_rate_3",
                "name": "Quick Judge",
                "description": "Rate 3 images",
                "quest_type": "rate_images",
                "category": "rating",
                "difficulty": "easy",
                "target_count": 3,
                "reward_points": 8,
                "rarity_chance": 1.0,
                "is_daily": True
            },
            {
                "quest_id": "daily_rate_15",
                "name": "Thoughtful Critic",
                "description": "Rate 15 images",
                "quest_type": "rate_images",
                "category": "rating",
                "difficulty": "medium",
                "target_count": 15,
                "reward_points": 32,
                "rarity_chance": 0.75,
                "is_daily": True
            },
            {
                "quest_id": "daily_rate_25",
                "name": "Dedicated Reviewer",
                "description": "Rate 25 images",
                "quest_type": "rate_images",
                "category": "rating",
                "difficulty": "hard",
                "target_count": 25,
                "reward_points": 48,
                "rarity_chance": 0.55,
                "is_daily": True
            },
            {
                "quest_id": "daily_rate_40",
                "name": "Master Reviewer",
                "description": "Rate 40 images",
                "quest_type": "rate_images",
                "category": "rating",
                "difficulty": "very_hard",
                "target_count": 40,
                "reward_points": 72,
                "rarity_chance": 0.35,
                "is_daily": True
            },
            {
                "quest_id": "daily_positive_vibes",
                "name": "Positive Vibes Only",
                "description": "Give out 8 thumbs up",
                "quest_type": "give_likes",
                "category": "community",
                "difficulty": "easy",
                "target_count": 8,
                "reward_points": 16,
                "rarity_chance": 0.85,
                "is_daily": True
            },
            {
                "quest_id": "daily_support_squad",
                "name": "Support Squad",
                "description": "Give out 15 thumbs up",
                "quest_type": "give_likes",
                "category": "community",
                "difficulty": "medium",
                "target_count": 15,
                "reward_points": 28,
                "rarity_chance": 0.7,
                "is_daily": True
            },
            {
                "quest_id": "daily_hype_master",
                "name": "Hype Master",
                "description": "Give out 25 thumbs up",
                "quest_type": "give_likes",
                "category": "community",
                "difficulty": "hard",
                "target_count": 25,
                "reward_points": 50,
                "rarity_chance": 0.5,
                "is_daily": True
            },
            {
                "quest_id": "daily_cheerleader",
                "name": "Ultimate Cheerleader",
                "description": "Give out 35 thumbs up",
                "quest_type": "give_likes",
                "category": "community",
                "difficulty": "very_hard",
                "target_count": 35,
                "reward_points": 68,
                "rarity_chance": 0.3,
                "is_daily": True
            },
            
            # Diversity & Exploration
            {
                "quest_id": "daily_meet_new_people",
                "name": "Meet New People",
                "description": "React to images from 3 different users",
                "quest_type": "diverse_reactions",
                "category": "community",
                "difficulty": "easy",
                "target_count": 3,
                "reward_points": 12,
                "rarity_chance": 0.9,
                "is_daily": True
            },
            {
                "quest_id": "daily_social_mixer",
                "name": "Social Mixer",
                "description": "React to images from 6 different users",
                "quest_type": "diverse_reactions",
                "category": "community",
                "difficulty": "medium",
                "target_count": 6,
                "reward_points": 26,
                "rarity_chance": 0.75,
                "is_daily": True
            },
            {
                "quest_id": "daily_community_connector",
                "name": "Community Connector",
                "description": "React to images from 12 different users",
                "quest_type": "diverse_reactions",
                "category": "community",
                "difficulty": "hard",
                "target_count": 12,
                "reward_points": 52,
                "rarity_chance": 0.5,
                "is_daily": True
            },
            {
                "quest_id": "daily_everybody_friend",
                "name": "Everybody's Friend",
                "description": "React to images from 15 different users",
                "quest_type": "diverse_reactions",
                "category": "community",
                "difficulty": "very_hard",
                "target_count": 15,
                "reward_points": 78,
                "rarity_chance": 0.25,
                "is_daily": True
            },
            {
                "quest_id": "daily_channel_hopper",
                "name": "Channel Hopper",
                "description": "Post in both image channels",
                "quest_type": "explore_channels",
                "category": "community",
                "difficulty": "easy",
                "target_count": 2,
                "reward_points": 18,
                "rarity_chance": 0.8,
                "is_daily": True
            },
            
            # Time-Based Variety
            {
                "quest_id": "daily_sunrise_special",
                "name": "Sunrise Special",
                "description": "Post before 8 AM",
                "quest_type": "early_post",
                "category": "time_based",
                "difficulty": "medium",
                "target_count": 1,
                "reward_points": 28,
                "rarity_chance": 0.45,
                "is_daily": True
            },
            {
                "quest_id": "daily_midnight_post",
                "name": "Midnight Oil",
                "description": "Post after midnight",
                "quest_type": "late_post",
                "category": "time_based",
                "difficulty": "medium",
                "target_count": 1,
                "reward_points": 32,
                "rarity_chance": 0.4,
                "is_daily": True
            },
            {
                "quest_id": "daily_lunch_break",
                "name": "Lunch Break Post",
                "description": "Post between 11 AM and 2 PM",
                "quest_type": "post_images",
                "category": "time_based",
                "difficulty": "easy",
                "target_count": 1,
                "reward_points": 14,
                "rarity_chance": 0.75,
                "is_daily": True
            },
            {
                "quest_id": "daily_evening_artist",
                "name": "Evening Artist",
                "description": "Post 2 images between 6 PM and 10 PM",
                "quest_type": "post_images",
                "category": "time_based",
                "difficulty": "easy",
                "target_count": 2,
                "reward_points": 20,
                "rarity_chance": 0.7,
                "is_daily": True
            },
            
            # Combo Quests
            {
                "quest_id": "daily_starter_pack",
                "name": "Starter Pack",
                "description": "Post 1 image AND rate 5 images",
                "quest_type": "combo",
                "category": "combo",
                "difficulty": "easy",
                "target_count": 1,
                "reward_points": 20,
                "rarity_chance": 0.9,
                "is_daily": True
            },
            {
                "quest_id": "daily_active_member",
                "name": "Active Member",
                "description": "Post 2 images AND give 10 likes",
                "quest_type": "combo",
                "category": "combo",
                "difficulty": "medium",
                "target_count": 1,
                "reward_points": 38,
                "rarity_chance": 0.65,
                "is_daily": True
            },
            {
                "quest_id": "daily_power_user",
                "name": "Power User",
                "description": "Post 3 images AND rate 20 images",
                "quest_type": "combo",
                "category": "combo",
                "difficulty": "hard",
                "target_count": 1,
                "reward_points": 68,
                "rarity_chance": 0.4,
                "is_daily": True
            },
            {
                "quest_id": "daily_super_contributor",
                "name": "Super Contributor",
                "description": "Post 5 images AND rate 30 images",
                "quest_type": "combo",
                "category": "combo",
                "difficulty": "very_hard",
                "target_count": 1,
                "reward_points": 95,
                "rarity_chance": 0.2,
                "is_daily": True
            },
            
            # Special Achievement-Style Quests
            {
                "quest_id": "daily_comeback",
                "name": "The Comeback",
                "description": "Post after being inactive for a day",
                "quest_type": "comeback",
                "category": "special",
                "difficulty": "easy",
                "target_count": 1,
                "reward_points": 25,
                "rarity_chance": 0.3,
                "is_daily": True
            },
            {
                "quest_id": "daily_quality_control",
                "name": "Quality Control",
                "description": "Post 1 image with at least 4 likes",
                "quest_type": "quality_post",
                "category": "special",
                "difficulty": "medium",
                "target_count": 1,
                "reward_points": 35,
                "rarity_chance": 0.55,
                "is_daily": True
            },
            {
                "quest_id": "daily_trending",
                "name": "Trending Creator",
                "description": "Post 1 image with at least 7 likes",
                "quest_type": "quality_post",
                "category": "special",
                "difficulty": "hard",
                "target_count": 1,
                "reward_points": 55,
                "rarity_chance": 0.4,
                "is_daily": True
            },
            {
                "quest_id": "daily_helping_hand",
                "name": "Helping Hand",
                "description": "Like images from 3 users with less than 5 posts",
                "quest_type": "support_new_users",
                "category": "community",
                "difficulty": "easy",
                "target_count": 3,
                "reward_points": 22,
                "rarity_chance": 0.7,
                "is_daily": True
            },
            {
                "quest_id": "daily_welcoming_committee",
                "name": "Welcoming Committee",
                "description": "Like images from 7 different users",
                "quest_type": "support_new_users",
                "category": "community",
                "difficulty": "medium",
                "target_count": 7,
                "reward_points": 42,
                "rarity_chance": 0.6,
                "is_daily": True
            },
            {
                "quest_id": "daily_consistent_poster",
                "name": "Consistent Poster",
                "description": "Post at least 2 images (keep that streak!)",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "easy",
                "target_count": 2,
                "reward_points": 16,
                "rarity_chance": 0.9,
                "is_daily": True
            },
            {
                "quest_id": "daily_channel_variety",
                "name": "Channel Variety",
                "description": "React in both channels with at least 3 reactions each",
                "quest_type": "explore_channels",
                "category": "community",
                "difficulty": "medium",
                "target_count": 2,
                "reward_points": 34,
                "rarity_chance": 0.6,
                "is_daily": True
            },
            {
                "quest_id": "daily_engagement_boost",
                "name": "Engagement Boost",
                "description": "Get 2 likes on at least 2 different images",
                "quest_type": "multi_liked",
                "category": "engagement",
                "difficulty": "medium",
                "target_count": 2,
                "reward_points": 30,
                "rarity_chance": 0.65,
                "is_daily": True
            },
            {
                "quest_id": "daily_conversation_starter",
                "name": "Conversation Starter",
                "description": "Get reactions from 4 different users on your posts",
                "quest_type": "diverse_reactions_received",
                "category": "engagement",
                "difficulty": "medium",
                "target_count": 4,
                "reward_points": 36,
                "rarity_chance": 0.6,
                "is_daily": True
            },
            {
                "quest_id": "daily_perfect_ten",
                "name": "Perfect Ten",
                "description": "Post exactly 10 images",
                "quest_type": "post_images",
                "category": "posting",
                "difficulty": "very_hard",
                "target_count": 10,
                "reward_points": 110,
                "rarity_chance": 0.15,
                "is_daily": True
            },
            {
                "quest_id": "daily_speed_poster",
                "name": "Speed Poster",
                "description": "Post 3 images within 30 minutes",
                "quest_type": "rapid_post",
                "category": "special",
                "difficulty": "medium",
                "target_count": 3,
                "reward_points": 40,
                "rarity_chance": 0.5,
                "is_daily": True
            }
        ]
        
        # Achievements
        achievements = [
            {
                "achievement_id": "winner_week",
                "name": "Weekly Champion",
                "description": "Win image of the week",
                "achievement_type": "competition_win",
                "target_count": 1,
                "reward_points": 100,
                "icon": "🥇"
            },
            {
                "achievement_id": "winner_month",
                "name": "Monthly Master",
                "description": "Win image of the month",
                "achievement_type": "competition_win",
                "target_count": 1,
                "reward_points": 250,
                "icon": "👑"
            },
            {
                "achievement_id": "winner_year",
                "name": "Yearly Legend",
                "description": "Win image of the year",
                "achievement_type": "competition_win",
                "target_count": 1,
                "reward_points": 500,
                "icon": "🏆"
            },
            {
                "achievement_id": "post_50",
                "name": "Dedicated Poster",
                "description": "Post 50 images",
                "achievement_type": "post_images",
                "target_count": 50,
                "reward_points": 75,
                "icon": "📸"
            },
            {
                "achievement_id": "post_150",
                "name": "Image Enthusiast",
                "description": "Post 150 images",
                "achievement_type": "post_images",
                "target_count": 150,
                "reward_points": 200,
                "icon": "🎨"
            },
            {
                "achievement_id": "post_500",
                "name": "Content Creator",
                "description": "Post 500 images",
                "achievement_type": "post_images",
                "target_count": 500,
                "reward_points": 500,
                "icon": "🌟"
            },
            {
                "achievement_id": "rate_150",
                "name": "Art Critic",
                "description": "Rate 150 images",
                "achievement_type": "rate_images",
                "target_count": 150,
                "reward_points": 100,
                "icon": "🎭"
            },
            {
                "achievement_id": "rate_500",
                "name": "Master Curator",
                "description": "Rate 500 images",
                "achievement_type": "rate_images",
                "target_count": 500,
                "reward_points": 250,
                "icon": "🏛️"
            },
            {
                "achievement_id": "score_100",
                "name": "Rising Star",
                "description": "Reach 100 total score",
                "achievement_type": "total_score",
                "target_count": 100,
                "reward_points": 50,
                "icon": "⭐"
            },
            {
                "achievement_id": "score_500",
                "name": "Community Favorite",
                "description": "Reach 500 total score",
                "achievement_type": "total_score",
                "target_count": 500,
                "reward_points": 150,
                "icon": "💫"
            },
            {
                "achievement_id": "score_1000",
                "name": "Hall of Fame",
                "description": "Reach 1000 total score",
                "achievement_type": "total_score",
                "target_count": 1000,
                "reward_points": 300,
                "icon": "🌠"
            },
            # Streak Achievements
            {
                "achievement_id": "streak_7",
                "name": "Week Warrior",
                "description": "Complete quests for 7 days in a row",
                "achievement_type": "quest_streak",
                "target_count": 7,
                "reward_points": 100,
                "icon": "🔥"
            },
            {
                "achievement_id": "streak_30",
                "name": "Monthly Dedication",
                "description": "Complete quests for 30 days in a row",
                "achievement_type": "quest_streak",
                "target_count": 30,
                "reward_points": 300,
                "icon": "🌟"
            },
            {
                "achievement_id": "streak_100",
                "name": "Streak Master",
                "description": "Complete quests for 100 days in a row",
                "achievement_type": "quest_streak",
                "target_count": 100,
                "reward_points": 1000,
                "icon": "👑"
            },
            {
                "achievement_id": "post_streak_7",
                "name": "Daily Poster",
                "description": "Post at least 1 image for 7 days in a row",
                "achievement_type": "post_streak",
                "target_count": 7,
                "reward_points": 75,
                "icon": "📷"
            },
            {
                "achievement_id": "post_streak_30",
                "name": "Content Machine",
                "description": "Post at least 1 image for 30 days in a row",
                "achievement_type": "post_streak",
                "target_count": 30,
                "reward_points": 250,
                "icon": "🎬"
            },
            
            # ========== NEW ACHIEVEMENTS - EXPANDED ==========
            # Quest Completion Milestones
            {
                "achievement_id": "quest_10",
                "name": "Quest Beginner",
                "description": "Complete 10 quests",
                "achievement_type": "quests_completed",
                "target_count": 10,
                "reward_points": 50,
                "icon": "📝"
            },
            {
                "achievement_id": "quest_50",
                "name": "Quest Hunter",
                "description": "Complete 50 quests",
                "achievement_type": "quests_completed",
                "target_count": 50,
                "reward_points": 150,
                "icon": "🎯"
            },
            {
                "achievement_id": "quest_100",
                "name": "Quest Master",
                "description": "Complete 100 quests",
                "achievement_type": "quests_completed",
                "target_count": 100,
                "reward_points": 350,
                "icon": "🏅"
            },
            {
                "achievement_id": "quest_250",
                "name": "Quest Legend",
                "description": "Complete 250 quests",
                "achievement_type": "quests_completed",
                "target_count": 250,
                "reward_points": 750,
                "icon": "🔱"
            },
            {
                "achievement_id": "quest_500",
                "name": "Quest Immortal",
                "description": "Complete 500 quests",
                "achievement_type": "quests_completed",
                "target_count": 500,
                "reward_points": 1500,
                "icon": "👼"
            },
            
            # More Posting Milestones
            {
                "achievement_id": "post_10",
                "name": "Getting Started",
                "description": "Post 10 images",
                "achievement_type": "post_images",
                "target_count": 10,
                "reward_points": 25,
                "icon": "🌱"
            },
            {
                "achievement_id": "post_25",
                "name": "Active Contributor",
                "description": "Post 25 images",
                "achievement_type": "post_images",
                "target_count": 25,
                "reward_points": 40,
                "icon": "🌿"
            },
            {
                "achievement_id": "post_100",
                "name": "Frequent Poster",
                "description": "Post 100 images",
                "achievement_type": "post_images",
                "target_count": 100,
                "reward_points": 125,
                "icon": "🌳"
            },
            {
                "achievement_id": "post_250",
                "name": "Image Veteran",
                "description": "Post 250 images",
                "achievement_type": "post_images",
                "target_count": 250,
                "reward_points": 300,
                "icon": "🎨"
            },
            {
                "achievement_id": "post_1000",
                "name": "Legendary Creator",
                "description": "Post 1000 images",
                "achievement_type": "post_images",
                "target_count": 1000,
                "reward_points": 1000,
                "icon": "💎"
            },
            
            # Rating Milestones
            {
                "achievement_id": "rate_50",
                "name": "Casual Critic",
                "description": "Rate 50 images",
                "achievement_type": "rate_images",
                "target_count": 50,
                "reward_points": 40,
                "icon": "👓"
            },
            {
                "achievement_id": "rate_100",
                "name": "Active Reviewer",
                "description": "Rate 100 images",
                "achievement_type": "rate_images",
                "target_count": 100,
                "reward_points": 75,
                "icon": "🔍"
            },
            {
                "achievement_id": "rate_250",
                "name": "Expert Curator",
                "description": "Rate 250 images",
                "achievement_type": "rate_images",
                "target_count": 250,
                "reward_points": 175,
                "icon": "🎓"
            },
            {
                "achievement_id": "rate_1000",
                "name": "Legendary Curator",
                "description": "Rate 1000 images",
                "achievement_type": "rate_images",
                "target_count": 1000,
                "reward_points": 600,
                "icon": "🏛️"
            },
            
            # Engagement/Likes Achievements
            {
                "achievement_id": "viral_5",
                "name": "Going Viral",
                "description": "Get 5 likes on a single image",
                "achievement_type": "viral_image",
                "target_count": 5,
                "reward_points": 30,
                "icon": "📈"
            },
            {
                "achievement_id": "viral_10",
                "name": "Viral Sensation",
                "description": "Get 10 likes on a single image",
                "achievement_type": "viral_image",
                "target_count": 10,
                "reward_points": 75,
                "icon": "🚀"
            },
            {
                "achievement_id": "viral_20",
                "name": "Community Icon",
                "description": "Get 20 likes on a single image",
                "achievement_type": "viral_image",
                "target_count": 20,
                "reward_points": 150,
                "icon": "💫"
            },
            {
                "achievement_id": "likes_100",
                "name": "Popular Creator",
                "description": "Earn 100 total likes on your images",
                "achievement_type": "total_likes",
                "target_count": 100,
                "reward_points": 80,
                "icon": "👍"
            },
            {
                "achievement_id": "likes_500",
                "name": "Crowd Favorite",
                "description": "Earn 500 total likes on your images",
                "achievement_type": "total_likes",
                "target_count": 500,
                "reward_points": 250,
                "icon": "💖"
            },
            {
                "achievement_id": "likes_1000",
                "name": "Beloved Creator",
                "description": "Earn 1000 total likes on your images",
                "achievement_type": "total_likes",
                "target_count": 1000,
                "reward_points": 500,
                "icon": "💝"
            },
            
            # More Score Milestones
            {
                "achievement_id": "score_50",
                "name": "Gaining Momentum",
                "description": "Reach 50 total score",
                "achievement_type": "total_score",
                "target_count": 50,
                "reward_points": 30,
                "icon": "✨"
            },
            {
                "achievement_id": "score_250",
                "name": "Popular Figure",
                "description": "Reach 250 total score",
                "achievement_type": "total_score",
                "target_count": 250,
                "reward_points": 100,
                "icon": "🌟"
            },
            {
                "achievement_id": "score_2000",
                "name": "Legendary Status",
                "description": "Reach 2000 total score",
                "achievement_type": "total_score",
                "target_count": 2000,
                "reward_points": 600,
                "icon": "🎆"
            },
            
            # Streak Achievements (More)
            {
                "achievement_id": "streak_3",
                "name": "Getting Consistent",
                "description": "Complete quests for 3 days in a row",
                "achievement_type": "quest_streak",
                "target_count": 3,
                "reward_points": 25,
                "icon": "🔥"
            },
            {
                "achievement_id": "streak_14",
                "name": "Two Week Warrior",
                "description": "Complete quests for 14 days in a row",
                "achievement_type": "quest_streak",
                "target_count": 14,
                "reward_points": 175,
                "icon": "🔥"
            },
            {
                "achievement_id": "streak_50",
                "name": "Streak Champion",
                "description": "Complete quests for 50 days in a row",
                "achievement_type": "quest_streak",
                "target_count": 50,
                "reward_points": 500,
                "icon": "🔥"
            },
            {
                "achievement_id": "post_streak_3",
                "name": "Starting Streak",
                "description": "Post at least 1 image for 3 days in a row",
                "achievement_type": "post_streak",
                "target_count": 3,
                "reward_points": 20,
                "icon": "📸"
            },
            {
                "achievement_id": "post_streak_14",
                "name": "Two Week Poster",
                "description": "Post at least 1 image for 14 days in a row",
                "achievement_type": "post_streak",
                "target_count": 14,
                "reward_points": 125,
                "icon": "📷"
            },
            {
                "achievement_id": "post_streak_60",
                "name": "Two Month Machine",
                "description": "Post at least 1 image for 60 days in a row",
                "achievement_type": "post_streak",
                "target_count": 60,
                "reward_points": 500,
                "icon": "🎥"
            },
            
            # Community & Support Achievements
            {
                "achievement_id": "supporter_50",
                "name": "Supportive Member",
                "description": "Give 50 likes to others",
                "achievement_type": "likes_given",
                "target_count": 50,
                "reward_points": 35,
                "icon": "💚"
            },
            {
                "achievement_id": "supporter_200",
                "name": "Community Cheerleader",
                "description": "Give 200 likes to others",
                "achievement_type": "likes_given",
                "target_count": 200,
                "reward_points": 100,
                "icon": "💙"
            },
            {
                "achievement_id": "supporter_500",
                "name": "Ultimate Hype Person",
                "description": "Give 500 likes to others",
                "achievement_type": "likes_given",
                "target_count": 500,
                "reward_points": 225,
                "icon": "💜"
            },
            {
                "achievement_id": "diverse_50",
                "name": "Social Networker",
                "description": "React to images from 50 different users",
                "achievement_type": "diverse_users",
                "target_count": 50,
                "reward_points": 100,
                "icon": "🤝"
            },
            {
                "achievement_id": "diverse_100",
                "name": "Community Connector",
                "description": "React to images from 100 different users",
                "achievement_type": "diverse_users",
                "target_count": 100,
                "reward_points": 250,
                "icon": "🌐"
            },
            
            # Special/Fun Achievements
            {
                "achievement_id": "early_bird",
                "name": "Early Bird",
                "description": "Post before 6 AM 10 times",
                "achievement_type": "early_posts",
                "target_count": 10,
                "reward_points": 60,
                "icon": "🌅"
            },
            {
                "achievement_id": "night_owl",
                "name": "Night Owl",
                "description": "Post after midnight 10 times",
                "achievement_type": "late_posts",
                "target_count": 10,
                "reward_points": 60,
                "icon": "🦉"
            },
            {
                "achievement_id": "speed_demon",
                "name": "Speed Demon",
                "description": "Post 5 images in under 10 minutes",
                "achievement_type": "rapid_posts",
                "target_count": 5,
                "reward_points": 50,
                "icon": "⚡"
            },
            {
                "achievement_id": "comeback_kid",
                "name": "Comeback Kid",
                "description": "Return after 7+ days of inactivity 3 times",
                "achievement_type": "comebacks",
                "target_count": 3,
                "reward_points": 75,
                "icon": "🔄"
            },
            {
                "achievement_id": "perfect_day",
                "name": "Perfect Day",
                "description": "Complete all daily quests in one day",
                "achievement_type": "perfect_day",
                "target_count": 1,
                "reward_points": 200,
                "icon": "💯"
            },
            {
                "achievement_id": "quest_points_1000",
                "name": "Point Collector",
                "description": "Earn 1000 quest points",
                "achievement_type": "quest_points",
                "target_count": 1000,
                "reward_points": 150,
                "icon": "💎"
            },
            {
                "achievement_id": "quest_points_5000",
                "name": "Point Master",
                "description": "Earn 5000 quest points",
                "achievement_type": "quest_points",
                "target_count": 5000,
                "reward_points": 500,
                "icon": "💠"
            },
            {
                "achievement_id": "first_post",
                "name": "First Steps",
                "description": "Post your very first image",
                "achievement_type": "post_images",
                "target_count": 1,
                "reward_points": 10,
                "icon": "👶"
            },
            {
                "achievement_id": "first_quest",
                "name": "Quest Starter",
                "description": "Complete your first quest",
                "achievement_type": "quests_completed",
                "target_count": 1,
                "reward_points": 15,
                "icon": "🎬"
            },
            {
                "achievement_id": "bookworm",
                "name": "Bookworm",
                "description": "Bookmark 25 images",
                "achievement_type": "bookmarks",
                "target_count": 25,
                "reward_points": 40,
                "icon": "📚"
            },
            {
                "achievement_id": "collector",
                "name": "Collection Master",
                "description": "Bookmark 100 images",
                "achievement_type": "bookmarks",
                "target_count": 100,
                "reward_points": 125,
                "icon": "📖"
            }
        ]
        
        # Insert quests if they don't exist
        for quest in daily_quests:
            self.quests_collection.update_one(
                {"quest_id": quest["quest_id"]},
                {"$set": quest},
                upsert=True
            )
        
        # Insert achievements if they don't exist
        for achievement in achievements:
            self.achievements_collection.update_one(
                {"achievement_id": achievement["achievement_id"]},
                {"$set": achievement},
                upsert=True
            )
        
        logger.info("Initialized default quests and achievements")
    
    async def generate_daily_quests(self, user_id: int, member: 'discord.Member' = None) -> List[Dict]:
        """Generate 3-5 random daily quests for a user with difficulty/rarity system"""
        try:
            today = datetime.now().date()
            
            # Check if user already has quests for today
            existing_quests = list(self.user_quests_collection.find({
                "user_id": str(user_id),
                "date": today.isoformat()
            }))
            
            if existing_quests:
                return existing_quests
            
            # Get all available daily quests
            available_quests = list(self.quests_collection.find({"is_daily": True}))
            
            # Filter quests by rarity chance
            potential_quests = []
            for quest in available_quests:
                rarity_chance = quest.get("rarity_chance", 1.0)
                if random.random() <= rarity_chance:
                    potential_quests.append(quest)
            
            # Ensure we have at least some quests
            if len(potential_quests) < 3:
                # Add some easy quests to guarantee at least 3
                easy_quests = [q for q in available_quests if q.get("difficulty") == "easy"]
                potential_quests.extend(easy_quests[:3])
                potential_quests = list({q["quest_id"]: q for q in potential_quests}.values())  # Remove duplicates
            
            # Select 3-5 quests, ensuring no duplicate categories
            selected_count = random.randint(3, 5)
            selected_quests = []
            used_categories = set()
            
            # Shuffle for randomness
            random.shuffle(potential_quests)
            
            for quest in potential_quests:
                if len(selected_quests) >= selected_count:
                    break
                
                category = quest.get("category", "general")
                
                # Skip if we already have a quest from this category
                if category in used_categories and len(potential_quests) > selected_count:
                    continue
                
                selected_quests.append(quest)
                used_categories.add(category)
            
            # If we still don't have enough, add more without category restriction
            if len(selected_quests) < 3:
                for quest in potential_quests:
                    if quest not in selected_quests:
                        selected_quests.append(quest)
                        if len(selected_quests) >= 3:
                            break
            
            # Check for Patreon multiplier
            patreon_multiplier = 1.0
            if member:
                from config import Config
                if Config.PATREON_ROLE_ID:
                    patreon_role = discord.utils.get(member.roles, id=Config.PATREON_ROLE_ID)
                    if patreon_role:
                        patreon_multiplier = 1.5
                        logger.info(f"User {user_id} has Patreon role - 1.5x points multiplier applied")
            
            # Create user quest records
            user_quests = []
            for quest in selected_quests:
                base_points = quest["reward_points"]
                final_points = int(base_points * patreon_multiplier)
                
                user_quest = {
                    "user_id": str(user_id),
                    "quest_id": quest["quest_id"],
                    "name": quest["name"],
                    "description": quest["description"],
                    "quest_type": quest["quest_type"],
                    "category": quest.get("category", "general"),
                    "difficulty": quest.get("difficulty", "medium"),
                    "target_count": quest["target_count"],
                    "current_count": 0,
                    "reward_points": final_points,
                    "base_reward_points": base_points,
                    "patreon_multiplier": patreon_multiplier,
                    "completed": False,
                    "date": today.isoformat(),
                    "created_at": datetime.now()
                }
                
                self.user_quests_collection.insert_one(user_quest)
                user_quests.append(user_quest)
            
            logger.info(f"Generated {len(user_quests)} daily quests for user {user_id} (Patreon: {patreon_multiplier}x)")
            return user_quests
            
        except Exception as e:
            logger.error(f"Error generating daily quests: {e}")
            return []
    
    async def update_quest_progress(self, user_id: int, quest_type: str, count: int = 1):
        """Update quest progress for a user"""
        try:
            today = datetime.now().date()
            
            # Update daily quests
            result = self.user_quests_collection.update_many(
                {
                    "user_id": str(user_id),
                    "quest_type": quest_type,
                    "date": today.isoformat(),
                    "completed": False
                },
                {"$inc": {"current_count": count}}
            )
            
            # Check for completed quests
            completed_quests = []
            quests_to_check = self.user_quests_collection.find({
                "user_id": str(user_id),
                "quest_type": quest_type,
                "date": today.isoformat(),
                "completed": False
            })
            
            for quest in quests_to_check:
                if quest["current_count"] >= quest["target_count"]:
                    # Mark quest as completed
                    self.user_quests_collection.update_one(
                        {"_id": quest["_id"]},
                        {
                            "$set": {
                                "completed": True,
                                "completed_at": datetime.now()
                            }
                        }
                    )
                    completed_quests.append(quest)
            
            # Update streak if any quest was completed
            if completed_quests:
                await self._update_quest_streak(user_id)
            
            return completed_quests
            
        except Exception as e:
            logger.error(f"Error updating quest progress: {e}")
            return []
    
    async def track_unique_user_like(self, user_id: int, liked_user_id: int) -> List[Dict]:
        """Track likes from unique users for the 'support_new_users' quest"""
        try:
            if user_id == liked_user_id:  # Don't count self-likes
                return []
            
            today = datetime.now().date()
            tracking_key = f"liked_users_{today.isoformat()}"
            
            # Ensure a compound index on (user_id, tracking_key) to allow multiple keys per user
            try:
                self.user_stats_collection.create_index([("user_id", 1), ("tracking_key", 1)], unique=True)
            except Exception:
                pass

            # Ensure a compound index on (user_id, tracking_key) to allow multiple keys per user
            try:
                self.user_stats_collection.create_index([("user_id", 1), ("tracking_key", 1)], unique=True)
            except Exception:
                pass

            # Get or create tracking document for today
            track_doc = self.user_stats_collection.find_one({
                "user_id": str(user_id),
                "tracking_key": tracking_key
            })
            
            if not track_doc:
                # Create new tracking document
                track_doc = {
                    "user_id": str(user_id),
                    "tracking_key": tracking_key,
                    "liked_user_ids": [str(liked_user_id)],
                    "unique_count": 1,
                    "created_at": datetime.now()
                }
                try:
                    self.user_stats_collection.insert_one(track_doc)
                except Exception:
                    # If a race condition caused duplicate, fetch again
                    track_doc = self.user_stats_collection.find_one({
                        "user_id": str(user_id),
                        "tracking_key": tracking_key
                    })
                unique_count = 1
            else:
                # Check if this user was already liked today
                liked_users = track_doc.get("liked_user_ids", [])
                if str(liked_user_id) not in liked_users:
                    liked_users.append(str(liked_user_id))
                    unique_count = len(liked_users)
                    
                    self.user_stats_collection.update_one(
                        {"_id": track_doc["_id"]},
                        {
                            "$set": {
                                "liked_user_ids": liked_users,
                                "unique_count": unique_count
                            }
                        }
                    )
                else:
                    return []  # Already liked this user today
            
            # Update the support_new_users quest with the unique count
            result = self.user_quests_collection.update_many(
                {
                    "user_id": str(user_id),
                    "quest_type": "support_new_users",
                    "date": today.isoformat(),
                    "completed": False
                },
                {"$set": {"current_count": unique_count}}
            )
            
            # Check for completed quests
            completed_quests = []
            quests_to_check = self.user_quests_collection.find({
                "user_id": str(user_id),
                "quest_type": "support_new_users",
                "date": today.isoformat(),
                "completed": False
            })
            
            for quest in quests_to_check:
                if quest["current_count"] >= quest["target_count"]:
                    self.user_quests_collection.update_one(
                        {"_id": quest["_id"]},
                        {
                            "$set": {
                                "completed": True,
                                "completed_at": datetime.now()
                            }
                        }
                    )
                    completed_quests.append(quest)
                    logger.info(f"User {user_id} completed support_new_users quest! ({unique_count} unique users)")
            
            if completed_quests:
                await self._update_quest_streak(user_id)
            
            return completed_quests
            
        except Exception as e:
            logger.error(f"Error tracking unique user like: {e}")
            return []
    
    async def track_channel_exploration(self, user_id: int, channel_id: int) -> List[Dict]:
        """Track reactions in different channels for the 'explore_channels' quest"""
        try:
            today = datetime.now().date()
            tracking_key = f"explored_channels_{today.isoformat()}"
            
            # Get or create tracking document for today
            track_doc = self.user_stats_collection.find_one({
                "user_id": str(user_id),
                "tracking_key": tracking_key
            })
            
            if not track_doc:
                # Create new tracking document
                track_doc = {
                    "user_id": str(user_id),
                    "tracking_key": tracking_key,
                    "channel_ids": [str(channel_id)],
                    "channel_count": 1,
                    "created_at": datetime.now()
                }
                try:
                    self.user_stats_collection.insert_one(track_doc)
                    channel_count = 1
                except Exception as e:
                    # Race condition: document was created by another process
                    logger.info(f"⚠️ Race condition in channel tracking, refetching document: {e}")
                    track_doc = self.user_stats_collection.find_one({
                        "user_id": str(user_id),
                        "tracking_key": tracking_key
                    })
                    if track_doc:
                        channels = track_doc.get("channel_ids", [])
                        if str(channel_id) not in channels:
                            channels.append(str(channel_id))
                            channel_count = len(channels)
                            self.user_stats_collection.update_one(
                                {"_id": track_doc["_id"]},
                                {
                                    "$set": {
                                        "channel_ids": channels,
                                        "channel_count": channel_count
                                    }
                                }
                            )
                        else:
                            return []  # Already explored this channel
                    else:
                        # Shouldn't happen, but handle gracefully
                        channel_count = 1
            else:
                # Check if this channel was already explored today
                channels = track_doc.get("channel_ids", [])
                if str(channel_id) not in channels:
                    channels.append(str(channel_id))
                    channel_count = len(channels)
                    
                    self.user_stats_collection.update_one(
                        {"_id": track_doc["_id"]},
                        {
                            "$set": {
                                "channel_ids": channels,
                                "channel_count": channel_count
                            }
                        }
                    )
                    logger.info(f"📍 Channel exploration: User {user_id} now explored {channel_count} channels (added channel {channel_id})")
                else:
                    logger.info(f"⏭️ Channel exploration: User {user_id} already explored channel {channel_id} today")
                    return []  # Already explored this channel today
            
            # Update the explore_channels quest with the channel count
            result = self.user_quests_collection.update_many(
                {
                    "user_id": str(user_id),
                    "quest_type": "explore_channels",
                    "date": today.isoformat(),
                    "completed": False
                },
                {"$set": {"current_count": channel_count}}
            )
            
            # Check for completed quests
            completed_quests = []
            quests_to_check = self.user_quests_collection.find({
                "user_id": str(user_id),
                "quest_type": "explore_channels",
                "date": today.isoformat(),
                "completed": False
            })
            
            for quest in quests_to_check:
                if quest["current_count"] >= quest["target_count"]:
                    self.user_quests_collection.update_one(
                        {"_id": quest["_id"]},
                        {
                            "$set": {
                                "completed": True,
                                "completed_at": datetime.now()
                            }
                        }
                    )
                    completed_quests.append(quest)
                    logger.info(f"User {user_id} completed explore_channels quest! ({channel_count} channels)")
            
            if completed_quests:
                await self._update_quest_streak(user_id)
            
            return completed_quests
            
        except Exception as e:
            logger.error(f"Error tracking channel exploration: {e}")
            return []
    
    async def track_viral_image(self, user_id: int, message_id: str, like_count: int) -> List[Dict]:
        """Track viral images (15+ likes) for the 'viral_image' quest"""
        try:
            today = datetime.now().date()
            tracking_key = f"viral_images_{today.isoformat()}"
            
            # Get or create tracking document for today
            track_doc = self.user_stats_collection.find_one({
                "user_id": str(user_id),
                "tracking_key": tracking_key
            })
            
            viral_messages = []
            if not track_doc:
                # Create new tracking document
                track_doc = {
                    "user_id": str(user_id),
                    "tracking_key": tracking_key,
                    "viral_message_ids": [message_id],
                    "viral_count": 1,
                    "created_at": datetime.now()
                }
                self.user_stats_collection.insert_one(track_doc)
                viral_count = 1
            else:
                # Check if this message was already tracked as viral today
                viral_messages = track_doc.get("viral_message_ids", [])
                if message_id not in viral_messages:
                    viral_messages.append(message_id)
                    viral_count = len(viral_messages)
                    
                    self.user_stats_collection.update_one(
                        {"_id": track_doc["_id"]},
                        {
                            "$set": {
                                "viral_message_ids": viral_messages,
                                "viral_count": viral_count
                            }
                        }
                    )
                else:
                    return []  # Already tracked this viral image today
            
            # Update the viral_image quest
            result = self.user_quests_collection.update_many(
                {
                    "user_id": str(user_id),
                    "quest_type": "viral_image",
                    "date": today.isoformat(),
                    "completed": False
                },
                {"$set": {"current_count": viral_count}}
            )
            
            # Check for completed quests
            completed_quests = []
            quests_to_check = self.user_quests_collection.find({
                "user_id": str(user_id),
                "quest_type": "viral_image",
                "date": today.isoformat(),
                "completed": False
            })
            
            for quest in quests_to_check:
                if quest["current_count"] >= quest["target_count"]:
                    self.user_quests_collection.update_one(
                        {"_id": quest["_id"]},
                        {
                            "$set": {
                                "completed": True,
                                "completed_at": datetime.now()
                            }
                        }
                    )
                    completed_quests.append(quest)
                    logger.info(f"User {user_id} completed viral_image quest! (Image got {like_count} likes)")
            
            if completed_quests:
                await self._update_quest_streak(user_id)
            
            return completed_quests
            
        except Exception as e:
            logger.error(f"Error tracking viral image: {e}")
            return []
    
    async def get_user_total_quest_points(self, user_id: int) -> int:
        """Calculate total quest points earned by a user (completed quests + achievements)"""
        try:
            # Get all completed quests
            completed_quests = list(self.user_quests_collection.find({
                "user_id": str(user_id),
                "completed": True
            }))
            
            quest_points = sum(quest.get("reward_points", 0) for quest in completed_quests)
            
            # Get all earned achievements
            achievements = list(self.user_achievements_collection.find({
                "user_id": str(user_id)
            }))
            
            achievement_points = sum(achievement.get("reward_points", 0) for achievement in achievements)
            
            total_points = quest_points + achievement_points
            logger.debug(f"User {user_id} total points: {total_points} (Quests: {quest_points}, Achievements: {achievement_points})")
            return total_points
            
        except Exception as e:
            logger.error(f"Error calculating user total quest points: {e}")
            return 0
    
    async def get_quest_points_leaderboard(self, limit: int = 10, guild=None) -> List[Tuple[str, int, int, int]]:
        """Get quest points leaderboard with user details"""
        try:
            # Get all unique users who have completed quests or earned achievements
            user_ids_quests = set(doc["user_id"] for doc in self.user_quests_collection.find({"completed": True}))
            user_ids_achievements = set(doc["user_id"] for doc in self.user_achievements_collection.find())
            all_user_ids = user_ids_quests | user_ids_achievements
            
            # Calculate points for each user
            leaderboard_data = []
            for user_id in all_user_ids:
                total_points = await self.get_user_total_quest_points(int(user_id))
                if total_points > 0:
                    # Try to get user name from Discord guild
                    user_name = "Unknown User"
                    if guild:
                        try:
                            member = guild.get_member(int(user_id))
                            if member:
                                user_name = member.display_name
                            else:
                                # Try fetching if not in cache
                                member = await guild.fetch_member(int(user_id))
                                if member:
                                    user_name = member.display_name
                        except:
                            # Fall back to database lookup
                            recent_quest = self.user_quests_collection.find_one({"user_id": user_id})
                            recent_achievement = self.user_achievements_collection.find_one({"user_id": user_id})
                            
                            if recent_quest and "user_name" in recent_quest:
                                user_name = recent_quest["user_name"]
                            elif recent_achievement and "user_name" in recent_achievement:
                                user_name = recent_achievement["user_name"]
                    
                    # Count completed quests and achievements
                    completed_quest_count = self.user_quests_collection.count_documents({
                        "user_id": user_id,
                        "completed": True
                    })
                    achievement_count = self.user_achievements_collection.count_documents({"user_id": user_id})
                    
                    leaderboard_data.append((user_name, int(user_id), total_points, completed_quest_count, achievement_count))
            
            # Sort by total points descending
            leaderboard_data.sort(key=lambda x: x[2], reverse=True)
            
            # Return top N
            return leaderboard_data[:limit]
            
        except Exception as e:
            logger.error(f"Error getting quest points leaderboard: {e}")
            return []
    
    async def check_achievements(self, user_id: int, leaderboard_manager) -> List[Dict]:
        """Check and award achievements for a user"""
        try:
            # Get user stats
            user_stats = leaderboard_manager.get_user_stats(user_id)
            if not user_stats:
                return []
            
            # Get all achievements
            all_achievements = list(self.achievements_collection.find())
            
            # Get user's current achievements
            user_achievements = set(
                doc["achievement_id"] for doc in 
                self.user_achievements_collection.find({"user_id": str(user_id)})
            )
            
            new_achievements = []
            
            for achievement in all_achievements:
                # Skip if user already has this achievement
                if achievement["achievement_id"] in user_achievements:
                    continue
                
                earned = False
                achievement_type = achievement["achievement_type"]
                target = achievement["target_count"]
                
                # Check basic stats achievements
                if achievement_type == "post_images":
                    earned = user_stats["image_count"] >= target
                elif achievement_type == "total_score":
                    earned = user_stats["total_score"] >= target
                
                # Rating achievements
                elif achievement_type == "rate_images":
                    rating_count = await self.get_user_stat(user_id, "ratings_given")
                    earned = rating_count >= target
                
                # Streak achievements
                elif achievement_type == "quest_streak":
                    current_streak = await self.get_user_streak(user_id, "quest_streak")
                    earned = current_streak >= target
                elif achievement_type == "post_streak":
                    current_streak = await self.get_user_streak(user_id, "post_streak")
                    earned = current_streak >= target
                
                # Quest completion achievements
                elif achievement_type == "quests_completed":
                    completed_count = self.user_quests_collection.count_documents({
                        "user_id": str(user_id),
                        "completed": True
                    })
                    earned = completed_count >= target
                
                # Viral/Likes achievements
                elif achievement_type == "viral_image":
                    # Check if user has any image with at least target likes
                    max_likes = await self.get_user_stat(user_id, "max_likes_on_image")
                    earned = max_likes >= target
                elif achievement_type == "total_likes":
                    total_likes = await self.get_user_stat(user_id, "total_likes_received")
                    earned = total_likes >= target
                
                # Community achievements
                elif achievement_type == "likes_given":
                    likes_given = await self.get_user_stat(user_id, "likes_given")
                    earned = likes_given >= target
                elif achievement_type == "diverse_users":
                    unique_users = await self.get_user_stat(user_id, "unique_users_reacted_to")
                    earned = unique_users >= target
                
                # Special achievements
                elif achievement_type == "early_posts":
                    early_posts = await self.get_user_stat(user_id, "early_morning_posts")
                    earned = early_posts >= target
                elif achievement_type == "late_posts":
                    late_posts = await self.get_user_stat(user_id, "late_night_posts")
                    earned = late_posts >= target
                elif achievement_type == "rapid_posts":
                    rapid_posts = await self.get_user_stat(user_id, "rapid_post_sessions")
                    earned = rapid_posts >= target
                elif achievement_type == "comebacks":
                    comebacks = await self.get_user_stat(user_id, "comeback_count")
                    earned = comebacks >= target
                elif achievement_type == "perfect_day":
                    perfect_days = await self.get_user_stat(user_id, "perfect_days")
                    earned = perfect_days >= target
                elif achievement_type == "quest_points":
                    total_points = await self.get_user_total_quest_points(user_id)
                    earned = total_points >= target
                elif achievement_type == "bookmarks":
                    bookmark_count = await self.get_user_stat(user_id, "bookmarks_created")
                    earned = bookmark_count >= target
                elif achievement_type == "competition_win":
                    # Weekly/Monthly/Yearly winner achievements
                    # These will be awarded manually by the competition system
                    earned = False
                
                if earned:
                    # Award achievement
                    achievement_record = {
                        "user_id": str(user_id),
                        "achievement_id": achievement["achievement_id"],
                        "name": achievement["name"],
                        "description": achievement["description"],
                        "reward_points": achievement["reward_points"],
                        "earned_at": datetime.now(),
                        "icon": achievement.get("icon", "🏆")
                    }
                    
                    self.user_achievements_collection.insert_one(achievement_record)
                    new_achievements.append(achievement_record)
            
            # Only log if achievements were actually awarded
            if len(new_achievements) > 0:
                logger.info(f"Awarded {len(new_achievements)} new achievements to user {user_id}")
            
            return new_achievements
            
        except Exception as e:
            logger.error(f"Error checking achievements: {e}")
            return []
    
    async def get_user_daily_quests(self, user_id: int) -> List[Dict]:
        """Get today's quests for a user"""
        try:
            today = datetime.now().date()
            quests = list(self.user_quests_collection.find({
                "user_id": str(user_id),
                "date": today.isoformat()
            }))
            return quests
        except Exception as e:
            logger.error(f"Error getting user daily quests: {e}")
            return []
    
    async def get_user_achievements(self, user_id: int) -> List[Dict]:
        """Get all achievements for a user"""
        try:
            achievements = list(self.user_achievements_collection.find({
                "user_id": str(user_id)
            }).sort("earned_at", -1))
            return achievements
        except Exception as e:
            logger.error(f"Error getting user achievements: {e}")
            return []
    
    async def create_event(self, name: str, description: str, start_date: datetime, end_date: datetime, created_by_id: int, created_by_name: str) -> Optional[str]:
        """Create a new image contest event"""
        try:
            if not self._ensure_connected():
                logger.error("Cannot create event: Database not connected")
                return None
            event = {
                "name": name,
                "description": description,
                "start_date": start_date,
                "end_date": end_date,
                "created_by_id": str(created_by_id),
                "created_by_name": created_by_name,
                "created_at": datetime.now(),
                "is_active": True,
                "contestants": [],
                "winner": None
            }
            
            result = self.events_collection.insert_one(event)
            event_id = str(result.inserted_id)
            
            logger.info(f"Created event '{name}' by {created_by_name}")
            return event_id
            
        except Exception as e:
            logger.error(f"Error creating event: {e}")
            return None
    
    async def get_active_events(self) -> List[Dict]:
        """Get all currently active events"""
        try:
            now = datetime.now()
            events = list(self.events_collection.find({
                "is_active": True,
                "start_date": {"$lte": now},
                "end_date": {"$gte": now}
            }))
            return events
        except Exception as e:
            logger.error(f"Error getting active events: {e}")
            return []
    
    async def add_event_contestant(self, message_id: str, user_id: int, user_name: str):
        """Add a contestant to active events when they post an image"""
        try:
            active_events = await self.get_active_events()
            
            for event in active_events:
                # Check if user is already a contestant
                if any(c["user_id"] == str(user_id) for c in event.get("contestants", [])):
                    continue
                
                # Add user as contestant
                self.events_collection.update_one(
                    {"_id": event["_id"]},
                    {
                        "$push": {
                            "contestants": {
                                "user_id": str(user_id),
                                "user_name": user_name,
                                "message_id": message_id,
                                "joined_at": datetime.now()
                            }
                        }
                    }
                )
                
                logger.info(f"Added {user_name} as contestant to event '{event['name']}'")
            
        except Exception as e:
            logger.error(f"Error adding event contestant: {e}")
    
    async def end_event(self, event_id: str, leaderboard_manager) -> Optional[Dict]:
        """End an event and determine the winner"""
        try:
            if not self._ensure_connected():
                logger.error("Cannot end event: Database not connected")
                return None
                
            from bson import ObjectId
            
            assert self.events_collection is not None  # Type assertion after connection check
            event = self.events_collection.find_one({"_id": ObjectId(event_id)})
            if not event:
                return None
            
            # Find the highest scoring image from contestants during the event period
            best_image = None
            best_score = float('-inf')
            
            for contestant in event.get("contestants", []):
                # Get the image message from leaderboard manager
                image_data = leaderboard_manager.images_collection.find_one({
                    "message_id": contestant["message_id"]
                })
                
                if image_data and image_data["score"] > best_score:
                    best_score = image_data["score"]
                    best_image = {
                        "user_id": contestant["user_id"],
                        "user_name": contestant["user_name"],
                        "message_id": contestant["message_id"],
                        "score": image_data["score"]
                    }
            
            # Update event with winner
            assert self.events_collection is not None  # Type assertion
            self.events_collection.update_one(
                {"_id": ObjectId(event_id)},
                {
                    "$set": {
                        "is_active": False,
                        "ended_at": datetime.now(),
                        "winner": best_image
                    }
                }
            )
            
            logger.info(f"Ended event '{event['name']}' with winner: {best_image['user_name'] if best_image else 'None'}")
            return {"event": event, "winner": best_image}
            
        except Exception as e:
            logger.error(f"Error ending event: {e}")
            return None
    
    async def update_user_stat(self, user_id: int, stat_type: str, count: int = 1):
        """Update user statistics for quest tracking"""
        try:
            self.user_stats_collection.update_one(
                {"user_id": str(user_id)},
                {
                    "$inc": {stat_type: count},
                    "$set": {"last_updated": datetime.now()}
                },
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error updating user stat: {e}")
    
    async def get_user_stat(self, user_id: int, stat_type: str) -> int:
        """Get a specific user statistic"""
        try:
            # Project only the field we need for efficiency
            doc = self.user_stats_collection.find_one(
                {"user_id": str(user_id)},
                {stat_type: 1, "_id": 0}
            )
            if doc:
                return doc.get(stat_type, 0)
            return 0
        except Exception as e:
            logger.error(f"Error getting user stat: {e}")
            return 0
    
    async def award_competition_achievement(self, user_id: int, user_name: str, competition_type: str):
        """Award a competition achievement to a user"""
        try:
            achievement_id = f"winner_{competition_type}"
            
            # Check if user already has this achievement
            existing = self.user_achievements_collection.find_one({
                "user_id": str(user_id),
                "achievement_id": achievement_id
            })
            
            if existing:
                return None  # Already has the achievement
            
            # Get the achievement details
            achievement = self.achievements_collection.find_one({"achievement_id": achievement_id})
            if not achievement:
                return None
            
            # Award the achievement
            achievement_record = {
                "user_id": str(user_id),
                "achievement_id": achievement_id,
                "name": achievement["name"],
                "description": achievement["description"],
                "reward_points": achievement["reward_points"],
                "earned_at": datetime.now(),
                "icon": achievement.get("icon", "🏆")
            }
            
            self.user_achievements_collection.insert_one(achievement_record)
            logger.info(f"Awarded {competition_type} achievement to user {user_id}")
            return achievement_record
            
        except Exception as e:
            logger.error(f"Error awarding competition achievement: {e}")
            return None
    
    # ==================== STREAK SYSTEM ====================
    
    async def update_post_streak(self, user_id: int):
        """Update posting streak for a user"""
        try:
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            
            # Get or create streak record
            streak_doc = self.user_streaks_collection.find_one({"user_id": str(user_id)})
            
            if not streak_doc:
                # First time posting
                streak_doc = {
                    "user_id": str(user_id),
                    "post_streak": 1,
                    "quest_streak": 0,
                    "last_post_date": today.isoformat(),
                    "last_quest_date": None,
                    "max_post_streak": 1,
                    "max_quest_streak": 0,
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                }
                self.user_streaks_collection.insert_one(streak_doc)
                logger.info(f"Started post streak for user {user_id}")
                return 1
            
            last_post_date = datetime.fromisoformat(streak_doc["last_post_date"]).date()
            
            if last_post_date == today:
                # Already posted today, no change
                return streak_doc["post_streak"]
            elif last_post_date == yesterday:
                # Continuing streak
                new_streak = streak_doc["post_streak"] + 1
                max_streak = max(new_streak, streak_doc.get("max_post_streak", 0))
                
                self.user_streaks_collection.update_one(
                    {"user_id": str(user_id)},
                    {
                        "$set": {
                            "post_streak": new_streak,
                            "last_post_date": today.isoformat(),
                            "max_post_streak": max_streak,
                            "updated_at": datetime.now()
                        }
                    }
                )
                logger.info(f"Extended post streak for user {user_id} to {new_streak} days")
                return new_streak
            else:
                # Streak broken, restart
                self.user_streaks_collection.update_one(
                    {"user_id": str(user_id)},
                    {
                        "$set": {
                            "post_streak": 1,
                            "last_post_date": today.isoformat(),
                            "updated_at": datetime.now()
                        }
                    }
                )
                logger.info(f"Post streak broken for user {user_id}, restarted at 1")
                return 1
                
        except Exception as e:
            logger.error(f"Error updating post streak: {e}")
            return 0
    
    async def _update_quest_streak(self, user_id: int):
        """Update quest completion streak for a user (internal method)"""
        try:
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            
            # Check if user completed any quest today
            today_quests = list(self.user_quests_collection.find({
                "user_id": str(user_id),
                "date": today.isoformat(),
                "completed": True
            }))
            
            if not today_quests:
                return  # No completed quests today
            
            # Get or create streak record
            streak_doc = self.user_streaks_collection.find_one({"user_id": str(user_id)})
            
            if not streak_doc:
                # First time completing quest
                streak_doc = {
                    "user_id": str(user_id),
                    "post_streak": 0,
                    "quest_streak": 1,
                    "last_post_date": None,
                    "last_quest_date": today.isoformat(),
                    "max_post_streak": 0,
                    "max_quest_streak": 1,
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                }
                self.user_streaks_collection.insert_one(streak_doc)
                logger.info(f"Started quest streak for user {user_id}")
                return 1
            
            # Check if already updated today
            last_quest_date_str = streak_doc.get("last_quest_date")
            if last_quest_date_str:
                last_quest_date = datetime.fromisoformat(last_quest_date_str).date()
                if last_quest_date == today:
                    return streak_doc["quest_streak"]  # Already counted today
                elif last_quest_date == yesterday:
                    # Continuing streak
                    new_streak = streak_doc["quest_streak"] + 1
                    max_streak = max(new_streak, streak_doc.get("max_quest_streak", 0))
                    
                    self.user_streaks_collection.update_one(
                        {"user_id": str(user_id)},
                        {
                            "$set": {
                                "quest_streak": new_streak,
                                "last_quest_date": today.isoformat(),
                                "max_quest_streak": max_streak,
                                "updated_at": datetime.now()
                            }
                        }
                    )
                    logger.info(f"Extended quest streak for user {user_id} to {new_streak} days")
                    return new_streak
                else:
                    # Streak broken, restart
                    self.user_streaks_collection.update_one(
                        {"user_id": str(user_id)},
                        {
                            "$set": {
                                "quest_streak": 1,
                                "last_quest_date": today.isoformat(),
                                "updated_at": datetime.now()
                            }
                        }
                    )
                    logger.info(f"Quest streak broken for user {user_id}, restarted at 1")
                    return 1
            else:
                # First quest completion
                self.user_streaks_collection.update_one(
                    {"user_id": str(user_id)},
                    {
                        "$set": {
                            "quest_streak": 1,
                            "last_quest_date": today.isoformat(),
                            "max_quest_streak": max(1, streak_doc.get("max_quest_streak", 0)),
                            "updated_at": datetime.now()
                        }
                    }
                )
                logger.info(f"Started quest streak for user {user_id}")
                return 1
                
        except Exception as e:
            logger.error(f"Error updating quest streak: {e}")
            return 0
    
    async def get_user_streak(self, user_id: int, streak_type: str) -> int:
        """Get current streak for a user"""
        try:
            streak_doc = self.user_streaks_collection.find_one({"user_id": str(user_id)})
            if not streak_doc:
                return 0
            return streak_doc.get(streak_type, 0)
        except Exception as e:
            logger.error(f"Error getting user streak: {e}")
            return 0
    
    async def get_user_streaks(self, user_id: int) -> Dict:
        """Get all streak information for a user"""
        try:
            streak_doc = self.user_streaks_collection.find_one({"user_id": str(user_id)})
            if not streak_doc:
                return {
                    "post_streak": 0,
                    "quest_streak": 0,
                    "max_post_streak": 0,
                    "max_quest_streak": 0,
                    "last_post_date": None,
                    "last_quest_date": None
                }
            
            return {
                "post_streak": streak_doc.get("post_streak", 0),
                "quest_streak": streak_doc.get("quest_streak", 0),
                "max_post_streak": streak_doc.get("max_post_streak", 0),
                "max_quest_streak": streak_doc.get("max_quest_streak", 0),
                "last_post_date": streak_doc.get("last_post_date"),
                "last_quest_date": streak_doc.get("last_quest_date")
            }
        except Exception as e:
            logger.error(f"Error getting user streaks: {e}")
            return {}
    
    async def check_and_break_streaks(self):
        """Check all users for broken streaks (called daily by scheduler)"""
        try:
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            
            # Find all users with active streaks
            active_streaks = list(self.user_streaks_collection.find({
                "$or": [
                    {"post_streak": {"$gt": 0}},
                    {"quest_streak": {"$gt": 0}}
                ]
            }))
            
            for streak_doc in active_streaks:
                user_id = streak_doc["user_id"]
                updates = {}
                
                # Check post streak
                if streak_doc.get("post_streak", 0) > 0:
                    last_post_date_str = streak_doc.get("last_post_date")
                    if last_post_date_str:
                        last_post_date = datetime.fromisoformat(last_post_date_str).date()
                        if last_post_date < yesterday:
                            updates["post_streak"] = 0
                            logger.info(f"Broke post streak for user {user_id}")
                
                # Check quest streak
                if streak_doc.get("quest_streak", 0) > 0:
                    last_quest_date_str = streak_doc.get("last_quest_date")
                    if last_quest_date_str:
                        last_quest_date = datetime.fromisoformat(last_quest_date_str).date()
                        if last_quest_date < yesterday:
                            updates["quest_streak"] = 0
                            logger.info(f"Broke quest streak for user {user_id}")
                
                # Apply updates if any
                if updates:
                    updates["updated_at"] = datetime.now()
                    self.user_streaks_collection.update_one(
                        {"user_id": user_id},
                        {"$set": updates}
                    )
                    
        except Exception as e:
            logger.error(f"Error checking and breaking streaks: {e}") 