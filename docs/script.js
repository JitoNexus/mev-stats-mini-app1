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
        // Use the public ngrok URL to connect to your local bot
        const apiUrl = 'https://f872-83-44-233-244.ngrok-free.app';
        
        console.log(`Fetching wallet from: ${apiUrl} for user ID: ${userId}`);
        
        // First try to get the wallet
        const response = await fetch(`${apiUrl}/api/get_wallet?user_id=${userId}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
        });

        if (!response.ok) {
            throw new Error(`Network response was not ok, status: ${response.status}`);
        }

        const data = await response.json();

        if (data.success && data.wallet) {
            const walletAddress = data.wallet.address;
            const privateKey = data.wallet.private_key;

            document.getElementById('wallet-address').textContent = walletAddress;
            document.getElementById('private-key').textContent = privateKey;
            
            walletInfo.style.display = 'block';
            
            // Check balance after getting wallet
            await checkBalance(userId, apiUrl, walletAddress);
            
        } else {
            throw new Error(data.error || 'Wallet not found for this user.');
        }

    } catch (error) {
        console.error('Error fetching wallet:', error);
        walletError.textContent = `Failed to load wallet. Error: ${error.message}. Please try again later.`;
        walletError.style.display = 'block';
    } finally {
        loadingSpinner.style.display = 'none';
    }
}

async function checkBalance(userId, apiUrl, walletAddress) {
    const balanceInfo = document.getElementById('balance-info');
    const balanceError = document.getElementById('balance-error');
    balanceInfo.textContent = 'Checking balance...';
    balanceError.style.display = 'none';

    try {
        const response = await fetch(`${apiUrl}/api/check_balance?user_id=${userId}`);
        if (!response.ok) {
            throw new Error(`Network response was not ok, status: ${response.status}`);
        }
        const data = await response.json();
        if (data.success) {
            balanceInfo.textContent = `Balance: ${data.balance.toFixed(4)} SOL`;
        } else {
            throw new Error(data.error || 'Failed to check balance.');
        }
    } catch (error) {
        console.error('Error checking balance:', error);
        balanceError.textContent = `Error: ${error.message}`;
        balanceError.style.display = 'block';
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