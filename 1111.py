try:
    from solana.publickey import PublicKey
except ImportError:
    from solders.pubkey import Pubkey as PublicKey

from base58 import b58decode
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts

# Decode the wallet address into 32 bytes then create a PublicKey.
wallet_address_str = "9EnbaVoFqvh4vjz5GWzoo5ZSQp2soxp3n4wNjmKSqepA"
wallet_address = PublicKey(b58decode(wallet_address_str))

solana_client = Client("https://api.mainnet-beta.solana.com")

def get_sol_balance():
    # Call the API to get the balance for the wallet.
    response = solana_client.get_balance(wallet_address)
    
    # Print the SOL balance.
    if response.value:
        print(f"SOL balance: {response.value / 10**9} SOL")
    else:
        print("Unable to retrieve balance.")

def get_token_accounts():
    # Decode the SPL Token program id and convert to PublicKey.
    token_program_pubkey = PublicKey(b58decode("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"))
    
    # Create options using the program_id filter and specifying encoding.
    opts = TokenAccountOpts(program_id=token_program_pubkey, encoding="jsonParsed")
    
    # Call the API.
    response = solana_client.get_token_accounts_by_owner(wallet_address, opts)
    
    # Check if response contains value (adjust based on solders response format).
    if response.value:
        for account in response.value:
            # Depending on the response type, these attributes might be objects; adjust as needed.
            print(f"Token Account: {account.pubkey}, Program: {account.account.owner}")
    else:
        print("No token accounts found or wallet is empty.")

# Call both functions
get_sol_balance()
get_token_accounts()
