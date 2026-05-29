// BigRock Tournament -- Service Worker
// bump CACHE version whenever index.html or cached assets change.
// activate clears old cache AND force-reloads open pages for fresh HTML.
const CACHE = 'bigrock-pwa-v3';

const PRECACHE = [
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
      .then(() => self.clients.matchAll({ type: 'window', includeUncontrolled: true }))
      .then(clients => Promise.all(clients.map(c => c.navigate(c.url).catch(() => {}))))
  );
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const u = new URL(e.request.url);
  if (u.origin !== self.location.origin) return;
  if (u.pathname === '/' || u.pathname === '/offline') return;
  if (u.pathname.startsWith('/api/') || u.pathname.startsWith('/scrape/') ||
      u.pathname.includes('/hooked') || u.pathname.includes('/followed') ||
      u.pathname.includes('/participants_data')) return;
  e.respondWith(
    fetch(e.request)
      .then(r => {
        if (r && r.ok) caches.open(CACHE).then(c => c.put(e.request, r.clone()));
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});