// Row 398 (anti-capping): Insights > Who says the real count and is cut only when the
// server says so; the map's Places lens says "N of M shown" when its 400 are not all.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

"use strict";
const assert = require("assert");
const path = require("path");
const fs = require("fs");

global.window = {};
global.document = { addEventListener() {} };
const P = require(path.join(__dirname, "..", "src", "static", "app-patterns.js"));
const t = (s) => s;
const tf = (s, v) => String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m));
const ents = (n) => Array.from({ length: n }, (_, i) => ({ name: "P" + i, class: "person", articles: 1, mentions: 1 }));

// 1. A counted payload: "found" is the real total, and the cut line follows the server.
{
  const html = P.whoListHtml({ entities: ents(200), total: 3000, truncated: true }, t, tf);
  assert.ok(html.includes("3000 found"), "found showed the cap, not the count: " + html.slice(0, 300));
  assert.ok(html.includes("Showing the first 200."), "a cut list did not say so");
}
// 2. NEGATIVE SPACE: a list of exactly the cap that the server says is whole is not "cut".
{
  const html = P.whoListHtml({ entities: ents(200), total: 200, truncated: false }, t, tf);
  assert.ok(html.includes("200 found") && !html.includes("Showing the first"), "a whole list claimed a cut");
}
// 3. An older payload keeps the old guess.
{
  const html = P.whoListHtml({ entities: ents(200) }, t, tf);
  assert.ok(html.includes("200 found") && html.includes("Showing the first 200."), "the fallback was lost");
}

// 4. The map's cut line, from the shipped module.
const APP = require("./app_source.js").appJs();
function fnSource(name) {
  const m = new RegExp("function\\s+" + name + "\\s*\\(").exec(APP);
  assert.ok(m, name + " not found -- was it renamed?");
  const open = APP.indexOf("{", APP.indexOf(")", m.index));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(m.index, j);
}
const SRC = ["const window = {};", "function fmtNum(v) { return String(v); }",
  fnSource("_tfn"), fnSource("_ooMapPlacesCutText"), "module.exports = { _ooMapPlacesCutText };"].join("\n");
const M = (() => { const m = { exports: {} }; new Function("module", "exports", SRC)(m, m.exports); return m.exports; })();
const places = Array.from({ length: 400 }, () => ({}));
assert.strictEqual(M._ooMapPlacesCutText({ places, total: 1234, truncated: true }), "400 of 1234 shown.");
assert.strictEqual(M._ooMapPlacesCutText({ places, total: 400, truncated: false }), "", "a whole layer claimed a cut");
assert.strictEqual(M._ooMapPlacesCutText({ places }), "", "an older payload claimed a cut");
assert.strictEqual(M._ooMapPlacesCutText(null), "");
// the map asks only for drawable places
const MAP = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-map.js"), "utf8");
assert.ok(MAP.includes('"/api/insights/where?limit=400&placed_only=true"'), "the map stopped asking for placed places only");
assert.ok(!/api\("\/api\/insights\/where\?limit=400"\)/.test(MAP), "a map fetch still asks for unplaced places");

console.log("who_where_cut_node_test.js: OK");
