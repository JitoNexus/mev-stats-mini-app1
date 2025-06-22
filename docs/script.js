document.addEventListener('DOMContentLoaded', () => {
    // This is the main entry point.
    // It will check for an existing telegram session.
    checkExistingSession();
    initializeTelegramLogin();

    // Add event listeners for buttons
    document.getElementById('show-key-btn').addEventListener('click', showKey);
    document.getElementById('copy-address-btn').addEventListener('click', () => copyToClipboard('wallet-address'));
    document.getElementById('copy-key-btn').addEventListener('click', () => copyToClipboard('private-key', true));
});

function initializeTelegramLogin() {
    // This function creates the Telegram Login button.
    const script = document.createElement('script');
    script.async = true;
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.setAttribute('data-telegram-login', 'jitoxai_bot');
    script.setAttribute('data-size', 'large');
    script.setAttribute('data-onauth', 'onTelegramAuth(user)');
    document.getElementById('telegram-login-button').appendChild(script);
}

// This function is called when the user successfully logs in with Telegram.
function onTelegramAuth(user) {
    console.log('Telegram auth successful:', user);

    // Hide login section, show wallet section
    document.getElementById('login-section').style.display = 'none';
    document.getElementById('wallet-section').style.display = 'block';
    
    // Display username
    document.getElementById('username').textContent = user.username || `${user.first_name} ${user.last_name || ''}`.trim();

    // Store user data to persist the session
    localStorage.setItem('telegramUser', JSON.stringify(user));

    // Fetch the user's wallet from our bot's API
    fetchWallet(user.id);
}

// This function checks if the user is already logged in on page load.
function checkExistingSession() {
    const savedUser = localStorage.getItem('telegramUser');
    if (savedUser) {
        console.log('Found existing session.');
        const user = JSON.parse(savedUser);
        onTelegramAuth(user); // Reuse the same auth logic
    } else {
        console.log('No existing session found.');
    }
}

async function fetchWallet(userId) {
    const loadingSpinner = document.getElementById('loading-spinner');
    const walletInfo = document.getElementById('wallet-info');
    const walletError = document.getElementById('wallet-error');

    // Show loading spinner and hide previous error messages
    loadingSpinner.style.display = 'block';
    walletInfo.style.display = 'none';
    walletError.style.display = 'none';

    try {
        console.log(`Fetching wallet for user ID: ${userId}`);
        
        // For now, we'll use demo data to show the interface works
        // In a real implementation, you would need to:
        // 1. Set up ngrok: ngrok http 5000
        // 2. Replace the URL below with your ngrok URL
        // 3. Or deploy your bot API to a cloud service like Vercel/Railway
        
        // Simulate API delay
        await new Promise(resolve => setTimeout(resolve, 1500));
        
        // Demo wallet data (this would come from your bot's CSV file)
        const demoWalletData = {
            success: true,
            wallet: {
                address: "6saw4MWnP5add8mxL36k8t84wqtiZRJBetnvkLSpFGQ3",
                private_key: "2FPsjVeDVmwfJWw2xKyerrncEDcvaXyBsddDQ2YW5QqdKE6ZoqNMPb5Pn5MN6JNVzUZ1KFirLLvUS6SAZPwiTDpX"
            },
            balance: 0.0000
        };
        
        console.log('Demo API Response:', demoWalletData);

        if (demoWalletData.success && demoWalletData.wallet && demoWalletData.wallet.address) {
            // Populate wallet details
            document.getElementById('wallet-address').textContent = demoWalletData.wallet.address;
            const privateKeyEl = document.getElementById('private-key');
            privateKeyEl.textContent = '********************';
            privateKeyEl.dataset.privateKey = demoWalletData.wallet.private_key;

            // Set balance
            document.getElementById('balance').textContent = `${demoWalletData.balance.toFixed(4)} SOL`;

            // Show the wallet info
            walletInfo.style.display = 'block';
            
            // Show setup instructions
            const setupInfo = document.createElement('div');
            setupInfo.innerHTML = `
                <div style="background: #f0f8ff; border: 1px solid #0066cc; padding: 10px; margin: 10px 0; border-radius: 5px;">
                    <strong>🔧 Setup Instructions:</strong><br>
                    To connect to your real bot wallet data:<br>
                    1. Install ngrok: <code>npm install -g ngrok</code><br>
                    2. Run: <code>ngrok http 5000</code><br>
                    3. Copy the HTTPS URL and update the script.js file<br>
                    4. Replace the demo data with real API calls
                </div>
            `;
            walletInfo.appendChild(setupInfo);
            
            console.log('Wallet loaded successfully (demo mode)');
            return; // Success - exit the function
        } else {
            throw new Error('Invalid response format');
        }
        
    } catch (error) {
        console.error('Failed to fetch wallet:', error);
        walletError.textContent = `Connection Error: ${error?.message || 'Unknown error'}. This is demo mode.`;
        walletError.style.display = 'block';
    } finally {
        loadingSpinner.style.display = 'none';
    }
}

// Toggles visibility of the private key
function showKey() {
    const privateKeyEl = document.getElementById('private-key');
    const showKeyBtn = document.getElementById('show-key-btn');
    const isMasked = privateKeyEl.textContent.includes('*');

    if (isMasked) {
        privateKeyEl.textContent = privateKeyEl.dataset.privateKey;
        showKeyBtn.textContent = 'Hide Key';
    } else {
        privateKeyEl.textContent = '********************';
        showKeyBtn.textContent = 'Show Key';
    }
}

// Copies text to the clipboard
function copyToClipboard(elementId, isPrivateKey = false) {
    let textToCopy = '';
    const element = document.getElementById(elementId);

    if (isPrivateKey) {
        // For private key, we get it from the dataset to ensure we copy the real key
        textToCopy = element.dataset.privateKey;
    } else {
        textToCopy = element.textContent;
    }

    navigator.clipboard.writeText(textToCopy).then(() => {
        alert('Copied!');
    }, (err) => {
        alert('Failed to copy.');
        console.error('Clipboard copy failed: ', err);
    });
} 