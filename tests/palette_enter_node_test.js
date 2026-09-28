// The omnibar's Enter (Q608 = a), driven as REAL code: "Enter always opens the analysis
// window on the typed query; static commands need an explicit selection."
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// renderPalette, _palOrder, palKey, palRun and palMove are EXTRACTED from the shipped
// modules and run against a stubbed DOM, so what is asserted is what the keys do, not
// what the source happens to contain.

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

const src = `
  const calls = [];
  const els = {
    "pal-input": {value: ""},
    "pal-list": {innerHTML: ""},
    "palette": {classList: {contains: () => true}},
  };
  function $(id) { return els[id]; }
  const document = {querySelectorAll: () => [], querySelector: () => null};
  const window = {};
  function esc(s) { return String(s == null ? "" : s); }
  function ooLabelText(l, v) { return l + ": " + v; }
  function showTab(n) { calls.push(["showTab", n]); }
  function doSearch() { calls.push(["doSearch"]); }
  function openAnalysisInNewTab(q) { calls.push(["analyze", q]); }
  function _advHistRecord(q) { calls.push(["history", q]); }
  function closePalette() {}
  function _trapTab() {}
  let _omniLive = null;
  function _omniItems() { return _omniLive ? _omniLive.items : []; }
  function _omniFetch() {}
  let _palItems = [], _palFiltered = [], _palSel = 0, _palLastRaw = null;
  ${extract("renderPalette")}
  ${extract("_palOrder")}
  ${extract("palMove")}
  ${extract("palRun")}
  ${extract("palKey")}
  module.exports = {
    calls, els, renderPalette, palKey,
    setItems: (x) => { _palItems = x; },
    setLive: (x) => { _omniLive = x; },
    sel: () => _palSel, rows: () => _palFiltered,
  };
`;
const h = (() => {
  const m = {exports: {}};
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const key = (k) => h.palKey({key: k, preventDefault() {}});
let passed = 0;

// A typed word that ALSO names a static command: Enter analyses the word.
h.setItems([{grp: "Pages", label: "Settings", sub: "", run: () => h.calls.push(["settings"])}]);
h.els["pal-input"].value = "settings";
h.renderPalette();
assert.strictEqual(h.rows()[0].sub, "↵ ↗", "the Analysis row is row 0 and carries the ↵");
key("Enter");
assert.deepStrictEqual(h.calls.filter((c) => c[0] === "analyze"), [["analyze", "settings"]]);
assert.ok(!h.calls.some((c) => c[0] === "settings"), "Enter must not run the static command");
passed++;

// The static command is one explicit selection away.
h.calls.length = 0;
h.renderPalette();
const settingsAt = h.rows().findIndex((r) => r.label === "Settings");
assert.ok(settingsAt > 0, "the static match is still listed, below the search rows");
for (let i = 0; i < settingsAt; i++) key("ArrowDown");
key("Enter");
assert.ok(h.calls.some((c) => c[0] === "settings"), "an explicit selection runs the command");
assert.ok(!h.calls.some((c) => c[0] === "analyze"));
passed++;

// An explicit selection survives the live results landing (the omnibar redraws then).
h.calls.length = 0;
h.els["pal-input"].value = "";          // a fresh palette (openPalette clears the input)
h.renderPalette();
h.els["pal-input"].value = "settings";
h.renderPalette();
assert.strictEqual(h.sel(), 0, "typing a new query starts on row 0 again");
const at = h.rows().findIndex((r) => r.label === "Settings");
for (let i = 0; i < at; i++) key("ArrowDown");
h.setLive({q: "settings", items: [{grp: "Keywords", label: "settings (keyword)", run: () => {}}]});
h.renderPalette();
assert.strictEqual(h.rows()[h.sel()].label, "Settings", "the arrowed-to row is still selected");
passed++;

// A single typed character still analyses (the live search needs two; Enter does not).
h.calls.length = 0;
h.setLive(null);
h.els["pal-input"].value = "x";
h.renderPalette();
key("Enter");
assert.deepStrictEqual(h.calls.filter((c) => c[0] === "analyze"), [["analyze", "x"]]);
passed++;

// Nothing typed: the palette is the command list, and Enter runs its first command.
h.calls.length = 0;
h.els["pal-input"].value = "";
h.renderPalette();
key("Enter");
assert.ok(h.calls.some((c) => c[0] === "settings"));
assert.ok(!h.calls.some((c) => c[0] === "analyze"));
passed++;

console.log(`palette_enter_node_test: ${passed} passed`);
