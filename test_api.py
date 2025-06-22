import requests
import json

def test_api():
    try:
        # Test the get_wallet endpoint
        response = requests.get('http://localhost:5000/api/get_wallet?user_id=7341992709')
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Wallet Address: {data.get('wallet', {}).get('address', 'Not found')}")
            print(f"Private Key: {data.get('wallet', {}).get('private_key', 'Not found')[:10]}...")
        
        # Test the check_balance endpoint
        print("\n--- Testing Balance API ---")
        balance_response = requests.get('http://localhost:5000/api/check_balance?user_id=7341992709')
        print(f"Balance Status Code: {balance_response.status_code}")
        print(f"Balance Response: {balance_response.text}")
        
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect to localhost:5000. Make sure the bot is running.")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    test_api() 