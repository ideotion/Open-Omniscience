// Row 268 (invariant #17): every marker the map renderer draws carries its hover in a title ATTRIBUTE,
// which the shared #oo-tip bubble opens on hover and on touch long-press -- never in an SVG <title>
// child, which only ever reached a mouse. Run as REAL code, extracted from the shipped module.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What is run here: the mentioned-place and server-IP markers (two statements inside ooMap, taken
// out of its body as written), the signal shapes, and the Insights cities map. The wiki page and
// infobox-address markers are run in tests/wiki_map_layer_node_test.js.

const assert = require("assert");
const APP = require("./app_source.js").appJs();
const fs = require("fs");
const path = require("path");
const MAP = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-map.js"), "utf8");

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

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
const t = (s) => "T[" + s + "]";
const fmtNum = (n) => String(n);

// One statement of ooMap, from `<lhs> += ` to the semicolon that ends the template it builds.
function statement(lhs, end) {
  const body = extract("ooMap");
  const at = body.indexOf(lhs + " += `");
  assert.ok(at !== -1, lhs + " is no longer built in ooMap -- was it renamed?");
  const stop = body.indexOf(end, at);
  assert.ok(stop !== -1, "could not find the end of " + lhs);
  return body.slice(at, stop + end.length);
}

function hoverOf(markup, tag) {
  assert.ok(!/<title>/.test(markup), "a <title> child came back (mouse-only): " + markup);
  const m = new RegExp("<" + tag + " [^>]*title=\"([^\"]*)\"[^>]*>").exec(markup);
  assert.ok(m, "the " + tag + " carries no title attribute: " + markup);
  return m[1];
}

// --- mentioned places: hollow circles, deduced -------------------------------------------- //
{
  const run = new Function("p", "x", "y", "r", "esc", "t", "fmtNum",
    "let overlayPts = '';\n" + statement("overlayPts", "</circle>`;") + "\nreturn overlayPts;");
  const hover = hoverOf(run({ label: "Lyon", value: 12 }, "1.0", "2.0", "3.0", esc, t, fmtNum), "circle");
  assert.strictEqual(hover, "Lyon — 12 T[articles] T[(mentioned, deduced)]");
  assert.strictEqual(hoverOf(run({ label: "A \"q\" <b>" }, "1", "2", "3", esc, t, fmtNum), "circle"),
    "A &quot;q&quot; &lt;b&gt; — T[(mentioned, deduced)]", "the label was not escaped inside the attribute");
}

// --- server IP locations: violet squares --------------------------------------------------- //
{
  const run = new Function("p", "cx", "cy", "s", "esc", "t", "fmtNum",
    "let serverPts = '';\n" + statement("serverPts", "</rect>`;") + "\nreturn serverPts;");
  const hover = hoverOf(run({ label: "Frankfurt", value: 3 }, 10, 20, 4, esc, t, fmtNum), "rect");
  assert.strictEqual(hover, "Frankfurt — 3 T[articles] T[(server IP location)]");
}

// --- signals: the three shapes --------------------------------------------------------------- //
{
  const sig = new Function(extract("_ooSigMarker") + "\nreturn _ooSigMarker;")();
  for (const [cls, tag] of [["confirmed", "circle"], ["scheduled", "polygon"], ["deduced", "polygon"]]) {
    const out = sig(cls, 10, 20, 3, 'fill="x"', "Quake — D2000");
    assert.strictEqual(hoverOf(out, tag), "Quake — D2000", cls);
    assert.ok(out.includes('fill="x" title='), "the fill and the title merged into one attribute: " + out);
  }
}

// --- a clickable signal's wider hit disc carries the same hover, so a long-press anywhere on it opens the bubble //
{
  const body = extract("_ooSignalLayer");
  assert.ok(/fill="transparent" title="\$\{esc\(ti\)\}"><\/circle>/.test(body), "the signal's hit disc has no hover of its own");
}

// --- the Insights cities map ------------------------------------------------------------------ //
{
  const build = new Function("esc", "project", "_mapGraticule", "_mapSphere", "ooCountryCode", "ooCountryName",
    "MAP_W", "MAP_H", "MAP_ASPECT", extract("buildMapSvg") + "\nreturn buildMapSvg;")(
    esc, () => ({ x: 1, y: 2 }), () => "", () => "", (c) => c.toUpperCase(), () => "France", 1000, 500, 2);
  const out = build([{ name: "Paris", country: "fr", lat: 48.8, lon: 2.3, top: [{ term: "strike", mentions: 4 }] }]);
  assert.strictEqual(hoverOf(out, "circle"), "Paris (FR — France): strike 4");
}

// --- and none is left anywhere in the map module ------------------------------------------- //
{
  const code = MAP.replace(/\/\*[\s\S]*?\*\//g, "").split("\n").map((l) => l.replace(/^\s*\/\/.*$/, "")).join("\n");
  assert.ok(!/<title>/.test(code), "app-map.js builds an SVG <title> child again: hover only, no touch");
}

console.log("map_marker_titles_r268_node_test.js: all assertions passed");
