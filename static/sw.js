const CACHE_NAME = 'noteed-cache-v8';
const urlsToCache = [
  '/',
  '/static/css/style.css',
  '/static/images/noteedhalf.png',
  '/static/images/noteedfull.png',
  '/static/images/logo.png',
  '/static/manifest.json'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        return cache.addAll(urlsToCache);
      })
      .catch(err => {
        console.warn('Service Worker cache.addAll non-critical warning:', err);
      })
  );
});

self.addEventListener('activate', event => {
  const cacheWhitelist = [CACHE_NAME];
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheWhitelist.indexOf(cacheName) === -1) {
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  // Cache API only supports GET requests
  if (event.request.method !== 'GET') {
    return;
  }

  const url = new URL(event.request.url);

  // Pass through cross-origin requests directly
  if (url.origin !== self.location.origin) {
    return;
  }

  // API endpoints: Network-Only with graceful fallback to prevent unhandled rejected promises
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(err => {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      })
    );
    return;
  }

  // HTML navigation requests: Network First, fallback to cache
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          if (response && response.status === 200) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, responseClone));
          }
          return response;
        })
        .catch(() => {
          return caches.match(event.request, { ignoreSearch: true })
            .then(cached => cached || caches.match('/'));
        })
    );
    return;
  }

  // Local static assets (CSS, JS, Images, Manifest): Cache First, fallback to network
  event.respondWith(
    caches.match(event.request, { ignoreSearch: true })
      .then(cachedResponse => {
        if (cachedResponse) {
          // Revalidate in background
          fetch(event.request)
            .then(networkResponse => {
              if (networkResponse && networkResponse.status === 200) {
                caches.open(CACHE_NAME).then(cache => cache.put(event.request, networkResponse));
              }
            })
            .catch(() => {});
          return cachedResponse;
        }

        return fetch(event.request)
          .then(networkResponse => {
            if (networkResponse && networkResponse.status === 200) {
              const clone = networkResponse.clone();
              caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
            }
            return networkResponse;
          })
          .catch(() => {
            // Fallback for static assets if offline
            return caches.match('/static/css/style.css', { ignoreSearch: true });
          });
      })
      .catch(() => {
        return fetch(event.request).catch(() => new Response('', { status: 408 }));
      })
  );
});
