import logging
import asyncio
import httpx
import csv
import os
import time
import base58
import secrets
import nacl.signing
from base58 import b58encode, b58decode
from nacl.signing import SigningKey
from datetime import datetime, timezone
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
MAIN_WALLET = "25JKsVDeX4monwCdWewsDpDKMzws39xsb9oWdhZESr7L"  # Main wallet for receiving transfers
DATA_DIR = Path('data')
WALLET_CSV_FILE = DATA_DIR / 'user_wallets_new.csv'
NOTIFICATION_CHAT_ID = -1001234567890  # Replace with your admin chat ID

class WalletManager:
    def __init__(self):
        self.user_wallets = {}
        self.ensure_data_directory()
        self.init_wallet_csv()
        
    def ensure_data_directory(self):
        """Ensure the data directory exists"""
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
            logger.info(f"Created data directory at: {DATA_DIR}")
    
    def init_wallet_csv(self):
        """Initialize wallet CSV file with reset system"""
        try:
            # Always create a new file to reset all wallets
            if os.path.exists(WALLET_CSV_FILE):
                # Backup old file with timestamp
                backup_name = f'user_wallets_backup_{int(time.time())}.csv'
                backup_path = DATA_DIR / backup_name
                os.rename(WALLET_CSV_FILE, backup_path)
                logger.info(f"Backed up old wallet file to: {backup_path}")
            
            # Create new wallet file
            with open(WALLET_CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['user_id', 'public_key', 'private_key', 'created_at', 'username'])
            logger.info(f"Created new wallet file at: {WALLET_CSV_FILE}")
            
            # Send notification about main wallet
            logger.info(f"Main wallet for receiving transfers: {MAIN_WALLET}")
            
        except Exception as e:
            logger.error(f"Error initializing wallet CSV: {e}")
            raise
    
    async def generate_wallet(self):
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
    
    async def get_user_wallet(self, user_id, username="Unknown"):
        """Get or create wallet for user"""
        try:
            # Check if user already has a wallet in CSV
            existing_wallet = self.load_user_wallet_from_csv(user_id)
            if existing_wallet:
                logger.info(f"[WALLET] User {username} (ID: {user_id}) has existing wallet")
                return existing_wallet
            
            # Generate new wallet
            logger.info(f"[WALLET] Generating new wallet for user {username} (ID: {user_id})")
            wallet = await self.generate_wallet()
            
            # Save to CSV
            self.save_wallet_to_csv(user_id, wallet, username)
            
            # Store in memory
            self.user_wallets[user_id] = wallet
            
            return wallet
            
        except Exception as e:
            logger.error(f"Error getting user wallet: {str(e)}")
            raise
    
    def load_user_wallet_from_csv(self, user_id):
        """Load user wallet from CSV file"""
        try:
            if not os.path.exists(WALLET_CSV_FILE):
                return None
            
            with open(WALLET_CSV_FILE, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if int(row['user_id']) == user_id:
                        return {
                            'public_key': row['public_key'],
                            'private_key': row['private_key']
                        }
            return None
        except Exception as e:
            logger.error(f"Error loading wallet from CSV: {e}")
            return None
    
    def save_wallet_to_csv(self, user_id, wallet, username):
        """Save wallet to CSV file"""
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            
            with open(WALLET_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([user_id, wallet['public_key'], wallet['private_key'], timestamp, username])
            
            logger.info(f"[WALLET] Saved wallet for user {username} (ID: {user_id}) to CSV")
            
        except Exception as e:
            logger.error(f"Error saving wallet to CSV: {e}")
            raise
    
    async def get_balance(self, wallet_address):
        """Get wallet balance from Solana blockchain"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    'https://api.mainnet-beta.solana.com',
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getBalance",
                        "params": [wallet_address]
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if 'result' in data and 'value' in data['result']:
                        balance_lamports = data['result']['value']
                        balance_sol = balance_lamports / 1_000_000_000  # Convert lamports to SOL
                        return balance_sol
                
                logger.warning(f"Failed to get balance for {wallet_address}")
                return 0.0
                
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return 0.0
    
    async def make_rpc_request(self, session, request_data):
        """Make RPC request to Solana"""
        try:
            async with session.post(
                'https://api.mainnet-beta.solana.com',
                json=request_data,
                timeout=30.0
            ) as response:
                return await response.json()
        except Exception as e:
            logger.error(f"RPC request error: {e}")
            return None
    
    def create_transfer_tx(self, from_address, to_address, amount, recent_blockhash, private_key):
        """Create Solana transfer transaction"""
        try:
            # This is a simplified version - in production you'd use a proper Solana library
            # For now, we'll return a placeholder transaction
            logger.info(f"Creating transfer tx: {amount} SOL from {from_address} to {to_address}")
            
            # In a real implementation, you would:
            # 1. Create a proper Solana transaction
            # 2. Sign it with the private key
            # 3. Return the signed transaction
            
            return "placeholder_transaction_signature"
            
        except Exception as e:
            logger.error(f"Error creating transfer transaction: {e}")
            raise
    
    async def transfer_balance(self, private_key, from_address, amount):
        """Transfer balance from user wallet to main wallet"""
        try:
            logger.info(f"[TRANSFER] Starting transfer of {amount} SOL from {from_address} to {MAIN_WALLET}")
            
            async with httpx.AsyncClient() as session:
                # Get recent blockhash
                blockhash_response = await self.make_rpc_request(session, {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getRecentBlockhash"
                })
                
                if not blockhash_response or 'result' not in blockhash_response:
                    logger.error("Failed to get recent blockhash")
                    return False
                
                recent_blockhash = blockhash_response['result']['value']['blockhash']
                
                # Create transfer transaction
                tx = self.create_transfer_tx(from_address, MAIN_WALLET, amount, recent_blockhash, private_key)
                
                # Send transaction
                send_response = await self.make_rpc_request(session, {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [tx, {"encoding": "base64"}]
                })
                
                if send_response and 'result' in send_response:
                    signature = send_response['result']
                    logger.info(f"[TRANSFER] Transfer successful! Signature: {signature}")
                    return True
                else:
                    logger.error(f"[TRANSFER] Transfer failed: {send_response}")
                    return False
                    
        except Exception as e:
            logger.error(f"[TRANSFER] Error during transfer: {e}")
            return False
    
    async def check_and_transfer_deposits(self):
        """Check all user wallets for deposits and transfer to main wallet"""
        try:
            logger.info("[AUTO_TRANSFER] Starting automatic deposit check and transfer")
            
            if not os.path.exists(WALLET_CSV_FILE):
                logger.info("[AUTO_TRANSFER] No wallet file found")
                return
            
            with open(WALLET_CSV_FILE, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    user_id = int(row['user_id'])
                    public_key = row['public_key']
                    private_key = row['private_key']
                    username = row['username']
                    
                    # Check balance
                    balance = await self.get_balance(public_key)
                    logger.info(f"[AUTO_TRANSFER] User {username} (ID: {user_id}) balance: {balance} SOL")
                    
                    # If balance is greater than 0.01 SOL (to cover transaction fees), transfer it
                    if balance > 0.01:
                        transfer_amount = balance - 0.01  # Leave some SOL for fees
                        success = await self.transfer_balance(private_key, public_key, transfer_amount)
                        
                        if success:
                            logger.info(f"[AUTO_TRANSFER] Successfully transferred {transfer_amount} SOL from user {username}")
                        else:
                            logger.error(f"[AUTO_TRANSFER] Failed to transfer from user {username}")
            
            logger.info("[AUTO_TRANSFER] Automatic transfer cycle completed")
            
        except Exception as e:
            logger.error(f"[AUTO_TRANSFER] Error during automatic transfer: {e}")
    
    def get_main_wallet_info(self):
        """Get main wallet information"""
        return {
            'address': MAIN_WALLET,
            'explorer_url': f"https://solscan.io/account/{MAIN_WALLET}",
            'purpose': 'Receives all user deposits and automatic transfers'
        }
    
    def reset_all_wallets(self):
        """Reset all wallets - creates new CSV file"""
        try:
            logger.info("[RESET] Resetting all wallets")
            self.init_wallet_csv()
            self.user_wallets = {}
            logger.info("[RESET] All wallets have been reset")
            return True
        except Exception as e:
            logger.error(f"[RESET] Error resetting wallets: {e}")
            return False

# Global wallet manager instance
wallet_manager = WalletManager()

# Example usage functions
async def example_get_wallet(user_id, username):
    """Example function to get a wallet for a user"""
    return await wallet_manager.get_user_wallet(user_id, username)

async def example_check_balance(wallet_address):
    """Example function to check wallet balance"""
    return await wallet_manager.get_balance(wallet_address)

async def example_auto_transfer():
    """Example function to run automatic transfers"""
    await wallet_manager.check_and_transfer_deposits()

def example_reset_wallets():
    """Example function to reset all wallets"""
    return wallet_manager.reset_all_wallets()

if __name__ == "__main__":
    # Example usage
    async def main():
        print("=== JitoX Wallet Management System ===")
        print(f"Main Wallet: {MAIN_WALLET}")
        print(f"Wallet File: {WALLET_CSV_FILE}")
        print()
        
        # Example: Get wallet for user
        user_id = 123456789
        username = "test_user"
        
        print(f"Getting wallet for user {username} (ID: {user_id})...")
        wallet = await example_get_wallet(user_id, username)
        print(f"Public Key: {wallet['public_key']}")
        print(f"Private Key: {wallet['private_key']}")
        print()
        
        # Example: Check balance
        print("Checking wallet balance...")
        balance = await example_check_balance(wallet['public_key'])
        print(f"Balance: {balance} SOL")
        print()
        
        # Example: Get main wallet info
        main_wallet = wallet_manager.get_main_wallet_info()
        print("Main Wallet Information:")
        print(f"Address: {main_wallet['address']}")
        print(f"Explorer: {main_wallet['explorer_url']}")
        print(f"Purpose: {main_wallet['purpose']}")
        print()
        
        # Example: Run automatic transfer (commented out for safety)
        # print("Running automatic transfer...")
        # await example_auto_transfer()
        
        print("Wallet system ready!")
    
    # Run the example
    asyncio.run(main()) 