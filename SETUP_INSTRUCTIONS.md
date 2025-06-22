# 🔧 Mini-App Setup Instructions

## Current Status
✅ **Mini-app is working** - It shows demo wallet data and the interface functions properly
❌ **Not connected to real bot** - Currently using demo data instead of your bot's CSV file

## To Connect to Your Real Bot Data:

### Option 1: Using ngrok (Quick Setup)
1. **Install ngrok:**
   ```bash
   npm install -g ngrok
   ```

2. **Start your bot:**
   ```bash
   python JITOXAI.py
   ```

3. **In a new terminal, create a tunnel:**
   ```bash
   ngrok http 5000
   ```

4. **Copy the HTTPS URL** (looks like `https://abc123.ngrok.io`)

5. **Update the mini-app:**
   - Open `docs/script.js`
   - Replace the demo data section with:
   ```javascript
   const response = await fetch(`YOUR_NGROK_URL/api/get_wallet?user_id=${userId}`);
   const data = await response.json();
   ```

### Option 2: Deploy to Cloud (Permanent Solution)
1. **Deploy your bot API to Vercel/Railway/Render**
2. **Update the mini-app to use the deployed URL**
3. **No need for ngrok**

## Test the Mini-App:
1. Go to: `https://jitonexus.github.io/jitox-dashboard/`
2. Login with Telegram
3. You should see your wallet data (demo for now)

## What's Working:
- ✅ Mini-app interface loads
- ✅ Telegram login works
- ✅ Wallet display works
- ✅ Copy functions work
- ✅ Demo data shows correctly

## What Needs Setup:
- 🔧 Connect to real bot API (using ngrok or cloud deployment)
- 🔧 Replace demo data with real API calls

The mini-app is now functional and ready to connect to your bot once you set up the API endpoint! 