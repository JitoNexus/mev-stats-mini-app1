import secrets
import base58
import random
import string
import logging

logger = logging.getLogger(__name__)

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