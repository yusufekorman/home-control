const CACHE_VERSION = "home-control-v1";
const OFFLINE_URL = "/static/offline.html";

const PRECACHE_URLS = [
  OFFLINE_URL,
  "/manifest.webmanifest",
  "/static/icons/icon.svg",
  "/static/icons/maskable-icon.svg",
  "/static/icons/apple-touch-icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(PRECACHE_URLS)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_VERSION)
            .map((key) => caches.delete(key)),
        ),
      ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET") {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const responseClone = response.clone();
          caches.open(CACHE_VERSION).then((cache) => {
            cache.put(request, responseClone);
          });
          return response;
        })
        .catch(async () => {
          const cache = await caches.open(CACHE_VERSION);
          const cachedPage = await cache.match(request);
          if (cachedPage) {
            return cachedPage;
          }
          return cache.match(OFFLINE_URL);
        }),
    );
    return;
  }

  if (
    url.origin === self.location.origin &&
    url.pathname.startsWith("/static/")
  ) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const networkFetch = fetch(request)
          .then((response) => {
            const responseClone = response.clone();
            caches.open(CACHE_VERSION).then((cache) => {
              cache.put(request, responseClone);
            });
            return response;
          })
          .catch(() => cached);

        return cached || networkFetch;
      }),
    );
  }
});
