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
// BOUNDED ON THE NEXT DECLARATION, not on a distant one: slicing to
// `function _uxImRenderQueue(` used to be correct and stopped being so the moment a
// second table and the patch helpers were added between the two -- the recorded
// "a slice that runs to the next top-level declaration sweeps in unrelated code"
// trap, which here presented as a duplicate-declaration SyntaxError rather than as
// a silent over-run, because the sweep also re-declared what is extracted below.
const stateTable = APP.slice(
  APP.indexOf("const _UX_IM_STATE_LABEL = {"),
  APP.indexOf("const _UX_IM_STAGE_LABEL = {"),
);
assert(stateTable.indexOf("done:") !== -1, "the state-label table did not extract");

// The four stage-row labels (Q202 = a) and the chain's re-index cache, both read by
// _uxImRenderQueue's helpers. Sliced, not retyped, for the same reason as above.
const stageTable = APP.slice(
  APP.indexOf("const _UX_IM_STAGE_LABEL = {"),
  APP.indexOf("function _uxRowNode("),
);
assert(stageTable.indexOf("verify_stage:") !== -1, "the stage-label table did not extract");
const rxState = APP.slice(
  APP.indexOf("let _uxImRx = null, _uxImRxAt = 0;"),
  APP.indexOf("let _uxImRx = null, _uxImRxAt = 0;") + "let _uxImRx = null, _uxImRxAt = 0;".length,
);
assert(rxState.length > 10, "the chain's re-index cache declaration did not extract");

const src = [
  extract("function _uxVolPhase("),
  extract("function _uxImPhaseBits("),
  extract("function _uxImLive("),
  extract("function _uxImDur("),
  // B18 (R14): the queue row's elapsed time goes through the shared keyed, isolated
  // duration frames -- the real helpers, extracted.
  extract("function _uxDurIso("),
  extract("function _uxDurTf("),
  stateTable,
  stageTable,
  // The chain's own state, extracted rather than stubbed: _uxImRenderQueue reads
  // _uxImRx (the re-index job's last status) to fill stage 4, and a stand-in would
  // let this copy drift from the shipped declaration.
  rxState,
  extract("function _uxPatchRow("),
  extract("function _uxPruneRows("),
  extract("function _uxRowNode("),
  extract("function _uxImReindexBits("),
  extract("function _uxImStatements("),
  extract("function _uxImAnalyticsStatement("),
  extract("function _uxImNothingMerged("),
  extract("function _uxImRenderStatements("),
  extract("function _uxImRenderStages("),
  extract("function _uxImRenderQueue("),
  // The interrupted line the header shares with the fresh page (I9), and the two pieces
  // of chain state the renderer now writes -- declared here, not left to sloppy-mode
  // globals, so a typo in the shipped name fails this suite instead of passing it.
  extract("function _uxImInterruptedHtml("),
  "let _uxImLastStatus = null; let _uxImView = null;",
  extract("function _jobRow("),
  extract("function _fmtBytes("),
  // ...and _fmtBytes writes through the shared localised formatter (P8), the same trap.
  extract("function _sizeText("),
  // A queue row's error reads through the page's rendering of the server's sentence
  // (the 2026-09-26 leftovers, Y9): extracted with the tables it reads, the same trap.
  APP.slice(APP.indexOf("const _OO_SPACE_WHAT = {"), APP.indexOf("function ooServerText(")),
  extract("function ooServerText("),
  // _jobRow calls these two (PERF-09's rate line). Extracted rather than stubbed,
  // for the reason this whole harness exists: a stand-in would let the copy under
  // test drift from the shipped code. Adding a call to a function this suite
  // extracts in ISOLATION makes every such suite part of that change -- this one
  // went red on CI with "ReferenceError: _rateNote is not defined" the moment
  // _jobRow gained the call.
  extract("function _rateNote("),
  extract("function _fmtDur("),
  extract("function fmtNum("),
  // And the cause line S04-08's S5 added to the row (why a download is paused or
  // failed) -- the same trap, sprung again the day that call landed.
  extract("function _jobWhy("),
  // ...and a fourth (click-through B17, T5/T11): the whole-number percent and the keyed
  // label frame the row now draws through.
  extract("function _jobPct("),
  extract("function _jobLabel("),
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function fmtDateTime(ms){return 'DATE';}",
  "function _isDownloadKind(k){return false;}",
  "function _dlKey(j){return j.id;}",
  // ...and a third time (M5): _jobRow reads the set of LOCAL job kinds, whose resume
  // needs no consent popup. The real statement, sliced to its own semicolon.
  (() => {
    const at = APP.indexOf("const _LOCAL_JOB_KINDS");
    assert(at !== -1, "could not find const _LOCAL_JOB_KINDS");
    return APP.slice(at, APP.indexOf(";", at) + 1);
  })(),
  "return { _uxImRenderQueue, _uxImLive, _uxImPhaseBits, _uxVolPhase, _jobRow };",
].join("\n");

// A DOM small enough to be obviously faithful: the elements the renderer asks for,
// plus the handful of node operations the patch-in-place renderer uses (Q206 = a).
// `children`, `appendChild`, `remove`, `dataset` and get/setAttribute are the whole
// surface -- anything more would be a browser, and anything less would make the
// renderer unrunnable rather than testable.
function makeNode() {
  const attrs = {};
  const node = {
    innerHTML: "", style: {}, disabled: false, value: 0, max: 1,
    dataset: {}, children: [],
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
    removeAttribute(k) { delete attrs[k]; },
    appendChild(c) { c._parent = node; node.children.push(c); return c; },
    remove() {
      const par = node._parent;
      if (par) par.children = par.children.filter((c) => c !== node);
    },
  };
  return node;
}
const dom = {};
function resetDom() {
  for (const id of ["ux-imp-queue", "ux-imp-queue-rows", "ux-imp-queue-note",
                    "ux-imp-stop", "ux-imp-run", "ux-imp-bar",
                    "ux-imp-stages", "ux-imp-statements"]) {
    dom[id] = makeNode();
  }
}
const document = { getElementById: (id) => dom[id] || null, createElement: () => makeNode() };

const mod = new Function("window", "document", src)({}, document);  // no OOI18N: t() is identity

// Q206 = a: rows are PATCHED IN PLACE now, so the host's own innerHTML stays empty
// and the content lives on its children. Reading the host directly would report an
// empty string for a correctly-rendered list -- a false negative that reads exactly
// like a broken renderer.
function childHtml(id) { return dom[id].children.map((c) => c.innerHTML).join(""); }

// The HEADER is patched the same way since I9 (2026-09-26): a "head" part that carries
// the elapsed seconds and changes every tick, and a "body" part that does not.
function render(st) { resetDom(); mod._uxImRenderQueue(st); return childHtml("ux-imp-queue-note"); }

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
  const note = childHtml("ux-imp-queue-note");
  const rows = childHtml("ux-imp-queue-rows");
  assert(note.indexOf("Merging") === -1, "the header must not duplicate a running item's phase");
  assert(rows.indexOf("Merging") !== -1, "the running item's own row still carries it");
});

test("a running run with no phase at all adds nothing", () => {
  const note = render(Object.assign({}, TAIL_RUN, { live: null }));
  assert(note.indexOf(TUNING_LABEL) === -1,
    "with no phase published there is nothing to claim — an empty live must stay silent");
});

// --------------------------------------------------------------------------- //
//  batch B1 (2026-09-26): the header, the rows, and what they must not say
// --------------------------------------------------------------------------- //
const STAGED_RUN = {
  state: "running", elapsed_s: 7, collection_paused: true, items_staged: 2,
  checkpoint: { k: 3 }, items_done: 2, items_total: 4, stages_done: 0, stages_total: 4,
  items: [
    { id: "0", label: "b1", kind: "corpus", state: "staged", stage: 2, stage_applicable: true },
    { id: "1", label: "b2", kind: "corpus", state: "staged", stage: 2, stage_applicable: true },
    { id: "2", label: "b3", kind: "corpus", state: "running", stage: 1, stage_applicable: true },
    { id: "3", label: "b4", kind: "corpus", state: "queued", stage_applicable: true },
  ],
};

test("I9: no status line in the header is the toast box", () => {
  // THE WALK: the staged line was `<span class="note">` -- 11 px padding, a shadow and a
  // slide-in -- so it overlapped "0/4 imported" and re-animated on every 1 s tick.
  const note = render(STAGED_RUN);
  assert(note.indexOf("Merged, not yet saved") !== -1, "the staged line is still said: " + note);
  assert(note.indexOf('class="note') === -1, "the toast class overlaps the line above: " + note);
});

test("I9: a tick that only moves the clock rewrites the clock and nothing else", () => {
  resetDom();
  mod._uxImRenderQueue(STAGED_RUN);
  const host = dom["ux-imp-queue-note"];
  const keys = host.children.map((c) => c.getAttribute("data-row-key"));
  assert(keys.join(",") === "head,body", "the header is two patched parts: " + keys);
  const body = host.children[1];
  let writes = 0;
  const kept = body.innerHTML;
  Object.defineProperty(body, "innerHTML", {
    get() { return kept; }, set(_v) { writes += 1; }, configurable: true,
  });
  mod._uxImRenderQueue(Object.assign({}, STAGED_RUN, { elapsed_s: 8 }));
  assert(writes === 0, "the staged line was rewritten (and its animation replayed) by a clock tick");
  assert(host.children[0].innerHTML.indexOf("\u20688\u00a0s\u2069") !== -1, "the clock itself did move");
});

test("I12: a backup's folder name is isolated from the surrounding text direction", () => {
  resetDom();
  mod._uxImRenderQueue(Object.assign({}, STAGED_RUN, {
    items: [{ id: "0", label: "202609261808_OpenOmniscience_Backup_2", kind: "corpus", state: "done" }],
  }));
  const rows = childHtml("ux-imp-queue-rows");
  assert(rows.indexOf("<bdi>202609261808_OpenOmniscience_Backup_2</bdi>") !== -1, rows);
});

test("Y2/Y9: a row's error is the dialog's inline error line, in the page's words", () => {
  // THE WALK: the per-item error rode the toast box (`.note` -- padding, shadow and a
  // slide-in) inside a dialog row, and a free-space refusal read in English in every
  // locale. It is the dialog's own error colour now, and the sentence is re-written.
  resetDom();
  mod._uxImRenderQueue(Object.assign({}, STAGED_RUN, {
    state: "done",
    items: [{ id: "0", label: "b1", kind: "corpus", state: "error",
              error: "Not enough free space for the restore: needs about 1.5 GB, only 200.0 MB free at /mnt/x. "
                + "Free up space or choose another location, or use the large-data/volume backup for a big corpus." }],
  }));
  const rows = childHtml("ux-imp-queue-rows");
  assert(rows.indexOf('class="note') === -1, "the toast class in a dialog row: " + rows);
  assert(rows.indexOf("color:var(--err)") !== -1, "the error keeps its colour: " + rows);
  assert(rows.indexOf("Restore: not enough free space") !== -1, rows);
});

test("walk 2026-09-28: a wrong passphrase reads in the page's words, not the server's", () => {
  // The commonest failure there is arrived as English on the French, German and Arabic
  // pages alike. Both shapes the server sends -- bare, and prefixed by merge.py.
  for (const error of ["could not restore this backup: wrong passphrase or the file has been altered",
                       "wrong passphrase or the file has been altered"]) {
    resetDom();
    mod._uxImRenderQueue(Object.assign({}, STAGED_RUN, {
      state: "error", items: [{ id: "0", label: "b1", kind: "corpus", state: "error", error }],
    }));
    const rows = childHtml("ux-imp-queue-rows");
    assert(rows.indexOf("Could not open this backup: the passphrase is wrong, or its files have been altered.") !== -1, rows);
    assert(rows.indexOf("wrong passphrase or the file") === -1, "the server's sentence is still drawn: " + rows);
  }
});

test("I13: a long folder name may wrap rather than run out of a 375 px dialog", () => {
  resetDom();
  mod._uxImRenderQueue(STAGED_RUN);
  assert(childHtml("ux-imp-queue-rows").indexOf("overflow-wrap:anywhere") !== -1,
    childHtml("ux-imp-queue-rows"));
});

test("I14: a finished backup does not also read 'stage 2 of 4'", () => {
  resetDom();
  mod._uxImRenderQueue(Object.assign({}, STAGED_RUN, {
    state: "done",
    items: [
      { id: "0", label: "b1", kind: "corpus", state: "done", stage: 2, stage_applicable: true },
      { id: "1", label: "b2", kind: "corpus", state: "error", stage: 1, stage_applicable: true },
    ],
  }));
  const rows = childHtml("ux-imp-queue-rows");
  assert(rows.indexOf("stage ") === -1, "'Done · stage 2 of 4' says finished and half-way: " + rows);
});

test("I14: ...while a backup on its way, or waiting for its checkpoint, keeps its stage", () => {
  resetDom();
  mod._uxImRenderQueue(STAGED_RUN);
  const rows = dom["ux-imp-queue-rows"].children.map((c) => c.innerHTML);
  assert(rows[0].indexOf("stage 2 of 4") !== -1, "a staged backup waits in stage 2: " + rows[0]);
  assert(rows[2].indexOf("stage 1 of 4") !== -1, "a running backup is in stage 1: " + rows[2]);
  assert(rows[3].indexOf("stage ") === -1, "a queued backup has no stage yet: " + rows[3]);
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
  // Each size rides in its own bidi isolate since P8 (2026-09-26), with a no-break space
  // before its unit; strip the one and read the other as a space.
  assert(/1(\.0)? MB \/ 4(\.0)? MB/.test(row.replace(/[\u2068\u2069]/g, "").replace(/\u00a0/g, " ")), `bytes must keep their formatter (got ${row})`);
});

// CHANGED in click-through B19 (Q12). This test pinned "no unit = bytes" as the historic
// default. Since B17 every producer in src/api/jobs.py and src/jobs/background.py names
// its unit -- bytes included -- so the only rows that still reach this branch carry a
// number nobody named, and reading it as bytes is what drew "3 B / 12 B" on a count. A
// count that claims nothing is the honest default; the byte case above keeps its unit.
test("a job with no unit at all is a plain count, never bytes", () => {
  const row = mod._jobRow(
    { id: "x", kind: "dump", label: "x", state: "running",
      progress: { done: 3, total: 12, percent: 25.0 }, actions: [] },
    {}, (s) => s);
  assert(row.indexOf("3 / 12") !== -1, `an unnamed number is shown as the count it is (got ${row})`);
  assert(!/\bB\b|KB|MB/.test(row.replace(/[⁨⁩]/g, "")), `no byte unit is invented (got ${row})`);
});

console.log(`\n${passed} passed`);
