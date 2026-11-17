self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter((name) => name.startsWith('workbox-precache-'))
      .map((name) => caches.delete(name)));
    await self.clients.claim();
    await self.registration.unregister();
  })());
});
