/* PWA: register the offline shell service worker (item #69). External file so index.html
   carries no inline <script> (the PR-H decomposition invariant). Best-effort + guarded so
   it can never break boot; the SW only caches the static shell, never API/data responses.
   Served at /static/sw.js (scope /static/); full offline navigation of "/" needs a backend
   route serving it at root — see the PR. */
(function () {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/static/sw.js").catch(function () {});
  });
})();
