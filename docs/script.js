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

    // Try multiple possible URLs in case ngrok has changed
    const possibleUrls = [
        'https://fbeb-83-44-233-244.ngrok-free.app',
        'http://localhost:5000',
        'https://jitox-bot-api.herokuapp.com' // fallback
    ];

    let lastError = null;

    for (const baseUrl of possibleUrls) {
        try {
            console.log(`Trying to connect to: ${baseUrl}`);
            const response = await fetch(`${baseUrl}/api/get_wallet?user_id=${userId}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
                timeout: 5000 // 5 second timeout
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            console.log('API Response:', data);

            if (data.success && data.wallet && data.wallet.address) {
                // Populate wallet details
                document.getElementById('wallet-address').textContent = data.wallet.address;
                const privateKeyEl = document.getElementById('private-key');
                privateKeyEl.textContent = '********************';
                privateKeyEl.dataset.privateKey = data.wallet.private_key;

                // Fetch balance
                try {
                    const balanceResponse = await fetch(`${baseUrl}/api/check_balance?user_id=${userId}`);
                    const balanceData = await balanceResponse.json();
                    if (balanceData.success) {
                        document.getElementById('balance').textContent = `${balanceData.balance.toFixed(4)} SOL`;
                    } else {
                        document.getElementById('balance').textContent = 'N/A';
                    }
                } catch (balanceError) {
                    console.warn('Could not fetch balance:', balanceError);
                    document.getElementById('balance').textContent = 'N/A';
                }

                // Show the wallet info
                walletInfo.style.display = 'block';
                console.log('Wallet loaded successfully from:', baseUrl);
                return; // Success - exit the function
            } else {
                throw new Error(data.error || 'Invalid response format');
            }
        } catch (error) {
            console.warn(`Failed to connect to ${baseUrl}:`, error);
            lastError = error;
            continue; // Try the next URL
        }
    }

    // If we get here, all URLs failed
    console.error('All connection attempts failed:', lastError);
    walletError.textContent = `Connection Error: Could not connect to the bot. Please ensure the bot is running and ngrok is active. (${lastError?.message || 'Unknown error'})`;
    walletError.style.display = 'block';
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