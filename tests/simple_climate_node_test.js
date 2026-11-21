// Simple view, Numbers -> Climate (row 280, the simple-view twin of row 275), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What must hold: a dataset whose latest attempt failed is MARKED, never left reading as freshly
// fetched; the success date is kept beside the failure, never replaced; the kill switch is named
// airplane mode; every failure token the server can write has its own words; an unknown token is
// never echoed back. Extracted from the shipped simple.js, never re-typed.

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..");
const SRC = fs.readFileSync(path.join(ROOT, "src", "static", "simple", "simple.js"), "utf8");

function extract(name) {
  const at = SRC.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = SRC.indexOf("{", SRC.indexOf(")", at));
  let d = 0, j = open;
  for (; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return SRC.slice(at, j);
}
const R = new Function("t", extract("climateRows") + "\n" + extract("climateFailureWords") +
  "\nreturn { climateRows, climateFailureWords };")((s) => s);

const ok = { dataset: "oni", host: "www.cpc.ncep.noaa.gov", stored: { stored_rows: 900 },
  last_fetch: { fetched_at: "2026-11-20T08:00:00+00:00" } };
const failedAfterSuccess = { dataset: "gistemp", host: "data.giss.nasa.gov", stored: { stored_rows: 10 },
  last_fetch: { fetched_at: "2026-11-19T08:00:00+00:00", last_failure: { failed_at: "2026-11-21T10:00:00+00:00", reason: "kill_switch" } } };
const otherSeries = { dataset: "gistemp", host: "data.giss.nasa.gov", stored: { stored_rows: 5 },
  last_fetch: { fetched_at: "2026-11-20T09:00:00+00:00" } };

{
  const rows = R.climateRows([ok, failedAfterSuccess, otherSeries]);
  const by = Object.fromEntries(rows.map((r) => [r.dataset, r]));
  assert.strictEqual(by.oni.failed, null, "no failure, no mark");
  assert.strictEqual(by.oni.last, "2026-11-20T08:00:00+00:00");
  assert.ok(by.gistemp.failed, "a failed unit marks its dataset");
  assert.strictEqual(by.gistemp.failed.reason, "kill_switch");
  assert.strictEqual(by.gistemp.failed.at, "2026-11-21T10:00:00+00:00");
  assert.strictEqual(by.gistemp.last, "2026-11-20T09:00:00+00:00", "the success date stays, never replaced by the failure");
  assert.strictEqual(by.gistemp.stored, 15, "stored values are still counted");
  assert.strictEqual(by.gistemp.failing, 1, "one series failing");
  assert.strictEqual(by.gistemp.tried, 2, "of two series with a record");
  assert.strictEqual(by.oni.failing, 0);
  assert.strictEqual(R.climateRows([{ dataset: "owid", stored: {} }])[0].tried, 0, "a series never fetched is not counted as tried");
}
{
  // The newest of two failures is the one shown; a missing failed_at never wins over a dated one.
  const a = { dataset: "usgs", stored: {}, last_fetch: { last_failure: { failed_at: "2026-11-21T01:00:00+00:00", reason: "timeout" } } };
  const b = { dataset: "usgs", stored: {}, last_fetch: { last_failure: { failed_at: "2026-11-21T02:00:00+00:00", reason: "http_5xx" } } };
  const c = { dataset: "usgs", stored: {}, last_fetch: { last_failure: { reason: "other" } } };
  const [row] = R.climateRows([a, b, c]);
  assert.strictEqual(row.failed.reason, "http_5xx");
  assert.strictEqual(row.last, null, "a failure-only record has no fetch date");
  assert.deepStrictEqual(R.climateRows(undefined), [], "no units, no rows");
  assert.strictEqual(R.climateRows([{ dataset: "owid", last_fetch: { last_failure: "junk" } }])[0].failed, null, "a malformed failure is ignored, not shown as an object");
}
{
  assert.strictEqual(R.climateFailureWords("kill_switch"), "refused by airplane mode; no request was sent");
  const py = fs.readFileSync(path.join(ROOT, "src", "stats", "climate.py"), "utf8");
  const start = py.indexOf("FAILURE_REASONS = (");
  const tokens = [...py.slice(start, py.indexOf("\n)", start)).matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1]);
  assert.ok(tokens.length >= 15, "FAILURE_REASONS not read: " + tokens);
  const fallback = R.climateFailureWords("no-such-token");
  for (const tok of tokens.filter((x) => x !== "other")) assert.notStrictEqual(R.climateFailureWords(tok), fallback, tok + " has no words in the simple view");
  assert.strictEqual(R.climateFailureWords("<img src=x>"), fallback, "an unknown token is never echoed");
}
console.log("simple climate: all checks passed");
