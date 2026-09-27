// The Explore mind map and word cloud place LABELS, not points (re-walk M-13), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The cloud placed each word by its index on a golden-angle spiral and the map put every
// leaf of an arm on one ring, so 9-18 px words 60-130 px wide landed on top of one
// another. What must hold now: no two label boxes meet, a map node keeps the ANGLE the
// mind-map rules gave it (centre -> arms -> always outward) and only ever moves outward,
// and the first view frames every label. Extracted from the shipped module rather than
// re-typed: a re-typed copy would pass while the real one was broken.

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

const L = (() => {
  const m = { exports: {} };
  // No DOM here: `_mmTextWidth` falls back to its over-estimate, which is the width the
  // boxes below are measured with.
  new Function("module", "exports",
    "let _mmMeasureCtx = null;\n"
    + ["_mmTextWidth", "_mmLabelBox", "_mmHits", "_mmDeclutter", "_mmCloudPlace", "_mmFitBox"]
      .map(extract).join("\n")
    + "\nmodule.exports = { _mmTextWidth, _mmLabelBox, _mmHits, _mmDeclutter, _mmCloudPlace, _mmFitBox };")(m, m.exports);
  return m.exports;
})();

function node(label, fs, tag, extra) {
  const n = Object.assign({ id: label, label: label, fs: fs, lp: { shown: label, tag: tag || "" } }, extra || {});
  n.box = L._mmLabelBox(n, Math.max(8, fs * 0.5));
  return n;
}
function overlaps(a, b) {
  return Math.abs(a.x - b.x) * 2 < a.box.w + b.box.w
    && a.y - a.box.top < b.y + b.box.bottom && a.y + a.box.bottom > b.y - b.box.top;
}
function assertNoOverlap(nodes, what) {
  for (let i = 0; i < nodes.length; i++)
    for (let j = i + 1; j < nodes.length; j++)
      assert.ok(!overlaps(nodes[i], nodes[j]),
        `${what}: "${nodes[i].label}" (${nodes[i].x.toFixed(1)},${nodes[i].y.toFixed(1)}) overlaps `
        + `"${nodes[j].label}" (${nodes[j].x.toFixed(1)},${nodes[j].y.toFixed(1)})`);
}

// --- a label's box counts its tag line --------------------------------------------- //
const bare = node("избирателей", 12), tagged = node("избирателей", 12, "en russe");
assert.ok(bare.box.w > 12 * 5, "a word is never assumed to take no room");
assert.ok(tagged.box.bottom > bare.box.bottom, "the tag's second line is part of the box");

// --- the map: a crowded arm is pushed outward, never sideways ---------------------- //
const W = 680, H = 460, cx = W / 2, cy = H / 2;
const R1 = Math.min(W, H) * 0.30, R2 = Math.min(W, H) * 0.46;
const center = node("software", 17, "", { center: true, x: cx, y: cy });
const arms = ["código", "ayudar", "herramienta", "errors", "desarrollo", "programas"].map((w, i, a) => {
  const ang = (i / a.length) * 2 * Math.PI - Math.PI / 2;
  return node(w, 14, "en espagnol", { x: cx + R1 * Math.cos(ang), y: cy + R1 * Math.sin(ang) });
});
// Ten leaves squeezed into one arm's slice: the exact shape that stacked before.
const leaves = [];
for (let j = 0; j < 10; j++) {
  const a = -Math.PI / 2 + (Math.PI / 3) * 0.8 * ((j + 1) / 11 - 0.5);
  leaves.push(node("leaf-word-" + j, 11, "en espagnol", { x: cx + R2 * Math.cos(a), y: cy + R2 * Math.sin(a) }));
}
const order = [center, ...arms, ...leaves];
const before = order.map((n) => ({ ang: Math.atan2(n.y - cy, n.x - cx), r: Math.hypot(n.x - cx, n.y - cy) }));
assert.ok(order.some((a, i) => order.some((b, j) => j > i && overlaps(a, b))),
  "the fixture must start crowded, or it proves nothing");
L._mmDeclutter(order, cx, cy);
assertNoOverlap(order, "map");
order.forEach((n, i) => {
  if (n.center) { assert.strictEqual(n.x, cx); assert.strictEqual(n.y, cy); return; }
  const ang = Math.atan2(n.y - cy, n.x - cx), r = Math.hypot(n.x - cx, n.y - cy);
  assert.ok(Math.abs(ang - before[i].ang) < 1e-9, `"${n.label}" left its ray`);
  assert.ok(r >= before[i].r - 1e-9, `"${n.label}" moved inward`);
});

// --- the cloud: no word lands on another ------------------------------------------- //
const cloud = [];
for (let k = 0; k < 40; k++) cloud.push(node("mot" + "x".repeat(k % 9) + k, 9 + (k * 7) % 10, k % 3 ? "en russe" : ""));
L._mmCloudPlace(cloud, cx, cy);
assertNoOverlap(cloud, "cloud");
assert.ok(Math.abs(cloud[0].x - cx) < 1e-9 && Math.abs(cloud[0].y - cy) < 1e-9,
  "the heaviest word sits at the centre");

// --- the first view frames every label --------------------------------------------- //
const vb = L._mmFitBox(order, W, H);
assert.ok(vb.x <= 0 && vb.y <= 0 && vb.x + vb.w >= W && vb.y + vb.h >= H, "never smaller than the frame");
for (const n of order) {
  assert.ok(n.x - n.box.w / 2 >= vb.x && n.x + n.box.w / 2 <= vb.x + vb.w, `"${n.label}" is cut off sideways`);
  assert.ok(n.y - n.box.top >= vb.y && n.y + n.box.bottom <= vb.y + vb.h, `"${n.label}" is cut off vertically`);
}

console.log("all assertions passed");
