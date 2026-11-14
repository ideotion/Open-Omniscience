// The world map's scale bar, run as REAL code (lane N, 2026-11-13).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The bar is the only distance claim the map makes, so its arithmetic is executed against
// the shipped functions rather than asserted about their text:
//   * summed across the full width along the equator, the per-unit lengths give the
//     equator's real length (an independent physical fact, not a re-derivation);
//   * a step near a pole is shorter than one on the equator (the parallels shrink);
//   * a centre outside the globe gives 0, so the bar hides rather than guesses;
//   * the rounded length never exceeds what was measured (1, 2 or 5 x 10^k, rounded DOWN).

const assert = require("assert");
const APP = require("./app_source.js").appJs();

const _from = APP.indexOf("const EE_A1");
const _to = APP.indexOf("// The projected outline of the whole sphere");
assert.ok(_from !== -1 && _to > _from, "the projection seam was not found");
const SEAM = APP.slice(_from, _to);
function lift(name) {
  const i = APP.indexOf("function " + name + "(");
  assert.ok(i !== -1, name + " not found in the shipped map module");
  let depth = 0, j = APP.indexOf("{", i);
  for (; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}" && --depth === 0) break;
  }
  return APP.slice(i, j + 1);
}
const src = SEAM + "\n" + lift("_ooMapNiceLen") + "\n" + lift("_ooMapKmPerUnit")
  + "\nmodule.exports = { MAP_W, MAP_H, _ooMapNiceLen, _ooMapKmPerUnit };\n";
const mod = { exports: {} };
new Function("module", "exports", src)(mod, mod.exports);
const { MAP_W, MAP_H, _ooMapNiceLen, _ooMapKmPerUnit } = mod.exports;

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed++; console.log("ok   " + name); }
  catch (e) { failed++; console.log("FAIL " + name + "\n     " + e.message); }
}

check("the equator sums to its real length", () => {
  let km = 0;
  for (let x = 0.5; x < MAP_W; x += 1) km += _ooMapKmPerUnit(x, MAP_H / 2);
  const equator = 40075.017;
  assert.ok(Math.abs(km - equator) / equator < 0.005, `summed ${km.toFixed(1)} km`);
});
check("a parallel near the pole is shorter than the equator", () => {
  const eq = _ooMapKmPerUnit(MAP_W / 2, MAP_H / 2), hi = _ooMapKmPerUnit(MAP_W / 2, MAP_H * 0.08);
  assert.ok(hi > 0 && hi < eq * 0.8, `equator ${eq}, high latitude ${hi}`);
});
check("a centre outside the globe gives 0 (the bar hides)", () => {
  assert.strictEqual(_ooMapKmPerUnit(2, 2), 0);
  assert.strictEqual(_ooMapKmPerUnit(MAP_W - 2, MAP_H - 2), 0);
});
check("lengths round down to 1, 2 or 5 x 10^k", () => {
  assert.strictEqual(_ooMapNiceLen(1234), 1000);
  assert.strictEqual(_ooMapNiceLen(2600), 2000);
  assert.strictEqual(_ooMapNiceLen(7999), 5000);
  assert.strictEqual(_ooMapNiceLen(0.37), 0.2);
  assert.strictEqual(_ooMapNiceLen(0), 0);
  assert.strictEqual(_ooMapNiceLen(NaN), 0);
  for (const m of [0.013, 3.3, 47, 512, 9999, 123456]) assert.ok(_ooMapNiceLen(m) <= m, String(m));
});

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
