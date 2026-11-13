/*
 * Simple mode, first paint (invariant #34, ruling R682). GPL-3.0-or-later.
 *
 * Runs in <head>, before the body paints, so a reader who chose simple mode never sees the
 * full interface flash first. It only reads two per-device flags and sets one attribute;
 * it touches no network and no server state.
 *
 *   localStorage  oo.ui.simple = "1"  the reader's choice (the top-bar switch)
 *   sessionStorage oo.ui.peek  = "1"  a tool was opened in full view from simple mode, in
 *                                     this browser tab; the full view shows a "Back to simple
 *                                     view" bar until the reader goes back or switches off
 */
(function () {
  "use strict";
  var simple = false, peek = false;
  try { simple = localStorage.getItem("oo.ui.simple") === "1"; } catch (e) { /* storage blocked: full mode */ }
  try { peek = sessionStorage.getItem("oo.ui.peek") === "1"; } catch (e) { /* storage blocked */ }
  var root = document.documentElement;
  if (simple && !peek) {
    root.setAttribute("data-mode", "simple");
    // An alternative skin from the GUIs gallery restyles the FULL interface's DOM; simple mode
    // brings its own layout, so the skin steps aside while simple mode is on (the stored choice
    // is untouched and returns with the full view).
    root.removeAttribute("data-ui");
  } else if (simple && peek) {
    root.setAttribute("data-mode", "peek");
  }
})();
