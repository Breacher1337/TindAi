// TindAI Service Worker - Root Scoped ('/')
// Cache-First for static/CDN assets, Network-First for HTML/POS navigation, and Background Sync.

const CACHE_NAME = 'tindai-cache-v1';

const PRECACHE_ASSETS = [
  '/',
  '/pos/',
  '/manifest.json',
  '/static/manifest.json',
  '/static/js/offline_store.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  'https://cdn.tailwindcss.com',
  'https://unpkg.com/htmx.org@2.0.3',
  'https://unpkg.com/alpinejs@3.14.3/dist/cdn.min.js',
  'https://unpkg.com/lucide@latest'
];

// Install: pre-cache critical shell and CDN assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Use cache.addAll with individual catch so failures on external CDNs don't abort install
      return Promise.allSettled(
        PRECACHE_ASSETS.map((url) =>
          fetch(url, { mode: 'no-cors' })
            .then((res) => cache.put(url, res))
            .catch((err) => console.warn('[SW] Pre-cache failed for:', url, err))
        )
      );
    }).then(() => self.skipWaiting())
  );
});

// Activate: clean up obsolete caches and claim clients immediately
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: Strategy selector
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Non-GET requests (e.g. POST /checkout/) bypass SW cache
  if (request.method !== 'GET') {
    return;
  }

  // Check if static or CDN asset -> Cache-First
  const isCdn = url.hostname.includes('tailwindcss.com') ||
                url.hostname.includes('unpkg.com');
  const isStatic = url.pathname.startsWith('/static/') ||
                   url.pathname.endsWith('.js') ||
                   url.pathname.endsWith('.css') ||
                   url.pathname.endsWith('.png') ||
                   url.pathname.endsWith('.svg') ||
                   url.pathname.endsWith('.json');

  if (isCdn || isStatic) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }
        return fetch(request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseToCache = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseToCache);
            });
          }
          return networkResponse;
        }).catch(() => {
          // Return cached version by URL string if available
          return caches.match(url.pathname);
        });
      })
    );
    return;
  }

  // Navigation or HTML requests (e.g. /pos/, /) -> Network-First with cache fallback
  const isNav = request.mode === 'navigate' ||
                (request.headers.get('accept') && request.headers.get('accept').includes('text/html'));

  if (isNav || url.pathname === '/pos/' || url.pathname === '/') {
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseToCache = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseToCache);
            });
          }
          return networkResponse;
        })
        .catch(() => {
          return caches.match(request).then((cached) => {
            if (cached) return cached;
            return caches.match('/pos/').then((posFallback) => {
              if (posFallback) return posFallback;
              return caches.match('/');
            });
          });
        })
    );
    return;
  }

  // Default: Network with Cache Fallback
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});

// Background Sync Event Listener
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-offline-transactions' || event.tag === 'tindai-sync') {
    event.waitUntil(
      self.clients.matchAll().then((clients) => {
        clients.forEach((client) => {
          client.postMessage({
            type: 'TRIGGER_OFFLINE_SYNC',
            tag: event.tag
          });
        });
      })
    );
  }
});
