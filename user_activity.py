import logging
import os
import csv
from datetime import datetime

logger = logging.getLogger(__name__)

async def store_new_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    try:
        csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_data.csv')
        logger.info(f"Using CSV file at: {csv_file}")
        
        # Create file if it doesn't exist
        if not os.path.exists(csv_file):
            with open(csv_file, 'w', encoding='utf-8', newline='') as f:
                f.write("user_id,username,first_name,last_name\n")
        
        # Check if user exists
        with open(csv_file, 'r', encoding='utf-8') as file:
            if any(str(user_id) in line for line in file):
                return False  # User already exists

        # Store new user
        with open(csv_file, 'a', encoding='utf-8', newline='') as file:
            file.write(f"{user_id},{username or ''},{first_name or ''},{last_name or ''}\n")
            
        logger.info(f"Successfully stored new user: {user_id} ({username})")
        return True
    except Exception as e:
        logger.error(f"Error storing new user {user_id}: {str(e)}")
        return False

async def log_user_activity(application, user_id, activity):
    """Log user activity and store new users."""
    admin_chat_id = -4540844698
    try:
        # Get user info
        user = await application.bot.get_chat(user_id)
        username = user.username if user.username else user.first_name
        
        # Store user in CSV
        await store_new_user(user_id, username)
        
        # Send log message
        message = f"User {username} ({user_id}) {activity}"
        await application.bot.send_message(chat_id=admin_chat_id, text=message)
        
    except Exception as e:
        logger.error(f"Failed to log user activity: {e}") 