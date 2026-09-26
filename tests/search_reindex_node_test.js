// The search re-index's status line (S04-07 S8), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// `_searchReindexStatusText` is the one place the operator reads what the search re-index
// did, so what it must NOT say matters as much as what it says: a store whose triggers were
// never upgraded is named for its cause and its fix (it must not read "0 re-indexed"), an
// error never prints the code the server stored, a run whose size is not counted yet draws
// no "0 of 0", zero re-indexed articles are not printed as a figure mid-run, articles left
// alone for a missing segmenter are said only when there are some, and "paused for an
// import" is not the same fact as "paused".
//
// EXTRACTED from the shipped module rather than re-typed: a re-typed copy would pass
// while the real function was broken.

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

const { _searchReindexStatusText: line } = (() => {
  const m = { exports: {} };
  new Function("module", "exports",
    extract("_searchReindexStatusText") + "\nmodule.exports = { _searchReindexStatusText };")(m, m.exports);
  return m.exports;
})();

const id = (s) => s;
// A translator that MARKS what it translated, so a segment that skipped t() shows.
const mark = (s) => "«" + s + "»";
const run = (over) => Object.assign(
  { state: "running", cursor: null, max_id: 0, percent: 0, articles_total: 0, articles_checked: 0,
    tally: {}, running: true, parked_for_exclusive: false, error: null },
  over || {});
const report = (over) => Object.assign(
  { articles_checked: 0, articles_reindexed: 0, by_script: {}, unsegmented_by_a_missing_segmenter: 0 },
  over || {});

// --- nothing to say, nothing said ---------------------------------------------- //
assert.strictEqual(line(null, null, id), "");
assert.strictEqual(line(run(), null, id), "", "a run whose size is not counted yet must not print a count");

// --- a store never upgraded names its cause and its fix, and prints no figure ------- //
const raw = line(run({ state: "error", running: false, error: "index-not-upgraded", articles_total: 9 }), null, id);
assert.ok(raw.includes("has not been upgraded") && raw.includes("Restart the app"), raw);
assert.ok(!/\d/.test(raw), "a refusal read as a result: " + raw);

// --- an error has its own sentence; the stored code is never printed --------------- //
const err = line(run({ state: "error", running: false, error: "failed", articles_total: 9 }), null, id);
assert.ok(err.startsWith("The search re-index stopped on an error"), err);
assert.ok(!err.includes("failed"), "the stored error code reached the line: " + err);

// --- a finished run reads its report ------------------------------------------------- //
assert.strictEqual(line(run({ state: "done", running: false }), null, id), "done",
  "without its report a finished run claims nothing it cannot show");
const done = line(run({ state: "done", running: false }),
  report({ articles_checked: 10, articles_reindexed: 4, by_script: { arabic: 2, chinese: 2, japanese: 0 } }), id);
assert.strictEqual(done, "Articles checked: 10 · re-indexed: 4 (Arabic: 2 · Chinese: 2 · Japanese: 0)");
const bare = line(run({ state: "done", running: false }), {}, id);
assert.strictEqual(bare, "Articles checked: 0 · re-indexed: 0 (Arabic: 0 · Chinese: 0 · Japanese: 0)",
  "a missing report field must read as 0, never NaN or undefined");
const missing = line(run({ state: "done", running: false }),
  report({ articles_checked: 3, unsegmented_by_a_missing_segmenter: 2 }), id);
assert.ok(missing.endsWith(" · Indexed without word splitting, their segmenter is no longer installed: 2"), missing);

// --- a running re-index ---------------------------------------------------------------- //
const mid = line(run({ articles_total: 10, articles_checked: 5, percent: 50, tally: { articles_reindexed: 3 } }), null, id);
assert.strictEqual(mid, "Articles checked: 5 of 10 (50%) · Re-indexed: 3");
const quiet = line(run({ articles_total: 10, articles_checked: 1, percent: 10 }), null, id);
assert.strictEqual(quiet, "Articles checked: 1 of 10 (10%)", "zero re-indexed must not be printed as a figure");

// --- "paused for an import" and "paused" are two different facts -------------------- //
const parked = line(run({ articles_total: 4, articles_checked: 2, percent: 50, parked_for_exclusive: true }), null, id);
assert.ok(parked.endsWith("paused for an import"), parked);
const paused = line(run({ state: "paused", running: false, articles_total: 4, articles_checked: 2, percent: 50 }), null, id);
assert.ok(paused.endsWith(" · paused") && !paused.includes("import"), paused);

// --- every segment went through the translator ----------------------------------------- //
const segs = [
  line(run({ state: "error", error: "index-not-upgraded" }), null, mark),
  line(run({ state: "error", error: "failed" }), null, mark),
  line(run({ state: "done" }), null, mark),
  line(run({ state: "done" }), report(), mark),
  ...line(run({ articles_total: 2, articles_checked: 1, parked_for_exclusive: true, tally: { articles_reindexed: 1 } }), null, mark).split(" · "),
  ...line(run({ state: "paused", articles_total: 2, articles_checked: 1 }), null, mark).split(" · "),
];
for (const s of segs) {
  assert.ok(s.startsWith("«") && s.endsWith("»"), "a segment skipped t(): " + s);
}
// The done line holds " · " inside its own sentence, so it is checked whole: exactly two
// translated sentences, the second one the missing-segmenter count.
const two = line(run({ state: "done" }), report({ unsegmented_by_a_missing_segmenter: 1 }), mark);
assert.ok(/^«[^«»]*» · «[^«»]*»$/.test(two), "a segment skipped t(): " + two);

console.log("search re-index status line: all assertions passed");
