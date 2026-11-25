/**
 * Node test for the import run view (row 440): the hero card, the Detailed view's
 * figures and the top-bar pill.
 *
 * The functions are EXTRACTED FROM THE REAL module and EXECUTED, as in
 * import_stages_node_test.js. Most checks are negative space: no percentage without
 * the server's step counts, no phase bar without a counter, no 0 where a read failed,
 * no figure for a field the server did not send, and no pill brought back by a run
 * that has already ended.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const APP = require("./app_source.js").appJs();

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

function extract(head) {
  const at = APP.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let k = at; k < APP.length; k++) {
    const c = APP[k];
    if (c === "(") p++;
    else if (c === ")") { p--; if (p === 0) { i = APP.indexOf("{", k); break; } }
  }
  assert(i !== -1, "could not find the body brace of " + head);
  let depth = 0;
  for (let k = i; k < APP.length; k++) {
    if (APP[k] === "{") depth++;
    else if (APP[k] === "}") { depth--; if (depth === 0) return APP.slice(at, k + 1); }
  }
  assert(false, "unbalanced body for " + head);
}
function constLine(head) {
  const at = APP.indexOf(head);
  assert(at !== -1, "could not find " + head);
  return APP.slice(at, APP.indexOf(";", at) + 1);
}

const src = [
  constLine("const _UX_IM_FAILED_STATES"),
  extract("function _uxImRunModel("),
  extract("function _uxImRunTitle("),
  extract("function _uxImPctHover("),
  extract("function _uxImPctText("),
  extract("function _uxImRingSvg("),
  extract("function _uxImHeroHtml("),
  extract("function _uxImFactsRows("),
  extract("function _uxImElapsedHtml("),
  "let _ooImpPillHideT = null;",
  extract("function _ooImportPillPaint("),
].join("\n");

// The page's own helpers, reduced to what the extracted code calls.
const tf = (s, v) => String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
const t = (s) => s;
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const fmtNum = (n) => String(n);
const ooLabelHtml = (a, b) => a + ": " + b;
const ooLabelText = (a, b) => a + ": " + b;
const _uxImDur = (s) => s + " s";
const _uxImPhaseBits = (live) => (live && live.progress && live.progress.phase) ? "PHASE:" + live.progress.phase : "";
const _uxVolPhase = (p) => "PHASE:" + p;
const fmtDateTime = () => "WHEN";

function pillDom() {
  const els = {
    "imp-pill": { hidden: true, className: "", title: "", attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } },
    "imp-pill-pct": { textContent: "" },
    "imp-pill-ring": { innerHTML: "" },
  };
  return els;
}
let DOM = pillDom();
const timers = [];
const sandbox = {
  window: {}, document: { getElementById: (id) => DOM[id] || null },
  setTimeout: (fn, ms) => { timers.push(ms); return timers.length; }, clearTimeout: () => {},
};
const fn = new Function("tf", "t", "esc", "fmtNum", "ooLabelHtml", "ooLabelText", "_uxImDur", "_uxImPhaseBits",
  "_uxVolPhase", "fmtDateTime", "window", "document", "setTimeout", "clearTimeout",
  src + "\nreturn { _uxImRunModel, _uxImRunTitle, _uxImHeroHtml, _uxImFactsRows, _ooImportPillPaint, _uxImPctText, _uxImElapsedHtml };");
const M = fn(tf, t, esc, fmtNum, ooLabelHtml, ooLabelText, _uxImDur, _uxImPhaseBits, _uxVolPhase, fmtDateTime,
  sandbox.window, sandbox.document, sandbox.setTimeout, sandbox.clearTimeout);

function run(extra) {
  return Object.assign({
    state: "running", cursor: 1, elapsed_s: 60, stages_done: 1, stages_total: 4,
    items: [
      { id: "a", label: "B1", kind: "corpus", state: "done" },
      { id: "b", label: "B2", kind: "corpus", state: "running" },
      { id: "c", label: "B3", kind: "corpus", state: "queued" },
    ],
    live: { progress: { phase: "merging", merge_step: 50, merge_steps: 200 } },
  }, extra || {});
}

test("the percentage is the server's step count, rounded DOWN", () => {
  const m = M._uxImRunModel(run({ stages_done: 6, stages_total: 7 }));
  assert(m.pct === 85, "6 of 7 steps reads 85, never a rounded-up 86: " + m.pct);
  assert(M._uxImRunModel(run({ stages_done: 3, stages_total: 3, state: "done" })).pct === 100, "3 of 3 is 100");
});

test("no step counts, no percentage: never one taken from the item count", () => {
  const st = run(); delete st.stages_done; delete st.stages_total;
  const m = M._uxImRunModel(st);
  assert(m.pct === null && m.stepsTotal === null, "an older server publishes no steps");
  const html = M._uxImHeroHtml(m, t, tf);
  assert(html.indexOf('<span class="imp-ring-pct">—</span>') !== -1, "the ring reads a dash, not a percentage");
  assert(html.indexOf("steps not reported") !== -1, "it says the steps are not reported");
  assert(html.indexOf('style="display:none"') !== -1, "the ring's arc is not drawn over nothing");
});

test("the current phase's bar is drawn only over a counter", () => {
  const measured = M._uxImHeroHtml(M._uxImRunModel(run()), t, tf);
  assert(/role="progressbar"[^>]*aria-valuenow="25"/.test(measured), "50 of 200 merge steps is a 25% bar");
  assert(measured.indexOf("PHASE:merging") !== -1, "the phase is named");
  assert(measured.indexOf("imp-pbar-ind") === -1, "a measured phase is not drawn indeterminate");
  const st = run({ live: { progress: { phase: "swap" } } });
  const unmeasured = M._uxImHeroHtml(M._uxImRunModel(st), t, tf);
  assert(unmeasured.indexOf("imp-pbar-ind") !== -1, "a phase with no counter is indeterminate");
  assert(unmeasured.indexOf("aria-valuenow") === -1, "and carries no value");
  assert(unmeasured.indexOf("publishes no counter") !== -1, "and says why");
});

test("re-indexed articles count as the phase's counter too", () => {
  const m = M._uxImRunModel(run({ live: { progress: { phase: "reindexing", reindex_done: 30, reindex_total: 120 } } }));
  assert(m.phaseFrac === 0.25, "30 of 120 articles");
});

test("the tally keeps done, skipped and failed apart, and shows no failure chip at zero", () => {
  const st = run({ items: [
    { id: "a", state: "done" }, { id: "b", state: "skipped" }, { id: "c", state: "error" },
    { id: "d", state: "interrupted" }, { id: "e", state: "staged" }, { id: "f", state: "queued" } ], cursor: -1 });
  const m = M._uxImRunModel(st);
  assert(m.tally.done === 1 && m.tally.skipped === 1 && m.tally.failed === 2 && m.tally.staged === 1 && m.tally.waiting === 1,
    "tally " + JSON.stringify(m.tally));
  const html = M._uxImHeroHtml(m, t, tf);
  assert(html.indexOf("Failed: 2") !== -1 && html.indexOf("Merged — not yet saved: 1") !== -1, "warnings are chips");
  const clean = M._uxImHeroHtml(M._uxImRunModel(run()), t, tf);
  assert(clean.indexOf("Failed") === -1, "no failure chip when nothing failed");
});

test("a finished run that left a backup behind does not read as finished", () => {
  const m = M._uxImRunModel(run({ state: "done", items: [{ id: "a", state: "done" }, { id: "b", state: "error" }] }));
  assert(M._uxImRunTitle(m, t) === "Import finished with errors", M._uxImRunTitle(m, t));
  const ok = M._uxImRunModel(run({ state: "done", items: [{ id: "a", state: "done" }] }));
  assert(M._uxImRunTitle(ok, t) === "Import finished", "a clean run");
  assert(M._uxImRunTitle(M._uxImRunModel(run({ state: "interrupted" })), t) === "Import interrupted", "interrupted");
});

test("the hover says what the percentage counts", () => {
  const html = M._uxImHeroHtml(M._uxImRunModel(run()), t, tf);
  assert(/title="The percentage counts import steps/.test(html), "the ring's hover names its unit");
  assert(html.indexOf("left") === -1 && html.indexOf("remaining") === -1, "no time remaining anywhere");
});

test("the run's figures leave out what the server did not send", () => {
  const rows = M._uxImFactsRows({ elapsed_s: 5, items_total: 2, items_staged: 0 }, t, tf);
  const keys = rows.map((r) => r[0]);
  assert(keys.indexOf("Merged — not yet saved") === -1, "zero staged is not a figure");
  assert(keys.indexOf("Import steps finished") === -1, "no steps published, no steps row");
  assert(keys.indexOf("Written to your corpus") === -1, "no committed count published, no row");
  const full = M._uxImFactsRows(run({ items_committed: 1, items_staged: 2, checkpoint: { k: 3 }, started_at: 1 }), t, tf);
  const fk = full.map((r) => r[0]);
  for (const k of ["Started", "Import steps finished", "Written to your corpus", "Merged — not yet saved", "Merge steps"]) {
    assert(fk.indexOf(k) !== -1, "row " + k);
  }
});

test("the elapsed time is not part of the card's HTML, so a tick does not rewrite it", () => {
  const a = M._uxImHeroHtml(M._uxImRunModel(run({ elapsed_s: 60 })), t, tf);
  const b = M._uxImHeroHtml(M._uxImRunModel(run({ elapsed_s: 61 })), t, tf);
  assert(a === b, "same card one second later");
  assert(M._uxImElapsedHtml(M._uxImRunModel(run({ elapsed_s: 61 })), t) === "Elapsed: 61 s", "filled in apart");
  assert(M._uxImElapsedHtml(M._uxImRunModel(run({ elapsed_s: null })), t) === "", "nothing when unsent");
});

test("an ended run shows no current-backup figures", () => {
  const keys = M._uxImFactsRows(run({ state: "stopped", live: { progress: { phase: "merging", merge_step: 14, merge_steps: 14, phase_index: 3, phase_total: 3 } } }), t, tf).map((r) => r[0]);
  assert(keys.indexOf("Merge steps") === -1 && keys.indexOf("Phase of the current backup") === -1, keys.join(","));
});

test("the pill shows the step percentage while a run runs", () => {
  DOM = pillDom();
  M._ooImportPillPaint(run({ stages_done: 2, stages_total: 8 }));
  const pill = DOM["imp-pill"];
  assert(pill.hidden === false, "shown");
  assert(DOM["imp-pill-pct"].textContent === "25%", DOM["imp-pill-pct"].textContent);
  assert(pill.title.indexOf("Import steps finished: 2 of 8") !== -1, "the hover counts steps: " + pill.title);
  assert(pill.title.indexOf("The percentage counts import steps") !== -1, "and says what they are");
  assert(pill.attrs["aria-label"] && pill.attrs["aria-label"].length > 0, "it has an accessible name");
});

test("a failed read says so: never 0%, never blank", () => {
  DOM = pillDom();
  M._ooImportPillPaint(run());
  M._ooImportPillPaint(null, true);
  const pill = DOM["imp-pill"];
  assert(pill.hidden === false, "the pill stays");
  assert(DOM["imp-pill-pct"].textContent === "?", "a question mark, not 0%");
  assert(/could not be read/.test(pill.title) && /could not be read/.test(pill.attrs["aria-label"]), "and the words");
  DOM = pillDom();
  M._ooImportPillPaint(null, true);
  assert(DOM["imp-pill"].hidden === true, "a failed read with no run in sight shows nothing");
});

test("a run that has ended never brings the pill back, and one seen ending leaves after a while", () => {
  DOM = pillDom();
  M._ooImportPillPaint(run({ state: "done", items: [{ id: "a", state: "done" }] }));
  assert(DOM["imp-pill"].hidden === true, "a finished run read at boot or on a reopen shows no pill");
  DOM = pillDom();
  timers.length = 0;
  M._ooImportPillPaint(run());
  M._ooImportPillPaint(run({ state: "done", stages_done: 4, items: [{ id: "a", state: "done" }] }));
  assert(DOM["imp-pill"].hidden === false && DOM["imp-pill-pct"].textContent === "✓", "the ending shows");
  assert(timers.length === 1, "one timer to clear the slot, no poll");
});

test("the pill and the hero have no poll of their own", () => {
  const pillSrc = extract("function _ooImportPillPaint(") + extract("async function ooImportPillBoot(")
    + extract("function _uxImRenderHero(");
  assert(pillSrc.indexOf("setInterval") === -1, "no interval");
  assert((pillSrc.match(/api\(/g) || []).length === 1, "one read, at start-up only");
});

console.log(passed + " passed");
