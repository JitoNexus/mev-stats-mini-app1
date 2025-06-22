// Wait for window load to ensure all resources are available
window.addEventListener('load', () => {
    console.log('Window loaded, initializing animations...');
    initializeAnimations();
});

// Initialize animations
function initializeAnimations() {
    try {
        // Check if GSAP is available
        if (typeof gsap === 'undefined') {
            console.error('GSAP not loaded');
            return;
        }

        // Debug logging
        console.log('GSAP version:', gsap.version);
        
        // Get all required elements first
        const elements = {
            walletBody: document.querySelector('.wallet-body'),
            solCoin: document.querySelector('.coin.sol'),
            ethCoin: document.querySelector('.coin.eth'),
            wallet: document.querySelector('.wallet'),
            textGradient: document.querySelector('.text-gradient')
        };

        // Debug log elements
        console.log('Animation elements:', elements);

        // Initialize GSAP timeline for wallet animation
        if (elements.walletBody) {
            console.log('Initializing wallet animation');
            const tl = gsap.timeline({ repeat: -1 });

            tl.to(elements.walletBody, {
                rotateY: 15,
                rotateX: -10,
                duration: 2,
                ease: 'power1.inOut'
            })
            .to(elements.walletBody, {
                rotateY: -15,
                rotateX: 10,
                duration: 2,
                ease: 'power1.inOut'
            });
        }

        // Coin animations
        if (elements.solCoin) {
            console.log('Initializing SOL coin animation');
            gsap.to(elements.solCoin, {
                y: -30,
                rotation: 10,
                duration: 2,
                ease: 'power1.inOut',
                repeat: -1,
                yoyo: true
            });
        }

        if (elements.ethCoin) {
            console.log('Initializing ETH coin animation');
            gsap.to(elements.ethCoin, {
                y: -20,
                rotation: -10,
                duration: 2,
                delay: 0.5,
                ease: 'power1.inOut',
                repeat: -1,
                yoyo: true
            });
        }

        // Scale animation for the wallet
        if (elements.wallet) {
            console.log('Initializing wallet scale animation');
            gsap.to(elements.wallet, {
                scale: 1.05,
                duration: 2,
                ease: 'power1.inOut',
                repeat: -1,
                yoyo: true
            });
        }

        // Text animation
        if (elements.textGradient) {
            console.log('Initializing text animation');
            gsap.to(elements.textGradient, {
                opacity: 0.7,
                duration: 1.5,
                ease: 'power1.inOut',
                repeat: -1,
                yoyo: true
            });
        }

        console.log('All animations initialized successfully');
    } catch (error) {
        console.error('Error initializing animations:', error);
    }
}

// Export function for use in other files
window.initializeAnimations = initializeAnimations; 