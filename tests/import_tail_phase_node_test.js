/**
 * Node test for the import run's TAIL PHASE — the one that has no item in flight.
 *
 * THE FIELD REPORT (2026-08-11). An import's dialog read "1/1 imported · 1h 55m" with
 * its only item "Done · 1h 44m", and underneath it "Background collection is paused for
 * this whole import" — while one core sat at 100%. Nothing was wrong with the backend:
 * `ImportQueueManager._tune_after_run` merges the search index after the last item,
 * inside the same exclusive window, and publishes `live = {phase: "tuning"}` with a
 * comment saying exactly why it must not be silent. The renderer had nowhere to put it —
 * the live block is emitted INSIDE a row whose item is `running`, and by then no item is.
 * A second, independent reason it could not have shown: `_uxImLive` read
 * `live.progress.phase`, and the run's own live dict is flat (there is no sub-job to
 * mirror), so even a row would have rendered an empty string.
 *
 * THE OPPOSITE FAILURE IS EQUALLY DISHONEST and is pinned just as hard: a finished run
 * must NOT claim a phase is still running, and a run with an item genuinely in flight
 * must not grow a second copy of that item's phase in the header.
 *
 * The functions are EXTRACTED FROM THE REAL app.js — a re-typed copy would pass while the
 * shipped code was broken. Brace-matching starts at the BODY brace (after the parentheses
 * balance), per the recorded house lesson about default parameters.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const fs = require("fs");
const path = require("path");
// The engine is several ordered modules since 2026-08-20 (S-3); the helper reads the
// module list out of index.html, so this suite cannot come to read a subset of it.
const APP = require("./app_source.js").appJs();

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

function extract(head) {
  const at = APP.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let j = APP.indexOf("(", at); j < APP.length; j++) {
    if (APP[j] === "(") p++;
    else if (APP[j] === ")") { p--; if (p === 0) { i = APP.indexOf("{", j); break; } }
  }
  let depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces in " + head);
}

// The state-label table, taken from the real file rather than restated: it is what
// turns an item's state into the word the operator reads, and a stand-in here would
// let the two drift.
const stateTable = APP.slice(
  APP.indexOf("const _UX_IM_STATE_LABEL = {"),
  APP.indexOf("function _uxImRenderQueue("),
);
assert(stateTable.indexOf("done:") !== -1, "the state-label table did not extract");

const src = [
  extract("function _uxVolPhase("),
  extract("function _uxImPhaseBits("),
  extract("function _uxImLive("),
  extract("function _uxImDur("),
  extract("function _uxImDetails("),
  stateTable,
  extract("function _uxImRenderQueue("),
  extract("function _jobRow("),
  extract("function _fmtBytes("),
  extract("function fmtNum("),
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function fmtDateTime(ms){return 'DATE';}",
  "function _isDownloadKind(k){return false;}",
  "function _dlKey(j){return j.id;}",
  "return { _uxImRenderQueue, _uxImLive, _uxImPhaseBits, _uxVolPhase, _jobRow };",
].join("\n");

// A DOM small enough to be obviously faithful: the elements the renderer asks for.
const dom = {};
function resetDom() {
  for (const id of ["ux-imp-queue", "ux-imp-queue-rows", "ux-imp-queue-note",
                    "ux-imp-stop", "ux-imp-run", "ux-imp-details-body", "ux-imp-bar"]) {
    dom[id] = { innerHTML: "", style: {}, disabled: false, value: 0, max: 1 };
  }
}
const document = { getElementById: (id) => dom[id] || null };

const mod = new Function("window", "document", src)({}, document);  // no OOI18N: t() is identity

function render(st) { resetDom(); mod._uxImRenderQueue(st); return dom["ux-imp-queue-note"].innerHTML; }

const DONE_ITEM = { label: "backup-a", kind: "corpus", state: "done", elapsed_s: 6240, path: "/x" };
const RUNNING_ITEM = { label: "backup-a", kind: "corpus", state: "running", elapsed_s: 60, path: "/x" };
const TUNING = { phase: "tuning", own_the_machine: true, detail: "merging the search index after the import" };
const TUNING_LABEL = "Merging the search index";

// The field shape: one item, done; the search-index merge still running.
const TAIL_RUN = {
  state: "running", items: [DONE_ITEM], items_done: 1, items_total: 1,
  stages_done: 1, stages_total: 2, elapsed_s: 6960, collection_paused: true, live: TUNING,
};

// --------------------------------------------------------------------------- //
//  the defect: a run whose items are all done, still working
// --------------------------------------------------------------------------- //
test("the tail phase reaches the header when no item is in flight", () => {
  const note = render(TAIL_RUN);
  assert(note.indexOf(TUNING_LABEL) !== -1,
    "the header must NAME the phase that is still running — this is the reported defect");
});

test("the flat live dict is read at all (it has no sub-job to nest under)", () => {
  // Directly, so a regression in the reader is attributed to the reader rather than
  // reaching us through the renderer as a vague empty header.
  const flat = mod._uxImPhaseBits(TUNING, (s) => s);
  assert(flat.indexOf(TUNING_LABEL) !== -1, "a flat {phase} live must render its phase");
});

test("a nested sub-job live still renders (the shape that already worked)", () => {
  const nested = mod._uxImLive({ state: "running", progress: { phase: "merging" } }, (s) => s);
  assert(nested.indexOf("Merging") !== -1, "the mirrored sub-job shape must keep working");
});

// --------------------------------------------------------------------------- //
//  the bar: never full while the run is still working
// --------------------------------------------------------------------------- //
test("the run bar is short of full while the search index is still merging", () => {
  render(TAIL_RUN);
  const bar = dom["ux-imp-bar"];
  assert(bar.style.display === "", "the bar must be shown while the run is going");
  assert(bar.max > 0 && bar.value < bar.max,
    `the bar must not read full while a stage is left (got ${bar.value}/${bar.max})`);
});

test("the bar counts the stages the server published, inventing nothing", () => {
  render(TAIL_RUN);
  assert(dom["ux-imp-bar"].value === 1 && dom["ux-imp-bar"].max === 2,
    "value and max are the server's own stage counts");
});

test("an older server with no stage counts gets no bar rather than a wrong one", () => {
  const st = Object.assign({}, TAIL_RUN);
  delete st.stages_done; delete st.stages_total;
  render(st);
  assert(dom["ux-imp-bar"].style.display === "none",
    "falling back to the item count would restore the very 100% being corrected");
});

test("a finished run hides the bar rather than parking it at full", () => {
  render(Object.assign({}, TAIL_RUN, { state: "done", stages_done: 2, collection_paused: false }));
  assert(dom["ux-imp-bar"].style.display === "none", "no run, no run bar");
});

// --------------------------------------------------------------------------- //
//  the twins: neither a fabricated phase nor a duplicated one
// --------------------------------------------------------------------------- //
test("a finished run never claims a phase is still running", () => {
  const note = render(Object.assign({}, TAIL_RUN, { state: "done", collection_paused: false }));
  assert(note.indexOf(TUNING_LABEL) === -1,
    "a done run must not inherit the tail line from a stale live dict");
});

test("an item genuinely in flight keeps its phase in its own row, not the header", () => {
  resetDom();
  mod._uxImRenderQueue({
    state: "running", items: [RUNNING_ITEM], items_done: 0, items_total: 1,
    stages_done: 0, stages_total: 2, elapsed_s: 60, collection_paused: true,
    live: { state: "running", progress: { phase: "merging" } },
  });
  const note = dom["ux-imp-queue-note"].innerHTML;
  const rows = dom["ux-imp-queue-rows"].innerHTML;
  assert(note.indexOf("Merging") === -1, "the header must not duplicate a running item's phase");
  assert(rows.indexOf("Merging") !== -1, "the running item's own row still carries it");
});

test("a running run with no phase at all adds nothing", () => {
  const note = render(Object.assign({}, TAIL_RUN, { live: null }));
  assert(note.indexOf(TUNING_LABEL) === -1,
    "with no phase published there is nothing to claim — an empty live must stay silent");
});

// --------------------------------------------------------------------------- //
//  the task-manager row: counts are counts, bytes are bytes
// --------------------------------------------------------------------------- //
test("a counted job renders counts, not bytes", () => {
  const row = mod._jobRow(
    { id: "import-queue", kind: "import", label: "Finishing the import", state: "running",
      progress: { done: 1, total: 2, unit: "stages", percent: 50.0 }, actions: [] },
    {}, (s) => s);
  assert(row.indexOf("1 / 2 stages") !== -1, "the unit travelling with the numbers must be used");
  assert(row.indexOf(" B ") === -1 && row.indexOf(" B<") === -1,
    "a stage count is not a byte count");
  assert(row.indexOf("50%") !== -1, "the percentage is the server's own");
});

test("a byte job still renders bytes", () => {
  const row = mod._jobRow(
    { id: "dump:en", kind: "dump", label: "en dump", state: "running",
      progress: { done: 1048576, total: 4194304, unit: "bytes", percent: 25.0 }, actions: [] },
    {}, (s) => s);
  assert(/1(\.0)? MB \/ 4(\.0)? MB/.test(row), `bytes must keep their formatter (got ${row})`);
});

test("a job with no unit at all is treated as bytes (the historic default)", () => {
  const row = mod._jobRow(
    { id: "x", kind: "dump", label: "x", state: "running",
      progress: { done: 1048576, total: 4194304, percent: 25.0 }, actions: [] },
    {}, (s) => s);
  assert(row.indexOf("MB") !== -1, "an absent unit must not change what already shipped");
});

console.log(`\n${passed} passed`);
