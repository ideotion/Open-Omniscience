// The 2026-09-27 click-through's data-surface tail (batch B18), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What a source-level check cannot see: whether a count reaches the translator as ONE
// frame chosen by its number (a "1 200 imported" welded an English-ordered adjective to
// a figure), whether a number inside a sentence is isolated, and whether a surface drawn
// in one language is drawn again in the next WITHOUT a second request. A MARKING
// translator ("«fr:…»") shows every string that went through it, and which language it
// went through in, so one that skipped it -- or kept the old language -- is visible.
// Every function is EXTRACTED from the shipped modules, never re-typed.

"use strict";

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
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
// A top-level `const`/`let` statement, sliced up to the declaration that follows it.
function slice(from, to) {
  const a = APP.indexOf(from), b = APP.indexOf(to, a);
  assert.ok(a !== -1 && b !== -1, "could not slice " + from);
  return APP.slice(a, b);
}

// The marking translator, switchable, so a stale surface shows its old language.
const I18N = {
  lang: "fr",
  t(s) { return "«" + I18N.lang + ":" + s + "»"; },
  tf(s, v) { return I18N.t(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)); },
  current() { return "en"; },
};
const FSI = "⁨", PDI = "⁩", NBSP = " ";

// The DOM this batch's renderers write into: boxes and inputs by id.
const BOXES = {};
function $(id) {
  if (!BOXES[id]) BOXES[id] = { id, innerHTML: "", value: "", textContent: "" };
  return BOXES[id];
}
let API_CALLS = [];
const API_ANSWERS = {};
async function api(path) {
  API_CALLS.push(path);
  const key = Object.keys(API_ANSWERS).find((k) => path.startsWith(k));
  if (!key) throw new Error("unexpected request " + path);
  return JSON.parse(JSON.stringify(API_ANSWERS[key]));
}

const src = [
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function ooCountryCell(v){return '<span>' + esc(v) + '</span>';}",
  extract("fmtNum"),
  extract("fmtDateTime"),
  extract("ooAreaCell"),
  // app-backup: the per-item table and the already-merged line (R9, R11)
  slice("const _UX_OUTCOME = {", "function _uxOutcome"),
  extract("_uxOutcome"),
  extract("_uxDurIso"),
  extract("_uxDurTf"),
  extract("_uxFmtS"),
  extract("_uxFmtDur"),
  extract("_uxMergedLine"),
  extract("_uxPerItemView"),
  slice("const _OO_SPACE_WHAT = {", "function ooServerText("),
  extract("ooServerText"),
  extract("_sizeText"),
  // app-map: the counts with their nouns (R14) and the statistics tables (R7, R8)
  extract("_mapTf"),
  extract("_ooMapCount"),
  extract("_ooOsmCounts"),
  extract("_dumpScanned"),
  extract("_dumpSecs"),
  extract("_dumpPages"),
  extract("_statfigFmt"),
  extract("_statAreaLocal"),
  slice("let _statFigLast = null", "function _statIso"),
  extract("_statIso"),
  "async " + extract("loadStatFigures"),   // extract() starts at the keyword `function`
  "async " + extract("loadRevisionAnomalies"),   // extract() starts at the keyword `function`
  extract("repaintStatTablesFromCache"),
  // app-gov-law: the catalogue's names (R5)
  "let _govInds = null;",
  "function _setGovInds(v){ _govInds = v; }",
  extract("_govT"),
  extract("_govIndLabel"),
  slice("const _GOV_CAT_LABEL = {", "function _govCatLabel"),
  extract("_govCatLabel"),
  extract("_govPaintIndOptions"),
  extract("_govMapCaveatText"),
  "return { _uxMergedLine, _uxPerItemView, _uxFmtDur, _ooMapCount, _ooOsmCounts, _dumpScanned,"
    + " _dumpSecs, _dumpPages, loadStatFigures, loadRevisionAnomalies, repaintStatTablesFromCache,"
    + " _govIndLabel, _govCatLabel, _govPaintIndOptions, _govMapCaveatText, _setGovInds };",
].join("\n");
// Both the `window.OOI18N` and the bare `OOI18N` reads resolve (the node-harness trap).
const mod = new Function("window", "OOI18N", "$", "api", src)({ OOI18N: I18N }, I18N, $, api);

let n = 0;
async function test(name, fn) { await fn(); n++; console.log("ok  - " + name); }

(async () => {
  // --- R11: an already-merged backup says WHEN and AS WHAT --------------------------- //
  await test("R11: the skip names its batch and date, both isolated, in one keyed frame", () => {
    I18N.lang = "fr";
    const at = "2026-09-20T10:15:00Z";
    const line = mod._uxMergedLine({ batch: 7, at, open_group: false }, I18N.t, I18N.tf);
    assert.ok(line.startsWith("«fr:Already merged as batch " + FSI + "7" + PDI + " on " + FSI), line);
    assert.ok(line.endsWith(PDI + " — nothing new to import.»"), line);
    assert.ok(/2026/.test(line), "the date is missing: " + line);
    // Merged earlier in THIS run and not yet saved: a batch number would name a batch
    // that may never exist, so it says what is true instead.
    const open = mod._uxMergedLine({ batch: 9, at, open_group: true }, I18N.t, I18N.tf);
    assert.strictEqual(open, "«fr:Already merged earlier in this run, not yet saved — nothing new to import.»");
    // An older server sends neither: the plain line, never "batch undefined".
    const bare = mod._uxMergedLine({}, I18N.t, I18N.tf);
    assert.strictEqual(bare, "«fr:Already merged — nothing new to import.»");
  });

  // --- R9: each per-item count is ONE frame chosen by its number --------------------- //
  await test("R9: per-item counts are one/many frames, the duration isolated", () => {
    I18N.lang = "ar";
    const rows = [
      { title: "a", state: "done", kind: "articles", total: 1201, new: 1, dup: 1200, conf: 0, elapsed_s: 7.7 },
      { title: "b", state: "done", kind: "blobs", total: 4, new: 3, dup: 1, conf: 1, elapsed_s: 0.2 },
      { title: "c", state: "done", kind: "newsletters", total: 2, new: 2, dup: 0, conf: 0, elapsed_s: 1 },
      { title: "d", state: "skipped", kind: "articles", total: 0, new: 0, dup: 0, conf: 0,
        merged: { batch: 3, at: "2026-09-01T08:00:00Z" } },
    ];
    const html = mod._uxPerItemView(rows, I18N.t, I18N.tf);
    assert.ok(html.includes("«ar:1 article imported»"), html);
    assert.ok(/«ar:1\s200 duplicates»/.test(html), "the plural frame, the count grouped: " + html);
    assert.ok(html.includes("«ar:3 files restored»") && html.includes("«ar:1 file skipped»"), html);
    assert.ok(html.includes("«ar:1 conflict (your version kept)»"), html);
    assert.ok(html.includes("«ar:2 newsletters stored»") && html.includes("«ar:0 newsletters already present»"), html);
    assert.ok(!/imported»?\s*\d|\d+ «ar:imported/.test(html), "a count welded to a word: " + html);
    // The duration: the unit inside the keyed frame, isolated, unbreakable.
    assert.ok(html.includes(FSI + "«ar:7.7" + NBSP + "s»" + PDI), "the duration is not one isolated frame: " + html);
    // The already-merged row says so, not "nothing imported".
    assert.ok(html.includes("«ar:Already merged as batch " + FSI + "3" + PDI), html);
    assert.ok(!html.includes("nothing imported"), html);
  });

  // --- R14: the map's counts, each with its noun, one frame per number --------------- //
  await test("R14: map counts agree with their number", () => {
    I18N.lang = "fr";
    assert.strictEqual(mod._ooMapCount("sources", 1), "«fr:1 source»");
    assert.ok(/^«fr:12\s?345 sources»$/.test(mod._ooMapCount("sources", 12345)), mod._ooMapCount("sources", 12345));
    assert.strictEqual(mod._ooMapCount("articles", 2), "«fr:2 articles»");
    assert.strictEqual(mod._ooMapCount("keywords", 1), "«fr:1 mention»");
    const osm = mod._ooOsmCounts({ points: [1], lines: [1, 2], areaCount: 1, truncated: true });
    assert.strictEqual(osm, "«fr:1 node» · «fr:2 ways» · «fr:preview» · «fr:1 country boundary»");
    assert.strictEqual(mod._dumpScanned(1), "«fr:1 index line scanned»");
    assert.strictEqual(mod._dumpPages(3), "«fr:3 pages»");
    // "0.4s" read "s 0.4" on an Arabic page: the seconds are isolated and unbreakable.
    assert.strictEqual(mod._dumpSecs(0.42), FSI + "«fr:0.42" + NBSP + "s»" + PDI);
  });

  // --- R7 / R8: the statistics tables follow a language switch, with no request ------- //
  await test("R7/R8: the figures and anomalies tables redraw from their cache", async () => {
    I18N.lang = "fr";
    API_ANSWERS["/api/stats/figures"] = {
      shown: 2, count: 1500,
      figures: [
        { agency: "WB", series_id: "SP.POP.TOTL", ref_area: "EUU", area_kind: "aggregate",
          area_name: "European Union", time_period: "2024", value: 448000000, unit: "people" },
        { agency: "WB", series_id: "SP.POP.TOTL", ref_area: "FRA", area_kind: "country",
          area_name: null, time_period: "2024", value: 68000000, unit: "people" },
      ],
    };
    API_ANSWERS["/api/stats/revision-anomalies"] = {
      z_min: 3.5, min_prior_revisions: 3,
      anomalies: [{ agency: "WB", series_id: "X", ref_area: "FRA", area_kind: "country",
        time_period: "2020", from_value: 1, to_value: 2, abs_change: 1, rel_change: 1,
        robust_z: 4.2, n_prior_revisions: 5, revised_at: "2026-09-01" }],
    };
    API_CALLS = [];
    await mod.loadStatFigures();
    await mod.loadRevisionAnomalies();
    assert.strictEqual(API_CALLS.length, 2, API_CALLS.join(", "));
    const fig = $("statfig-table").innerHTML, rev = $("statfig-revisions").innerHTML;
    // ONE frame, its numbers grouped and isolated: never "Showing 2 of 1500" in English.
    assert.ok(new RegExp("«fr:Showing " + FSI + "2" + PDI + " of " + FSI + "1\\s500" + PDI
      + " · latest vintage»").test(fig), fig);
    for (const h of ["Agency", "Series", "Area", "Period", "Value", "Unit", "SA/NSA", "Base yr"]) {
      assert.ok(fig.includes("«fr:" + h + "»"), "header " + h + " not keyed: " + fig);
    }
    assert.ok(fig.includes("«fr:European Union»"), "the aggregate's name not keyed: " + fig);
    assert.ok(rev.includes("«fr:Flagged: " + FSI + "1" + PDI + " · robust z ≥ " + FSI + "3.5" + PDI
      + " · prior revisions ≥ " + FSI + "3" + PDI + "»"), rev);
    // The column is a SIZE, so it has its own noun key -- "Change" is the verb.
    assert.ok(rev.includes("«fr:Change in value»") && !rev.includes("«fr:Change»"), rev);
    // A language switch: both redraw in the new language, from what they last drew.
    I18N.lang = "zh";
    API_CALLS = [];
    mod.repaintStatTablesFromCache();
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(API_CALLS.length, 0, "a language switch refetched: " + API_CALLS.join(", "));
    assert.ok($("statfig-table").innerHTML.includes("«zh:Showing "), $("statfig-table").innerHTML);
    assert.ok(!$("statfig-table").innerHTML.includes("«fr:"), "the figures table kept French");
    assert.ok($("statfig-revisions").innerHTML.includes("«zh:Flagged: "), $("statfig-revisions").innerHTML);
    assert.ok(!$("statfig-revisions").innerHTML.includes("«fr:"), "the anomalies table kept French");
  });

  await test("R7: a table never opened stays unloaded on a switch", async () => {
    // Fresh module state: nothing drawn, so nothing to redraw and nothing to request.
    const fresh = new Function("window", "OOI18N", "$", "api", src)({ OOI18N: I18N }, I18N, $, api);
    $("statfig-table").innerHTML = "untouched";
    API_CALLS = [];
    fresh.repaintStatTablesFromCache();
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(API_CALLS.length, 0);
    assert.strictEqual($("statfig-table").innerHTML, "untouched");
  });

  // --- R5: the Governments catalogue's names --------------------------------------- //
  await test("R5: indicator names, notes and categories go through the translator", () => {
    I18N.lang = "fr";
    assert.strictEqual(mod._govIndLabel("GDP (current US$)"), "«fr:GDP (current US$)»");
    assert.strictEqual(mod._govIndLabel(""), "", "an absent label stays absent");
    // The categories arrive as lower-case ids and were capitalised by CSS.
    assert.strictEqual(mod._govCatLabel("energy & environment"), "«fr:Energy & environment»");
    assert.strictEqual(mod._govCatLabel("public finance"), "«fr:Public finance»");
    const cav = mod._govMapCaveatText({ label: "Gini index" }, { year: 2022, caveat: "c." }, I18N.t);
    assert.strictEqual(cav, "«fr:Gini index» · 2022 · «fr:c.»");
  });

  await test("R5: a language switch relabels the pickers and keeps the pick", () => {
    mod._setGovInds([{ id: "A", label: "Gini index" }, { id: "B", label: "Tax revenue (% of GDP)" }]);
    const sel = { options: [{ value: "A", textContent: "«fr:Gini index»" },
                            { value: "B", textContent: "«fr:Tax revenue (% of GDP)»", selected: true }] };
    I18N.lang = "ja";
    mod._govPaintIndOptions(sel);
    assert.strictEqual(sel.options[0].textContent, "«ja:Gini index»");
    assert.strictEqual(sel.options[1].textContent, "«ja:Tax revenue (% of GDP)»");
    assert.strictEqual(sel.options[1].selected, true, "the reader's pick was lost");
    mod._govPaintIndOptions(null);   // an absent picker is not an error
  });

  console.log(`\n${n} B18 checks passed`);
})().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
