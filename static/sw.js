// BigRock Tournament — Service Worker
const CACHE = 'bigrock-pwa-v1';

const PRECACHE = [
  '/',
  '/manifest.json',
  '/static/css/base.css',
  '/static/js/nav.js',
  '/static/js/vhf.js',
  '/static/js/offline.js',
  '/static/components/nav.html',
  '/static/images/bigrock.png',
  '/static/images/WHITELOGOBR.png',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(PRECACHE).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const u = e.request.url;
  // Never cache live data endpoints
  if (u.includes('/api/') || u.includes('/scrape/') ||
      u.includes('/hooked') || u.includes('/followed') ||
      u.includes('/participants_data')) return;

  e.respondWith(
    fetch(e.request)
      .then(r => {
        if (r && r.ok) caches.open(CACHE).then(c => c.put(e.request, r.clone()));
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
