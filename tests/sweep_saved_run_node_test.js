// The AI sweeps' saved-run panel, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Extracted from src/static/app.js rather than re-typed: a copy would pass while the
// shipped function was broken.
//
// WHY BEHAVIOURAL AND NOT A SOURCE GREP: the defect was an ABSENCE. The download links
// exist in the renderer's own source either way -- what was broken is that the renderer was
// only ever REACHED while a sweep was running, so after an overnight run finished, the
// panel was empty and the links did not exist in the DOM at all. A field report read that,
// correctly, as the button being missing. No assertion over the presence of an href can
// tell "the string is in the file" from "the string is rendered when someone looks", and
// it is the second that was false.
//
// The NEGATIVE-SPACE TWINS are the load-bearing half here: a fix that rendered the saved
// run unconditionally would clobber a LIVE run's own progress, and one that reused
// `paused_reason` to carry the saved state would relabel an errored run as "paused" -- a
// fabricated state, worse than the empty panel it replaced.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const APP = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app.js"), "utf8");

function functionSource(src, name) {
  let at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error("no function named " + name);
  // ASYNC-AGNOSTIC ANCHOR: `async function f(` starts six characters earlier, and slicing
  // from `function` alone yields a body whose `await` is a SyntaxError -- the same
  // stale-literal-anchor trap that a recorded `async def` -> `def` rename once cost, from
  // the other side. Take the modifier when it is there.
  if (src.slice(Math.max(0, at - 6), at) === "async ") at -= 6;
  // Balance the PARENTHESES before hunting the body brace, so a `{}` in a default
  // parameter cannot truncate the slice to the signature alone.
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = src.indexOf("{", i);
  depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  throw new Error("unbalanced braces in " + name);
}

// --- harness ---------------------------------------------------------------------- //

let apiRoutes, painted, polled, el;

function install() {
  apiRoutes = {};
  painted = [];
  polled = [];
  // The renderer writes `innerHTML`; the sync then PREPENDS the state line. Both go
  // through the same backing string, so the assertions read what a browser would show.
  el = { innerHTML: "", insertAdjacentHTML(where, s) { this.innerHTML = s + this.innerHTML; } };
  global.window = {};
  global.esc = (s) => String(s);
  global.api = async (url) => {
    if (!(url in apiRoutes)) throw new Error("unstubbed " + url);
    const v = apiRoutes[url];
    if (v instanceof Error) throw v;
    return v;
  };
  global._paintAiSweepButton = (id, running) => painted.push([id, running]);
  global._pollAiSweep = (job) => polled.push(job);
}

install();
// The three under test, plus the renderer they feed -- all read out of the shipped file.
eval(functionSource(APP, "_savedSweepAsResult"));
eval(functionSource(APP, "_savedSweepStateLine"));
eval(functionSource(APP, "_syncAiSweepToggle"));
eval(functionSource(APP, "renderKeywordTriageResult"));

const LAST_DONE = {
  available: true,
  filename: "oo-keyword-triage-20260813-000000-000000.jsonl",
  batches_logged: 4883,
  summary: {
    state: "done",
    batches_completed: 4883,
    keywords_in: 131838,
    verdicts_out: 109466,
    parse_failures: 22575,
    missing: 22372,
    canary_ok_overall: true,
  },
};

// --- 1. a FINISHED run renders, with both download links ---------------------------- //
(async () => {
  install();
  apiRoutes["/api/diagnostics/keyword-triage/status"] = { state: "done" };
  apiRoutes["/api/diagnostics/keyword-triage/last"] = LAST_DONE;

  await _syncAiSweepToggle(
    "keyword-triage", "kt-btn", null, el, renderKeywordTriageResult);

  assert.ok(el.innerHTML.includes("/api/diagnostics/keyword-triage/download"),
    "the raw log link must be reachable once a run has FINISHED, not only while it runs");
  assert.ok(el.innerHTML.includes("/api/diagnostics/keyword-triage/proposal"),
    "the proposal link must be reachable once a run has FINISHED");
  assert.ok(el.innerHTML.includes("109466"), "the saved run's own verdict count must show");
  assert.ok(el.innerHTML.includes("4883"), "the saved run's own batch count must show");
  assert.deepStrictEqual(painted, [["kt-btn", false]], "the button must read Start, not Stop");
  assert.deepStrictEqual(polled, [], "a finished run must not start a poll loop");

  // --- 2. NEGATIVE SPACE: a live run's own progress is never overwritten -------------- //
  //
  // `/last` is stubbed with a REAL saved run here, and that is the whole point. An earlier
  // draft left it unstubbed on the reasoning that reading it would throw and thereby prove
  // it was not read -- but the throw is swallowed by the courtesy try/catch, so the panel
  // stayed empty either way and the assertion passed for a reason unrelated to its claim.
  // Mutation-checked: with a real payload here, dropping the early return renders the saved
  // run over the live one and this fails.
  install();
  apiRoutes["/api/diagnostics/keyword-triage/status"] = { state: "running" };
  apiRoutes["/api/diagnostics/keyword-triage/last"] = LAST_DONE;
  await _syncAiSweepToggle(
    "keyword-triage", "kt-btn", null, el, renderKeywordTriageResult);
  assert.deepStrictEqual(polled, ["keyword-triage"],
    "a RUNNING sweep must still hand over to the live poller");
  assert.strictEqual(el.innerHTML, "",
    "a running sweep's own progress must not be overwritten by the last saved run");

  // --- 3. NEGATIVE SPACE: no run at all stays empty, never a zeroed fake ------------- //
  install();
  apiRoutes["/api/diagnostics/keyword-triage/status"] = { state: "idle" };
  apiRoutes["/api/diagnostics/keyword-triage/last"] = { available: false, note: "none yet" };
  await _syncAiSweepToggle(
    "keyword-triage", "kt-btn", null, el, renderKeywordTriageResult);
  assert.strictEqual(el.innerHTML, "",
    "no saved run must render nothing -- a 0-batch panel would read as a run that found nothing");

  // --- 4. NEGATIVE SPACE: an ERRORED run is never relabelled "paused" ---------------- //
  install();
  apiRoutes["/api/diagnostics/keyword-triage/status"] = { state: "error" };
  apiRoutes["/api/diagnostics/keyword-triage/last"] = {
    available: true,
    filename: "oo-keyword-triage-x.jsonl",
    batches_logged: 12,
    summary: { state: "error", batches_completed: 12, verdicts_out: 300, error: "backend gone" },
  };
  await _syncAiSweepToggle(
    "keyword-triage", "kt-btn", null, el, renderKeywordTriageResult);
  assert.ok(el.innerHTML.includes("ended on an error"),
    "an errored saved run must say so");
  assert.ok(!el.innerHTML.includes("paused"),
    "an errored run must NEVER be relabelled 'paused' -- the renderer turns any truthy "
    + "paused_reason into that word, so the adapter must not set it");
  assert.ok(!el.innerHTML.includes("sweep complete"),
    "an errored run must not read as complete");

  // --- 5. the four saved states each say what they were ------------------------------ //
  const t = (s) => s;
  const say = (state) => _savedSweepStateLine({ summary: { state }, filename: "f.jsonl" }, t);
  assert.ok(say("done").includes("complete"));
  assert.ok(say("cancelled").includes("stopped"));
  assert.ok(say("error").includes("error"));
  // A log with no footer, read only BECAUSE the job is not running, is an interrupted run
  // -- not one still in progress.
  assert.ok(say("in_progress").includes("interrupted"),
    "a footerless log must read as interrupted, never as still running");
  assert.ok(say("done").includes("f.jsonl"), "the file that was read must be named");

  // --- 6. a /last that fails must not break the toggle ------------------------------- //
  install();
  apiRoutes["/api/diagnostics/keyword-triage/status"] = { state: "done" };
  apiRoutes["/api/diagnostics/keyword-triage/last"] = new Error("boom");
  await _syncAiSweepToggle(
    "keyword-triage", "kt-btn", null, el, renderKeywordTriageResult);
  assert.deepStrictEqual(painted, [["kt-btn", false]],
    "the button must still be painted when the courtesy read of the saved run fails");

  console.log("sweep saved-run panel: 6 groups passed");
})().catch((e) => { console.error(e); process.exit(1); });
