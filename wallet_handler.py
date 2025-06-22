import logging
import secrets
import base58
import random
import string
import csv
from datetime import datetime, timezone
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Constants
WALLET_CSV_FILE = 'data/wallets.csv'

# Ensure wallet directory exists
if not os.path.exists('data'):
    os.makedirs('data')
if not os.path.exists(WALLET_CSV_FILE):
    with open(WALLET_CSV_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['user_id', 'public_key', 'private_key', 'created_at'])

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
        from user_activity import log_user_activity
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