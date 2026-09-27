/**
 * Behavioural node test for batch B17 of the 2026-09-26 delegated click-through (the
 * tail): a Library tile keeps the window it was switched to (T1), one language switch
 * fetches the Trends windows once (T2), a user calendar is named by its name (T3), the
 * Bulletin's counts are one frame chosen by the count (T4), /tasks writes its counts and
 * percents as the app does (T5), the estimate's method sentence is a keyed frame (T6), a
 * duration's unit is keyed on both task managers (T7), the AI store's sizes go through
 * the one size writer (T8), the reader's density line and mindmap remainder are whole
 * frames (T9), the top-bar chip's "Collecting x/y…" reaches the screen, keyed (T10), and
 * a job label carrying a value is written from its frame on both task managers (T11).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name -- a re-typed
 * copy would pass while the real code was still broken (the sibling-test convention).
 * Translations come from the REAL locale files.
 *
 * Run by tests/test_clickthrough_b17_fixes.py (and standalone:
 * `node tests/clickthrough_b17_node_test.js`).
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
const MAP = read("app-map.js");
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
// One `const NAME = ...;` line, read from the source.
function constLine(src, name) {
  const m = src.match(new RegExp("\\n\\s*const " + name + " = [^\\n]+"));
  assert(m, "could not read " + name);
  return m[0].trim();
}

const ESC = `const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));`;
const esc_ = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c]));
const NNBSP = " ";
const bare = (s) => String(s).replace(/[⁨⁩]/g, "").replace(/ /g, " ");

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
const FMTNUM = extract("fmtNum", null, MARKETS);
const spaFmt = new Function(FMTNUM + "; return fmtNum;")();

async function run() {
  // ============== T1: a Library tile keeps the window it was switched to ============ //
  function langTile() {
    const calls = [];
    const src = [
      constLine(LIB, "LIB_WINDOWS"), constLine(LIB, "LIB_DEFAULT_DAYS"), constLine(LIB, "LIB_LANG_TOP_N"),
      "let _libTileDays = {};",
      "const _libFetched = new Map();",
      extract("_libGet", null, LIB), extract("_libWindowChips", null, LIB), extract("_libLangNotes", null, LIB),
      extract("_libLanguageTile", "async function _libLanguageTile(", LIB),
      extract("_libSetWindow", "async function _libSetWindow(", LIB),
      "this.tile = _libLanguageTile; this.setWindow = _libSetWindow; this.DEF = LIB_DEFAULT_DAYS;",
    ].join("\n");
    const I = i18n("en");
    const box = {calls};
    const el = {replaceWith(n) { box.replaced = n; }};
    const document = {createElement: () => ({set innerHTML(v) { this.firstElementChild = {html: v}; }})};
    // eslint-disable-next-line no-new-func
    new Function("esc", "api", "smallMultiplesSvg", "ooLangName", "window", "OOI18N", "$", "document",
      "_libRenderQualChart", src).call(box,
      (s) => String(s),
      (u) => { calls.push(u); return Promise.resolve({bucket: "day", series: [
        {language: "en", total: 9, points: [{t: "2027-01-01", n: 9}]}]}); },
      () => "<svg></svg>", (c) => c, {OOI18N: I}, I,
      (id) => (id === "lib-tile-__lang" ? el : null), document, () => {});
    return box;
  }
  const onChip = (html, days) => new RegExp('class="chip tiny on" onclick="_libSetWindow\\(\'__lang\', ' + days + '\\)"').test(html);

  await test("T1: a tile switched to 7d stays 7d when the view redraws it (a switch, a reopen)", async () => {
    const box = langTile();
    const first = await box.tile(box.DEF);
    assert(onChip(first, 30), "the tile does not open on its default window: " + first);
    await box.setWindow("__lang", 7);
    assert(/days=7&/.test(box.calls[box.calls.length - 1]), "the chip did not fetch its window: " + box.calls);
    // What the Activity view does on a language switch and on a reopen: redraw every
    // tile, each passing LIB_DEFAULT_DAYS.
    const again = await box.tile(box.DEF);
    assert(onChip(again, 7) && !onChip(again, 30), "the redraw snapped the tile back to 30d: " + again);
    assert(box.calls.every((u) => !/days=30&/.test(u) || u === box.calls[0]),
      "the redraw fetched the default window again: " + box.calls);
  });

  // ============== T2: one switch fetches the Trends windows once ==================== //
  function repaintGuard(hosts) {
    const calls = [];
    const document = {
      getElementById(id) {
        const kids = hosts[id];
        if (!kids) return null;
        return {children: kids, querySelector: () => kids.find((k) => k.placeholder) || null};
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

  await test("T2: with the Trends tab drawn, a switch runs loadTrends once and not the windows beside it", async () => {
    // loadTrends ends by re-running loadTrendWindows (app-corpus.js) -- the real chain.
    assert(/loadTrendWindows\(\);\s*\}\s*$/.test(extract("loadTrends", "async function loadTrends(", CORPUS)),
      "loadTrends no longer re-runs the windows itself; the skip below would lose them");
    const calls = repaintGuard({"trd-top": [{placeholder: false}], "trd-windows": [{placeholder: false}]});
    assert(calls.filter((c) => c === "loadTrends").length === 1, "loadTrends: " + calls);
    assert(calls.indexOf("loadTrendWindows") === -1,
      "the windows were fetched a second time by the same switch: " + calls);
  });

  await test("T2: ...and the windows still re-run on their own when the bar charts never drew", async () => {
    const calls = repaintGuard({"trd-top": [{placeholder: true}], "trd-windows": [{placeholder: false}]});
    assert(calls.indexOf("loadTrends") === -1 && calls.filter((c) => c === "loadTrendWindows").length === 1,
      "the drawn windows were left in the old language: " + calls);
  });

  // ============== T3: a user calendar is named, never its internal key ============== //
  function agRow(lang, feeds) {
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      const agConfPill = () => "", agWhen = () => "", ooCountryCell = () => "";
      const extLink = (url, text) => '<a href="' + esc(url) + '">' + esc(text) + "</a>";
      const _agFeedById = () => (${JSON.stringify(feeds)});
      ${extract("agRow", null, AGENDA)}
      ${extract("mapImportedToAgenda", null, AGENDA)}
      this.row = agRow; this.map = mapImportedToAgenda;
    `;
    const sb = {I: i18n(lang)};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb;
  }
  // The /api/events/imported row of an .ics the user uploaded (src/events/feeds.py
  // collapse_imported): its only "source" is the family key.
  const USER_EVT = {title: "Harbour festival", date: "2026-10-05", kind: "other", sources: ["user-harbour-a"],
    families: ["user-harbour-a"], family_names: ["Harbour A"], family: "user-harbour-a",
    family_name: "Harbour A", source_count: 1, family_count: 1};

  await test("T3: a user calendar's event reads 'from <its name>', in every language", async () => {
    for (const lang of ["en", "fr", "zh"]) {
      const sb = agRow(lang, {nager: {name: "Nager.Date", url: "https://date.nager.at"}});
      const html = sb.row(sb.map(USER_EVT));
      const pill = (html.match(/<span class="pill" title="([^"]*)">([^<]*)<\/span>/) || [])[0] || "";
      assert(pill, lang + ": no provenance pill: " + html);
      assert(pill.indexOf("Harbour A") !== -1 && pill.indexOf("user-harbour-a") === -1,
        lang + ": the pill shows the calendar's internal key: " + pill);
    }
    // A directory feed keeps its directory name and URL.
    const sb = agRow("en", {nager: {name: "Nager.Date", url: "https://date.nager.at"}});
    const dir = sb.row(sb.map({title: "x", date: "2026-07-14", kind: "holidays", sources: ["nager"],
      families: ["holidays-fr"], family_names: ["France holidays"], family: "holidays-fr", family_name: "France holidays"}));
    assert(dir.indexOf("from Nager.Date") !== -1 && dir.indexOf("Nager.Date — https://date.nager.at") !== -1, dir);
  });

  // ============== T4: the Bulletin's counts, one frame chosen by the count ============ //
  function bulletin(lang) {
    const line = (s) => { const at = AGENDA.indexOf(s); assert(at !== -1, s); return AGENDA.slice(at, AGENDA.indexOf("\n", at)); };
    const code = [
      "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
      "const _els = {}; function $(id){ return _els[id] || (_els[id] = {id, textContent: '', innerHTML: '', hidden: false, children: [], style: {}}); }",
      "var window = {OOI18N: this.I}; var OOI18N = this.I;",
      FMTNUM,
      line("let _bulExcludeSections"), line("let _bulExcludeStories"), line("let _bulFile"),
      line("let _bulGate"), line("const _bulMsgs"),
      "const _BUL_CADENCE_LABEL = {};",
      ...["_bulT", "_bulTf", "_bulPaintMsg", "_bulUnit", "_bulRender"].map((n) => extract(n, null, AGENDA)),
      "this.render = _bulRender; this.$ = $;",
    ].join("\n");
    const sb = {I: i18n(lang)};
    // eslint-disable-next-line no-new-func
    new Function(code).call(sb);
    return sb;
  }
  const story = (arts, srcs) => ({key: "s1", shared_terms: ["vote"], articles: arts, distinct_sources: srcs,
    single_source: srcs === 1, narrated: false, fallback_reason: "x", sentences: []});
  const reviewText = (lang, arts, srcs) => {
    const sb = bulletin(lang);
    sb.render({state: "draft", caveat: "", method: "", sections: [], stories: [story(arts, srcs)]});
    return sb.$("bulletin-review").innerHTML;
  };

  await test("T4: one source reads '1 source', one article '1 article', and a count is grouped", async () => {
    const en = reviewText("en", 4, 1);
    assert(en.indexOf("4 articles · 1 source · one source only") !== -1, "en: " + en);
    assert(en.indexOf("1 sources") === -1, en);
    assert(reviewText("en", 1, 3).indexOf("1 article · 3 sources") !== -1, reviewText("en", 1, 3));
    assert(reviewText("en", 12806, 2).indexOf("12" + NNBSP + "806 articles") !== -1, "an ungrouped count");
  });

  await test("T4: Russian and Arabic write a 'many' count as a label, right for every number", async () => {
    const ru = LOCALE("ru"), ar = LOCALE("ar");
    const r = reviewText("ru", 4, 1);
    assert(r.indexOf(esc_(ru["{n} articles"].replace("{n}", "4"))) !== -1 && ru["{n} articles"] === "статей: {n}", r);
    assert(r.indexOf(esc_(ru["{n} source"].replace("{n}", "1"))) !== -1, r);
    const a = reviewText("ar", 4, 3);
    assert(a.indexOf(esc_(ar["{n} sources"].replace("{n}", "3"))) !== -1 && /: \{n\}$/.test(ar["{n} sources"]), a);
  });

  // ============== T5 / T7 / T11: the /tasks page ===================================== //
  function tm(lang) {
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      function t(s) { return OOI18N.t(s); }
      ${ESC}
      var isDl = function (k) { return k === "wiki-dump" || k === "osm-map"; };
      var isLocal = function (k) { return k === "reindex" || k === "keyword-fold" || k === "search-reindex"; };
      var dlKey = function (j) { return j.id; };
      ${extract("fmtBytes", null, TM)}
      ${extract("tf", null, TM)}
      ${extract("fmtNum", null, TM)}
      ${extract("fmtDur", null, TM)}
      var _langDN = {};
      ${extract("langName", null, TM)}
      ${extract("jobPct", null, TM)}
      ${extract("jobLabel", null, TM)}
      ${extract("jobWhy", null, TM)}
      ${extract("jobRow", null, TM)}
      this.row = (j) => jobRow(j, {}); this.fmtNum = fmtNum; this.fmtDur = fmtDur; this.label = jobLabel;
      this.pct = jobPct;
    `;
    const sb = {I: i18n(lang)};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb;
  }
  const FOLD = (done, total, percent) => ({id: "keyword-fold", kind: "keyword-fold", state: "running",
    actions: ["pause"], label: "Folding keyword forms into their base form",
    progress: {done, total, unit: "keywords", percent}});

  await test("T5: /tasks' fmtNum is the SPA's, over every shape of number", async () => {
    const page = tm("en");
    const values = [0, 1, -1, 7, 99.5, 100, 999, 1000, 1234.5, 6402, 12806, -45678.25, 1e6, 123456789,
      0.5, 0.05, 0.001234, 2.5, 3.14159, NaN, Infinity, null, undefined, 1e21];
    for (const v of values) {
      for (const dec of [undefined, 0, 1, 2]) {
        assert(spaFmt(v, dec) === page.fmtNum(v, dec), `fmtNum(${v}, ${dec}): ${spaFmt(v, dec)} vs ${page.fmtNum(v, dec)}`);
      }
    }
  });

  await test("T5: a job's counts are grouped and its percent is whole, never 100 while work is left", async () => {
    const page = tm("fr");
    const row = page.row(FOLD(1956, 12806, 15.27));
    assert(row.indexOf("1" + NNBSP + "956 / 12" + NNBSP + "806 " + LOCALE("fr")["keywords"]) !== -1, "raw counts: " + row);
    assert(row.indexOf("· 15%") !== -1 && row.indexOf("15.27") === -1 && row.indexOf("15.3") === -1, "a float percent: " + row);
    assert(page.pct({done: 12805, total: 12806, percent: 99.99}) === 99, "a running job read 100%");
    assert(page.pct({done: 12806, total: 12806, percent: 100}) === 100, "a finished job");
    assert(page.pct({done: 3, total: 4}) === 75, "a job that publishes no percent");
    // The in-app window draws the same percent.
    const app = new Function(extract("_jobPct", null, CORE) + "; return _jobPct;")();
    for (const p of [{done: 1956, total: 12806, percent: 15.27}, {done: 12805, total: 12806, percent: 99.99},
      {done: 12806, total: 12806}, {done: 3, total: 4}, {done: 0, total: 10, percent: 0.4}]) {
      assert(app(p) === page.pct(p), "the two task managers disagree on " + JSON.stringify(p));
    }
  });

  // The in-app _jobRow, with the real size writer and number formatter.
  function appRow(lang) {
    const I = i18n(lang);
    const stmt = (head) => { const at = CORE.indexOf(head); assert(at !== -1, head); return CORE.slice(at, CORE.indexOf(";", at) + 1); };
    const src = [ESC, FMTNUM, extract("_sizeText", null, CORE), extract("_fmtBytes", null, CORE),
      "function _rateNote(){return '';}", stmt("const _isDownloadKind"), stmt("const _LOCAL_JOB_KINDS"), stmt("const _dlKey"),
      extract("_jobWhy", null, CORE), extract("_jobPct", null, CORE), extract("_jobLabel", null, CORE),
      extract("_jobRow", null, CORE), "return _jobRow;"].join("\n");
    // eslint-disable-next-line no-new-func
    const fn = new Function("window", "OOI18N", src)({OOI18N: I}, I);
    return (j) => fn(j, {}, I.t);
  }
  const PULLB = {id: "model-pull:m", kind: "model-pull", state: "running", label: "Downloading model m",
    progress: {done: 1288490188, total: 4831838208, unit: "bytes", percent: 26.7}, actions: ["cancel"]};
  const TASKN = {id: "task:9", kind: "llm", state: "running", label: "Summarizing 12 article(s)",
    progress: {done: 3, total: 12, unit: "items", percent: 25}, actions: []};   // src/api/jobs.py _task_jobs

  await test("T5: bytes read as sizes and a task's count as a count, on both task managers", async () => {
    for (const [name, row] of [["/tasks", (j) => tm("en").row(j)], ["in-app", appRow("en")]]) {
      const pull = bare(row(PULLB));
      assert(pull.indexOf("1.2 GB / 4.5 GB") !== -1, name + ": a model pull's bytes are not sizes: " + pull);
      const task = bare(row(TASKN));
      assert(task.indexOf("3 / 12 items · 25%") !== -1 && task.indexOf(" B ") === -1, name + ": a task's count read as bytes: " + task);
    }
  });

  await test("T7: a duration's unit is the locale's on /tasks, hours included", async () => {
    const ar = LOCALE("ar"), de = LOCALE("de");
    assert(tm("ar").fmtDur(45) === "~" + ar["{n} s"].replace("{n}", "45"), tm("ar").fmtDur(45));
    assert(tm("de").fmtDur(600) === "~" + de["{n} min"].replace("{n}", "10"), tm("de").fmtDur(600));
    assert(tm("de").fmtDur(9000) === "~" + de["{n} h"].replace("{n}", "2.5"), tm("de").fmtDur(9000));
    assert(tm("en").fmtDur(9000) === "~2.5 h" && tm("en").fmtDur(45) === "~45 s", tm("en").fmtDur(9000));
  });

  function appDur(lang) {
    const I = i18n(lang);
    // eslint-disable-next-line no-new-func
    return new Function("window", "OOI18N", FMTNUM + ";" + extract("_fmtDur", null, CORE) + "; return _fmtDur;")(
      {OOI18N: I}, I);
  }
  await test("T7: ...and in the in-app window", async () => {
    const ar = LOCALE("ar");
    assert(appDur("ar")(45) === "~" + ar["{n} s"].replace("{n}", "45"), appDur("ar")(45));
    assert(appDur("ar")(600) === "~" + ar["{n} min"].replace("{n}", "10"), appDur("ar")(600));
    assert(appDur("en")(600) === "~10 min" && appDur("en")(null) === "—", appDur("en")(600));
  });

  const DUMP = {id: "dump:frwiki", kind: "wiki-dump", state: "queued", label: "French Wikipedia — articles dump",
    label_i18n: "{language} Wikipedia — articles dump", label_vars: {language: "fr"}};
  const PULL = {id: "model-pull:llama3:8b", kind: "model-pull", state: "running", label: "Downloading model llama3:8b",
    label_i18n: "Downloading model {model}", label_vars: {model: "llama3:8b"}};
  const BULK = {id: "task:4", kind: "llm", state: "running", label: "Summarizing 1234 article(s)",
    label_i18n: "Summarizing {n} article(s)", label_vars: {n: 1234}};

  await test("T11: /tasks writes a value-carrying label from its frame, in the UI language", async () => {
    const fr = LOCALE("fr");
    const page = tm("fr");
    const frName = new Intl.DisplayNames(["fr"], {type: "language"}).of("fr");
    assert(page.label(DUMP) === fr["{language} Wikipedia — articles dump"].replace("{language}", frName), page.label(DUMP));
    assert(bare(page.label(PULL)) === fr["Downloading model {model}"].replace("{model}", "llama3:8b"), page.label(PULL));
    assert(page.label(BULK) === fr["Summarizing {n} article(s)"].replace("{n}", "1" + NNBSP + "234"), page.label(BULK));
    assert(page.row(PULL).indexOf("Downloading model") === -1, "the row still prints the English label");
    // A code CLDR only echoes back keeps the server's English sentence whole.
    const simple = Object.assign({}, DUMP, {label: "Simple English Wikipedia — articles dump", label_vars: {language: "simple"}});
    assert(page.label(simple) === "Simple English Wikipedia — articles dump", page.label(simple));
    // A label with no frame is still a key.
    assert(page.label({label: "Re-indexing the corpus"}) === fr["Re-indexing the corpus"], "a fixed label");
  });

  function appLabel(lang) {
    const I = i18n(lang);
    const tables = CORE.slice(CORE.indexOf("const _OO_ISO1_TO_3_TEXT"), CORE.indexOf("function ooLangBase("));
    const src = [tables, extract("ooLangBase", null, CORE), extract("ooLangCode", null, CORE),
      extract("ooLangStorage", null, CORE), constLine(MAP, "_ooLangDN"), extract("ooLangName", null, MAP),
      FMTNUM, extract("_jobLabel", null, CORE), "return _jobLabel;"].join("\n");
    // eslint-disable-next-line no-new-func
    const fn = new Function("window", "OOI18N", src)({OOI18N: I}, I);
    return (j) => fn(j, I.t);
  }
  await test("T11: ...and so does the in-app window, through the app's own language names", async () => {
    const fr = LOCALE("fr");
    const lbl = appLabel("fr");
    const frName = new Intl.DisplayNames(["fr"], {type: "language"}).of("fr");
    assert(lbl(DUMP) === fr["{language} Wikipedia — articles dump"].replace("{language}", frName), lbl(DUMP));
    assert(lbl(BULK) === fr["Summarizing {n} article(s)"].replace("{n}", "1" + NNBSP + "234"), lbl(BULK));
    const simple = Object.assign({}, DUMP, {label: "Simple English Wikipedia — articles dump", label_vars: {language: "simple"}});
    assert(lbl(simple) === "Simple English Wikipedia — articles dump", "an echoed code became a name: " + lbl(simple));
    const tarask = Object.assign({}, DUMP, {label: "Belarusian (Taraškievica) Wikipedia — articles dump",
      label_vars: {language: "be-tarask"}});
    assert(lbl(tarask) === tarask.label, "a subtagged edition was named by its base: " + lbl(tarask));
  });

  // ============== T6: the estimate's method sentence =============================== //
  await test("T6: the method sentence is written from its frame, its numbers through fmtNum", async () => {
    const I = i18n("fr");
    // eslint-disable-next-line no-new-func
    const txt = new Function(FMTNUM + ";" + extract("_estimateMethodText", null, CORE) + "; return _estimateMethodText;")();
    const frame = "{sources} source(s) × ~{delay}s politeness delay × ~{fetches} fetch(es) each (from the last run) — an assumption, not a promise; robots crawl-delays can stretch it.";
    const plan = {estimate_method: "6411 source(s) × ~2.0s politeness delay × ~1.0 fetch(es) each (from the last run) — an assumption, not a promise; robots crawl-delays can stretch it.",
      estimate_method_i18n: frame, estimate_method_vars: {sources: 6411, delay: 2.0, fetches: 1.3}};
    const out = txt(plan, I.tf);
    assert(out === LOCALE("fr")[frame].replace("{sources}", "6" + NNBSP + "411").replace("{delay}", "2")
      .replace("{fetches}", "1.3"), out);
    assert(txt({estimate_method: "older server"}, I.tf) === "older server", "an older payload lost its sentence");
  });

  // ============== T8: the AI store's sizes ========================================= //
  async function store(lang, payload) {
    const I = i18n(lang);
    const box = {innerHTML: ""};
    const src = [ESC, extract("ooLabelHtml", null, CORE), extract("_sizeText", null, CORE), extract("_fmtBytes", null, CORE),
      extract("loadAiStore", "async function loadAiStore(", AI), "return loadAiStore;"].join("\n");
    // eslint-disable-next-line no-new-func
    const fn = new Function("window", "OOI18N", "$", "api", src)({OOI18N: I}, I,
      (id) => (id === "ai-store-box" ? box : null), () => Promise.resolve(payload));
    await fn();
    return box.innerHTML;
  }
  const STORE = {root: "/d/models",
    ollama: {in_app_folder: true, configured: "/d/models/ollama", bytes: 5300000},
    huggingface: {configured: "/d/models/huggingface", bytes: 21474836480}};

  await test("T8: a few-megabyte store reads its size, in the locale's unit, never '0.0 GB'", async () => {
    const fr = LOCALE("fr");
    const html = bare(await store("fr", STORE));
    assert(html.indexOf("0.0 GB") === -1, "the size said nothing: " + html);
    assert(html.indexOf("(" + bare(fr["{n} MB"].replace("{n}", "5.1")) + ")") !== -1, "MB: " + html);
    assert(html.indexOf("(" + bare(fr["{n} GB"].replace("{n}", "20.0")) + ")") !== -1, "GB: " + html);
  });

  // ============== T9: the reader's density line and the mindmap remainder ============ //
  function reader(lang) {
    const I = i18n(lang);
    // The reader's own esc() goes through a DOM node; the shared text escape stands in.
    const src = [ESC, extract("fmtNum", null, READER), extract("num", null, READER),
      extract("T", null, READER), extract("TF", null, READER),
      extract("renderSubjectivity", null, READER), extract("renderMindmap", null, READER),
      "return {sub: renderSubjectivity, mm: renderMindmap};"].join("\n");
    // eslint-disable-next-line no-new-func
    return new Function("window", src)({OOI18N: I});
  }
  const SUBJ = (n) => ({available: true, density: 0.0213, n_loaded: 1, n_tokens: n, terms: ["x"], method: "m", caveat: "c"});

  await test("T9: the density line is the locale's label and a whole counted frame", async () => {
    const fr = LOCALE("fr");
    const pane = {innerHTML: ""};
    reader("fr").sub(pane, SUBJ(4700));
    assert(pane.innerHTML.indexOf(esc_(fr["{prefix}: {text}"].replace("{prefix}", fr["Loaded-term density"])
      .replace("{text}", "\u0002")).replace("\u0002", "<b>0.0213</b>")) !== -1, pane.innerHTML);
    assert(pane.innerHTML.indexOf(esc_(fr["({n} of {m} words)"].replace("{n}", "1").replace("{m}", "4" + NNBSP + "700"))) !== -1,
      pane.innerHTML);
    assert(!/Loaded-term density| of 4/.test(pane.innerHTML), "English left in the French line: " + pane.innerHTML);
    reader("fr").sub(pane, SUBJ(1));
    assert(pane.innerHTML.indexOf(esc_(fr["({n} of {m} word)"].replace("{n}", "1").replace("{m}", "1"))) !== -1,
      "one word is not 'words': " + pane.innerHTML);
  });

  const MM = (arms) => ({nodes: [{center: true, label: "c", size: 5}].concat(
    Array.from({length: arms}, (_, i) => ({label: "k" + i, size: 1, mentions: 1}))), method: "m", caveat: "c"});
  await test("T9: the mindmap's remainder is one frame per count", async () => {
    const fr = LOCALE("fr");
    const pane = {innerHTML: ""};
    reader("fr").mm(pane, MM(16));
    assert(pane.innerHTML.indexOf(esc_(fr["+ {n} more keywords not shown."].replace("{n}", "2"))) !== -1, pane.innerHTML);
    reader("fr").mm(pane, MM(15));
    assert(pane.innerHTML.indexOf(esc_(fr["+ {n} more keyword not shown."].replace("{n}", "1"))) !== -1, pane.innerHTML);
    reader("en").mm(pane, MM(14));
    assert(pane.innerHTML.indexOf("more keyword") === -1, "no remainder, no line");
  });

  // ============== T10: the top-bar chip's count reaches the screen, keyed ============== //
  function chip(lang) {
    const I = i18n(lang);
    const el = (id) => ({id, hidden: true, textContent: "", classList: {toggle() {}, remove() {}}});
    const els = {"activity": el("activity"), "activity-host": el("activity-host"), "activity-label": el("activity-label")};
    const src = [FMTNUM, "let _inflight = 0, _bg = null, _curHost = null, _netOnline = true, _bgProgress = null;",
      extract("_paintActivity", null, CORE),
      "return {paint: _paintActivity, set(bg, pg, online) { _bg = bg; _bgProgress = pg; _netOnline = online; }};"].join("\n");
    // eslint-disable-next-line no-new-func
    const api = new Function("window", "OOI18N", "$", src)({OOI18N: I}, I, (id) => els[id]);
    return {api, els, I};
  }
  await test("T10: a running pass shows its position, grouped, in the UI language", async () => {
    const fr = LOCALE("fr");
    const c = chip("fr");
    c.api.set("Collecting…", {done: 3, total: 6411}, true);
    c.api.paint();
    assert(c.els["activity-label"].textContent === fr["Collecting {done}/{total}…"]
      .replace("{done}", "3").replace("{total}", "6" + NNBSP + "411"), c.els["activity-label"].textContent);
    // A language switch repaints it (app-boot.js calls _paintActivity).
    c.I.set("zh");
    c.api.paint();
    assert(c.els["activity-label"].textContent.indexOf(LOCALE("zh")["Collecting {done}/{total}…"].split(" ")[0]) === 0,
      c.els["activity-label"].textContent);
    // Offline, the pass is PAUSED, never "collecting x/y".
    c.api.set("Collecting…", {done: 3, total: 6411}, false);
    c.api.paint();
    assert(c.els["activity-label"].textContent.indexOf("6") === -1, c.els["activity-label"].textContent);
  });

  // ============== T12: the bulk qualification's tally, one frame per count ============ //
  async function qualify(lang, result) {
    const I = i18n(lang);
    const out = {textContent: ""};
    const els = {"qualify-bulk-status": out, "qualify-bulk-cancel-btn": {style: {}}};
    // B19 (Q12): the progress line and the ending reason go through _framedText/_jobLabel.
    const src = [FMTNUM, extract("_qualTf", null, AI), extract("_qualDeclinedText", null, AI),
      extract("_jobStillRunning", null, CORE), extract("_jobLabel", null, CORE), extract("_framedText", null, CORE),
      extract("qualifyBulkStart", "async function qualifyBulkStart(", AI), "return qualifyBulkStart;"].join("\n");
    // eslint-disable-next-line no-new-func
    const fn = new Function("window", "OOI18N", "$", "api", "ensureOnline", "pollJobStatus", "loadQualifyBulk", src)(
      {OOI18N: I}, I, (id) => els[id] || null, () => Promise.resolve({started: true}),
      () => Promise.resolve(true), () => Promise.resolve({state: "done", result}), () => {});
    await fn(null);
    return out.textContent;
  }
  await test("T12: one source reads 'qualified' in the singular, many in the plural, in every locale", async () => {
    const fr = LOCALE("fr");
    const one = await qualify("fr", {qualified: 1, disqualified: 3, no_evidence: 0});
    assert(one === [fr["{n} source qualified"].replace("{n}", "1"), fr["{n} sources disqualified"].replace("{n}", "3"),
      fr["{n} sources with no evidence yet"].replace("{n}", "0")].join(" · "), "fr: " + one);
    const many = await qualify("fr", {qualified: 3, disqualified: 1, no_evidence: 1});
    assert(many.indexOf(fr["{n} sources qualified"].replace("{n}", "3")) === 0, "fr: " + many);
    assert(!/\b3 qualifié\b/.test(many), "a plural count before a singular adjective: " + many);
    const en = await qualify("en", {qualified: 1204, disqualified: 1, no_evidence: 2, paused_reason: "cancelled"});
    assert(en === "1" + NNBSP + "204 sources qualified · 1 source disqualified · 2 sources with no evidence yet — cancelled", en);
  });

  console.log("all assertions passed (" + passed + " tests)");
}

run().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
