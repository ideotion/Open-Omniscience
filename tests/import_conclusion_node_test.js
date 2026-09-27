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

// The _UX_OUTCOME table is extracted too: it is the single place the badge, the
// aggregate filter and the headline agree about what "counted" means, so a
// stand-in here would let them drift apart unnoticed.
const outcomeTable = APP.slice(APP.indexOf("const _UX_OUTCOME = {"), APP.indexOf("function _uxOutcome"));

const src = [
  outcomeTable,
  extract("function _uxOutcome("),
  extract("function _uxFmtDur("),
  // B18: a duration is ONE keyed frame, isolated (R9); an already-merged backup states
  // its batch and date (R11); summary lines are label: value (R14). The real helpers.
  extract("function _uxDurIso("),
  extract("function _uxDurTf("),
  extract("function _uxMergedLine("),
  extract("function fmtDateTime("),
  extract("function ooLabelText("),
  extract("function _uxPerItemView("),
  extract("function _uxCorpusDeltaView("),
  extract("function _uxStageLabel("),
  extract("function _uxFmtS("),
  extract("function _uxTimingsView("),
  extract("function _uxPlanExtras("),
  extract("function _renderImportSummary("),
  // A per-item error is shown through the page's reading of the server's own sentence
  // (the 2026-09-26 leftovers, Y9), which writes its sizes through `_sizeText`: both are
  // extracted, with the tables they read, for the reason this harness exists.
  APP.slice(APP.indexOf("const _OO_SPACE_WHAT = {"), APP.indexOf("function ooServerText(")),
  extract("function ooServerText("),
  extract("function _sizeText("),
  // The counts go through the app's one number formatter, and a signed delta through the
  // shared left-to-right isolate (the 2026-09-27 leftovers, W9/W18): both are the real
  // shipped functions, extracted rather than stubbed.
  extract("function fmtNum("),
  APP.slice(APP.indexOf("const _LTR_ISOLATE = "), APP.indexOf("function _ltrIsolate(")),
  extract("function _ltrIsolate("),
  // Collaborators the renderer calls that are not what is under test.
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function _v2PlanTable(p){return '<table data-plan></table>';}",
  "return { _renderImportSummary, _uxPerItemView, _uxFmtDur, _uxOutcome, _uxPlanExtras, _uxCorpusDeltaView };",
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
  // fmtNum's grouping (U+202F), not the browser's locale "1,000" (W18).
  assert(html.includes("1\u202F000") && html.includes("250"), "each item's own count is printed, not only the total");
  assert(!html.includes("1,000"), "a count went through the browser's locale: " + html);
  assert(html.includes("\u20682\u00a0h\u00a00\u00a0min\u2069"), "the run's own measured elapsed time is shown");
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

// --------------------------------------------------------------------------- //
// The "still indexing" caveat, driven END TO END: a real run_restore() report goes
// through the REAL producer (_uxPlanExtras) into the REAL renderer, exactly as the
// three push sites do it.
//
// THE DEFECT this pins shut, which shipped: the renderer read `reindex_deferred`
// from the day the deferral landed and NOTHING ever wrote it -- _uxPlanExtras is the
// one helper all three call sites spread, and it did not carry the key. So the
// caveat could not render on any path. The test that accompanied the change asserted
// only that the RENDERER reads the key; a reader with no producer satisfies that
// perfectly. Assert the chain, not one end of it.
//
// It matters more than a cosmetic line: deferring the re-index means "import
// finished" no longer means "fully indexed", and the change's own rationale says
// deferring SILENTLY is strictly worse than the three-hour wait it replaced.
const restoreReport = (rx) => ({
  plan: { articles: { new: 12778, duplicate: 3, conflict: 0 } },
  corpus_delta: null, reindexed: null, timings: null,
  reindex_deferred: rx,
});
const viaProducer = (rep, title) =>
  ({ title: title || "backup-a", state: "done", elapsed_s: 118.6,
     plan: rep.plan || {}, ...mod._uxPlanExtras(rep) });

test("a deferred re-index reaches the screen, with its real pending count", () => {
  const html = render([viaProducer(restoreReport({
    deferred: true, articles_pending: 12778, pending_unreadable_reason: null,
    started: true, job: "reindex-resume",
  }))], { state: "done", elapsed_s: 118.6, items_done: 1, items_total: 1 });

  assert(html.includes("Indexing continues in the background"), "the deferral must be stated");
  assert(html.includes("12\u202F778"), "with the REAL backlog, thousands-separated (by fmtNum, W18)");
  assert(html.includes("absent from analytics"), "and with what being un-indexed actually costs");
  assert(html.includes("card-caveat"), "it is a caveat about corpus completeness, styled as one");
});

test("an import with nothing deferred grows NO indexing caveat", () => {
  // The negative-space twin. A caveat that fires on every import is noise, and an
  // over-eager one reads as conservative while telling users their complete corpus
  // is incomplete -- a fabricated warning is as dishonest as a missing one.
  const html = render([viaProducer(restoreReport(null))],
                      { state: "done", elapsed_s: 60, items_done: 1, items_total: 1 });
  assert(html.includes("Import successful"), "still a clean success");
  assert(!html.includes("Indexing continues"), "no fabricated incompleteness");
});

test("an unreadable backlog says so and never renders as zero pending", () => {
  const html = render([viaProducer(restoreReport({
    deferred: true, articles_pending: null,
    pending_unreadable_reason: "database is locked", started: false,
  }))], { state: "done", elapsed_s: 90, items_done: 1, items_total: 1 });
  assert(html.includes("could not be read"), "'could not read' must not look like 'nothing pending'");
  assert(!html.includes("0 article"), "an unreadable count is not a measured zero");
});

// I6 (2026-09-26) REVERSED what this suite used to pin. Each item's `articles_pending`
// is the WHOLE corpus backlog when that item committed (volume_job.hand_off_reindex reads
// reindex_backlog()), so the later snapshot already CONTAINS the earlier one; the test
// that asserted a sum pinned the double count. The walk: four 1,200-article backups at
// K=3 read 3,600 then 4,800, and the summary said "8,400 still to index".
test("several backups' backlogs are the LAST snapshot, never a sum of snapshots", () => {
  const html = render([
    viaProducer(restoreReport({ deferred: true, articles_pending: 3600, started: false }), "a"),
    viaProducer(restoreReport({ deferred: true, articles_pending: 4800, started: true }), "b"),
  ], { state: "done", elapsed_s: 400, items_done: 2, items_total: 2 });
  assert(html.includes("4\u202F800"), "the backlog the run ended with is the last snapshot");
  assert(!html.includes("8\u202F400"), "summing whole-corpus snapshots double-counts: " + html);
});

test("an unreadable last snapshot says so rather than repeating an older figure", () => {
  const html = render([
    viaProducer(restoreReport({ deferred: true, articles_pending: 3600, started: false }), "a"),
    viaProducer(restoreReport({ deferred: true, articles_pending: null,
                                pending_unreadable_reason: "database is locked" }), "b"),
  ], { state: "done", elapsed_s: 400, items_done: 2, items_total: 2 });
  assert(html.includes("could not be read"), "the current backlog was not read: " + html);
  assert(!html.includes("3\u202F600"), "an earlier snapshot is not the current backlog");
});

test("I13/I12: the per-backup table lets a folder name wrap, and isolates it", () => {
  // At 375 px the one-line names held this table 130-170 px wider than the dialog
  // (measured in Chromium, 2026-09-26), clipping them at its edge.
  const name = "202609261808_OpenOmniscience_Backup_2";
  const html = render([ok(name, 1200, 0), ok("b", 1200, 0)],
                      { state: "done", elapsed_s: 13, items_done: 2, items_total: 2 });
  const cell = html.slice(html.indexOf("<tr>"), html.indexOf("</td>", html.indexOf("<tr>")));
  assert(cell.indexOf("<bdi>" + name + "</bdi>") !== -1, "the name is isolated: " + cell);
  assert(cell.indexOf("white-space:nowrap") === -1, "the name may wrap: " + cell);
});

// --------------------------------------------------------------------------- //
// The 2026-09-26 click-through's leftovers (batch B13).
const deferredReport = (fresh, pending) => ({
  plan: { articles: { new: fresh, duplicate: 0, conflict: 0 } },
  corpus_delta: null, reindexed: null, timings: null,
  reindex_deferred: pending === undefined ? null
    : { deferred: true, articles_pending: pending, started: true, job: "reindex-resume" },
});

test("Y4: 'Articles awaiting indexing' is the server's backlog, not the plan's new articles", () => {
  // The walk: a second 2,400-article import while the first one's re-index still owed
  // 1,900 -- the server measured 4,300 pending, and the line said 2,400.
  const html = render([viaProducer(deferredReport(2400, 4300))],
                      { state: "done", elapsed_s: 7, items_done: 1, items_total: 1 });
  assert(html.includes("Articles awaiting indexing: 4\u202F300"), html);
  assert(!html.includes("Articles awaiting indexing: 2\u202F400"), "the plan's new count is not the backlog");
  // ...and the caveat and the queue line are the SAME reading.
  assert(html.includes("4\u202F300 article(s) still to index"), html);
});

test("Y4: with no item snapshot, the line takes the re-index job's own read", () => {
  const html = render([viaProducer(deferredReport(2400))],
                      { state: "done", elapsed_s: 7, items_done: 1, items_total: 1,
                        rx: { backlog: { available: true, articles_pending: 5000 } } });
  assert(html.includes("Articles awaiting indexing: 5\u202F000"), html);
  assert(!html.includes("Articles awaiting indexing: 2\u202F400"), html);
  // Nothing read at all: no figure is invented from the plan.
  const none = render([viaProducer(deferredReport(2400))],
                      { state: "done", elapsed_s: 7, items_done: 1, items_total: 1 });
  assert(!none.includes("Articles awaiting indexing"), none);
});

test("Y4: a measured empty backlog grows no 'still indexing' caveat", () => {
  // A re-import whose every article was already here: 0 new, backlog measured at 0.
  const html = render([viaProducer(deferredReport(0, 0))],
                      { state: "done", elapsed_s: 7, items_done: 1, items_total: 1 });
  assert(!html.includes("Indexing continues"), "a caveat about work that does not exist: " + html);
  assert(!html.includes("awaiting indexing"), html);
});

test("Y1: a source's details wrap its folder name and scroll their own body", () => {
  const name = "202609261808_OpenOmniscience_Backup_2";
  const html = render([ok(name, 1200, 0), ok("b", 1200, 0)],
                      { state: "done", elapsed_s: 13, items_done: 2, items_total: 2 });
  const at = html.indexOf("<summary", html.indexOf("Details by source"));
  const blk = html.slice(at, html.indexOf("</details>", at));
  assert(/<summary[^>]*overflow-wrap:anywhere[^>]*><bdi>/.test(blk), "the summary name may wrap, isolated: " + blk);
  assert(blk.indexOf('<div style="overflow-x:auto">') !== -1, "the plan table scrolls in its own box: " + blk);
});

test("Y1: a date in the date-range row never breaks inside itself", () => {
  const snap = (a, b) => ({ articles: 1, sources: 1, languages: 1, countries: 0, keywords: 1, date_min: a, date_max: b });
  const html = mod._uxCorpusDeltaView(snap("2023-01-07", "2026-07-29"), snap("2023-01-07", "2026-09-26"), (x) => x);
  const row = html.slice(html.indexOf("Date range"));
  const dates = row.match(/<span dir="ltr" style="unicode-bidi:isolate;white-space:nowrap">[0-9-]{10}<\/span>/g) || [];
  assert(dates.length === 4, "each of the four dates is one isolated, unbreakable token: " + row);
});

test("W9: a signed corpus delta keeps its sign on the number's left in an RTL panel", () => {
  // A leading "+"/"-" is a weak bidi character: bare, it resolved to the Arabic
  // paragraph's direction and read "2,400+". Each delta is a first-strong isolate.
  const snap = (n) => ({ articles: n, sources: 5, languages: 2, countries: 3, keywords: 10, date_min: null, date_max: null });
  const html = mod._uxCorpusDeltaView(snap(100), snap(2500), (x) => x);
  assert(html.includes("⁨+2 400⁩"), "the growth is not isolated: " + html);
  const shrink = mod._uxCorpusDeltaView(snap(2500), snap(100), (x) => x);
  assert(shrink.includes("⁨-2 400⁩"), "a decrease is not isolated: " + shrink);
  assert(html.includes("⁨±0⁩"), "a zero delta is not isolated: " + html);
});

test("W7: the per-backup table is marked to stack at phone width", () => {
  const html = render([ok("202609261808_OpenOmniscience_Backup", 1000, 0), ok("b", 250, 0)],
                      { state: "done", elapsed_s: 60, items_done: 2, items_total: 2 });
  assert(/<table class="ux-peritem"/.test(html), "the per-item table carries no stacking hook: " + html);
});

test("Y1: a conflict sample (one JSON token) may break rather than widen the table", () => {
  const src2 = [extract("function _v2PlanTable("),
    "function esc(s){return String(s==null?'':s);}", "return _v2PlanTable;"].join("\n");
  const table = new Function("window", src2)({});
  const out = table({ sources: { new: 0, duplicate: 6, conflict: 1,
    conflicts: [{ domain: "icj-cij.org", incoming_name: "International Court of Justice" }] } });
  assert(/<td colspan="4"[^>]*overflow-wrap:anywhere/.test(out), out);
});

test("Y9: a per-item free-space refusal is written from the keyed frame", () => {
  const err = "Not enough free space for the restore: needs about 1.5 GB, only 200.0 MB free at /mnt/x. "
    + "Free up space or choose another location, or use the large-data/volume backup for a big corpus.";
  const html = render([ok("a", 10, 0), { title: "b", state: "error", error: err, elapsed_s: 1, plan: {} }],
                      { state: "error", elapsed_s: 5, items_done: 1, items_total: 2 });
  assert(html.includes("Restore: not enough free space"), "the page's frame, not the server's words: " + html);
  assert(!html.includes("Not enough free space for the restore"), html);
});

test("_uxFmtDur refuses to invent a duration it does not have", () => {
  assert(mod._uxFmtDur(null) === "—", "a missing measurement is not 0 s");
  assert(mod._uxFmtDur(undefined) === "—", "undefined is not 0 s");
  assert(mod._uxFmtDur(-1) === "—", "a negative is not a duration");
  assert(mod._uxFmtDur(0) === "\u20680.0\u00a0s\u2069", "a real zero IS reportable");
  assert(mod._uxFmtDur(61585).includes("17\u00a0h"), "hours are readable, not '61585.0 s'");
});

console.log(`\n${passed} passed`);
