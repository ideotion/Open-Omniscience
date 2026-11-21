// Row 269 (invariant #17): a chart mark carries its hover in a title ATTRIBUTE, which the shared #oo-tip
// bubble opens on hover and on touch long-press -- never in an SVG <title> child, which only a mouse reached.
// Run as REAL code, extracted from the shipped modules.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Run here: the ingest-rhythm grid (Library), the share donut (Library), the per-country dumbbell
// (Insights) and the slope chart (Corpus). The concept tree and the small multiples are run by their own
// node tests (concept_tree_node_test.js, small_multiples_gaps_node_test.js); the guard that no renderer
// builds a <title> child again is tests/test_chart_hover_titles_r269.py.

const assert = require("assert");
const APP = require("./app_source.js").appJs();
const ooViz = require("../src/static/ooviz.js");

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
function constLine(name) {
  const m = new RegExp("const " + name + " = [^\\n]*;").exec(APP);
  assert.ok(m, name + " not found");
  return m[0];
}

const PRELUDE = "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}\n" +
  "var window = {};\nvar document = { documentElement: { dir: 'ltr' } };\n" +
  "function fmtNum(n){ return String(n); }\n" +
  "function _tfn(s, v){ return String(s).replace(/\\{(\\w+)\\}/g, (m, k) => v[k]); }\n";

function load(names, consts, exportsList) {
  const src = PRELUDE + consts.map(constLine).join("\n") + "\n" + names.map(extract).join("\n") +
    "\nreturn {" + exportsList.join(",") + "};";
  return new Function("ooViz", "ooCountryCode", "ooCountryName", "ooCountryKey", "ooLtrIsolate", src)(
    ooViz, (c) => String(c).toUpperCase(), () => "France", (c) => String(c).toLowerCase(), (s) => String(s));
}

function noTitleChild(markup, what) {
  assert.ok(!/<title>/.test(markup), what + " built a <title> child again (mouse-only): " + markup.slice(0, 300));
}

// --- the ingest-rhythm grid: observed slots and slots that have not come round -------------- //
{
  const F = load(["_ingestRhythm", "ingestRhythmSvg"], ["_RHYTHM_DAYS"], ["ingestRhythmSvg"]);
  const svg = F.ingestRhythmSvg([{ t: "2026-01-05T09:00:00Z", n: 4 }, { t: "2026-01-05T10:00:00Z", n: 0 }]);
  noTitleChild(svg, "the rhythm grid");
  assert.ok(/<rect [^>]*title="Monday 9:00 — 4 articles over 1 occurrence\(s\), 4 on average"/.test(svg), svg.slice(0, 600));
  assert.ok(/<rect [^>]*fill="url\(#rhythm-none\)" title="[^"]+ — not observed yet"/.test(svg), "an unobserved slot lost its hover");
}

// --- the share donut ------------------------------------------------------------------------ //
{
  const F = load(["ooDonut"], ["_DONUT_MAX_SLICES"], ["ooDonut"]);
  const host = { innerHTML: "" };
  F.ooDonut(host, [{ label: "en", value: 3 }, { label: "fr", value: 1 }], { unit: "articles" });
  noTitleChild(host.innerHTML, "the donut");
  assert.ok(/<circle [^>]*title="en: 3 articles \(75%\)"/.test(host.innerHTML), host.innerHTML.slice(0, 600));
}

// --- the per-country dumbbell (Q302: the code on the axis, the name in the hover) ----------- //
{
  const F = load(["ringDumbbellSvg"], ["_DUMBBELL_MAX"], ["ringDumbbellSvg"]);
  const svg = F.ringDumbbellSvg([{ country: "fr", articles: 2, mentions: 5 }], {}, null);
  noTitleChild(svg, "the dumbbell");
  assert.ok(/<g title="France">/.test(svg), svg.slice(0, 600));
  assert.ok(/<circle [^>]*title="France: 2 articles"/.test(svg) && /<circle [^>]*title="France: 5 mentions"/.test(svg), svg);
}

// --- the slope chart -------------------------------------------------------------------------- //
{
  const F = load(["slopeChartSvg"], ["_SLOPE_MAX"], ["slopeChartSvg"]);
  const svg = F.slopeChartSvg({ stages: ["a", "b"], series: [{ label: "Lyon", values: [1, 3] }] });
  noTitleChild(svg, "the slope chart");
  assert.ok(/<circle [^>]*title="Lyon: 3"/.test(svg), svg.slice(0, 800));
}

// --- the accessible name: an SVG <title> child named the mark for a screen reader; the title ATTRIBUTE does
// not (SVG reads aria-label and a <title> child), so the bubble's marker gives a titled SVG mark the same text
// as its aria-label, and keeps one the renderer set itself. ------------------------------------------------ //
{
  const name = new Function(extract("_ooTipSvgName") + "\nreturn _ooTipSvgName;")();
  const SVG = "http://www.w3.org/2000/svg";
  const el = (ns, tag, attrs) => ({ namespaceURI: ns, tagName: tag, a: Object.assign({}, attrs || {}),
    hasAttribute(k) { return k in this.a; }, getAttribute(k) { return k in this.a ? this.a[k] : null; },
    setAttribute(k, v) { this.a[k] = String(v); } });
  const dot = el(SVG, "circle");
  name(dot, "Lyon: 3");
  assert.strictEqual(dot.a["aria-label"], "Lyon: 3");
  name(dot, "Lyon: 4");
  assert.strictEqual(dot.a["aria-label"], "Lyon: 4", "a name this helper set must follow the title");
  const own = el(SVG, "g", { "aria-label": "set by the renderer" });
  name(own, "the hover");
  assert.strictEqual(own.a["aria-label"], "set by the renderer", "a renderer's own aria-label was overwritten");
  const html = el("http://www.w3.org/1999/xhtml", "BUTTON");
  name(html, "x");
  assert.ok(!("aria-label" in html.a), "an HTML element's title is already its description: no aria-label added");
  const root = el(SVG, "svg");
  name(root, "x");
  assert.ok(!("aria-label" in root.a), "the <svg> root keeps its own role and name");
}

console.log("chart_hover_titles_r269_node_test.js: all assertions passed");
