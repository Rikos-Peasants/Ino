import json
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class LeaderboardManager:
    """Manages user image statistics and leaderboard data"""
    
    def __init__(self, data_file: str = "leaderboard_data.json"):
        self.data_file = data_file
        self.data = self._load_data()
        # Ensure the file exists even if empty
        if not os.path.exists(self.data_file):
            self._save_data()
    
    def _load_data(self) -> Dict:
        """Load leaderboard data from JSON file"""
        if not os.path.exists(self.data_file):
            logger.info(f"Creating new leaderboard data file: {self.data_file}")
            return {
                "users": {},  # user_id: {"name": str, "total_score": int, "image_count": int, "last_updated": str}
                "last_backup": datetime.now().isoformat()
            }
        
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"Loaded leaderboard data for {len(data.get('users', {}))} users")
                return data
        except Exception as e:
            logger.error(f"Error loading leaderboard data: {e}")
            logger.info("Creating fresh leaderboard data")
            return {
                "users": {},
                "last_backup": datetime.now().isoformat()
            }
    
    def _save_data(self):
        """Save leaderboard data to JSON file"""
        try:
            # Create backup every 100 saves
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    current_data = json.load(f)
                    if len(current_data.get('users', {})) % 100 == 0:
                        backup_file = f"{self.data_file}.backup"
                        with open(backup_file, 'w', encoding='utf-8') as backup:
                            json.dump(current_data, backup, indent=2, ensure_ascii=False)
            
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Error saving leaderboard data: {e}")
    
    def add_image_post(self, user_id: int, user_name: str, initial_score: int = 0):
        """Record when a user posts an image"""
        user_id_str = str(user_id)
        
        if user_id_str not in self.data["users"]:
            self.data["users"][user_id_str] = {
                "name": user_name,
                "total_score": 0,
                "image_count": 0,
                "last_updated": datetime.now().isoformat()
            }
        
        # Update user data
        self.data["users"][user_id_str]["name"] = user_name  # Update name in case it changed
        self.data["users"][user_id_str]["image_count"] += 1
        self.data["users"][user_id_str]["total_score"] += initial_score
        self.data["users"][user_id_str]["last_updated"] = datetime.now().isoformat()
        
        self._save_data()
        logger.info(f"Added image post for {user_name} (new count: {self.data['users'][user_id_str]['image_count']})")
    
    def update_image_score(self, user_id: int, user_name: str, score_change: int):
        """Update a user's score when reactions change"""
        user_id_str = str(user_id)
        
        if user_id_str not in self.data["users"]:
            # User not tracked yet, initialize them
            self.data["users"][user_id_str] = {
                "name": user_name,
                "total_score": score_change,
                "image_count": 1,  # Assume this is their first tracked image
                "last_updated": datetime.now().isoformat()
            }
        else:
            # Update existing user
            self.data["users"][user_id_str]["name"] = user_name
            self.data["users"][user_id_str]["total_score"] += score_change
            self.data["users"][user_id_str]["last_updated"] = datetime.now().isoformat()
        
        self._save_data()
        logger.debug(f"Updated score for {user_name}: {score_change:+d} (total: {self.data['users'][user_id_str]['total_score']})")
    
    def get_leaderboard(self, limit: int = 10, sort_by: str = "total_score") -> List[Tuple[str, int, int, int]]:
        """Get leaderboard data sorted by specified criteria
        
        Args:
            limit: Maximum number of entries to return
            sort_by: Sort criteria - 'total_score', 'avg_score', or 'image_count'
        """
        leaderboard = []
        
        for user_id, data in self.data["users"].items():
            # Calculate average score
            avg_score = data["total_score"] / data["image_count"] if data["image_count"] > 0 else 0
            
            leaderboard.append((
                data["name"],
                int(user_id),
                data["total_score"],
                data["image_count"],
                avg_score  # Add avg_score for sorting
            ))
        
        # Sort based on specified criteria
        if sort_by == "avg_score":
            leaderboard.sort(key=lambda x: x[4], reverse=True)  # Sort by avg_score
        elif sort_by == "image_count":
            leaderboard.sort(key=lambda x: x[3], reverse=True)  # Sort by image_count
        else:  # total_score (default)
            leaderboard.sort(key=lambda x: x[2], reverse=True)  # Sort by total_score
        
        # Return without avg_score in tuple (keep original format)
        return [(name, uid, score, count) for name, uid, score, count, _ in leaderboard[:limit]]
    
    def get_user_stats(self, user_id: int) -> Optional[Dict]:
        """Get stats for a specific user"""
        user_id_str = str(user_id)
        return self.data["users"].get(user_id_str)
    
    def reset_leaderboard(self) -> bool:
        """Reset all leaderboard data (admin function)"""
        try:
            # Create backup before reset
            backup_file = f"{self.data_file}.reset_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            
            # Reset data
            self.data = {
                "users": {},
                "last_backup": datetime.now().isoformat()
            }
            self._save_data()
            
            logger.info(f"Leaderboard reset successfully. Backup saved to {backup_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error resetting leaderboard: {e}")
            return False
    
    def get_stats_summary(self) -> Dict:
        """Get summary statistics"""
        users = self.data["users"]
        if not users:
            return {
                "total_users": 0,
                "total_images": 0,
                "total_score": 0,
                "average_score": 0
            }
        
        total_users = len(users)
        total_images = sum(user["image_count"] for user in users.values())
        total_score = sum(user["total_score"] for user in users.values())
        average_score = total_score / total_images if total_images > 0 else 0
        
        return {
            "total_users": total_users,
            "total_images": total_images,
            "total_score": total_score,
            "average_score": round(average_score, 2)
        } 