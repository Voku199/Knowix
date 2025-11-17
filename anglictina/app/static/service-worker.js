// Service Worker pro Knowix PWA
const STATIC_CACHE = 'knowix-static-v2';
const DYNAMIC_CACHE = 'knowix-dynamic-v2';
const OFFLINE_URL = '/offline';

// Seznam statických souborů k precache
const PRECACHE_ASSETS = [
    '/', '/offline', '/static/style.css', '/static/mobile_header.css',
    '/static/pic/logo.webp', '/static/favicon.ico', '/static/manifest.json'
];

// Detekce iOS
function isIOS() {
    return /iphone|ipad|ipod/i.test(navigator.userAgent);
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

// Push notifikace - JEDNA definice
self.addEventListener('push', (event) => {
    console.log('[SW] Push event received:', event);

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
        requireInteraction: false
    };

    // Pro iOS: zkrátit text pokud je příliš dlouhý
    if (isIOS() && body.length > 100) {
        options.body = body.substring(0, 100) + '...';
    }

    // Vibrace pokud jsou podporovány
    if ('vibrate' in navigator) {
        options.vibrate = [100, 50, 100];
    }

    console.log('[SW] Showing notification with options:', options);

    event.waitUntil(
        self.registration.showNotification(title, options)
            .then(() => console.log('[SW] Notification shown successfully'))
            .catch(err => {
                console.error('[SW] Notification error:', err);
                // Fallback pro iOS - zkusíme bez tagu
                if (isIOS()) {
                    delete options.tag;
                    return self.registration.showNotification(title, options);
                }
                throw err;
            })
    );
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