const CACHE = "findmycat-v4";

const STATIC_ASSETS = [
  ".",
  "index.html",
  "css/app.css",
  "src/app.js",
  "src/store.js",
  "src/utils.js",
  "src/api/traccar.js",
  "src/api/hologram.js",
  "src/api/geocode.js",
  "src/screens/login.js",
  "src/screens/home.js",
  "src/components/map.js",
  "src/components/drawer.js",
  "src/components/device-modal.js",
  "src/components/geofence-modal.js",
  "manifest.json",
  "config.js",
];

// Install: cache all static assets and activate immediately
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Activate: remove old caches and take control of all clients
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// Fetch: network-first for API/cross-origin, cache-first for everything else
self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  const isApi = url.pathname.startsWith("/api/");
  const isCrossOrigin = url.hostname !== self.location.hostname;

  // Cache API only supports GET — put() on other methods throws
  const cacheable = request.method === "GET";

  if (isApi || isCrossOrigin) {
    // Network first, fall back to cache
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (cacheable) {
            const clone = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
  } else {
    // Cache first, then network (cache successful network response)
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) {
          return cached;
        }
        return fetch(request).then((response) => {
          if (response.ok && cacheable) {
            const clone = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, clone));
          }
          return response;
        });
      })
    );
  }
});
