#!/usr/bin/env python3
"""
JitoX AI Main Wallet Information
This script displays the main wallet address for receiving transfers
"""

import os

# Main wallet address
MAIN_WALLET = "25JKsVDeX4monwCdWewsDpDKMzws39xsb9oWdhZESr7L"

def main():
    print("=" * 60)
    print("🏦 JITOX AI MAIN WALLET INFORMATION 🏦")
    print("=" * 60)
    print()
    print("💎 Main Wallet Address:")
    print(f"   {MAIN_WALLET}")
    print()
    print("🔗 View on Solana Explorer:")
    print(f"   https://solscan.io/account/{MAIN_WALLET}")
    print()
    print("📊 Purpose:")
    print("   • Receives all user deposits")
    print("   • Centralized fund management")
    print("   • Automatic transfer destination")
    print()
    print("⚠️  Important Notes:")
    print("   • All user deposits are automatically transferred here")
    print("   • Any amount above 0.000001 SOL will be transferred")
    print("   • This is the main wallet for the entire system")
    print()
    print("=" * 60)
    print("✅ System Status: Ready for automatic transfers")
    print("=" * 60)

if __name__ == "__main__":
    main() 