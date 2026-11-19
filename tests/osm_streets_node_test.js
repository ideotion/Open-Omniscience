// The street view's drawing, run as REAL code against a recording canvas (S07-02 S2).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What a source grep cannot tell apart from its opposite: that each road class is ONE path
// (the frame budget at the caps depends on it), that the important classes are stroked LAST
// so they sit on top, that labels never overlap, are never upside down, stop at the cap, and
// name each road once.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function fnSource(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found in the UI engine -- renamed?");
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

const from = APP.indexOf("const _OO_OSM_STREET_STYLE");
const to = APP.indexOf("function _ooOsmDrawStreets(");
assert.ok(from !== -1 && to > from, "the street style table moved");
// eslint-disable-next-line no-new-func
const mod = new Function(APP.slice(from, to) + fnSource("_ooOsmDrawStreets")
  + "\nreturn { _ooOsmDrawStreets, _OO_OSM_STREET_STYLE, _OO_OSM_STREET_LABELS };")();
const { _ooOsmDrawStreets, _OO_OSM_STREET_STYLE, _OO_OSM_STREET_LABELS } = mod;

function recorder() {
  const log = [];
  let cur = null;
  const ctx = {
    log, globalAlpha: 1, lineWidth: 1, strokeStyle: "", fillStyle: "", font: "", textAlign: "", textBaseline: "",
    lineCap: "", lineJoin: "", _rot: 0,
    beginPath() { cur = { moves: 0 }; log.push(["path", cur]); },
    moveTo() { cur.moves++; }, lineTo() {},
    stroke() { log.push(["stroke", this.lineWidth, this.strokeStyle]); },
    measureText(s) { return { width: s.length * 6 }; },
    save() {}, restore() { this._rot = 0; }, translate(x, y) { this._at = [x, y]; }, rotate(a) { this._rot = a; },
    strokeText() {}, fillText(s, x, y) { log.push(["label", s, this._at, this._rot]); },
  };
  return ctx;
}
const px = (la, lo) => [lo * 1000, 1000 - la * 1000];   // a plain flip: north is up
const toScreen = (r) => r.c.map(([la, lo]) => px(la, lo));
const color = (v) => v;
const sz = { w: 1000, h: 1000 };

let passed = 0;
function check(name, fn) { fn(); passed++; console.log("ok -", name); }

check("one path per class, stroked from the least to the most important", () => {
  const roads = [];
  for (let i = 0; i < 300; i++) roads.push({ k: i % 9, c: [[0.1 + i / 1000, 0.1], [0.1 + i / 1000, 0.9]] });
  const ctx = recorder();
  _ooOsmDrawStreets(ctx, roads, toScreen, color, sz);
  const paths = ctx.log.filter((e) => e[0] === "path");
  assert.strictEqual(paths.length, 9, "nine classes, nine paths, whatever the road count");
  assert.strictEqual(paths.reduce((a, p) => a + p[1].moves, 0), 300);
  const widths = ctx.log.filter((e) => e[0] === "stroke" && e[2] !== "--bg").map((e) => e[1]);
  assert.deepStrictEqual(widths, _OO_OSM_STREET_STYLE.map((s) => s[1]).reverse(), "motorways last, on top");
  assert.strictEqual(ctx.log.filter((e) => e[2] === "--bg").length, 5, "a casing under the five major classes only");
});

check("labels: one per name, never overlapping, never upside down, capped", () => {
  const roads = [];
  for (let i = 0; i < 400; i++) {
    const y = (i % 40) / 40 + 0.01, x = Math.floor(i / 40) / 10;
    roads.push({ k: i % 6, name: "Street " + (i % 150), c: [[y, x], [y + 0.02 * (i % 3 - 1), x + 0.09]] });
  }
  roads.push({ k: 7, name: "A footway", c: [[0.5, 0], [0.5, 1]] });   // a path is never labelled
  roads.push({ k: 0, name: "Westward", c: [[0.995, 0.9], [0.995, 0.1]] });   // drawn east to west
  const ctx = recorder();
  const n = _ooOsmDrawStreets(ctx, roads, toScreen, color, sz);
  const labels = ctx.log.filter((e) => e[0] === "label");
  assert.strictEqual(labels.length, n);
  assert.ok(n > 10 && n <= _OO_OSM_STREET_LABELS, `placed ${n}`);
  const names = labels.map((l) => l[1]);
  assert.strictEqual(new Set(names).size, names.length, "a name is printed once");
  assert.ok(!names.includes("A footway"));
  for (const l of labels) assert.ok(Math.abs(l[3]) <= Math.PI / 2 + 1e-9, "never upside down: " + l[1]);
  for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) {
    const [a, b] = [labels[i][2], labels[j][2]];
    assert.ok(Math.hypot(a[0] - b[0], a[1] - b[1]) >= 12, "two labels on one spot: " + labels[i][1] + " / " + labels[j][1]);
  }
  const w = labels.find((l) => l[1] === "Westward");
  assert.ok(w && Math.abs(w[3]) < 1e-9, "an east-to-west road reads left to right");
});

check("a road too short for its name, or out of sight, gets no label", () => {
  const ctx = recorder();
  const n = _ooOsmDrawStreets(ctx, [
    { k: 0, name: "A very long name for a short road", c: [[0.5, 0.5], [0.5, 0.51]] },
    { k: 0, name: "Far away", c: [[5, 5], [5, 6]] },
  ], toScreen, color, sz);
  assert.strictEqual(n, 0);
});

console.log(`${passed} passed`);
