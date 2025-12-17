// Service Worker pro Knowix PWA
const STATIC_CACHE = 'knowix-static-v2';
const DYNAMIC_CACHE = 'knowix-dynamic-v2';
const OFFLINE_URL = '/offline';

// Denní limit lokálně v SW jako poslední pojistka (server má hlavní limit)
const MAX_PUSHES_PER_DAY_SW = 5;

// Seznam statických souborů k precache
const PRECACHE_ASSETS = [
    '/', '/offline', '/static/style.css', '/static/mobile_header.css',
    '/static/pic/logo.webp', '/static/favicon.ico', '/static/manifest.json'
];

// --- Jednoduchý IndexedDB helper ---
const DB_NAME = 'knowix-sw';
const DB_STORE = 'kv';

function idbOpen() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = (e) => {
            const db = req.result;
            if (!db.objectStoreNames.contains(DB_STORE)) {
                db.createObjectStore(DB_STORE);
            }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

function idbGet(key) {
    return idbOpen().then(db => new Promise((resolve, reject) => {
        const tx = db.transaction(DB_STORE, 'readonly');
        const st = tx.objectStore(DB_STORE);
        const g = st.get(key);
        g.onsuccess = () => resolve(g.result);
        g.onerror = () => reject(g.error);
    }));
}

function idbSet(key, val) {
    return idbOpen().then(db => new Promise((resolve, reject) => {
        const tx = db.transaction(DB_STORE, 'readwrite');
        const st = tx.objectStore(DB_STORE);
        const p = st.put(val, key);
        p.onsuccess = () => resolve(true);
        p.onerror = () => reject(p.error);
    }));
}

function todayStr() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

// Detekce iOS v SW (bezpečně, userAgent může být nedostupný)
function isIOS() {
    try {
        const ua = (self.navigator && self.navigator.userAgent) ? self.navigator.userAgent : '';
        return /iphone|ipad|ipod/i.test(ua);
    } catch (_) {
        return false;
    }
}

self.addEventListener('install', (event) => {
    console.log('[SW] Installing service worker...');
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then(cache => cache.addAll(PRECACHE_ASSETS))
            .then(() => {
                console.log('[SW] Pre-cached assets');
                return self.skipWaiting();
            })
    );
});

self.addEventListener('activate', (event) => {
    console.log('[SW] Activating service worker...');
    event.waitUntil(
        caches.keys().then(keys => Promise.all(
            keys.filter(k => ![STATIC_CACHE, DYNAMIC_CACHE].includes(k))
                .map(k => {
                    console.log('[SW] Deleting old cache:', k);
                    return caches.delete(k);
                })
        )).then(() => {
            console.log('[SW] Now controlling clients');
            return self.clients.claim();
        })
    );
});

function isStaticRequest(request) {
    const url = new URL(request.url);
    return url.pathname.startsWith('/static/') || url.pathname === '/' || url.pathname === '/offline';
}

self.addEventListener('fetch', (event) => {
    const request = event.request;
    const url = new URL(request.url);

    // Ignoruj vše mimo http/https (např. chrome-extension://)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return;

    // Navigace (HTML stránky) – network first s fallbackem
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request)
                .then(resp => {
                    try {
                        const copy = resp.clone();
                        caches.open(DYNAMIC_CACHE).then(c => c.put(request, copy)).catch(() => {
                        });
                    } catch (_) {
                    }
                    return resp;
                })
                .catch(() => caches.match(request).then(r => r || caches.match(OFFLINE_URL)))
        );
        return;
    }

    // Statické soubory – cache first
    if (isStaticRequest(request)) {
        event.respondWith(
            caches.match(request).then(cached => {
                if (cached) {
                    console.log('[SW] Serving from cache:', request.url);
                    return cached;
                }
                return fetch(request)
                    .then(resp => {
                        try {
                            const copy = resp.clone();
                            caches.open(STATIC_CACHE).then(c => c.put(request, copy)).catch(() => {
                            });
                        } catch (_) {
                        }
                        return resp;
                    })
                    .catch(() => caches.match(OFFLINE_URL));
            })
        );
        return;
    }

    // Ostatní – network s fallbackem do cache
    event.respondWith(
        fetch(request)
            .then(resp => {
                if (request.method === 'GET') {
                    try {
                        const copy = resp.clone();
                        caches.open(DYNAMIC_CACHE).then(c => c.put(request, copy)).catch(() => {
                        });
                    } catch (_) {
                    }
                }
                return resp;
            })
            .catch(() => caches.match(request).then(r => r || caches.match(OFFLINE_URL)))
    );
});

async function canShowNotificationToday() {
    try {
        const key = 'push-count:' + todayStr();
        const n = await idbGet(key);
        const cur = typeof n === 'number' ? n : parseInt(n || '0', 10) || 0;
        return cur < MAX_PUSHES_PER_DAY_SW;
    } catch (_) {
        return true; // pokud IDB selže, neblokuj
    }
}

self.addEventListener('fetch', event => {
    try {
        const url = new URL(event.request.url);
        if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/.well-known/')) {
            // neni voláno event.respondWith -> necháme prohlížeč standardně načíst zdroj
            return;
        }
    } catch (e) {
        // pokud URL parsing selže, pokračujeme do běžného handleru níže
    }

    // Původní fetch/cache logika SW (příklad fallbacku)
    event.respondWith(
        caches.match(event.request).then(cached => cached || fetch(event.request))
    );
});

async function markNotificationShown() {
    try {
        const key = 'push-count:' + todayStr();
        const n = await idbGet(key);
        const cur = typeof n === 'number' ? n : parseInt(n || '0', 10) || 0;
        await idbSet(key, cur + 1);
    } catch (_) {
        // ignore
    }
}

async function notifyClientsShown() {
    try {
        const cl = await clients.matchAll({type: 'window', includeUncontrolled: true});
        for (const c of cl) {
            c.postMessage({type: 'PUSH_SHOWN'});
        }
    } catch (_) {
    }
}

// Push notifikace - JEDNA definice
self.addEventListener('push', (event) => {
    console.log('[SW] Push event received:', event);

    event.waitUntil((async () => {
        // Denní limit – pojistka
        const allowed = await canShowNotificationToday();
        if (!allowed) {
            console.log('[SW] Daily push limit reached in SW – skipping notification');
            return;
        }

        let data = {};
        try {
            data = event.data ? event.data.json() : {};
            console.log('[SW] Push data parsed:', data);
        } catch (e) {
            console.error('[SW] Push data parsing error:', e);
            // Fallback pro starší prohlížeče
            try {
                data = {
                    title: 'Knowix',
                    body: event.data?.text() || 'Nová aktualizace!',
                    url: '/'
                };
            } catch (_) {
                data = {
                    title: 'Knowix',
                    body: 'Nová lekce je dostupná!',
                    url: '/'
                };
            }
        }

        const title = data.title || 'Knowix aktualizace';
        let body = data.body || 'Nová lekce je dostupná!';
        const url = data.url || '/';

        // iOS specifické úpravy
        const options = {
            body: body,
            icon: '/static/pic/logo.webp',
            badge: '/static/pic/logo.webp',
            data: {url: url},
            tag: data.tag || 'knowix-general',
            renotify: true,
            requireInteraction: false,
            vibrate: [100, 50, 100]
        };

        // Pro iOS: zkrátit text pokud je příliš dlouhý
        if (isIOS() && body.length > 100) {
            options.body = body.substring(0, 100) + '...';
        }

        console.log('[SW] Showing notification with options:', options);

        try {
            await self.registration.showNotification(title, options);
            await markNotificationShown();
            await notifyClientsShown();
            console.log('[SW] Notification shown successfully');
        } catch (err) {
            console.error('[SW] Notification error:', err);
            // Fallback pro iOS - zkusíme bez tagu
            if (isIOS()) {
                delete options.tag;
                try {
                    await self.registration.showNotification(title, options);
                    await markNotificationShown();
                    await notifyClientsShown();
                } catch (e2) {
                    console.error('[SW] Notification retry error:', e2);
                }
            }
        }
    })());
});

// Obsluha kliknutí na notifikaci - JEDNA definice
self.addEventListener('notificationclick', (event) => {
    console.log('[SW] Notification click received:', event.notification);

    event.notification.close();

    const urlToOpen = (event.notification.data && event.notification.data.url)
        ? event.notification.data.url
        : '/';

    event.waitUntil(
        clients.matchAll({
            type: 'window',
            includeUncontrolled: true
        }).then((windowClients) => {
            // Hledáme již otevřené okno s Knowix
            for (const client of windowClients) {
                if (client.url.includes('knowix.cz') && 'focus' in client) {
                    console.log('[SW] Focusing existing client:', client.url);
                    return client.focus();
                }
            }

            // Pokud okno není otevřené, otevřeme nové
            console.log('[SW] Opening new window:', urlToOpen);
            if (clients.openWindow) {
                return clients.openWindow(urlToOpen);
            }
        }).catch(err => {
            console.error('[SW] Notification click error:', err);
            // Fallback - otevřeme nové okno
            if (clients.openWindow) {
                return clients.openWindow(urlToOpen);
            }
        })
    );
});

// Pomocný převodník VAPID klíče
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

// Automatická obnova subscription
self.addEventListener('pushsubscriptionchange', (event) => {
    console.log('[SW] Push subscription change detected');
    event.waitUntil((async () => {
        try {
            // Získej CSRF token pro POSTy (pokud existuje session)
            let csrf = null;
            try {
                const t = await fetch('/push/csrf-token', {credentials: 'include'});
                const tj = await t.json();
                csrf = (tj && tj.csrf_token) ? tj.csrf_token : null;
            } catch (e) {
                // ignore
            }

            const resp = await fetch('/push/vapid-public-key', {credentials: 'include'});
            const j = await resp.json();
            const pub = j && j.publicKey;
            if (!pub) {
                console.error('[SW] No VAPID public key available');
                return;
            }

            const newSub = await self.registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(pub)
            });

            const headers = {'Content-Type': 'application/json'};
            if (csrf) headers['X-CSRFToken'] = csrf;

            await fetch('/push/subscribe', {
                method: 'POST',
                headers,
                body: JSON.stringify({subscription: newSub}),
                credentials: 'include'
            });

            console.log('[SW] Push subscription renewed successfully');
        } catch (e) {
            console.error('[SW] Push subscription renewal error:', e);
        }
    })());
});

