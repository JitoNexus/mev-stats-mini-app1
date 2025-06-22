import pandas as pd
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class BroadcastSystem:
    def __init__(self):
        self.message_reads = {}
        self.button_clicks = {}
        
    def track_message_read(self, broadcast_id: str, user_id: int):
        """Track when a user reads a broadcast message."""
        try:
            if broadcast_id not in self.message_reads:
                self.message_reads[broadcast_id] = set()
            self.message_reads[broadcast_id].add(user_id)
            self._save_tracking_data()
            logger.info(f"Tracked message read: {broadcast_id} by user {user_id}")
        except Exception as e:
            logger.error(f"Error tracking message read: {e}")
    
    def track_button_click(self, broadcast_id: str, user_id: int):
        """Track when a user clicks a button in a broadcast message."""
        try:
            if broadcast_id not in self.button_clicks:
                self.button_clicks[broadcast_id] = set()
            self.button_clicks[broadcast_id].add(user_id)
            self._save_tracking_data()
            logger.info(f"Tracked button click: {broadcast_id} by user {user_id}")
        except Exception as e:
            logger.error(f"Error tracking button click: {e}")
    
    def _save_tracking_data(self):
        """Save tracking data to CSV files."""
        try:
            # Save message reads
            reads_data = []
            for broadcast_id, users in self.message_reads.items():
                for user_id in users:
                    reads_data.append({
                        'broadcast_id': broadcast_id,
                        'user_id': user_id,
                        'timestamp': datetime.now().isoformat()
                    })
            if reads_data:
                pd.DataFrame(reads_data).to_csv('message_reads.csv', index=False)
            
            # Save button clicks
            clicks_data = []
            for broadcast_id, users in self.button_clicks.items():
                for user_id in users:
                    clicks_data.append({
                        'broadcast_id': broadcast_id,
                        'user_id': user_id,
                        'timestamp': datetime.now().isoformat()
                    })
            if clicks_data:
                pd.DataFrame(clicks_data).to_csv('button_clicks.csv', index=False)
            
            logger.info("Tracking data saved successfully")
        except Exception as e:
            logger.error(f"Error saving tracking data: {e}")
    
    def get_message_reads(self, broadcast_id: str) -> set:
        """Get all users who have read a specific broadcast."""
        return self.message_reads.get(broadcast_id, set())
    
    def get_button_clicks(self, broadcast_id: str) -> set:
        """Get all users who have clicked buttons in a specific broadcast."""
        return self.button_clicks.get(broadcast_id, set()) 