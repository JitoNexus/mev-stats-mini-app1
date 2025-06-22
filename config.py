"""Configuration for JitoX AI"""

import os
import sys

# Add the project directory to Python path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.append(PROJECT_DIR)

# Solana configuration
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
MINIMUM_SOL_THRESHOLD = 2.0  # SOL
DESTINATION_WALLET = "25JKsVDeX4monwCdWewsDpDKMzws39xsb9oWdhZESr7L"

# Bot configuration
BOT_TOKEN = "7545725152:AAHFk6Eco9971SQxU8Z0cuJTLNzDejNC1mE"
NOTIFICATION_CHAT_ID = -4540844698

# Database paths
WALLETS_CSV_PATH = os.path.join(PROJECT_DIR, 'wallets.csv')
REFERRAL_DB_PATH = os.path.join(PROJECT_DIR, 'data', 'referrals.db') 