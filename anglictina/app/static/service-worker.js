// Service Worker pro Knowix PWA
const STATIC_CACHE = 'knowix-static-v1';
const DYNAMIC_CACHE = 'knowix-dynamic-v1';
const OFFLINE_URL = '/offline';

// Seznam statických souborů k precache
const PRECACHE_ASSETS = [
    '/', '/offline', '/static/style.css', '/static/mobile_header.css', '/static/pic/logo.webp', '/static/favicon.ico', '/static/manifest.json'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(STATIC_CACHE).then(cache => cache.addAll(PRECACHE_ASSETS)).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then(keys => Promise.all(
            keys.filter(k => ![STATIC_CACHE, DYNAMIC_CACHE].includes(k)).map(k => caches.delete(k))
        )).then(() => self.clients.claim())
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
                if (cached) return cached;
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

// Push notifikace
self.addEventListener('push', (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
    }
    const title = data.title || 'Knowix aktualizace';
    const options = {
        body: data.body || 'Nová lekce je dostupná!',
        icon: '/static/pic/logo.webp',
        badge: '/static/pic/logo.webp',
        data: {url: data.url || '/'}
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const urlToOpen = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/';
    event.waitUntil(
        clients.matchAll({type: 'window', includeUncontrolled: true}).then(windowClients => {
            for (const client of windowClients) {
                if (client.url === urlToOpen && 'focus' in client) return client.focus();
            }
            if (clients.openWindow) return clients.openWindow(urlToOpen);
        })
    );
});
