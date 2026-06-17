/*
 * Open Omniscience — alternative interfaces ("GUIs") gallery: boot loader.
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 *
 * Maintainer-ruled 2026-06-17 (sandbox gallery): eight opt-in alternative
 * interfaces, selectable from Settings -> GUIs, applied at boot. Each one is a
 * SHARED-CORE SHELL: it reuses the ONE app.js render logic (which targets
 * elements by id) under a different, fully-scoped skin (html[data-ui="<id>"])
 * plus, for a couple of them, a thin interaction layer. The default interface
 * is untouched and stays the guarded reference.
 *
 * Non-negotiables preserved BY CONSTRUCTION (the alternatives only restyle /
 * re-lay-out the SAME DOM, never remove a node): caveats stay visible, the
 * network-consent popup is unchanged, no interface invents a score, "deduced /
 * never confirmed" labels remain. tests/test_gui_alternatives.py enforces that
 * no skin hides a caveat/consent surface and that every asset is local.
 *
 * Zero network: every asset (skins + the vendored Alpine.js) is served from
 * 127.0.0.1/static. This file runs in <head> (synchronously) so the active
 * skin is applied before first paint — no flash of the default interface.
 */
(function () {
  "use strict";

  // -- The registry --------------------------------------------------------- //
  // id      : stored in localStorage oo.ui.gui; the html[data-ui] value + the
  //           skin/JS file stem.
  // name    : a proper noun (NOT translated).
  // engine  : "vanilla" | "alpine" (shown as a badge; Alpine is vendored MIT).
  // css/js  : assets under /static/guis/ (js optional; self-gates on app.js).
  var GUIS = [
    { id: "aurora",    name: "Aurora",    engine: "vanilla", css: "ui-aurora.css" },
    { id: "atlas",     name: "Atlas",     engine: "vanilla", css: "ui-atlas.css" },
    { id: "command",   name: "Command",   engine: "alpine",  css: "ui-command.css",   js: "ui-command.js" },
    { id: "field",     name: "Field",     engine: "vanilla", css: "ui-field.css" },
    { id: "focus",     name: "Focus",     engine: "vanilla", css: "ui-focus.css" },
    { id: "terminal",  name: "Terminal",  engine: "vanilla", css: "ui-terminal.css" },
    { id: "canvas",    name: "Canvas",    engine: "alpine",  css: "ui-canvas.css",    js: "ui-canvas.js" },
    { id: "editorial", name: "Editorial", engine: "vanilla", css: "ui-editorial.css" }
  ];
  var BASE = "/static/guis/";
  var UI_KEY = "oo.ui";

  function byId(id) {
    for (var i = 0; i < GUIS.length; i++) { if (GUIS[i].id === id) return GUIS[i]; }
    return null;
  }
  function readUi() {
    try { return JSON.parse(localStorage.getItem(UI_KEY) || "{}") || {}; }
    catch (e) { return {}; }
  }
  function activeId() {
    var g = readUi().gui;
    return byId(g) ? g : "";          // "" == the default interface
  }

  function injectCss(href, id) {
    if (document.getElementById(id)) return;
    var l = document.createElement("link");
    l.rel = "stylesheet"; l.href = BASE + href; l.id = id;
    (document.head || document.documentElement).appendChild(l);
  }
  function injectJs(src, id) {
    if (id && document.getElementById(id)) return;
    var s = document.createElement("script");
    s.src = (src.indexOf("/") === 0) ? src : BASE + src;
    if (id) s.id = id;
    (document.head || document.documentElement).appendChild(s);
  }

  // -- whenReady: run AFTER app.js has booted (its globals exist) and the DOM
  //    is parsed. Skin JS self-gates on this, so injection order never matters. //
  function whenReady(fn) {
    function go() {
      // app.js defines showTab at the end of <body>; poll briefly for it so a
      // skin never touches the DOM before the core has wired itself up.
      var tries = 0;
      (function poll() {
        if (typeof window.showTab === "function") { try { fn(); } catch (e) { /* fail-safe */ } return; }
        if (tries++ > 200) { try { fn(); } catch (e) { /* give up gracefully */ } return; }
        setTimeout(poll, 25);
      })();
    }
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { setTimeout(go, 0); });
    } else {
      setTimeout(go, 0);
    }
  }

  // -- loadAlpine: inject the vendored Alpine once. It auto-starts on the next
  //    microtask, so the caller must build its x-data DOM and register any
  //    document 'alpine:init' listener BEFORE calling this. Guarded: one load. //
  function loadAlpine(cb) {
    if (window.Alpine) { if (cb) cb(window.Alpine); return; }
    var existing = document.getElementById("oo-alpine");
    if (existing) { existing.addEventListener("load", function () { if (cb) cb(window.Alpine); }); return; }
    var s = document.createElement("script");
    s.src = BASE + "vendor/alpine.min.js";
    s.id = "oo-alpine";
    s.addEventListener("load", function () { if (cb) cb(window.Alpine); });
    (document.head || document.documentElement).appendChild(s);
  }

  // -- Apply the active interface (called immediately, in <head>). ----------- //
  function applyActive() {
    var id = activeId();
    var root = document.documentElement;
    // gallery.css styles the Settings -> GUIs picker; always present so the
    // gallery looks right even under the default interface.
    injectCss("gallery.css", "oo-gui-gallery-css");
    if (!id) { root.removeAttribute("data-ui"); return; }
    var g = byId(id);
    if (!g) { root.removeAttribute("data-ui"); return; }
    root.setAttribute("data-ui", id);          // scope: html[data-ui="<id>"]
    injectCss(g.css, "oo-gui-css");
    if (g.js) injectJs(g.js, "oo-gui-js");      // skin JS self-gates via whenReady
  }

  // -- setActive: persist the choice into the shared oo.ui blob, then reload so
  //    the skin applies cleanly from boot (deterministic, no half-torn state). //
  function setActive(id) {
    var u = readUi();
    if (id && byId(id)) u.gui = id; else delete u.gui;
    try { localStorage.setItem(UI_KEY, JSON.stringify(u)); } catch (e) { /* private mode */ }
    location.reload();
  }

  window.OOGUIs = {
    BASE: BASE,
    all: GUIS,
    byId: byId,
    activeId: activeId,
    setActive: setActive,
    whenReady: whenReady,
    loadAlpine: loadAlpine
  };

  try { applyActive(); } catch (e) { /* never break the base app */ }
})();
