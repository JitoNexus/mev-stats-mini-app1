import base58
import nacl.signing
from cryptography.fernet import Fernet
import aiohttp
import asyncio
import logging
import json
import struct
import aiosqlite
from datetime import datetime
import os
from typing import Dict, Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
LAMPORTS_PER_SOL = 1_000_000_000
MIN_BALANCE = 0.00001 * LAMPORTS_PER_SOL  # Minimum balance for fees
THRESHOLD_BALANCE = 1 * LAMPORTS_PER_SOL   # 1 SOL threshold
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
RPC_URL = "https://api.mainnet-beta.solana.com"
DB_PATH = "wallets.db"

class WalletManager:
    def __init__(self, encryption_key: bytes):
        """Initialize the wallet manager with an encryption key."""
        self.fernet = Fernet(encryption_key)
        self.session = None
        
    async def __aenter__(self):
        """Set up aiohttp session for context manager."""
        self.session = aiohttp.ClientSession()
        await self.init_db()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up resources."""
        if self.session:
            await self.session.close()
            
    async def init_db(self):
        """Initialize the SQLite database with required schema."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS wallets (
                    user_id INTEGER PRIMARY KEY,
                    public_key TEXT UNIQUE,
                    enc_private_key TEXT,
                    last_checked REAL DEFAULT 0,
                    balance REAL DEFAULT 0
                )
            ''')
            await db.commit()

    def generate_keypair(self) -> Dict[str, str]:
        """Generate a new Solana keypair using PyNaCl."""
        signing_key = nacl.signing.SigningKey.generate()
        verify_key = signing_key.verify_key
        
        return {
            'public': base58.b58encode(verify_key.encode()).decode(),
            'private': base58.b58encode(bytes(signing_key)).decode()
        }

    async def create_wallet(self, user_id: int) -> Dict[str, str]:
        """Create and store a new wallet for a user."""
        keypair = self.generate_keypair()
        enc_private_key = self.fernet.encrypt(keypair['private'].encode()).decode()
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO wallets (user_id, public_key, enc_private_key) VALUES (?, ?, ?)',
                (user_id, keypair['public'], enc_private_key)
            )
            await db.commit()
        
        return {'public_key': keypair['public']}

    async def get_balance(self, public_key: str) -> int:
        """Get the balance of a wallet in lamports."""
        if not self.session:
            raise RuntimeError("Session not initialized")
            
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [public_key]
        }
        
        try:
            async with self.session.post(RPC_URL, json=payload) as response:
                result = await response.json()
                if 'error' in result:
                    raise ValueError(f"RPC error: {result['error']}")
                return result['result']['value']
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            raise

    async def get_recent_blockhash(self) -> str:
        """Get a recent blockhash from the network."""
        if not self.session:
            raise RuntimeError("Session not initialized")
            
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": []
        }
        
        try:
            async with self.session.post(RPC_URL, json=payload) as response:
                result = await response.json()
                if 'error' in result:
                    raise ValueError(f"RPC error: {result['error']}")
                return result['result']['value']['blockhash']
        except Exception as e:
            logger.error(f"Failed to get recent blockhash: {e}")
            raise

    def build_transfer_tx(
        self,
        src_pubkey: str,
        dst_pubkey: str,
        lamports: int,
        recent_blockhash: str
    ) -> bytes:
        """Build a transfer transaction message."""
        # Instruction data (transfer = 2)
        instruction_data = struct.pack('<IQ', 2, lamports)
        
        # Account metas
        accounts = [
            {'pubkey': src_pubkey, 'isSigner': True, 'isWritable': True},
            {'pubkey': dst_pubkey, 'isSigner': False, 'isWritable': True}
        ]
        
        # Build the message
        message = {
            'recentBlockhash': recent_blockhash,
            'instructions': [{
                'programId': SYSTEM_PROGRAM_ID,
                'accounts': accounts,
                'data': base58.b58encode(instruction_data).decode()
            }]
        }
        
        return json.dumps(message).encode()

    async def send_transaction(self, signed_tx: str) -> str:
        """Send a signed transaction to the network."""
        if not self.session:
            raise RuntimeError("Session not initialized")
            
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [signed_tx]
        }
        
        try:
            async with self.session.post(RPC_URL, json=payload) as response:
                result = await response.json()
                if 'error' in result:
                    raise ValueError(f"RPC error: {result['error']}")
                return result['result']
        except Exception as e:
            logger.error(f"Failed to send transaction: {e}")
            raise

    async def safe_transfer(
        self,
        user_id: int,
        destination: str,
        amount: int,
        max_retries: int = 3
    ) -> Optional[str]:
        """Safely transfer SOL with retries."""
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                'SELECT public_key, enc_private_key FROM wallets WHERE user_id = ?',
                (user_id,)
            )
            wallet_data = await cursor.fetchone()
            
        if not wallet_data:
            raise ValueError("Wallet not found")
            
        public_key, enc_private_key = wallet_data
        private_key = self.fernet.decrypt(enc_private_key.encode()).decode()
        
        for attempt in range(max_retries):
            try:
                blockhash = await self.get_recent_blockhash()
                message = self.build_transfer_tx(
                    public_key,
                    destination,
                    amount,
                    blockhash
                )
                
                # Sign the message
                signing_key = nacl.signing.SigningKey(base58.b58decode(private_key))
                signed_message = signing_key.sign(message)
                
                # Send the transaction
                signature = await self.send_transaction(
                    base58.b58encode(signed_message).decode()
                )
                return signature
                
            except Exception as e:
                logger.error(f"Transfer attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

    async def monitor_balances(self):
        """Monitor wallet balances and auto-transfer when threshold is reached."""
        while True:
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    cursor = await db.execute('SELECT user_id, public_key FROM wallets')
                    wallets = await cursor.fetchall()
                
                for user_id, public_key in wallets:
                    balance = await self.get_balance(public_key)
                    
                    if balance > THRESHOLD_BALANCE:
                        excess = balance - MIN_BALANCE
                        # Here you would implement the logic to transfer to your destination
                        # wallet, logging the transaction, etc.
                        logger.info(f"Wallet {public_key} exceeded threshold. Excess: {excess}")
                        
                    await db.execute(
                        'UPDATE wallets SET balance = ?, last_checked = ? WHERE user_id = ?',
                        (balance, datetime.now().timestamp(), user_id)
                    )
                    await db.commit()
                    
            except Exception as e:
                logger.error(f"Error in balance monitoring: {e}")
                
            await asyncio.sleep(300)  # Wait 5 minutes before next check

# Example usage
async def main():
    # Generate a new encryption key
    encryption_key = Fernet.generate_key()
    
    async with WalletManager(encryption_key) as wallet_manager:
        # Create a new wallet
        user_id = 1
        wallet = await wallet_manager.create_wallet(user_id)
        print(f"Created wallet: {wallet['public_key']}")
        
        # Start balance monitoring in the background
        monitoring_task = asyncio.create_task(wallet_manager.monitor_balances())
        
        try:
            # Keep the script running
            await asyncio.gather(monitoring_task)
        except KeyboardInterrupt:
            monitoring_task.cancel()
            
if __name__ == "__main__":
    asyncio.run(main()) 