// The keyword fold's status line (Q416 = a), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// `_foldStatusText` is the one place the operator reads what the fold did, so what it
// must NOT say matters as much as what it says: a refusal is named for its cause (an
// install with lemmatisation off must not read "0 keywords folded"), an error never prints
// what the server stored in `error` (a code, but the line has its own sentence), a run
// whose size is not counted yet draws no "0 of 0", and "paused for an import" is not the
// same fact as "paused". A source-level check cannot tell those apart, so this runs it.
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

const { _foldStatusText } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", extract("_foldStatusText") + "\nmodule.exports = { _foldStatusText };")(m, m.exports);
  return m.exports;
})();

const id = (s) => s;
// A translator that MARKS what it translated, so a segment that skipped t() shows.
const mark = (s) => "«" + s + "»";
const run = (over) => Object.assign(
  { state: "running", phase: "fold", keywords_total: 0, keywords_done: 0, percent: 0,
    tally: {}, running: true, parked_for_exclusive: false, refusal: null, error: null },
  over || {});

// --- nothing to say, nothing said ---------------------------------------------- //
assert.strictEqual(_foldStatusText(null, null, id), "");
assert.strictEqual(_foldStatusText(run(), null, id), "",
  "a run whose size is not counted yet must not print a count");

// --- a refusal names its cause, and prints no figure ------------------------------ //
const off = _foldStatusText(run({ state: "idle", running: false, refusal: "lemmatisation-off" }), null, id);
assert.ok(off.includes("OO_EXTRACT_LEMMA=0"), off);
assert.ok(!/\d+ of|folded:/.test(off), "a refusal read as a result: " + off);
const none = _foldStatusText(run({ state: "idle", running: false, refusal: "no-lemmatiser" }), null, id);
assert.ok(none.startsWith("No lemmatiser is installed"), none);
// A refusal outranks whatever state the manager also reports.
const refusedDone = _foldStatusText(run({ state: "done", refusal: "lemmatisation-off" }), { fold: {} }, id);
assert.ok(refusedDone.startsWith("Lemmatisation is off"), refusedDone);

// --- an error has its own sentence; the stored code is never printed --------------- //
const err = _foldStatusText(run({ state: "error", running: false, error: "failed", keywords_total: 9 }), null, id);
assert.ok(err.startsWith("The fold stopped on an error"), err);
assert.ok(!err.includes("failed"), "the stored error code reached the line: " + err);

// --- a finished run reads its report, and counts merged rows as moved --------------- //
assert.strictEqual(_foldStatusText(run({ state: "done", running: false }), null, id), "done",
  "without its report a finished run claims nothing it cannot show");
const done = _foldStatusText(
  run({ state: "done", running: false }),
  { fold: { keywords_folded: 3, mentions_moved: 5, mentions_merged: 2 }, language: { relanguaged: 4 } },
  id);
assert.strictEqual(done, "Keywords folded: 3 · mentions moved: 7 · keywords whose language changed: 4");
const bare = _foldStatusText(run({ state: "done", running: false }), { fold: {} }, id);
assert.strictEqual(bare, "Keywords folded: 0 · mentions moved: 0 · keywords whose language changed: 0",
  "a missing report field must read as 0, never NaN or undefined");

// --- a running fold ------------------------------------------------------------------ //
const mid = _foldStatusText(
  run({ keywords_total: 10, keywords_done: 5, percent: 50, tally: { mentions_moved: 4, mentions_merged: 1 } }), null, id);
assert.strictEqual(mid, "Keywords checked: 5 of 10 (50%) · Mentions moved: 5");
const quiet = _foldStatusText(run({ keywords_total: 10, keywords_done: 1, percent: 10 }), null, id);
assert.strictEqual(quiet, "Keywords checked: 1 of 10 (10%)", "zero moved must not be printed as a figure");

// --- the language pass replaces the count, it does not add to it -------------------- //
const lang = _foldStatusText(run({ phase: "language", keywords_total: 10, keywords_done: 10, percent: 100 }), null, id);
assert.strictEqual(lang, "Setting each keyword's language from its mentions…");

// --- "paused for an import" and "paused" are two different facts -------------------- //
const parked = _foldStatusText(run({ keywords_total: 4, keywords_done: 2, percent: 50, parked_for_exclusive: true }), null, id);
assert.ok(parked.endsWith("paused for an import"), parked);
const paused = _foldStatusText(run({ state: "paused", running: false, keywords_total: 4, keywords_done: 2, percent: 50 }), null, id);
assert.ok(paused.endsWith(" · paused") && !paused.includes("import"), paused);

// --- every segment went through the translator ----------------------------------------- //
const segs = [
  _foldStatusText(run({ refusal: "lemmatisation-off" }), null, mark),
  _foldStatusText(run({ refusal: "no-lemmatiser" }), null, mark),
  _foldStatusText(run({ state: "error" }), null, mark),
  _foldStatusText(run({ state: "done" }), null, mark),
  _foldStatusText(run({ state: "done" }), { fold: {}, language: {} }, mark),
  ..._foldStatusText(run({ phase: "language", parked_for_exclusive: true }), null, mark).split(" · "),
  ..._foldStatusText(run({ state: "paused", keywords_total: 2, keywords_done: 1, tally: { mentions_moved: 1 } }), null, mark).split(" · "),
];
for (const s of segs) {
  assert.ok(s.startsWith("«") && s.endsWith("»"), "a segment skipped t(): " + s);
}

console.log("keyword fold status line: all assertions passed");
