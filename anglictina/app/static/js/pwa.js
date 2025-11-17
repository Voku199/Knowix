// pwa.js – registrace SW, PWA instalace a Web Push subscription (iOS/Android/PC)
(function () {
    'use strict';

    // --- Pomocné detekce
    const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent || '');
    const isStandalone = () => (
        window.matchMedia('(display-mode: standalone)').matches ||
        (window.navigator && window.navigator.standalone === true)
    );
    const hasSW = () => 'serviceWorker' in navigator;
    const hasPush = () => 'PushManager' in window;
    const csrfToken = () => (document.querySelector('meta[name="csrf-token"]')?.content || '');
    const isSecure = () => window.location.protocol === 'https:' || window.location.hostname === 'localhost';

    // Diagnostika – důvod proč nelze požádat o notifikace
    function pushSupportStatus() {
        if (!hasSW()) return 'Chybí Service Worker.';
        if (!hasPush()) return 'Prohlížeč nepodporuje Push API.';
        if (!('Notification' in window)) return 'Chybí Notification API.';
        if (!isSecure()) return 'Nutný HTTPS (nebo localhost pro Chrome).';
        if (isIOS() && !isStandalone()) return 'Na iOS musí být aplikace přidaná na plochu.';
        return 'OK';
    }

    // --- Prvky UI
    const btnNotif = document.getElementById('enable-notifications');
    const btnInstall = document.getElementById('install-app');

    // Uložíme deferred prompt pro instalaci
    let deferredInstallPrompt = null;

    // Vlastní modal pro vysvětlení notifikací (teprve kliknutím vyvoláme requestPermission)
    function showPermissionModal() {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.id = 'notif-permission-overlay';
            overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:9999;';

            const box = document.createElement('div');
            box.style.cssText = 'max-width:420px;width:92%;background:#1c1f26;color:#fff;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.4);padding:18px;font-family:inherit;';
            const iosHint = (isIOS() && !isStandalone()) ? '<p style="margin:6px 0 10px;color:#ffbf4d;font-size:13px;">Nejdřív přidej aplikaci na plochu (Sdílet → Přidat na plochu), pak povol notifikace.</p>' : '';
            box.innerHTML = `
        <h3 style="margin:0 0 8px; font-size:18px;">Zapnout oznámení?</h3>
        <p style="margin:0 0 12px; line-height:1.4; color:#cfd3dc;">
          Dostávej upozornění na nové lekce, výzvy a tipy. Kdykoli lze vypnout v nastavení prohlížeče.
        </p>
        ${iosHint}
        <div style="display:flex; gap:8px; justify-content:flex-end;">
          <button id="notif-cancel" style="padding:8px 12px;border:1px solid #3a3f4b;background:#12151b;color:#cfd3dc;border-radius:8px;cursor:pointer;">Později</button>
          <button id="notif-allow" style="padding:8px 12px;border:none;background:linear-gradient(135deg,#ff9600,#ffbf4d);color:#1c1f26;border-radius:8px;cursor:pointer;font-weight:700;">Povolit</button>
        </div>
      `;

            overlay.appendChild(box);
            document.body.appendChild(overlay);

            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) close(false);
            });
            box.querySelector('#notif-cancel').addEventListener('click', () => close(false));
            box.querySelector('#notif-allow').addEventListener('click', () => close(true));

            function close(allow) {
                try {
                    document.body.removeChild(overlay);
                } catch (_) {
                }
                resolve(Boolean(allow));
            }
        });
    }

    // Převodník VAPID klíče (base64url -> Uint8Array)
    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
        return outputArray;
    }

    // Registrace Service Workeru
    async function registerServiceWorker() {
        if (!hasSW()) return null;
        try {
            const reg = await navigator.serviceWorker.register('/service-worker.js', {scope: '/'});
            await navigator.serviceWorker.ready; // zajistí připravenost
            return reg;
        } catch (e) {
            console.error('[PWA] SW registrace selhala', e);
            return null;
        }
    }

    // Uložení subscription na backend
    async function saveSubscription(sub) {
        const body = JSON.stringify({subscription: sub, installed: isStandalone()});
        const headers = {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken()};
        const saveResp = await fetch('/push/subscribe', {method: 'POST', headers, body, credentials: 'include'});
        if (!saveResp.ok) {
            const t = await saveResp.text();
            throw new Error('Uložení subscription selhalo: ' + t);
        }
    }

    // Získání/uložení subscription na backend
    async function ensureSubscribed() {
        try {
            const reg = await navigator.serviceWorker.ready;
            if (!reg || !hasPush()) throw new Error('Push API není k dispozici.');

            let sub = await reg.pushManager.getSubscription();
            if (!sub) {
                const r = await fetch('/push/vapid-public-key', {credentials: 'include'});
                const j = await r.json();
                const pub = j && j.publicKey;
                if (!pub) throw new Error('Chybí VAPID public key.');
                sub = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToUint8Array(pub)
                });
            }
            await saveSubscription(sub);
            console.log('[PWA] Subscription OK');
            return true;
        } catch (e) {
            console.error('[PWA] ensureSubscribed error', e);
            alert('Nepodařilo se zapnout oznámení. Možné důvody: blokace v prohlížeči, HTTP místo HTTPS, nebo systémové omezení.');
            return false;
        }
    }

    // Jednorázová automatická žádost o permission (neobtěžovat opakovaně)
    function autoRequestPermission() {
        if (!('Notification' in window)) return;
        if (Notification.permission !== 'default') return;
        if (localStorage.getItem('notifPrompted') === '1') return;
        const status = pushSupportStatus();
        if (status !== 'OK') {
            console.log('[PWA] Auto-permission skip:', status);
            return;
        }
        // Malé zpoždění aby se UI ustálilo
        setTimeout(async () => {
            try {
                console.log('[PWA] Auto requesting notification permission');
                const res = await Notification.requestPermission();
                localStorage.setItem('notifPrompted', '1');
                if (res === 'granted') {
                    await ensureSubscribed();
                    if (btnNotif) btnNotif.style.display = 'none';
                } else if (res === 'denied') {
                    console.warn('[PWA] Uživatel odmítl notifikace.');
                }
            } catch (e) {
                console.error('[PWA] Auto request selhal', e);
            }
        }, 1500);
    }

    // Hlavní init
    async function init() {
        console.log('[PWA] Push support status:', pushSupportStatus());
        const reg = await registerServiceWorker();

        // Instalace PWA: nabídka
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            deferredInstallPrompt = e;
            if (btnInstall) btnInstall.style.display = 'inline-block';
        });

        if (btnInstall) {
            btnInstall.addEventListener('click', async () => {
                if (!deferredInstallPrompt) {
                    if (isIOS() && !isStandalone()) {
                        alert('Na iOS přidej aplikaci na plochu: Sdílet → Přidat na plochu.');
                    }
                    return;
                }
                deferredInstallPrompt.prompt();
                const {outcome} = await deferredInstallPrompt.userChoice;
                console.log('[PWA] Install choice:', outcome);
                deferredInstallPrompt = null;
                btnInstall.style.display = 'none';
            });
        }

        // Notifikace: zobraz tlačítko pokud dává smysl
        if (btnNotif) {
            const supported = pushSupportStatus() === 'OK';
            const perm = Notification?.permission || 'default';

            if (supported && perm !== 'granted') {
                btnNotif.style.display = 'inline-block';
            } else if (perm === 'granted') {
                btnNotif.style.display = 'none';
            }

            // Pokud iOS není instalovaná PWA -> instrukce
            if (isIOS() && !isStandalone()) {
                btnNotif.style.display = 'inline-block';
                btnNotif.textContent = 'Instaluj pro notifikace';
                btnNotif.addEventListener('click', () => {
                    alert('Pro notifikace na iOS nejprve přidej aplikaci na plochu (Safari → Sdílet → Přidat na plochu).');
                }, {once: true});
            } else {
                btnNotif.addEventListener('click', async () => {
                    try {
                        if (Notification.permission === 'default') {
                            const allow = await showPermissionModal();
                            if (!allow) return;
                        }
                        const result = await Notification.requestPermission();
                        if (result !== 'granted') {
                            alert('Bez povolení notifikací to nepůjde. Povol je v nastavení prohlížeče.');
                            return;
                        }
                        await ensureSubscribed();
                        btnNotif.style.display = 'none';
                    } catch (e) {
                        console.error('[PWA] Povolení notifikací selhalo', e);
                        alert('Povolení notifikací se nepodařilo. Zkontroluj HTTPS nebo systémové nastavení.');
                    }
                });
            }
        }

        // Auto žádost (pouze pokud vše splněno a permission default)
        autoRequestPermission();

        // Pokud jsou notifikace již povolené, ujisti se o subscription
        try {
            if (Notification?.permission === 'granted' && reg) {
                await ensureSubscribed();
            }
        } catch (_) {
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
