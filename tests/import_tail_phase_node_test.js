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
const APP = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app.js"), "utf-8");

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
  extract("function _uxImLive("),
  extract("function _uxImDur("),
  extract("function _uxImDetails("),
  stateTable,
  extract("function _uxImRenderQueue("),
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function fmtDateTime(ms){return 'DATE';}",
  "return { _uxImRenderQueue, _uxImLive, _uxVolPhase };",
].join("\n");

// A DOM small enough to be obviously faithful: the six elements the renderer asks for.
const dom = {};
function resetDom() {
  for (const id of ["ux-imp-queue", "ux-imp-queue-rows", "ux-imp-queue-note",
                    "ux-imp-stop", "ux-imp-run", "ux-imp-details-body"]) {
    dom[id] = { innerHTML: "", style: {}, disabled: false };
  }
}
const document = { getElementById: (id) => dom[id] || null };

const mod = new Function("window", "document", src)({}, document);  // no OOI18N: t() is identity

function render(st) { resetDom(); mod._uxImRenderQueue(st); return dom["ux-imp-queue-note"].innerHTML; }

const DONE_ITEM = { label: "backup-a", kind: "corpus", state: "done", elapsed_s: 6240, path: "/x" };
const RUNNING_ITEM = { label: "backup-a", kind: "corpus", state: "running", elapsed_s: 60, path: "/x" };
const TUNING = { phase: "tuning", own_the_machine: true, detail: "merging the search index after the import" };
const NOT_FINISHED = "The import is not finished";
const TUNING_LABEL = "Merging the search index";

// --------------------------------------------------------------------------- //
//  the defect: a run whose items are all done, still working
// --------------------------------------------------------------------------- //
test("the tail phase reaches the header when no item is in flight", () => {
  const note = render({
    state: "running", items: [DONE_ITEM], items_done: 1, items_total: 1,
    elapsed_s: 6960, collection_paused: true, live: TUNING,
  });
  assert(note.indexOf(NOT_FINISHED) !== -1,
    "the header must say the run is not finished — this is the reported defect");
  assert(note.indexOf(TUNING_LABEL) !== -1,
    "and it must NAME the phase, not merely assert that one exists");
});

test("the flat live dict is read at all (it has no sub-job to nest under)", () => {
  // Directly, so a regression in _uxImLive is attributed to _uxImLive rather than
  // reaching us through the renderer as a vague empty header.
  const flat = mod._uxImLive(TUNING, (s) => s);
  assert(flat.indexOf(TUNING_LABEL) !== -1, "a flat {phase} live must render its phase");
});

test("a nested sub-job live still renders (the shape that already worked)", () => {
  const nested = mod._uxImLive({ state: "running", progress: { phase: "merging" } }, (s) => s);
  assert(nested.indexOf("Merging") !== -1, "the mirrored sub-job shape must keep working");
});

// --------------------------------------------------------------------------- //
//  the twins: neither a fabricated phase nor a duplicated one
// --------------------------------------------------------------------------- //
test("a finished run never claims a phase is still running", () => {
  const note = render({
    state: "done", items: [DONE_ITEM], items_done: 1, items_total: 1,
    elapsed_s: 6960, collection_paused: false, live: TUNING,
  });
  assert(note.indexOf(NOT_FINISHED) === -1,
    "a done run must not inherit the tail line from a stale live dict");
});

test("an item genuinely in flight keeps its phase in its own row, not the header", () => {
  resetDom();
  mod._uxImRenderQueue({
    state: "running", items: [RUNNING_ITEM], items_done: 0, items_total: 1,
    elapsed_s: 60, collection_paused: true,
    live: { state: "running", progress: { phase: "merging" } },
  });
  const note = dom["ux-imp-queue-note"].innerHTML;
  const rows = dom["ux-imp-queue-rows"].innerHTML;
  assert(note.indexOf(NOT_FINISHED) === -1, "the header must not duplicate a running item's phase");
  assert(rows.indexOf("Merging") !== -1, "the running item's own row still carries it");
});

test("a running run with no phase at all adds nothing", () => {
  const note = render({
    state: "running", items: [DONE_ITEM], items_done: 1, items_total: 1,
    elapsed_s: 10, collection_paused: true, live: null,
  });
  assert(note.indexOf(NOT_FINISHED) === -1,
    "with no phase published there is nothing to claim — an empty live must stay silent");
});

console.log(`\n${passed} passed`);
