/**
 * Behavioural node test for batch B16 of the 2026-09-26 delegated click-through: the
 * agenda row's sentences as whole frames (V3), the reader's "Original source:" footer
 * through the locale's separator (V4), the AI hardware chips keyed (V8), the System panel
 * repainted from the samples it holds (V9), a job count that names its unit (V10), a
 * language switch that skips panels never opened and graph views that do not refetch on
 * a repaint (V11), and the reader page's numbers written exactly as the SPA writes them
 * (V16).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name -- a re-typed
 * copy would pass while the real code was still broken (the sibling-test convention;
 * see tests/clickthrough_b14_node_test.js). Translations come from the REAL locale files.
 *
 * Run by tests/test_clickthrough_b16_fixes.py (and standalone:
 * `node tests/clickthrough_b16_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const read = (name) => fs.readFileSync(path.join(STATIC, name), "utf-8");
const CORE = read("app-core.js");
const AGENDA = read("app-agenda.js");
const AI = read("app-ai-tools.js");
const LIB = read("app-library.js");
const CORPUS = read("app-corpus.js");
const MARKETS = read("app-markets.js");
const READER = read("reader.js");
const TM = read("taskmanager.html");
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

const ESC = `const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));`;

// A fake i18n engine over a real locale: t()/tf() behave like src/static/i18n.js (an
// unknown key renders its English). `lang` may be switched live, like OOI18N.setLang.
function i18n(lang) {
  const I = {
    lang,
    map: lang === "en" ? {} : LOCALE(lang),
    set(code) { I.lang = code; I.map = code === "en" ? {} : LOCALE(code); },
    t: (s) => (I.map[s] == null ? s : I.map[s]),
    tf: (s, v) => {
      let out = I.map[s] == null ? s : I.map[s];
      if (v) out = out.replace(/\{(\w+)\}/g, (m, k) => (v[k] == null ? m : String(v[k])));
      return out;
    },
    current: () => I.lang,
  };
  return I;
}

const NNBSP = " ";

async function run() {
  // ============== V16: the reader page writes numbers as the SPA does ============== //
  // toLocaleString() read the BROWSER's locale; the SPA writes every number through
  // fmtNum (Latin digits, a decimal point, U+202F grouping). The reader cannot load the
  // SPA bundle, so it carries a port: the two must agree on every value.
  const spaFmt = new Function(extract("fmtNum", null, MARKETS) + "; return fmtNum;")();
  const reader = new Function(extract("fmtNum", null, READER) + ";" + extract("num", null, READER)
    + "; return {fmtNum: fmtNum, num: num};")();

  await test("V16: the reader's fmtNum agrees with the SPA's over every shape of number", async () => {
    const values = [0, 1, -1, 7, 12, 99.5, 100, 999, 1000, 1234.5, 6402, 12806, -45678.25, 1e6,
      123456789, 0.5, 0.05, 0.001234, 2.5, 10.1, 100.04, 1000.06, 3.14159, NaN, Infinity,
      -Infinity, null, undefined, 1e21];
    for (const v of values) {
      for (const dec of [undefined, 0, 1, 2]) {
        const a = spaFmt(v, dec), b = reader.fmtNum(v, dec);
        assert(a === b, `fmtNum(${v}, ${dec}): SPA ${JSON.stringify(a)} vs reader ${JSON.stringify(b)}`);
      }
    }
  });

  await test("V16: a reader count is grouped by the ruled formatter, never the browser's", async () => {
    assert(reader.num(6402) === "6" + NNBSP + "402", reader.num(6402));
    assert(reader.num(12806) === spaFmt(12806, 0), reader.num(12806));
    assert(reader.num(null) === "0" && reader.num(undefined) === "0", "a missing count reads 0");
  });

  // ============== V3: the agenda row's sentences are whole frames ================= //
  function agRow(lang) {
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      const agConfPill = () => "", agWhen = () => "", ooCountryCell = () => "";
      const extLink = (url, text) => '<a href="' + esc(url) + '">' + esc(text) + "</a>";
      const _agFeedById = () => ({nager: {name: "Nager.Date", url: "https://date.nager.at"}});
      ${extract("agRow", null, AGENDA)}
      this.row = agRow;
    `;
    const sb = {I: i18n(lang)};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb.row;
  }
  const EVT = {
    title: "Bastille Day", category: "civic", country: "FRA", tags: [],
    also_in: ["holidays-fr", "holidays-eu"], imported: true, sources: ["nager"],
    date_variants: ["2026-07-14", "2026-07-15"], official_url: "https://example.org/e",
  };

  await test("V3: French and Chinese write each agenda sentence in their own order", async () => {
    const fr = agRow("fr")(EVT);
    assert(fr.indexOf("aussi dans 2") !== -1, "also-in pill not a frame in fr: " + fr);
    assert(fr.indexOf("de Nager.Date") !== -1, "provenance pill not a frame in fr: " + fr);
    assert(fr.indexOf("la date varie selon la source : 2026-07-14 · 2026-07-15") !== -1, fr);
    assert(fr.indexOf("Cet événement apparaît aussi dans : holidays-fr, holidays-eu") !== -1, fr);
    assert(!/also in|>from |date varies/.test(fr), "English glued onto a French row: " + fr);
    const zh = agRow("zh")(EVT);
    assert(zh.indexOf("另见于 2 处") !== -1, "the Chinese frame puts the count inside: " + zh);
    assert(zh.indexOf("来自 Nager.Date") !== -1, zh);
    const en = agRow("en")(EVT);
    assert(en.indexOf(">also in 2<") !== -1 && en.indexOf(">from Nager.Date<") !== -1, en);
    assert(en.indexOf("official source ↗") !== -1, en);
  });

  // ============== V8: the AI hardware chips ========================================= //
  function hwChips(lang) {
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      ${extract("_sizeText", null, CORE)}
      ${extract("_hwChips", null, AI)}
      this.chips = _hwChips;
    `;
    const sb = {I: i18n(lang)};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb.chips;
  }
  const METHOD = "nvidia-smi probe for a dedicated NVIDIA GPU; platform.system()/machine() plus total system RAM for Apple Silicon unified memory. Read-only, no network.";

  await test("V8: a French hardware card reads French, label, value and hover", async () => {
    const fr = LOCALE("fr");
    const none = hwChips("fr")({available: false}, {total_ram_gb: 16, cpu_cores: 8, method: METHOD});
    assert(none.indexOf(esc_(fr["Cores"])) !== -1 && none.indexOf(">Cores<") === -1, "Cores: " + none);
    assert(none.indexOf(esc_(fr["none detected"])) !== -1, none);
    assert(none.indexOf(esc_(fr["No dedicated GPU was found. vLLM needs one; Ollama runs on the CPU."])) !== -1, none);
    assert(none.indexOf(esc_(fr[METHOD])) !== -1, "the RAM hover is the server's English: " + none);
    const gpu = hwChips("fr")({available: true}, null);
    assert(gpu.indexOf(esc_(fr["detected"])) !== -1, gpu);
    assert(gpu.indexOf(esc_(fr["A dedicated GPU was detected, so vLLM can serve here."])) !== -1, gpu);
  });

  // ============== V9: the System panel repaints from what it holds ================= //
  function vitals(lang) {
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      const tf = this.I.tf;
      ${ESC}
      const els = {"vitals-body": {innerHTML: ""}, "vitals-note": {innerHTML: ""}};
      const $ = (id) => els[id];
      let _vitalsOpen = true, _vitalsPrev = null, _vitalsLast = null;
      let _actData = {active: true, running: true};
      const fmtDateTime = (x) => String(x);
      function _budgetHtml() { return ""; }
      function _sessionHtml() { return ""; }
      ${extract("_sizeText", null, CORE)}
      ${extract("_fmtBytes", null, CORE)}
      ${extract("_rateBytes", null, CORE)}
      ${extract("_fmtDur", null, CORE)}
      ${extract("repaintVitalsFromCache", null, CORE)}
      ${extract("_renderVitals", null, CORE)}
      this.els = els;
      this.render = _renderVitals;
      this.repaint = repaintVitalsFromCache;
      this.poll = (v) => { _renderVitals(v); _vitalsPrev = v; };   // _pollVitals' order
    `;
    const sb = {I: i18n(lang)};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb;
  }

  await test("V9: a switch redraws the panel in the new language, with the same rate", async () => {
    const sb = vitals("fr");
    const s0 = {at: 100, process: {cpu_percent: 3, rss_bytes: 1 << 20}, scraping: {bytes_total: 0, fetches_total: 1}};
    const s1 = {at: 102, process: {cpu_percent: 4, rss_bytes: 1 << 20}, scraping: {bytes_total: 4096, fetches_total: 2}};
    sb.poll(s0);
    sb.poll(s1);
    const fr = LOCALE("fr"), zh = LOCALE("zh");
    const before = sb.els["vitals-body"].innerHTML;
    assert(before.indexOf(esc_(fr["Now collecting"])) !== -1 && before.indexOf(esc_(fr["System"])) !== -1, before);
    assert(before.indexOf(esc_(fr["Collecting…"])) !== -1, "the phase fallback is English: " + before);
    const rate = before.match(/<span>[^<]*<\/span><b>([^<]*\/s)/);
    assert(rate, "no measured rate in the French panel: " + before);
    sb.I.set("zh");
    sb.repaint();
    const after = sb.els["vitals-body"].innerHTML;
    assert(after.indexOf(esc_(zh["Now collecting"])) !== -1 && after.indexOf(esc_(zh["System"])) !== -1,
      "the panel kept the old language: " + after);
    assert(after.indexOf(esc_(fr["Now collecting"])) === -1, after);
    // The repaint uses the SAME pair of samples: re-rendering the last sample against
    // itself would divide by a zero interval and drop the rate the panel showed.
    assert(/\/s/.test(after) && after.indexOf("—") === -1, "the repaint lost the measured rate: " + after);
  });

  await test("V9: a closed panel is never repainted", async () => {
    const sb = vitals("fr");
    sb.repaint();
    assert(sb.els["vitals-body"].innerHTML === "", "a repaint with nothing drawn yet wrote the panel");
  });

  // ============== V10: a count names its unit on the /tasks page ==================== //
  function tmRow(lang) {
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      function t(s) { return OOI18N.t(s); }
      ${ESC}
      var isDl = function (k) { return k === "wiki-dump" || k === "osm-map"; };
      var isLocal = function (k) { return k === "reindex" || k === "keyword-fold" || k === "search-reindex"; };
      var dlKey = function (j) { return j.id; };
      ${extract("fmtBytes", null, TM)}
      ${extract("fmtDur", null, TM)}
      ${extract("jobWhy", null, TM)}
      ${extract("jobRow", null, TM)}
      this.row = jobRow;
    `;
    const sb = {I: i18n(lang)};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb.row;
  }

  await test("V10: the keyword fold's count says what it counts, in the page's language", async () => {
    const fold = {id: "keyword-fold", kind: "keyword-fold", state: "running", actions: ["pause"],
      label: "Folding keyword forms into their base form",
      progress: {done: 12, total: 40, unit: "keywords", percent: 30}};
    const fr = tmRow("fr")(fold);
    assert(fr.indexOf("12 / 40 " + LOCALE("fr")["keywords"]) !== -1, "no unit on the count: " + fr);
    const reidx = {id: "reindex", kind: "reindex", state: "running", actions: [], label: "Re-indexing the corpus",
      progress: {done: 1, total: 4, unit: "stages", percent: 25}};
    const r = tmRow("fr")(reidx);
    assert(r.indexOf("1 / 4 " + LOCALE("fr")["stages"]) !== -1, r);
    assert(r.indexOf(esc_(LOCALE("fr")["Re-indexing the corpus"])) !== -1, "the fixed label is English: " + r);
    const dl = tmRow("fr")({id: "d", kind: "wiki-dump", state: "running", label: "x",
      progress: {done: 1024, total: 2048, unit: "bytes", percent: 50}});
    assert(dl.indexOf("bytes") === -1 && dl.indexOf("octets") === -1, "a byte count names 'bytes' twice: " + dl);
  });

  // ============== V11: panels never opened, and the graph views' cache ============== //
  function repaintGuard(hosts) {
    // A tiny DOM: each host lists its children as {placeholder: bool}.
    const calls = [];
    const document = {
      getElementById(id) {
        const kids = hosts[id];
        if (!kids) return null;
        return {
          children: kids,
          querySelector(sel) {
            assert(sel === ":scope > [data-oo-placeholder]", "unexpected selector " + sel);
            return kids.find((k) => k.placeholder) || null;
          },
        };
      },
    };
    const window = {};
    for (const fn of ["loadHomeTrends", "loadLandscape", "loadFamilies", "loadFamilyCuration",
      "loadTrendWindows", "loadTrends", "loadSuperGroups", "loadBriefing", "exploreTerm",
      "anRenderKwChips", "anMindmapRepaint", "_renderOverviewTrends", "_obsRelabel"]) {
      window[fn] = () => calls.push(fn);
    }
    // eslint-disable-next-line no-new-func
    new Function("window", "document", extract("ooKwRepaintOnLangChange", null, CORPUS)
      + "; ooKwRepaintOnLangChange();")(window, document);
    return calls;
  }

  await test("V11: a switch fetches for no panel still holding its markup placeholder", async () => {
    const calls = repaintGuard({
      "home-trends": [{placeholder: false}],                // drawn: re-runs
      "ins-landscape": [{placeholder: true}],               // never opened
      "fam-list": [{placeholder: true}],
      "famc-list": [{placeholder: true}],
      "trd-windows": [{placeholder: true}],
      "sg-list": [{placeholder: false}, {placeholder: false}],  // opened: re-runs
      "briefing-feed": [{placeholder: false}],
    });
    for (const never of ["loadLandscape", "loadFamilies", "loadFamilyCuration", "loadTrendWindows"]) {
      assert(calls.indexOf(never) === -1, never + " fetched for a panel never opened: " + calls);
    }
    for (const opened of ["loadHomeTrends", "loadSuperGroups", "loadBriefing"]) {
      assert(calls.indexOf(opened) !== -1, opened + " no longer re-runs for the new language: " + calls);
    }
  });

  function libViews() {
    const calls = [];
    const cacheAt = LIB.indexOf("const _LIB_REFRESH_ON_REOPEN");
    assert(cacheAt !== -1, "app-library.js has no per-view payload cache");
    const src = `
      const document = { querySelectorAll: () => [] };
      const api = (url) => { this.fetched.push(url); return Promise.resolve({url: url, n: this.fetched.length}); };
      let _libView = "overview";
      const _libViewLoaded = new Set();
      const _LIB_VIEW_LOADERS = {
        overview: () => this.calls.push("overview"),
        activity: () => this.calls.push("activity"),
        tracked: () => this.calls.push("tracked"),
        storage: () => this.calls.push("storage"),
      };
      ${LIB.slice(cacheAt, LIB.indexOf("const _LIB_VIEW_LOADERS"))}
      ${extract("selectLibraryView", null, LIB)}
      this.select = selectLibraryView;
      this.get = _libGet;
    `;
    const sb = {calls, fetched: []};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb;
  }

  await test("V11: a repaint of an open graph view draws from its payloads, a reopen refetches", async () => {
    const sb = libViews();
    const H = "/api/library/history?metric=articles_per_hour&days=30";
    const W = "/api/library/history?metric=wiki_pages&days=30";
    sb.select("activity");
    await sb.get(H);
    await sb.get(W);
    const again = await sb.get(H);                 // the language-switch repaint
    assert(sb.fetched.length === 2, "a repaint refetched: " + sb.fetched);
    assert(again.n === 1, "the repaint did not draw from the payload the tile was drawn from");
    sb.select("activity");                         // the same view again: not a reopen
    assert(sb.calls.filter((c) => c === "activity").length === 1, "re-selecting the open view reloaded it");
    sb.select("storage");
    sb.select("activity");                         // reopened after another view
    assert(sb.calls.filter((c) => c === "activity").length === 2, "a reopen did not reload: " + sb.calls);
    await sb.get(H);
    assert(sb.fetched.length === 3 && sb.fetched[2] === H, "a reopen showed the first numbers: " + sb.fetched);
    await sb.get(W);
    assert(sb.fetched.length === 3, "reopening Activity dropped the Tracked view's payloads too");
    sb.select("storage");
    sb.select("storage");
    assert(sb.calls.filter((c) => c === "storage").length === 1, "a non-graph view reloads on reopen");
  });

  // ============== V4: the reader footer ============================================ //
  function footer(lang) {
    const kids = [];
    const anchor = {tag: "a", href: "https://example.org/x"};
    const box = {
      querySelector: (sel) => (sel === "a.src-link" ? anchor : null),
      set textContent(v) { kids.length = 0; },
      appendChild(frag) { for (const n of frag.nodes) kids.push(n); },
    };
    const document = {
      querySelector: (sel) => (sel === ".src-orig" ? box : null),
      createDocumentFragment: () => ({nodes: [], appendChild(n) { this.nodes.push(n); }}),
      createTextNode: (s) => ({text: s}),
    };
    const I = i18n(lang);
    const T = I.t, TF = I.tf;
    // eslint-disable-next-line no-new-func
    new Function("document", "T", "TF", extract("paintOrigSource", null, READER) + "; paintOrigSource();")(
      document, T, TF);
    return {kids, anchor};
  }

  await test("V4: the footer label takes the locale's own separator and keeps the server's link", async () => {
    const fr = footer("fr");
    assert(fr.kids.length === 3, "unexpected footer: " + JSON.stringify(fr.kids));
    assert(fr.kids[0].text === "Source originale" && fr.kids[1].text === " : ", JSON.stringify(fr.kids));
    assert(fr.kids[2] === fr.anchor, "the anchor was rebuilt instead of moved");
    const zh = footer("zh");
    assert(zh.kids[0].text === LOCALE("zh")["Original source"] && zh.kids[1].text === "：", JSON.stringify(zh.kids));
    const en = footer("en");
    assert(en.kids[0].text === "Original source" && en.kids[1].text === ": " && en.kids[2] === en.anchor,
      JSON.stringify(en.kids));
  });

  console.log("all assertions passed (" + passed + " tests)");
}

function esc_(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c]));
}

run().catch((e) => { console.error(e); process.exit(1); });
