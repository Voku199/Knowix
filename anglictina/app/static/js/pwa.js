// PWA + Push registrace
(function () {
    let deferredPrompt = null;
    // Exponovaná funkce pro instalaci (volána z modalu po registraci)
    window.tryPwaInstall = async function () {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            const choice = await deferredPrompt.userChoice;
            deferredPrompt = null;
            const installBtn = document.getElementById('install-app');
            if (installBtn) installBtn.style.display = 'none';
            return choice && choice.outcome === 'accepted';
        } else {
            // Fallback: pokud již běží ve standalone nebo není k dispozici prompt, nic neděláme
            if (window.matchMedia('(display-mode: standalone)').matches) {
                return true;
            }
            console.warn('[PWA] Instalace prompt není dostupný');
            return false;
        }
    };
    const installBtn = document.getElementById('install-app');
    const notifBtn = document.getElementById('enable-notifications');
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const CSRF = csrfMeta ? csrfMeta.content : null;

    // Instalace aplikace
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPrompt = e;
        window.beforeInstallPromptFired = true; // flag pro detekci v registration_success.html
        if (installBtn) installBtn.style.display = 'inline-block';
    });
    if (installBtn) {
        installBtn.addEventListener('click', async () => {
            if (!deferredPrompt) return;
            deferredPrompt.prompt();
            const choice = await deferredPrompt.userChoice;
            if (choice.outcome === 'accepted') {
                console.log('PWA instalace přijata');
            }
            deferredPrompt = null;
            installBtn.style.display = 'none';
        });
    }

    // Registrace SW z kořene kvůli scope '/'
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/service-worker.js', {scope: '/'}).then(() => {
            console.log('[PWA] Service Worker registrován na / se scope "/"');
            if (Notification && Notification.permission === 'default') {
                if (notifBtn) notifBtn.style.display = 'inline-block';
            }
        }).catch(err => console.error('[PWA] SW chyba', err));
    }

    // Push subscription
    async function subscribeToPush() {
        try {
            const perm = await Notification.requestPermission();
            if (perm !== 'granted') {
                console.warn('Notifikace zamítnuty');
                return;
            }
            const reg = await navigator.serviceWorker.ready;
            // VAPID public key
            const vapidResp = await fetch('/push/vapid-public-key');
            const {publicKey} = await vapidResp.json();
            if (!publicKey) {
                console.warn('Chybí public VAPID key');
                return;
            }
            const keyUint8 = urlBase64ToUint8Array(publicKey);
            const sub = await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: keyUint8});
            const headers = {'Content-Type': 'application/json'};
            if (CSRF) headers['X-CSRFToken'] = CSRF;
            await fetch('/push/subscribe', {
                method: 'POST',
                headers,
                body: JSON.stringify({subscription: sub})
            });
            console.log('Push subscription OK');
            if (notifBtn) notifBtn.style.display = 'none';
        } catch (e) {
            console.error('Subscribe error', e);
        }
    }

    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    // Helpery pro CSRF a POST JSON
    async function postJSON(url, body) {
        const headers = {'Content-Type': 'application/json'};
        if (CSRF) headers['X-CSRFToken'] = CSRF;
        return fetch(url, {method: 'POST', headers, body: JSON.stringify(body || {})});
    }

    function isStandalone() {
        return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
            || window.navigator.standalone === true
            || document.referrer && document.referrer.startsWith('android-app://');
    }

    async function getEndpoint() {
        try {
            const reg = await navigator.serviceWorker.ready;
            const sub = await reg.pushManager.getSubscription();
            return sub ? sub.endpoint : null;
        } catch (_) {
            return null;
        }
    }

    async function markInstalledIfPossible() {
        const ep = await getEndpoint();
        if (!ep) return;
        await postJSON('/push/installed', {endpoint: ep, installed: true});
    }

    async function sendPing() {
        const ep = await getEndpoint();
        if (!ep) return;
        await postJSON('/push/ping', {endpoint: ep});
    }

    // Po registraci SW: pokud už je subscription a běží ve standalone, označ jako nainstalované
    if ('serviceWorker' in navigator) {
        (async () => {
            try {
                await navigator.serviceWorker.ready;
                if (isStandalone()) {
                    await markInstalledIfPossible();
                }
                // ping při načtení
                await sendPing();
            } catch (_) {
            }
        })();
    }

    // Událost skutečné instalace PWA
    window.addEventListener('appinstalled', async () => {
        await markInstalledIfPossible();
    });

    // Ping při návratu do okna
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') sendPing();
    });

    // Volitelně: periodický ping (každých 30 min)
    setInterval(sendPing, 30 * 60 * 1000);

    if (notifBtn) {
        notifBtn.addEventListener('click', subscribeToPush);
    }
})();
