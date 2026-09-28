/**
 * Behavioural node test for batch B8 of the 2026-09-26 delegated click-through:
 * the Home at-a-glance strip (H8, P7, S4, U5), the Library's Database & storage tiles
 * (S6), and the task-manager page's language handling (T5, O4).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name -- a re-typed
 * copy would pass while the real code was still broken (the sibling-test convention;
 * see tests/axis_honesty_node_test.js). Translations come from the REAL locale files,
 * so "the label is translated" means translated by what ships, not by a fixture map.
 *
 * Run by tests/test_clickthrough_b8_fixes.py (and standalone:
 * `node tests/clickthrough_b8_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const HOME = fs.readFileSync(path.join(STATIC, "app-home.js"), "utf-8");
const LIB = fs.readFileSync(path.join(STATIC, "app-library.js"), "utf-8");
const TM = require("./app_source.js").pageSource("taskmanager.html");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) {
  return Promise.resolve().then(fn).then(() => { passed += 1; console.log("ok  - " + name); });
}

// Same balanced-brace extraction every node suite here uses (duplicated per convention).
function extract(name, decl, src) {
  const head = decl || ("function " + name + "(");
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let j = src.indexOf("(", at); j < src.length; j++) {
    if (src[j] === "(") p++;
    else if (src[j] === ")") { p--; if (p === 0) { i = src.indexOf("{", j); break; } }
  }
  assert(i !== -1, "could not find the body of " + head);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}
// A `const NAME = {...};` / `[...]` literal, bracket-matched (its values hold no brackets).
function extractConst(name, src) {
  const head = "const " + name + " = ";
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  const open = at + head.length, oc = src[open], cc = oc === "{" ? "}" : "]";
  let depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === oc) depth++;
    else if (src[j] === cc) { depth--; if (depth === 0) return src.slice(at, j + 1) + ";"; }
  }
  assert(false, "unbalanced literal extracting " + name);
}

function makeEl() {
  const el = { innerHTML: "", textContent: "", className: "", title: "", attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); }, hasAttribute(k) { return k in this.attrs; },
    removeAttribute(k) { delete this.attrs[k]; } };
  return el;
}

// A fake i18n engine over a swappable locale map: t(), tf() and current() behave like
// src/static/i18n.js (unknown key -> the English), and `ready` resolves on demand.
function makeI18n(lang) {
  const I = { lang, map: lang === "en" ? {} : LOCALE(lang) };
  let markReady;
  I.ready = new Promise((res) => { markReady = res; });
  I.markReady = () => markReady(I.lang);
  I.use = (code) => { I.lang = code; I.map = code === "en" ? {} : LOCALE(code); };
  I.api = {
    t: (s) => (I.map[s] == null ? s : I.map[s]),
    tf: (s, v) => {
      let out = I.map[s] == null ? s : I.map[s];
      if (v) out = out.replace(/\{(\w+)\}/g, (m, k) => (v[k] == null ? m : String(v[k])));
      return out;
    },
    current: () => I.lang,
    get ready() { return I.ready; },
  };
  return I;
}

// ======================= Home at-a-glance strip ========================== //
function makeHomeSandbox(i18n) {
  const src = `
    const window = { OOI18N: this.i18n };
    const OOI18N = this.i18n;
    const els = this.els;
    function $(id) { return els[id] || null; }
    const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
      c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));
    const calls = this.calls;
    // A language switch must never fetch: any api() call is recorded and fails the test.
    async function api(p) { calls.api.push(p); throw new Error("no fetch expected: " + p); }
    function renderHomeWikiFigure(cached) { calls.wiki.push(cached === true); }
    let _homeWikiLane = null;
    let _homeStatsFailed = false;
    ${extractConst("HOME_STAT_LABELS", HOME)}
    ${extractConst("HOME_SOURCE_SPLIT_HOVER", HOME)}
    ${extractConst("HOME_SOURCE_SPLIT_KEYS", HOME)}
    ${extract("homeStatLabel", null, HOME)}
    ${extract("homeSourceSplitHover", null, HOME)}
    ${extract("homeStatEntries", null, HOME)}
    let _homeStatsLast = null;
    let _homeRunningLast = null;
    let _homeGlanceAwaitingI18n = false;
    ${extract("repaintHomeGlance", null, HOME)}
    ${extract("_homeGlanceWhenReady", null, HOME)}
    const _STALE_NOTE_S = 90;
    ${extract("homeStatsAgeNote", null, HOME)}
    ${extract("renderHomeStats", null, HOME)}
    ${extract("renderHomeStatus", null, HOME)}
    this.homeStatEntries = homeStatEntries;
    this.renderHomeStats = renderHomeStats;
    this.renderHomeStatus = renderHomeStatus;
    this.repaintHomeGlance = repaintHomeGlance;
    this.homeStatsAgeNote = homeStatsAgeNote;
    this.setFailed = (v) => { _homeStatsFailed = v; };
    this.isFailed = () => _homeStatsFailed;
    this.setWikiLane = (v) => { _homeWikiLane = v; };
  `;
  const sb = { i18n: i18n.api, els: { "home-stats": makeEl(), "home-status": makeEl() },
    calls: { api: [], wiki: [] } };
  // eslint-disable-next-line no-new-func
  new Function(src).call(sb);
  return sb;
}

// The row-S fixture: four predicates that give four different answers, the split summing.
const COUNTS = { articles: 24, sources: 11, keywords: 648, commodity_prices: 0,
  article_links: 0, mentioned_dates: 10, sources_qualified: 3, sources_pending: 3,
  sources_candidates: 5 };

function items(html) {
  const out = [];
  const re = /<span class="s"([^>]*)><b>([^<]*)<\/b> <span>([^<]*)<\/span><\/span>/g;
  let m;
  while ((m = re.exec(html)) !== null) out.push({ attrs: m[1], n: m[2], label: unesc(m[3]) });
  return out;
}
function unesc(s) {
  return s.replace(/&(amp|lt|gt|quot|#39);/g, (m, e) => ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'" }[e]));
}

async function run() {
  await test("S4: the flat sources figure is REPLACED IN PLACE by its three-way split", () => {
    const sb = makeHomeSandbox(makeI18n("en"));
    const keys = sb.homeStatEntries(COUNTS).map(([k]) => k);
    assert(JSON.stringify(keys) === JSON.stringify(["articles", "sources_qualified", "sources_pending",
      "sources_candidates", "keywords", "commodity_prices", "article_links", "mentioned_dates"]),
      "entries order: " + keys.join(","));
    // A payload without the split keeps its flat figure (nothing silently vanishes).
    const flat = sb.homeStatEntries({ articles: 1, sources: 4 }).map(([k]) => k);
    assert(JSON.stringify(flat) === '["articles","sources"]', "a split-less payload kept: " + flat);
  });

  await test("S4: no bare total beside the split; each part names the total in its hover", () => {
    const sb = makeHomeSandbox(makeI18n("en"));
    sb.renderHomeStats(COUNTS, { counts: COUNTS });
    const its = items(sb.els["home-stats"].innerHTML);
    assert(its.length === 8, "8 strip items, got " + its.length);
    assert(!its.some((x) => x.n === "11"), "the flat total 11 is on the strip as a bare figure");
    const split = its.filter((x) => /title=/.test(x.attrs));
    assert(split.length === 3, "three split items carry a hover, got " + split.length);
    for (const x of split) {
      assert(/of your 11 sources/.test(x.attrs), "hover does not name the total: " + x.attrs);
      assert(/data-i18n-dyn/.test(x.attrs), "a titled split item must own its title: " + x.attrs);
    }
    assert(its[1].n === "3" && its[1].label === "Sources collecting",
      "the headline (enabled AND qualified) leads the source figures: " + JSON.stringify(its[1]));
  });

  await test("H8/P7/U5: every label on the strip is translated in fr, ar and zh", () => {
    for (const code of ["fr", "ar", "zh"]) {
      const sb = makeHomeSandbox(makeI18n(code));
      sb.renderHomeStats(COUNTS, { counts: COUNTS });
      const loc = LOCALE(code);
      for (const x of items(sb.els["home-stats"].innerHTML)) {
        const english = Object.keys(loc).find((k) => loc[k] === x.label);
        assert(english, code + ": label " + JSON.stringify(x.label) + " is not a translation");
        assert(/_/.test(x.label) === false, code + ": a raw key reached the strip: " + x.label);
      }
      assert(!/Sources collecting|sources qualified/i.test(sb.els["home-stats"].innerHTML),
        code + ": an English split label survived");
    }
  });

  await test("U5: a live switch repaints the strip AND the status line from the cache, no fetch", () => {
    const I = makeI18n("en");
    const sb = makeHomeSandbox(I);
    sb.renderHomeStats(COUNTS, { counts: COUNTS });
    sb.renderHomeStatus(false);
    const wikiBefore = sb.calls.wiki.length;
    I.use("fr");
    sb.repaintHomeGlance();
    const fr = LOCALE("fr");
    const html = sb.els["home-stats"].innerHTML;
    assert(html.indexOf(">" + fr["Sources collecting"] + "<") !== -1, "strip not repainted in fr: " + html.slice(0, 200));
    assert(html.indexOf(">" + fr["Keywords"] + "<") !== -1, "keywords label not repainted in fr");
    assert(sb.els["home-status"].innerHTML.indexOf(fr["stopped"]) !== -1, "status line not repainted in fr");
    assert(sb.calls.api.length === 0, "a language switch fetched: " + sb.calls.api.join(","));
    // No Wikipedia figure was cached, so the repaint asks nothing of the lane either.
    assert(sb.calls.wiki.length === wikiBefore, "the repaint re-read the Wikipedia lane");
    sb.setWikiLane({ measured: true, pages: 2, changes_today: 1 });
    sb.repaintHomeGlance();
    assert(sb.calls.wiki[sb.calls.wiki.length - 1] === true, "a cached figure must be re-appended FROM CACHE");
  });

  await test("U5: the repaint never paints stats over the read-failure line", () => {
    const I = makeI18n("en");
    const sb = makeHomeSandbox(I);
    sb.renderHomeStats(COUNTS, { counts: COUNTS });
    sb.setFailed(true);
    sb.els["home-stats"].innerHTML = "FAILURE LINE";
    I.use("ar");
    sb.repaintHomeGlance();
    assert(sb.els["home-stats"].innerHTML === "FAILURE LINE", "stats were painted over the failure line");
    // ...and a later successful read is what the strip shows, so the flag clears with it.
    sb.renderHomeStats(COUNTS, { counts: COUNTS });
    assert(sb.isFailed() === false, "real stats on screen but the failure flag is still set");
  });

  await test("U5: the boot race -- a strip painted before the locale loaded is repainted when ready", async () => {
    const I = makeI18n("en");
    const sb = makeHomeSandbox(I);
    sb.renderHomeStats(COUNTS, { counts: COUNTS });   // painted while the map was still empty
    sb.renderHomeStatus(true);
    I.use("zh");                                      // the locale lands afterwards
    I.markReady();
    await I.ready; await Promise.resolve();
    const zh = LOCALE("zh");
    assert(sb.els["home-stats"].innerHTML.indexOf(zh["Sources collecting"]) !== -1, "not repainted on ready");
    assert(sb.els["home-status"].innerHTML.indexOf(zh["running"]) !== -1, "status not repainted on ready");
    assert(sb.calls.api.length === 0, "the ready repaint fetched");
  });

  await test("U5: the 'as of' stamp uses the APP language, not the browser's", () => {
    const I = makeI18n("fr");
    const sb = makeHomeSandbox(I);
    const as_of = "2026-09-26T20:11:00Z";
    const note = sb.homeStatsAgeNote({ cache_age_s: 120, as_of }, I.api.t);
    const want = new Date(as_of).toLocaleTimeString("fr", { hour: "2-digit", minute: "2-digit" });
    assert(note.indexOf(want) !== -1, "stamp not in fr format: " + note + " (want " + want + ")");
    assert(!/[AP]M/.test(note), "an English AM/PM stamp in fr: " + note);
  });

  // ===================== Library: Database & storage ===================== //
  await test("S6: the Library tiles take Home's labels and relabel from cache on a switch", () => {
    const I = makeI18n("en");
    const tiles = {};
    for (const k of Object.keys(COUNTS)) {
      if (k === "sources") continue;
      const lbl = makeEl();
      const tile = makeEl();
      tile.querySelector = () => lbl;
      Object.defineProperty(tile, "title", {
        get() { return this.attrs.title || ""; }, set(v) { this.attrs.title = String(v); } });
      tile.lbl = lbl;
      tiles["db-t-" + k] = tile;
    }
    const src = `
      const window = { OOI18N: this.i18n };
      const OOI18N = this.i18n;
      const document = { getElementById: (id) => this.tiles[id] || null };
      ${extractConst("HOME_STAT_LABELS", HOME)}
      ${extractConst("HOME_SOURCE_SPLIT_HOVER", HOME)}
      ${extractConst("HOME_SOURCE_SPLIT_KEYS", HOME)}
      ${extract("homeStatLabel", null, HOME)}
      ${extract("homeSourceSplitHover", null, HOME)}
      let _dbStatsLast = null;
      ${extract("_paintDbStatLabels", null, LIB)}
      this.paint = (s) => { if (s) _dbStatsLast = s; _paintDbStatLabels(); };
    `;
    const sb = { i18n: I.api, tiles };
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    sb.paint({ counts: COUNTS });
    assert(tiles["db-t-commodity_prices"].lbl.textContent === "Commodity prices",
      "raw key on a tile: " + tiles["db-t-commodity_prices"].lbl.textContent);
    assert(/of your 11 sources/.test(tiles["db-t-sources_pending"].title), "split tile has no hover");
    assert(!tiles["db-t-articles"].hasAttribute("title"), "a plain tile must carry no split hover");
    I.use("ar");
    sb.paint();                                        // the langchange path: no payload, no fetch
    const ar = LOCALE("ar");
    for (const [id, tile] of Object.entries(tiles)) {
      const txt = tile.lbl.textContent;
      assert(Object.values(ar).indexOf(txt) !== -1, id + " not relabelled in ar: " + txt);
    }
  });

  // ============================ Task manager ============================= //
  await test("O4: applyLang walks the whole document only AFTER setLang has loaded the map", async () => {
    const seen = [];
    const I = { map: {}, setLang(code) {
      return new Promise((res) => setTimeout(() => { I.map = LOCALE(code); res(); }, 5));
    }, apply(root) { seen.push({ root, loaded: Object.keys(I.map).length > 0 }); } };
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      const document = "DOC";
      const localStorage = { getItem: () => "fr" };
      ${extract("applyLang", null, TM)}
      this.applyLang = applyLang;
    `;
    const sb = { I };
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    sb.applyLang();
    await new Promise((r) => setTimeout(r, 30));
    const docPass = seen.filter((s) => s.root === "DOC");
    assert(docPass.length >= 1, "applyLang never walked the whole document");
    assert(seen.every((s) => s.loaded), "a document walk ran against an EMPTY map (the English <title> is cached as the original)");
  });

  await test("T5: a live switch repaints the summary strip, the panels, 'Live' and the health pill from cache", () => {
    const I = makeI18n("ar");
    const els = {};
    const $ = (id) => (els[id] = els[id] || makeEl());
    const calls = { api: [], panels: [] };
    const src = `
      const window = { OOI18N: this.i18n, _act: { online: false, active: false, running: false } };
      var $ = this.$;
      function t(s) { return (window.OOI18N && OOI18N.t) ? OOI18N.t(s) : s; }
      const OOI18N = this.i18n;
      function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
      const calls = this.calls;
      async function api(p) { calls.api.push(p); throw new Error("no fetch expected"); }
      function paintAir() {}
      function renderProcesses() { calls.panels.push("processes"); }
      function renderQueue() { calls.panels.push("queue"); }
      function renderSchedule() { calls.panels.push("schedule"); }
      function renderPerformance() { calls.panels.push("performance"); }
      var _tmOnline = null, _jobs = { jobs: [] };
      var _lastVitals = { process: { cpu_percent: 2, rss_bytes: 1048576 } }, _lastRates = { netRate: 0 };
      var _painted = true, _healthState = "healthy";
      ${extract("fmtBytes", null, TM)}
      ${extract("fmtRate", null, TM)}
      ${extract("fmtNum", null, TM)}
      ${extract("renderSummary", null, TM)}
      ${extract("paintHealth", null, TM)}
      ${extract("repaintFromCache", null, TM)}
      this.renderSummary = renderSummary; this.paintHealth = paintHealth; this.repaint = repaintFromCache;
      this.window = window;
    `;
    const sb = { i18n: I.api, $, calls };
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    sb.renderSummary(null, sb.window._act, null);
    sb.paintHealth();
    $("tm-conn").textContent = I.api.t("Live");
    const ar = LOCALE("ar"), zh = LOCALE("zh");
    assert($("tm-summary").innerHTML.indexOf(ar["Airplane mode"]) !== -1, "summary not painted in ar first");
    I.use("zh");
    sb.repaint();
    const sum = $("tm-summary").innerHTML;
    assert(sum.indexOf(zh["Airplane mode"]) !== -1 && sum.indexOf(zh["Memory"]) !== -1,
      "summary still in the previous language after the switch: " + sum.slice(0, 200));
    assert(sum.indexOf(ar["Memory"]) === -1, "an Arabic metric label survived the switch");
    assert($("health").innerHTML.indexOf(zh["healthy"]) !== -1, "health pill not repainted: " + $("health").innerHTML);
    assert($("tm-conn").textContent === zh["Live"], "'Live' not repainted: " + $("tm-conn").textContent);
    assert(["processes", "queue", "schedule", "performance"].every((p) => calls.panels.includes(p)),
      "a panel was not repainted: " + calls.panels.join(","));
    assert(calls.api.length === 0, "the switch fetched: " + calls.api.join(","));
  });

  console.log("all assertions passed (" + passed + " tests)");
}

run().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
