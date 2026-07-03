/* Open Omniscience — minimal offline service worker (item #69).

   SAFE BY CONSTRUCTION. It only touches SAME-ORIGIN GET requests for the static
   app shell under /static/. It NEVER caches or replays API / data responses
   (/api/, /metrics), non-GET requests, cross-origin requests, or the app document
   ("/") — any of which could go dangerously stale.

   Strategy = NETWORK-FIRST with a cache fallback: an online user always gets the
   fresh asset (this repo's static files change often — a cache-first SW would serve
   stale code against a newer backend), and an offline user gets the last-cached
   shell. Old cache versions are purged on activate.

   SCOPE NOTE: served at /static/sw.js, its maximum scope is /static/. The app
   document is served at "/", which is OUTSIDE that scope, so it is not SW-controlled
   without a 1-line backend route serving this file at root (@app.get("/sw.js")) or a
   `Service-Worker-Allowed: /` header on /static/sw.js. Frontend-only, this stages the
   offline shell cache; see the PR for the backend follow-up. */

const CACHE = "oo-shell-v1";
const SHELL = [
  "/static/app.css",
  "/static/app.js",
  "/static/i18n.js",
  "/static/ooviz.js",
  "/static/osmpbf.js",
  "/static/guis/boot.js",
  "/static/guis/gallery.js",
  "/static/favicon.svg",
];

self.addEventListener("install", (e) => {
  // Precache the shell — best-effort per file so one 404 never fails the whole install.
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;                    // never touch writes
  let url;
  try { url = new URL(req.url); } catch (_e) { return; }
  if (url.origin !== self.location.origin) return;     // same-origin only
  if (!url.pathname.startsWith("/static/")) return;    // the static shell ONLY — never /api, /metrics, or "/"
  // Network-first: fresh when online, last-cached when offline. Only a successful,
  // same-origin, basic 200 is cached (never an opaque/error response).
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.status === 200 && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req))
  );
});
