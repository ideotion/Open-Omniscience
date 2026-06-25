/*
 * Node test for src/static/ooviz.js — the honest-chart primitives (ported from the
 * MIT research set) PLUS statSeriesPaths, the Phase B2 consumer of the
 * src/stats/series.py to_chart_series output. Asserts the honesty rules live in the
 * SHAPE of the output: gaps break the line (never bridged), a comparability segment
 * break is NEVER joined, AREA-honest symbol sizing, deterministic ticks/PRNG.
 * Run by tests/test_ooviz.py (and standalone: `node tests/ooviz_node_test.js`).
 * GPL-3.0-or-later.
 */
"use strict";
const assert = require("node:assert/strict");
const path = require("path");
const V = require(path.join(__dirname, "..", "src", "static", "ooviz.js"));

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("ok  - " + name);
}

const id = (v) => v; // identity scales for pure-logic path checks

// --------------------------------------------------------------------------- //
// Primitives (ported — same guarantees as the research set).
// --------------------------------------------------------------------------- //
test("isMissing flags only true gaps, never zero", () => {
  assert.equal(V.isMissing(null), true);
  assert.equal(V.isMissing(undefined), true);
  assert.equal(V.isMissing(NaN), true);
  assert.equal(V.isMissing(0), false); // zero is a value, not a gap
  assert.equal(V.isMissing(-1.5), false);
});

test("linearScale maps + inverts; zero-width domain is finite", () => {
  const s = V.linearScale(0, 10, 0, 100);
  assert.equal(s(5), 50);
  assert.equal(s.invert(50), 5);
  assert.equal(Number.isFinite(V.linearScale(4, 4, 0, 100)(4)), true);
});

test("sqrtAreaScale encodes by AREA (honest symbols)", () => {
  const r = V.sqrtAreaScale(100, 20);
  assert.equal(r(0), 0);
  assert.equal(r(100), 20);
  assert.equal(r(25), 10); // sqrt(25/100) = 0.5 => half radius, quarter area
  assert.ok(Math.abs(r(40) / r(10) - 2) < 1e-12); // 4x value => 2x radius, never 4x
});

test("niceTicks gives clean 1-2-5 steps without float drift", () => {
  assert.deepEqual(V.niceTicks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(V.niceTicks(0, 1, 5), [0, 0.2, 0.4, 0.6, 0.8, 1]);
  assert.deepEqual(V.niceTicks(10, 0, 5), [0, 2, 4, 6, 8, 10]); // reversed input ok
});

test("mulberry32 is deterministic + seed-sensitive", () => {
  const a = V.mulberry32(1234);
  const b = V.mulberry32(1234);
  const seqA = [a(), a(), a()];
  assert.deepEqual(seqA, [b(), b(), b()]); // same seed => identical pixels
  const c = V.mulberry32(5678);
  assert.notDeepEqual([c(), c(), c()], seqA); // different seed => different
});

test("pathWithGaps breaks at a gap and never bridges it (H2)", () => {
  const d = V.pathWithGaps(
    [
      { x: 0, y: 1 },
      { x: 1, y: 2 },
      { x: 2, y: null }, // gap
      { x: 3, y: 4 },
    ],
    id,
    id
  );
  assert.equal((d.match(/M/g) || []).length, 2); // two subpaths => gap honoured
});

test("binCounts1D buckets correctly and ignores missing", () => {
  assert.deepEqual(V.binCounts1D([1, 1, 2, 3, NaN, 4], { min: 1, max: 5, count: 4 }), [2, 1, 1, 1]);
});

test("fiveNumberSummary uses R-7 quantiles and reports n", () => {
  const s = V.fiveNumberSummary([4, 2, 1, 3]);
  assert.equal(s.median, 2.5);
  assert.equal(s.n, 4);
  assert.equal(V.fiveNumberSummary([]).n, 0);
});

// --------------------------------------------------------------------------- //
// statSeriesPaths — the Phase B2 consumer of to_chart_series.
// --------------------------------------------------------------------------- //
test("statSeriesPaths: one subpath per segment, gaps break within a segment", () => {
  // A single comparability segment with a gap in the middle.
  const series = {
    segments: [
      {
        unit: "million euro",
        base_year: null,
        adjustment: "SA",
        points: [
          { period: "2019", t: 2019, value: 10 },
          { period: "2020", t: 2020, value: null }, // a gap
          { period: "2021", t: 2021, value: 12 },
        ],
      },
    ],
  };
  const paths = V.statSeriesPaths(series, id, id);
  assert.equal(paths.length, 1); // one segment => one path entry
  assert.equal((paths[0].d.match(/M/g) || []).length, 2); // the gap broke the line
  assert.equal(paths[0].unit, "million euro"); // metadata carried
  assert.equal(paths[0].adjustment, "SA");
  assert.equal(paths[0].n, 3);
});

test("statSeriesPaths: a comparability break is NEVER joined (separate paths)", () => {
  // Two segments (an Index 2010=100 run, then a 2015=100 run) must not connect.
  const series = {
    segments: [
      {
        unit: "Index",
        base_year: "2010",
        adjustment: null,
        points: [
          { period: "2018", t: 2018, value: 100 },
          { period: "2019", t: 2019, value: 102 },
        ],
      },
      {
        unit: "Index",
        base_year: "2015",
        adjustment: null,
        points: [
          { period: "2020", t: 2020, value: 50 },
          { period: "2021", t: 2021, value: 51 },
        ],
      },
    ],
  };
  const paths = V.statSeriesPaths(series, id, id);
  assert.equal(paths.length, 2); // TWO separate paths — the break is never bridged
  assert.equal(paths[0].base_year, "2010");
  assert.equal(paths[1].base_year, "2015");
  // Each segment is its own continuous run (no gap within) => exactly one M each.
  assert.equal((paths[0].d.match(/M/g) || []).length, 1);
  assert.equal((paths[1].d.match(/M/g) || []).length, 1);
  // The two segments are NOT in one path string (no single d spans both base years).
  assert.notEqual(paths[0].d, paths[0].d + paths[1].d);
});

test("statSeriesPaths: empty / missing series is honest, not a throw", () => {
  assert.deepEqual(V.statSeriesPaths({ segments: [] }, id, id), []);
  assert.deepEqual(V.statSeriesPaths(null, id, id), []);
  assert.deepEqual(V.statSeriesPaths({}, id, id), []);
});

// --------------------------------------------------------------------------- //
// statChartGeometry — the pure chart math (domains, scales, paths, ticks).
// --------------------------------------------------------------------------- //
test("statChartGeometry: domains + ticks + one path per comparability segment", () => {
  const series = {
    segments: [
      {
        unit: "Index", base_year: "2010", adjustment: null,
        points: [{ t: 2018, value: 100 }, { t: 2019, value: 110 }],
      },
      {
        unit: "Index", base_year: "2015", adjustment: null,
        points: [{ t: 2020, value: 50 }, { t: 2021, value: 52 }],
      },
    ],
  };
  const g = V.statChartGeometry(series, { width: 600, height: 200 });
  assert.deepEqual(g.timeDomain, [2018, 2021]); // spans all points
  assert.deepEqual(g.valueDomain, [50, 110]); // min/max of plottable values
  assert.equal(g.paths.length, 2); // one subpath per comparability segment (break not joined)
  assert.equal(g.nSegments, 2);
  assert.equal(g.nPoints, 4);
  assert.ok(g.xTicks.length > 0 && g.yTicks.length > 0);
  // y ticks carry pixel positions inside the plot box.
  for (const t of g.yTicks) assert.ok(t.y >= g.pad.t - 1e-6 && t.y <= g.height - g.pad.b + 1e-6);
});

test("statChartGeometry: a gap is ignored by the value domain, kept in the time domain", () => {
  const series = {
    segments: [
      {
        unit: null, base_year: null, adjustment: null,
        points: [{ t: 2019, value: 10 }, { t: 2020, value: null }, { t: 2021, value: 30 }],
      },
    ],
  };
  const g = V.statChartGeometry(series);
  assert.deepEqual(g.valueDomain, [10, 30]); // the null does not pull the domain toward 0
  assert.deepEqual(g.timeDomain, [2019, 2021]); // but the gap year still bounds the x axis
  assert.equal(g.paths.length, 1);
  assert.equal((g.paths[0].d.match(/M/g) || []).length, 2); // the gap broke the line
});

test("statChartGeometry: empty series is honest (no throw, a unit box)", () => {
  const g = V.statChartGeometry({ segments: [] });
  assert.deepEqual(g.paths, []);
  assert.equal(g.nPoints, 0);
  assert.deepEqual(g.timeDomain, [0, 1]);
  assert.deepEqual(g.valueDomain, [0, 1]);
});

// --------------------------------------------------------------------------- //
// choroplethData / symbolRadii — the §5B "normalized-only" map data layer.
// --------------------------------------------------------------------------- //
test("periodToYear: annual/quarter/month/day parse; junk => NaN", () => {
  assert.equal(V.periodToYear("2019"), 2019);
  assert.equal(V.periodToYear("2019-Q3"), 2019 + 2 / 4);
  assert.equal(V.periodToYear("2019-M07"), 2019 + 6 / 12);
  assert.ok(Math.abs(V.periodToYear("2019-07-01") - (2019 + 6 / 12)) < 1e-9);
  assert.ok(Number.isNaN(V.periodToYear("not-a-period")));
});

test("choroplethData: comparability gate — odd basis is no-data, never recoloured", () => {
  // Three areas share '% of GDP'; one reports in 'current US$' — it must NOT be
  // coloured on the same scale (it would be comparable:false, no-data).
  const rows = [
    { ref_area: "FR", value: 2.1, unit: "% of GDP", base_year: null, adjustment: null, time_period: "2020" },
    { ref_area: "DE", value: 1.4, unit: "% of GDP", base_year: null, adjustment: null, time_period: "2020" },
    { ref_area: "IT", value: 3.0, unit: "% of GDP", base_year: null, adjustment: null, time_period: "2020" },
    { ref_area: "XX", value: 9000, unit: "current US$", base_year: null, adjustment: null, time_period: "2020" },
  ];
  const d = V.choroplethData(rows, { kind: "normalized" });
  assert.equal(d.mode, "choropleth");
  assert.equal(d.basis.unit, "% of GDP"); // the modal basis won
  assert.equal(d.comparableCount, 3);
  assert.equal(d.incomparableCount, 1);
  assert.deepEqual(d.domain, [1.4, 3.0]); // the 9000 outlier never stretches the scale
  const xx = d.cells.find((c) => c.area === "XX");
  assert.equal(xx.comparable, false);
  assert.ok(/unit/.test(xx.reason)); // honest reason names the difference
});

test("choroplethData: a missing value is no-data with its own reason (never zero)", () => {
  const rows = [
    { ref_area: "FR", value: 2.0, unit: "%", base_year: null, adjustment: null, time_period: "2021" },
    { ref_area: "DE", value: null, unit: "%", base_year: null, adjustment: null, time_period: "2021" },
  ];
  const d = V.choroplethData(rows);
  assert.equal(d.noValueCount, 1);
  const de = d.cells.find((c) => c.area === "DE");
  assert.equal(de.comparable, false);
  assert.ok(/no value/.test(de.reason));
  assert.deepEqual(d.domain, [2.0, 2.0]); // domain ignores the gap; zero-width is fine
});

test("choroplethData: keeps each area's LATEST period when none requested", () => {
  const rows = [
    { ref_area: "FR", value: 1.0, unit: "%", base_year: null, adjustment: null, time_period: "2019" },
    { ref_area: "FR", value: 2.5, unit: "%", base_year: null, adjustment: null, time_period: "2021" },
    { ref_area: "FR", value: 1.8, unit: "%", base_year: null, adjustment: null, time_period: "2020" },
  ];
  const d = V.choroplethData(rows);
  assert.equal(d.cells.length, 1);
  assert.equal(d.cells[0].value, 2.5); // 2021 wins
  assert.equal(d.cells[0].period, "2021");
});

test("choroplethData: opts.period filters to exactly that period", () => {
  const rows = [
    { ref_area: "FR", value: 1.0, unit: "%", base_year: null, adjustment: null, time_period: "2019" },
    { ref_area: "FR", value: 2.5, unit: "%", base_year: null, adjustment: null, time_period: "2021" },
  ];
  const d = V.choroplethData(rows, { period: "2019" });
  assert.equal(d.cells.length, 1);
  assert.equal(d.cells[0].value, 1.0);
});

test("choroplethData: a LEVEL refuses the choropleth (mode symbols)", () => {
  const rows = [
    { ref_area: "CN", value: 1.4e9, unit: "persons", base_year: null, adjustment: null, time_period: "2022" },
    { ref_area: "FR", value: 6.8e7, unit: "persons", base_year: null, adjustment: null, time_period: "2022" },
  ];
  const d = V.choroplethData(rows, { kind: "level" });
  assert.equal(d.mode, "symbols");
  assert.equal(d.refusedChoropleth, true);
  assert.ok(/proportional symbols/.test(d.refusalReason));
});

test("symbolRadii: AREA ∝ value (honest), incomparable/negative => not shown", () => {
  const cells = [
    { area: "A", value: 100, comparable: true, reason: null },
    { area: "B", value: 25, comparable: true, reason: null }, // sqrt(25/100)=0.5 => half radius
    { area: "C", value: 5, comparable: false, reason: "unit differs" },
    { area: "D", value: -3, comparable: true, reason: null },
  ];
  const r = V.symbolRadii(cells, 20);
  const A = r.find((x) => x.area === "A");
  const B = r.find((x) => x.area === "B");
  assert.equal(A.r, 20);
  assert.equal(B.r, 10); // 4x value => 2x radius (area-honest), never 4x
  assert.equal(r.find((x) => x.area === "C").shown, false); // incomparable not plotted
  assert.equal(r.find((x) => x.area === "D").shown, false); // negative not a proportional symbol
  assert.ok(/negative/.test(r.find((x) => x.area === "D").reason));
});

test("choroplethData: empty input is honest (no throw, no basis)", () => {
  const d = V.choroplethData([], {});
  assert.deepEqual(d.cells, []);
  assert.equal(d.basis, null);
  assert.equal(d.domain, null);
  assert.equal(d.comparableCount, 0);
});

console.log("\n" + passed + " tests passed.");
console.log("OOVIZ OK");
