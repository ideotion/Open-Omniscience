// The analysis window's 2026-09-27 re-walk fixes (batch B24), run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Every renderer below is EXTRACTED from the shipped modules rather than re-typed, and
// the i18n engine is driven by the REAL locale files -- t() is the same exact-key lookup
// OOI18N does, tf() the same frame fill -- so an assertion about French is an assertion
// about what a French reader sees, not about a table this file invented.
//
// One GROUP per defect, chosen by argv, so each can fail on its own:
//   n3  the Trend's Counts mode and the price panel say MENTIONS, not articles (P1)
//   u6  the price x coverage svg is drawn left to right under rtl; its label is keyed
//   n2  the Links / Sentiment / Sources caveats go through t()
//   n4  a language switch redraws those panels, the Trend and the form counts, no fetch
//       (the Trend's unit included), and When/Where/Who, Related, Competitive, Overview
//   n5  the locale's own separators: the label frame and the list frame
//   n6  the enlarge button names what a click does NOW
//   n7  the mind map is never drawn below its own scale on a narrow screen, and a map
//       drawn while its subtab is hidden opens centred once shown

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace: a `{}` in a default parameter would
  // otherwise truncate the slice to the signature alone (the recorded ooChart trap).
  let at = APP.indexOf("async function " + name + "(");
  if (at === -1) at = APP.indexOf("function " + name + "(");
  if (at === -1) return null;
  let i = APP.indexOf("(", at), depth = 0;
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
  return APP.slice(at, j);
}

// ---------------------------------------------------------------- the i18n engine
const LOCALES = path.join(__dirname, "..", "src", "static", "locales");
const TABLE = {};
function table(lang) {
  if (!TABLE[lang]) TABLE[lang] = JSON.parse(fs.readFileSync(path.join(LOCALES, lang + ".json"), "utf-8"));
  return TABLE[lang];
}
let LANG = "en";
const OOI18N = {
  t: (s) => { const v = table(LANG)[s]; return v == null ? s : v; },
  tf: (s, vars) => String(OOI18N.t(s)).replace(/\{(\w+)\}/g,
    (m, k) => (vars && vars[k] != null) ? String(vars[k]) : m),
  current: () => LANG,
};
const T = (lang, s) => { const v = table(lang)[s]; return v == null ? s : v; };

// ---------------------------------------------------------------- the sandbox
const NAMES = [
  // app-core
  "ooLabelHtml", "ooLabelText", "ooListJoin",
  // app-analysis
  "commodityOverlaySvg", "_anPriceHtml", "_anLensSuffix", "commoditiesForTerm",
  "renderAnTrend", "_anCtlLabel", "drawAnTrend", "renderAnMindmap",
  "_anLinksHtml", "_anSentimentHtml", "_anSourcesHtml", "_anSourceCatalogHtml",
  "_anRepaintOnLangChange", "_anFormCountsHtml", "_anFormCountsFailedHtml",
  "_anRefillFormSlots",
  // the panels a switch also redraws (the round-2 review of N-4)
  "_anWwwHtml", "_anRelatedHtml", "_anCompetitiveHtml", "_anOverviewHtml",
  // the entity spine's hover helpers _anWwwHtml calls (S05-03)
  "placeNameSourceText", "entityLadderHoverText", "placeUnresolvedText",
];
const found = NAMES.map((n) => [n, extract(n)]);
const MISSING = found.filter(([, s]) => !s).map(([n]) => n);

const src = [
  "function esc(s){return s==null?'':String(s).replace(/[&<>\"']/g,"
    + "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function fmtNum(x){return String(x);}",
  "function extLink(u, label){return '<a>' + label + '</a>';}",
  "function ooLangCell(v){return '<span>' + esc(String(v == null ? '' : v)) + '</span>';}",
  "function ooLangCode(v){return String(v).toUpperCase();}",
  "function anQuery(){return '';}",
  "function ooCountryCode(c){return String(c).toUpperCase();}",
  "function anRelUpdateSel(){H.selUpdated++;}",
  "function getComputedStyle(el){return {direction: el.dir || 'ltr'};}",
  // A ResizeObserver the test fires by hand: `cb` is the callback, `off` its disconnect.
  "function ResizeObserver(cb){const o = {cb, off: false, targets: [],"
    + " observe(el){o.targets.push(el);}, disconnect(){o.off = true;}}; H.ros.push(o); return o;}",
  "function $(id){return H.el[id] || null;}",
  "function api(u){H.api.push(u); return H.respond(u);}",
  "function ooChart(host, list, opts){H.charts.push({host, list, opts});}",
  "function _anRepaintArticles(){H.articlesRepainted++;}",
  "function _exploreSync(){}",   // Explore's note (R47), redrawn from state; tested in test_explore_merge.py
  "var _SPARSE_BAR_MAX = 10;",
  "var COMMODITY_QUERY = {WTI: 'crude oil'};",
  "var _anCommodity = null, _anExpand = true;",
  "var _anTrend = {key: null, term: null, counts: [], suggested: [], picked: {}, mode: 'counts',"
    + " byLang: null, concept: null, articles: null};",
  "var _anMM = {graph: null, gp: null, cloud: false, concept: false, arms: null, scale: 100, big: false};",
  "var _anPanelsLast = {}, _anFormCountsLast = {};",
  "var _anFacets = {who: [], where: [], when: []}, _anOverviewKey = null, _anOverviewLast = null;",
  ...found.filter(([, s]) => s).map(([, s]) => s),
  "module.exports = {" + found.filter(([, s]) => s).map(([n]) => n).join(", ")
    + ", state: () => ({_anTrend, _anMM, _anPanelsLast, _anFormCountsLast, _anFacets}),"
    + " setPanels: (v) => { _anPanelsLast = v; }, setForms: (v) => { _anFormCountsLast = v; },"
    + " setOverview: (k, v) => { _anOverviewKey = k; _anOverviewLast = v; } };",
].join("\n");

const H = { el: {}, api: [], charts: [], articlesRepainted: 0, selUpdated: 0, ros: [],
  respond: () => Promise.resolve(null) };
const DOC = { documentElement: { dir: "ltr" } };
const M = (() => {
  const m = { exports: {} };
  new Function("module", "exports", "window", "OOI18N", "document", "H", src)(
    m, m.exports, { OOI18N }, OOI18N, DOC, H);
  return m.exports;
})();

function el(extra) {
  return Object.assign({ innerHTML: "", offsetParent: {}, dataset: {},
    querySelector() { return null; }, querySelectorAll() { return []; } }, extra || {});
}
function reset(lang) {
  LANG = lang || "en"; DOC.documentElement.dir = LANG === "ar" ? "rtl" : "ltr";
  H.el = {}; H.api = []; H.charts = []; H.articlesRepainted = 0; H.selUpdated = 0; H.ros = [];
  H.respond = () => Promise.reject(new Error("no request was expected here"));
}
// The Trend host and the two children its render writes into (a stub host makes no
// children of its own from the innerHTML it is given).
function trendHosts(extra) {
  H.el["an-trend"] = el(extra);
  H.el["an-trend-chart"] = el();
  H.el["an-trend-dual"] = el();
}
// A host whose checkboxes and folds are REBUILT, unticked and closed, from every innerHTML
// it is given -- as a real DOM's are -- so a selection that survives a redraw was put back.
function rebuildingHost(extra) {
  let html = "", boxes = [], folds = [];
  const h = el(extra);
  Object.defineProperty(h, "innerHTML", {
    get: () => html,
    set: (v) => {
      html = v;
      boxes = [...v.matchAll(/class="an-rel-pick" data-kind="(\w)" data-idx="(\d+)"/g)]
        .map((m) => ({ checked: false, dataset: { kind: m[1], idx: m[2] } }));
      folds = [...v.matchAll(/<details/g)].map(() => ({ open: false }));
    },
  });
  h.querySelectorAll = (sel) => sel === ".an-rel-pick:checked" ? boxes.filter((b) => b.checked)
    : sel === ".an-rel-pick" ? boxes : sel === "details" ? folds : [];
  return h;
}
function need(...names) {
  const gone = names.filter((n) => MISSING.includes(n));
  assert.deepStrictEqual(gone, [], "not found in the app source -- renamed or never written: " + gone);
}

// The served caveats, handed in by the pytest wrapper (read out of the Python source
// with ast), so this suite drives the sentences the server actually sends.
const CAV = Object.assign({
  sentiment: "Tone is measured by VADER, an ENGLISH-lexicon method; scores for non-English "
    + "articles are unreliable (see the English share). Counts only, never a verdict.",
  sources: "Volume and timing are exact counts; mean tone is VADER (English-lexicon, "
    + "unreliable for non-English). No ranking and no verdict -- coverage, not credibility.",
  links: "Shared-origin structure, counts only. Several articles citing the SAME link are "
    + "not independent confirmation -- one origin, several echoes. Citing sources is the "
    + "count that bounds how many independent paths there could be; even distinct outlets "
    + "may still share an upstream origin this view cannot see.",
}, process.env.B24_CAVEATS ? JSON.parse(process.env.B24_CAVEATS) : {});

function needServed(...keys) {
  const gone = keys.filter((k) => !CAV[k]);
  assert.deepStrictEqual(gone, [], "run through tests/test_rewalk_b24_analysis.py, which hands in the served caveats: " + gone);
}
const WWW = { caveat: "", who: { entities: [{ name: "Kim", class: "person", articles: 2 }] },
  where: { places: [] }, when: { years: [{ year: 2024, articles: 8 }] } };
const SOURCES2 = { caveat: "", n_articles: 3, sources: [{ name: "A", articles: 2 }, { name: "B", articles: 1 }] };
const CLUSTERS = [{ size: 3, single_source: true, distinct_sources: 1, members: [], article_ids: [1, 2, 3] },
  { size: 2, single_source: false, distinct_sources: 2, members: [], article_ids: [4, 5] }];

const PRICES = [
  { observed_on: "2025-01-01", price: 289 }, { observed_on: "2025-02-01", price: 281.7 },
  { observed_on: "2025-03-01", price: 274.4 },
];
const VOL = [{ date: "2025-01-01", count: 22 }, { date: "2025-02-01", count: 4 }];
const svgTag = (html) => (html.match(/<svg[^>]*>/) || [""])[0];
const texts = (html) => [...html.matchAll(/<text([^>]*)>([^<]*)<\/text>/g)]
  .map((m) => ({ attrs: m[1], text: m[2] }));

// ---------------------------------------------------------------- the groups
const GROUPS = {};

// N-3 (P1). The trend endpoint's point `count` is SUM(KeywordMention.count), so the
// series unit is MENTIONS -- labelled "articles", a week holding 7 articles read "22".
GROUPS.n3 = async () => {
  for (const lang of ["en", "fr", "zh"]) {
    reset(lang);
    trendHosts();
    H.respond = (u) => Promise.resolve(u.startsWith("/api/insights/trend")
      ? { resolved: true, points: [{ date: "2026-09-21", count: 22 }], articles: 7 }
      : { nodes: [] });
    M.state()._anTrend.key = null;
    await M.renderAnTrend(new URLSearchParams("query=climate"));
    assert.strictEqual(H.charts.length, 1, "the Counts chart was not drawn");
    const [series] = H.charts[0].list;
    assert.strictEqual(series.unit, T(lang, "mentions"),
      `[${lang}] the Counts series is labelled ${JSON.stringify(series.unit)}, not mentions`);
    assert.notStrictEqual(series.unit, T(lang, "articles"));
    const html = H.el["an-trend"].innerHTML;
    assert.ok(html.includes(esc(T(lang, "Mention counts on a shared time axis."))),
      `[${lang}] the caption does not say the axis counts mentions`);
    assert.ok(!html.includes("Article counts on a shared time axis."),
      "the old caption, which called the same counts articles, is still drawn");
  }
  // The price x coverage panel plots the SAME sums: its coverage axis and its total say so.
  for (const lang of ["en", "fr"]) {
    reset(lang);
    const host = el();
    M._anPriceHtml(host, { name: "Dy", prices: PRICES, vol: VOL, unit: "USD/kg", total: 26 });
    const axis = texts(host.innerHTML).map((x) => x.text);
    assert.ok(axis.includes(esc(T(lang, "Mentions"))), `[${lang}] the coverage axis is not "Mentions": ${axis}`);
    assert.ok(!axis.includes(esc(T(lang, "Articles"))), `[${lang}] the coverage axis still says Articles`);
    assert.ok(host.innerHTML.includes(M.ooLabelHtml(esc(T(lang, "Mentions")), "26")),
      `[${lang}] the panel's total is not labelled as mentions`);
  }
};

// U-6. Under rtl an svg inherits the page direction, and every text-anchor flips: the
// price ticks at x = padL - 5 grew rightward over the first bar.
GROUPS.u6 = () => {
  reset("en");
  const en = M.commodityOverlaySvg(PRICES, VOL, "USD/kg");
  reset("ar");
  const ar = M.commodityOverlaySvg(PRICES, VOL, "USD/kg");
  for (const [lang, html] of [["en", en], ["ar", ar]]) {
    assert.ok(/style="[^"]*direction:\s*ltr/.test(svgTag(html)),
      `[${lang}] the chart svg does not pin direction:ltr, so rtl flips every anchor`);
    const frame = T(lang, "Price × coverage: {prices} price points, {coverage} coverage points");
    const aria = frame.replace("{prices}", "3").replace("{coverage}", "2");
    assert.ok(svgTag(html).includes(`aria-label="${esc(aria)}"`),
      `[${lang}] the aria-label is not the keyed frame: ${svgTag(html)}`);
  }
  assert.ok(!/\bprice,|\bcoverage\b/.test((svgTag(ar).match(/aria-label="([^"]*)"/) || ["", ""])[1]),
    "the Arabic aria-label still carries English words");
  // The axis TITLES are words: each keeps the reader's direction and the mirrored
  // anchor, which lands it where it sits in English.
  const title = (html, word) => texts(html).find((x) => x.text.startsWith(esc(word)));
  const pe = title(en, T("en", "Price")), pa = title(ar, T("ar", "Price"));
  const me = title(en, T("en", "Mentions")), ma = title(ar, T("ar", "Mentions"));
  assert.ok(pe && pa && me && ma, "an axis title is missing");
  assert.ok(/text-anchor="start"/.test(pe.attrs) && !/direction=/.test(pe.attrs));
  assert.ok(/text-anchor="end"/.test(me.attrs) && !/direction=/.test(me.attrs));
  assert.ok(/direction="rtl"/.test(pa.attrs) && /text-anchor="end"/.test(pa.attrs),
    "the Arabic price title does not keep its own direction with the mirrored anchor");
  assert.ok(/direction="rtl"/.test(ma.attrs) && /text-anchor="start"/.test(ma.attrs));
  // The numeric ticks are identical in both: the svg's own ltr gives them one meaning.
  const ticks = (html) => texts(html).filter((x) => /^[\d.]+$/.test(x.text)).map((x) => x.attrs);
  assert.deepStrictEqual(ticks(ar), ticks(en), "the tick labels are drawn differently under rtl");
};

// N-2. Fixed server sentences, keyed x12 -- drawn verbatim they read English everywhere.
GROUPS.n2 = () => {
  need("_anLinksHtml", "_anSentimentHtml", "_anSourcesHtml", "_anWwwHtml", "_anRelatedHtml",
    "_anCompetitiveHtml");
  needServed("www", "coordination", "coordination method", "framing");
  for (const lang of ["fr", "zh", "ar", "ja"]) {
    reset(lang);
    const cases = [
      ["links", M._anLinksHtml({ caveat: CAV.links, items: [] })],
      ["sentiment", M._anSentimentHtml({ caveat: CAV.sentiment, n_scored: 0 })],
      ["sentiment", M._anSentimentHtml({ caveat: CAV.sentiment, n_scored: 4, n_articles: 5,
        english_scored: 2, mean_score: -0.2, labels: { positive: 1, negative: 3 } })],
      ["sources", M._anSourcesHtml({ caveat: CAV.sources, sources: [] })],
      // When/Where/Who, the Related tab's method line and caveat, and the Competitive tab,
      // which draws /api/framing's own sentence beside the sources one (the round-2 review).
      ["www", M._anWwwHtml(Object.assign({}, WWW, { caveat: CAV.www }))],
      ["coordination", M._anRelatedHtml({ caveat: CAV.coordination, method: CAV["coordination method"],
        clusters: CLUSTERS }, { items: [] })],
      ["coordination method", M._anRelatedHtml({ caveat: "", method: CAV["coordination method"],
        clusters: [] }, { items: [] })],
      ["sources", M._anCompetitiveHtml(Object.assign({}, SOURCES2, { caveat: CAV.sources }),
        { caveat: CAV.framing, framing: [] }, "climate")],
      ["framing", M._anCompetitiveHtml(Object.assign({}, SOURCES2, { caveat: CAV.sources }),
        { caveat: CAV.framing, framing: [] }, "climate")],
    ];
    for (const [k, html] of cases) {
      const tr = T(lang, CAV[k]);
      assert.notStrictEqual(tr, CAV[k], `[${lang}] the ${k} caveat has no translation`);
      assert.ok(html.includes(esc(tr)), `[${lang}] the ${k} caveat is not drawn through t()`);
      assert.ok(!html.includes(esc(CAV[k])), `[${lang}] the ${k} caveat is drawn in English`);
    }
  }
};

// N-4. The switch redraws from what each panel already holds, and asks for nothing.
GROUPS.n4 = async () => {
  need("_anRepaintOnLangChange", "_anRefillFormSlots");
  reset("en");
  const S = M.state();
  M.setPanels({ links: { caveat: CAV.links, items: [] },
                sentiment: { caveat: CAV.sentiment, n_scored: 0 },
                sources: { caveat: CAV.sources, sources: [] } });
  S._anTrend.counts = [{ label: "climate", unitKey: "mentions", points: [{ t: "2026-09-21", v: 22 }] }];
  S._anTrend.mode = "counts"; S._anTrend.picked = {}; S._anTrend.byLang = null;
  reset("fr");
  for (const id of ["an-links", "an-sentiment", "an-sources"]) H.el[id] = el({ innerHTML: "EN" });
  trendHosts({ innerHTML: "EN" });
  M._anRepaintOnLangChange();
  assert.deepStrictEqual(H.api, [], "a language switch sent a request");
  assert.strictEqual(H.articlesRepainted, 1, "the Articles list is not redrawn on a switch");
  assert.ok(H.el["an-links"].innerHTML.includes(esc(T("fr", CAV.links))));
  assert.ok(H.el["an-sentiment"].innerHTML.includes(esc(T("fr", CAV.sentiment))));
  assert.ok(H.el["an-sources"].innerHTML.includes(esc(T("fr", CAV.sources))));
  assert.ok(H.el["an-trend"].innerHTML.includes(esc(T("fr", "Mention counts on a shared time axis."))),
    "an open Trend chart kept its first language");
  assert.strictEqual(H.charts.length, 1);
  // A hidden Trend redraws itself when its subtab is next opened -- never measured hidden.
  reset("ar");
  trendHosts({ innerHTML: "FR", offsetParent: null });
  M._anRepaintOnLangChange();
  assert.strictEqual(H.el["an-trend"].innerHTML, "FR", "a hidden Trend chart was redrawn");
  // A panel never drawn (still loading, or failed) is left as it is.
  M.setPanels({});
  H.el["an-links"] = el({ innerHTML: "Loading…" });
  M._anRepaintOnLangChange();
  assert.strictEqual(H.el["an-links"].innerHTML, "Loading…");
  // The per-form counts: every redraw of the rail made each slot anew and EMPTY.
  reset("fr");
  M.setForms({ "an-xforms-climate": { forms: [{ form: "climat", articles: 3 }], total: 3 },
               "an-xforms-strom": null, "an-xforms-kept": { forms: [] } });
  H.el["an-xforms-climate"] = el();
  H.el["an-xforms-strom"] = el();
  H.el["an-xforms-kept"] = el({ innerHTML: "…" });
  M._anRefillFormSlots();
  assert.ok(H.el["an-xforms-climate"].innerHTML.includes("climat <b>3</b>"),
    "the counts the reader asked for were not put back");
  assert.ok(H.el["an-xforms-strom"].innerHTML.includes(esc(T("fr", "The forms could not be counted."))),
    "a failed count came back as an empty slot, which reads as nothing to count");
  assert.strictEqual(H.el["an-xforms-kept"].innerHTML, "…", "a slot already showing something was overwritten");
  assert.deepStrictEqual(H.api, []);

  // THE TREND'S UNIT follows the switch too (the round-2 review): fetched in English, then
  // redrawn in Chinese, the legend, the hover and the data table name it in Chinese.
  reset("en");
  trendHosts();
  H.respond = (u) => Promise.resolve(u.startsWith("/api/insights/trend")
    ? { resolved: true, points: [{ date: "2026-09-21", count: 22 }], articles: 7 }
    : { nodes: [] });
  S._anTrend.key = null;
  await M.renderAnTrend(new URLSearchParams("query=climate"));
  assert.strictEqual(H.charts[0].list[0].unit, T("en", "mentions"));
  reset("zh");
  trendHosts({ innerHTML: "EN" });
  M._anRepaintOnLangChange();
  assert.deepStrictEqual(H.api, [], "a language switch sent a request");
  assert.notStrictEqual(T("zh", "mentions"), "mentions", "the zh table has no word for mentions");
  assert.strictEqual(H.charts.length, 1);
  assert.strictEqual(H.charts[0].list[0].unit, T("zh", "mentions"),
    "the charted unit stayed in the language the trend was fetched in");
  assert.strictEqual(S._anTrend.counts[0].unit, undefined,
    "the retained series holds a translation, which the next switch cannot undo");
  need("_anWwwHtml", "_anRelatedHtml", "_anCompetitiveHtml", "_anOverviewHtml");
  needServed("www", "coordination", "framing");

  // When/Where/Who, Related, Competitive and the Overview tiles: every panel the window
  // composes at render time redraws from what it holds, and asks for nothing.
  reset("en");
  M.setPanels({
    www: Object.assign({}, WWW, { caveat: CAV.www }),
    related: { cd: { caveat: CAV.coordination, method: CAV["coordination method"], clusters: CLUSTERS },
               ld: { caveat: CAV.links, items: [] } },
    competitive: { cs: Object.assign({}, SOURCES2, { caveat: CAV.sources }),
                   fr: { caveat: CAV.framing, framing: [] }, query: "climate" },
  });
  const OV = { key: "k1", kw: { terms: [{ term: "climate" }] }, www: null, src: null, sent: null };
  M.setOverview("k1", OV);
  const rel = rebuildingHost({ dataset: { done: "1" } });
  rel.innerHTML = M._anRelatedHtml(M.state()._anPanelsLast.related.cd, M.state()._anPanelsLast.related.ld);
  rel.querySelectorAll(".an-rel-pick").find((b) => b.dataset.kind === "c" && b.dataset.idx === "1").checked = true;
  rel.querySelectorAll("details")[0].open = true;
  reset("zh");
  H.el["an-www"] = el({ innerHTML: "EN" });
  H.el["an-competitive"] = el({ innerHTML: "EN" });
  H.el["an-overview"] = el({ innerHTML: "EN", dataset: { done: "1" } });
  H.el["an-related"] = rel;
  M._anRepaintOnLangChange();
  assert.deepStrictEqual(H.api, [], "a language switch sent a request");
  const www = H.el["an-www"].innerHTML;
  assert.ok(www.includes(esc(T("zh", CAV.www))), "When/Where/Who kept its caveat in English");
  assert.ok(www.includes(esc(T("zh", "Who"))) && www.includes("branchByFacet('who',0)"));
  assert.strictEqual(M.state()._anFacets.who[0].value, "Kim", "the facet the drill reads was not rebuilt");
  const comp = H.el["an-competitive"].innerHTML;
  assert.ok(comp.includes(esc(T("zh", CAV.framing))), "the framing caveat stayed in English");
  assert.ok(comp.includes(esc(T("zh", "Volume"))), "the Competitive headers stayed in English");
  const ov = H.el["an-overview"].innerHTML;
  assert.ok(ov.includes(esc(T("zh", "Open"))) && !ov.includes(">Open "), "the Overview tiles kept \"Open\"");
  const rh = rel.innerHTML;
  assert.ok(rh.includes(esc(T("zh", CAV.coordination))), "the Related caveat stayed in English");
  assert.ok(rh.includes(esc(T("zh", CAV["coordination method"]))), "the Related method line stayed in English");
  const ticked = rel.querySelectorAll(".an-rel-pick:checked").map((b) => b.dataset.kind + b.dataset.idx);
  assert.deepStrictEqual(ticked, ["c1"], "a switch dropped the reader's selection for branching");
  assert.deepStrictEqual(rel.querySelectorAll("details").map((d) => d.open), [true, false],
    "a switch folded what the reader had unfolded");
  assert.strictEqual(H.selUpdated, 1, "the selected-count line is not redrawn in the new language");
  // Not drawn, or drawn for another corpus: left as it is.
  reset("fr");
  M.setOverview("k2", OV);   // the Overview now belongs to another corpus
  H.el["an-overview"] = el({ innerHTML: "ZH", dataset: { done: "1" } });
  H.el["an-related"] = el({ innerHTML: "Loading…", dataset: { done: "" } });
  M._anRepaintOnLangChange();
  assert.strictEqual(H.el["an-overview"].innerHTML, "ZH", "an Overview for another corpus was painted over");
  assert.strictEqual(H.el["an-related"].innerHTML, "Loading…", "a Related tab still loading was painted over");
};

// N-5. The reader's own separators, through keyed frames every locale states once.
GROUPS.n5 = () => {
  need("ooListJoin", "_anCtlLabel");
  const cases = { en: "a, b, c", fr: "a, b, c", zh: "a、b、c", ja: "a、b、c", ar: "a، b، c" };
  for (const [lang, want] of Object.entries(cases)) {
    reset(lang);
    assert.strictEqual(M.ooListJoin(["a", "b", "c"]), want, `[${lang}] list punctuation`);
  }
  reset("zh");
  assert.strictEqual(M.ooListJoin(["$&", "x"]), "$&、x", "an item is read as a replacement pattern");
  assert.strictEqual(M.ooListJoin(["solo"]), "solo");
  assert.strictEqual(M.ooListJoin([]), "");
  for (const lang of ["fr", "zh", "ar"]) {
    reset(lang);
    const label = T(lang, "View");
    const got = M._anCtlLabel(label);
    const want = T(lang, "{prefix}: {text}").replace("{prefix}", label).replace("{text}", "").trim();
    assert.ok(got.includes(`>${esc(want)}<`), `[${lang}] ${got} is not the locale's own label frame`);
    if (lang !== "ar") assert.ok(!got.includes(esc(label) + ":"), `[${lang}] an English colon is welded`);
  }
  // The Sentiment line's two labels, and the Trend controls, drawn whole.
  reset("fr");
  const sent = M._anSentimentHtml({ caveat: "", n_scored: 4, n_articles: 5, english_scored: 2,
    mean_score: -0.2, labels: { negative: 4 } });
  for (const k of ["Mean tone", "English-scored (reliable)"]) {
    assert.ok(!sent.includes(esc(T("fr", k)) + ":"), `the fr "${k}" label welds an English colon`);
    assert.ok(sent.includes(esc(T("fr", k)) + " :"), `the fr "${k}" label lost its separator`);
  }
  reset("zh");
  const S = M.state();
  S._anTrend.counts = [{ label: "climate", unitKey: "mentions", points: [{ t: "2026-09-21", v: 22 }] }];
  S._anTrend.mode = "counts"; S._anTrend.picked = {}; S._anTrend.suggested = []; S._anTrend.byLang = null;
  trendHosts();
  M.drawAnTrend();
  const tr = H.el["an-trend"].innerHTML;
  for (const k of ["View", "Overlay a commodity"]) {
    assert.ok(tr.includes(esc(T("zh", k)) + "："), `the zh "${k}" control lost its full-width colon`);
    assert.ok(!tr.includes(esc(T("zh", k)) + ":"), `the zh "${k}" control welds an English colon`);
  }
};

// N-6 / N-7 share the mind map's renderer.
function mindmap(big, nodes) {
  const S = M.state();
  S._anMM.big = big; S._anMM.cloud = false; S._anMM.concept = false; S._anMM.arms = null;
  const host = el();
  M.renderAnMindmap({ nodes }, host);
  return host.innerHTML;
}
const ONE = [{ id: "climate", label: "climate", center: true, size: 5 }];
const THREE = ONE.concat([{ id: "carbon", label: "carbon", size: 3 }, { id: "heat", label: "heat", size: 2 }]);

GROUPS.n6 = () => {
  for (const lang of ["en", "fr"]) {
    reset(lang);
    for (const [big, key, pressed] of [[false, "Enlarge the mindmap", "false"], [true, "Shrink the mindmap", "true"]]) {
      const html = mindmap(big, ONE);
      const btn = (html.match(/<button[^>]*>⛶<\/button>/) || [""])[0];
      assert.ok(btn, "the ⛶ button is gone");
      assert.ok(btn.includes(`title="${esc(T(lang, key))}"`),
        `[${lang}] big=${big}: the hover does not name what a click does now: ${btn}`);
      assert.ok(btn.includes(`aria-pressed="${pressed}"`), `[${lang}] big=${big}: no pressed state`);
    }
  }
};

GROUPS.n7 = () => {
  reset("en");
  for (const [big, w] of [[false, 680], [true, 1100]]) {
    const html = mindmap(big, THREE);
    const svg = svgTag(html);
    assert.ok(svg.includes(`min-width:${w}px`),
      `big=${big}: the map can be drawn below its own scale (labels of 5-7 px at 375 px): ${svg}`);
    assert.ok(/<div class="an-mm-box[^"]*" style="overflow:auto;max-width:100%/.test(html),
      `big=${big}: the map has no box of its own to scroll in`);
  }
  // DRAWN WHILE ITS SUBTAB IS HIDDEN (the round-2 review): `loadAnalysis` draws the Map
  // behind whichever tab is open, where the box measures 0 and nothing can be centred.
  const S = M.state();
  const box = (dir) => ({ dir, clientWidth: 0, scrollWidth: 0, clientHeight: 0, scrollHeight: 0,
    scrollLeft: 0, scrollTop: 0 });
  const show = (b) => Object.assign(b, { clientWidth: 301, scrollWidth: 680, clientHeight: 460, scrollHeight: 460 });
  const draw = (b) => {
    S._anMM.big = false; S._anMM.cloud = false; S._anMM.concept = false; S._anMM.arms = null;
    M.renderAnMindmap({ nodes: THREE }, el({ querySelector: (sel) => (sel === ".an-mm-box" ? b : null) }));
  };
  for (const [dir, sign] of [["ltr", 1], ["rtl", -1]]) {
    reset(dir === "rtl" ? "ar" : "en");
    const b = box(dir);
    draw(b);
    assert.strictEqual(b.scrollLeft, 0);
    assert.strictEqual(H.ros.length, 1, `[${dir}] a map drawn hidden does not wait for a width to centre in`);
    H.ros[0].cb();                        // still hidden: a resize to nothing changes nothing
    assert.ok(!H.ros[0].off && b.scrollLeft === 0);
    show(b); H.ros[0].cb();               // the reader opens the subtab
    assert.strictEqual(b.scrollLeft, sign * (680 - 301) / 2, `[${dir}] the map did not open on its centre`);
    assert.ok(H.ros[0].off, `[${dir}] the wait is not one-shot, so it would undo the reader's own scroll`);
  }
  // Shown already: centred at once, with nothing left waiting.
  reset("en");
  const vis = show(box("ltr"));
  draw(vis);
  assert.strictEqual(vis.scrollLeft, (680 - 301) / 2);
  assert.strictEqual(H.ros.length, 0);
  // Redrawn while still hidden (a language switch re-fetches it): the older wait is dropped.
  draw(box("ltr")); draw(box("ltr"));
  assert.strictEqual(H.ros.length, 2);
  assert.ok(H.ros[0].off && !H.ros[1].off, "a replaced map's wait is left running");
  assert.strictEqual(S._anMM.ro, H.ros[1]);
};

function esc(s) {
  return s == null ? "" : String(s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
}

(async () => {
  const want = process.argv.slice(2);
  const run = want.length ? want : Object.keys(GROUPS);
  for (const g of run) {
    assert.ok(GROUPS[g], "no such group: " + g);
    await GROUPS[g]();
    console.log("ok " + g);
  }
  console.log("rewalk_b24_node_test: all assertions passed");
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
