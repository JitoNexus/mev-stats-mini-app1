"""Solana utilities for JitoX AI"""

import base58
import nacl.signing
from solana.rpc.api import Client
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from spl.token.client import Token
from anchorpy import Provider, Wallet

class SolanaUtils:
    def __init__(self, rpc_url="https://api.mainnet-beta.solana.com"):
        self.client = Client(rpc_url)
        
    def generate_wallet(self):
        """Generate a new Solana wallet."""
            signing_key = nacl.signing.SigningKey.generate()
            verify_key = signing_key.verify_key
            
            private_key = base58.b58encode(bytes(signing_key)).decode('ascii')
            public_key = base58.b58encode(bytes(verify_key)).decode('ascii')
            
            return {
                'private_key': private_key,
                'public_key': public_key
            }
        
    async def check_balance(self, public_key: str) -> float:
        """Check SOL balance of a wallet."""
        try:
            response = self.client.get_balance(public_key)
            if 'result' in response:
                balance = response['result']['value']
                return float(balance) / 1_000_000_000  # Convert lamports to SOL
            return 0.0
        except Exception as e:
            print(f"Error checking balance: {e}")
            return 0.0
            
    async def transfer_sol(self, from_private_key: str, to_public_key: str, amount_sol: float) -> bool:
        """Transfer SOL from one wallet to another."""
        try:
            # Convert private key from base58
            private_key_bytes = base58.b58decode(from_private_key)
            signing_key = nacl.signing.SigningKey(private_key_bytes)
            
            # Get public key
            verify_key = signing_key.verify_key
            from_public_key = base58.b58encode(bytes(verify_key)).decode('ascii')
            
            # Create transfer instruction
            amount_lamports = int(amount_sol * 1_000_000_000)
            transfer_params = TransferParams(
                from_pubkey=from_public_key,
                to_pubkey=to_public_key,
                lamports=amount_lamports
            )
            
            transaction = Transaction().add(transfer(transfer_params))
            
            # Sign and send transaction
            result = self.client.send_transaction(
                transaction,
                signing_key,
            )
            
            return 'result' in result and 'signature' in result['result']
            
        except Exception as e:
            print(f"Error transferring SOL: {e}")
            return False 