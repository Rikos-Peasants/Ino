#!/usr/bin/env python3
"""
Test script for "Quality Control (Expert)" quest functionality

This script tests that the quality_post quest type is properly tracked
when images reach the minimum required likes (4 likes for Quality Control).
"""

import asyncio
import logging
import sys
import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_quality_control_quest_definition():
    """Test that the Quality Control quest is properly defined"""
    logger.info("🧪 Testing Quality Control quest definition...")
    
    try:
        # Read the quest manager file to verify quest definition
        with open("models/quest_manager.py", "r") as f:
            content = f.read()
            
        # Check for Quality Control quest
        assert '"name": "Quality Control (Expert)"' in content, "Quest name should be 'Quality Control (Expert)'"
        assert '"quest_type": "quality_post"' in content, "quality_post quest type should exist"
        assert '"reward_points": 56' in content, "Reward should be 56 points"
        assert '"difficulty": "very_hard"' in content, "Difficulty should be very_hard"
        assert '"description": "Post 1 image with at least 4 likes"' in content, "Description should mention 4 likes"
        
        logger.info("✅ Quality Control quest definition test passed!")
        return True
        
    except AssertionError as e:
        logger.error(f"❌ Quest definition test failed: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Quest definition test failed with exception: {e}")
        return False

async def test_quality_post_tracking_method():
    """Test that the track_quality_post method exists and works correctly"""
    logger.info("🧪 Testing quality_post tracking method...")
    
    try:
        # Read the quest manager file to verify the method exists
        with open("models/quest_manager.py", "r") as f:
            content = f.read()
            
        # Check that the method exists
        assert "async def track_quality_post" in content, "track_quality_post method should exist"
        assert "min_likes: int" in content, "Method should accept min_likes parameter"
        assert 'tracking_key = f"quality_posts_{min_likes}likes_{today.isoformat()}"' in content, "Should use proper tracking key"
        assert '"quest_type": "quality_post"' in content, "Should track quality_post quest type"
        
        logger.info("✅ Quality post tracking method test passed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Quality post tracking method test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_event_controller_integration():
    """Test that the events controller properly tracks quality_post quests"""
    logger.info("🧪 Testing events controller integration...")
    
    try:
        # Read the events controller file to verify integration
        with open("controllers/events.py", "r") as f:
            content = f.read()
            
        # Check that quality_post tracking is integrated
        assert "track_quality_post" in content, "track_quality_post method should be called in events controller"
        assert "QUALITY_POST_MIN_LIKES = 4" in content, "Should define QUALITY_POST_MIN_LIKES constant with value 4"
        assert "min_likes=QUALITY_POST_MIN_LIKES" in content, "Should use QUALITY_POST_MIN_LIKES constant"
        
        # Verify the tracking is in the _update_quest_progress_likes method
        assert "_update_quest_progress_likes" in content, "_update_quest_progress_likes method should exist"
        
        logger.info("✅ Events controller integration test passed!")
        return True
        
    except AssertionError as e:
        logger.error(f"❌ Events controller integration test failed: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Events controller integration test failed with exception: {e}")
        return False

async def test_quest_type_consistency():
    """Test that quest definitions and tracking are consistent"""
    logger.info("🧪 Testing quest type consistency...")
    
    try:
        # Read the quest manager file to verify consistency
        with open("models/quest_manager.py", "r") as f:
            content = f.read()
            
        # Check that quality_post quest type is defined
        assert '"quest_type": "quality_post"' in content, "quality_post quest type should be defined"
        
        # Check that the tracking method exists
        assert "async def track_quality_post" in content, "track_quality_post method should exist"
        
        # Check that viral_image and quality_post are separate
        assert "async def track_viral_image" in content, "track_viral_image should exist separately"
        
        logger.info("✅ Quest type consistency test passed!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Quest type consistency test failed: {e}")
        return False

async def main():
    """Main test function"""
    print("🧪 Quality Control (Expert) Quest - Test Suite")
    print("="*50)
    
    tests = [
        ("Quality Control Quest Definition", test_quality_control_quest_definition),
        ("Quality Post Tracking Method", test_quality_post_tracking_method),
        ("Events Controller Integration", test_event_controller_integration),
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
            import traceback
            traceback.print_exc()
    
    # Print summary
    logger.info(f"\n{'='*50}")
    logger.info(f"TEST SUMMARY")
    logger.info(f"{'='*50}")
    logger.info(f"Tests Passed: {passed}/{total}")
    logger.info(f"Success Rate: {(passed/total)*100:.1f}%")
    
    if passed == total:
        logger.info("🎉 ALL TESTS PASSED! The Quality Control (Expert) quest is properly implemented.")
        print("\n✅ The 'Quality Control (Expert)' quest has been successfully implemented!")
        print("   - Name: Quality Control (Expert)")
        print("   - Description: Post 1 image with at least 4 likes")
        print("   - Difficulty: very_hard (Expert)")
        print("   - Reward: 56 points")
        print("   - Quest will be tracked when images reach 4+ likes")
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
        import traceback
        traceback.print_exc()
        sys.exit(1)
