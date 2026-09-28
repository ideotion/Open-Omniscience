/* Open Omniscience — the external-link confirm for the server-rendered readers.
 *
 * The article reader (/api/articles/{id}/view) and the law reader
 * (/api/law/documents/{id}/view) are standalone pages that do not load the SPA. Any
 * link that leaves the local copy (a.ext) is confirmed first, honest about the
 * exposure (invariant #7). This was an inline <script> in each page; it moved here so
 * the CSP can drop script-src 'unsafe-inline' (Q1127 = a). The page names which
 * question it asks with <body data-ext-confirm="article|law">, and both consent
 * strings go through the i18n engine (x12), as they did inline.
 */
(function () {
  "use strict";
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a.ext");
    if (!a) return;
    e.preventDefault();
    var t = (window.OOI18N && OOI18N.t) ? OOI18N.t : function (x) { return x; };
    var law = document.body.getAttribute("data-ext-confirm") === "law";
    var ok = window.confirm(
      (law ? t("Open the official source on the public web?") : t("Open an EXTERNAL site on the public web?")) +
      "\n\n" + a.href + "\n\n" +
      t("This leaves your local copy and makes a live request from your machine — the site may see your visit. Continue?"));
    if (ok) window.open(a.href, "_blank", "noopener");
  });
})();
