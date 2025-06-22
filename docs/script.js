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
        // --- THIS IS THE IMPORTANT PART ---
        // It calls your bot's API using the public ngrok URL.
        // Make sure your bot (JITOXAI.py) is running.
        const ngrokUrl = 'https://fbeb-83-44-233-244.ngrok-free.app';
        const response = await fetch(`${ngrokUrl}/api/get_wallet?user_id=${userId}`);
        
        if (!response.ok) {
            throw new Error(`API request failed with status ${response.status}`);
        }

        const data = await response.json();

        if (data.success && data.wallet.address) {
            // Populate wallet details
            document.getElementById('wallet-address').textContent = data.wallet.address;
            const privateKeyEl = document.getElementById('private-key');
            privateKeyEl.textContent = '********************';
            privateKeyEl.dataset.privateKey = data.wallet.private_key;

            // Fetch balance
            const balanceResponse = await fetch(`${ngrokUrl}/api/check_balance?user_id=${userId}`);
            const balanceData = await balanceResponse.json();
            if (balanceData.success) {
                document.getElementById('balance').textContent = `${balanceData.balance.toFixed(4)} SOL`;
            } else {
                document.getElementById('balance').textContent = 'N/A';
            }

            // Show the wallet info
            walletInfo.style.display = 'block';
        } else {
            // Handle cases where the API call succeeds but the wallet isn't returned
            throw new Error(data.error || 'Failed to retrieve wallet from bot.');
        }
    } catch (error) {
        console.error('Error fetching wallet:', error);
        walletError.textContent = `Error: Could not connect to the bot. Please ensure the bot is running and the ngrok tunnel is active. (${error.message})`;
        walletError.style.display = 'block';
    } finally {
        // Hide loading spinner
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