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
  + extract("kpiPanelHtml") + extract("_kpiBlockHtml") + "\nreturn kpiPanelHtml;";
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
    {vertical: "osm", kind: "lane", state: "recorded", first_slice: false, lane: "absent", countries: 0,
      reason: "no OpenStreetMap country has been cut"},
    {vertical: "wiki", kind: "lane", state: "recorded", first_slice: true, editions_listed: 3, pages_seen: 4000,
      gaps_total: null, method: "the wiki report"},
  ]};
html = kpiPanelHtml({metrics: [k13]}, H);
txt = text(html);
assert.ok(txt.includes("measured, no target set yet"));
for (const name of ["Climate", "Elections", "Law", "OpenStreetMap", "Wikipedia"]) assert.ok(txt.includes(name), name);
assert.ok(txt.includes("Climate · not measured · no first slice yet"), txt);
assert.ok(txt.includes("no climate fetch has been recorded"), "the reason is visible");
assert.ok(!/datasets fetched/.test(txt), "a count the block does not carry is not drawn");
assert.ok(txt.includes("countries on the floor: 140") && txt.includes("snapshot rows: unknown"), txt);
assert.ok(txt.includes("Law · recorded · first slice in · as of: 2026-11-18"));
assert.ok(txt.includes("jurisdictions: unknown") && txt.includes("documents never checked: 0"),
  "unknown and a real 0 stay apart");
assert.ok(txt.includes("countries listed: 0"));
assert.ok(txt.includes("gaps: unknown") && txt.includes("pages seen: 4000"));
assert.ok(html.includes('title="the law report&#39;s own counts"'), "each block's method is its own hover title");

// 5. Hostile strings from a hand-edited record are escaped, never markup.
html = kpiPanelHtml({metrics: [{id: "<b>", name: "<img src=x onerror=1>", value: "<i>", verdict: "weird", target: "<t>",
  method: '"><script>'}]}, H);
assert.ok(!/<img|<script|<i>|<b>|<t>/.test(html.replace(/<\/?(div|b|span)( [^>]*)?>/g, "")), html);
// A value that is not a finite number is not printed as one.
assert.ok(text(html).includes("value: unknown"));

console.log("kpi panel: all assertions passed");
