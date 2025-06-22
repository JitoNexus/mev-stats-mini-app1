#!/usr/bin/env python3
"""
JitoX Mini App Deployment Script
This script helps deploy the upgraded mini app to GitHub Pages
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

def main():
    print("🚀 JitoX Mini App Deployment Script")
    print("=" * 50)
    
    # Check if we're in the right directory
    current_dir = Path.cwd()
    mini_app_dir = current_dir / "app" / "solana-mev-tracker-main" / "solana-mev-tracker-main"
    
    if not mini_app_dir.exists():
        print("❌ Error: Mini app directory not found!")
        print(f"Expected path: {mini_app_dir}")
        return False
    
    print(f"✅ Found mini app at: {mini_app_dir}")
    
    # Create deployment directory
    deploy_dir = current_dir / "deploy"
    if deploy_dir.exists():
        shutil.rmtree(deploy_dir)
    deploy_dir.mkdir()
    
    print("📁 Creating deployment package...")
    
    # Copy mini app files to deployment directory
    files_to_copy = [
        "index.html",
        "script.js", 
        "styles.css",
        "loading.css",
        "loading.js",
        "loading.html"
    ]
    
    for file_name in files_to_copy:
        src_file = mini_app_dir / file_name
        dst_file = deploy_dir / file_name
        
        if src_file.exists():
            shutil.copy2(src_file, dst_file)
            print(f"✅ Copied: {file_name}")
        else:
            print(f"⚠️  Warning: {file_name} not found")
    
    # Create README for deployment
    readme_content = """# JitoX PRO - Advanced MEV Trading Suite

## 🚀 Professional MEV Trading Platform

This is the upgraded JitoX PRO mini app with advanced features:

### ✨ New Features
- **Wallet Generation**: Generate Solana wallets directly in the app
- **Real-time Balance**: Live balance updates and monitoring
- **MEV Attacks Feed**: Real-time MEV attack simulation and tracking
- **Easy Deposit**: One-click 2 SOL deposit functionality
- **Professional UI**: Enhanced cyberpunk design with PRO branding

### 🎯 Key Functionality
1. **Generate Wallet**: Create new Solana wallets with private keys
2. **Deposit SOL**: Easy deposit interface with multiple amount options
3. **MEV Attacks**: Live simulation of various MEV attack types
4. **Real-time Stats**: Live profit tracking and success rates
5. **Professional Dashboard**: Advanced analytics and charts

### 🔧 Technical Features
- Responsive design for all devices
- Real-time data updates
- Interactive charts and graphs
- Professional animations and effects
- Secure wallet management

### 🎮 How to Use
1. Generate a wallet using the "Generate Wallet" button
2. Deposit SOL using the "Deposit 2 SOL" button
3. Watch MEV attacks happen in real-time
4. Monitor your profits and success rates
5. Explore different sections using the navigation

### 🛡️ Security
- Self-custodial wallet system
- Private key management
- Secure deposit handling
- Professional-grade security protocols

---
*JitoX PRO - Professional MEV Trading Suite*
"""
    
    with open(deploy_dir / "README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print("✅ Created README.md")
    
    # Create deployment instructions
    deploy_instructions = """# Deployment Instructions

## Option 1: GitHub Pages (Recommended)

1. Create a new repository on GitHub
2. Upload all files from the deploy folder to the repository
3. Go to Settings > Pages
4. Select "Deploy from a branch"
5. Choose "main" branch and "/ (root)" folder
6. Click "Save"

## Option 2: Netlify

1. Go to netlify.com
2. Drag and drop the deploy folder
3. Your site will be live instantly

## Option 3: Vercel

1. Go to vercel.com
2. Import your GitHub repository
3. Deploy automatically

## Option 4: Local Testing

1. Open index.html in a web browser
2. Or use a local server:
   ```bash
   python -m http.server 8000
   ```
   Then visit http://localhost:8000

## 🔗 Update Bot URL

After deployment, update your bot's mini app URL to point to your new deployment.

Example:
```javascript
const mev_stats_url = "https://yourusername.github.io/your-repo-name/";
```
"""
    
    with open(deploy_dir / "DEPLOYMENT.md", "w", encoding="utf-8") as f:
        f.write(deploy_instructions)
    
    print("✅ Created DEPLOYMENT.md")
    
    # List files in deployment directory
    print("\n📋 Deployment package contents:")
    for file in deploy_dir.iterdir():
        if file.is_file():
            size = file.stat().st_size
            print(f"   📄 {file.name} ({size:,} bytes)")
    
    print(f"\n🎉 Deployment package ready at: {deploy_dir}")
    print("\n📝 Next steps:")
    print("1. Upload the contents of the 'deploy' folder to your hosting platform")
    print("2. Update your bot's mini app URL to point to the new deployment")
    print("3. Test the mini app functionality")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\n✅ Deployment script completed successfully!")
        else:
            print("\n❌ Deployment script failed!")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1) 