/*
 * Open Omniscience — simple mode (invariant #34, ruling R682). GPL-3.0-or-later.
 *
 * A second, task-first interface over the SAME page, the SAME server routes and the SAME
 * chrome. One switch in the top bar (#ui-simple-toggle) turns it on and off; the choice is
 * remembered on this device (localStorage "oo.ui.simple"). Off, nothing here runs beyond
 * painting the switch, and the full interface is exactly what it was.
 *
 * What simple mode changes: the sidebar lists five plain views (Today, Read, Search, More
 * tools; Numbers follows) instead of the thirteen tabs, and the tab pages are replaced by those
 * views. What it never changes or hides (R682): the network consent popup (it calls the full
 * app's own toggleNetwork / ensureOnline, never a second POST), airplane mode and the Tor or
 * Protected-mode state in the top bar, the lock redirect, destructive-action confirmations,
 * toasts and errors.
 *
 * Transparency is one step away, not deleted: every figure and card carries an ⓘ button
 * (keyboard, touch and screen-reader reachable) that opens its source, date, method, n and
 * caveat, and a figure that is approximate, partial or stale also shows a small visible mark
 * (~ ◐ ◷) so the reader knows the ⓘ holds something worth opening.
 *
 * Any route into a full-mode tab (More tools, Settings, Help, the Ctrl+K palette, a link in a
 * toast) opens the full view for this browser tab with a "Back to simple view" bar; one click
 * returns to the simple view the reader left, with its search still in place.
 *
 * Rendering: Preact 10 + hooks + htm, vendored under simple/vendor (MIT / Apache-2.0, sha256
 * pinned, no eval, so the CSP's script-src 'self' holds). No request leaves this origin.
 */
(function () {
  "use strict";
  var P = window.preact, H = window.preactHooks, HTM = window.htm;
  var ROOT = document.documentElement;
  var K_SIMPLE = "oo.ui.simple", K_PEEK = "oo.ui.peek", K_STATE = "oo.ui.simple.state";

  // ---------------------------------------------------------------- storage helpers
  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* blocked */ } }
  function ssGet(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
  function ssSet(k, v) { try { if (v == null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch (e) { /* blocked */ } }

  function mode() { return ROOT.getAttribute("data-mode") || "full"; }
  function isSimple() { return mode() === "simple"; }

  // ---------------------------------------------------------------- strings (x12)
  // Simple mode's own strings live in simple/locales/<lang>.json, keyed by the English text,
  // so the twelve shared locale files are untouched. A key missing there falls back to the
  // main engine (OOI18N.t), then to English.
  var STR = {};
  var strLang = "en";
  function curLang() { try { return (window.OOI18N && OOI18N.current()) || "en"; } catch (e) { return "en"; } }
  function loadStrings() {
    var l = curLang();
    if (l === strLang && (l === "en" || Object.keys(STR).length)) return Promise.resolve();
    strLang = l;
    if (l === "en") { STR = {}; return Promise.resolve(); }
    return fetch("/static/simple/locales/" + encodeURIComponent(l) + ".json")
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (d) { STR = (d && d.strings) || {}; })
      .catch(function () { STR = {}; });
  }
  function t(s, vars) {
    var o = STR[s] != null ? STR[s] : ((window.OOI18N && OOI18N.t) ? OOI18N.t(s) : s);
    if (vars) o = String(o).replace(/\{(\w+)\}/g, function (m, k) { return vars[k] == null ? m : String(vars[k]); });
    return o;
  }
  // A server-provided template (briefing cards) goes through the MAIN engine, where those
  // keys already live x12.
  function tf(s, vars) { return (window.OOI18N && OOI18N.tf) ? OOI18N.tf(s, vars) : t(s, vars); }

  // ---------------------------------------------------------------- formatting
  function fmtInt(n) {
    if (n == null || isNaN(n)) return "—";
    try { return new Intl.NumberFormat(curLang()).format(n); } catch (e) { return String(n); }
  }
  // A date that Intl cannot format falls back to the app's own ISO helper, which isolates it
  // under a right-to-left page (the raw-date ratchet, R258).
  function isoDate(iso) { return typeof window.ooIsoDate === "function" ? window.ooIsoDate(iso) : String(iso).split("T")[0]; }
  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(String(iso).replace(" ", "T"));
    if (isNaN(d)) return isoDate(iso);
    try { return new Intl.DateTimeFormat(curLang(), { year: "numeric", month: "short", day: "numeric" }).format(d); }
    catch (e) { return isoDate(iso); }
  }
  function fmtTime(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return String(iso);
    try { return new Intl.DateTimeFormat(curLang(), { dateStyle: "medium", timeStyle: "short" }).format(d); }
    catch (e) { return String(iso); }
  }
  function langName(code) {
    if (!code) return "";
    try { return new Intl.DisplayNames([curLang()], { type: "language" }).of(code) || code; } catch (e) { return code; }
  }
  function apiCall(path, opts) {
    if (typeof window.api === "function") return window.api(path, opts || {});
    return fetch(path, opts).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
  }

  // ---------------------------------------------------------------- the switch
  var _origShowTab = null;
  var _internal = 0;      // >0 while simple mode itself drives the full app (never a peek)
  var _booted = false;    // the full app's own boot navigation has run

  function paintSwitch() {
    var b = document.getElementById("ui-simple-toggle");
    if (!b) return;
    var on = isSimple();
    b.setAttribute("aria-checked", on ? "true" : "false");
    b.classList.toggle("on", on);
    var lbl = b.querySelector(".simple-switch-label");
    if (lbl) lbl.textContent = t("Simple");
    b.title = on
      ? t("Simple view is on. Click to return to the full view.")
      : t("Switch to the simple view: fewer screens, details one click away.");
    b.setAttribute("aria-label", t("Simple view"));
    var back = document.getElementById("simple-back");
    if (back) {
      var msg = back.querySelector(".simple-back-msg");
      var btn = back.querySelector("button");
      if (msg) msg.textContent = t("This tool is part of the full view.");
      if (btn) btn.textContent = t("Back to simple view");
      back.setAttribute("aria-label", t("Simple view"));
    }
  }

  // The GUIs gallery keeps its skin in localStorage "oo.ui" as JSON, field "gui" (guis/boot.js).
  function hasSkin() {
    try { var u = JSON.parse(lsGet("oo.ui") || "null"); var g = u && u.gui; return !!(g && g !== "default"); }
    catch (e) { return false; }
  }

  // Going (back) to simple mode drops the full view's query string, so a reload stays simple.
  function clearDeepLink() {
    if (!location.search) return;
    try { history.replaceState(history.state, "", location.pathname + location.hash); } catch (e) { /* ignore */ }
  }
  function enterSimple() {
    lsSet(K_SIMPLE, "1");
    ssSet(K_PEEK, null);
    clearDeepLink();
    if (hasSkin()) { location.reload(); return; }   // a gallery skin re-initialises on load
    ROOT.setAttribute("data-mode", "simple");
    ROOT.removeAttribute("data-ui");
    mount();
    paintSwitch();
    focusMain();
  }
  function leaveSimple() {
    lsSet(K_SIMPLE, null);
    ssSet(K_PEEK, null);
    if (hasSkin()) { location.reload(); return; }
    ROOT.setAttribute("data-mode", "full");
    unmount();
    paintSwitch();
    var tab = (location.hash || "").replace(/^#/, "") || "home";
    callShowTab(tab);
  }
  // A full-view tool opened from simple mode: the preference stays "simple", this browser tab
  // shows the full view with a bar that brings the reader back (R682 (b)).
  function peekFull(tab, after) {
    saveState();
    ssSet(K_PEEK, "1");
    ROOT.setAttribute("data-mode", "peek");
    unmount();
    paintSwitch();
    callShowTab(tab);
    if (typeof after === "function") { try { after(); } catch (e) { /* the full app reports its own errors */ } }
  }
  function backToSimple() {
    ssSet(K_PEEK, null);
    clearDeepLink();
    ROOT.setAttribute("data-mode", "simple");
    ROOT.removeAttribute("data-ui");
    mount();
    paintSwitch();
    focusMain();
  }
  function onSwitch() {
    var m = mode();
    if (m === "simple") leaveSimple();
    else if (m === "peek") backToSimple();
    else enterSimple();
  }
  function callShowTab(tab) {
    if (typeof _origShowTab !== "function") return;
    _internal++;
    try { _origShowTab(tab); } finally { _internal--; }
  }
  function focusMain() {
    var m = document.getElementById("simple-root");
    if (m) { try { m.focus({ preventScroll: false }); } catch (e) { /* older browsers */ } }
    window.scrollTo(0, 0);
  }
  // Was this navigation asked for by the reader, or is it the full app's own boot or poll?
  // A reader's click or key gives the page transient activation; boot does not.
  function readerAsked() {
    if (!_booted) return false;
    var ua = navigator.userActivation;
    return ua ? !!ua.isActive : true;
  }
  function wrapShowTab() {
    if (typeof window.showTab !== "function" || window.showTab.__simpleWrapped) return;
    _origShowTab = window.showTab;
    var wrapped = function (name) {
      if (isSimple() && !_internal && readerAsked()) { peekFull(name); return; }
      return _origShowTab.apply(this, arguments);
    };
    wrapped.__simpleWrapped = true;
    window.showTab = wrapped;
  }

  // ---------------------------------------------------------------- state
  var store = { view: "today", query: "", ids: null, countries: null, langs: null, label: "", order: "recent" };
  var subs = [];
  function saveState() { ssSet(K_STATE, JSON.stringify(store)); }
  function loadState() {
    try {
      var s = JSON.parse(ssGet(K_STATE) || "null");
      if (s && typeof s === "object") Object.assign(store, s);
      // Only bare country codes survive a reload; anything else would become a hidden scope.
      store.countries = Array.isArray(store.countries)
        ? store.countries.filter(function (c) { return typeof c === "string" && /^[a-z]{2,3}$/i.test(c); })
        : null;
      if (store.countries && !store.countries.length) store.countries = null;
      store.langs = Array.isArray(store.langs)
        ? store.langs.filter(function (c) { return typeof c === "string" && /^[a-z]{2,3}(-[a-z0-9]{2,8})?$/i.test(c); })
        : null;
      if (store.langs && !store.langs.length) store.langs = null;
      if (!Array.isArray(store.ids)) store.ids = null;
    } catch (e) { /* start clean */ }
    if (["today", "read", "search", "world", "numbers", "more"].indexOf(store.view) < 0) store.view = "today";
  }
  function emit() { saveState(); subs.slice().forEach(function (f) { f(); }); }
  function go(view, extra) {
    var moved = store.view !== view;
    store.view = view;
    if (extra) Object.assign(store, extra);
    document.body.classList.remove("nav-open");
    emit();
    if (moved) focusMain();   // a new view takes focus; a change inside a view leaves it where it is
  }

  // Everything below needs the vendored renderer. Without it, the switch still paints and
  // the full interface is untouched; simple mode says so instead of showing a blank page.
  var html = (P && HTM) ? HTM.bind(P.h) : null;
  var useState = H && H.useState, useEffect = H && H.useEffect, useRef = H && H.useRef;

  function useStore() {
    var st = useState(0), bump = st[1];
    useEffect(function () {
      var f = function () { bump(function (x) { return x + 1; }); };
      subs.push(f);
      return function () { subs = subs.filter(function (g) { return g !== f; }); };
    }, []);
    return store;
  }
  var _idSeq = 0;
  function useId(prefix) { var r = useRef(null); if (!r.current) r.current = prefix + "-" + (++_idSeq); return r.current; }

  // A remote read with honest states: loading, error (the message the server gave), data.
  function useLoad(fn, deps) {
    var s = useState({ loading: true, error: null, data: null }), state = s[0], set = s[1];
    useEffect(function () {
      var live = true;
      // Keep what is on screen while it reloads: a refresh never blanks a panel or closes an open ⓘ.
      set(function (x) { return { loading: true, error: null, data: x.data }; });
      Promise.resolve().then(fn).then(
        function (d) { if (live) set({ loading: false, error: null, data: d }); },
        function (e) { if (live) set(function (x) { return { loading: false, error: (e && e.message) || String(e), data: x.data }; }); });
      return function () { live = false; };
    }, deps);
    return state;
  }

  // ---------------------------------------------------------------- small components
  function Icon(props) {
    var paths = {
      today: "M3 11l9-8 9 8M5 10v10h14V10",
      read: "M4 5h10M4 10h10M4 15h7M16 4h4v4h-4zM16 12h4v4h-4z",
      search: "M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14zM20 20l-3.5-3.5",
      more: "M4 6h16M4 12h16M4 18h10",
      world: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9s1.3-6.4 3.8-9z",
      numbers: "M4 20V10M10 20V4M16 20v-7M22 20H2",
      ext: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
    };
    return html`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d=${paths[props.name] || ""}/></svg>`;
  }

  // The ⓘ disclosure: a real button (Tab, Enter, Space, touch), aria-expanded + aria-controls,
  // and an inline panel so nothing is positioned off-screen on a phone. Esc closes it.
  function Details(props) {
    var o = useState(false), open = o[0], setOpen = o[1];
    var id = useId("sd");
    return html`<span class="s-info">
      <button type="button" class="s-info-btn" aria-expanded=${open ? "true" : "false"} aria-controls=${id}
        aria-label=${t("Details: {what}", { what: props.what })}
        onClick=${function () { setOpen(!open); }}
        onKeyDown=${function (e) { if (e.key === "Escape") setOpen(false); }}>ⓘ</button>
      <div id=${id} class="s-info-panel" role="region" aria-label=${t("Details: {what}", { what: props.what })}
        hidden=${!open}>${open ? props.children : null}</div>
    </span>`;
  }
  // The visible mark for a figure that is approximate (~), partial (◐) or stale (◷).
  function Mark(props) {
    var sym = { approx: "~", partial: "◐", stale: "◷" }[props.kind] || "•";
    var word = { approx: t("approximate"), partial: t("partial"), stale: t("may be out of date") }[props.kind] || "";
    return html`<span class=${"s-mark s-mark-" + props.kind} title=${word}><span aria-hidden="true">${sym}</span><span class="s-sr">${word}</span></span>`;
  }
  function Row(props) { return html`<div class="s-drow"><span class="s-dk">${props.k}</span><span class="s-dv">${props.v}</span></div>`; }
  function Loading() { return html`<div class="s-loading" role="status">${t("Loading…")}</div>`; }
  function ErrorLine(props) { return html`<div class="s-error" role="alert">${t("Could not load this: {why}", { why: props.msg })}</div>`; }
  function Empty(props) { return html`<div class="s-empty">${props.children}</div>`; }

  // ---------------------------------------------------------------- navigation
  var VIEWS = [
    { id: "today", label: function () { return t("Today"); } },
    { id: "read", label: function () { return t("Read"); } },
    { id: "search", label: function () { return t("Search"); } },
    { id: "world", label: function () { return t("World"); } },
    { id: "numbers", label: function () { return t("Numbers"); } },
    { id: "more", label: function () { return t("More tools"); } },
  ];
  function Nav() {
    var s = useStore();
    return html`<div class="simple-nav-list" role="list">
      ${VIEWS.map(function (v) {
        var on = s.view === v.id;
        return html`<div role="listitem"><button type="button" class=${"nav-item" + (on ? " active" : "")}
          aria-current=${on ? "page" : null} onClick=${function () { go(v.id); }}>
          <${Icon} name=${v.id}/><span>${v.label()}</span></button></div>`;
      })}
    </div>`;
  }

  // ---------------------------------------------------------------- Today
  function cardText(c, field) {
    var parts = c && c.i18n && c.i18n[field];
    if (Array.isArray(parts) && parts.length) return parts.map(function (p) { return tf(p.t, p.v); }).join(" ");
    return (c && c[field]) || "";
  }
  function bucketLabel(b) { return b ? t(b.label || b.bucket) : ""; }

  function StatusPanel() {
    var st = useState(0), tick = st[0], setTick = st[1];
    useEffect(function () {
      var h = setInterval(function () { if (isSimple() && !document.hidden) setTick(function (x) { return x + 1; }); }, 20000);
      var onNet = function () { setTick(function (x) { return x + 1; }); };
      document.addEventListener("oo:simple-refresh", onNet);
      return function () { clearInterval(h); document.removeEventListener("oo:simple-refresh", onNet); };
    }, []);
    var r = useLoad(function () {
      return Promise.all([
        apiCall("/api/database/stats", { polled: true }),
        apiCall("/api/system/network", { polled: true }).catch(function () { return null; }),
        apiCall("/api/scheduler/status", { polled: true }).catch(function () { return null; }),
      ]);
    }, [tick]);
    if (r.loading && !r.data) return html`<section class="s-card s-status"><${Loading}/></section>`;
    if (r.error) return html`<section class="s-card s-status"><${ErrorLine} msg=${r.error}/></section>`;
    var stats = r.data[0] || {}, net = r.data[1], sch = r.data[2];
    var c = stats.counts || {};
    var online = net ? !!net.online : null;
    var running = sch ? !!sch.running : null;
    var collecting = online === false ? t("Offline: nothing is fetched until you go online.")
      : online == null ? t("The network state could not be read.")
      : running ? t("Online: collecting from your sources.")
      : t("Online: collection is not running right now.");
    var stale = stats.verified_current === false;
    return html`<section class="s-card s-status" aria-labelledby="s-status-h">
      <h2 id="s-status-h" class="s-sr">${t("Your corpus")}</h2>
      <div class="s-figs">
        <div class="s-fig"><b>${fmtInt(c.articles)}</b><span>${t("articles")}</span></div>
        <div class="s-fig"><b>${fmtInt(c.sources_qualified != null ? c.sources_qualified : c.sources)}</b><span>${t("sources")}</span></div>
        ${stale ? html`<${Mark} kind="stale"/>` : null}
        <${Details} what=${t("Your corpus")}>
          <${Row} k=${t("Counted")} v=${fmtTime(stats.as_of || stats.computed_at)}/>
          <${Row} k=${t("Where")} v=${t("On this machine only; nothing is sent anywhere.")}/>
          <${Row} k=${t("Sources waiting to be checked")} v=${fmtInt(c.sources_pending)}/>
          ${stats.cached ? html`<${Row} k=${t("Cache")} v=${t("A count from the last {s} s.", { s: stats.cache_age_s })}/>` : null}
        <//>
      </div>
      <div class="s-collect">
        <span class=${"s-dot " + (online ? (running ? "ok" : "idle") : "off")} aria-hidden="true"></span>
        <span>${collecting}</span>
        ${online === false ? html`<button type="button" class="s-btn primary" onClick=${goOnline}>${t("Go online")}</button>` : null}
      </div>
    </section>`;
  }
  // The ONE consent path: the full app's own airplane switch, which opens the consent popup
  // (invariant #14). Simple mode never POSTs /api/system/network itself.
  // The panel's figure can be up to 20 s old and the switch flips state, so read the live state
  // first: the switch is pressed only while the app is still offline AND the top-bar plane says
  // so; otherwise the panel just refreshes. A stale panel can never send the reader offline.
  function refreshStatus() { document.dispatchEvent(new CustomEvent("oo:simple-refresh")); }
  function goOnline() {
    if (typeof window.toggleNetwork !== "function") return;
    var plane = document.getElementById("net-toggle");
    apiCall("/api/system/network", { polled: true }).then(function (n) {
      if (n && n.online === false && plane && plane.classList.contains("off")) {
        return Promise.resolve(window.toggleNetwork()).then(function () { setTimeout(refreshStatus, 600); });
      }
      refreshStatus();
    }, refreshStatus);
  }
  // A network change made anywhere (the top-bar plane, the consent popup) repaints the panel.
  function watchNetwork() {
    var plane = document.getElementById("net-toggle");
    if (!plane || typeof MutationObserver !== "function") return;
    var last = plane.classList.contains("off");
    new MutationObserver(function () {
      var now = plane.classList.contains("off");
      if (now !== last) { last = now; if (mounted) refreshStatus(); }
    }).observe(plane, { attributes: true, attributeFilter: ["class"] });
  }

  var MAX_IDS = 500;   // the most article ids one request carries
  function LeadCard(props) {
    var c = props.card;
    var title = cardText(c, "title") || c.title;
    var summary = cardText(c, "summary") || c.summary;
    var thin = typeof c.n === "number" && c.n < 5;
    var trig = c.trigger || {};
    return html`<article class="s-card s-lead">
      <div class="s-lead-top">
        <span class=${"s-chip s-b-" + (c.bucket || "x")}>${props.bucket}</span>
        ${thin ? html`<${Mark} kind="approx"/>` : null}
      </div>
      <h3 class="s-lead-title">${title}</h3>
      <p class="s-lead-sum">${summary}</p>
      <div class="s-actions">
        ${Array.isArray(c.article_ids) && c.article_ids.length
          ? html`<button type="button" class="s-btn" onClick=${function () {
              go("search", { query: "", ids: c.article_ids.slice(0, MAX_IDS), countries: null, langs: null, label: title });
            }}>${t("Read the articles ({n})", { n: fmtInt(Math.min(c.article_ids.length, MAX_IDS)) })}</button>
            ${c.article_ids.length > MAX_IDS ? html`<${Mark} kind="partial"/>` : null}` : null}
        <${Details} what=${title}>
          ${trig.plain ? html`<p class="s-why"><b>${t("Why you see this")}</b> ${tf(trig.plain)}</p>` : null}
          ${c.caveat ? html`<p class="s-caveat"><b>${t("Caveat")}</b> ${cardText(c, "caveat") || c.caveat}</p>` : null}
          ${c.method ? html`<p class="s-method"><b>${t("Method")}</b> ${cardText(c, "method") || c.method}</p>` : null}
          ${Array.isArray(trig.math) ? trig.math.map(function (m) { return html`<${Row} k=${tf(m.label)} v=${m.value}/>`; }) : null}
          <${Row} k="n" v=${c.n}/>
          <${Row} k=${t("Found")} v=${fmtTime(c.created_at)}/>
        <//>
      </div>
    </article>`;
  }

  function Leads() {
    var lang = curLang();
    var tick = useState(0), tries = tick[0], setTries = tick[1];
    var r = useLoad(function () { return apiCall("/api/briefing?target_lang=" + encodeURIComponent(lang)); }, [lang, tries]);
    // The server builds leads in the background and says so ("refreshing"): ask again while it
    // works (a few times, spaced out), so a first visit does not read "nothing stands out" yet.
    var building = !!(r.data && r.data.refreshing);
    useEffect(function () {
      if (!building || tries >= 6) return undefined;
      var h = setTimeout(function () { setTries(tries + 1); }, 3000 + tries * 2000);
      return function () { clearTimeout(h); };
    }, [building, tries]);
    if (r.loading && !r.data) return html`<${Loading}/>`;
    if (r.error) return html`<${ErrorLine} msg=${r.error}/>`;
    var cards = [];
    (r.data.buckets || []).forEach(function (b) {
      (b.cards || []).forEach(function (c) { cards.push({ card: c, bucket: bucketLabel(b) }); });
    });
    if (!cards.length && building) return html`<div class="s-loading" role="status">${t("Looking for leads in your corpus…")}</div>`;
    if (!cards.length) {
      return html`<${Empty}>${t("Nothing stands out yet. Leads appear here as your corpus grows.")}<//>`;
    }
    var shown = cards.slice(0, 6);
    return html`<div class="s-grid">${shown.map(function (x) { return html`<${LeadCard} key=${x.card.id} card=${x.card} bucket=${x.bucket}/>`; })}</div>
      ${cards.length > shown.length ? html`<button type="button" class="s-link" onClick=${function () { peekFull("home"); }}>
        ${t("All {n} leads in the full view", { n: cards.length })}</button>` : null}`;
  }

  function Trending() {
    var r = useLoad(function () { return apiCall("/api/insights/trending-windows?limit=8"); }, []);
    if (r.loading) return html`<${Loading}/>`;
    if (r.error) return html`<${ErrorLine} msg=${r.error}/>`;
    var wins = (r.data && r.data.windows) || [];
    var w = wins.filter(function (x) { return x.window_days === 7 && !x.skipped && (x.terms || []).length; })[0]
      || wins.filter(function (x) { return !x.skipped && (x.terms || []).length; })[0];
    if (!w) return html`<${Empty}>${t("No topic is rising yet.")}<//>`;
    var d = r.data || {};
    // Not the usual week: say so with a mark; the ⓘ names the window actually shown.
    var other = w.window_days !== 7;
    return html`<div class="s-chips">
      ${w.terms.map(function (x) {
        return html`<button type="button" class="s-chip s-term" onClick=${function () { go("search", { query: x.term, ids: null, countries: null, langs: null, label: "" }); }}>
          <span dir="auto">${x.term}</span> <span class="s-n">${x.recent}</span>
          ${x.growth_is_ratio === false ? html`<${Mark} kind="approx"/>` : null}</button>`;
      })}
      ${other ? html`<${Mark} kind="partial"/>` : null}
      <${Details} what=${t("Rising topics")}>
        <p>${t("Mentions in the last {d} days compared with the {b} days before. The number on each topic is its recent mention count.", { d: w.window_days, b: w.baseline_days })}</p>
        <p>${t("~ marks a topic with too few earlier mentions to compare: it is new, not necessarily growing.")}</p>
        <${Row} k=${t("Topics scanned")} v=${fmtInt(w.scanned)}/>
        ${d.method ? html`<p class="s-method"><b>${t("Method")}</b> ${t(d.method)}</p>` : null}
        ${d.caveat ? html`<p class="s-caveat"><b>${t("Caveat")}</b> ${t(d.caveat)}</p>` : null}
        ${d.computed_at ? html`<${Row} k=${t("Computed")} v=${fmtTime(d.computed_at)}/>` : null}
      <//>
    </div>`;
  }

  function Today() {
    return html`<div class="s-view">
      <h1 class="s-h1">${t("Today")}</h1>
      <${StatusPanel}/>
      <h2 class="s-h2">${t("Worth a look")}</h2>
      <${Leads}/>
      <h2 class="s-h2">${t("Rising topics")}</h2>
      <${Trending}/>
    </div>`;
  }

  // ---------------------------------------------------------------- Read
  function ArticleMeta(props) {
    var a = props.a;
    var lang = a.language || a.detected_language;
    return html`<div class="s-meta"><span dir="auto">${a.source || ""}</span>
      ${a.published_at ? html`<span>· ${fmtDate(a.published_at)}</span>` : null}
      ${lang ? html`<span>· ${langName(lang)}</span>` : null}</div>`;
  }
  function openOriginal(url) {
    // Invariant #6: an outbound link opens the LOCAL preview first, never the site directly.
    if (typeof window.openLinkPreview === "function") window.openLinkPreview(url);
  }
  function FeedItem(props) {
    var a = props.a;
    var o = useState(false), open = o[0], setOpen = o[1];
    var id = useId("sa");
    var reader = a.reader_url || ("/api/articles/" + a.id + "/view");
    return html`<article class="s-item">
      <h3 class="s-item-title"><button type="button" class="s-title-btn" aria-expanded=${open ? "true" : "false"}
        aria-controls=${id} onClick=${function () { setOpen(!open); }} dir="auto">${a.title || t("(untitled)")}</button></h3>
      <${ArticleMeta} a=${a}/>
      <p id=${id} class=${"s-excerpt" + (open ? " open" : "")} dir="auto">${open ? (a.excerpt_full || a.excerpt) : a.excerpt}</p>
      ${open ? html`<div class="s-actions">
        <a class="s-btn" href=${reader} target="_blank" rel="noopener">${t("Open the reader")}</a>
        ${a.url ? html`<button type="button" class="s-btn ghost" onClick=${function () { openOriginal(a.url); }}>${t("Original page")}</button>` : null}
      </div>` : null}
    </article>`;
  }

  function Read() {
    var s = useStore();
    var ls = useState({ rows: [], cursor: null, more: false, loading: true, error: null, held: null, method: "", caveat: "" });
    var st = ls[0], set = ls[1];
    var gen = useRef(0);
    function load(reset) {
      // Only the newest request may write: an older answer (a previous order, a slow page)
      // arriving late is dropped instead of mixing lists.
      var mine = ++gen.current;
      var p = new URLSearchParams({ order: s.order === "shuffled" ? "shuffled" : "recent", limit: "20" });
      if (s.order === "shuffled") p.set("seed", "1");
      if (!reset && st.cursor) p.set("after", st.cursor);
      set(function (x) { return Object.assign({}, x, { loading: true, error: null }, reset ? { rows: [] } : {}); });
      apiCall("/api/feed?" + p.toString()).then(function (d) {
        if (mine !== gen.current) return;
        set(function (x) {
          // The server counts held-back articles on the first page only; later pages keep it.
          return { rows: (reset ? [] : x.rows).concat(d.results || []), cursor: d.next_cursor, more: !!d.has_more,
            loading: false, error: null, held: d.held_back != null ? d.held_back : (reset ? null : x.held),
            method: d.method || x.method, caveat: d.caveat || x.caveat };
        });
      }, function (e) {
        if (mine !== gen.current) return;
        set(function (x) { return Object.assign({}, x, { loading: false, error: e.message || String(e) }); });
      });
    }
    useEffect(function () { load(true); }, [s.order]);
    var held = st.held ? (st.held.source_not_qualified || 0) + (st.held.quarantined || 0) : 0;
    return html`<div class="s-view">
      <h1 class="s-h1">${t("Read")}</h1>
      <div class="s-toolbar">
        <div class="s-seg" role="group" aria-label=${t("Order")}>
          <button type="button" aria-pressed=${s.order !== "shuffled" ? "true" : "false"} onClick=${function () { go("read", { order: "recent" }); }}>${t("Newest")}</button>
          <button type="button" aria-pressed=${s.order === "shuffled" ? "true" : "false"} onClick=${function () { go("read", { order: "shuffled" }); }}>${t("Mixed")}</button>
        </div>
        ${held ? html`<${Mark} kind="partial"/>` : null}
        <${Details} what=${t("This list")}>
          ${st.method ? html`<p><b>${t("Order")}</b> ${t(st.method)}</p>` : null}
          ${st.caveat ? html`<p class="s-caveat">${t(st.caveat)}</p>` : null}
          ${held ? html`<p>${t("{n} articles are held back until their source has been checked.", { n: fmtInt(held) })}</p>` : null}
        <//>
      </div>
      ${st.error ? html`<${ErrorLine} msg=${st.error}/>` : null}
      ${!st.loading && !st.error && !st.rows.length ? html`<${Empty}>${t("No articles yet. Go online on Today to start collecting.")}<//>` : null}
      <div class="s-list">${st.rows.map(function (a) { return html`<${FeedItem} key=${a.id} a=${a}/>`; })}</div>
      ${st.loading ? html`<${Loading}/>` : null}
      ${st.more && !st.loading ? html`<button type="button" class="s-btn wide" onClick=${function () { load(false); }}>${t("Show more")}</button>` : null}
    </div>`;
  }

  // ---------------------------------------------------------------- Search
  function searchParams(s) {
    var p = new URLSearchParams();
    if (s.ids && s.ids.length) p.set("ids", s.ids.join(","));
    else if (s.query) p.set("query", s.query);
    if (s.countries && s.countries.length && !(s.ids && s.ids.length)) p.set("countries", s.countries.join(","));
    if (s.langs && s.langs.length && !(s.ids && s.ids.length)) p.set("langs", s.langs.join(","));
    return p;
  }
  function setKey(s) {
    return (s.ids ? s.ids.join(",") : "") + "|" + s.query + "|" + (s.countries ? s.countries.join(",") : "") + "|" + (s.langs ? s.langs.join(",") : "");
  }
  function Glance(props) {
    var s = props.s;
    var key = setKey(s);
    var r = useLoad(function () {
      // The corpus endpoints name the set "article_ids" (the article list calls it "ids").
      var g = new URLSearchParams();
      if (s.ids && s.ids.length) g.set("article_ids", s.ids.join(","));
      else {
        if (s.query) g.set("query", s.query);
        if (s.countries && s.countries.length) g.set("countries", s.countries.join(","));
        if (s.langs && s.langs.length) g.set("langs", s.langs.join(","));
      }
      g.set("ui_lang", curLang());
      var p = g.toString();
      return Promise.all([
        apiCall("/api/insights/corpus-sources?limit=200&" + p).catch(function () { return null; }),
        apiCall("/api/insights/corpus-www?" + p).catch(function () { return null; }),
      ]);
    }, [key]);
    if (r.loading) return html`<${Loading}/>`;
    if (r.error) return html`<${ErrorLine} msg=${r.error}/>`;
    var src = r.data[0], www = r.data[1];
    var top = src && src.sources ? src.sources.slice(0, 4) : [];
    var years = www && www.when ? (www.when.years || []).slice().sort(function (a, b) { return b.articles - a.articles; }).slice(0, 4) : [];
    var places = www && www.where ? (www.where.places || []).slice(0, 5) : [];
    var who = www && www.who ? (www.who.entities || []).slice(0, 5) : [];
    function names(list, nameKey) {
      return list.map(function (x) { return (x[nameKey] || x.name || x.label || x.text || "") + " (" + fmtInt(x.articles || x.count || x.mentions) + ")"; }).join(", ");
    }
    // Where the coverage comes from: the sources' own (catalogue-asserted) countries, summed.
    var byC = {};
    (src && src.sources ? src.sources : []).forEach(function (x) {
      if (x.country) byC[x.country] = (byC[x.country] || 0) + (x.articles || 0);
    });
    var from = Object.keys(byC).sort(function (a, b) { return byC[b] - byC[a]; });
    // Partial when the set itself was capped, or when the 200-source page may have left sources out.
    var srcCapped = !!(src && (src.capped || (src.sources && src.sources.length >= 200)));
    var rows = [];
    if (from.length) rows.push([t("Covered from"), from.slice(0, 8).map(function (c) { return c + " (" + fmtInt(byC[c]) + ")"; }).join(", ")
      + (from.length > 8 ? " " + t("and {n} more", { n: from.length - 8 }) : "")]);
    if (top.length) rows.push([t("Most coverage from"), names(top, "name")]);
    if (years.length) rows.push([t("Years mentioned"), names(years, "year")]);
    if (places.length) rows.push([t("Places mentioned"), names(places, "name")]);
    if (who.length) rows.push([t("People and organisations"), names(who, "name")]);
    if (!rows.length) return null;
    return html`<section class="s-card s-glance" aria-labelledby="s-glance-h">
      <div class="s-glance-head"><h2 id="s-glance-h" class="s-h3">${t("At a glance")}</h2>
        ${(www && www.capped) || srcCapped ? html`<${Mark} kind="partial"/>` : null}
        <${Details} what=${t("At a glance")}>
          <p class="s-caveat">${t("Counts of articles, never a verdict. Places, people and years are deduced from the text and never confirmed.")}</p>
          <p>${t("Covered from: the country each source is catalogued under, never where a story happened.")}</p>
          ${www ? html`<${Row} k=${t("Articles read")} v=${fmtInt(www.n_articles) + " / " + fmtInt(www.total_matched)}/>` : null}
          ${www && www.computed_at ? html`<${Row} k=${t("Computed")} v=${fmtTime(www.computed_at)}/>` : null}
        <//>
      </div>
      ${rows.map(function (x) { return html`<${Row} k=${x[0]} v=${html`<span dir="auto">${x[1]}</span>`}/>`; })}
    </section>`;
  }
  function openFullAnalysis(s) {
    peekFull("explore", function () {
      if (s.ids && s.ids.length && typeof window.openAnalysisForIds === "function") window.openAnalysisForIds(s.ids, s.label || "");
      else if (typeof window.openAnalysisFor === "function") window.openAnalysisFor(s.query);
    });
  }
  function Results(props) {
    var s = props.s;
    var key = setKey(s);
    var r = useLoad(function () {
      var p = searchParams(s);
      p.set("limit", "20");
      p.set("ui_lang", curLang());
      return apiCall("/api/articles?" + p.toString());
    }, [key]);
    // Further pages, appended under the first; a new search starts again from the top.
    var more = useState({ key: key, rows: [], busy: false, err: null }), setExtra = more[1];
    var extra = more[0].key === key ? more[0] : { key: key, rows: [], busy: false, err: null };
    if (r.loading && !r.data) return html`<${Loading}/>`;
    if (r.error) return html`<${ErrorLine} msg=${r.error}/>`;
    var rows = (r.data.results || []).concat(extra.rows);
    var total = r.data.total || 0;
    function loadMore() {
      var p = searchParams(s);
      p.set("limit", "20");
      p.set("offset", String(rows.length));
      p.set("ui_lang", curLang());
      setExtra({ key: key, rows: extra.rows, busy: true, err: null });
      apiCall("/api/articles?" + p.toString()).then(function (d) {
        setExtra(function (x) { return x.key !== key ? x : { key: key, rows: x.rows.concat(d.results || []), busy: false, err: null }; });
      }, function (e) {
        setExtra(function (x) { return x.key !== key ? x : Object.assign({}, x, { busy: false, err: (e && e.message) || String(e) }); });
      });
    }
    if (!rows.length) return html`<${Empty}>${t("No article matches. Try fewer or different words.")}<//>`;
    return html`<div>
      <div class="s-count">${t("{n} articles", { n: fmtInt(total) })}
        ${total > rows.length ? html`<span class="s-muted"> · ${t("showing the first {n}", { n: fmtInt(rows.length) })}</span>` : null}</div>
      <${Glance} s=${s}/>
      <div class="s-actions"><button type="button" class="s-btn" onClick=${function () { openFullAnalysis(s); }}>
        ${t("Open the full analysis")}</button></div>
      <div class="s-list">${rows.map(function (a) {
        var reader = "/api/articles/" + a.id + "/view";
        var snip = (a.content || "").slice(0, 220);
        return html`<article class="s-item" key=${a.id}>
          <h3 class="s-item-title"><a href=${reader} target="_blank" rel="noopener" dir="auto">${a.title || t("(untitled)")}</a></h3>
          <${ArticleMeta} a=${a}/>
          ${snip ? html`<p class="s-excerpt" dir="auto">${snip}${(a.content || "").length > 220 ? "…" : ""}</p>` : null}
        </article>`;
      })}</div>
      ${extra.err ? html`<${ErrorLine} msg=${extra.err}/>` : null}
      ${total > rows.length ? html`<button type="button" class="s-btn wide" disabled=${extra.busy} onClick=${loadMore}>
        ${extra.busy ? t("Loading…") : t("Show more")}</button>` : null}
    </div>`;
  }
  function Search() {
    var s = useStore();
    var q = useState(s.query || ""), text = q[0], setText = q[1];
    useEffect(function () { setText(s.query || ""); }, [s.query]);
    var active = (s.ids && s.ids.length) || (s.query && s.query.trim()) || (s.countries && s.countries.length) || (s.langs && s.langs.length);
    // The languages the corpus holds, with their article counts, for the language filter.
    var lr = useLoad(function () { return apiCall("/api/insights/corpus-source-language-facets").catch(function () { return null; }); }, []);
    var langs = (lr.data && lr.data.languages) || [];
    var picked = s.langs && s.langs.length ? s.langs[0] : "";
    return html`<div class="s-view">
      <h1 class="s-h1">${t("Search")}</h1>
      <form class="s-search" role="search" onSubmit=${function (e) {
        e.preventDefault();
        go("search", { query: text.trim(), ids: null, label: "" });   // a country scope stays until cleared
      }}>
        <label class="s-sr" for="s-q">${t("Search your articles")}</label>
        <input id="s-q" type="search" value=${text} placeholder=${t("Search your articles")} autocomplete="off"
          onInput=${function (e) { setText(e.currentTarget.value); }}/>
        <button type="submit" class="s-btn primary">${t("Search")}</button>
      </form>
      ${langs.length > 1 && !(s.ids && s.ids.length) ? html`<div class="s-toolbar s-toolbar-start">
        <label class="s-inline" for="s-lang">${t("Language")}</label>
        <select id="s-lang" class="s-select" value=${picked}
          onChange=${function (e) { var v = e.currentTarget.value; go("search", { langs: v ? [v] : null }); }}>
          <option value="">${t("Any language")}</option>
          ${langs.map(function (x) { return html`<option value=${x.language}>${langName(x.language) + " (" + fmtInt(x.n) + ")"}</option>`; })}
          ${picked && !langs.some(function (x) { return x.language === picked; }) ? html`<option value=${picked}>${langName(picked)}</option>` : null}
        </select>
        <${Details} what=${t("Language")}>
          <p>${t("The language each article is written in, as its source states it or, failing that, as detected from its text. The counts are for the whole corpus.")}</p>
        <//>
      </div>` : null}
      ${s.ids && s.ids.length ? html`<div class="s-scope">
        <span>${t("The articles behind: {label}", { label: s.label || "" })}</span>
        <button type="button" class="s-btn ghost" onClick=${function () { go("search", { ids: null, label: "" }); }}>${t("Clear")}</button></div>` : null}
      ${s.countries && s.countries.length && !(s.ids && s.ids.length) ? html`<div class="s-scope">
        <span>${t("From sources in: {c}", { c: s.countries.join(", ") })}</span>
        <button type="button" class="s-btn ghost" onClick=${function () { go("search", { countries: null }); }}>${t("Clear")}</button></div>` : null}
      ${active ? html`<${Results} s=${s}/>` : html`<${Empty}>${t("Type a word, a name or a phrase. Use quotes for an exact phrase, OR for either word.")}<//>`}
    </div>`;
  }


  // ---------------------------------------------------------------- World
  // Where the corpus comes from, by the country each source is catalogued under. A click reads
  // that country's articles. Codes on screen, names on hover (Q302).
  function World() {
    var r = useLoad(function () { return apiCall("/api/insights/map-coverage"); }, []);
    if (r.loading && !r.data) return html`<div class="s-view"><h1 class="s-h1">${t("World")}</h1><${Loading}/></div>`;
    if (r.error) return html`<div class="s-view"><h1 class="s-h1">${t("World")}</h1><${ErrorLine} msg=${r.error}/></div>`;
    var d = r.data || {};
    var all = d.by_country || [];
    var withArt = all.filter(function (c) { return c.articles > 0; }).sort(function (a, b) { return b.articles - a.articles; });
    var waiting = all.length - withArt.length;
    var max = withArt.length ? withArt[0].articles : 1;
    return html`<div class="s-view">
      <h1 class="s-h1">${t("World")}</h1>
      <div class="s-toolbar s-toolbar-start">
        <p class="s-lede">${t("Where your articles come from. Choose a country to read its articles.")}</p>
        <${Details} what=${t("World")}>
          ${d.method ? html`<p class="s-method"><b>${t("Method")}</b> ${t(d.method)}</p>` : null}
          ${d.caveat ? html`<p class="s-caveat"><b>${t("Caveat")}</b> ${t(d.caveat)}</p>` : null}
          <${Row} k=${t("Articles")} v=${fmtInt(d.total_articles)}/>
          <${Row} k=${t("sources")} v=${fmtInt(d.total_sources)}/>
          <p>${t("Search hides articles held back until their source is checked, so a country's list can be shorter than its count here.")}</p>
          ${d.unlocated && d.unlocated.sources ? html`<${Row} k=${t("Sources with no country")} v=${fmtInt(d.unlocated.sources)}/>` : null}
          ${d.computed_at ? html`<${Row} k=${t("Computed")} v=${fmtTime(d.computed_at)}/>` : null}
        <//>
      </div>
      ${withArt.length ? html`<ol class="s-ranks">${withArt.map(function (c) {
        return html`<li><button type="button" class="s-rank" title=${c.name || c.country}
          aria-label=${(c.name ? c.name + " (" + c.country + ")" : c.country) + ", " + t("{n} articles", { n: fmtInt(c.articles) })}
          onClick=${function () { go("search", { query: "", ids: null, countries: [c.country], langs: null, label: "" }); }}>
          <b class="s-code">${c.country}</b>
          <span class="s-barbox" aria-hidden="true"><span class="s-bar" style=${"width:" + Math.max(2, Math.round(100 * c.articles / max)) + "%"}></span></span>
          <span class="s-n">${t("{n} articles", { n: fmtInt(c.articles) })}</span>
          <span class="s-sr">${c.name || ""}</span></button></li>`;
      })}</ol>` : html`<${Empty}>${t("No articles yet. Go online on Today to start collecting.")}<//>`}
      ${waiting > 0 ? html`<p class="s-muted s-foot">${t("{n} more countries have sources but no articles yet.", { n: fmtInt(waiting) })}</p>` : null}
      <button type="button" class="s-link" onClick=${function () { peekFull("timemap"); }}>${t("The map and timeline in the full view")}</button>
    </div>`;
  }

  // ---------------------------------------------------------------- Numbers
  function fmtNum(v) {
    if (v == null || isNaN(v)) return "—";
    try { return new Intl.NumberFormat(curLang(), { maximumSignificantDigits: 4 }).format(v); } catch (e) { return String(v); }
  }
  function Markets() {
    var r = useLoad(function () { return apiCall("/api/markets/series"); }, []);
    if (r.loading && !r.data) return html`<${Loading}/>`;
    if (r.error) return html`<${ErrorLine} msg=${r.error}/>`;
    var rows = (r.data && r.data.series) || [];
    if (!rows.length) return html`<${Empty}>${t("No prices stored yet.")}
      <button type="button" class="s-link" onClick=${function () { peekFull("markets"); }}>${t("Import prices in the full view")}</button><//>`;
    return html`<div class="s-toolbar s-toolbar-start"><p class="s-lede">${t("The latest stored price of each series.")}</p>
      <${Details} what=${t("Prices")}>
        <p>${t("Prices are imported in the full view, with your consent; nothing is fetched here. Each card shows the newest stored value and its date.")}</p>
        <p class="s-caveat">${t("A price can be old: read its date.")}</p>
      <//></div><ul class="s-nums">${rows.map(function (x) {
      var l = x.latest || {};
      return html`<li class="s-num"><button type="button" class="s-num-btn" onClick=${function () { peekFull("markets"); }}
        aria-label=${[x.name || x.symbol, fmtNum(l.price) + " " + (l.currency || "") + (l.unit ? "/" + l.unit : ""), fmtDate(l.observed_on),
          t("{n} values stored", { n: fmtInt(x.points) })].join(", ")}>
        <span class="s-num-name" dir="auto">${x.name || x.symbol}</span>
        <b class="s-num-val">${fmtNum(l.price)} <small>${(l.currency || "") + (l.unit ? "/" + l.unit : "")}</small></b>
        <span class="s-meta">${fmtDate(l.observed_on)}</span>
        <span class="s-sr">${t("{n} values stored", { n: fmtInt(x.points) })}</span></button></li>`;
    })}</ul>`;
  }
  function Climate() {
    var r = useLoad(function () { return apiCall("/api/climate/datasets"); }, []);
    if (r.loading && !r.data) return html`<${Loading}/>`;
    if (r.error) return html`<${ErrorLine} msg=${r.error}/>`;
    var units = (r.data && r.data.units) || [];
    var seen = {}, rows = [];
    units.forEach(function (u) {
      var x = seen[u.dataset];
      if (!x) { x = seen[u.dataset] = { dataset: u.dataset, host: u.host, stored: 0, last: null }; rows.push(x); }
      x.stored += (u.stored && u.stored.stored_rows) || 0;
      var at = u.last_fetch && u.last_fetch.fetched_at;
      if (at && (!x.last || at > x.last)) x.last = at;   // the newest fetch of any of its series
    });
    var have = rows.filter(function (x) { return x.stored > 0; });
    return html`<div>
      ${have.length ? html`<ul class="s-nums">${have.map(function (x) {
        return html`<li class="s-num"><button type="button" class="s-num-btn" onClick=${function () { peekFull("climate"); }}>
          <span class="s-num-name">${x.dataset.toUpperCase()}</span>
          <b class="s-num-val">${t("{n} values", { n: fmtInt(x.stored) })}</b>
          <span class="s-meta">${x.last ? t("Fetched {d}", { d: fmtDate(x.last) }) : x.host}</span></button></li>`;
      })}</ul>` : html`<${Empty}>${t("No climate record is stored yet. Each one is fetched, with your consent, in the full view.")}<//>`}
      <button type="button" class="s-link" onClick=${function () { peekFull("climate"); }}>${t("Climate records in the full view")}</button>
    </div>`;
  }
  function Numbers() {
    return html`<div class="s-view">
      <h1 class="s-h1">${t("Numbers")}</h1>
      <h2 class="s-h2">${t("Prices")}</h2>
      <${Markets}/>
      <div class="s-toolbar"><h2 class="s-h2">${t("Climate")}</h2>
        <${Details} what=${t("Climate")}>
          <p>${t("Published records, fetched with your consent in the full view. The count includes every revision the publisher made.")}</p>
        <//></div>
      <${Climate}/>
    </div>`;
  }

  // ---------------------------------------------------------------- Add a source
  // A local write: the source joins your list and nothing is fetched until you are online.
  function AddSource() {
    var f = useState({ name: "", domain: "", rss: "" }), v = f[0], setV = f[1];
    var st = useState({ busy: false, msg: "", err: "" }), s = st[0], setS = st[1];
    function field(k) { return function (e) { var o = Object.assign({}, v); o[k] = e.currentTarget.value; setV(o); }; }
    function submit(e) {
      e.preventDefault();
      // A bare host, as the server stores it: no scheme, login, port, path or "www.", lower case.
      var domain = v.domain.trim().toLowerCase().replace(/^[a-z]+:\/\//, "").replace(/[\/?#].*$/, "")
        .replace(/^[^@]*@/, "").replace(/:\d+$/, "").replace(/^www\./, "");
      if (!v.name.trim() || !domain) { setS({ busy: false, msg: "", err: t("A name and a web address are needed.") }); return; }
      setS({ busy: true, msg: "", err: "" });
      // The server hands back the existing row for a known domain, so look first and say so.
      var low = domain.toLowerCase();
      var feed = v.rss.trim();
      apiCall("/api/sources/?limit=1000&q=" + encodeURIComponent(low)).then(function (list) {
        // A second feed of a known site is a new source (the server keeps it as a sibling);
        // only the same site with the same feed (or with no feed on both) is already there.
        var have = (list || []).filter(function (x) {
          return String(x.domain || "").toLowerCase().replace(/^www\./, "") === low
            && String(x.rss_url || "") === feed;
        })[0];
        if (have) {
          setS({ busy: false, msg: t("{name} is already in your sources.", { name: have.name || low }), err: "" });
          return null;
        }
        // "/api/sources/?" (an empty query) rather than a bare "/api/sources/": the route-caller
        // ratchet (#35) reads a literal ending in "/" as a head for any word in this file, and
        // "search" here is a view name, never a call to /api/sources/search.
        return apiCall("/api/sources/?", { method: "POST", body: JSON.stringify({
          name: v.name.trim(), domain: domain, rss_url: feed || null, tags: "" }) }).then(function (r) {
          // The server matches feeds more loosely than the check above (scheme, case, a trailing
          // slash) and hands back the existing row then: an id we already had means nothing was added.
          var known = (list || []).filter(function (x) { return r && x.id === r.id; })[0];
          if (known) {
            setS({ busy: false, msg: t("{name} is already in your sources.", { name: known.name || low }), err: "" });
            return;
          }
          setV({ name: "", domain: "", rss: "" });
          setS({ busy: false, msg: t("Added. It is collected from the next time you are online."), err: "" });
        });
      }).catch(function (er) { setS({ busy: false, msg: "", err: (er && er.message) || String(er) }); });
    }
    return html`<form class="s-card s-form" onSubmit=${submit}>
      <h2 class="s-h3">${t("Add a source")}</h2>
      <label>${t("Name")}<input type="text" value=${v.name} onInput=${field("name")} autocomplete="off" required/></label>
      <label>${t("Web address")}<input type="text" inputmode="url" placeholder="example.org" value=${v.domain} onInput=${field("domain")} autocomplete="off" required/></label>
      <label>${t("Feed address (optional)")}<input type="text" inputmode="url" value=${v.rss} onInput=${field("rss")} autocomplete="off"/></label>
      <div class="s-actions">
        <button type="submit" class="s-btn primary" disabled=${s.busy}>${t("Add")}</button>
        <${Details} what=${t("Add a source")}>
          <p>${t("Nothing is fetched now. The source is checked against its robots.txt and collected politely once you go online.")}</p>
        <//>
      </div>
      ${s.msg ? html`<p class="s-ok" role="status">${s.msg}</p>` : null}
      ${s.err ? html`<div class="s-error" role="alert">${t("Not added: {why}", { why: s.err })}</div>` : null}
    </form>`;
  }

  // ---------------------------------------------------------------- More tools
  var TOOLS = [
    ["home", "Briefing", "Every lead, with its method and evidence."],
    ["feed", "Feed", "The full feed with its keyword chips."],
    ["explore", "Explore", "Search with filters and twelve kinds of analysis."],
    ["insights", "Insights", "Trends, keyword families and maps of the corpus."],
    ["observatory", "Observatory", "The corpus as a sky of keywords."],
    ["timemap", "World map", "Coverage by country and over time."],
    ["law", "Governments", "Laws and country facts."],
    ["agenda", "Agenda", "Coming events and dates found in articles."],
    ["climate", "Climate", "Published climate and Earth records."],
    ["indices", "Indices", "Stock market indices."],
    ["markets", "Commodities", "Commodity prices and alerts."],
    ["living", "Living sources", "Changes to watched Wikipedia pages, laws and maps."],
    ["library", "Library", "What your corpus holds and how it grew."],
    ["settings", "Settings", "Language, look, sources, backup and safety."],
    ["help", "Help", "The manual."],
  ];
  function More() {
    return html`<div class="s-view">
      <h1 class="s-h1">${t("More tools")}</h1>
      <p class="s-lede">${t("These open in the full view. A bar at the top brings you back here.")}</p>
      <ul class="s-tools">${TOOLS.map(function (x) {
        return html`<li><button type="button" class="s-tool" onClick=${function () { peekFull(x[0]); }}>
          <b>${t(x[1])}</b><span>${t(x[2])}</span></button></li>`;
      })}</ul>
      <${AddSource}/>
    </div>`;
  }

  function App() {
    var s = useStore();
    var V = { today: Today, read: Read, search: Search, world: World, numbers: Numbers, more: More }[s.view] || Today;
    return html`<${V}/>`;
  }

  // ---------------------------------------------------------------- mounting
  var mounted = false;
  function hosts() {
    var main = document.getElementById("main");
    var root = document.getElementById("simple-root");
    if (!root && main) {
      root = document.createElement("div");
      root.id = "simple-root";
      root.setAttribute("data-i18n-dyn", "");
      root.setAttribute("tabindex", "-1");
      main.insertBefore(root, main.firstChild);
    }
    var nav = document.getElementById("simple-nav");
    var side = document.getElementById("sidebar");
    if (!nav && side) {
      nav = document.createElement("nav");
      nav.id = "simple-nav";
      nav.setAttribute("data-i18n-dyn", "");
      var groups = document.getElementById("navGroups");
      side.insertBefore(nav, groups || null);
    }
    if (nav) nav.setAttribute("aria-label", t("Simple view"));
    return { root: root, nav: nav };
  }
  function mount() {
    if (!html) { renderFallback(); return; }
    loadState();
    var hs = hosts();
    if (!hs.root || !hs.nav) return;
    loadStrings().then(function () {
      if (!isSimple()) return;
      P.render(html`<${Nav}/>`, hs.nav);
      P.render(html`<${App}/>`, hs.root);
      mounted = true;
      paintSwitch();
    });
  }
  function unmount() {
    if (!mounted || !html) return;
    var root = document.getElementById("simple-root"), nav = document.getElementById("simple-nav");
    if (root) P.render(null, root);
    if (nav) P.render(null, nav);
    mounted = false;
  }
  function renderFallback() {
    var hs = hosts();
    if (hs.root) {
      hs.root.textContent = t("Simple view could not start: a file it needs did not load. Use the switch in the top bar to return to the full view.");
      hs.root.setAttribute("role", "alert");
    }
  }

  function backBar() {
    if (document.getElementById("simple-back")) return;
    var chrome = document.querySelector(".chrome");
    if (!chrome) return;
    var bar = document.createElement("div");
    bar.id = "simple-back";
    bar.setAttribute("data-i18n-dyn", "");
    bar.setAttribute("role", "region");
    bar.setAttribute("aria-label", t("Simple view"));
    var msg = document.createElement("span");
    msg.className = "simple-back-msg";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.addEventListener("click", backToSimple);
    bar.appendChild(msg);
    bar.appendChild(btn);
    var top = chrome.querySelector(".topbar");
    chrome.insertBefore(bar, top ? top.nextSibling : chrome.firstChild);
  }

  function init() {
    wrapShowTab();
    backBar();
    var b = document.getElementById("ui-simple-toggle");
    if (b) b.addEventListener("click", onSwitch);
    watchNetwork();
    paintSwitch();
    document.addEventListener("oo:langchange", function () {
      loadStrings().then(function () { paintSwitch(); if (mounted) emit(); var hs = hosts(); });
    });
    if (isSimple()) mount();
    // The full app's boot navigation (the initial showTab from the URL hash) has run once the
    // page has loaded; only after that is a showTab call a reader's request.
    var done = function () { setTimeout(function () { _booted = true; }, 1500); };
    if (document.readyState === "complete") done(); else window.addEventListener("load", done);
    // Open the strings for the switch label even in full mode.
    loadStrings().then(paintSwitch);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  // For tests and the More tools list; nothing else calls these.
  window.ooSimple = { enter: enterSimple, leave: leaveSimple, back: backToSimple, go: go, mode: mode };
})();
