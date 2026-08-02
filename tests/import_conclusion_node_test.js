/**
 * Node test for the multi-backup import CONCLUSION screen.
 *
 * THE DEFECT this pins shut: the header was the literal string "✓ Import
 * successful", unconditionally, and the aggregate folded in EVERY queued item
 * regardless of how it ended. `it.summary` is `{}` for an item that failed, and
 * `{}` is truthy, so `rep.plan || {}` sailed straight into the plan branch and the
 * failure landed in the totals as a silent zero. A six-backup run in which two
 * failed rendered identically to one in which none did -- same tick, same green
 * rule, same "Import successful", and nothing anywhere naming the two that did not
 * make it.
 *
 * THE OPPOSITE FAILURE IS EQUALLY DISHONEST and is pinned just as hard: a clean run
 * must NOT acquire a warning, and a single-item import must not grow a
 * "1 of 1 backups" line it has no use for. Every "it reports trouble here" below has
 * an "and it does NOT there" beside it.
 *
 * The functions are EXTRACTED FROM THE REAL app.js -- a re-typed copy would pass
 * while the shipped code was broken. Brace-matching starts at the BODY brace (after
 * the parentheses balance), because a default parameter carries a `{}` in the
 * signature and the naive extractor truncates the body to nothing, which would make
 * every assertion here pass vacuously (the recorded house lesson).
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

// The _UX_OUTCOME table is extracted too: it is the single place the badge, the
// aggregate filter and the headline agree about what "counted" means, so a
// stand-in here would let them drift apart unnoticed.
const outcomeTable = APP.slice(APP.indexOf("const _UX_OUTCOME = {"), APP.indexOf("function _uxOutcome"));

const src = [
  outcomeTable,
  extract("function _uxOutcome("),
  extract("function _uxFmtDur("),
  extract("function _uxPerItemView("),
  extract("function _uxCorpusDeltaView("),
  extract("function _uxStageLabel("),
  extract("function _uxFmtS("),
  extract("function _uxTimingsView("),
  extract("function _renderImportSummary("),
  // Collaborators the renderer calls that are not what is under test.
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function _v2PlanTable(p){return '<table data-plan></table>';}",
  "return { _renderImportSummary, _uxPerItemView, _uxFmtDur, _uxOutcome };",
].join("\n");

const mod = new Function("window", src)({});   // no OOI18N: t()/tf() take their fallbacks

function render(summaries, run) {
  const host = { innerHTML: "" };
  mod._renderImportSummary(host, summaries, run);
  return host.innerHTML;
}

const plan = (n, d, c) => ({ articles: { new: n, duplicate: d, conflict: c || 0 } });
const ok   = (title, n, d) => ({ title, state: "done", elapsed_s: 60, plan: plan(n, d) });

// --------------------------------------------------------------------------- //
test("a failed backup is NOT folded into the totals as a silent zero", () => {
  const html = render([
    ok("backup-a", 1000, 10),
    { title: "backup-b", state: "error", error: "volume 3 failed its checksum", elapsed_s: 12, plan: {} },
  ], { state: "error", elapsed_s: 900, items_done: 1, items_total: 2 });

  assert(!html.includes("Import successful"), "a run with a failure must not claim success");
  assert(html.includes("Import finished with errors"), "the failure must be in the header");
  assert(html.includes("1 of 2 backups imported"), "the n-of-m must be stated");
  assert(html.includes("backup-b"), "the failed backup must still be listed");
  assert(html.includes("volume 3 failed its checksum"), "its real error must be shown, not swallowed");
  // The totals cover only what completed, and say so.
  assert(html.includes("the 1 that completed"), "the aggregate's scope must be disclosed");
});

test("a clean run keeps the plain success header and grows NO warning", () => {
  const html = render([ok("backup-a", 1000, 10), ok("backup-b", 500, 5)],
                      { state: "done", elapsed_s: 900, items_done: 2, items_total: 2 });
  assert(html.includes("Import successful"), "a clean run must still read as successful");
  assert(!html.includes("finished with errors"), "no fabricated failure");
  assert(!html.includes("Import stopped"), "no fabricated stop");
  assert(!html.includes("that completed"), "no scope caveat when nothing was excluded");
  assert(html.includes("2 of 2 backups imported"), "the count line is still useful on a clean multi-run");
});

test("a stopped run is stopped, not failed -- they are different words", () => {
  const html = render([
    ok("backup-a", 1000, 10),
    { title: "backup-b", state: "cancelled", elapsed_s: 0, plan: {} },
  ], { state: "stopped", elapsed_s: 300, items_done: 1, items_total: 2 });
  assert(html.includes("Import stopped"), "a cancelled item is a stop");
  assert(!html.includes("finished with errors"), "a deliberate stop is not an error");
});

test("a single-item import grows no n-of-m line and no per-backup table", () => {
  const html = render([ok("just-one", 42, 1)], { state: "done", elapsed_s: 30, items_done: 1, items_total: 1 });
  assert(html.includes("Import successful"), "still a success");
  assert(!html.includes("backups imported"), "an n-of-m line is noise for one item");
  assert(!html.includes("What each backup brought"), "a one-row comparison compares nothing");
});

test("the per-backup view names every item, with its own numbers and time", () => {
  const html = render([ok("older-set", 1000, 10), ok("newer-set", 250, 3)],
                      { state: "done", elapsed_s: 7200, items_done: 2, items_total: 2 });
  assert(html.includes("What each backup brought"), "the per-backup view renders for a multi-run");
  assert(html.includes("older-set") && html.includes("newer-set"), "every item is named");
  assert(html.includes("1,000") && html.includes("250"), "each item's own count is printed, not only the total");
  assert(html.includes("2 h 0 min"), "the run's own measured elapsed time is shown");
});

test("an item that imported nothing gets no bar rather than a fake sliver", () => {
  const html = render([ok("brought-something", 1000, 0), ok("brought-nothing", 0, 0)],
                      { state: "done", elapsed_s: 60, items_done: 2, items_total: 2 });
  assert(html.includes("nothing imported"), "an empty item says so in words");
  // Exactly one bar row: the empty one must not draw a min-width segment that would
  // claim a contribution it never made.
  const bars = (html.match(/min-width:2px/g) || []).length;
  assert(bars === 1, `expected 1 bar for 2 items (one empty), got ${bars}`);
});

test("an absent per-item state is treated as counted, not demoted", () => {
  // _uxShowLastCompletedSummary reads jobs whose status was already "done" and
  // carries no per-item state. Demoting those would blank the recovered summary --
  // the exact regression the recovery path was built to fix.
  const html = render([{ title: "recovered", plan: plan(500, 5) }], undefined);
  assert(html.includes("Import successful"), "a stateless summary must not read as failed");
  assert(html.includes("500"), "its numbers must still be counted");
});

test("_uxFmtDur refuses to invent a duration it does not have", () => {
  assert(mod._uxFmtDur(null) === "—", "a missing measurement is not 0 s");
  assert(mod._uxFmtDur(undefined) === "—", "undefined is not 0 s");
  assert(mod._uxFmtDur(-1) === "—", "a negative is not a duration");
  assert(mod._uxFmtDur(0) === "0.0 s", "a real zero IS reportable");
  assert(mod._uxFmtDur(61585).includes("17 h"), "hours are readable, not '61585.0 s'");
});

console.log(`\n${passed} passed`);
