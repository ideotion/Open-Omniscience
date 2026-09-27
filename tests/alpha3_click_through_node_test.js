// The 2026-09-26 click-through's row L (alpha-3 codes everywhere) -- run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Each defect gets its own check, and every check runs even when another fails, so a
// run against the unfixed tree names EACH defect it would have caught rather than
// stopping at the first. The functions are extracted from the shipped modules by name
// (never re-typed: a copy would agree with a broken original), and only the platform
// (Intl, the DOM, the network) is stubbed.
//
// The Intl stub is a small ENGLISH name table rather than an echo, because two of the
// defects are about ORDER and about what a filter MATCHES, and an echo would sort and
// match by code -- which is exactly the behaviour the unfixed code had.

"use strict";

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function span(name) {
  let at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  if (APP.slice(at - 6, at) === "async ") at -= 6;
  const open = APP.indexOf("{", APP.indexOf(")", at));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j);
}

function constSpan(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const end = APP.indexOf("`;", at);
  return APP.slice(at, end + 2);
}

function line(prefix) {
  const at = APP.indexOf(prefix);
  assert.ok(at !== -1, prefix + " not found");
  return APP.slice(at, APP.indexOf("\n", at));
}

// Names as the browser's CLDR would give them in ENGLISH, for the codes these checks use.
const EN = {
  fr: "France", de: "Germany", eg: "Egypt", es: "Spain", kr: "South Korea",
  us: "United States", gb: "United Kingdom", cn: "China", xk: "Kosovo", "001": "World",
};

const HELPERS = [
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g," +
    "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function ooRegionName(code, fallback){ const n = NAMES[String(code).toLowerCase()];" +
    " return n || (fallback == null ? '' : fallback); }",
  "function ooLangName(code, fallback){ return fallback == null ? '' : fallback; }",
  constSpan("_OO_ISO3_TO_2_TEXT"),
  "const OO_ISO3_TO_ISO2 = {}; const OO_ISO2_TO_ISO3 = {};",
  "_OO_ISO3_TO_2_TEXT.split(/\\s+/).forEach((p)=>{if(!p)return;const[a,b]=p.split(':');" +
    "if(!a||!b)return;OO_ISO3_TO_ISO2[a]=b;OO_ISO2_TO_ISO3[b]=a;});",
  constSpan("_OO_ISO1_TO_3_TEXT"),
  "const OO_LANG1_TO_3 = {}; const OO_LANG3_TO_1 = {};",
  "_OO_ISO1_TO_3_TEXT.split(/\\s+/).forEach((p)=>{if(!p)return;const[a,b]=p.split(':');" +
    "if(!a||!b)return;OO_LANG1_TO_3[a]=b;OO_LANG3_TO_1[b]=a;});",
  APP.slice(APP.indexOf("const OO_SPECIAL_ALPHA3 = "),
            APP.indexOf("\n", APP.indexOf("const OO_CLDR_WRONG_ABOUT = "))),
  ...["ooCountryAlpha2", "ooCountryCode", "ooCountryKind", "ooCountryName", "ooCountryTitle",
      "ooCountryCell", "ooCountryCompare", "ooLangBase", "ooLangCode", "ooLangStorage",
      "ooLangDisplayName", "ooLangCell"].map(span),
].join("\n") + "\n";

// Build a sandbox holding the helpers plus the named functions, and hand back `pick`.
// `pre` declares whatever module state the functions close over.
function build(fnNames, pre, pick, env) {
  const body = "const {NAMES, window, OOI18N, $, api} = ENV;\n" + (pre || "") + "\n" + HELPERS +
    fnNames.map(span).join("\n") + "\nreturn {" + pick + "};";
  return new Function("ENV", body)(Object.assign({NAMES: EN, window: {}, OOI18N: undefined,
    $: () => null, api: async () => ({})}, env || {}));
}

// A marked i18n engine: `t` and `tf` wrap what they were handed, so a check can tell a
// string that went through a keyed frame from one welded out of English literals.
const MARKED = {
  t: (s) => "T[" + s + "]",
  tf: (s, v) => "TF[" + s + "]" + JSON.stringify(v),
  current: () => "en",
};

// A fake <details class="msel"> with a checklist, enough for mselValues/fill/summary.
function fakeMsel(checked) {
  const summary = {textContent: ""};
  const list = {
    html: "", checked: checked.slice(),
    set innerHTML(v) { this.html = v; }, get innerHTML() { return this.html; },
    querySelectorAll() { return this.checked.map((value) => ({value})); },
  };
  return {summary, list, querySelector: (sel) => (sel === "summary" ? summary : list)};
}

const failures = [];
async function check(id, what, fn) {
  try { await fn(); console.log("ok  " + id + "  " + what); }
  catch (e) { failures.push(id); console.log("FAIL " + id + "  " + what + "\n     " + (e && e.message)); }
}

(async () => {
  await check("L9/L13", "a published aggregate is disclosed as one, a country keeps code + name", () => {
    const F = build(["ooAreaCell"], "", "ooAreaCell");
    const wld = F.ooAreaCell("WLD", "aggregate", "World");
    assert.ok(/>WLD</.test(wld), "the aggregate's CODE stays visible: " + wld);
    assert.ok(/title="World — published aggregate"/.test(wld), "the hover discloses it: " + wld);
    assert.ok(!/not a recognised/.test(wld), "an aggregate is not an unreadable code: " + wld);
    // "World" is a KEYED string: a Chromium without CLDR region data answers M49 `001`
    // with `001`, which is what the first version of this fix put in the hover.
    const M = build(["ooAreaCell"], "", "ooAreaCell", {window: {OOI18N: MARKED}, OOI18N: MARKED});
    const wldT = M.ooAreaCell("WLD", "aggregate", "World");
    assert.ok(/title="T\[World\] — T\[published aggregate\]"/.test(wldT), wldT);
    const hic = F.ooAreaCell("HIC", "aggregate", "High income");
    assert.ok(/title="High income — published aggregate"/.test(hic), hic);
    const us = F.ooAreaCell("US", "country", null);
    assert.ok(/>USA</.test(us) && /title="United States"/.test(us), "a country is the ordinary cell: " + us);
    // No classification (an older payload) is the country cell, never a guess.
    assert.ok(/>FRA</.test(F.ooAreaCell("fr")), "an unclassified area falls back to the country cell");
  });

  await check("L16", "the worldview picker reads Name (CODE), ordered by name after the conventions", () => {
    const F = build(["_ooWorldviewLabel", "_ooWorldviewOrder"], line("const _OO_POV_REGION = "),
      "_ooWorldviewLabel, _ooWorldviewOrder");
    assert.deepStrictEqual(F._ooWorldviewOrder(["de", "iso", "eg", "tlc", "es", "ko"]),
      ["contested", "iso", "tlc", "eg", "de", "ko", "es"]);
    assert.strictEqual(F._ooWorldviewLabel("de"), "Germany (DEU)");
    // KO is the viewpoint key; the country is KR, so the code must come AFTER the mapping.
    assert.strictEqual(F._ooWorldviewLabel("ko"), "South Korea (KOR)");
  });

  await check("L7", "a closed filter with one value shows the code the list beside it shows", () => {
    const dets = {"src-msel-country": fakeMsel(["fr"]), "src-msel-language": fakeMsel(["fr"]),
                  "src-msel-tag": fakeMsel(["energy"])};
    const F = build(["mselValues", "updateMselSummary"], "", "updateMselSummary",
      {$: (id) => dets[id] || null});
    Object.keys(dets).forEach(F.updateMselSummary);
    assert.strictEqual(dets["src-msel-country"].summary.textContent, "FRA");
    assert.strictEqual(dets["src-msel-language"].summary.textContent, "fra");
    assert.strictEqual(dets["src-msel-tag"].summary.textContent, "energy", "a tag is not a code");
  });

  await check("L3", "re-filling the facet lists keeps what is ticked", async () => {
    const dets = {"src-msel-country": fakeMsel(["fr"]), "src-msel-language": fakeMsel([]),
                  "src-msel-source_type": fakeMsel([]), "src-msel-tag": fakeMsel([])};
    const facets = {countries: [{key: "de", n: 3}, {key: "fr", n: 5}], languages: [{key: "fr", n: 5}],
                    types: [], tags: []};
    const F = build(["mselValues", "updateMselSummary", "loadSrcFacets"], "", "loadSrcFacets",
      {$: (id) => dets[id] || null, api: async () => facets});
    await F.loadSrcFacets();
    const html = dets["src-msel-country"].list.html;
    assert.ok(/value="fr" checked/.test(html), "the ticked country must survive the re-fill: " + html);
    assert.ok(!/value="de" checked/.test(html), "and nothing else becomes ticked: " + html);
    assert.strictEqual(dets["src-msel-country"].summary.textContent, "FRA",
      "the label must not reset to Any over a table still filtered to France");
  });

  // renderCoverageTable, fed a row per case the defect named.
  const covEnv = (q, names) => {
    const els = {"cov-filter": {value: q}, "coverage-table": {innerHTML: ""}, "coverage-gaps": {innerHTML: ""}};
    const F = build(["renderCoverageTable"],
      "let COV_COUNTRIES = [" +
      "{code:'de',name:'Germany',region:'Europe',sources:4,enabled:4,top_tags:[['energy',2]]}," +
      "{code:'fr',name:'France',region:'Europe',sources:5,enabled:5,top_tags:[]}," +
      "{code:'(none)',name:'',region:'',sources:2,enabled:2,top_tags:[['news',2]]}];" +
      "let COV_MISSING = [{code:'eg',name:'Egypt'}];",
      "renderCoverageTable", {$: (id) => els[id], NAMES: names || EN});
    F.renderCoverageTable();
    return els;
  };

  await check("L11", "the coverage filter matches the alpha-3 on screen and the localised name", () => {
    const deu = covEnv("DEU")["coverage-table"].innerHTML;
    assert.ok(/>DEU</.test(deu) && !/No matching countries/.test(deu), "DEU must find Germany: " + deu);
    // A French UI names Germany "Allemagne"; the server's name is English.
    const fr = Object.assign({}, EN, {de: "Allemagne", eg: "Égypte"});
    const all = covEnv("allemagne", fr)["coverage-table"].innerHTML;
    assert.ok(/>DEU</.test(all), "the localised name must match: " + all);
    const gaps = covEnv("EGY")["coverage-gaps"].innerHTML;
    assert.ok(/>EGY</.test(gaps), "the not-covered list filters the same way: " + gaps);
  });

  await check("L11", "the no-country rollup row reads as absent, not as an unreadable code", () => {
    const html = covEnv("")["coverage-table"].innerHTML;
    assert.ok(/no country recorded/.test(html), "the (none) row must say so: " + html);
    assert.ok(!/not a recognised country code/.test(html), "(none) is not junk: " + html);
  });

  await check("L17", "the regional balance names the top country by code, in keyed frames", () => {
    const host = {innerHTML: ""};
    // The label goes through ooLabelHtml since the 2026-09-27 re-walk (O-5), which fills
    // its frame with control-character markers; this engine keeps them raw (MARKED's
    // JSON.stringify would escape them away and drop the label).
    const RAW = {t: MARKED.t, current: MARKED.current,
      tf: (s, v) => "TF[" + s + "]" + Object.keys(v || {}).map((k) => k + "=" + v[k]).join(",")};
    const F = build(["ooLabelHtml", "renderCoverageRegions"], "function _regionFloorBars(){ return ''; }",
      "renderCoverageRegions", {$: () => host, window: {OOI18N: RAW}, OOI18N: RAW});
    F.renderCoverageRegions({regional: {
      regions: [{region: "Europe", sources: 9, countries_total: 2, countries_covered: 2}],
      top_country: {code: "de", sources: 4, share_pct: 44, max_share_pct: 30},
      located_share_pct: 80, min_located_share_pct: 50,
    }});
    const h = host.innerHTML;
    assert.ok(/>DEU</.test(h), "the top country's CODE is on screen: " + h);
    assert.ok(!/>Germany</.test(h), "the server's English name is no longer the text: " + h);
    assert.ok(h.includes("T[Top country]") && h.includes("TF[{prefix}: {text}]"),
      "the top-country label takes the reader's separator: " + h);
    for (const k of ["{n} sources, {pct}% of located", "above the {pct}% guard",
                     "{pct}% of sources carry a country", "floor {pct}%"]) {
      assert.ok(h.includes(k + "]"), "this part of the line is not keyed: " + k + " in " + h);
    }
  });

  await check("L17", "the unanalysable-languages line is a keyed frame with 639-2/T codes", async () => {
    const els = {"unmanaged-lang-panel": {style: {}}, "unmanaged-lang-summary": {innerHTML: ""}};
    const F = build(["loadUnmanagedLanguages"], "", "loadUnmanagedLanguages",
      {$: (id) => els[id], window: {OOI18N: MARKED}, OOI18N: MARKED,
       api: async () => ({enabled_unmanaged: 3, by_language: {sw: 2, am: 1}})});
    await F.loadUnmanagedLanguages();
    const h = els["unmanaged-lang-summary"].innerHTML;
    // esc()'d on the way into innerHTML, so the apostrophe arrives as an entity.
    assert.ok(h.includes("TF[{n} enabled source(s) in languages we can&#39;t analyse yet:]"), h);
    assert.ok(/>swa</.test(h) && />amh</.test(h), "the languages are 639-2/T codes: " + h);
  });

  await check("L17", "a sorted column's label stays its own text node", () => {
    const F = build(["srcTh"], "const SRC = {sort: 'name', order: 'asc'};", "srcTh");
    assert.ok(/<span>Name<\/span> ▲/.test(F.srcTh("Name", "name")), F.srcTh("Name", "name"));
  });

  await check("L6", "a law-change title hovers the jurisdiction's name", () => {
    const F = build(["cardTitleTip"], "", "cardTitleTip");
    assert.strictEqual(F.cardTitleTip({signal: {jurisdiction: "GBR"}}), ' title="United Kingdom"');
    assert.strictEqual(F.cardTitleTip({signal: {jurisdiction: "XKX"}}), ' title="Kosovo — not an ISO code"');
    assert.strictEqual(F.cardTitleTip({signal: {jurisdiction: "—"}}), "");
    assert.strictEqual(F.cardTitleTip({signal: {}}), "");
  });

  if (failures.length) {
    console.log("alpha3_click_through_node_test.js: FAILED " + failures.join(", "));
    process.exit(1);
  }
  console.log("alpha3_click_through_node_test.js: OK");
})();
