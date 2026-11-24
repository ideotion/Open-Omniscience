// Markets follows a language switch (row 367, app-markets.js), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Eight renderers wrote t() output into ordinary nodes, so their words stayed in the language that was active when
// they were drawn. Now:
//   * the commodities and indices boards are drawn again from what they hold by repaintMarketBoards, which app-boot's
//     one oo:langchange listener calls; it never reads, and a board not drawn yet is left alone;
//   * the feed verdict list and the retry line are held renders;
//   * the shared time-range control (ooTimeScope, also used by Explore and Insights) holds its words, its options
//     (keeping the scale in use) and its attributes.
//
// The WHOLE shipped app-markets.js is run, with the shipped ooLive family EXTRACTED from the engine; t()/tf() are the
// shipped i18n engine over the shipped locales. Only the network, the subtab component and the chart canvas are stubs.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");

const MARKETS_JS = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-markets.js"), "utf-8");

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
    this.listeners = {}; this.dataset = {};
    this.classList = { add: (c) => { if (!this.cls.includes(c)) this.cls.push(c); }, toggle() {}, contains: (c) => this.cls.includes(c) };
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
      el.parentEl = this;
      this._kids.push(el);
      if (id) REGISTRY.fresh(id[1], el);
    }
  }
  _drop() { for (const k of this._kids) { k._connected = false; k._drop(); } this._kids = []; }
  _all() { return this._kids.flatMap((k) => [k, ...k._all()]); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) { const c = sel.replace(/^\./, ""); return this._all().filter((k) => k.isConnected && k.cls.includes(c)); }
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  fire(ev, target) { (this.listeners[ev] || []).forEach((fn) => fn({ target: target || this, preventDefault() {} })); }
  focus() {}
  getElementsByTagName() { return this._all().filter((k) => k.isConnected); }
  getBoundingClientRect() { return { left: 0, width: 100 }; }
}
let REGISTRY = null;

const CORE = ["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml",
  "ooLiveRepaint", "ooLabelHtml", "ooLtrIsolate", "_ltrIsolate"];

function harness(answers) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  REGISTRY = { fresh(id, el) { if (nodes[id]) nodes[id]._connected = false; nodes[id] = el; } };
  for (const id of ["idx-board", "indices-cats", "indices-tags", "idx-compare-bar", "idx-timescope", "idx-timescope-row",
    "idx-viewtoggle", "mkt-dashboard", "mkt-dash-status", "commodities-cats", "mkt-viewtoggle", "mkt-timescope", "mkt-verdicts", "box"]) nodes[id] = new El("DIV");
  const calls = { api: [], charts: [], subtabs: 0 };
  const api = async (url, o) => {
    const key = ((o && o.method) || "GET") + " " + url;
    calls.api.push(key);
    const a = answers[key] !== undefined ? answers[key] : answers[url];
    if (a === undefined) throw new Error("unexpected call " + key);
    if (a instanceof Error) throw a;
    return a;
  };
  const src = [
    "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
    extractConst("esc"), extractConst("_LTR_ISOLATE"),
    ...CORE.map(extract),
    "function fmtNum(x) { return String(x); }",
    MARKETS_JS,
    // the canvas is not what is tested: the chart records the labels it was handed, and keeps a view the way the
    // shipped one does (_ooChartArgs, _ooChartView, _ooChartSetView, a pending view taken at build)
    "ooChart = (el, series) => { __calls.charts.push(series.map((s) => s.label)); el._ooChartArgs = [series];" +
    " el.__view = el._ooChartViewToTake || null; el._ooChartViewToTake = null;" +
    " el._ooChartView = () => el.__view || { t0: 0, t1: 1, full: true, hidden: [] }; el._ooChartSetView = (v) => { el.__view = v; }; };",
    "return { renderIndicesBoard, renderDashboard, repaintMarketBoards, loadDashboard, _renderFeedVerdicts, retryFailedFeeds, ooTimeScope," +
    " ooLiveRepaint, set(o) { if ('cards' in o) _idxCards = o.cards; if ('idxView' in o) _idxView = o.idxView;" +
    " if ('series' in o) MKT_SERIES = o.series; if ('prices' in o) Object.assign(MKT_PRICES, o.prices); if ('loaded' in o) _idxSeriesLoaded = o.loaded;" +
    " if (o.clear) for (const k in MKT_PRICES) delete MKT_PRICES[k]; } };",
  ].join("\n");
  const document = { createElement: (tag) => new El(tag.toUpperCase()), documentElement: { dir: "ltr" }, querySelectorAll: () => [] };
  const window = { OOI18N, addEventListener() {}, devicePixelRatio: 1 };
  const env = {
    window, OOI18N, document, MutationObserver: undefined, console, __calls: calls,
    $: (id) => nodes[id] || null, api, toast() {}, extLink: (u, l) => l,
    ooSubtabs: (nav, onSelect, opts) => { calls.subtabs++; return { select() {}, paint() {} }; },
    ensureOnline: async () => true, _failMsg: (k, e) => e.message,
  };
  const fns = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns, nodes, calls, $: (id) => nodes[id],
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      // app-boot's ONE oo:langchange listener: the boards are drawn again, then every held node
      fns.repaintMarketBoards();
      fns.ooLiveRepaint();
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));

const CARDS = [
  { symbol: "^A", name: "Alpha", continent: "Europe", tags: ["x", "y"], latest: { price: 10, observed_on: "2026-01-02" }, spark: [["2026-01-01", 9], ["2026-01-02", 10]] },
  { symbol: "^B", name: "Beta", continent: "Asia", tags: ["y"], latest: { price: 20, observed_on: "2026-01-02" }, spark: [["2026-01-01", 21], ["2026-01-02", 20]] },
];
const PRICES = {
  "^A": [{ observed_on: "2026-01-01", price: 9, currency: "EUR", unit: "pt" }, { observed_on: "2026-01-02", price: 10, currency: "EUR", unit: "pt" }],
  "^B": [{ observed_on: "2026-01-01", price: 21, currency: "EUR", unit: "pt" }, { observed_on: "2026-01-02", price: 20, currency: "EUR", unit: "pt" }],
  GOLD: [{ observed_on: "2026-01-01", price: 1, currency: "USD", unit: "oz" }, { observed_on: "2026-01-02", price: 2, currency: "USD", unit: "oz" }],
  OIL: [{ observed_on: "2026-01-01", price: 70, currency: "USD", unit: "bbl" }, { observed_on: "2026-01-02", price: 71, currency: "USD", unit: "bbl" }],
};

(async () => {
  // 1. The boards: nothing is drawn before a board has been drawn once; then a switch draws both again in the new
  //    language, from the prices they hold, with no request.
  {
    const h = harness({});
    h.switchTo("fr");
    assert.strictEqual(h.calls.charts.length, 0, "a board not drawn yet is left alone");
    assert.strictEqual(h.$("idx-board").innerHTML, "");
    h.switchTo("en");
    h.fns.set({ cards: CARDS, idxView: "families", loaded: true, prices: PRICES,
      series: [{ symbol: "GOLD", name: "Gold", category: "metals" }, { symbol: "OIL", name: "Oil", category: "energy" }] });
    h.fns.renderIndicesBoard();
    h.fns.renderDashboard();
    const idx = h.$("idx-board"), dash = h.$("mkt-dashboard"), cats = h.$("commodities-cats");
    assert.ok(idx.innerHTML.includes(`<span>${esc("Europe")} `), idx.innerHTML);
    assert.ok(dash.innerHTML.includes("Indexed to 100 at the window start"), "the family caveat is drawn");
    assert.ok(cats.innerHTML.includes(">All</button>"), cats.innerHTML);
    const sent = h.calls.api.length, drawn = h.calls.charts.length;
    h.switchTo("fr");
    assert.ok(idx.innerHTML.includes(`<span>${esc(FR["Asia"])} `), "the indices families follow a switch: " + idx.innerHTML);
    assert.ok(dash.innerHTML.includes(esc(FR["Indexed to 100 at the window start — relative moves, not absolute levels; the hover shows the real value."])),
      "the commodities caveat follows a switch");
    assert.ok(cats.innerHTML.includes(">" + esc(FR["All"]) + "</button>"), "the category tabs follow a switch: " + cats.innerHTML);
    assert.ok(h.$("indices-cats").innerHTML.includes(">" + esc(FR["Asia"]) + "</button>"), h.$("indices-cats").innerHTML);
    assert.ok(h.calls.charts.length > drawn, "the charts are drawn again");
    assert.strictEqual(h.calls.api.length, sent, "a switch sends no request");
  }
  {
    // the indices families view waits for its own series read; a switch never starts one
    const h = harness({});
    h.fns.set({ cards: CARDS, idxView: "families", loaded: false });
    h.fns.renderIndicesBoard();          // starts the series read (fetchPrices) as before
    await tick();
    const sent = h.calls.api.length;
    h.switchTo("fr");
    assert.strictEqual(h.calls.api.length, sent, "a switch starts no read of its own");
  }

  {
    // a switch keeps the reader's zoom and hidden series on each chart, matched by the series it draws
    const h = harness({});
    h.fns.set({ cards: CARDS, idxView: "families", loaded: true, prices: PRICES, series: [] });
    h.fns.renderIndicesBoard();
    const charts = () => h.$("idx-board").getElementsByTagName("*").filter((el) => el._ooChartArgs);
    const europe = () => charts().find((el) => el._ooChartArgs[0][0].symbol === "^A");
    const asia = () => charts().find((el) => el._ooChartArgs[0][0].symbol === "^B");
    assert.ok(europe() && asia(), "one chart per family");
    const old = europe();
    old.__view = { t0: 5, t1: 6, full: false, hidden: ["^A"] };
    h.switchTo("fr");
    assert.notStrictEqual(europe(), old, "the chart was drawn again");
    assert.deepStrictEqual(europe().__view, { t0: 5, t1: 6, full: false, hidden: ["^A"] }, "the window and hidden series come back");
    assert.ok(!asia().__view || (asia().__view.full && !asia().__view.hidden.length), "another chart's view is not handed over");
    // matched by series, not by place: with the first family gone the Europe chart still gets its own view
    h.fns.set({ cards: [CARDS[0]] });
    h.switchTo("en");
    assert.strictEqual(charts().length, 1);
    assert.deepStrictEqual(europe().__view, { t0: 5, t1: 6, full: false, hidden: ["^A"] }, "matched by the series drawn");
    h.fns.set({ cards: CARDS });
    h.switchTo("fr");
    // a chart not laid out yet keeps the view it was waiting with
    const wait = europe(); wait.__view = null; wait._ooChartView = null; wait._ooChartViewToTake = { t0: 7, t1: 8, full: false, hidden: [] };
    h.switchTo("de");
    assert.deepStrictEqual(europe().__view, { t0: 7, t1: 8, full: false, hidden: [] }, "a pending view is carried too");
  }
  {
    // a switch while the prices are being read again draws nothing then, and is drawn when the read ends
    let answer;
    const h = harness({
      "GET /api/markets/series": new Promise((r) => { answer = r; }),
      "GET /api/commodities/%5EA/prices": { prices: PRICES["^A"] }, "GET /api/commodities/%5EB/prices": { prices: PRICES["^B"] },
      "GET /api/commodities/GOLD/prices": { prices: PRICES.GOLD }, "GET /api/commodities/OIL/prices": { prices: PRICES.OIL },
    });
    h.fns.set({ cards: CARDS, idxView: "families", loaded: true, prices: PRICES, series: [] });
    h.fns.renderIndicesBoard();
    const idx = h.$("idx-board"), before = idx.innerHTML;
    h.fns.set({ clear: true });           // a refresh or an import empties the prices, then reads them again
    const run = h.fns.loadDashboard();
    h.switchTo("fr");
    assert.strictEqual(idx.innerHTML, before, "nothing is drawn from emptied prices");
    answer({ series: [{ symbol: "^A", category: "index" }, { symbol: "^B", category: "index" },
      { symbol: "GOLD", name: "Gold", category: "metals" }, { symbol: "OIL", name: "Oil", category: "energy" }] });
    await run;
    assert.notStrictEqual(FR["Asia"], "Asia");
    assert.ok(idx.innerHTML.includes(`<span>${esc(FR["Asia"])} `), "the owed switch is drawn when the read ends: " + idx.innerHTML);
    assert.ok(!idx.innerHTML.includes(esc(FR["No data in this window yet."])), idx.innerHTML);
  }

  // 2. The feed verdicts and the retry line are held.
  {
    const h = harness({ "POST /api/markets/feeds/import-all?keys=f1": new Error("refused") });
    const r = { results: [{ key: "f1", symbol: "S1", status: "fetch_failed", verdict: "dead-series", verdict_note: "gone" }],
      retryable_failed_keys: ["f1"], skipped_offline: 2 };
    h.fns._renderFeedVerdicts("mkt-verdicts", r, "");
    const box = h.$("mkt-verdicts");
    assert.ok(box.innerHTML.includes(">Retry failed feeds (1)</button>"), box.innerHTML);
    h.switchTo("fr");
    assert.ok(box.innerHTML.includes(">" + esc(FR["Retry failed feeds"]) + " (1)</button>"), "the retry button follows a switch: " + box.innerHTML);
    assert.ok(box.innerHTML.includes(esc(FR["{n} not fetched (airplane mode)"].replace("{n}", "2"))), box.innerHTML);
    const run = h.fns.retryFailedFeeds("", "f1", "mkt-verdicts");
    assert.ok(box.innerHTML.includes(esc(FR["Retry failed feeds"])), "the list stays until the consent answers");
    await tick();
    await run;
    assert.strictEqual(box.textContent, "refused", "the failure is shown as the server said it");
    let finish;
    const h2 = harness({ "POST /api/markets/feeds/import-all?keys=f1": new Promise((r2) => { finish = r2; }) });
    h2.fns._renderFeedVerdicts("mkt-verdicts", r, "");
    const run2 = h2.fns.retryFailedFeeds("", "f1", "mkt-verdicts");
    await tick();
    assert.strictEqual(h2.$("mkt-verdicts").textContent, "Retrying failed feeds…");
    h2.switchTo("de");
    assert.strictEqual(h2.$("mkt-verdicts").textContent, DE["Retrying failed feeds…"], "the retry line follows a switch");
    finish({ results: [], points_imported: 1, failed: 0 });
    await run2;
  }

  // 3. The time-range control: its words, its presets, its scale options (keeping the scale in use) and its attributes
  //    follow a switch; the control is out of the page walker's reach.
  {
    const h = harness({});
    const box = h.$("box");
    const ctl = h.fns.ooTimeScope(box, { min: "2026-01-01", max: "2026-12-31", from: "2026-03-10", to: "2026-09-16" });
    assert.ok(box.hasAttribute("data-i18n-dyn"), "the walker stays out of the control");
    const q = (c) => box.querySelector(c);
    assert.strictEqual(q("ts-l-from").textContent, "From");
    assert.strictEqual(q("ts-bar").getAttribute("aria-label"), "Date range");
    const scale = q("ts-scale");
    scale.value = "month"; scale.fire("change");
    assert.strictEqual(ctl.get().scale, "month");
    h.switchTo("fr");
    assert.strictEqual(q("ts-l-from").textContent, FR["From"], "the label follows a switch");
    assert.strictEqual(q("ts-l-scale").textContent, FR["Snap range to"]);
    assert.strictEqual(q("ts-bar").getAttribute("aria-label"), FR["Date range"], "the bar's name follows a switch");
    assert.strictEqual(q("ts-h-to").getAttribute("aria-label"), FR["To"]);
    assert.ok(q("ts-scale-l").getAttribute("title").startsWith(FR["Reads the range in whole days, weeks, months or years: each bound snaps to the start or end of its period. The data inside the range is never thinned."].slice(0, 20)));
    assert.ok(scale.innerHTML.includes(`<option value="month" selected>${esc(FR["Months"])}</option>`), "the scale in use stays chosen: " + scale.innerHTML);
    assert.ok(q("ts-presets").innerHTML.includes(`data-preset="All">${esc(FR["All"])}</button>`), "the presets follow a switch: " + q("ts-presets").innerHTML);
    // a scale the reader picks is the one still chosen after a switch
    scale.value = "year"; scale.fire("change");
    h.switchTo("de");
    assert.ok(scale.innerHTML.includes(`<option value="year" selected>${esc(DE["Years"])}</option>`), scale.innerHTML);
    h.switchTo("fr");
    // a control built again on the same box: the earlier holds go with it, and the degraded form is held too
    h.fns.ooTimeScope(box, {});
    assert.ok(box.innerHTML.includes(esc(FR["not enough data for a time range"])), box.innerHTML);
    h.switchTo("de");
    assert.ok(box.innerHTML.includes(esc(DE["not enough data for a time range"])), "the degraded line follows a switch: " + box.innerHTML);
    // and a full control built again over the degraded line is not drawn over by it at the next switch
    h.fns.ooTimeScope(box, { min: "2026-01-01", max: "2026-12-31" });
    h.switchTo("fr");
    assert.strictEqual(q("ts-l-from").textContent, FR["From"], "the rebuilt control keeps its words: " + box.innerHTML);
    assert.ok(!box.innerHTML.includes(esc(FR["not enough data for a time range"])), box.innerHTML);
  }

  console.log("markets_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
