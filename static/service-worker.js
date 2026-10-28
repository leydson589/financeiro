'use strict';
// Store only the public offline explanation. Never cache private pages or financial data.
const CACHE = 'a-dois-offline-v1';
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.add('/offline')).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('a-dois-offline-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).catch(async () => {
    const page = await caches.match('/offline');
    return page || new Response('Sem conexão. Reconecte e abra o sistema novamente.', {status: 503, headers: {'Content-Type': 'text/plain; charset=utf-8'}});
  }));
});
