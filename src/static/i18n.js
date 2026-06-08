/*
 * Open Omniscience — i18n engine. GPL-3.0-or-later.
 *
 * Dependency-free, offline: translations are local JSON (locales/<code>.json),
 * keyed by the *English UI string* so the existing interface can be translated
 * without tagging every element. English is the canonical source; any string with
 * no translation falls back to English — so a partial (stub) locale never breaks
 * the UI. Only chrome is translated; data (article titles, source names, counts)
 * is left untouched.
 *
 * Phase 1 (this file): the engine + locale scaffold. Phase 2 (next, needs a
 * browser check): include this script in index.html / desk.html, add a language
 * picker calling OOI18N.setLang(code), and call OOI18N.apply() after dynamic
 * renders. See docs/I18N.md.
 */
(function () {
  "use strict";
  const KEY = "oo.lang";
  const ATTRS = ["placeholder", "title", "aria-label"];
  let map = {};            // English string -> translation (for the active language)
  let meta = {};           // _meta of the active locale
  let captured = false;
  const nodeOrig = [];     // [{node, text}] — original English text nodes (captured once)
  const attrOrig = [];     // [{el, attr, text}]

  // Capture the original (English) DOM once, so switching languages always
  // translates FROM English rather than from an already-translated string.
  function captureOnce(root) {
    if (captured) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.nodeValue && n.nodeValue.trim() &&
        n.parentNode && !/^(SCRIPT|STYLE)$/.test(n.parentNode.nodeName))
        ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
    });
    let n; while ((n = walker.nextNode())) nodeOrig.push({ node: n, text: n.nodeValue });
    root.querySelectorAll("[" + ATTRS.join("],[") + "]").forEach((el) =>
      ATTRS.forEach((a) => { if (el.hasAttribute(a)) attrOrig.push({ el, attr: a, text: el.getAttribute(a) }); }));
    captured = true;
  }

  // Swap only when the trimmed text exactly matches a known key (preserve whitespace).
  function tr(s) {
    const k = (s || "").trim();
    if (!k || map[k] == null) return s;
    const i = s.indexOf(k);
    return s.slice(0, i) + map[k] + s.slice(i + k.length);
  }

  function apply() {
    captureOnce(document.body);
    for (const o of nodeOrig) o.node.nodeValue = tr(o.text);
    for (const o of attrOrig) o.el.setAttribute(o.attr, tr(o.text));
  }

  async function load(code) {
    try {
      const r = await fetch("/static/locales/" + encodeURIComponent(code) + ".json");
      const d = r.ok ? await r.json() : {};
      meta = d._meta || {};
      map = {}; for (const k in d) if (k !== "_meta") map[k] = d[k];
    } catch (e) { map = {}; meta = {}; }
  }

  function setDir() {
    document.documentElement.dir = meta.dir === "rtl" ? "rtl" : "ltr";
  }

  async function setLang(code) {
    localStorage.setItem(KEY, code);
    document.documentElement.lang = code;
    if (code === "en") { map = {}; meta = {}; } else { await load(code); }
    setDir();
    apply();
  }

  function current() { return localStorage.getItem(KEY) || "en"; }

  async function init() {
    const c = current();
    document.documentElement.lang = c;
    if (c && c !== "en") { await load(c); setDir(); }
    apply();
  }

  window.OOI18N = { setLang, apply, current, init, get meta() { return meta; } };
  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
