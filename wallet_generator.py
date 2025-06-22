from solana.keypair import Keypair
import base58
import json

def generate_wallets(num_wallets=10):
    """Generate Solana wallets with their private keys."""
    wallets = []
    for _ in range(num_wallets):
        # Generate new keypair
        keypair = Keypair()
        
        # Get public key (wallet address)
        public_key = str(keypair.public_key)
        
        # Get private key in base58 format
        private_key = base58.b58encode(keypair.secret_key).decode('ascii')
        
        wallets.append({
            'public_key': public_key,
            'private_key': private_key
        })
    
    # Save to JSON file
    with open('generated_wallets.json', 'w') as f:
        json.dump(wallets, f, indent=2)
    
    # Print wallet addresses for easy copying
    print("\nGenerated wallet addresses (for wallet_addresses list):")
    addresses = [f'    "{w["public_key"]}",' for w in wallets]
    print("\n".join(addresses))
    
    print("\nWallet details have been saved to generated_wallets.json")

if __name__ == "__main__":
    # Generate 10 wallets by default
    generate_wallets() 