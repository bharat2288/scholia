// Minimal service worker for PWA installability.
// Network-first strategy: always try network, fall back to cache.
// No aggressive caching — Scholia is a live app that needs fresh data.

const CACHE_NAME = 'scholia-v1'

// Cache the app shell on install
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll([
        '/',
        '/scholia.svg',
      ])
    })
  )
  self.skipWaiting()
})

// Clean up old caches on activate
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) => {
      return Promise.all(
        names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))
      )
    })
  )
  self.clients.claim()
})

// Network-first: try network, fall back to cache for navigation requests
self.addEventListener('fetch', (event) => {
  // Only handle same-origin navigation requests
  if (event.request.mode !== 'navigate') return

  event.respondWith(
    fetch(event.request).catch(() => {
      return caches.match('/') || new Response('Offline', { status: 503 })
    })
  )
})
