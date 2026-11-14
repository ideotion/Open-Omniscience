// Lane N round 2 (the journalist walk 2026-09-30, 4f): an ooChart x label names a calendar
// unit, so it sits at the start of that unit. Lifts _msTickSnap and _msLabel out of
// app-markets.js and checks the snapped tick is the midnight / first of the month its label names.
const fs = require("fs"), path = require("path"), assert = require("assert");
const src = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-markets.js"), "utf8");
function extract(name) {
  const i = src.indexOf(`function ${name}(`);
  assert.ok(i >= 0, `${name} not found`);
  let d = 0, j = src.indexOf("{", i);
  for (let k = j; k < src.length; k++) {
    if (src[k] === "{") d++;
    else if (src[k] === "}") { d--; if (d === 0) return src.slice(i, k + 1); }
  }
  throw new Error("unbalanced " + name);
}
const { _msTickSnap, _msLabel } = new Function(extract("_msTickSnap") + "\n" + extract("_msLabel")
  + "\nreturn {_msTickSnap, _msLabel};")();
const DAY = 864e5;
let n = 0;
// A five-day window: the even fraction 1/3 of the way in lands at 08:00, the label says the day.
const t0 = Date.UTC(2026, 7, 1), span = 5 * DAY;
const raw = t0 + span / 3 + 1;
const snapped = _msTickSnap(raw, span);
assert.strictEqual(snapped % DAY, 0, "a day label sits on its midnight"); n++;
assert.strictEqual(new Date(snapped).toISOString().slice(0, 10), _msLabel(snapped, span)); n++;
// A two-year window: month labels sit on the first of the month.
const s2 = _msTickSnap(Date.UTC(2025, 3, 20), 730 * DAY);
assert.strictEqual(new Date(s2).toISOString().slice(0, 10), "2025-05-01", "nearest month start"); n++;
const s3 = _msTickSnap(Date.UTC(2025, 3, 10), 730 * DAY);
assert.strictEqual(new Date(s3).toISOString().slice(0, 10), "2025-04-01"); n++;
// A short window keeps its even spacing: the minute label is the moment itself.
const s4 = Date.UTC(2026, 7, 1, 13, 37);
assert.strictEqual(_msTickSnap(s4, DAY), s4, "under two days nothing moves"); n++;
// Even ticks over 92 days: every snapped tick is a midnight and labels never repeat.
const T0 = Date.UTC(2026, 0, 3, 7), T1 = T0 + 80 * DAY, seen = new Set();
for (let g = 0; g <= 6; g++) {
  const ms = _msTickSnap(T0 + (T1 - T0) * g / 6, T1 - T0);
  assert.strictEqual(ms % DAY, 0); seen.add(_msLabel(ms, T1 - T0));
}
assert.strictEqual(seen.size, 7); n++;
console.log(`chart_tick_snap_node_test: ${n} checks passed`);
