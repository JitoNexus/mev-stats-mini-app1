import logging
import csv
import asyncio
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
import pandas as pd
from pathlib import Path
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for
import json
from werkzeug.utils import secure_filename
import os
from telegram.ext import MessageHandler, filters, CallbackContext, Application
from typing import List, Optional, Dict, Any
import aiohttp

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Your bot token
BOT_TOKEN = "7593402599:AAFJTV2BW4yJQYtg4Q0RGYDiU23jk9Aev_o"

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4'}

class BroadcastSystem:
    def __init__(self):
        # Configure request with proper settings
        request = HTTPXRequest(
            connection_pool_size=8,
            connect_timeout=60.0,
            read_timeout=60.0,
            write_timeout=60.0,
            pool_timeout=60.0
        )
        self.bot = Bot(token=BOT_TOKEN, request=request)
        self.stats_file = "broadcast_stats.csv"
        self.users_file = "user_data.csv"
        self.interactions_file = "message_interactions.csv"
        self._init_stats_file()
        self._init_interactions_file()
        self.message_queue = []
        self.is_broadcasting = False
        self.broadcast_task = None
        self.message_reads = {}
        self.button_clicks = {}
        self.broadcast_lock = asyncio.Lock()
        self.user_states = {}
        self.load_user_states()

    def _init_stats_file(self):
        if not Path(self.stats_file).exists():
            with open(self.stats_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['date', 'message_id', 'total_users', 'sent', 'seen', 'failed'])

    def _init_interactions_file(self):
        if not Path(self.interactions_file).exists():
            with open(self.interactions_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['message_id', 'user_id', 'read', 'button_clicks', 'timestamp'])

    async def load_users(self):
        try:
            df = pd.read_csv(self.users_file)
            return df['user_id'].tolist()
        except Exception as e:
            logger.error(f"Error loading users: {e}")
            return []

    async def broadcast_message(self, user_ids: List[int], message: str, parse_mode: Optional[str] = None) -> Dict[str, Any]:
        """Broadcast a message to multiple users."""
        results = {
            'successful': [],
            'failed': []
        }
        
        async with self.broadcast_lock:
            for user_id in user_ids:
                try:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=parse_mode
                    )
                    results['successful'].append(user_id)
                except TelegramError as e:
                    results['failed'].append({
                        'user_id': user_id,
                        'error': str(e)
                    })
                await asyncio.sleep(0.05)  # Rate limiting
        
        return results

    def load_user_states(self):
        """Load user states from file."""
        try:
            if os.path.exists('user_states.json'):
                with open('user_states.json', 'r') as f:
                    self.user_states = json.load(f)
        except Exception as e:
            logging.error(f"Error loading user states: {e}")
            self.user_states = {}

    def save_user_states(self):
        """Save user states to file."""
        try:
            with open('user_states.json', 'w') as f:
                json.dump(self.user_states, f)
        except Exception as e:
            logging.error(f"Error saving user states: {e}")

    async def update_user_state(self, user_id: int, state: Dict[str, Any]):
        """Update state for a specific user."""
        self.user_states[str(user_id)] = {
            'state': state,
            'last_updated': datetime.now().isoformat()
        }
        self.save_user_states()

    async def get_user_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get state for a specific user."""
        return self.user_states.get(str(user_id), {}).get('state')

    async def send_broadcast(self, message_text, buttons=None, image_url=None):
        users = await self.load_users()
        sent_count = 0
        failed_count = 0
        broadcast_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Prepare keyboard if buttons provided
        reply_markup = None
        if buttons:
            keyboard = []
            for button_row in buttons:
                row = []
                for button in button_row:
                    if len(button) == 2:
                        text, url = button
                        row.append(InlineKeyboardButton(
                            text=text,
                            url=url
                        ))
                if row:
                    keyboard.append(row)
            if keyboard:
                reply_markup = InlineKeyboardMarkup(keyboard)

        for user_id in users:
            try:
                sent_message = None
                try:
                    # First attempt with HTML parsing
                    if image_url:
                        if image_url.endswith(('.gif', '.mp4')):
                            sent_message = await self.bot.send_animation(
                                chat_id=user_id,
                                animation=image_url,
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                        else:
                            sent_message = await self.bot.send_photo(
                                chat_id=user_id,
                                photo=image_url,
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                    else:
                        sent_message = await self.bot.send_message(
                            chat_id=user_id,
                            text=message_text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                except TelegramError as html_error:
                    if "can't parse entities" in str(html_error).lower():
                        # Fallback to plain text if HTML parsing fails
                        if image_url:
                            if image_url.endswith(('.gif', '.mp4')):
                                sent_message = await self.bot.send_animation(
                                    chat_id=user_id,
                                    animation=image_url,
                                    caption=message_text,
                                    reply_markup=reply_markup
                                )
                            else:
                                sent_message = await self.bot.send_photo(
                                    chat_id=user_id,
                                    photo=image_url,
                                    caption=message_text,
                                    reply_markup=reply_markup
                                )
                        else:
                            sent_message = await self.bot.send_message(
                                chat_id=user_id,
                                text=message_text,
                                reply_markup=reply_markup
                            )
                    else:
                        raise html_error
                
                # Store the Telegram message ID mapping
                with open('message_mapping.csv', 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([broadcast_id, sent_message.message_id, user_id])
                    
                sent_count += 1
                await asyncio.sleep(0.05)  # Rate limiting
            except TelegramError as e:
                error_type = type(e).__name__
                error_details = str(e)
                logger.error(f"Failed to send to {user_id}: {error_type} - {error_details}")
                with open('failed_messages.log', 'a') as f:
                    f.write(f"{datetime.now()}: User {user_id} - {error_type} - {error_details}\n")
                failed_count += 1

        self._save_stats(broadcast_id, len(users), sent_count, 0, failed_count)
        return broadcast_id

    def _save_stats(self, message_id, total_users, sent, seen, failed):
        with open(self.stats_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                message_id, 
                total_users, 
                sent, 
                seen, 
                failed
            ])

    def get_stats(self, days=7):
        try:
            # Read broadcast stats
            df = pd.read_csv(self.stats_file)
            df['date'] = pd.to_datetime(df['date'], format='%Y-%m-%d %H:%M:%S')
            recent_stats = df.tail(days)
            
            # Read interaction stats
            interactions_df = pd.read_csv(self.interactions_file)
            
            # Convert to records and enhance with interaction data
            stats_records = []
            for record in recent_stats.to_dict('records'):
                message_id = record['message_id']
                message_interactions = interactions_df[interactions_df['message_id'] == message_id]
                
                record['total_reads'] = len(message_interactions[message_interactions['read'] == True])
                record['total_clicks'] = len(message_interactions[message_interactions['button_clicks'] > 0])
                stats_records.append(record)
                
            return stats_records
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return []

    def get_user_count(self):
        try:
            df = pd.read_csv(self.users_file)
            return len(df)
        except Exception as e:
            logger.error(f"Error counting users: {e}")
            return 0

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

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = 'your-secret-key'
broadcaster = BroadcastSystem()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    stats = broadcaster.get_stats()
    user_count = broadcaster.get_user_count()
    return render_template('dashboard.html', stats=stats, user_count=user_count)

@app.route('/send_message', methods=['POST'])
def send_message():
    try:
        if not request.form.get('message'):
            return jsonify({'success': False, 'error': 'Message is required'}), 400
            
        message = request.form.get('message')
        file = request.files.get('image')
        buttons = json.loads(request.form.get('buttons', '[]'))
        
        image_path = None
        if file and allowed_file(file.filename):
            try:
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                image_path = filepath
            except Exception as e:
                logger.error(f"Failed to save image: {str(e)}")
                return jsonify({'success': False, 'error': 'Failed to process image'}), 500

        # Run the async broadcast in the event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            message_id = loop.run_until_complete(broadcaster.send_broadcast(
                message_text=message,
                buttons=buttons,
                image_url=image_path
            ))
        finally:
            loop.close()
        
        if not message_id:
            return jsonify({'success': False, 'error': 'Failed to send broadcast'}), 500
            
        return jsonify({'success': True, 'message_id': message_id}), 200
    except json.JSONDecodeError:
        return jsonify({'success': False, 'error': 'Invalid button format'}), 400
    except Exception as e:
        logger.error(f"Error in send_message: {str(e)}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/stats')
def get_stats():
    days = request.args.get('days', 7, type=int)
    stats = broadcaster.get_stats(days)
    return jsonify(stats)

async def message_read_handler(update: Update, context: CallbackContext):
    message = update.message
    if message and hasattr(message, 'message_id'):
        broadcaster.track_message_read(str(message.message_id), update.effective_user.id)

if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    
    app.run(debug=True, port=5000)