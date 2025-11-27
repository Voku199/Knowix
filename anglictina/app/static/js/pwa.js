// pwa.js – Okamžité nativní vyžádání povolení notifikací (Safari/Chrome/Firefox/Edge)
(function () {
    'use strict';

    const PROMPT_IMMEDIATELY = true; // vyžádej povolení ihned po načtení

    const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent || '');
    const isStandalone = () => window.navigator.standalone === true || window.matchMedia('(display-mode: standalone)').matches;
    const isSafari = () => /safari/i.test(navigator.userAgent) && /apple/i.test(navigator.vendor);
    const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

    const OPT_OUT_KEY = 'pushOptOut';
    const DAILY_KEY_PREFIX = 'pushCount:';

    function todayKey() {
        const d = new Date();
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        return `${DAILY_KEY_PREFIX}${yyyy}${mm}${dd}`;
    }

    function isOptedOut() {
        return localStorage.getItem(OPT_OUT_KEY) === '1';
    }

    function setOptOut(v) {
        v ? localStorage.setItem(OPT_OUT_KEY, '1') : localStorage.removeItem(OPT_OUT_KEY);
        updateNotifButtonUI();
    }

    function incClientDailyCount() {
        const k = todayKey();
        const cur = parseInt(localStorage.getItem(k) || '0', 10);
        localStorage.setItem(k, String(cur + 1));
    }

    function updateNotifButtonUI() {
        const btn = document.getElementById('enable-notifications');
        if (!btn) return;
        // Vždy zobrazit tlačítko – i při denied, aby měl uživatel šanci povolit v nastavení
        btn.style.display = 'inline-block';
        if (!('Notification' in window)) {
            btn.querySelector('.label')?.replaceChildren(document.createTextNode('Nepodporováno'));
            btn.disabled = true;
            btn.title = 'Prohlížeč nepodporuje notifikace';
            return;
        }
        btn.disabled = false;
        if (Notification.permission === 'granted') {
            btn.querySelector('.label')?.replaceChildren(document.createTextNode('Vypnout'));
            btn.title = 'Vypnout notifikace';
        } else if (Notification.permission === 'denied') {
            btn.querySelector('.label')?.replaceChildren(document.createTextNode('Povolit v nastavení'));
            btn.title = 'Notifikace jsou zablokované v prohlížeči – klikni pro instrukce';
        } else {
            btn.querySelector('.label')?.replaceChildren(document.createTextNode('Povolit'));
            btn.title = 'Povolit notifikace';
        }
    }

    async function registerServiceWorker() {
        if (!('serviceWorker' in navigator)) return null;
        try {
            const reg = await navigator.serviceWorker.register('/service-worker.js');
            return reg;
        } catch (e) {
            console.error('[PWA] SW registrace selhala', e);
            return null;
        }
    }

    async function getVapidPublicKey() {
        const resp = await fetch('/push/vapid-public-key');
        const data = await resp.json();
        if (!data.publicKey) throw new Error('No VAPID public key');
        return data.publicKey;
    }

    async function saveSubscription(subscription) {
        try {
            const r = await fetch('/push/subscribe', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken()},
                body: JSON.stringify({subscription, installed: window.navigator.standalone || false})
            });
            if (!r.ok) throw new Error('saveSubscription failed');
            return true;
        } catch (e) {
            console.error('[PWA] saveSubscription error', e);
            return false;
        }
    }

    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
        return outputArray;
    }

    async function ensureWebPushSubscription(reg) {
        const existing = await reg.pushManager.getSubscription();
        if (existing) {
            await saveSubscription(existing);
            return existing;
        }
        if (isOptedOut()) return null;
        const publicKey = await getVapidPublicKey();
        const sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(publicKey)
        });
        await saveSubscription(sub);
        return sub;
    }

    function showMessage(text, color) {
        const el = document.createElement('div');
        el.style.cssText = `position:fixed;top:20px;right:20px;background:${color};color:#fff;padding:12px 16px;border-radius:8px;z-index:10001;font-family:system-ui,sans-serif;`;
        el.textContent = text;
        document.body.appendChild(el);
        setTimeout(() => {
            el.remove();
        }, 3000);
    }

    const showSuccess = (t) => showMessage(t, '#4CAF50');
    const showError = (t) => showMessage(t, '#f44336');

    async function requestWebPushPermissionImmediate() {
        if (!('Notification' in window)) {
            showError('Prohlížeč nepodporuje notifikace.');
            return false;
        }
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            updateNotifButtonUI();
            if (permission === 'denied')
                showError('Notifikace jsou zablokované. Povol je v nastavení prohlížeče.');
            return false;
        }
        try {
            const reg = await (navigator.serviceWorker.ready || registerServiceWorker());
            await ensureWebPushSubscription(reg);
            setOptOut(false);
            showSuccess('Notifikace povoleny!');
            return true;
        } catch (e) {
            console.error('[PWA] subscribe after grant failed', e);
            showError('Nepodařilo se dokončit přihlášení k notifikacím.');
            return false;
        } finally {
            updateNotifButtonUI();
        }
    }

    async function requestIOSPermissionImmediate() {
        if (!('Notification' in window)) {
            showError('Prohlížeč nepodporuje notifikace.');
            return false;
        }
        const permission = await Notification.requestPermission();
        if (permission === 'granted') {
            setOptOut(false);
            showSuccess('Notifikace povoleny!');
            return true;
        }
        if (permission === 'denied') {
            showError('Notifikace jsou zablokované v Safari. Povol je v Nastavení > Safari.');
        }
        updateNotifButtonUI();
        return false;
    }

    async function onNotifButtonClick() {
        try {
            if (!('Notification' in window)) {
                showError('Tento prohlížeč nepodporuje notifikace.');
                return;
            }
            if (Notification.permission === 'granted') {
                // Odhlášení a opt-out
                await unsubscribeWebPush();
                setOptOut(true);
                showMessage('Notifikace vypnuty.', '#607d8b');
                return;
            }
            if (Notification.permission === 'denied') {
                // Zobraz jednoduchý návod
                alert('Notifikace jsou zablokované v prohlížeči.\n\nJak povolit:\n- Chrome: Nastavení > Ochrana soukromí a zabezpečení > Nastavení webu > Oznámení\n- Safari: Nastavení systému > Safari > Oznámení\n- Firefox/Edge: Nastavení webu > Oprávnění > Oznámení');
                return;
            }
            // default -> okamžité vyžádání
            if ('PushManager' in window) await requestWebPushPermissionImmediate(); else await requestIOSPermissionImmediate();
        } finally {
            updateNotifButtonUI();
        }
    }

    async function unsubscribeWebPush() {
        try {
            if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false;
            const reg = await navigator.serviceWorker.ready;
            const sub = await reg.pushManager.getSubscription();
            if (!sub) return true;
            try {
                await fetch('/push/unsubscribe', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken()},
                    body: JSON.stringify({endpoint: sub.endpoint})
                });
            } catch (_) {
            }
            await sub.unsubscribe();
            return true;
        } catch (e) {
            console.warn('[PWA] Unsubscribe failed', e);
            return false;
        }
    }

    function wireNotifButton() {
        const btn = document.getElementById('enable-notifications');
        if (!btn || btn._wired) return;
        btn._wired = true;
        btn.addEventListener('click', onNotifButtonClick);
        updateNotifButtonUI();
    }

    async function init() {
        wireNotifButton();
        // SW registrace hned na start (pomáhá na Androidu)
        registerServiceWorker().catch(() => {
        });

        // Okamžité nativní vyžádání povolení (bez vlastního modalu)
        if (PROMPT_IMMEDIATELY && 'Notification' in window && !isOptedOut()) {
            try {
                if (Notification.permission === 'default') {
                    if ('PushManager' in window) await requestWebPushPermissionImmediate();
                    else if (isIOS() && isSafari()) await requestIOSPermissionImmediate();
                }
            } catch (_) {
            }
        }

        // Telemetrie zobrazení
        try {
            navigator.serviceWorker?.addEventListener?.('message', (e) => {
                if (e?.data?.type === 'PUSH_SHOWN') {
                    incClientDailyCount();
                }
            });
        } catch (_) {
        }
        updateNotifButtonUI();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
