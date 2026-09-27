/**
 * Behavioural node test for fix batch B29 of the 2026-09-27 delegated re-walk: sources,
 * collection, Living sources and the search palette.
 *
 *   O-2 / S-4  the Collection targets line is keyed, names its "?" bucket, and redraws
 *              in the new language from the payload it holds;
 *   L-8 / L-9  the Sources pager and the World-coverage "thin" tile are keyed frames;
 *   T-1        the collection-speed knob's hover follows a live switch;
 *   P-3 / U-5  both places that write the Wikipedia lane's host list isolate each host;
 *   P-6        the palette's two rows for one page say what each opens, and the tracked
 *              one opens the tracked changes, not Settings;
 *   O-3        a live switch keeps an open stream diff and an open law diff;
 *   O-6        clicking a tracked page while on the Wikipedia panel reloads nothing;
 *   O-5        composed zh lines take the locale's own separator, never "： " or "。 " (the
 *              Storage lines, the failed-download line, and the round-2 sweep of the
 *              batch's files: the newsletter tally and the keyed failure labels).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name -- a re-typed
 * copy would pass while the real code was still broken (the sibling-test convention).
 * Translations come from the REAL locale files.
 *
 * Run by tests/test_rewalk_b29_fixes.py (and standalone:
 * `node tests/rewalk_b29_node_test.js`).
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
const SOURCES = read("app-sources.js");
const MARKETS = read("app-markets.js");
const LIVING = read("app-living.js");
const MAP = read("app-map.js");
const SHELL = read("app-shell.js");
const SETTINGS = read("app-settings.js");
const LIBRARY = read("app-library.js");
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
// The visible text of rendered markup: drop the tags by walking the string (not a
// regex replace, which CodeQL reads as an incomplete sanitizer), then decode the five
// entities esc() writes in ONE pass, so "&amp;lt;" reads "&lt;" and is never decoded twice.
const stripTags = (html) => {
  let out = "", inTag = false;
  for (const ch of String(html)) {
    if (ch === "<") inTag = true;
    else if (ch === ">" && inTag) inTag = false;
    else if (!inTag) out += ch;
  }
  return out;
};
const ENTITY = { lt: "<", gt: ">", amp: "&", quot: "\"", "#39": "'" };
const visible = (html) => stripTags(html).replace(/&(lt|gt|amp|quot|#39);/g, (m, e) => ENTITY[e]);

// A fake i18n engine over a real locale: t()/tf() behave like src/static/i18n.js (an
// unknown key renders its English). `set` switches live, like OOI18N.setLang.
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
// The shipped code reads `window.OOI18N && OOI18N.t`: the bare global too.
const BARE_I18N = "var OOI18N = window.OOI18N;";
const HELPERS = [
  BARE_I18N,
  ESC,
  extract("fmtNum", null, MARKETS),
  extract("ooLabelHtml", null, CORE),
  extract("ooLabelText", null, CORE),
].join("\n");

// A plain element: what the code under test writes, recorded for the assertions.
function el(extra) {
  return Object.assign({ innerHTML: "", textContent: "", title: "", hidden: false,
    attrs: {}, classList: { set: new Set(), toggle(c, on) { if (on) this.set.add(c); else this.set.delete(c); },
      contains(c) { return this.set.has(c); } },
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; } }, extra || {});
}

async function run() {
  // ===================== O-2 / S-4: the Collection targets line ===================== //
  function targets(I, els) {
    const src = [HELPERS,
      "function ooLangCell(v) { return '<span title=\"L:' + esc(v) + '\">' + esc(v) + '</span>'; }",
      "let _schedTargetsLast = null;",
      extract("_renderSchedTargets", null, SOURCES),
      extract("previewTargets", "async function previewTargets(", SOURCES),
      "this.render = _renderSchedTargets; this.preview = previewTargets;",
    ].join("\n");
    const box = { calls: [] };
    new Function("window", "$", "api", "_failMsg", src).call(box, { OOI18N: I },
      (id) => els[id] || null,
      (u) => { box.calls.push(u); return Promise.resolve({ matched: 3, total_enabled: 6, will_process_this_run: 3,
        by_language: { "?": 3 }, by_source_type: { news: 3 } }); },
      (tpl, e) => tpl.replace("{error}", e.message));
    return box;
  }
  await test("O-2/S-4: the targets line is the reader's language, and a switch redraws it from what it holds", async () => {
    const I = i18n("fr");
    const els = { "sched-targets": el() };
    const box = targets(I, els);
    await box.preview();
    const fr = visible(els["sched-targets"].innerHTML);
    assert(!els["sched-targets"].textContent, "the preview failed: " + els["sched-targets"].textContent);
    assert(!/sources targeted|this run will process|by language|by type/i.test(fr), "English left in fr: " + fr);
    assert(fr.includes("3 sources ciblées"), "the pill is not the fr frame: " + fr);
    assert(fr.includes("sur 6 activées"), "the sentence is not the fr frame: " + fr);
    assert(fr.includes("Par langue : Langue inconnue 3"), "the '?' bucket or the fr separator is wrong: " + fr);
    assert(fr.includes("Par type : news 3"), "the type line is not keyed: " + fr);
    assert(!/[: ]\?[: ]/.test(fr), "the '?' bucket printed bare: " + fr);
    assert(/<strong>3<\/strong>/.test(els["sched-targets"].innerHTML), "the figure lost its emphasis");
    I.set("zh");
    box.render();
    const zh = visible(els["sched-targets"].innerHTML);
    assert(zh.includes("目标来源 3 个") && zh.includes("按语言：未知语言 3"), "the switch did not redraw in zh: " + zh);
    assert(box.calls.length === 1, "the language switch fetched again: " + box.calls.length);
    I.set("en");
    box.render();
    const en = visible(els["sched-targets"].innerHTML);
    assert(en.includes("3 sources targeted of 6 enabled · this run will process up to 3"), en);
  });
  await test("O-2/S-4: one source reads singular", async () => {
    const I = i18n("fr");
    const els = { "sched-targets": el() };
    const box = targets(I, els);
    await box.preview();
    // Re-render the held payload with one source, in place of a second fetch.
    const src = [HELPERS, "function ooLangCell(v) { return esc(v); }",
      "let _schedTargetsLast = {matched: 1, total_enabled: 1, will_process_this_run: 1, by_language: {fra: 1}, by_source_type: {}};",
      extract("_renderSchedTargets", null, SOURCES), "_renderSchedTargets();"].join("\n");
    new Function("window", "$", src)({ OOI18N: I }, (id) => els[id] || null);
    const out = visible(els["sched-targets"].innerHTML);
    assert(out.includes("1 source ciblée") && out.includes("Par type : —"), out);
  });

  // ============================== L-8: the Sources pager ============================= //
  await test("L-8: the Sources pager is the keyed frame, in fr, ar and zh", async () => {
    for (const [code, want] of [["fr", "Page 1 sur 129"], ["ar", "صفحة 1 من 129"], ["zh", "第 1 页，共 129 页"]]) {
      const I = i18n(code);
      const els = { "src-table": el(), "src-meta": el(), "src-page": el() };
      const src = [HELPERS,
        "const SRC = {offset: 0, limit: 50, sort: 'name', order: 'asc'};",
        "function srcQuery() { return new URLSearchParams(); }",
        extract("srcTh", null, SOURCES),
        extract("loadManagedSources", "async function loadManagedSources(", SOURCES),
        "this.load = loadManagedSources;"].join("\n");
      const box = {};
      new Function("window", "OOI18N", "$", "api", "toast", "_failMsg", src).call(box, { OOI18N: I }, I,
        (id) => els[id] || null, () => Promise.resolve({ total: 6418, sources: [] }),
        (m) => { throw new Error("toast: " + m); }, (x) => x);
      await box.load();
      assert(els["src-page"].textContent === want, code + ": " + els["src-page"].textContent);
    }
  });

  // ======================= L-9: the World-coverage "thin" tile ======================= //
  await test("L-9: the thin tile is a keyed frame, never 'thin (<3)' in another language", async () => {
    for (const [code, want] of [["fr", "peu couverts (<3)"], ["zh", "覆盖薄弱（<3）"], ["ar", "تغطية ضعيفة (<3)"]]) {
      const I = i18n(code);
      const els = { "coverage-summary": el() };
      const src = [HELPERS,
        "let _covStamp = ''; let COV_COUNTRIES = []; let COV_MISSING = [];",
        "function renderCoverageMap() {} function renderCoverageRegions() {} function renderCoverageTable() {}",
        extract("_covUiLang", null, SOURCES),
        extract("loadCoverage", "async function loadCoverage(", SOURCES),
        "this.load = loadCoverage;"].join("\n");
      const box = {};
      new Function("window", "$", "api", "_failMsg", src).call(box, { OOI18N: I }, (id) => els[id] || null,
        (u) => Promise.resolve(u.includes("coverage")
          ? { covered: 206, total_countries: 249, coverage_pct: 82.7, missing_count: 43, thin: [1, 2], thin_threshold: 3 }
          : { countries: [], missing: [] }),
        (x) => x);
      await box.load();
      const tiles = visible(els["coverage-summary"].innerHTML);
      assert(tiles.includes(want) && !tiles.includes("thin ("), code + ": " + tiles);
    }
  });

  // ==================== T-1: the collection-speed knob follows a switch ================== //
  await test("T-1: a knob painted in fr repaints in ar from the mode it holds", async () => {
    const I = i18n("fr");
    const btn = el();
    const needle = el();
    const src = [BARE_I18N,
      "let _rateMode = null;",
      extract("_paintRateMode", null, SOURCES),
      "this.paint = _paintRateMode; this.mode = () => _rateMode;"].join("\n");
    const box = {};
    new Function("window", "$", "document", src).call(box, { OOI18N: I }, (id) => (id === "rate-toggle" ? btn : null),
      { getElementById: () => needle });
    box.paint("maximum");
    assert(btn.title.startsWith("Vitesse de collecte"), "fr paint: " + btn.title);
    I.set("ar");
    // What app-boot.js's oo:langchange listener runs, from the state the knob holds.
    box.paint(box.mode());
    assert(btn.title === LOCALE("ar")["Collection speed: Maximum — uses your connection fully (politeness per host unchanged). Click for the considerate 500 KiB/s target."],
      "the hover kept its old language: " + btn.title);
  });

  // ============== P-3 / U-5: both host lists isolate each host left to right ============= //
  await test("P-3/U-5: the wizard and the consent bubble both wrap every host in LRI … PDI", async () => {
    const hosts = ["*.wikipedia.org", "stream.wikimedia.org", "dumps.wikimedia.org"];
    const lanes = [{ id: "wikipedia", hosts }];
    const hostEl = el();
    const wiz = new Function("window", "$", "OO_NET_LANES",
      extract("_wizPaintHosts", null, SOURCES) + "\n_wizPaintHosts();")({}, (id) => (id === "wiki-wizard-hosts" ? hostEl : null), lanes);
    void wiz;
    const bubble = new Function("window", "_laneTransport",
      extract("_laneHostTitle", null, CORE) + "\nreturn _laneHostTitle;")({}, () => "")({ hosts }, "direct");
    for (const [where, text] of [["wizard", hostEl.textContent], ["consent bubble", bubble]]) {
      for (const h of hosts) {
        assert(text.includes("\u2066" + h + "\u2069"), where + " does not isolate " + h + ": " + JSON.stringify(text));
      }
    }
  });

  // =============== P-6: the palette's two rows for one page say what each opens =========== //
  await test("P-6: one watched page with a local copy gives two rows that say what they open", async () => {
    const I = i18n("fr");
    const calls = [];
    const src = [
      "let _omniLive = OO_LIVE;",
      "function _omniTypedRows(g) { return (g.items || []).length; }",
      "function _omniCrossNote() { return ''; }",
      extract("_omniItems", null, SHELL),
      "return _omniItems;"].join("\n");
    const live = { q: "coastal", groups: [{ kind: "wiki", total: 2, items: [
      { article_id: 448, title: "Coastal Infrastructure Act", wiki: "en", url: "/api/articles/448/view" },
      { page_id: 1, title: "Coastal Infrastructure Act", wiki: "en" }] }] };
    const items = new Function("window", "OOI18N", "OO_LIVE", "showTab", "openWikiTC", src)(
      { OOI18N: I, open: (u) => calls.push(["open", u]) }, I, live,
      (n) => calls.push(["showTab", n]), (id, title, wiki) => calls.push(["openWikiTC", id, title, wiki]))("coastal");
    assert(items.length === 2, "rows: " + items.length);
    assert(items[0].sub !== items[1].sub, "two rows with the same label and sub: " + items[0].sub);
    assert(items[0].sub === "en · Copie locale" && items[1].sub === "en · Modifications suivies",
      "subs: " + items[0].sub + " / " + items[1].sub);
    items[1].run();
    assert(calls.length === 1 && calls[0][0] === "openWikiTC" && calls[0][1] === 1,
      "the tracked row did not open the tracked changes: " + JSON.stringify(calls));
  });

  // ============ O-3: a live switch keeps the open stream diff and the open law fold ======== //
  // A DOM just large enough for the Living panels: writing innerHTML re-creates every
  // element the markup names, so a rebuilt list really does drop what was open on the old.
  function livingDom() {
    const byId = {};
    const node = (id) => {
      const n = el({ id, children: [] });
      let html = "";
      Object.defineProperty(n, "innerHTML", {
        get() { return html; },
        set(v) {
          html = String(v);
          n.children = [];
          const re = /<(div|button|details)\b([^>]*)>/g;
          let m;
          while ((m = re.exec(html)) !== null) {
            const attrs = {};
            m[2].replace(/([\w-]+)="([^"]*)"/g, (_x, k, val) => { attrs[k] = val; return ""; });
            if (m[1] === "div" && attrs.id) {
              const child = node(attrs.id); byId[attrs.id] = child; n.children.push(child);
            } else if (m[1] === "button" && attrs["data-diff-rev"]) {
              n.children.push(el({ tag: "button", attrs, textContent: visible(html.slice(m.index).split("</button>")[0]) }));
            } else if (m[1] === "details") {
              n.children.push(el({ tag: "details", attrs, open: false }));
            }
          }
        },
      });
      n.querySelectorAll = (sel) => {
        if (sel === '[id^="living-diff-"]') return n.children.filter((c) => /^living-diff-/.test(c.id || ""));
        if (sel === "details[data-change-id][open]") return n.children.filter((c) => c.tag === "details" && c.open);
        if (sel === "details[data-change-id]") return n.children.filter((c) => c.tag === "details");
        throw new Error("selector not shimmed: " + sel);
      };
      n.querySelector = (sel) => {
        const m = /^button\[data-diff-rev="(\d+)"\]$/.exec(sel);
        if (!m) throw new Error("selector not shimmed: " + sel);
        return n.children.find((c) => c.tag === "button" && c.attrs["data-diff-rev"] === m[1]) || null;
      };
      return n;
    };
    for (const id of ["living-stream", "living-stream-more", "living-stream-cap", "living-law-changes",
                      "living-pages", "living-osm-regions", "living-status"]) byId[id] = node(id);
    return byId;
  }
  await test("O-3: a switch redraws Living sources in the new language, keeps both open diffs, fetches nothing", async () => {
    const I = i18n("en");
    const dom = livingDom();
    const calls = [];
    const payloads = {
      "/api/wiki/lane/changes?limit=50&offset=0": { measured: true, count: 1, total: 1, changes: [
        { revision_id: 42, recorded_at: "2026-09-20T12:00:00", title: "Walk Rome", change_kind: "edit",
          text_stored: true, diff_method: "unified", diff_added: 38, diff_removed: 0, byte_delta: 38 }] },
      "/api/wiki/lane/revisions/42": { diff_text: "+a new line", truncated: false },
      "/api/law/changes?limit=50": { caveat: "", changes: [
        { id: 7, document_id: 3, jurisdiction: "fr", title: "Code civil", observed_at: "2026-09-20T12:00:00",
          delta_bytes: 12, flag_reasons: [], diff: "+x" }] },
    };
    const src = [HELPERS,
      extract("_ltrIsolate", null, LIBRARY).replace(/_LTR_ISOLATE\[0\]/, "'\\u2068'").replace(/_LTR_ISOLATE\[1\]/, "'\\u2069'"),
      "function ooCountryCell(v) { return esc(v); } function ooLangCell(v) { return esc(v); }",
      "let _livingSubtabs = null; let _livingView = 'wiki'; let _livingOverview = null; let _livingStreamOffset = 0;",
      "const _LIVING_KINDS = ['wiki', 'law', 'osm']; const _LIVING_STREAM_PAGE = 50;",
      "const _LIVING_CHANGE_KINDS = { edit: 'edit', create: 'create', delete: 'deletion', move: 'move' };",
      ...["livingWhen", "livingSigned", "livingDiffHtml", "livingDiffBoxHtml", "livingStreamRowsHtml", "livingLawRowsHtml",
        "livingMapRowsHtml", "_livingT", "_livingTf", "_livingFailHtml", "renderLivingOverview", "renderLivingStream",
        "_livingStreamCap", "renderLivingPages", "renderLivingLaw", "renderLivingMaps", "repaintLivingFromCache"]
        .map((n) => extract(n, null, LIVING)),
      "let _livingStreamLast = null, _livingPagesLast = null, _livingLawLast = null, _livingMapsLast = null;",
      "const _livingDiffs = new Map();",
      extract("loadLivingStream", "async function loadLivingStream(", LIVING),
      extract("livingShowDiff", "async function livingShowDiff(", LIVING),
      extract("loadLivingLaw", "async function loadLivingLaw(", LIVING),
      "this.stream = loadLivingStream; this.diff = livingShowDiff; this.law = loadLivingLaw;",
      "this.repaint = repaintLivingFromCache;"].join("\n");
    const box = {};
    new Function("window", "$", "api", "humanBytes", "_jobWhy", src).call(box, { OOI18N: I }, (id) => dom[id] || null,
      (u) => { calls.push(u); return Promise.resolve(payloads[u]); }, (n) => String(n), () => "");
    await box.stream();
    await box.law();
    const btn = dom["living-stream"].querySelector('button[data-diff-rev="42"]');
    await box.diff(42, btn);
    assert(dom["living-diff-42"].innerHTML.includes("a new line"), "the diff did not open");
    dom["living-law-changes"].querySelectorAll("details[data-change-id]")[0].open = true;
    const fetched = calls.length;
    I.set("fr");
    box.repaint();
    assert(calls.length === fetched, "the switch fetched: " + calls.slice(fetched).join(", "));
    assert(dom["living-diff-42"].innerHTML.includes("a new line"), "the switch collapsed the open stream diff");
    const btn2 = dom["living-stream"].querySelector('button[data-diff-rev="42"]');
    assert(btn2 && btn2.textContent === LOCALE("fr")["Hide diff"], "the diff button did not say Hide diff in fr: " + (btn2 && btn2.textContent));
    assert(visible(dom["living-stream"].innerHTML).includes(LOCALE("fr")["Lines added: {added}, removed: {removed}"]
      .replace("{added}", "38").replace("{removed}", "0")), "the stream rows did not redraw in fr");
    const folds = dom["living-law-changes"].querySelectorAll("details[data-change-id]");
    assert(folds.length === 1 && folds[0].open === true, "the switch closed the open law diff");
    assert(visible(dom["living-law-changes"].innerHTML).includes(LOCALE("fr")["Stored diff"]), "the law list is not in fr");
  });

  // =========== O-6: a tracked-page click on the Wikipedia panel reloads nothing ============ //
  await test("O-6: a tracked page opened from the Wikipedia panel does not reload the panel", async () => {
    function open(view, active) {
      const calls = [];
      const tab = el(); if (active) tab.classList.set.add("active");
      const els = { "tab-living": tab, "wiki-tc-title": el(), "wiki-tc-flagged": el(), "wiki-tc": el() };
      const src = [
        "let _wikiTc = { id: null, title: '', wiki: '' };",
        "let _livingView = OO_VIEW;",
        "const _livingSubtabs = { select: (k) => OO_CALLS.push('select:' + k) };",
        extract("openWikiTC", null, MAP),
        "return openWikiTC;"].join("\n");
      new Function("$", "showTab", "loadWikiTC", "OO_VIEW", "OO_CALLS", src)(
        (id) => els[id] || null, (n) => calls.push("showTab:" + n), () => calls.push("loadWikiTC"), view, calls)(
        5, "Walk Tracked Page", "en");
      return { calls, title: els["wiki-tc-title"].textContent };
    }
    const here = open("wiki", true);
    assert(JSON.stringify(here.calls) === JSON.stringify(["loadWikiTC"]),
      "a click on the panel it is already on reloaded it: " + JSON.stringify(here.calls));
    assert(here.title === "en · Walk Tracked Page", here.title);
    const fromLaw = open("law", true);
    assert(fromLaw.calls.includes("select:wiki") && fromLaw.calls.includes("loadWikiTC"),
      "from the Law panel it must switch: " + JSON.stringify(fromLaw.calls));
    const fromElsewhere = open("wiki", false);
    assert(fromElsewhere.calls.includes("showTab:living") && fromElsewhere.calls.includes("select:wiki"),
      "from another tab it must open the tab: " + JSON.stringify(fromElsewhere.calls));
  });

  // ============ O-5: composed zh lines take the locale's own separator ================= //
  await test("O-5: the failed-download line, the storage reading and the budget warning in zh", async () => {
    const I = i18n("zh");
    const core = new Function("window", BARE_I18N + ESC + "\n" + extract("ooLabelText", null, CORE) + "\n" +
      "const _isDownloadKind = (k) => k === 'osm-map' || k === 'wiki-dump';\n" +
      extract("_jobWhy", null, CORE) + "\nreturn _jobWhy;")({ OOI18N: I });
    const why = visible(core({ kind: "osm-map", state: "failed", error: "HTTP 503 from the mirror" }, I.t));
    assert(why === "失败：HTTP 503 from the mirror", "the failure line: " + JSON.stringify(why));
    const set = new Function("window", "humanBytes", HELPERS + "\n" +
      extract("_storageReadingHtml", null, SETTINGS) + "\n" + extract("_storageDiskHtml", null, SETTINGS) +
      "\nreturn [_storageReadingHtml, _storageDiskHtml];")({ OOI18N: I }, (b) => (b / 1e9).toFixed(1) + " GB");
    const reading = visible(set[0]({ reading: { when: "boot", cores: 4, ram_bytes: 8e9, disk_free_bytes: 15e9 } }));
    assert(reading.startsWith("本机（启动时读取）：4 个"), "the reading's lead: " + JSON.stringify(reading.slice(0, 30)));
    const disk = visible(set[1]({ disk: { free_bytes: 15e9, total_bytes: 64e9 }, claimable_bytes: 20e9, budgets_fit: false }));
    assert(!/[：。] /.test(disk), "a Latin space after full-width punctuation: " + JSON.stringify(disk));
    assert(disk.includes("可用。这超过了"), disk);
    I.set("en");
    const en = visible(set[1]({ disk: { free_bytes: 15e9, total_bytes: 64e9 }, claimable_bytes: 20e9, budgets_fit: false }));
    assert(en.includes("free. That is more than the drive has free."), en);
  });

  // The reviewer's round-2 finding: the same welds sat elsewhere in the batch's own files.
  await test("O-5: the newsletter anonymisation tally and a failed-download label in zh", async () => {
    const I = i18n("zh");
    const F = new Function("window", HELPERS + "\n" + extract("_nlAnonLine", null, SETTINGS) +
      "\nreturn { _nlAnonLine, ooLabelText };")({ OOI18N: I });
    const line = F._nlAnonLine({ recipient_redactions: 3, tracker_params_stripped: 1200, trackers_flagged: 0 });
    assert(!/[\u3002\uff1a\uff0c] /.test(line), "a Latin space after full-width punctuation: " + JSON.stringify(line));
    assert(line === "匿名化：3 处收件人痕迹已隐去，1\u202f200 个跟踪令牌已剥离，0 个跟踪包装已标记。", JSON.stringify(line));
    const dl = F.ooLabelText(I.t("Download failed"), "HTTP 503");
    assert(dl === "下载失败：HTTP 503", JSON.stringify(dl));
    I.set("fr");
    assert(F.ooLabelText(I.t("Download failed"), "HTTP 503") === "Échec du téléchargement : HTTP 503", "fr keeps its own spaced colon");
    I.set("en");
    assert(F._nlAnonLine({ recipient_redactions: 3, tracker_params_stripped: 1, trackers_flagged: 0 }) ===
      "Anonymisation: 3 recipient echoes redacted, 1 tracker tokens stripped, 0 tracker wrappers flagged.", "the English line changed");
  });

  console.log(`all assertions passed (${passed} tests)`);
}

run().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
