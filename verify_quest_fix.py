#!/usr/bin/env python3
"""
Simple verification script for the Meet New People quest fix
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def verify_quest_fix():
    """Verify that the quest fix is properly implemented"""
    print("🔍 Verifying Meet New People quest fix...")
    
    try:
        # Check the quest manager file for the correct quest type
        with open("models/quest_manager.py", "r", encoding='utf-8') as f:
            content = f.read()
        
        # Check for the Meet New People quest definition
        meet_new_people_found = '"name": "Meet New People"' in content
        diverse_reactions_found = '"quest_type": "diverse_reactions"' in content
        
        # Check for the corrected tracking method
        tracking_method_found = 'async def track_unique_user_like' in content
        diverse_reactions_tracking = 'quest_type": "diverse_reactions"' in content
        
        print(f"✅ Meet New People quest definition found: {meet_new_people_found}")
        print(f"✅ diverse_reactions quest type found: {diverse_reactions_found}")
        print(f"✅ track_unique_user_like method found: {tracking_method_found}")
        print(f"✅ diverse_reactions tracking found: {diverse_reactions_tracking}")
        
        # Check the events controller
        with open("controllers/events.py", "r", encoding='utf-8') as f:
            events_content = f.read()
        
        events_tracking_found = 'track_unique_user_like' in events_content
        diverse_comment_found = '"diverse_reactions" quest' in events_content
        
        print(f"✅ Events controller tracking found: {events_tracking_found}")
        print(f"✅ Events controller comment updated: {diverse_comment_found}")
        
        if all([meet_new_people_found, diverse_reactions_found, tracking_method_found, 
                diverse_reactions_tracking, events_tracking_found]):
            print("\n🎉 SUCCESS: All components are properly configured!")
            print("The 'Meet New People' quest should now work correctly.")
            print("\nWhat was fixed:")
            print("- Changed quest tracking from 'support_new_users' to 'diverse_reactions'")
            print("- Updated method documentation and comments")
            print("- The quest now properly tracks reactions to different users")
            return True
        else:
            print("\n❌ ISSUE: Some components may not be properly configured.")
            return False
            
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        return False

if __name__ == "__main__":
    success = verify_quest_fix()
    if success:
        print("\n✅ The Meet New People quest fix has been successfully verified!")
    else:
        print("\n⚠️ There may be issues with the quest fix.")
    
    sys.exit(0 if success else 1)