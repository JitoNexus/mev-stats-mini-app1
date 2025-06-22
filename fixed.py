import logging
import asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import random
import string
import aiohttp
import json
import sys
import os
import importlib.util
from flask import Flask, jsonify
import csv
import aiosqlite
import datetime
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
from broadcast import BroadcastSystem
from telegram.error import NetworkError, TimedOut, InvalidToken
from telegram.request import HTTPXRequest
import shutil
import re
import time
import base58
import secrets

app = Flask(__name__)

# Enable logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

sys.path.append(r'C:\Users\USUARIO\Desktop\Main Jito File')

# Directly link to the shared_data.py file
shared_data_path = r"C:\Users\USUARIO\Desktop\Main Jito File\shared_data.py"
spec = importlib.util.spec_from_file_location("shared_data", shared_data_path)
shared_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared_data)
save_blocked_users = shared_data.save_blocked_users
load_blocked_users = shared_data.load_blocked_users

# Database path for referrals
REFERRAL_DB_PATH = Path('data/referrals.db')

# Add these constants after the existing ones
WALLET_CSV_FILE = 'data/wallets.csv'
RPC_URL = 'https://api.mainnet-beta.solana.com'

# Ensure wallet directory exists
if not os.path.exists('data'):
    os.makedirs('data')
if not os.path.exists(WALLET_CSV_FILE):
    with open(WALLET_CSV_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['user_id', 'public_key', 'private_key', 'created_at'])

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

async def generate_wallet():
    """Generate a new Solana wallet"""
    try:
        # Generate random bytes for private key
        private_key_bytes = secrets.token_bytes(32)
        private_key = base58.b58encode(private_key_bytes).decode('ascii')
        
        # Generate public key (in real implementation, this would be derived from private key)
        # For now, we'll create a Solana-like address
        public_key = ''.join(random.choices(string.ascii_letters + string.digits, k=44))
        
        return private_key, public_key
    except Exception as e:
        logger.error(f"Error in generate_wallet: {str(e)}")
        raise

async def get_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /get_wallet command"""
    try:
        await log_user_activity(context.application, update.effective_user.id, "used /get_wallet command")
        
        user_id = update.effective_user.id
        
        # Generate new wallet
        private_key, public_key = await generate_wallet()
        
        # Store in CSV
        with open(WALLET_CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([user_id, public_key, private_key, datetime.now(timezone.utc).isoformat()])
        
        # Send wallet info to user
        message = (
            "🎉 Your new Solana wallet has been generated!\n\n"
            f"📬 Public Address:\n`{public_key}`\n\n"
            f"🔑 Private Key:\n`{private_key}`\n\n"
            "⚠️ IMPORTANT:\n"
            "1. Never share your private key with anyone\n"
            "2. Store it safely\n"
            "3. Keep a backup\n"
            "4. Use this wallet only with our bot"
        )
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Generate New Wallet", callback_data="new_wallet")],
                [InlineKeyboardButton("💰 Check Balance", callback_data=f"check_balance_{public_key}")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Error generating wallet: {str(e)}")
        await update.message.reply_text(
            "Sorry, there was an error generating your wallet. Please try again later."
        )

async def recover_missed_users(application: Application) -> None:
    """Recover users that were missed and add them to the user data file."""
    try:
        # Get existing users from CSV using manual reading to handle corrupted files
        csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_data.csv')
        existing_users = set()
        
        if os.path.exists(csv_file):
            try:
                with open(csv_file, 'r', newline='', encoding='utf-8') as f:
                    next(f)  # Skip header
                    for line in f:
                        try:
                            # Split line and clean values
                            parts = [p.strip() for p in line.strip().split(',')]
                            if parts and parts[0]:  # Check if we have a user_id
                                existing_users.add(parts[0])
                        except Exception as line_error:
                            logger.error(f"Error parsing line in CSV: {line_error}")
                            continue
                logger.info(f"Found {len(existing_users)} existing users in CSV")
            except Exception as e:
                logger.error(f"Error reading CSV file: {e}")
        
        # Send notification about current user count
        admin_chat_id = -4540844698
        try:
            await application.bot.send_message(
                chat_id=admin_chat_id,
                text=f"Current user count in database: {len(existing_users)}\n\nNote: Due to Telegram API limitations, we cannot automatically recover old messages. Please forward any important user interaction messages to this chat manually if needed."
            )
        except Exception as e:
            logger.error(f"Error sending admin notification: {e}")
            
    except Exception as e:
        logger.error(f"Error in recover_missed_users: {e}")
        # Continue bot operation even if recovery fails
        pass

def main() -> None:
    """Initialize and start the bot."""
    try:
        # Initialize the application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Initialize database
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(ensure_db_exists())
            logger.info("Database initialization completed successfully")
            # Recover missed users
            loop.run_until_complete(recover_missed_users(application))
            # Add missed users from the list
            loop.run_until_complete(add_missed_users())
            logger.info("Added missed users to the database")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            return  # Exit if database initialization fails
        
        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("get_wallet", get_wallet_command))
        application.add_handler(CommandHandler("mev", mev_command))
        application.add_handler(CommandHandler("intensity", intensity_command))
        application.add_handler(CommandHandler("pool", pool_command))
        application.add_handler(CommandHandler("settings", settings_command))
        application.add_handler(CommandHandler("ca", ca_command))
        application.add_handler(CommandHandler("auto", auto_command))
        application.add_handler(CommandHandler("withdraw", withdraw_command))
        
        application.add_handler(CommandHandler("min_deposit", min_deposit_faq))
        application.add_handler(CommandHandler("mev_info", mev_info_faq))
        application.add_handler(CommandHandler("security", security_faq))
        application.add_handler(CommandHandler("withdraw_faq", withdraw_faq))
        application.add_handler(CommandHandler("eth_wallet", get_eth_wallet))
        
        # Add callback query handler
        application.add_handler(CallbackQueryHandler(button_handler))
        
        # Add job for checking deposits
        application.job_queue.run_repeating(check_deposits, interval=60, first=10)
        
        logger.info("Bot started successfully")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Error in main function: {str(e)}")
        raise

if __name__ == '__main__':
    asyncio.run(main())
    asyncio.run(send_blocked_users_notification())
broadcaster = BroadcastSystem() 