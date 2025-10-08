#!/usr/bin/env python3
"""
Script to fix the MongoDB index issue for user_quest_stats collection.
This drops the old incorrect index and allows the bot to create the correct one.
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def fix_index():
    """Drop the old incorrect index from user_quest_stats collection"""
    
    # Get MongoDB connection string from environment
    mongo_uri = os.getenv('MONGO_URI')
    if not mongo_uri:
        print("[ERROR] MONGO_URI not found in .env file")
        return False
    
    try:
        # Connect to MongoDB
        print("[INFO] Connecting to MongoDB...")
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        
        # Test connection
        client.admin.command('ismaster')
        print("[SUCCESS] Connected to MongoDB")
        
        # Get the database
        db = client['Riko']
        collection = db['user_quest_stats']
        
        # Get current indexes
        print("\n[INFO] Current indexes:")
        indexes = collection.index_information()
        for index_name, index_info in indexes.items():
            print(f"  - {index_name}: {index_info}")
        
        # Drop the old incorrect index if it exists
        if 'user_id_1' in indexes:
            print("\n[ACTION] Dropping old incorrect index 'user_id_1'...")
            collection.drop_index('user_id_1')
            print("[SUCCESS] Successfully dropped old index!")
        else:
            print("\n[WARNING] Old index 'user_id_1' not found (may have been already dropped)")
        
        # Optional: Clear the collection to start fresh
        print("\n[PROMPT] Do you want to clear all tracking data? (y/n): ", end='')
        response = input().strip().lower()
        
        if response == 'y':
            doc_count = collection.count_documents({})
            print(f"[ACTION] Clearing {doc_count} documents from user_quest_stats...")
            result = collection.delete_many({})
            print(f"[SUCCESS] Cleared {result.deleted_count} documents")
        else:
            print("[INFO] Skipping data clear")
        
        # Show final indexes
        print("\n[INFO] Final indexes:")
        indexes = collection.index_information()
        for index_name, index_info in indexes.items():
            print(f"  - {index_name}: {index_info}")
        
        print("\n[SUCCESS] Index fix complete!")
        print("[INFO] Now restart the bot to create the new correct index")
        
        client.close()
        return True
        
    except Exception as e:
        print(f"[ERROR] {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("MongoDB Index Fix Script")
    print("=" * 60)
    print("\nThis script will fix the user_quest_stats index issue")
    print("that's preventing the Channel Explorer quest from working.\n")
    
    success = fix_index()
    
    if success:
        print("\n" + "=" * 60)
        print("[SUCCESS] The index has been fixed.")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("[FAILED] Please check the error above.")
        print("=" * 60)

