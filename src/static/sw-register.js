/* PWA: register the offline shell service worker (item #69). External file so index.html
   carries no inline <script> (the PR-H decomposition invariant). Best-effort + guarded so
   it can never break boot; the SW only caches the static shell, never API/data responses.

   Scope is /static/ BY DESIGN. A root-scoped variant existed (a backend route serving
   this file at "/" with Service-Worker-Allowed: /) and was removed 2026-08-04: nothing
   registered it, and sw.js's own fetch guard returns early for "/" regardless, so it
   could not have served the app document even with the scope. This worker caches shell
   ASSETS and claims nothing more. */
(function () {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/static/sw.js").catch(function () {});
  });
})();
