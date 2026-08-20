/* Open Omniscience — minimal offline service worker (item #69).

   SAFE BY CONSTRUCTION. It only touches SAME-ORIGIN GET requests for the static
   app shell under /static/. It NEVER caches or replays API / data responses
   (/api/, /metrics), non-GET requests, cross-origin requests, or the app document
   ("/") — any of which could go dangerously stale.

   Strategy = NETWORK-FIRST with a cache fallback: an online user always gets the
   fresh asset (this repo's static files change often — a cache-first SW would serve
   stale code against a newer backend), and an offline user gets the last-cached
   shell. Old cache versions are purged on activate.

   SCOPE NOTE: served at /static/sw.js, its maximum scope is /static/ — and that is
   the whole intent. The app document at "/" is deliberately NOT controlled: the fetch
   handler below returns early for every path outside /static/, so this worker could
   not serve the document at any scope. A root-scoped route existed to grant scope "/"
   and was removed 2026-08-04 as dead scaffolding (nothing registered it, and this
   guard declined "/" regardless). What remains is honest: an offline cache of the
   shell ASSETS, which is what the SHELL list below actually contains. */

const CACHE = "oo-shell-v5";
const SHELL = [
  "/static/app.js",
  "/static/app-settings.js",
  "/static/app-backup.js",
  "/static/app-library.js",
  "/static/app-sources.js",
  "/static/app-markets.js",
  "/static/app-insights.js",
  "/static/app-diagnostics.js",
  "/static/app-corpus.js",
  "/static/app-map.js",
  "/static/app-analysis.js",
  "/static/app-ai-tools.js",
  "/static/app-boot.js",
  "/static/app.css",
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
