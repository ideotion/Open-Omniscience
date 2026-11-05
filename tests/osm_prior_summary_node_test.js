// The planet's past says where it came from, and a cut without a current summary asks for one once (v0.6.0 R435), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What must NOT happen is most of it:
//
//   * a computed answer is never worded as if it came from the summary, and a summary answer never as if it were recomputed;
//   * the reason a summary was not used is named (never built, out of date, no table), and nothing is said when there is no prior;
//   * the request to build is ONE POST per country per session (a GET never writes), never sent for an answer that came from the summary
//     or for a country with no history cut, and the page refetches only when the cheap state read says «current»;
//   * a build that ends without a current summary leaves the computed answer in place: no refetch, no endless polling.
//
// EXTRACTED from the shipped module rather than re-typed.

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
function extractConst(name, end) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  const stop = end || ";\n";
  return APP.slice(at, APP.indexOf(stop, at) + stop.length - 1);
}

const src =
  extractConst("esc") + "\n" +
  "var window = {};\n" +
  "var calls = [], answers = [], timers = [];\n" +
  "async function api(u, o) { calls.push((o && o.method ? o.method : 'GET') + ' ' + u); const a = answers.shift(); if (a instanceof Error) throw a; return a; }\n" +
  "function setTimeout(fn) { fn(); }\n" +
  "function ooIsoDate(s) { return 'D(' + String(s == null ? '' : s).slice(0, 10) + ')'; }\n" +
  "function osmCompTf(s, v) { return s.replace(/\\{(\\w+)\\}/g, (_, k) => v[k]); }\n" +
  "const _osmPriorAsked = new Set();\n" +
  extract("_osmPriorSource") + "\n" + extract("_osmPriorEnsure") + "\n" +
  "module.exports = { _osmPriorSource, _osmPriorEnsure, calls, answers, asked: _osmPriorAsked };";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html).replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();
const tick = () => new Promise((r) => setImmediate(r));
const computed = (state, extra) => ({ available: true, source: "computed", vintage: "2025-01-01T00:00:00+00:00", summary: Object.assign({ state, building: false }, extra || {}) });

(async () => {
  // ---- the line --------------------------------------------------------------------------------------------------
  assert.strictEqual(R._osmPriorSource({ available: false, reason: "no-history-cut" }), "", "a prior that is not available has no source to state");
  assert.strictEqual(R._osmPriorSource(null), "");
  const stored = visible(R._osmPriorSource({ available: true, source: "summary", vintage: "2025-01-01T00:00:00+00:00", summary: { state: "current", built_at: "2025-02-03T04:05:06+00:00" } }));
  assert.ok(stored.includes("monthly summary stored D(2025-02-03)") && stored.includes("history file dated D(2025-01-01)"), stored);
  assert.ok(!stored.includes("Computed from the history rows"), "a stored answer was worded as computed");
  for (const [state, word] of [["not-built", "no monthly summary of this cut is stored yet"], ["stale-cut", "out of date"], ["stale-rule", "out of date"], ["no-summary-table", "no table for the monthly summary"]]) {
    const line = visible(R._osmPriorSource(computed(state)));
    assert.ok(line.startsWith("Computed from the history rows on this read") && line.includes(word), state + ": " + line);
    assert.ok(!line.includes("Read from the monthly summary"), "a computed answer was worded as stored");
  }
  assert.ok(visible(R._osmPriorSource(computed("not-built", { building: true }))).includes("A monthly summary is being built"));
  assert.ok(!visible(R._osmPriorSource(computed("not-built"))).includes("is being built"), "nothing is being built, and it was said to be");
  assert.ok(R._osmPriorSource(computed("not-built")).includes('data-osm-prior-source="computed"'));

  // ---- the request -----------------------------------------------------------------------------------------------
  let fetched = 0;
  const go = () => { fetched++; };
  // never for a stored answer, a missing prior, or a cut that does not exist
  R._osmPriorEnsure("ZZZ", { available: true, source: "summary", summary: { state: "current" } }, go);
  R._osmPriorEnsure("ZZZ", { available: false, reason: "no-history-cut" }, go);
  R._osmPriorEnsure("ZZZ", null, go);
  R._osmPriorEnsure("", computed("not-built"), go);
  await tick();
  assert.deepStrictEqual(R.calls, [], "a request was sent that cannot build anything");
  // once, and the page refetches only when the state read says current
  R.answers.push({ started: true, status: "building" }, { state: "not-built", building: true }, { state: "current", building: false });
  R._osmPriorEnsure("ZZZ", computed("not-built"), go);
  R._osmPriorEnsure("ZZZ", computed("not-built"), go);   // a second ask for the same country in the same session is not sent
  for (let i = 0; i < 6; i++) await tick();
  assert.deepStrictEqual(R.calls, ["POST /api/osm/countries/ZZZ/prior-summary", "GET /api/osm/countries/ZZZ/prior-summary", "GET /api/osm/countries/ZZZ/prior-summary"]);
  assert.strictEqual(fetched, 1, "the page did not refetch when the summary became current (or refetched twice)");
  // a build that ends without a current summary leaves the computed answer: no refetch, no more polling
  R.calls.length = 0; fetched = 0;
  R.answers.push({ started: true, status: "building" }, { state: "stale-cut", building: false });
  R._osmPriorEnsure("YYY", computed("stale-cut"), go);
  for (let i = 0; i < 6; i++) await tick();
  assert.deepStrictEqual(R.calls, ["POST /api/osm/countries/YYY/prior-summary", "GET /api/osm/countries/YYY/prior-summary"]);
  assert.strictEqual(fetched, 0, "the page refetched although no summary became current");
  // a lane cut by an older build has no table for the summary: the build adds it, so that is asked for too
  R.calls.length = 0;
  R.answers.push({ started: true, status: "building" }, { state: "current", building: false });
  R._osmPriorEnsure("WWW", computed("no-summary-table"), go);
  for (let i = 0; i < 4; i++) await tick();
  assert.strictEqual(R.calls[0], "POST /api/osm/countries/WWW/prior-summary", "an old lane was never offered a summary");
  // a refused request ends quietly
  R.calls.length = 0;
  R.answers.push(new Error("409"));
  R._osmPriorEnsure("XXX", computed("not-built"), go);
  for (let i = 0; i < 4; i++) await tick();
  assert.deepStrictEqual(R.calls, ["POST /api/osm/countries/XXX/prior-summary"]);

  console.log("all checks passed");
})().catch((e) => { console.error(e); process.exit(1); });
