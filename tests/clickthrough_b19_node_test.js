/**
 * Behavioural node test for batch B19 of the 2026-09-26 delegated click-through (the last
 * tail): an import item's own word (Q1) and a volume backup's phase (Q2) are written in
 * the UI language on both task managers; /tasks writes its relative and absolute times in
 * the app's language (Q3); a task's "model {model}" line is a frame (Q5); the Performance
 * card's counts go through fmtNum with their nouns in one frame (Q6); the AI pill names its
 * work in the UI language and survives a switch (Q7); session durations use the keyed unit
 * frames (Q8); the reader's hover labels, trend line and subjectivity method/caveat are
 * keyed (Q9); the paused chip is one keyed string (Q10); the shipped-verdict counts pick
 * their frame by the count (Q11); and the qualification run's lines arrive as frames while
 * a unit-less progress is a plain count (Q12).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name -- a re-typed
 * copy would pass while the real code was still broken (the sibling-test convention).
 * Translations come from the REAL locale files. The server payloads below are the shapes
 * tests/test_clickthrough_b19_fixes.py pins from the server's own functions.
 *
 * Run by tests/test_clickthrough_b19_fixes.py (and standalone:
 * `node tests/clickthrough_b19_node_test.js`).
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
const AI = read("app-ai-tools.js");
const MARKETS = read("app-markets.js");
const READER = read("reader.js");
const TM = require("./app_source.js").pageSource("taskmanager.html");
const TIMELINE = require(path.join(STATIC, "ootimeline.js"));
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));
const EN = LOCALE("en");
const METHOD = Object.keys(EN).find((k) => k.startsWith("Share of curated loaded/subjective markers"));
const CAVEAT = Object.keys(EN).find((k) => k.startsWith("STRUCTURE, never intent or truth"));

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
// One `var NAME = ...;` line, read from the source.
function varLine(src, name) {
  const m = src.match(new RegExp("\\n\\s*var " + name + " = [^\\n]+"));
  assert(m, "could not read " + name);
  return m[0].trim();
}

const ESC = `const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));`;
const esc_ = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c]));
const NNBSP = " ";
const ISO = (s) => "⁨" + s + "⁩";
const fill = (frame, v) => frame.replace(/\{(\w+)\}/g, (m, k) => (v[k] == null ? m : String(v[k])));

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

// ---- the server shapes (pinned by tests/test_clickthrough_b19_fixes.py) -------------- //
const IMPORT_ROW = {id: "import-queue", kind: "import", state: "running", label: "Importing Données volumineuses",
  label_i18n: "Importing {label}", label_vars: {label: {i18n: "Large data"}},
  progress: {done: 1, total: 4, unit: "stages", percent: 25.0}, actions: ["cancel"]};
const IMPORT_FILE_ROW = {id: "import-queue", kind: "import", state: "running", label: "Importing corpus-2026.oo",
  label_i18n: "Importing {label}", label_vars: {label: "corpus-2026.oo"}, progress: null, actions: []};
const VOLUME_ROW = (n) => ({id: "volume-backup", kind: "volume-backup", state: "running",
  label: `Backing up (volumes + parity) — parity, ${n} volumes`,
  label_i18n: "{verb} — {phase}, {volumes}",
  label_vars: {verb: {i18n: "Backing up (volumes + parity)"}, phase: {i18n: "Writing parity…"},
    volumes: {i18n: n === 1 ? "{n} volume" : "{n} volumes", vars: {n}}},
  progress: null, actions: []});
const TASK_ROW = {id: "task:2", kind: "llm", state: "running", label: "Summarizing “Harbour festival”",
  label_i18n: "Summarizing “{title}”", label_vars: {title: "Harbour festival"},
  detail: "model llama3:8b", detail_i18n: "model {model}", detail_vars: {model: "llama3:8b"},
  elapsed_s: 420, progress: null, actions: []};
const TALLY = {qualified: {i18n: "{n} sources qualified", vars: {n: 3}},
  disqualified: {i18n: "{n} source disqualified", vars: {n: 1}},
  no_evidence: {i18n: "{n} source with no evidence yet", vars: {n: 1}}};
const AIRPLANE = "airplane mode engaged — progress is saved, start again to resume";

async function run() {
  // ============== Q1 / Q2 / Q5: the in-app window's labels ============================ //
  function core(lang) {
    const I = i18n(lang);
    const src = [ESC, FMTNUM, extract("_jobLabel", null, CORE), extract("_framedText", null, CORE),
      "return {label: _jobLabel, framed: _framedText};"].join("\n");
    // eslint-disable-next-line no-new-func
    return Object.assign(new Function("window", "OOI18N", src)({OOI18N: I}, I), {I});
  }
  await test("Q1: the import item's own word is written in the UI language, a file name stays data", async () => {
    for (const lang of ["fr", "ar", "zh"]) {
      const L = LOCALE(lang), c = core(lang);
      const got = c.label(IMPORT_ROW, c.I.t);
      assert(got === fill(L["Importing {label}"], {label: L["Large data"]}), `${lang}: ${got}`);
    }
    const fr = LOCALE("fr"), c = core("fr");
    assert(c.label(IMPORT_FILE_ROW, c.I.t) === fill(fr["Importing {label}"], {label: ISO("corpus-2026.oo")}),
      "a file name is data, in its isolate: " + c.label(IMPORT_FILE_ROW, c.I.t));
  });
  await test("Q2: a volume backup's verb, phase and volume count are keyed, the count picking its frame", async () => {
    for (const lang of ["fr", "ru", "ar"]) {
      const L = LOCALE(lang), c = core(lang);
      for (const n of [1, 5]) {
        const got = c.label(VOLUME_ROW(n), c.I.t);
        const want = fill(L["{verb} — {phase}, {volumes}"], {verb: L["Backing up (volumes + parity)"],
          phase: L["Writing parity…"], volumes: fill(L[n === 1 ? "{n} volume" : "{n} volumes"], {n})});
        assert(got === want, `${lang} n=${n}: ${got} != ${want}`);
        assert(got.indexOf("parity,") === -1, "the phase CODE never reaches the screen: " + got);
      }
    }
  });
  await test("Q12: a line with its frame is written from it; with none it is data", async () => {
    const fr = LOCALE("fr"), c = core("fr");
    assert(c.framed("model llama3:8b", "model {model}", {model: "llama3:8b"}, c.I.t)
      === fill(fr["model {model}"], {model: ISO("llama3:8b")}), "the model line");
    assert(c.framed("bare text", null, null, c.I.t) === "bare text", "no frame: shown as given");
  });

  // ============== Q12: a unit-less progress in the in-app window ======================= //
  await test("Q12: a progress with no unit is a plain count, never bytes", async () => {
    const I = i18n("fr");
    const src = [ESC, FMTNUM, "var _LOCAL_JOB_KINDS = new Set();",
      "function _isDownloadKind() { return false; } function _rateNote() { return ''; } function _jobWhy() { return ''; }",
      extract("_jobPct", null, CORE), extract("_jobLabel", null, CORE), extract("_jobRow", null, CORE), "return _jobRow;"].join("\n");
    // eslint-disable-next-line no-new-func
    const row = new Function("window", "OOI18N", src)({OOI18N: I}, I)(
      {id: "x", kind: "task", label: "Re-indexing the corpus", state: "running",
        progress: {done: 3, total: 12, percent: 25}, actions: []}, {}, I.t);
    assert(row.indexOf("3 / 12") !== -1, "the count: " + row);
    assert(!/\d\s?(B|KB|MB|o|Ko)\b/.test(row.replace(/[⁨⁩ ]/g, " ")), "no byte unit invented: " + row);
  });

  // ============== Q1 / Q2 / Q3 / Q5 / Q6: the /tasks page ============================= //
  function tm(lang) {
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      function t(s) { return OOI18N.t(s); }
      ${ESC}
      var _el = { "vitals-body": { innerHTML: "" } };
      var $ = function (id) { return _el[id]; };
      var isDl = function (k) { return k === "wiki-dump" || k === "osm-map"; };
      var isLocal = function (k) { return k === "reindex" || k === "keyword-fold" || k === "search-reindex"; };
      var dlKey = function (j) { return j.id; };
      ${varLine(TM, "PERF_N")}
      ${varLine(TM, "_perf")}
      ${varLine(TM, "_memMax")}
      ${extract("fmtBytes", null, TM)}
      ${extract("fmtRate", null, TM)}
      ${extract("tf", null, TM)}
      ${extract("fmtNum", null, TM)}
      ${extract("fmtDur", null, TM)}
      ${extract("fmtRel", null, TM)}
      ${extract("fmtLocal", null, TM)}
      var _langDN = {};
      ${extract("langName", null, TM)}
      ${extract("jobPct", null, TM)}
      ${extract("jobLabel", null, TM)}
      ${extract("jobDetail", null, TM)}
      ${extract("jobWhy", null, TM)}
      ${extract("jobRow", null, TM)}
      ${extract("sparkSvg", null, TM)}
      ${extract("perfCard", null, TM)}
      ${extract("nounCount", null, TM)}
      ${extract("renderPerformance", null, TM)}
      this.row = (j) => jobRow(j, {}); this.label = jobLabel; this.rel = fmtRel; this.local = fmtLocal;
      this.perf = (v, r) => { renderPerformance(v, r); return _el["vitals-body"].innerHTML; };
    `;
    const sb = {I: i18n(lang)};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb;
  }
  await test("Q1/Q2: /tasks writes the same keyed phrases as the in-app window", async () => {
    const fr = LOCALE("fr"), page = tm("fr"), c = core("fr");
    for (const row of [IMPORT_ROW, IMPORT_FILE_ROW, VOLUME_ROW(1), VOLUME_ROW(5), TASK_ROW]) {
      assert(page.label(row) === c.label(row, c.I.t), `the two task managers disagree: ${page.label(row)} / ${c.label(row, c.I.t)}`);
    }
    assert(page.row(IMPORT_ROW).indexOf(esc_(fill(fr["Importing {label}"], {label: fr["Large data"]}))) !== -1,
      "the row: " + page.row(IMPORT_ROW));
  });
  await test("Q3: relative times are keyed both ways, and the exact moment is in the app's language", async () => {
    for (const lang of ["fr", "ar", "en"]) {
      const L = lang === "en" ? {} : LOCALE(lang), page = tm(lang);
      const k = (key) => (L[key] == null ? key : L[key]);
      const ago = page.rel(new Date(Date.now() - 7 * 60000).toISOString());
      assert(ago === fill(k("{t} ago"), {t: fill(k("{n} min"), {n: "7"})}), `${lang} ago: ${ago}`);
      const fut = page.rel(new Date(Date.now() + 42 * 60000 + 500).toISOString());
      assert(fut === fill(k("in {t}"), {t: fill(k("{n} min"), {n: "42"})}), `${lang} in: ${fut}`);
      const secs = page.rel(new Date(Date.now() - 30000).toISOString());
      assert(secs === fill(k("{t} ago"), {t: fill(k("{n} s"), {n: "30"})}), `${lang} seconds: ${secs}`);
    }
    assert(!/\bago\b|^in /.test(tm("fr").rel(new Date(Date.now() - 7200000).toISOString())), "no English left in French");
    const when = "2026-09-14T08:30:00Z";
    const opts = {year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit"};
    assert(tm("fr").local(when) === new Intl.DateTimeFormat("fr", opts).format(new Date(when)), "fr: " + tm("fr").local(when));
    assert(tm("de").local(when) === new Intl.DateTimeFormat("de", opts).format(new Date(when)), "de: " + tm("de").local(when));
    assert(tm("fr").local(when) !== tm("en").local(when), "the page's language, not one fixed locale");
  });
  await test("Q3/Q5: 'running for' is one frame, and the model line is written from its frame", async () => {
    for (const lang of ["fr", "ar", "ja"]) {
      const L = LOCALE(lang), row = tm(lang).row(TASK_ROW);
      const running = fill(L["running for {t}"], {t: "~" + fill(L["{n} min"], {n: "7"})});
      assert(row.indexOf(esc_(running)) !== -1, `${lang} running-for: ${row}`);
      assert(row.indexOf(esc_(fill(L["model {model}"], {model: ISO("llama3:8b")}))) !== -1, `${lang} detail: ${row}`);
      assert(row.indexOf(">model llama3") === -1, `${lang}: the English detail leaked: ${row}`);
    }
    const fixed = tm("fr").row(Object.assign({}, TASK_ROW, {detail: "all enabled sweeps are up to date",
      detail_i18n: null, detail_vars: null}));
    assert(fixed.indexOf(esc_(LOCALE("fr")["all enabled sweeps are up to date"])) !== -1, "a fixed detail is a key: " + fixed);
  });
  await test("Q6: the Performance card's numbers go through fmtNum, each count with its noun in one frame", async () => {
    const V = (cores, threads) => ({process: {cpu_percent: 12.34, cpu_cores: cores, num_threads: threads, rss_bytes: 1048576},
      scraping: {bytes_total: 2048, fetches_total: 12345}});
    for (const lang of ["fr", "ru", "ar"]) {
      const L = LOCALE(lang);
      const html = tm(lang).perf(V(8, 1), {netRate: 0, diskRate: 0});
      assert(html.indexOf(esc_(fill(L["{n} cores"], {n: "8"}))) !== -1, `${lang} cores: ${html}`);
      assert(html.indexOf(esc_(fill(L["{n} thread"], {n: "1"}))) !== -1, `${lang} one thread: ${html}`);
      assert(html.indexOf("12" + NNBSP + "345×") !== -1, `${lang} fetches: ${html}`);
      assert(html.indexOf(">12.3%<") !== -1, `${lang} cpu: ${html}`);
      const one = tm(lang).perf(V(1, 23), {netRate: 0, diskRate: 0});
      assert(one.indexOf(esc_(fill(L["{n} core"], {n: "1"}))) !== -1 && one.indexOf(esc_(fill(L["{n} threads"], {n: "23"}))) !== -1,
        `${lang} one core / many threads: ${one}`);
    }
  });

  // ============== Q7: the AI pill ====================================================== //
  async function pill(lang, act) {
    const I = i18n(lang);
    const el = {id: "llm", title: "AI status", textContent: "AI", className: "pill", style: {}};
    const calls = {api: 0};
    const src = [FMTNUM, ESC, extract("_jobLabel", null, CORE),
      "let _aiStarting = false, _aiHealth = {available: true}, _aiBusyLocal = 0, _aiBusyServer = false;",
      "let _aiBusyLabel = null, _aiActPollTimer = null;",
      "async function aiPillClick() {}",
      extract("_aiBusy", null, AI), extract("_paintAiPill", null, AI),
      extract("_aiActShouldPoll", null, AI), extract("_aiActCadence", null, AI),
      extract("_ensureAiActivityPoll", null, AI),
      "return {poll: _ensureAiActivityPoll, paint: _paintAiPill};"].join("\n");
    // eslint-disable-next-line no-new-func
    const P = new Function("window", "OOI18N", "$", "api", "document", "setTimeout", "clearTimeout", src)(
      {OOI18N: I}, I, (id) => (id === "llm" ? el : null),
      async () => { calls.api += 1; return act; }, {hidden: false}, () => 0, () => {});
    P.poll();
    await new Promise((r) => setTimeout(r, 0));
    return {P, el, I, calls};
  }
  const ACT = {working: true, label: "Summarizing “Harbour festival”", label_i18n: "Summarizing “{title}”",
    label_vars: {title: "Harbour festival"}, models: []};
  await test("Q7: the busy pill names its work in the UI language, and its word is keyed", async () => {
    for (const lang of ["fr", "ar", "zh"]) {
      const L = LOCALE(lang), p = await pill(lang, ACT);
      assert(p.el.title === fill(L["Summarizing “{title}”"], {title: ISO("Harbour festival")}) + " — " + L["AI is working right now"],
        `${lang}: ${p.el.title}`);
      assert(p.el.textContent === L["AI"], `${lang} word: ${p.el.textContent}`);
    }
  });
  await test("Q7: a language switch repaints the pill from what it holds, with no request", async () => {
    const p = await pill("fr", ACT);
    const before = p.calls.api;
    p.I.set("de");
    p.P.paint();
    const de = LOCALE("de");
    assert(p.el.title.indexOf(de["AI is working right now"]) !== -1 && p.el.textContent === de["AI"], "de: " + p.el.title);
    assert(p.calls.api === before, "a repaint must not fetch");
  });
  await test("Q7: a batch hold is a fixed sentence (keyed); a model name is data", async () => {
    const fr = LOCALE("fr");
    const hold = await pill("fr", {working: true, label: "bulk summarize", label_i18n: null, label_vars: null, models: []});
    assert(hold.el.title.indexOf(fr["bulk summarize"] + " — ") === 0, "hold: " + hold.el.title);
    const model = await pill("fr", {working: true, label: null, models: ["llama3:8b"]});
    assert(model.el.title.indexOf("llama3:8b — ") === 0, "model: " + model.el.title);
  });

  // ============== Q8: session durations ================================================ //
  await test("Q8: a session's duration is written with the keyed unit frames", async () => {
    for (const lang of ["fr", "ar", "ru"]) {
      const I = i18n(lang), L = LOCALE(lang);
      const src = [ESC, FMTNUM, extract("_sessionHtml", null, CORE), "return _sessionHtml;"].join("\n");
      // eslint-disable-next-line no-new-func
      const html = new Function("window", "OOI18N", src)({OOI18N: I, ooTimeline: TIMELINE}, I)(
        {since_last_restart_s: 3600 * 26 + 120, longest_stretch_s: 30});
      const long = [fill(L["{n} d"], {n: "1"}), fill(L["{n} h"], {n: "02"}), fill(L["{n} min"], {n: "02"})].join(" ");
      assert(html.indexOf(esc_(long)) !== -1, `${lang} long: ${html}`);
      assert(html.indexOf(esc_(fill(L["{n} s"], {n: "30"}))) !== -1, `${lang} short: ${html}`);
    }
    assert(TIMELINE.fmtDur(3600 * 26 + 120) === "1 d 02 h 02 m", "without a writer the locale-free form is unchanged");
  });

  // ============== Q9: the reader ======================================================= //
  function reader(lang) {
    const I = i18n(lang);
    const src = [ESC, "var localStorage = {getItem: function () { return null; }}; var _langDN = {};",
      ...["fmtNum", "num", "T", "TF", "rdLabelText", "uiLang", "langName", "langList", "countsLine", "rdLabel",
        "kwStatLine", "renderSubjectivity"].map((n) => extract(n, null, READER)),
      "return {label: rdLabel, stat: kwStatLine, sub: renderSubjectivity};"].join("\n");
    // eslint-disable-next-line no-new-func
    return new Function("window", src)({OOI18N: I});
  }
  await test("Q9: the reader's hover labels go through the locale's own label frame", async () => {
    const fr = LOCALE("fr"), label = (p, v) => fill(fr["{prefix}: {text}"], {prefix: p, text: v});
    const out = reader("fr").label({term: "Wahl", translation: "élection", translation_tier: "verified",
      mention_languages: {de: 3}, translation_qid: "Q40231"});
    assert(out.hover.indexOf(label(fr["Original"], "Wahl")) !== -1, "Original: " + out.hover);
    assert(out.hover.indexOf(label("Wikidata", "Q40231")) !== -1, "Wikidata: " + out.hover);
    const lang = reader("fr").label({term: "Wahl", translation_tier: "untranslated", translation_source_lang: "de"});
    assert(lang.hover.indexOf(fr["Language"] + " : ") !== -1, "Language: " + lang.hover);
    assert(!/[^ ]: /.test(out.hover.replace(/https?:/g, "")), "no English colon welded on in French: " + out.hover);
  });
  await test("Q9: the keyword hover's trend is one frame with keyed day spans", async () => {
    for (const lang of ["fr", "ar", "ja"]) {
      const L = LOCALE(lang);
      const line = reader(lang).stat({resolved: true, mentions: 5, articles: 2,
        trend: {recent: 3, prior: 1, growth: 1.5, window_days: 30, baseline_days: 90},
        cooccurrences: [{term: "a"}, {term: "b"}]});
      const trend = fill(L["{prefix}: {text}"], {prefix: L["trend"], text: fill(L["{growth}× ({window} vs {baseline})"],
        {growth: spaFmt(1.5), window: fill(L["{n} d"], {n: "30"}), baseline: fill(L["{n} d"], {n: "90"})})});
      assert(line.indexOf(trend) !== -1, `${lang} trend: ${line}`);
      assert(line.indexOf(fill(L["{prefix}: {text}"], {prefix: L["with"], text: "a, b"})) !== -1, `${lang} with: ${line}`);
      assert(line.indexOf("30d") === -1, `${lang}: the welded English unit is gone: ${line}`);
    }
  });
  await test("Q9: the subjectivity method and caveat are written in the UI language", async () => {
    assert(METHOD && CAVEAT, "the method and caveat are keys in en.json");
    for (const lang of ["fr", "ar", "zh"]) {
      const L = LOCALE(lang), pane = {innerHTML: ""};
      reader(lang).sub(pane, {available: true, density: 0.02, n_loaded: 1, n_tokens: 50, terms: ["x"], method: METHOD, caveat: CAVEAT});
      assert(pane.innerHTML.indexOf(esc_(L[METHOD])) !== -1, `${lang} method`);
      assert(pane.innerHTML.indexOf(esc_(L[CAVEAT])) !== -1, `${lang} caveat`);
      assert(pane.innerHTML.indexOf("STRUCTURE, never intent") === -1, `${lang}: English caveat left`);
    }
  });

  // ============== Q10: the paused chip ================================================= //
  await test("Q10: the paused chip is ONE keyed string, its ellipsis the locale's", async () => {
    for (const lang of ["fr", "ja", "ar"]) {
      const I = i18n(lang), L = LOCALE(lang);
      const el = (id) => ({id, hidden: true, textContent: "", classList: {toggle() {}, remove() {}}});
      const els = {"activity": el("activity"), "activity-host": el("activity-host"), "activity-label": el("activity-label")};
      const src = [FMTNUM, "let _inflight = 0, _bg = 'Collecting…', _curHost = null, _netOnline = false, _bgProgress = null;",
        extract("_paintActivity", null, CORE), "return _paintActivity;"].join("\n");
      // eslint-disable-next-line no-new-func
      new Function("window", "OOI18N", "$", src)({OOI18N: I}, I, (id) => els[id])();
      assert(els["activity-label"].textContent === L["Collecting paused…"], `${lang}: ${els["activity-label"].textContent}`);
    }
  });

  // ============== Q11: the shipped-verdict counts ====================================== //
  await test("Q11: one shipped verdict reads in the singular, several in the plural", async () => {
    for (const lang of ["fr", "ru", "de"]) {
      const I = i18n(lang), L = LOCALE(lang);
      const host = {textContent: "", innerHTML: ""};
      const src = [ESC, FMTNUM, extract("ooLabelHtml", null, CORE), extract("_qualTf", null, AI),
        extract("_overlayButtons", null, AI), extract("loadOverlayEditor", "async function loadOverlayEditor(", AI),
        "return loadOverlayEditor;"].join("\n");
      // eslint-disable-next-line no-new-func
      const load = new Function("window", "OOI18N", "$", "api", "_apiErrorMessage", src)({OOI18N: I}, I,
        (id) => (id === "qual-overlay" ? host : null),
        async () => ({file: {exists: true}, in_overlay: 4, shipped_qualified: 1, shipped_disqualified: 3,
          adopted_here: 1, revertible: 1, declined: {}, would_adopt: 0, adopting_at_startup: true}),
        (e) => String(e));
      await load();
      assert(host.innerHTML.indexOf(esc_(fill(L["{n} source qualified"], {n: "1"}))) !== -1, `${lang} one: ${host.innerHTML}`);
      assert(host.innerHTML.indexOf(esc_(fill(L["{n} sources disqualified"], {n: "3"}))) !== -1, `${lang} many: ${host.innerHTML}`);
    }
  });

  // ============== Q12: the qualification run's lines =================================== //
  async function qualify(lang, progress, result) {
    const I = i18n(lang);
    const out = {textContent: ""}, seen = [];
    const els = {"qualify-bulk-status": out, "qualify-bulk-cancel-btn": {style: {}}};
    const src = [FMTNUM, extract("_qualTf", null, AI), extract("_qualDeclinedText", null, AI),
      extract("_jobStillRunning", null, CORE), extract("_jobLabel", null, CORE), extract("_framedText", null, CORE),
      extract("qualifyBulkStart", "async function qualifyBulkStart(", AI), "return qualifyBulkStart;"].join("\n");
    // eslint-disable-next-line no-new-func
    const fn = new Function("window", "OOI18N", "$", "api", "ensureOnline", "pollJobStatus", "loadQualifyBulk", src)(
      {OOI18N: I}, I, (id) => els[id] || null, () => Promise.resolve({started: true}), () => Promise.resolve(true),
      async (u, o) => { o.onProgress(progress); seen.push(out.textContent); return {state: "done", result}; }, () => {});
    await fn(null);
    seen.push(out.textContent);
    return seen;
  }
  await test("Q12: the run's progress line and its ending reason are written in the UI language", async () => {
    for (const lang of ["fr", "ar", "zh"]) {
      const L = LOCALE(lang);
      const [during, after] = await qualify(lang,
        {progress: {done: 5, total: 40}, done: 5, total: 40, detail: "3 qualified · 1 disqualified · 1 no-evidence so far",
          detail_i18n: "so far: {qualified} · {disqualified} · {no_evidence}", detail_vars: TALLY},
        {qualified: 3, disqualified: 1, no_evidence: 1, paused_reason: AIRPLANE, paused_reason_i18n: AIRPLANE,
          paused_reason_vars: {}});
      const soFar = fill(L["so far: {qualified} · {disqualified} · {no_evidence}"], {
        qualified: fill(L["{n} sources qualified"], {n: "3"}), disqualified: fill(L["{n} source disqualified"], {n: "1"}),
        no_evidence: fill(L["{n} source with no evidence yet"], {n: "1"})});
      assert(during === soFar + " 5/40", `${lang} during: ${during} != ${soFar}`);
      assert(after.endsWith(" — " + L[AIRPLANE]), `${lang} reason: ${after}`);
      assert(!/airplane mode engaged|so far/.test(during + after), `${lang}: English left: ${during} | ${after}`);
    }
  });

  console.log(`\nall assertions passed (${passed} tests)`);
}

run().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
