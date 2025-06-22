import requests
import base58
import json
from nacl.signing import SigningKey

# Constants
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
LAMPORTS_PER_SOL = 1000000000  # 1 SOL = 1 billion lamports

def get_recent_blockhash():
    response = requests.post(SOLANA_RPC_URL, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getLatestBlockhash",
        "params": [{"commitment": "finalized"}]
    })
    result = response.json()
    return result['result']['value']['blockhash']

def create_transfer_tx(from_address, to_address, amount, recent_blockhash, private_key, fee_payer_address):
    lamports = int(amount * LAMPORTS_PER_SOL)
    
    # Create message
    message = (
        bytes([2, 0, 1]) +  # 2 required signatures, 0 readonly signed, 1 readonly unsigned
        bytes([4]) +  # Number of accounts
        base58.b58decode(fee_payer_address) +
        base58.b58decode(from_address) +
        base58.b58decode(to_address) +
        base58.b58decode("11111111111111111111111111111111") +
        base58.b58decode(recent_blockhash) +
        bytes([1]) +  # 1 instruction
        bytes([3]) +  # Program ID index
        bytes([3]) +  # Number of accounts
        bytes([0]) +  # Account index 0 (fee payer)
        bytes([1]) +  # Account index 1 (from)
        bytes([2]) +  # Account index 2 (to)
        bytes([12]) +  # Data length
        bytes([2, 0, 0, 0]) +  # Transfer instruction
        lamports.to_bytes(8, 'little')  # Amount
    )
    
    # Sign the message with the sender's private key
    private_bytes = base58.b58decode(private_key)[:32]
    signer = SigningKey(private_bytes)
    signature = signer.sign(message).signature
    
    # Sign the message with the fee payer's private key
    fee_payer_private_bytes = base58.b58decode(fee_payer_private_key)[:32]
    fee_payer_signer = SigningKey(fee_payer_private_bytes)
    fee_payer_signature = fee_payer_signer.sign(message).signature
    
    # Build final transaction
    transaction = bytes([2]) + fee_payer_signature + signature + message
    
    return base58.b58encode(transaction).decode()

def send_transaction(transaction):
    response = requests.post(SOLANA_RPC_URL, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendTransaction",
        "params": [
            transaction,
            {"encoding": "base58", "skipPreflight": False, "preflightCommitment": "finalized"}
        ]
    })
    return response.json()

# Replace with your actual private keys and addresses
private_key = "Qk6xwRF4Pbcx8gsFTLqVdntS3pVaeuSDRVxjgqCuTY6RvZt2Dign7rnpkt8V3qZ2Xm1c2uikP3NSZFvVGRjGRhC"
fee_payer_private_key = "4E8jaGCXDzshTSXK4dKQAaXb1d1YsTuaN8fmchBEmu1azrm1nJRQT7Z3fPSwfWt571dUWF7aFwmEXqhRYPoaS3Aa"
from_address = "9EnbaVoFqvh4vjz5GWzoo5ZSQp2soxp3n4wNjmKSqepA"
to_address = "25JKsVDeX4monwCdWewsDpDKMzws39xsb9oWdhZESr7L"
fee_payer_address = "7FCWDpxqQsoVfmMKzEXnabKp5UL3267VMX5qQi6EBN9g"
amount = 7.0  # Amount in SOL to transfer

# Get recent blockhash
recent_blockhash = get_recent_blockhash()

# Create and send transaction
transaction = create_transfer_tx(from_address, to_address, amount, recent_blockhash, private_key, fee_payer_address)
response = send_transaction(transaction)
print("Transaction response:", response)