// R751(c): the K1–K14 measures in the task manager's System tab, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What is guarded is a set of refusals a diff does not show: a measure without a value reads "unknown" and never 0,
// no total and no count of the measures that meet their target is drawn, the caveat line is on screen, every method rides
// a hover title, and the five K13 blocks each draw their own counts, an unreadable count reading "unknown". The functions
// are EXTRACTED from the shipped module, never re-typed.

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
function constDecl(name) {
  const at = APP.indexOf("const " + name + " = {");
  assert.ok(at !== -1, name + " not found");
  let d = 0, j = APP.indexOf("{", at);
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j) + ";";
}

const src = ["_KPI_VERDICT", "_KPI_VERTICAL", "_KPI_FIGURES"].map(constDecl).join("\n")
  + extract("kpiFramesText") + extract("kpiPanelHtml") + extract("_kpiBlockHtml") + "\nreturn kpiPanelHtml;";
const kpiPanelHtml = new Function(src)();

const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const H = {
  t: s => s,
  tf: (s, v) => String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m),
  esc, fmt: v => String(v), date: v => String(v).slice(0, 10), label: (l, v) => l + ": " + v,
};
const text = html => html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ");

// 1. A measure without a value reads unknown, never 0; its method is a hover title; the verdict is words.
const nm = {id: "K1", name: "Warm unlock", value: null, n: null, as_of: null, verdict: "not-measurable-here",
  target: "< 2 s", method: "needs a live corpus"};
const green = {id: "K11", name: "Locales", value: 100, n: 11, as_of: "2026-11-19T15:01:05+00:00", verdict: "green",
  target: "min 100%", method: "minimum locale key-coverage"};
const red = {id: "K2", name: "p95", value: 812.5, n: 40, as_of: null, verdict: "red", target: "< 500 ms", method: "reservoir"};
let html = kpiPanelHtml({metrics: [nm, green, red], caveat: "NO composite"}, H);
let txt = text(html);
assert.ok(/K1 Warm unlock · not measurable here/.test(txt), txt);
assert.ok(txt.includes("value: unknown"), "a missing value reads unknown");
assert.ok(!/value: 0\b/.test(txt), "a missing value never reads 0");
assert.ok(html.includes('title="needs a live corpus"'), "the method rides a hover title");
assert.ok(txt.includes("meets its target") && txt.includes("misses its target"));
assert.ok(txt.includes("n = 11") && txt.includes("as of: 2026-11-19"));
assert.ok(txt.includes("target: &lt; 500 ms"), "the target is shown, escaped");
// 2. The caveat is on screen (not only in a title), and no total or tally is drawn.
assert.ok(/<div class="card-caveat"[^>]*>Each measure stands alone/.test(html), "the caveat line is visible");
assert.ok(!/score/i.test(txt.replace("there is no overall score", "")), "no score is drawn");
assert.ok(!/\b[0-9]+ (of|\/) 3\b/.test(txt), "no count of the measures");
// 3. No metrics array: an honest line, never an empty div.
assert.ok(text(kpiPanelHtml({}, H)).includes("No measures could be read."));
assert.ok(text(kpiPanelHtml(null, H)).includes("No measures could be read."));

// 4. The K13 blocks: each its own counts; an unreadable count reads unknown; a count the block never carries is not drawn.
const k13 = {id: "K13", name: "Vertical coverage", value: 2, n: 5, as_of: "2026-11-18", verdict: "measured-no-bar",
  target: "pending", method: "2 of the 5", verticals: [
    {vertical: "climate", state: "not-measured", first_slice: false, reason: "no climate fetch has been recorded"},
    {vertical: "elections", state: "not-measured", first_slice: false, floor_countries: 140, covered: 7, missing: 122,
      snapshot_rows: null, method: "the elections floor"},
    {vertical: "law", kind: "lane", state: "recorded", first_slice: true, as_of: "2026-11-18T10:00:00+00:00", documents: 12,
      baselined: 10, jurisdictions: null, never_checked: 0, method: "the law report's own counts"},
    {vertical: "medical", state: "recorded", first_slice: true, as_of: "2026-11-18T10:00:00+00:00",
      files_applied_last_run: 7, files_listed: 40, files_remaining: 0, papers_kept: null,
      newest_file_applied: "pubmed25n1400.xml.gz", method: "the last PubMed fetch's own record"},
    {vertical: "osm", kind: "lane", state: "recorded", first_slice: false, lane: "absent", countries: 0,
      reason: "no OpenStreetMap country has been cut"},
    {vertical: "wiki", kind: "lane", state: "recorded", first_slice: true, editions_listed: 3, pages_seen: 4000,
      gaps_total: null, method: "the wiki report"},
  ]};
html = kpiPanelHtml({metrics: [k13]}, H);
txt = text(html);
assert.ok(txt.includes("measured, no target set yet"));
for (const name of ["Climate", "Elections", "Law", "Medical papers", "OpenStreetMap", "Wikipedia"]) assert.ok(txt.includes(name), name);
assert.ok(txt.includes("Climate · not measured · no first slice yet"), txt);
assert.ok(txt.includes("no climate fetch has been recorded"), "the reason is visible");
assert.ok(!/datasets fetched/.test(txt), "a count the block does not carry is not drawn");
assert.ok(txt.includes("countries on the floor: 140") && txt.includes("snapshot rows: unknown"), txt);
assert.ok(txt.includes("Law · recorded · first slice in · as of: 2026-11-18"));
assert.ok(txt.includes("jurisdictions: unknown") && txt.includes("documents never checked: 0"),
  "unknown and a real 0 stay apart");
assert.ok(txt.includes("countries listed: 0"));
// Row 207: the medical block draws its counts; an unreadable one reads unknown and a real 0 stays 0; its file name is no figure.
assert.ok(txt.includes("Medical papers · recorded · first slice in"), txt);
assert.ok(txt.includes("update files applied last run: 7") && txt.includes("update files listed: 40"), txt);
assert.ok(txt.includes("update files remaining: 0") && txt.includes("papers kept: unknown"), txt);
assert.ok(!txt.includes("pubmed25n1400"), "the newest file name is not drawn as a figure");
assert.ok(txt.includes("gaps: unknown") && txt.includes("pages seen: 4000"));
assert.ok(html.includes('title="the law report&#39;s own counts"'), "each block's method is its own hover title");

// 5. Hostile strings from a hand-edited record are escaped, never markup.
html = kpiPanelHtml({metrics: [{id: "<b>", name: "<img src=x onerror=1>", value: "<i>", verdict: "weird", target: "<t>",
  method: '"><script>'}]}, H);
for (const raw of ["<img", "<script", "<i>", "<t>", "<b><"]) assert.ok(!html.toLowerCase().includes(raw), raw + " " + html);
for (const safe of ["&lt;img src=x onerror=1&gt;", "&lt;b&gt;", "&lt;t&gt;", "&quot;&gt;&lt;script&gt;"])
  assert.ok(html.includes(safe), safe + " " + html);
// A value that is not a finite number is not printed as one.
assert.ok(text(html).includes("value: unknown"));

// 6. Row 201: the method and a block's reason render from their keyed frames in the UI language. The template translates,
// the data does not, a `tr` var's word translates while a number passes through, and the pieces join with nothing between
// them. A snapshot without frames still shows its English.
const FR = {
  "{n} of the {total} verticals and lanes listed have a first slice in ({names}); ":
    "{n} des {total} verticales et voies listées ont une première tranche ({names}) ; ",
  "each block below carries its own figures.": "chaque bloc ci-dessous porte ses propres chiffres.",
  "the last law coverage report counted no tracked document": "le dernier rapport n'a compté aucun document suivi",
  "{gaps} gaps": "{gaps} lacunes", "an unknown number of": "un nombre inconnu de",
  "Vertical coverage": "Couverture des verticales", "< 2 s": "< 2 s",
};
const tFr = s => (FR[s] != null ? FR[s] : s);
const HFR = Object.assign({}, H, {
  t: tFr,
  tf: (s, v) => tFr(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m),
});
const framed = {id: "K13", name: "Vertical coverage", value: 1, n: 6, verdict: "measured-no-bar", target: "pending",
  method: "1 of the 6 verticals and lanes listed have a first slice in (law); each block below carries its own figures.",
  method_i18n: [
    {t: "{n} of the {total} verticals and lanes listed have a first slice in ({names}); ",
      v: {n: "1", total: "6", names: "law"}},
    {t: "each block below carries its own figures.", v: {}},
  ],
  verticals: [{vertical: "law", kind: "lane", state: "recorded", first_slice: false,
    method: "x", method_i18n: [{t: "{gaps} gaps", v: {gaps: "an unknown number of"}, tr: ["gaps"]}],
    reason: "the last law coverage report counted no tracked document",
    reason_i18n: [{t: "the last law coverage report counted no tracked document", v: {}}]},
    {vertical: "wiki", kind: "lane", state: "recorded", first_slice: true,
      method: "7 gaps", method_i18n: [{t: "{gaps} gaps", v: {gaps: "7"}, tr: ["gaps"]}]}]};
html = kpiPanelHtml({metrics: [framed]}, HFR);
assert.ok(html.includes('title="1 des 6 verticales et voies listées ont une première tranche (law) ; chaque bloc ci-dessous porte ses propres chiffres."'), html);
assert.ok(html.includes('title="un nombre inconnu de lacunes"'), "a tr word translates");
assert.ok(html.includes('title="7 lacunes"'), "a number in a tr var passes through");
assert.ok(text(html).includes("le dernier rapport n&#39;a compté aucun document suivi"), "the reason renders from its frames");
assert.ok(text(html).includes("Couverture des verticales"), "the measure's name is keyed");
assert.ok(!html.includes("each block below"), "no English left where a frame translates");
// An older snapshot with no frames keeps its English method.
html = kpiPanelHtml({metrics: [{id: "K1", name: "x", verdict: "not-measurable-here", target: "t", method: "plain english"}]}, HFR);
assert.ok(html.includes('title="plain english"'));
// Frames that render nothing (malformed) fall back to the English rather than hiding the hover.
html = kpiPanelHtml({metrics: [{id: "K1", name: "x", verdict: "not-measurable-here", target: "t", method: "plain english",
  method_i18n: [{}, null]}]}, HFR);
assert.ok(html.includes('title="plain english"'), html);

console.log("kpi panel: all assertions passed");
