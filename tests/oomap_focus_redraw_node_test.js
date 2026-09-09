// The ooMap focus slider redraws the SIGNALS, not the world — run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// `focusT` feeds the signal markers and their year label and NOTHING else — not the
// choropleth, not the grid, not the labels or the OSM overlay. A drag frame nonetheless
// re-projected and re-serialised all 175 countries (285 rings, 10,521 coordinate pairs)
// into fresh path `d` strings, replaced the host's whole innerHTML and re-attached every
// listener, to move a handful of circles.
//
// The properties below are the ones a diff cannot show and a source grep cannot tell
// apart, so they are executed: that the cheap path draws the SAME markers the full render
// would (it must be a shortcut, never a second renderer), that it leaves the map's other
// layers untouched, that it refuses rather than half-updates when it cannot be sure, and
// that the click-resolution list stays in step with what is actually on screen — a stale
// one opens the wrong event's detail, which is silent and wrong.

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

// The real projection constants, lifted from the module so the geometry is not re-typed.
const mm = /const MAP_W\s*=\s*([0-9.]+)\s*,\s*MAP_H\s*=\s*([0-9.]+)/.exec(APP);
assert.ok(mm, "MAP_W/MAP_H not found -- the projection moved");
const mw = [null, mm[1]], mh = [null, mm[2]];

const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  "var window = {};\n" +                       // OOI18N absent = the boot-time state
  "const MAP_W=" + mw[1] + ", MAP_H=" + mh[1] + ";\n" +
  "const lon2x = lon => (Number(lon) + 180) / 360 * MAP_W;\n" +
  "const lat2y = lat => (90 - Number(lat)) / 180 * MAP_H;\n" +
  "const kindColor = k => 'col:' + k;\n" +
  "function kindLabel(k){ return 'Kind ' + k; }\n" +
  "function fmtDate(s){ return 'D' + s.t; }\n" +
  extract("_ooSigClass") + "\n" +
  extract("_ooSigClassLabel") + "\n" +
  extract("_ooSigMarker") + "\n" +
  extract("_ooSignalLayer") + "\n" +
  extract("_ooSigKindsHtml") + "\n" +
  extract("_ooMapFocusRedraw") + "\n" +
  "module.exports = { _ooSignalLayer, _ooSigKindsHtml, _ooMapFocusRedraw };\n";

const mod = { exports: {} };
new Function("module", "exports", src)(mod, mod.exports);
const { _ooSignalLayer, _ooSigKindsHtml, _ooMapFocusRedraw } = mod.exports;

const SIGNALS = [
  { lat: 10, lon: 20, t: 2000, kind: "hazard", title: "Quake", confirmed: true, magnitude: 6 },
  { lat: -5, lon: 40, t: 2010, kind: "flood", title: "Flood", confirmed: true },
  { lat: 50, lon: -3, t: 1900, kind: "vote", title: "Old vote", confirmed: false },
  { lat: 0, lon: 0, t: null, kind: "vote", title: "No time", confirmed: true },
  { lat: null, lon: 5, t: 2005, kind: "vote", title: "No place", confirmed: true },
];
const base = (over) => Object.assign(
  { signalsOn: true, signals: SIGNALS, focusT: 2005, windowY: 10, onSignal: null }, over || {});

let pass = 0, fail = 0;
function check(name, fn) {
  try { fn(); pass++; console.log("ok   - " + name); }
  catch (e) { fail++; console.log("FAIL - " + name + ": " + e.message); }
}

// ---- the layer itself ------------------------------------------------------------ //

check("a signal with no time or no place is never drawn", () => {
  const out = _ooSignalLayer(base());
  assert.strictEqual(out.visible.length, 2, "only the two in-window, placed, timed signals");
  assert.ok(!out.markup.includes("No time") && !out.markup.includes("No place"));
});

check("the focus window selects, and moving it changes the selection", () => {
  const near = _ooSignalLayer(base({ focusT: 2005, windowY: 10 })).visible.map(s => s.title);
  const old = _ooSignalLayer(base({ focusT: 1900, windowY: 10 })).visible.map(s => s.title);
  assert.deepStrictEqual(near.sort(), ["Flood", "Quake"]);
  assert.deepStrictEqual(old, ["Old vote"]);
});

check("it is PURE: same input, byte-identical markup", () => {
  assert.strictEqual(_ooSignalLayer(base()).markup, _ooSignalLayer(base()).markup);
});

check("signals off draws nothing at all", () => {
  const out = _ooSignalLayer(base({ signalsOn: false }));
  assert.strictEqual(out.markup, "");
  assert.deepStrictEqual(out.kinds, []);
  assert.deepStrictEqual(out.visible, []);
});

check("the kinds follow the window, so the legend cannot outlive its markers", () => {
  assert.deepStrictEqual(_ooSignalLayer(base({ focusT: 1900 })).kinds, ["vote"]);
  assert.deepStrictEqual(_ooSignalLayer(base({ focusT: 2005 })).kinds.sort(), ["flood", "hazard"]);
});

check("marker indices match the visible list, so a click resolves the right event", () => {
  const out = _ooSignalLayer(base({ onSignal: () => {} }));
  const idx = [...out.markup.matchAll(/data-oomap-sig="(\d+)"/g)].map(m => +m[1]);
  assert.deepStrictEqual(idx, out.visible.map((_, i) => i));
});

// ---- the cheap redraw ------------------------------------------------------------ //

function fakeHost({ withLayer = true } = {}) {
  const nodes = {};
  const mk = (sel) => ({
    innerHTML: "", textContent: "", dataset: {}, _sel: sel,
    addEventListener() { this._wired = (this._wired || 0) + 1; },
  });
  if (withLayer) nodes["[data-oomap-siglayer]"] = mk("layer");
  nodes["[data-oomap-sigkinds]"] = mk("kinds");
  nodes["[data-oomap-focuslabel]"] = mk("label");
  return {
    _nodes: nodes,
    _countryPaths: "<path d='UNTOUCHED'/>".repeat(175),
    querySelector(sel) { return this._nodes[sel] || null; },
    querySelectorAll(sel) {
      if (sel !== "[data-oomap-sig]") return [];
      const layer = this._nodes["[data-oomap-siglayer]"];
      const n = layer ? [...String(layer.innerHTML).matchAll(/data-oomap-sig="(\d+)"/g)].length : 0;
      return Array.from({ length: n }, (_, i) => ({ dataset: { oomapSig: String(i) }, addEventListener() {} }));
    },
  };
}

check("the cheap redraw draws exactly what a full render would", () => {
  const host = fakeHost();
  const opts = base({ focusT: 1900, focusLabel: "1900" });
  assert.strictEqual(_ooMapFocusRedraw(host, opts), true);
  assert.strictEqual(host._nodes["[data-oomap-siglayer]"].innerHTML, _ooSignalLayer(opts).markup,
    "the cheap path must be a shortcut, never a second renderer");
});

check("it does NOT touch the country paths -- that is the whole point", () => {
  const host = fakeHost();
  const before = host._countryPaths;
  _ooMapFocusRedraw(host, base({ focusT: 1900, focusLabel: "1900" }));
  assert.strictEqual(host._countryPaths, before, "175 countries must not be re-serialised");
});

check("the year label and the kind chips are refreshed with the markers", () => {
  const host = fakeHost();
  _ooMapFocusRedraw(host, base({ focusT: 1900, focusLabel: "1900" }));
  assert.strictEqual(host._nodes["[data-oomap-focuslabel]"].textContent, "1900");
  assert.strictEqual(host._nodes["[data-oomap-sigkinds]"].innerHTML, _ooSigKindsHtml(["vote"]));
});

check("the click-resolution list is replaced, never left stale", () => {
  const host = fakeHost();
  _ooMapFocusRedraw(host, base({ focusT: 2005, focusLabel: "2005" }));
  const first = host._ooSigVisible.map(s => s.title).sort();
  assert.deepStrictEqual(first, ["Flood", "Quake"]);
  _ooMapFocusRedraw(host, base({ focusT: 1900, focusLabel: "1900" }));
  assert.deepStrictEqual(host._ooSigVisible.map(s => s.title), ["Old vote"],
    "a stale list opens the wrong event's detail -- silent and wrong");
});

check("marker listeners are re-attached, because the markers were replaced", () => {
  const host = fakeHost();
  let wired = 0;
  const opts = base({ focusT: 2005, focusLabel: "2005", onSignal: () => {} });
  host.querySelectorAll = (sel) => (sel === "[data-oomap-sig]"
    ? [{ dataset: { oomapSig: "0" }, addEventListener() { wired++; } }] : []);
  _ooMapFocusRedraw(host, opts);
  assert.strictEqual(wired, 1);
});

check("it REFUSES when there is no rendered signals layer, so the caller can fall back", () => {
  assert.strictEqual(_ooMapFocusRedraw(fakeHost({ withLayer: false }), base()), false);
  assert.strictEqual(_ooMapFocusRedraw(null, base()), false);
});

console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
