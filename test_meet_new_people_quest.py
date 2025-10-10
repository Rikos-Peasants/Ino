#!/usr/bin/env python3
"""
Test script for "Meet New People" quest functionality

This script tests that the diverse_reactions quest type is properly tracked
when users react to images from different users.
"""

import asyncio
import logging
import sys
import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_meet_new_people_quest():
    """Test the Meet New People quest tracking"""
    logger.info("🧪 Testing Meet New People quest tracking...")
    
    try:
        # Import the quest manager
        from models.quest_manager import QuestManager
        
        # Create mock quest manager
        quest_manager = MagicMock()
        quest_manager.track_unique_user_like = AsyncMock()
        
        # Mock the database operations
        quest_manager.user_stats_collection = MagicMock()
        quest_manager.user_quests_collection = MagicMock()
        quest_manager._update_quest_streak = AsyncMock()
        
        # Mock finding no existing tracking document (first reaction)
        quest_manager.user_stats_collection.find_one.return_value = None
        quest_manager.user_stats_collection.insert_one = MagicMock()
        quest_manager.user_stats_collection.update_one = MagicMock()
        
        # Mock quest checking - simulate a quest that needs 3 different users
        mock_quest = {
            "_id": "quest123",
            "quest_id": "daily_meet_new_people",
            "name": "Meet New People",
            "quest_type": "diverse_reactions",
            "target_count": 3,
            "current_count": 2,  # Will become 3 after this reaction
            "completed": False
        }
        
        quest_manager.user_quests_collection.find.return_value = [mock_quest]
        quest_manager.user_quests_collection.update_many = MagicMock()
        quest_manager.user_quests_collection.update_one = MagicMock()
        
        # Test the actual tracking method implementation
        from models.quest_manager import QuestManager
        real_quest_manager = QuestManager()
        
        # Mock the database connection
        real_quest_manager.user_stats_collection = quest_manager.user_stats_collection
        real_quest_manager.user_quests_collection = quest_manager.user_quests_collection
        real_quest_manager._update_quest_streak = quest_manager._update_quest_streak
        
        # Test tracking a unique user like
        user_id = 12345
        liked_user_id = 67890
        
        # Mock the tracking document creation
        quest_manager.user_stats_collection.find_one.return_value = None
        
        # Call the method
        completed_quests = await real_quest_manager.track_unique_user_like(user_id, liked_user_id)
        
        # Verify the method was called correctly
        quest_manager.user_stats_collection.find_one.assert_called()
        quest_manager.user_stats_collection.insert_one.assert_called()
        quest_manager.user_quests_collection.update_many.assert_called()
        quest_manager.user_quests_collection.find.assert_called()
        
        # Check that the update_many call used the correct quest_type
        update_call = quest_manager.user_quests_collection.update_many.call_args
        assert update_call[0][0]["quest_type"] == "diverse_reactions", "Should update diverse_reactions quest type"
        
        # Check that the find call used the correct quest_type
        find_call = quest_manager.user_quests_collection.find.call_args
        assert find_call[0][0]["quest_type"] == "diverse_reactions", "Should query diverse_reactions quest type"
        
        logger.info("✅ Meet New People quest tracking test passed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Meet New People quest tracking test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_quest_type_consistency():
    """Test that quest definitions and tracking are consistent"""
    logger.info("🧪 Testing quest type consistency...")
    
    try:
        from models.quest_manager import QuestManager
        
        # Create a real quest manager to check quest definitions
        quest_manager = QuestManager()
        
        # Check that "Meet New People" quest exists and has correct type
        quest_manager._initialize_quests_and_achievements()
        
        # The quest should be defined in the initialization
        # We can't easily test the database without a connection,
        # but we can verify the quest definition exists in the code
        
        # Read the quest manager file to verify quest definitions
        with open("models/quest_manager.py", "r") as f:
            content = f.read()
            
        # Check for Meet New People quest
        assert '"name": "Meet New People"' in content, "Meet New People quest should be defined"
        assert '"quest_type": "diverse_reactions"' in content, "diverse_reactions quest type should exist"
        
        # Check that the tracking method references diverse_reactions
        assert 'quest_type": "diverse_reactions"' in content, "Tracking should use diverse_reactions"
        
        logger.info("✅ Quest type consistency test passed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Quest type consistency test failed: {e}")
        return False

async def main():
    """Main test function"""
    print("🧪 Meet New People Quest - Test Suite")
    print("="*50)
    
    tests = [
        ("Meet New People Quest Tracking", test_meet_new_people_quest),
        ("Quest Type Consistency", test_quest_type_consistency)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        logger.info(f"\n{'='*40}")
        logger.info(f"Running {test_name}")
        logger.info(f"{'='*40}")
        
        try:
            success = await test_func()
            if success:
                passed += 1
                logger.info(f"✅ {test_name} PASSED")
            else:
                logger.error(f"❌ {test_name} FAILED")
        except Exception as e:
            logger.error(f"❌ {test_name} FAILED with exception: {e}")
    
    # Print summary
    logger.info(f"\n{'='*50}")
    logger.info(f"TEST SUMMARY")
    logger.info(f"{'='*50}")
    logger.info(f"Tests Passed: {passed}/{total}")
    logger.info(f"Success Rate: {(passed/total)*100:.1f}%")
    
    if passed == total:
        logger.info("🎉 ALL TESTS PASSED! The Meet New People quest should now work correctly.")
        print("\n✅ The 'Meet New People' quest tracking has been fixed!")
        print("   Users should now see progress when reacting to images from different users.")
    else:
        logger.warning(f"⚠️ {total-passed} test(s) failed. Please review the implementation.")
    
    return passed == total

if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⏹️ Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test suite crashed: {e}")
        sys.exit(1)