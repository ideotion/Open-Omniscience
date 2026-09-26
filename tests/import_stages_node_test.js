/**
 * Node test for the import lifecycle's PURE renderers (`S04-02`, Q201-Q206, Q222).
 *
 * WHY BEHAVIOURAL AND NOT A SOURCE GREP. Every claim below is of the form "this line
 * SAYS X" or "this row does NOT claim Y", and a substring assertion over app-backup.js
 * proves only that a token appears somewhere in the slice -- the recorded trap that
 * `read the field and throw it away` keeps every needle and changes the output. So the
 * functions are EXTRACTED FROM THE REAL module and EXECUTED; a re-typed copy would
 * pass while the shipped code was broken.
 *
 * THE NEGATIVE SPACE IS MOST OF IT. A stage with no counter must render indeterminate
 * rather than a percentage; an unread re-index status must say so rather than show 0;
 * a run that has not saved must not say the import files can be removed. Each of those
 * has its positive twin beside it, because an over-eager refusal invents an outage as
 * dishonestly as a fabricated number invents progress.
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
  // Start brace-matching at the BODY brace: scan forward until the PARENTHESES
  // balance, then take the next "{" (the recorded default-parameter trap).
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

// All THREE tables, from the item-state labels through the stage labels: a stage row in an
// ENDED state is labelled from _UX_IM_STATE_LABEL, so slicing only the stage table left the
// renderer reaching for a name that was not in the module.
const stageTable = APP.slice(
  APP.indexOf("const _UX_IM_STATE_LABEL = {"),
  APP.indexOf("function _uxRowNode("),
);
assert(stageTable.indexOf("verify_stage:") !== -1, "the stage-label table did not extract");
assert(stageTable.indexOf("_UX_IM_ENDED") !== -1, "the ended-state table did not extract");
assert(stageTable.indexOf("interrupted:") !== -1, "the item-state labels did not extract");

const src = [
  stageTable,
  extract("function _uxRowNode("),
  extract("function _uxPatchRow("),
  extract("function _uxPruneRows("),
  extract("function _uxVolPhase("),
  extract("function _uxImReindexBits("),
  extract("function _uxImStatements("),
  extract("function _uxImRenderStatements("),
  extract("function _uxImRenderStages("),
  extract("function _uxImLastLineHtml("),
  extract("function _uxImCheckpointHtml("),
  extract("function _uxImHistoryHtml("),
  // 2026-09-26 (batch B1): the reopen's decision, the run summary behind the "Last
  // import" line, and the guarded start -- all pure, or pure but for the one `api`
  // call the stub below answers.
  extract("function _uxImStage4Owed("),
  extract("function _uxImFreshView("),
  extract("function _uxImRunSummary("),
  extract("function _uxImInterruptedHtml("),
  extract("function _uxImRenderFresh("),
  extract("async function _uxImStartGuarded("),
  "let _uxImLastStatus = null; let _uxImView = null;",
  "let __api = null; function api(u, o) { return __api(u, o); }",
  "function __setApi(f) { __api = f; }",
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function fmtDateTime(x){return 'DATE';}",
  "return { _uxImReindexBits, _uxImStatements, _uxImRenderStages, _uxImLastLineHtml,"
  + " _uxImCheckpointHtml, _uxImHistoryHtml, _uxPatchRow, _uxPruneRows,"
  + " _uxImStage4Owed, _uxImFreshView, _uxImRunSummary, _uxImRenderFresh,"
  + " _uxImStartGuarded, __setApi, view: () => _uxImView };",
].join("\n");

function makeNode() {
  const attrs = {};
  const node = {
    innerHTML: "", dataset: {}, children: [], style: {},
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
    appendChild(c) { c._parent = node; node.children.push(c); return c; },
    remove() { const p = node._parent; if (p) p.children = p.children.filter((c) => c !== node); },
  };
  return node;
}
const dom = {};
function resetDom() {
  for (const id of ["ux-imp-stages", "ux-imp-statements", "ux-imp-queue",
                    "ux-imp-queue-note", "ux-imp-queue-rows"]) dom[id] = makeNode();
}
const document = { getElementById: (id) => dom[id] || null, createElement: () => makeNode() };
const mod = new Function("window", "document", src)({}, document);

const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
const html = (id) => dom[id].children.map((c) => c.innerHTML).join("\n");
// The row's visible TEXT. A numeric assertion over raw markup is a non-unique needle
// by construction -- the state dot carries `border-radius:50%`, so "this row shows no
// percentage" matched the dot and failed against correct code on its first run.
const text = (id) => html(id).replace(/<[^>]*>/g, " ");

// ── stage 4's line: three states that must not collapse ──────────────────────
test("an unread re-index status says so and never shows a zero", () => {
  const out = mod._uxImReindexBits(null, t, tf);
  assert(out.indexOf("could not be read") !== -1, "an unread status must say so");
  assert(!/\b0\b/.test(out), "it must not print a count it does not have: " + out);
});

test("an unreadable BACKLOG is distinguished from an unread job", () => {
  const out = mod._uxImReindexBits({ state: "idle", backlog: { available: false } }, t, tf);
  assert(out.indexOf("backlog could not be read") !== -1, out);
});

test("a measured empty backlog says complete", () => {
  const out = mod._uxImReindexBits(
    { state: "idle", backlog: { available: true, articles_pending: 0 } }, t, tf);
  assert(out.indexOf("complete") !== -1, out);
  assert(out.indexOf("could not") === -1, "a measured zero must not read as unread");
});

test("a pending backlog states the real figure", () => {
  const out = mod._uxImReindexBits(
    { state: "idle", backlog: { available: true, articles_pending: 12340 } }, t, tf);
  assert(/12,?340/.test(out), out);
});

test("a running drain reports the job's own measured progress", () => {
  const out = mod._uxImReindexBits(
    { state: "running", done: 40, total: 100, backlog: { available: true, articles_pending: 60 } },
    t, tf);
  assert(out.indexOf("resuming re-index") !== -1, out);
  assert(out.indexOf("40") !== -1 && out.indexOf("100") !== -1, out);
});

test("a running drain with no total says it is resuming and invents no numerator", () => {
  const out = mod._uxImReindexBits({ state: "running", done: 0, total: 0 }, t, tf);
  assert(out.indexOf("resuming re-index") !== -1, out);
  assert(out.indexOf(" of ") === -1, "no denominator exists, so none may be drawn: " + out);
});

// ── the three statements (Q203) ──────────────────────────────────────────────
const RX_CLEAN = { state: "idle", backlog: { available: true, articles_pending: 0 } };
const RX_PENDING = { state: "idle", backlog: { available: true, articles_pending: 900 } };

test("nothing saved yet: the files must be kept and closing costs work", () => {
  const out = mod._uxImStatements({ items: [{ kind: "corpus", state: "staged" }] }, RX_CLEAN, t, tf);
  assert(out[0].ok === false && out[0].text.indexOf("Keep the import files") === 0, out[0].text);
  assert(out[1].ok === false && out[1].text.indexOf("Closing the app now") === 0, out[1].text);
});

test("every item saved: the files can go and the app can be closed", () => {
  const out = mod._uxImStatements({ items: [{ kind: "corpus", state: "done" }] }, RX_CLEAN, t, tf);
  assert(out[0].ok === true && out[0].text.indexOf("can be removed") !== -1, out[0].text);
  assert(out[1].ok === true && out[1].text.indexOf("Safe to close") === 0, out[1].text);
  assert(out[1].text.indexOf("re-index") !== -1, "it must say what resumes: " + out[1].text);
});

test("ONE unsaved item is enough to withhold both statements", () => {
  const out = mod._uxImStatements(
    { items: [{ kind: "corpus", state: "done" }, { kind: "corpus", state: "staged" }] },
    RX_CLEAN, t, tf);
  assert(out[0].ok === false && out[1].ok === false, "a group is saved or it is not");
});

test("a still-running blobs item withholds both safety statements", () => {
  // THE ADVERSARIAL FINDING, 2026-09-16. _uxImScan pre-checks every box, so a real
  // folder yields corpus + blobs + newsletters from ONE click, all pointing at the same
  // source. The corpus restore finishes first (seconds); the blobs copy can run for
  // hours. Filtering the statements to the restore kinds announced "the import files can
  // be removed" while that copy was still reading the folder it names.
  const out = mod._uxImStatements(
    { items: [{ kind: "corpus", state: "done" }, { kind: "blobs", state: "running" }] },
    RX_CLEAN, t, tf);
  assert(out[0].ok === false, "the folder is still being read: " + out[0].text);
  assert(out[1].ok === false, "closing now would abandon the copy: " + out[1].text);
});

test("a FAILED blobs item also withholds them -- in the other direction", () => {
  // Not merely "nothing is running": the folder still holds something that never
  // arrived, so "everything they carried is in your corpus" is false either way.
  const out = mod._uxImStatements(
    { items: [{ kind: "corpus", state: "done" }, { kind: "blobs", state: "error" }] },
    RX_CLEAN, t, tf);
  assert(out[0].ok === false, out[0].text);
});

test("a whole run that succeeded does make both statements", () => {
  const out = mod._uxImStatements(
    { items: [{ kind: "corpus", state: "done" }, { kind: "blobs", state: "done" },
              { kind: "newsletters", state: "skipped" }] },
    RX_CLEAN, t, tf);
  assert(out[0].ok === true && out[1].ok === true, "nothing is left to wait for");
});

test("a blobs-only run does not claim its corpus is saved", () => {
  const out = mod._uxImStatements({ items: [{ kind: "blobs", state: "done" }] }, RX_CLEAN, t, tf);
  assert(out[0].ok === false, "there is no corpus import here to have saved");
});

test("analytics: pending, complete and unreadable are three different sentences", () => {
  const pending = mod._uxImStatements({ items: [{ kind: "corpus", state: "done" }] }, RX_PENDING, t, tf)[2];
  const done = mod._uxImStatements({ items: [{ kind: "corpus", state: "done" }] }, RX_CLEAN, t, tf)[2];
  const unread = mod._uxImStatements({ items: [{ kind: "corpus", state: "done" }] }, null, t, tf)[2];
  assert(pending.ok === false && pending.text.indexOf("900") !== -1, pending.text);
  assert(pending.text.indexOf("no keywords") !== -1, "the consequence is the point: " + pending.text);
  assert(done.ok === true && done.text.indexOf("complete") !== -1, done.text);
  assert(unread.ok === false && unread.text.indexOf("could not be read") !== -1, unread.text);
  assert(unread.text !== done.text && unread.text !== pending.text, "three states, three sentences");
});

// ── the four stage rows (Q202) ───────────────────────────────────────────────
const STAGES = [
  { n: 1, key: "verify_stage", state: "done", done: 2, total: 2, failed: 0, measured: true },
  { n: 2, key: "merge_swap", state: "running", done: 1, total: 2, failed: 0, measured: true,
    phase: "merging", phase_stage_is_exact: true },
  { n: 3, key: "search_index", state: "pending", done: 0, total: 1, measured: false,
    reason: "SQLite publishes no progress" },
  { n: 4, key: "reindex", state: "external", measured: false, reads: "/x" },
];

test("all four rows render, in order, each named", () => {
  resetDom();
  mod._uxImRenderStages({ stages: STAGES }, RX_CLEAN, t, tf);
  const rows = dom["ux-imp-stages"].children;
  assert(rows.length === 4, "expected four rows, got " + rows.length);
  assert(rows.map((r) => r.getAttribute("data-row-key")).join(",")
         === "verify_stage,merge_swap,search_index,reindex", "row order");
  const body = html("ux-imp-stages");
  for (const label of ["Check the backup", "Merge it into your corpus",
                       "Merge the search index", "Re-index the imported"]) {
    assert(body.indexOf(label) !== -1, "missing row label: " + label);
  }
});

test("a measured row shows its real fraction", () => {
  resetDom();
  mod._uxImRenderStages({ stages: STAGES }, RX_CLEAN, t, tf);
  assert(html("ux-imp-stages").indexOf("1 of 2 backups") !== -1, html("ux-imp-stages"));
});

test("the search-index row draws NO number at all", () => {
  resetDom();
  mod._uxImRenderStages({ stages: [STAGES[2]] }, RX_CLEAN, t, tf);
  const out = text("ux-imp-stages");
  assert(out.indexOf("3.") !== -1, "the row is drawn: " + out);
  assert(!/\d+ of \d+/.test(out), "an unmeasured stage must not show a fraction: " + out);
  assert(!/\d+\s*%/.test(out), "nor a percentage: " + out);
});

test("stage 4 links the task manager (Q204)", () => {
  resetDom();
  mod._uxImRenderStages({ stages: [STAGES[3]] }, RX_CLEAN, t, tf);
  assert(html("ux-imp-stages").indexOf("openTaskManager()") !== -1, html("ux-imp-stages"));
});

test("an older server with no stages gets NO rows rather than four empty ones", () => {
  resetDom();
  mod._uxImRenderStages({}, RX_CLEAN, t, tf);
  assert(dom["ux-imp-stages"].children.length === 0);
  assert(dom["ux-imp-stages"].innerHTML === "");
});

test("a failed count is shown beside the fraction, never folded into it", () => {
  resetDom();
  mod._uxImRenderStages({ stages: [{ ...STAGES[0], done: 1, total: 3, failed: 2 }] }, RX_CLEAN, t, tf);
  const out = html("ux-imp-stages");
  assert(out.indexOf("1 of 3 backups") !== -1, out);
  assert(out.indexOf("2 failed") !== -1, out);
});

// ── Q206: patched in place, and the no-write property ────────────────────────
test("an unchanged row is not rewritten at all", () => {
  const host = makeNode();
  const el = mod._uxPatchRow(host, "k", "sig-1", "<b>one</b>");
  let writes = 0;
  Object.defineProperty(el, "innerHTML", {
    get() { return "<b>one</b>"; }, set(_v) { writes += 1; }, configurable: true,
  });
  mod._uxPatchRow(host, "k", "sig-1", "<b>one</b>");
  assert(writes === 0, "an identical signature must not touch the DOM");
  mod._uxPatchRow(host, "k", "sig-2", "<b>two</b>");
  assert(writes === 1, "a changed signature must write exactly once");
  assert(host.children.length === 1, "patching must not append a second node");
});

test("a row that leaves the list is pruned, and the others survive", () => {
  const host = makeNode();
  mod._uxPatchRow(host, "a", "1", "A");
  mod._uxPatchRow(host, "b", "1", "B");
  mod._uxPruneRows(host, ["a"]);
  assert(host.children.length === 1 && host.children[0].getAttribute("data-row-key") === "a");
});

// ── Q201: the quiet line ─────────────────────────────────────────────────────
test("the last-import line states the count and links the report", () => {
  const out = mod._uxImLastLineHtml(
    { filename: "restore-x.json", created_at: "2026-09-12T10:45:00Z", articles: 12340,
      articles_basis: "merged", outcome: "ok" }, t, tf);
  assert(out.indexOf("Last import") !== -1, out);
  assert(/12,?340 articles/.test(out), out);
  assert(out.indexOf("import-reports/restore-x.json") !== -1, out);
  assert(out.indexOf("did not complete") === -1, "a clean run must not be labelled: " + out);
});

test("a report with no article figure prints no number", () => {
  const out = mod._uxImLastLineHtml(
    { filename: "r.json", created_at: "2026-09-12T10:45:00Z", outcome: "unknown" }, t, tf);
  assert(!/\d+ articles/.test(out), "an absent figure must not become 0: " + out);
  assert(out.indexOf("did not complete") !== -1, "an unknown outcome is labelled: " + out);
});

test("an aborted run's figure is labelled PLANNED, never merged", () => {
  const out = mod._uxImLastLineHtml(
    { filename: "r.json", created_at: "x", articles: 686896, articles_basis: "planned",
      outcome: "killed" }, t, tf);
  assert(out.indexOf("planned") !== -1, out);
});

test("no report at all renders nothing", () => {
  assert(mod._uxImLastLineHtml(null, t, tf) === "");
  assert(mod._uxImLastLineHtml({}, t, tf) === "");
});

// ── Q216: the checkpoint sentence ────────────────────────────────────────────
test("K = 3 states what a stop before a save costs", () => {
  const out = mod._uxImCheckpointHtml(3, t, tf);
  assert(out.indexOf("every 3 backups") !== -1, out);
  assert(out.indexOf("nothing is durable") !== -1, "the cost is the point: " + out);
});

test("K = 1 promises nothing about losing work", () => {
  const out = mod._uxImCheckpointHtml(1, t, tf);
  assert(out.indexOf("as soon as it finishes") !== -1, out);
  assert(out.indexOf("nothing is durable") === -1, "at K=1 there is nothing to warn about: " + out);
});

test("an unread K makes no claim at all", () => {
  for (const bad of [null, undefined, 0, -1, "x"]) {
    assert(mod._uxImCheckpointHtml(bad, t, tf) === "", "K=" + bad);
  }
});

// ── Q222: the history list ───────────────────────────────────────────────────
test("an empty history is an honest empty state, not a blank", () => {
  const out = mod._uxImHistoryHtml([], t, tf);
  assert(out.indexOf("No imports recorded yet") !== -1, out);
});

test("a history row names its outcome and labels a planned figure", () => {
  const out = mod._uxImHistoryHtml([
    { filename: "a.json", created_at: "x", kind: "restore", articles: 10, articles_basis: "merged", outcome: "ok" },
    { filename: "b.json", created_at: "y", kind: "restore", articles: 99, articles_basis: "planned", outcome: "killed" },
    { filename: "c.json", created_at: "z", kind: "restore", outcome: "unknown" },
  ], t, tf);
  assert(out.indexOf("10 articles") !== -1, out);
  assert(out.indexOf("99 articles planned") !== -1, out);
  assert(out.indexOf("article count not recorded") !== -1, "an absent count says so: " + out);
  assert(out.indexOf("killed") !== -1 && out.indexOf("unknown") !== -1, out);
  assert(out.indexOf("import-reports/b.json") !== -1, out);
});


test("a stage row on an ENDED run says which ending, never just a grey pending", () => {
  // The backend distinguishes "two still to come" from "the app died after two"; the
  // renderer drew both grey with the same text, so the distinction existed and could not
  // be seen. The four words come from _UX_IM_STATE_LABEL, already shipped x12.
  const ended = { n: 1, key: "verify_stage", state: "interrupted", done: 2, total: 4,
                  failed: 2, measured: true, unit: "backups" };
  resetDom();
  mod._uxImRenderStages({ stages: [ended] }, RX_CLEAN, t, tf);
  const got = html("ux-imp-stages");
  assert(got.indexOf("Interrupted") !== -1, "the ending is not named: " + got);
  // The DOT, not any red on the row: since I9 (2026-09-26) the "2 failed" count is red
  // TEXT rather than the toast box, so a bare "var(--err)" needle also matches a pending
  // row that merely reports failures -- a non-unique needle, the recorded trap.
  assert(got.indexOf("background:var(--err)") !== -1, "an interrupted run is drawn as if pending");
  // ...and the real progress is still there beside it, never replaced by the ending.
  assert(text("ux-imp-stages").indexOf("2 of 4") !== -1, got);

  resetDom();
  mod._uxImRenderStages({ stages: [{ ...ended, state: "pending" }] }, RX_CLEAN, t, tf);
  const live = html("ux-imp-stages");
  assert(live.indexOf("Interrupted") === -1, "a live run must not claim an ending");
  assert(live.indexOf("background:var(--err)") === -1, "a live run is not an error");
});

// ── I2 (2026-09-26): analytics are complete AFTER stage 4, never at the start ─
const RUN_START = { state: "running",
                    items: [{ kind: "corpus", state: "running" }, { kind: "corpus", state: "queued" }] };

test("I2: a run in flight never says analytics are complete", () => {
  // THE WALK: "✓ Analytics are complete — every imported article is indexed" at
  // "0/4 imported". An empty backlog then is a fact about the corpus BEFORE the import.
  const s = mod._uxImStatements(RUN_START, RX_CLEAN, t, tf)[2];
  assert(s.ok === false, "a check mark at 0 of 4 imported: " + s.text);
  assert(s.text.indexOf("once the re-index (stage 4) finishes") !== -1, s.text);
});

test("I2: row 4 of a run in flight reads 'not started', not 'complete'", () => {
  assert(mod._uxImReindexBits(RX_CLEAN, t, tf, RUN_START) === "not started",
    mod._uxImReindexBits(RX_CLEAN, t, tf, RUN_START));
  resetDom();
  mod._uxImRenderStages({ ...RUN_START, stages: [STAGES[3]] }, RX_CLEAN, t, tf);
  const out = text("ux-imp-stages");
  assert(out.indexOf("not started") !== -1 && out.indexOf("complete") === -1, out);
});

test("I2: a drain still running holds the statement back even at a zero backlog", () => {
  const s = mod._uxImStatements({ state: "done", items: [{ kind: "corpus", state: "done" }] },
    { state: "running", done: 4800, total: 4800, backlog: { available: true, articles_pending: 0 } },
    t, tf)[2];
  assert(s.ok === false, "stage 4 is still going: " + s.text);
});

test("I2: ...and the finished run's measured zero still says complete (the twin)", () => {
  const st = { state: "done", items: [{ kind: "corpus", state: "done" }] };
  assert(mod._uxImStatements(st, RX_CLEAN, t, tf)[2].ok === true, "an over-eager refusal invents an outage");
  assert(mod._uxImReindexBits(RX_CLEAN, t, tf, st) === "complete");
});

// ── I1 / I3 (2026-09-26): what a REOPEN shows (R1 fresh page; Q204/Q205 stage 4) ─
const DONE_RUN = { state: "done", items: [{ kind: "corpus", state: "done" }],
                   stages: STAGES.map((s) => ({ ...s, state: "done" })) };
const RX_DRAINING = { state: "running", done: 1200, total: 4800,
                      backlog: { available: true, articles_pending: 3600 } };

test("I3: a finished run with nothing owed reopens onto a fresh page", () => {
  const v = mod._uxImFreshView(DONE_RUN, RX_CLEAN);
  assert(!v.full && !v.interrupted && !v.stage4, JSON.stringify(v));
  resetDom();
  mod._uxPatchRow(dom["ux-imp-queue-rows"], "old", "x", "a row the last opening drew");
  mod._uxImRenderFresh(DONE_RUN, RX_CLEAN, t, tf);
  assert(dom["ux-imp-queue"].style.display === "none", "the run box is not shown at all");
  assert(dom["ux-imp-queue-rows"].children.length === 0, "the previous run's rows are gone");
  assert(dom["ux-imp-stages"].children.length === 0, "no stage rows");
  assert(dom["ux-imp-statements"].innerHTML === "", "no statements");
  assert(mod.view() === "fresh", "the view says which page it is");
});

test("I1/I3: a stage 4 still owed stands alone beside the quiet line, and says so", () => {
  for (const rx of [RX_PENDING, RX_DRAINING]) {
    const v = mod._uxImFreshView(DONE_RUN, rx);
    assert(!v.full && v.stage4 && !v.interrupted, JSON.stringify(v));
    resetDom();
    mod._uxImRenderFresh(DONE_RUN, rx, t, tf);
    assert(dom["ux-imp-queue"].style.display === "", "the stage-4 row is shown");
    const keys = dom["ux-imp-stages"].children.map((c) => c.getAttribute("data-row-key"));
    assert(keys.join(",") === "reindex", "stage 4 ALONE, never the whole run again: " + keys);
    const stm = dom["ux-imp-statements"].innerHTML;
    assert((stm.match(/<div>/g) || []).length === 1, "only the analytics statement: " + stm);
    assert(stm.indexOf("Safe to close") === -1, stm);
    assert(dom["ux-imp-queue-rows"].children.length === 0, "no per-backup rows");
  }
  resetDom();
  mod._uxImRenderFresh(DONE_RUN, RX_DRAINING, t, tf);
  assert(text("ux-imp-stages").indexOf("resuming re-index") !== -1, text("ux-imp-stages"));
});

test("I3: an interrupted run keeps its one red line on the fresh page", () => {
  const st = { state: "interrupted", items: [{ kind: "corpus", state: "interrupted" }] };
  const v = mod._uxImFreshView(st, RX_CLEAN);
  assert(v.interrupted && !v.full && !v.stage4, JSON.stringify(v));
  resetDom();
  mod._uxImRenderFresh(st, RX_CLEAN, t, tf);
  assert(html("ux-imp-queue-note").indexOf("start it again") !== -1, html("ux-imp-queue-note"));
  assert(html("ux-imp-queue-note").indexOf('class="note') === -1, "coloured text, not the toast box");
});

test("I1/I3: a running run is the full view, and nothing at all is not a run", () => {
  assert(mod._uxImFreshView(RUN_START, RX_CLEAN).full === true);
  const none = mod._uxImFreshView({ state: "idle", items: [] }, RX_PENDING);
  assert(!none.full && !none.interrupted && !none.stage4, "no run, no stage 4 to show");
});

test("I1: stage 4 is owed while draining or with a measured backlog; unknown is not owed", () => {
  assert(mod._uxImStage4Owed(RX_DRAINING) === true);
  assert(mod._uxImStage4Owed({ state: "paused" }) === true);
  assert(mod._uxImStage4Owed(RX_PENDING) === true);
  assert(mod._uxImStage4Owed(RX_CLEAN) === false);
  assert(mod._uxImStage4Owed(null) === false);
  assert(mod._uxImStage4Owed({ state: "idle", backlog: { available: false } }) === false);
});

// ── I7 (2026-09-26): the "Last import" line is the RUN, not its last backup ───
const rep = (over) => ({ filename: "restore-x.json", created_at: "2026-09-26T18:11:00Z",
                         articles: 1200, articles_basis: "merged", outcome: "ok", run_id: "r1", ...over });

test("I7: the newest run's reports are summed into ONE import", () => {
  const s = mod._uxImRunSummary([
    rep({ filename: "restore-4.json" }), rep({ filename: "restore-3.json" }),
    rep({ filename: "restore-2.json" }), rep({ filename: "restore-1.json" }),
    rep({ filename: "restore-old.json", run_id: "r0", articles: 99 }),
  ]);
  assert(s.articles === 4800, "four 1,200-article backups are one 4,800-article import: " + s.articles);
  assert(s.filename === "restore-4.json", "the link stays the newest report");
  const line = mod._uxImLastLineHtml(s, t, tf);
  assert(/4,?800 articles/.test(line) && !/1,?200 articles/.test(line), line);
});

test("I7: a member with no figure, or only a PLANNED one, makes the total unknown", () => {
  const a = mod._uxImRunSummary([rep({}), rep({ articles: null })]);
  assert(a.articles === null, "a part is not the whole: " + a.articles);
  const b = mod._uxImRunSummary([rep({}), rep({ articles_basis: "planned", outcome: "killed" })]);
  assert(b.articles === null && b.outcome === "killed", JSON.stringify(b));
  assert(mod._uxImLastLineHtml(b, t, tf).indexOf("did not complete") !== -1);
});

test("I7: an older report with no run id is quoted exactly as before", () => {
  const old = rep({ run_id: undefined, articles: 933 });
  assert(mod._uxImRunSummary([old, rep({})]) === old, "no run id, no grouping");
  assert(mod._uxImRunSummary([]) === null);
});

test("I7/I12: the history names each backup, isolated for right-to-left pages", () => {
  const out = mod._uxImHistoryHtml([rep({ label: "202609261808_OpenOmniscience_Backup_2", kind: "restore" })], t, tf);
  assert(out.indexOf("<bdi") !== -1 && out.indexOf("202609261808_OpenOmniscience_Backup_2") !== -1, out);
});

// ── I8 (2026-09-26): a refused Verify never adopts the import's own restore ──
async function asyncTests() {
  const refused = () => Promise.reject(new Error("409 a job is already running"));
  mod.__setApi(async () => ({ state: "running", mode: "restore" }));
  let threw = null;
  try { await mod._uxImStartGuarded(refused, "/status", "verify"); } catch (e) { threw = e; }
  assert(threw && /409/.test(threw.message),
    "a live RESTORE is not the verify we asked for; the refusal must surface");
  passed += 1; console.log("ok  - I8: a live job of another mode is not the one we started");

  mod.__setApi(async () => ({ state: "running", mode: "verify" }));
  await mod._uxImStartGuarded(refused, "/status", "verify");   // resolves: it IS ours
  passed += 1; console.log("ok  - I8: a lost START over our own live verify is still accepted");

  mod.__setApi(async () => ({ state: "running", mode: "restore" }));
  await mod._uxImStartGuarded(refused, "/status");              // no mode: unchanged
  passed += 1; console.log("ok  - I8: a caller that names no mode keeps the old guard");
}

asyncTests().then(
  () => console.log("\n" + passed + " passed"),
  (e) => { console.error("FAIL: " + (e && e.message)); process.exit(1); },
);
