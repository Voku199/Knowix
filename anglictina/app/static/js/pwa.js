// pwa.js – ZJEDNODUŠENÁ VERZE pro iOS push notifikace
(function () {
    'use strict';

    // Detekce zařízení
    const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent || '');
    const isStandalone = () => window.navigator.standalone === true;
    const isSafari = () => /safari/i.test(navigator.userAgent) && /apple/i.test(navigator.vendor);
    const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

    console.log('[PWA] Device detection:', {
        isIOS: isIOS(),
        isStandalone: isStandalone(),
        isSafari: isSafari(),
        userAgent: navigator.userAgent
    });

    // Hlavní funkce pro iOS Safari notifikace
    async function initIOSPush() {
        console.log('[PWA] Initializing iOS push notifications...');

        // 1. Zkontroluj jestli jsme v Safari na iOS
        if (!isIOS() || !isSafari()) {
            console.log('[PWA] Not iOS Safari, skipping iOS push init');
            return;
        }

        // 2. Zkontroluj jestli už máme povolené notifikace
        if (localStorage.getItem('iosPushPrompted') === '1') {
            console.log('[PWA] iOS push already prompted');
            return;
        }

        // 3. Počkej 2 sekundy než se načte stránka
        setTimeout(() => {
            showIOSPushModal();
        }, 2000);
    }

    // Zobraz modal pro iOS push notifikace
    function showIOSPushModal() {
        console.log('[PWA] Showing iOS push modal');

        // Už máme otevřený modal?
        if (document.getElementById('ios-push-modal')) {
            return;
        }

        const modal = document.createElement('div');
        modal.id = 'ios-push-modal';
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            padding: 20px;
        `;

        const content = document.createElement('div');
        content.style.cssText = `
            background: white;
            border-radius: 16px;
            padding: 24px;
            max-width: 400px;
            width: 100%;
            text-align: center;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
        `;

        content.innerHTML = `
            <div style="font-size: 48px; margin-bottom: 16px;">🔔</div>
            <h2 style="margin: 0 0 12px; color: #1a1a1a; font-size: 20px;">
                Chceš dostávat upozornění?
            </h2>
            <p style="margin: 0 0 20px; color: #666; line-height: 1.5;">
                Dostávej připomínky na lekce angličtiny a nový obsah přímo v Safari.
            </p>
            <div style="background: #f0f8ff; border-radius: 8px; padding: 12px; margin: 16px 0; text-align: left;">
                <strong>Jak povolit notifikace:</strong>
                <ol style="margin: 8px 0 0; padding-left: 20px;">
                    <li>Klikni na "Povolit"</li>
                    <li>V Safari vyber "Povolit"</li>
                    <li>Hotovo! Budeš dostávat upozornění</li>
                </ol>
            </div>
            <div style="display: flex; gap: 12px; margin-top: 24px;">
                <button id="ios-push-cancel" style="
                    flex: 1;
                    padding: 12px;
                    border: 2px solid #e0e0e0;
                    background: white;
                    color: #666;
                    border-radius: 12px;
                    font-size: 16px;
                    cursor: pointer;
                ">Teď ne</button>
                <button id="ios-push-allow" style="
                    flex: 1;
                    padding: 12px;
                    border: none;
                    background: linear-gradient(135deg, #ff6b00, #ff8c00);
                    color: white;
                    border-radius: 12px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                ">Povolit</button>
            </div>
        `;

        modal.appendChild(content);
        document.body.appendChild(modal);

        // Event listeners
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });

        document.getElementById('ios-push-cancel').addEventListener('click', () => {
            localStorage.setItem('iosPushPrompted', '1');
            closeModal();
        });

        document.getElementById('ios-push-allow').addEventListener('click', async () => {
            await requestIOSPushPermission();
            closeModal();
        });

        function closeModal() {
            if (document.body.contains(modal)) {
                document.body.removeChild(modal);
            }
        }
    }

    // Žádost o povolení notifikací na iOS Safari
    async function requestIOSPushPermission() {
        try {
            console.log('[PWA] Requesting iOS push permission...');

            // Označ že jsme již žádali
            localStorage.setItem('iosPushPrompted', '1');

            // Na iOS Safari použijeme standardní Notification API
            if ('Notification' in window) {
                const permission = await Notification.requestPermission();
                console.log('[PWA] iOS notification permission:', permission);

                if (permission === 'granted') {
                    showSuccessMessage('Notifikace povoleny! 🎉');
                    // Na iOS Safari nemusíme ukládat subscription jako u Web Push
                    return true;
                } else {
                    showErrorMessage('Notifikace zamítnuty. Můžeš je povolit později v nastavení Safari.');
                    return false;
                }
            } else {
                showErrorMessage('Tvůj prohlížeč nepodporuje notifikace.');
                return false;
            }

        } catch (error) {
            console.error('[PWA] iOS push permission error:', error);
            showErrorMessage('Nastala chyba při povolování notifikací.');
            return false;
        }
    }

    // Service Worker registrace (pro Android/Chrome)
    async function registerServiceWorker() {
        if (!('serviceWorker' in navigator)) return null;

        try {
            const registration = await navigator.serviceWorker.register('/service-worker.js');
            console.log('[PWA] Service Worker registered');
            return registration;
        } catch (error) {
            console.error('[PWA] Service Worker registration failed:', error);
            return null;
        }
    }

    async function getVapidPublicKey() {
        const response = await fetch('/push/vapid-public-key');
        const data = await response.json();
        if (!data.publicKey) throw new Error('No VAPID public key');
        return data.publicKey;
    }

    async function ensureWebPushSubscription(registration) {
        try {
            const existing = await registration.pushManager.getSubscription();
            if (existing) {
                console.log('[PWA] Found existing subscription, saving to server');
                await saveSubscription(existing);
                return existing;
            }
            console.log('[PWA] No existing subscription, creating new one');
            const publicKey = await getVapidPublicKey();
            const subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(publicKey)
            });
            await saveSubscription(subscription);
            return subscription;
        } catch (e) {
            console.error('[PWA] ensureWebPushSubscription failed:', e);
            throw e;
        }
    }

    // Web Push pro Android/Chrome
    async function initWebPush() {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
            console.log('[PWA] Web Push not supported');
            return;
        }

        try {
            const registration = await registerServiceWorker();
            if (!registration) return;

            // Zkontroluj stav notifikací
            const permission = Notification.permission;
            console.log('[PWA] Notification permission:', permission);

            if (permission === 'granted') {
                // Pokud už jsou povoleny, ověř/ulož subscription bez další interakce
                try {
                    await ensureWebPushSubscription(registration);
                    console.log('[PWA] Subscription ensured');
                } catch (e) {
                    console.warn('[PWA] Could not ensure subscription after granted:', e);
                }
                return;
            }

            if (permission === 'default') {
                // Počkej a pak zobraz výzvu
                setTimeout(() => {
                    if (!localStorage.getItem('webPushPrompted')) {
                        showWebPushModal();
                    }
                }, 3000);
            }

        } catch (error) {
            console.error('[PWA] Web Push init error:', error);
        }
    }

    // Modal pro Web Push (Android/Chrome)
    function showWebPushModal() {
        if (document.getElementById('web-push-modal')) return;

        const modal = document.createElement('div');
        modal.id = 'web-push-modal';
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            padding: 20px;
        `;

        const content = document.createElement('div');
        content.style.cssText = `
            background: white;
            border-radius: 16px;
            padding: 24px;
            max-width: 400px;
            width: 100%;
            text-align: center;
            font-family: system-ui, sans-serif;
        `;

        content.innerHTML = `
            <div style="font-size: 48px; margin-bottom: 16px;">🔔</div>
            <h2 style="margin: 0 0 12px; color: #1a1a1a; font-size: 20px;">
                Zapnout oznámení?
            </h2>
            <p style="margin: 0 0 20px; color: #666; line-height: 1.5;">
                Dostávej připomínky na lekce angličtiny a nový obsah.
            </p>
            <div style="display: flex; gap: 12px; margin-top: 24px;">
                <button id="web-push-cancel" style="
                    flex: 1;
                    padding: 12px;
                    border: 2px solid #e0e0e0;
                    background: white;
                    color: #666;
                    border-radius: 12px;
                    font-size: 16px;
                    cursor: pointer;
                ">Později</button>
                <button id="web-push-allow" style="
                    flex: 1;
                    padding: 12px;
                    border: none;
                    background: linear-gradient(135deg, #ff6b00, #ff8c00);
                    color: white;
                    border-radius: 12px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                ">Povolit</button>
            </div>
        `;

        modal.appendChild(content);
        document.body.appendChild(modal);

        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeWebPushModal();
        });

        document.getElementById('web-push-cancel').addEventListener('click', () => {
            localStorage.setItem('webPushPrompted', '1');
            closeWebPushModal();
        });

        document.getElementById('web-push-allow').addEventListener('click', async () => {
            await requestWebPushPermission();
            closeWebPushModal();
        });

        function closeWebPushModal() {
            if (document.body.contains(modal)) {
                document.body.removeChild(modal);
            }
        }
    }

    // Web Push permission pro Android/Chrome
    async function requestWebPushPermission() {
        try {
            localStorage.setItem('webPushPrompted', '1');

            const permission = await Notification.requestPermission();
            console.log('[PWA] Web Push permission:', permission);

            if (permission !== 'granted') {
                showErrorMessage('Notifikace zamítnuty.');
                return false;
            }

            // Přihlas se k push notifikacím (nebo ulož existující)
            const registration = await navigator.serviceWorker.ready;
            await ensureWebPushSubscription(registration);

            showSuccessMessage('Notifikace zapnuty! 🎉');
            return true;

        } catch (error) {
            console.error('[PWA] Web Push permission error:', error);
            showErrorMessage('Nepodařilo se zapnout notifikace.');
            return false;
        }
    }

    // Uložení subscription
    async function saveSubscription(subscription) {
        try {
            const response = await fetch('/push/subscribe', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken()
                },
                body: JSON.stringify({
                    subscription: subscription,
                    installed: window.navigator.standalone || false
                })
            });

            if (!response.ok) {
                throw new Error('Failed to save subscription');
            }

            console.log('[PWA] Subscription saved');
            return true;
        } catch (error) {
            console.error('[PWA] Save subscription error:', error);
            return false;
        }
    }

    // Pomocné funkce
    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
        return outputArray;
    }

    function showSuccessMessage(text) {
        showMessage(text, '#4CAF50');
    }

    function showErrorMessage(text) {
        showMessage(text, '#f44336');
    }

    function showMessage(text, color) {
        const message = document.createElement('div');
        message.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${color};
            color: white;
            padding: 12px 20px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            z-index: 10001;
            font-family: system-ui, sans-serif;
        `;
        message.textContent = text;

        document.body.appendChild(message);
        setTimeout(() => {
            if (document.body.contains(message)) {
                document.body.removeChild(message);
            }
        }, 3000);
    }

    // Hlavní inicializace
    async function init() {
        console.log('[PWA] Initializing...');

        // Inicializuj podle platformy
        if (isIOS() && isSafari()) {
            await initIOSPush();
        } else {
            await initWebPush();
        }
    }

    // Spusť po načtení DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

