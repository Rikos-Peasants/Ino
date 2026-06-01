import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from bson import ObjectId

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest
from models.art_challenge_manager import ArtChallengeManager
from models.art_random_events_manager import ArtRandomEventsManager
from tests.test_scam_image_manager_smoke import FakeDb, FakeCollection, FakeInsertResult

# Patch FakeCollection to preserve pre-existing _id keys and support update_many
def custom_insert_one(self, doc):
    if "sha256" in doc:
        for existing in self.docs:
            if existing.get("sha256") == doc["sha256"]:
                from pymongo.errors import DuplicateKeyError
                raise DuplicateKeyError("duplicate sha256")
    if "cooldown_key" in doc:
        for existing in self.docs:
            if existing.get("cooldown_key") == doc["cooldown_key"]:
                from pymongo.errors import DuplicateKeyError
                raise DuplicateKeyError("duplicate cooldown_key")
    stored = dict(doc)
    if "_id" not in stored:
        stored["_id"] = len(self.docs) + 1
    self.docs.append(stored)
    return FakeInsertResult(stored["_id"])

def custom_update_many(self, query, update, upsert=False):
    modified_count = 0
    for doc in self.docs:
        if self._matches(doc, query):
            doc.update(update.get("$set", {}))
            modified_count += 1
    # Create a wrapper class like FakeUpdateResult
    class FakeUpdateResultMany:
        def __init__(self, modified_count):
            self.modified_count = modified_count
            self.upserted_id = None
    return FakeUpdateResultMany(modified_count)

FakeCollection.insert_one = custom_insert_one
FakeCollection.update_many = custom_update_many

class TestArtChallengeRandomEvents(unittest.TestCase):
    def setUp(self):
        # Create a fresh fake DB for each test
        self.db = FakeDb()
        
        # Patch connect to prevent real MongoClient creation
        with patch.object(ArtChallengeManager, "_connect", lambda self: None), \
             patch.object(ArtRandomEventsManager, "_connect", lambda self: None):
             
            self.challenge_manager = ArtChallengeManager()
            self.challenge_manager.db = self.db
            self.challenge_manager.challenges_collection = self.db["art_challenges"]
            self.challenge_manager.submissions_collection = self.db["art_submissions"]
            self.challenge_manager.challenge_stats_collection = self.db["art_challenge_stats"]
            self.challenge_manager.users_collection = self.db["users"]
            self.challenge_manager.gemini_api_key = "fake_key"
            self.challenge_manager._ensure_connected = lambda: True
            
            self.events_manager = ArtRandomEventsManager()
            self.events_manager.db = self.db
            self.events_manager.buffs_collection = self.db["art_buffs"]
            self.events_manager.debuffs_collection = self.db["art_debuffs"]
            self.events_manager.events_collection = self.db["art_events"]
            self.events_manager._ensure_connected = lambda: True

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_verify_submission_appends_extra_instructions(self):
        # We want to test that verify_submission constructs verification_prompt containing:
        # 1. required_character
        # 2. fishy_active and fishy_required_item
        
        self.challenge_manager.download_image_bytes = AsyncMock(return_value=b"fake_bytes")
        self.challenge_manager.check_image_similarity = AsyncMock(return_value={"is_duplicate": False})
        
        # Mock genai.Client generate_content
        mock_response = MagicMock()
        mock_response.text = '{"verified": true, "confidence": 0.9, "reasoning": "Passes"}'
        
        with patch("google.genai.Client") as mock_client_cls, \
             patch("models.art_challenge_manager.extract_gemini_text", return_value='{"verified": true, "confidence": 0.9, "reasoning": "Passes"}'):
            
            # Setup genai.Client mock
            mock_client = MagicMock()
            mock_client.models.generate_content = MagicMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            
            challenge_data = {
                "challenge_id": "507f1f77bcf86cd799439011",
                "challenge_type": "tags",
                "required_tags": ["anime"],
                "fishy_active": True,
                "fishy_required_item": "rubber duck"
            }
            
            self.run_async(self.challenge_manager.verify_submission(
                challenge_data, 
                "http://fake.url/image.jpg", 
                required_character="Goku"
            ))
            
            # Assert generate_content was called and the prompt has Goku and rubber duck
            call_args = mock_client.models.generate_content.call_args
            contents = call_args[1]["contents"]
            parts = contents[0].parts
            prompt_text = parts[-1].text
            
            self.assertIn("Goku", prompt_text)
            self.assertIn("rubber duck", prompt_text)

    def test_submit_entry_applies_buffs_and_debuffs(self):
        # Set up an active challenge with valid end_time and state
        challenge_id = "507f1f77bcf86cd799439011"
        self.db["art_challenges"].insert_one({
            "_id": ObjectId(challenge_id),
            "challenge_id": challenge_id,
            "title": "Cool Art",
            "reward_points": 100,
            "active": True,
            "state": "active",
            "end_time": datetime.utcnow() + timedelta(days=1)
        })
        
        # Mock verify_submission to succeed
        self.challenge_manager.verify_submission = AsyncMock(return_value={
            "verified": True,
            "confidence": 0.95,
            "reasoning": "Incredible art!"
        })
        
        # Patch dynamic import of ArtRandomEventsManager
        with patch("models.art_random_events_manager.ArtRandomEventsManager") as mock_events_class, \
             patch("random.random", return_value=0.99):
             
            # Make the instantiated manager return our pre-configured events_manager
            mock_events_class.return_value = self.events_manager
            
            # A. Test buff multiplier with inos_blessing (one_shot=True, multiplier=2.0)
            self.events_manager.apply_buff(user_id=123, buff_key="inos_blessing")
            
            res = self.run_async(self.challenge_manager.submit_entry(
                challenge_id=challenge_id,
                user_id=123,
                image_url="http://url.com/1.jpg",
                message_id=456
            ))
            
            self.assertTrue(res.get("success", False))
            self.assertTrue(res["verified"])
            self.assertEqual(res["points_awarded"], 200) # 100 * 2.0
            
            # Verify one-shot buff got consumed (became active=False)
            buff = self.db["art_buffs"].find_one({"user_id": 123, "buff_key": "inos_blessing"})
            self.assertFalse(buff["active"])

            # B. Test debuff multiplier (Look of Disgust)
            self.db["art_submissions"].docs = []
            
            self.events_manager.apply_debuff(user_id=123, debuff_key="look_of_disgust") # Multiplier 0.5
            
            res = self.run_async(self.challenge_manager.submit_entry(
                challenge_id=challenge_id,
                user_id=123,
                image_url="http://url.com/2.jpg",
                message_id=457
            ))
            self.assertEqual(res["points_awarded"], 50) # 100 * 0.5

    def test_submit_entry_jinx_debuff(self):
        challenge_id = "507f1f77bcf86cd799439011"
        self.db["art_challenges"].insert_one({
            "_id": ObjectId(challenge_id),
            "challenge_id": challenge_id,
            "title": "Cool Art",
            "reward_points": 100,
            "active": True,
            "state": "active",
            "end_time": datetime.utcnow() + timedelta(days=1)
        })
        
        # Mock verify_submission to FAIL
        self.challenge_manager.verify_submission = AsyncMock(return_value={
            "verified": False,
            "confidence": 0.95,
            "reasoning": "Doesn't match required tags."
        })
        
        # Patch dynamic import of ArtRandomEventsManager
        with patch("models.art_random_events_manager.ArtRandomEventsManager") as mock_events_class, \
             patch("random.random", return_value=0.99):
             
            mock_events_class.return_value = self.events_manager
            
            # Apply 'The Jinx' debuff
            self.events_manager.apply_debuff(user_id=123, debuff_key="the_jinx")
            
            # Verify the Jinx is currently active and one_shot_on_fail
            debuff = self.db["art_debuffs"].find_one({"user_id": 123, "debuff_key": "the_jinx"})
            self.assertTrue(debuff["active"])
            self.assertTrue(debuff.get("one_shot_on_fail"))
            
            res = self.run_async(self.challenge_manager.submit_entry(
                challenge_id=challenge_id,
                user_id=123,
                image_url="http://url.com/fail.jpg",
                message_id=458
            ))
            
            self.assertTrue(res.get("success", False))
            # Points awarded should be -15 (Jinx penalty)
            self.assertEqual(res["points_awarded"], -15)
            
            # The Jinx debuff should be consumed (active=False)
            debuff = self.db["art_debuffs"].find_one({"user_id": 123, "debuff_key": "the_jinx"})
            self.assertFalse(debuff["active"])

    def test_submit_entry_character_commission_disqualification_and_resubmission(self):
        challenge_id = "507f1f77bcf86cd799439011"
        self.db["art_challenges"].insert_one({
            "_id": ObjectId(challenge_id),
            "challenge_id": challenge_id,
            "title": "Cool Art",
            "reward_points": 100,
            "active": True,
            "state": "active",
            "end_time": datetime.utcnow() + timedelta(days=1)
        })
        
        # A. First submission is verified, but random commission triggers (15% chance, we mock random to trigger it)
        self.challenge_manager.verify_submission = AsyncMock(return_value={
            "verified": True,
            "confidence": 0.95,
            "reasoning": "Excellent art!"
        })
        
        # Mock generate_character_commission to return Goku
        mock_commission = {
            "character_name": "Goku",
            "character_personality": "Energetic, eats a lot",
            "rating": 5,
            "comment": "Where am I?",
            "reaction": "Hi! I'm Goku!"
        }
        
        # Patch dynamic import of ArtRandomEventsManager
        with patch("models.art_random_events_manager.ArtRandomEventsManager") as mock_events_class, \
             patch("random.random", return_value=0.05), \
             patch.object(ArtRandomEventsManager, "generate_character_commission", AsyncMock(return_value=mock_commission)):
             
            mock_events_class.return_value = self.events_manager
            
            res = self.run_async(self.challenge_manager.submit_entry(
                challenge_id=challenge_id,
                user_id=123,
                image_url="http://url.com/commission_trigger.jpg",
                message_id=459
            ))
            
            self.assertTrue(res.get("success", False))
            # Submission must be DISQUALIFIED
            self.assertFalse(res["verified"])
            self.assertEqual(res["points_awarded"], 0)
            self.assertTrue(res["requires_resubmission"])
            self.assertEqual(res["character_commission"]["character_name"], "Goku")
            
            # Verify it's saved in the database
            sub = self.db["art_submissions"].find_one({"user_id": 123, "challenge_id": challenge_id})
            self.assertTrue(sub["requires_resubmission"])
            self.assertEqual(sub["character_commission"]["character_name"], "Goku")
            print(f"DEBUG A submission in DB: {sub}")

        # B. Second submission does NOT include Goku. verify_submission is called with required_character="Goku"
        # We mock verify_submission to fail Goku validation
        self.challenge_manager.verify_submission = AsyncMock(return_value={
            "verified": False,
            "confidence": 0.90,
            "reasoning": "Goku is missing from the artwork."
        })
        
        with patch("models.art_random_events_manager.ArtRandomEventsManager") as mock_events_class, \
             patch("random.random", return_value=0.99):
             
            mock_events_class.return_value = self.events_manager
            
            res2 = self.run_async(self.challenge_manager.submit_entry(
                challenge_id=challenge_id,
                user_id=123,
                image_url="http://url.com/no_goku.jpg",
                message_id=460
            ))
            
            self.assertTrue(res2.get("success", False))
            self.assertFalse(res2["verified"])
            # Ensure the required_character parameter is checked
            self.challenge_manager.verify_submission.assert_called_with(
                unittest.mock.ANY, "http://url.com/no_goku.jpg", required_character="Goku"
            )
            
            sub = self.db["art_submissions"].find_one({"user_id": 123, "challenge_id": challenge_id})
            print(f"DEBUG B submission in DB: {sub}")

        # C. Third submission successfully includes Goku!
        self.challenge_manager.verify_submission = AsyncMock(return_value={
            "verified": True,
            "confidence": 0.98,
            "reasoning": "Goku is clearly present eating ramen!"
        })
        
        with patch("models.art_random_events_manager.ArtRandomEventsManager") as mock_events_class, \
             patch("random.random", return_value=0.99):
             
            mock_events_class.return_value = self.events_manager
            
            res3 = self.run_async(self.challenge_manager.submit_entry(
                challenge_id=challenge_id,
                user_id=123,
                image_url="http://url.com/with_goku.jpg",
                message_id=461
            ))
            
            sub = self.db["art_submissions"].find_one({"user_id": 123, "challenge_id": challenge_id})
            print(f"DEBUG C submission in DB: {sub}")
            
            self.assertTrue(res3.get("success", False))
            self.assertTrue(res3["verified"])
            self.assertEqual(res3["points_awarded"], 100)
            self.assertEqual(res3["commission_completed"], "Goku")
            
            # Verify the commission state is cleared in database
            self.assertFalse(sub.get("requires_resubmission", False))

if __name__ == "__main__":
    unittest.main()
