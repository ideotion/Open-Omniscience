/*
 * Open Omniscience — i18n engine. GPL-3.0-or-later.
 *
 * Dependency-free, offline: translations are local JSON (locales/<code>.json),
 * keyed by the *English UI string* so the existing interface can be translated
 * without tagging every element. English is the canonical source; any string with
 * no translation falls back to English — so a partial (stub) locale never breaks
 * the UI. Only chrome is translated; data (article titles, source names, counts)
 * is left untouched (a data string only changes if it happens to exactly equal a
 * known UI key — rare, and harmless).
 *
 * Integration (Phase 2): include this script, and add a language picker
 *   <select id="oo-lang-select"> … </select>
 * anywhere — it is auto-wired. Dynamically-rendered chrome (command palette,
 * customize drawer, home cards) is picked up automatically by a debounced
 * MutationObserver, so no apply() calls need to be sprinkled through the app.
 */
(function () {
  "use strict";
  const KEY = "oo.lang";
  const SELECT_ID = "oo-lang-select";
  const ATTRS = ["placeholder", "title", "aria-label"];
  const SKIP = /^(SCRIPT|STYLE|TEXTAREA|CODE|PRE)$/;
  let map = {};                 // English string -> translation (active language)
  let meta = {};                // _meta of the active locale
  const origText = new WeakMap(); // textNode  -> original (English) value
  const origAttr = new WeakMap(); // element   -> { attr: original value }
  let observer = null, pending = false;

  // Translate only when the trimmed text exactly matches a known key
  // (preserving surrounding whitespace). Internal whitespace is normalised for the
  // lookup, so a multi-line HTML paragraph matches a clean single-line JSON key (and
  // markup indentation/wrapping need not be mirrored in the locale files).
  // Unknown strings pass through (English).
  function tr(s) {
    if (!s) return s;
    const lead = s.match(/^\s*/)[0];
    const trail = s.match(/\s*$/)[0];
    const core = s.slice(lead.length, s.length - trail.length);
    if (!core) return s;
    const k = core.replace(/\s+/g, " ");   // normalise internal whitespace for matching
    if (map[k] == null) return s;
    return lead + map[k] + trail;
  }

  function doText(n) {
    if (!n.nodeValue || !n.nodeValue.trim()) return;
    const p = n.parentNode; if (p && SKIP.test(p.nodeName)) return;
    // home-i18n-mixed-language-glance (P1): a container marked data-i18n-dyn owns
    // its own text (it renders itself, in the active language, via direct t()
    // calls -- e.g. #home-stats/#home-tier/#home-status). The walker must NEVER
    // touch or cache text inside one: doing so would cache that already-
    // TRANSLATED string as "the original English" on first sight (origText below
    // is first-seen-wins), permanently poisoning every future lookup for that
    // node under every OTHER language -- a node stays frozen in whichever
    // language it happened to render in first, exactly like the attribute-level
    // opt-out just above this function.
    if (p && p.closest && p.closest("[data-i18n-dyn]")) return;
    let o = origText.get(n);
    if (o === undefined) { o = n.nodeValue; origText.set(n, o); }  // first sight = English
    const t = tr(o);
    if (n.nodeValue !== t) n.nodeValue = t;
  }
  function doAttrs(el) {
    // Opt-out for JS-managed (state-dependent) attributes: an element marked
    // data-i18n-dyn owns its own attribute text and translates it itself via t()
    // (e.g. the airplane button's title flips with online/offline state). Without
    // this, the first-seen-English cache below would revert the dynamic value on the
    // next pass (field test 2026-06-19 #5).
    if (el.hasAttribute && el.hasAttribute("data-i18n-dyn")) return;
    let store = origAttr.get(el);
    for (const a of ATTRS) {
      if (!el.hasAttribute(a)) continue;
      if (!store) { store = {}; origAttr.set(el, store); }
      if (store[a] === undefined) store[a] = el.getAttribute(a);
      const t = tr(store[a]);
      if (el.getAttribute(a) !== t) el.setAttribute(a, t);
    }
  }

  // Idempotent: records each node's original English once, always translates
  // from that original — so it can run any number of times (incl. switching
  // languages, or restoring English with an empty map) without corrupting text.
  function apply(root) {
    root = root || document.body; if (!root) return;
    if (observer) observer.disconnect();
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n; while ((n = w.nextNode())) doText(n);
    if (root.querySelectorAll) root.querySelectorAll("[" + ATTRS.join("],[") + "]").forEach(doAttrs);
    if (observer && document.body) observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }
  function schedule() { if (pending) return; pending = true; setTimeout(() => { pending = false; apply(); }, 120); }

  async function load(code) {
    try {
      const r = await fetch("/static/locales/" + encodeURIComponent(code) + ".json");
      const d = r.ok ? await r.json() : {};
      meta = d._meta || {};
      map = {}; for (const k in d) if (k !== "_meta") map[k] = d[k];
    } catch (e) { map = {}; meta = {}; }
  }
  function setDir() { document.documentElement.dir = meta.dir === "rtl" ? "rtl" : "ltr"; }

  async function setLang(code) {
    localStorage.setItem(KEY, code);
    document.documentElement.lang = code;
    if (code === "en") { map = {}; meta = {}; } else { await load(code); }
    setDir();
    apply();
    // Notify surfaces whose text is derived at RENDER time and so cannot be reached by
    // the string-matching DOM walker above — e.g. CLDR country/continent names on the
    // map and the sources table (field test 2026-06-19 #16: names only updated on a full
    // page refresh). Those listeners re-render in the new locale.
    try { document.dispatchEvent(new CustomEvent("oo:langchange", { detail: { lang: code } })); }
    catch (_e) { /* CustomEvent unsupported -> the page-refresh fallback still works */ }
    const sel = document.getElementById(SELECT_ID);
    if (sel && sel.value !== code) sel.value = code;
  }
  function current() { return localStorage.getItem(KEY) || "en"; }

  async function init() {
    const c = current();
    document.documentElement.lang = c;
    if (c && c !== "en") { await load(c); setDir(); }
    const sel = document.getElementById(SELECT_ID);
    if (sel) { sel.value = c; sel.addEventListener("change", () => setLang(sel.value)); }
    if ("MutationObserver" in window) observer = new MutationObserver(schedule);
    apply();  // also connects the observer
  }

  // t(): string-level lookup for JS-built text (confirm dialogs, toasts) that
  // the DOM observer cannot reach. Same fallback rule: unknown -> English.
  function t(s) { return map[s] == null ? s : map[s]; }

  // tf(): COMPOSITE / interpolated lookup. The KEY is a fixed TEMPLATE with
  // {named} placeholders (a keyable string), and the VALUES are DATA (counts,
  // terms, dates) left untranslated. This is what makes a dynamic, value-bearing
  // string translatable at all: a row like "3 of 10 articles" can never match a
  // static key, but the fixed template "{done} of {total} articles" can be keyed
  // ×12 and the numbers substituted after translation. So the FRAME translates and
  // the DATA does not (the same discipline as translating chrome but never data).
  // Unknown template -> the English template (fallback). A placeholder with no
  // matching var is LEFT VERBATIM (never blanked) so a template/vars mismatch is
  // visible, not silently dropped. Used by JS-built rows and by server-emitted card
  // titles ({title_i18n, title_vars}) whose data (the keyword term) must not translate.
  function tf(s, vars) {
    if (s == null) return s;
    let out = map[s] == null ? s : map[s];
    if (vars) out = out.replace(/\{(\w+)\}/g, function (m, k) {
      return (vars[k] === undefined || vars[k] === null) ? m : String(vars[k]);
    });
    return out;
  }

  window.OOI18N = { setLang, apply, current, init, t, tf, get meta() { return meta; } };
  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
