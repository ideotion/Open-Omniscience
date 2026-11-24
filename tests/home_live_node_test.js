// The Home tab follows a language switch (row 367, app-home.js), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Thirteen renderers wrote t() output into ordinary nodes, so their words stayed in the language that was active when
// they were drawn. Now the "Loading…" lines (Feed, Latest, Most recent, a weather check, the link preview) are held
// until what they wait for lands; the link preview's lines and the trending strip are held; the alert strip and the
// Leads carousel are drawn again from what they hold (repaintHomeAlerts, repaintLeadsCarousel, from app-boot's one
// oo:langchange listener); a late subtab's label and the dismiss-reason form are held.
//
// The WHOLE shipped app-home.js is run, with the shipped ooLive family EXTRACTED from the engine; t()/tf() are the
// shipped i18n engine over the shipped locales. Only the network and helpers from other files are stubs.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");

const HOME_JS = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-home.js"), "utf-8");
const BOOT_JS = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-boot.js"), "utf-8");

function extract(name) {
  const marker = "function " + name + "(";
  const at0 = APP.indexOf(marker);
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
  let i = APP.indexOf("(", at0), depth = 0;
  for (; i < APP.length; i++) {
    if (APP[i] === "(") depth++;
    else if (APP[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = APP.indexOf("{", i);
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at0, j);
}
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  return APP.slice(at, APP.indexOf(";\n", at) + 1);
}
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));
const FR = locale("fr"), DE = locale("de");
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}
// A small element: markup written into it makes a child element for every tag with an id or a class, found again by
// $(id), querySelector(".cls") and querySelectorAll(".cls"); those children leave the page when the markup is replaced.
class El {
  constructor(tag, cls) {
    this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null;
    this.style = {}; this.value = ""; this._connected = true; this._kids = []; this.cls = cls || [];
    this.listeners = {}; this.dataset = {}; this.disabled = false; this.hidden = false; this.placeholder = "";
    this.className = "";
  }
  get isConnected() { return this._connected; }
  hasAttribute(a) { return Object.prototype.hasOwnProperty.call(this.attrs, a); }
  getAttribute(a) { return this.hasAttribute(a) ? this.attrs[a] : null; }
  setAttribute(a, v) { this.attrs[a] = String(v); }
  removeAttribute(a) { delete this.attrs[a]; }
  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = nodes; this._html = null;
    for (const c of nodes) c.parentNode = this;
  }
  appendChild(c) { this.childNodes.push(c); c.parentNode = this; this._html = null; return c; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this._drop(); this.replaceChildren(...(v === "" ? [] : [new Text(String(v))])); }
  get innerHTML() { return this._html != null ? this._html : this.textContent; }
  set innerHTML(v) {
    const html = String(v);
    this._drop();
    this.replaceChildren(new Text(html)); this._html = html;
    for (const m of html.matchAll(/<(\w+)([^>]*)>/g)) {
      const id = /\bid="([^"]+)"/.exec(m[2]), cl = /\bclass="([^"]+)"/.exec(m[2]);
      if (!id && !cl) continue;
      const el = new El(m[1].toUpperCase(), cl ? cl[1].split(/\s+/) : []);
      for (const at of m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) el.attrs[at[1]] = at[2] == null ? "" : at[2];
      this._kids.push(el);
      if (id) REGISTRY.fresh(id[1], el);
    }
  }
  _drop() { for (const k of this._kids) { k._connected = false; k._drop(); } this._kids = []; }
  _all() { return this._kids.flatMap((k) => [k, ...k._all()]); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) { const c = sel.replace(/^\./, ""); return this._all().filter((k) => k.isConnected && k.cls.includes(c)); }
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  showModal() { this.open = true; }
  focus() {}
  remove() { this._connected = false; }
}
let REGISTRY = null;

const CORE = ["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml",
  "ooLiveRepaint", "_tfn", "ooLabelHtml"];

function harness(answers) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  REGISTRY = { fresh(id, el) { if (nodes[id]) nodes[id]._connected = false; nodes[id] = el; } };
  for (const id of ["feed-list", "feed-more", "home-latest-panel", "home-latest", "home-recent-panel", "home-recent",
    "home-trends-panel", "home-trends", "ov-trending", "home-alerts-panel", "home-alerts", "home-carousel-panel",
    "home-carousel", "link-preview", "lp-body", "lp-out", "wx-c1", "home-channels-panel"]) nodes[id] = new El("DIV");
  nodes["feed-list"].insertAdjacentHTML = function (_w, h) { this._html = (this._html || "") + h; };
  nodes["home-channels-panel"].hidden = true;
  const calls = { api: [] };
  const held = [];
  const api = (url, o) => {
    const key = ((o && o.method) || "GET") + " " + url.split("?")[0];
    calls.api.push(key);
    const a = answers[key];
    if (a === "hold") return new Promise((resolve, reject) => held.push({ resolve, reject }));
    if (a === undefined) return Promise.reject(new Error("unexpected call " + key));
    if (a instanceof Error) return Promise.reject(a);
    return Promise.resolve(a);
  };
  // The dismiss form's card: a .card with its .acts row, found the way dismissCard finds it.
  const acts = new El("DIV", ["acts"]);
  acts.querySelector = (sel) => (sel === ".lead-dismiss-form" ? acts.childNodes.find((c) => c.className === sel.slice(1)) || null : null);
  const card = { querySelector: (sel) => (sel === ".acts" ? acts : null) };
  // The Home subtab strip: buttons found by their data-tab, the way _syncHomeSubtabs looks for them.
  const nav = new El("NAV");
  nav.querySelectorAll = () => nav.childNodes.filter((b) => b.isConnected);
  nav.querySelector = (sel) => { const k = /data-tab="([^"]+)"/.exec(sel)[1]; return nav.childNodes.find((b) => b.dataset.tab === k) || null; };
  nodes["home-fam-subtabs"] = nav;
  const src = [
    "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
    extractConst("esc"),
    ...CORE.map(extract),
    "function fmtNum(x) { return String(x); }",
    HOME_JS,
    "return { loadFeed, loadHomeLatest, loadHomeRecentList, loadHomeTrends, loadHomeAlerts, repaintHomeAlerts," +
    " renderLeadsCarousel, carouselToggle, carouselStep, repaintLeadsCarousel, dismissCard, openLinkPreview," +
    " cardWeatherFetch, _syncHomeSubtabs, ooLiveRepaint, setBrief: (o) => { _briefCards = o; } };",
  ].join("\n");
  const document = {
    createElement: (tag) => new El(tag.toUpperCase()), documentElement: { dir: "ltr" }, querySelectorAll: () => [],
    querySelector: (sel) => (sel.startsWith(".card[") ? card : null), getElementById: (id) => nodes[id] || null,
  };
  const window = { OOI18N, addEventListener() {}, devicePixelRatio: 1, open() {} };
  const env = {
    window, OOI18N, document, MutationObserver: undefined, console, setInterval: () => 1, clearInterval() {},
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    $: (id) => nodes[id] || null, api, toast() {}, confirm: () => true, ensureOnline: async () => true,
    ooSaidText: (o, f) => String(o[f] || ""), ooSaidHtml: (o, f) => esc(o[f] || ""),
    ooCountryCell: (c) => esc(c), ooCountryTitle: () => "", ooIsoDate: (d) => d, ooIsoDateTime: (d) => d, fmtAgo: (d) => d,
    ooFetchedOffSiteNote: () => "", safeUrl: (u) => u, uiLangCode: () => lang, tgtLangParam: () => "",
    kwLabelHtml: (x) => esc(x.term), kwQidHtml: () => "", growthIsRatio: () => true, growthFallback: () => "",
    trendRateText: () => "", dashChartSvg: () => "", ooSubtabs() {}, ooCardDismissedUndo() {},
    openAnalysisForIds() {}, chartEnlarge() {}, ooChart() {},
  };
  const fns = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns, nodes, calls, held, acts, nav, $: (id) => nodes[id],
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      // app-boot's ONE oo:langchange listener, in its order: the held nodes, then the Home strip and carousel
      fns.ooLiveRepaint();
      fns.repaintHomeAlerts();
      fns.repaintLeadsCarousel();
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));
const has = (el, s) => el.innerHTML.includes(s) || el.textContent.includes(s);

(async () => {
  // 1. The "Loading…" lines: Latest, Most recent and the Feed's, while their read is in flight; the rows that land
  //    then draw over them.
  {
    const h = harness({ "GET /api/insights/latest": "hold", "GET /api/articles": "hold", "GET /api/feed": "hold" });
    h.fns.loadHomeLatest();
    h.fns.loadHomeRecentList("t1");
    h.fns.loadFeed(true);
    for (const id of ["home-latest", "home-recent", "feed-more"]) assert.ok(has(h.$(id), "Loading…"), id);
    h.switchTo("fr");
    for (const id of ["home-latest", "home-recent", "feed-more"]) {
      assert.ok(has(h.$(id), esc(FR["Loading…"])), id + " follows a switch: " + h.$(id).innerHTML);
    }
    h.held[1].resolve({ results: [{ id: 7, title: "Seven", source: "S", published_at: "2026-11-01" }] });
    await tick();
    assert.ok(has(h.$("home-recent"), "Seven"), "the rows draw over the held line");
    h.switchTo("de");
    assert.ok(has(h.$("home-recent"), "Seven") && !has(h.$("home-recent"), esc(DE["Loading…"])),
      "the held line is let go once the rows are drawn: " + h.$("home-recent").innerHTML);
  }

  // 2. The alert strip: the scan-still-running line, then the strip itself, drawn again from what it holds.
  {
    const h = harness({ "GET /api/signals/alerts": { building: true } });
    await h.fns.loadHomeAlerts();
    assert.ok(has(h.$("home-alerts"), "Checking for alerts…"));
    h.switchTo("fr");
    assert.ok(has(h.$("home-alerts"), esc(FR["Checking for alerts…"])), "the running-scan line follows a switch");
    const h2 = harness({ "GET /api/signals/alerts": { total: 1, hazards_available: false, tiers: {
      urgent: { count: 1, hazards: [{ type: "flood", place: "Riverside", major: false }] } } } });
    await h2.fns.loadHomeAlerts();
    const box = h2.$("home-alerts");
    assert.ok(has(box, ">" + esc("Alerts") + "<") && has(box, esc("Urgent")), box.innerHTML);
    h2.switchTo("de");
    for (const k of ["Alerts", "Urgent", "Flood", "No local hazard snapshot — silence is not safety."]) {
      assert.ok(has(box, esc(DE[k])), k + " follows a switch: " + box.innerHTML);
    }
    assert.strictEqual(h2.calls.api.length, 1, "a switch never reads the alerts again");
    // an empty strip has nothing to draw again
    const h3 = harness({ "GET /api/signals/alerts": { total: 0 } });
    await h3.fns.loadHomeAlerts();
    h3.switchTo("fr");
    assert.strictEqual(h3.$("home-alerts").innerHTML, "", "an empty strip stays empty");
  }

  // 3. The Leads carousel: its names and buttons, and the face showing, keep their place and their pause state.
  {
    const h = harness({});
    const cards = [1, 2, 3].map((i) => ({ id: "c" + i, title: "Lead " + i, summary: "", type: "x", bucket: "b" }));
    h.fns.renderLeadsCarousel(cards);
    const car = h.$("home-carousel").querySelector(".carousel");
    assert.ok(car.hasAttribute("data-i18n-dyn"), "the walker is kept off the words the carousel writes");
    assert.strictEqual(car.getAttribute("aria-label"), "Leads");
    h.fns.carouselStep(1);
    h.fns.carouselToggle();
    h.switchTo("fr");
    const pause = h.$("carousel-pause");
    assert.strictEqual(car.getAttribute("aria-label"), FR["Leads"], "the region's name follows a switch");
    assert.strictEqual(car.getAttribute("aria-roledescription"), FR["carousel"]);
    assert.strictEqual(h.$("home-carousel").querySelector(".carousel-prev").getAttribute("aria-label"), FR["Previous Lead"]);
    assert.strictEqual(pause.getAttribute("aria-label"), FR["Play the carousel"], "the paused state is kept, in French");
    assert.strictEqual(pause.textContent, "▶");
    const face = h.$("carousel-face");
    assert.ok(has(face, "Lead 2") && has(face, esc(FR["Open corpus"])), "the face showing stays, redrawn: " + face.innerHTML);
    // a carousel never drawn is left alone
    const h2 = harness({});
    h2.switchTo("fr");
    assert.strictEqual(h2.$("home-carousel").innerHTML, "");
  }

  // 4. The dismiss-reason form: its prompt, each reason, the field's placeholder and the button; what is typed stays.
  {
    const h = harness({});
    h.fns.dismissCard("c1", "x");
    const form = h.acts.childNodes[0];
    assert.ok(form.hasAttribute("data-i18n-dyn"), "the walker is kept off the placeholder");
    const [label, chips, row] = form.childNodes;
    const inp = row.childNodes[0], go = row.childNodes[1];
    assert.strictEqual(label.textContent, "Why dismiss? (optional)");
    assert.strictEqual(inp.placeholder, "Add a reason…");
    inp.value = "mine";
    h.switchTo("de");
    assert.strictEqual(label.textContent, DE["Why dismiss? (optional)"]);
    assert.strictEqual(chips.childNodes[0].textContent, DE["Not relevant"], "a reason follows a switch");
    assert.strictEqual(go.textContent, DE["Dismiss"]);
    assert.strictEqual(inp.placeholder, DE["Add a reason…"], "the placeholder follows a switch");
    assert.strictEqual(inp.value, "mine", "what is typed is kept");
  }

  // 5. The link preview: its loading line, then every line of what the database knows and the outbound link's note.
  {
    const h = harness({ "GET /api/links/preview": "hold" });
    const p = h.fns.openLinkPreview("https://example.org/a");
    assert.strictEqual(h.$("lp-body").textContent, "Loading…");
    h.switchTo("fr");
    assert.strictEqual(h.$("lp-body").textContent, FR["Loading…"]);
    h.held[0].resolve({ domain: "example.org", url: "https://example.org/a", cited_by_articles: 3,
      known_source: { name: "Ex" } });
    await p;
    h.switchTo("de");
    const body = h.$("lp-body"), out = h.$("lp-out");
    for (const k of ["Known source in your catalog:", "Articles in your corpus citing this URL:",
      "Built from your local database only — no network call."]) assert.ok(has(body, esc(DE[k])), k + ": " + body.innerHTML);
    assert.ok(has(out, esc(DE["The transparent outbound link — its text is the full address; opening it leaves this machine:"])), out.innerHTML);
    assert.ok(has(out, "https://example.org/a"), "the full address stays");
  }

  // 6. A weather check's loading line, while the held slice is looked up.
  {
    const h = harness({ "GET /api/weather/context/held": "hold" });
    h.fns.setBrief({ c1: { title: "T", signal: { lat: 1, lon: 2, window_start: "2026-01-01", window_end: "2026-01-02" } } });
    const p = h.fns.cardWeatherFetch("c1");
    h.switchTo("fr");
    assert.strictEqual(h.$("wx-c1").textContent, FR["Loading…"], "the weather check's loading line follows a switch");
    h.held[0].resolve({ held: true, ok: true, daily: { time: [] }, provenance: {} });
    await p;
    h.switchTo("de");
    const wx = h.$("wx-c1");
    assert.ok(has(wx, "Open-Meteo") && !has(wx, DE["Loading…"]), "the drawn slice is never overwritten by the held line: " + wx.innerHTML);
  }

  // 7. Trending: the "not computed" line (the server's words, keyed) follows a switch; the cards keep what they drew
  //    under another language (their rows carry the language they were read for) and redraw under the same one.
  {
    const h = harness({ "GET /api/insights/trending-windows": { partial: true, caveat: "Loading…", windows: [] } });
    await h.fns.loadHomeTrends();
    h.switchTo("fr");
    assert.ok(has(h.$("home-trends"), esc(FR["Loading…"])), "the partial answer's line follows a switch");
    const h2 = harness({ "GET /api/insights/trending-windows": { windows: [{ label: "7d",
      terms: [{ term: "storm", growth: 3, series: [{ date: "2026-11-01", count: 2 }] }] }] } });
    await h2.fns.loadHomeTrends();
    const box = h2.$("home-trends");
    assert.ok(has(box, esc("Enlarge the chart")), box.innerHTML);
    h2.switchTo("fr");
    assert.ok(has(box, esc("Enlarge the chart")) && !has(box, esc(FR["Enlarge the chart"])),
      "rows read for English are not redrawn under French tags (M8)");
    h2.switchTo("en");
    assert.ok(has(box, esc("Enlarge the chart")), "back under the language they were read for, they redraw");
  }

  // 8. A subtab that arrives late: its label follows a switch.
  {
    const h = harness({});
    h.$("home-recent-panel").hidden = false;
    h.$("home-latest-panel").hidden = true;
    h.fns._syncHomeSubtabs();
    const b = h.nav.childNodes.find((x) => x.dataset.tab === "__recent");
    assert.strictEqual(b.textContent, "Most recent");
    h.switchTo("fr");
    assert.strictEqual(b.textContent, FR["Most recent"], "a late subtab's label follows a switch");
  }

  // 9. The listener: both redraws are called from app-boot's ONE oo:langchange listener.
  {
    const at = BOOT_JS.indexOf('document.addEventListener("oo:langchange"');
    assert.ok(at !== -1);
    for (const fn of ["repaintHomeAlerts()", "repaintLeadsCarousel()"]) {
      assert.strictEqual(BOOT_JS.split(fn).length - 1, 1, fn + " is called once");
      assert.ok(BOOT_JS.indexOf(fn) > at, fn + " is in the listener");
    }
  }

  // Every word checked above has its own translation in the language it is checked in, so a check that passes is not
  // passing on English.
  const own = (loc, name, keys) => keys.forEach((k) => assert.ok(loc[k] && loc[k] !== k, name + " has its own words for " + k));
  own(FR, "fr", ["Loading…", "Checking for alerts…", "Leads", "carousel", "Previous Lead", "Play the carousel", "Open corpus",
    "Enlarge the chart", "Most recent", "The transparent outbound link — its text is the full address; opening it leaves this machine:"]);
  own(DE, "de", ["Loading…", "Alerts", "Urgent", "Flood", "No local hazard snapshot — silence is not safety.",
    "Why dismiss? (optional)", "Not relevant", "Dismiss", "Add a reason…", "Known source in your catalog:",
    "Articles in your corpus citing this URL:", "Built from your local database only — no network call.",
    "The transparent outbound link — its text is the full address; opening it leaves this machine:"]);
  console.log("home_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
