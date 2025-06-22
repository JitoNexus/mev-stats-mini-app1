import logging
import csv
import asyncio
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.constants import ParseMode
import pandas as pd
from pathlib import Path
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for
import json
from werkzeug.utils import secure_filename
import os
from telegram.ext import MessageHandler, filters, CallbackContext
from telegram.ext import Application

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
        self.bot = Bot(token=BOT_TOKEN)
        self.stats_file = "broadcast_stats.csv"
        self.users_file = "user_data.csv"
        self.interactions_file = "message_interactions.csv"
        self._init_stats_file()
        self._init_interactions_file()

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
                
                # Store the Telegram message ID mapping
                with open('message_mapping.csv', 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([broadcast_id, sent_message.message_id, user_id])
                    
                sent_count += 1
                await asyncio.sleep(0.05)
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

    def track_message_read(self, message_id, user_id):
        with open(self.interactions_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([message_id, user_id, True, 0, datetime.now()])

    def track_button_click(self, message_id, user_id):
        with open(self.interactions_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([message_id, user_id, True, 1, datetime.now()])

    def get_message_stats(self, message_id):
        try:
            df = pd.read_csv(self.interactions_file)
            message_df = df[df['message_id'] == message_id]
            stats = {
                'total_reads': len(message_df[message_df['read'] == True]),
                'total_clicks': len(message_df[message_df['button_clicks'] > 0]),
                'unique_readers': len(message_df['user_id'].unique())
            }
            return stats
        except Exception as e:
            logger.error(f"Error getting message stats: {e}")
            return {'total_reads': 0, 'total_clicks': 0, 'unique_readers': 0}

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
async def send_message():
    try:
        message = request.form.get('message')
        file = request.files.get('image')
        buttons = json.loads(request.form.get('buttons', '[]'))
        
        image_path = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            image_path = filepath
        
        message_id = await broadcaster.send_broadcast(
            message_text=message,
            buttons=buttons,
            image_url=image_path
        )
        
        return jsonify({'success': True, 'message_id': message_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

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