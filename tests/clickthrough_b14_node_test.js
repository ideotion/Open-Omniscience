/**
 * Behavioural node test for batch B14 of the 2026-09-26 delegated click-through: the
 * Home strip's numbers through the ruled formatter (Z1), size panels repainted on a
 * language switch from the payload they last drew (Z2), the locale's own "label: value"
 * separator (Z3), the Governments group aggregates in the reader's language with a
 * whole-series refusal said once (Z4), and a language picked in another tab (Z8).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name -- a re-typed
 * copy would pass while the real code was still broken (the sibling-test convention;
 * see tests/clickthrough_b12_node_test.js). Translations come from the REAL locale files.
 *
 * Run by tests/test_clickthrough_b14_fixes.py (and standalone:
 * `node tests/clickthrough_b14_node_test.js`).
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
const HOME = read("app-home.js");
const MARKETS = read("app-markets.js");
const SETTINGS = read("app-settings.js");
const LIB = read("app-library.js");
const GOV = read("app-gov-law.js");
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

// An object literal by balanced braces, from its declaration to its closing brace.
function extractObj(head, src) {
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let depth = 0;
  for (let j = src.indexOf("{", at); j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + head);
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
  // ======================= Z1: the Home strip's numbers ====================== //
  // toLocaleString() reads the BROWSER's locale, which the app's language switcher never
  // changes: a French strip read "6,402" under an English browser. fmtNum is the app's
  // one ruled formatter (Latin digits, a decimal point, U+202F grouping) in every locale.
  function homeHover(lang, withFormatter) {
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${withFormatter ? extract("fmtNum", null, MARKETS) : ""}
      ${extractObj("const HOME_SOURCE_SPLIT_HOVER = {", HOME)};
      const HOME_SOURCE_SPLIT_KEYS = ["sources_qualified", "sources_pending", "sources_candidates"];
      ${extract("homeSourceSplitHover", null, HOME)}
      this.hover = homeSourceSplitHover;
    `;
    const sb = {I: i18n(lang)};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb.hover;
  }

  await test("Z1: the Home split hover groups its counts with the ruled formatter, not the browser's", async () => {
    const hover = homeHover("fr", true)("sources_qualified",
      {sources: 12806, sources_qualified: 6402, sources_pending: 6000, sources_candidates: 404});
    assert(hover.indexOf("6" + NNBSP + "402") !== -1, "the count is not fmtNum-grouped: " + hover);
    assert(hover.indexOf("12" + NNBSP + "806") !== -1, "the total is not fmtNum-grouped: " + hover);
    assert(hover.indexOf("6,402") === -1 && hover.indexOf("6 402") === -1,
      "a browser-locale grouping leaked into the French hover: " + hover);
  });

  await test("Z1: extracted without the formatter (a node harness) the hover still renders", async () => {
    const hover = homeHover("en", false)("sources_pending", {sources_qualified: 1, sources_pending: 2});
    assert(hover.indexOf("2 of your 3 sources") !== -1, hover);
  });

  // ======================= Z3: the locale's own separator ==================== //
  function core(lang) {
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      ${extract("ooLabelHtml", null, CORE)}
      ${extract("ooLabelText", null, CORE)}
      this.html = ooLabelHtml; this.text = ooLabelText;
    `;
    const sb = {I: i18n(lang)};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb;
  }

  await test("Z3: 'label: value' takes the reader's separator (fr space, zh/ja full-width)", async () => {
    assert(core("en").text("absolute floor", 0.5) === "absolute floor: 0.5", core("en").text("absolute floor", 0.5));
    assert(core("fr").text("seuil absolu", 0.5) === "seuil absolu : 0.5", core("fr").text("seuil absolu", 0.5));
    assert(core("zh").text("绝对阈值", 0.5) === "绝对阈值：0.5", core("zh").text("绝对阈值", 0.5));
    assert(core("ja").html("<b>X</b>", "<i>1</i>") === "<b>X</b>：<i>1</i>", core("ja").html("<b>X</b>", "<i>1</i>"));
  });

  await test("Z3: the frame is text -- markup comes only from the caller's escaped pieces", async () => {
    const sb = core("en");
    sb.I.map = {"{prefix}: {text}": "<i>{prefix}</i> $& {text}"};
    const out = sb.html("<b>L</b>", "V$1");
    assert(out === "&lt;i&gt;<b>L</b>&lt;/i&gt; $&amp; V$1", "the frame was read as markup or as a pattern: " + out);
  });

  await test("Z3: the storage footprint's summary line uses the French colon", async () => {
    const I = i18n("fr");
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      ${extract("ooLabelHtml", null, CORE)}
      const _SF_PUBLIC = new Set(["wiki_dumps"]);
      const _sfLabel = (kind, name) => name || kind;
      const _fmtBytes = (n) => n + " B";
      ${extract("_sfPaint", null, LIB)}
      this.paint = _sfPaint;
    `;
    const sb = {I};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    const host = {id: "library-storage", innerHTML: ""};
    sb.paint(host, {totals: {grand_total_bytes: 30}, components: [
      {kind: "db", name: "db", bytes: 20}, {kind: "wiki_dumps", name: "dumps", bytes: 10}]}, I.t);
    const fr = LOCALE("fr");
    const priv = fr["Private (local; corpus encrypted at rest)"];
    assert(host.innerHTML.indexOf(priv + " : <b>20 B</b>") !== -1, "the private line lacks the French colon: " + host.innerHTML);
    assert(host.innerHTML.indexOf(fr["Re-downloadable (dumps / maps / models)"] + " : <b>10 B</b>") !== -1,
      "the re-downloadable line lacks the French colon: " + host.innerHTML);
    assert(host.innerHTML.indexOf("): <b>") === -1, "a welded ': ' survived: " + host.innerHTML);
  });

  // ======================= Z2: sizes repaint on a language switch ============= //
  await test("Z2: Settings Storage redraws from its last payload on a switch -- no fetch, typed budget kept", async () => {
    const I = i18n("en");
    const els = {};
    const mk = (id) => (els[id] = {id, innerHTML: "", value: ""});
    ["storage-reading", "storage-lanes", "storage-disk"].forEach(mk);
    const calls = {api: []};
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      const els = this.els, calls = this.calls;
      const $ = (id) => els[id] || null;
      const document = { querySelectorAll: (sel) => Object.values(els).filter((e) => /^storage-budget-/.test(e.id)) };
      async function api(p) { calls.api.push(p); return this_rep; }
      let this_rep = null;
      const humanBytes = (n) => OOI18N.tf("{n} MB", {n: (n / 1048576).toFixed(1)});
      const _storageReadingHtml = (rep) => OOI18N.t("Storage");
      const _storageTableHtml = (rep) => '<input id="storage-budget-wiki" value="5">';
      ${extract("_storageDiskHtml", null, SETTINGS)}
      let _laneStorageLast = null;
      ${extract("_paintLaneStorage", null, SETTINGS)}
      ${extract("repaintLaneStorageFromCache", null, SETTINGS)}
      ${extract("loadLaneStorage", "async function loadLaneStorage(", SETTINGS)}
      this.setRep = (r) => { this_rep = r; };
      this.load = loadLaneStorage; this.repaint = repaintLaneStorageFromCache;
    `;
    const sb = {I, els, calls};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    // Before the panel was ever drawn, a switch does nothing.
    sb.repaint();
    assert(calls.api.length === 0 && els["storage-disk"].innerHTML === "", "repainted a panel never drawn");
    sb.setRep({disk: {free_bytes: 37329305, total_bytes: 104857600}});
    await sb.load();
    assert(els["storage-disk"].innerHTML.indexOf("35.6 MB") !== -1, "not drawn in English: " + els["storage-disk"].innerHTML);
    els["storage-budget-wiki"] = {id: "storage-budget-wiki", value: "9"};   // the operator is typing
    I.set("fr");
    sb.repaint();
    const disk = els["storage-disk"].innerHTML;
    assert(disk.indexOf("35.6 Mo") !== -1, "the size kept the old locale after the switch: " + disk);
    assert(disk.indexOf("Disk left") === -1, "the frame kept the old locale: " + disk);
    assert(calls.api.length === 1, "the switch fetched: " + calls.api);
    assert(els["storage-budget-wiki"].value === "9", "a typed budget was lost to the redraw");
  });

  await test("Z2: the Library overview redraws from its last payload and keeps an opened disclosure", async () => {
    const painted = [];
    let det = {open: true};
    const host = {querySelector: () => det};
    const src = `
      const $ = (id) => (id === "library-overview" ? this.host : null);
      let _libOvLast = null;
      function _paintLibraryOverview(host, d, fig) { this_painted.push([d, fig]); this_reset(); }
      const this_painted = this.painted, this_reset = this.reset;
      ${extract("repaintLibraryOverviewFromCache", null, LIB)}
      this.repaint = repaintLibraryOverviewFromCache;
      this.seed = (v) => { _libOvLast = v; };
    `;
    const sb = {host, painted, reset: () => { det = {open: false}; }};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    sb.repaint();
    assert(painted.length === 0, "repainted an overview never drawn");
    sb.seed({d: {downloaded: 1}, fig: {n: 2}});
    sb.repaint();
    assert(painted.length === 1 && painted[0][0].downloaded === 1 && painted[0][1].n === 2,
      "not redrawn from the cached payload");
    assert(det.open === true, "the disclosure the reader opened was closed by the redraw");
    assert(!/\bapi\(/.test(extract("repaintLibraryOverviewFromCache", null, LIB)), "the repaint fetches");
  });

  // ======================= Z4: group aggregates ============================== //
  function govHtml(lang, strategies, coverage) {
    const I = i18n(lang);
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      const ooCountryCode = (c) => String(c).toUpperCase();
      const _govFmt = (v) => String(v);
      ${extract("_govTf", null, GOV)}
      ${extract("_govNames", null, GOV)}
      ${extract("_govGroupHtml", null, GOV)}
      this.render = _govGroupHtml;
    `;
    const sb = {I};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb.render({
      group: {members: ["fr", "de", "it"], resolved_year: 2024, as_of: "2026-09-01"},
      aggregate: {coverage: coverage || {members: 3, reported: 3, missing: [], complete: true},
        spread: {}, strategies, caveat: "Strategies are shown side by side and never blended: they answer different questions and can legitimately disagree. A mean over members weighs a small country like a large one; a weighted mean weighs people (or output) instead. Each figure states its own method."},
    }, false);
  }
  const SIX = [["sum", "Total"], ["mean", "Mean of members"], ["median", "Median member"],
    ["population_weighted", "Population-weighted mean"], ["gdp_weighted", "GDP-weighted mean"],
    ["labour_force_weighted", "Labour-force-weighted mean"]];

  await test("Z4: a whole-series refusal is said ONCE above the cards, not six times", async () => {
    const fr = LOCALE("fr");
    const strategies = {};
    for (const [k, label] of SIX) strategies[k] = {label, refused: "English refusal.", refused_code: "incomplete"};
    const html = govHtml("fr", strategies, {members: 3, reported: 2, missing: ["it"], complete: false});
    const frame = fr["{missing} of {members} members did not report this indicator for this period ({who}). A figure over the members that happen to have reported is not the group's figure, and nothing downstream could tell the difference. Choose “{action}” to compute it anyway — the missing members travel with the result."];
    // The frame's longest literal stretch, counted in the page: once, above the cards.
    const lead = esc_(frame.split(/\{\w+\}/).sort((a, b) => b.length - a.length)[0]);
    assert(lead.length > 40, "the French frame has no long literal stretch: " + frame);
    const n = html.split(lead).length - 1;
    assert(n === 1, "the refusal appears " + n + " times: " + html);
    const note = fr["Not computed: the reason is stated above the cards."];
    assert(html.split(esc_(note)).length - 1 === 6, "each card does not point to the one refusal: " + html);
    for (const [, label] of SIX) assert(html.indexOf(">" + esc_(fr[label]) + "<") !== -1, "label not French: " + label);
    assert(html.indexOf("English refusal.") === -1, "the English sentence leaked: " + html);
    assert(html.indexOf("population_weighted") === -1, "an internal key was printed");
  });

  await test("Z4: each method and refusal is drawn in the reader's language from its code", async () => {
    const fr = LOCALE("fr");
    const html = govHtml("fr", {
      sum: {label: "Total", refused: "E1", refused_code: "intensive"},
      mean: {label: "Mean of members", value: 2, basis: "exact", method: "E2", method_code: "members"},
      median: {label: "Median member", value: 2, basis: "exact", method: "E3", method_code: "median"},
      population_weighted: {label: "Population-weighted mean", value: 2, basis: "exact", method: "E4",
        method_code: "weighted_exact", weight: "population", denominator: "population"},
      gdp_weighted: {label: "GDP-weighted mean", refused: "E5", refused_code: "missing_weight", weight: "gdp",
        missing_weight: ["de"]},
      labour_force_weighted: {label: "Labour-force-weighted mean", value: 2, basis: "approximate", method: "E6",
        method_code: "weighted_approx", weight: "labour_force", denominator: "population"},
    });
    for (const e of ["E1", "E2", "E3", "E4", "E5", "E6"]) {
      assert(html.indexOf(">" + e + "<") === -1, "the English sentence " + e + " was shown in French: " + html);
    }
    assert(html.indexOf(esc_(fr["This indicator is intensive — a rate, share, index or per-capita value — so its members' values do not add up to anything. A summed percentage is not a large percentage; it is not a statistic at all."])) !== -1, "intensive not French");
    const exact = fr["Sum of (value x {weight}) divided by the summed {weight}. This indicator is measured PER {weight}, so the reconstructed numerator is the real one and this is the group's true figure, not an estimate."]
      .replace(/\{weight\}/g, fr["population"]);
    assert(html.indexOf(esc_(exact)) !== -1, "the exact weighted method is not French: " + html);
    const miss = fr["{n} member(s) reported a value but have no {weight} weight ({who}). Dropping them would compute over a different membership than the label claims, and weighting them as unweighted would silently mix two methods."]
      .replace("{n}", "1").replace("{weight}", fr["GDP"]).replace("{who}", "DE");
    assert(html.indexOf(esc_(miss)) !== -1, "the missing-weight refusal is not French: " + html);
    const approx = fr["Sum of (value x {weight}) divided by the summed {weight}. APPROXIMATE: this indicator is measured per {denominator}, not per {weight}, so the reconstructed numerator is not the real one."]
      .replace(/\{weight\}/g, fr["labour force"]).replace("{denominator}", fr["population"]);
    assert(html.indexOf(esc_(approx)) !== -1, "the approximate weighted method is not French: " + html);
    // Two different refusals: nothing is hoisted above the cards.
    assert(html.indexOf("gov-grp-refusal") === -1, "a mixed set was hoisted as one refusal");
  });

  await test("Z4: under partial coverage the method carries the PARTIAL frame, keyed", async () => {
    const fr = LOCALE("fr");
    const html = govHtml("fr", {mean: {label: "Mean of members", value: 2, basis: "approximate", method: "E", method_code: "members"}},
      {members: 3, reported: 2, missing: ["it"], complete: false});
    const partial = fr["PARTIAL: computed over {reported} of {members} members; {missing} did not report."]
      .replace("{reported}", "2").replace("{members}", "3").replace("{missing}", "1");
    assert(html.indexOf(esc_(partial)) !== -1, "the PARTIAL clause is not French: " + html);
  });

  await test("Z4: a result with no code (an older server) keeps the engine's sentence verbatim", async () => {
    const html = govHtml("fr", {
      sum: {label: "Total", refused: "Not a statistic at all."},
      mean: {label: "Mean of members", value: 1, basis: "exact", method: "m"},
    });
    assert(html.indexOf("Not a statistic at all.") !== -1 && html.indexOf(">m<") !== -1, html);
  });

  await test("Z4: a language switch redraws the group cards from the last payload, never a fetch", async () => {
    const drawn = [];
    const host = {innerHTML: "", hasGrid: false, querySelector: (sel) => (sel === ".gov-strat-grid" && host.hasGrid ? {} : null)};
    const src = `
      const $ = (id) => (id === "gov-grp-body" ? this.host : null);
      let _govGrpLast = null;
      function _govGroupHtml(d, allow) { this_drawn.push([d, allow]); return "<grid>"; }
      const this_drawn = this.drawn;
      ${extract("repaintGovGroupFromCache", null, GOV)}
      this.repaint = repaintGovGroupFromCache;
      this.seed = (v) => { _govGrpLast = v; };
    `;
    const sb = {host, drawn};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    sb.repaint();
    assert(drawn.length === 0, "repainted a card set never drawn");
    sb.seed({d: {aggregate: {}}, allowIncomplete: true});
    host.innerHTML = "<div class=\"muted\">Loading…</div>";   // a render in flight: not the cards
    sb.repaint();
    assert(drawn.length === 0, "overwrote a panel that is not showing the cached cards");
    host.hasGrid = true;
    sb.repaint();
    assert(drawn.length === 1 && drawn[0][1] === true && host.innerHTML === "<grid>",
      "not redrawn from the cached payload with its own allow-incomplete choice");
    assert(!/\bapi\(/.test(extract("repaintGovGroupFromCache", null, GOV)), "the repaint fetches");
  });

  // ======================= Z8: a language picked in another tab ============== //
  await test("Z8: the main app follows a language another tab picked, and ignores everything else", async () => {
    const body = CORE.slice(CORE.indexOf('window.addEventListener("storage", (e) => {'));
    const listener = body.slice(0, body.indexOf("});") + 3);
    const picked = [];
    const handlers = [];
    const window = {addEventListener: (ev, fn) => { if (ev === "storage") handlers.push(fn); }};
    const document = {documentElement: {lang: "en"}};
    // eslint-disable-next-line no-new-func
    new Function("window", "document", "pickLang", listener)(window, document, (c) => picked.push(c));
    assert(handlers.length === 1, "no storage listener registered");
    handlers[0]({key: "oo.theme", newValue: "dark"});
    handlers[0]({key: "oo.lang", newValue: null});
    handlers[0]({key: "oo.lang", newValue: "en"});
    assert(picked.length === 0, "acted on an unrelated or unchanged key: " + picked);
    handlers[0]({key: "oo.lang", newValue: "fr"});
    assert(picked.join() === "fr", "did not switch to the language the other tab picked: " + picked);
  });

  console.log("all assertions passed (" + passed + " tests)");
}

function esc_(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c]));
}

run().catch((e) => { console.error(e); process.exit(1); });
