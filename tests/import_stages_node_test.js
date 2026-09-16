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
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function fmtDateTime(x){return 'DATE';}",
  "return { _uxImReindexBits, _uxImStatements, _uxImRenderStages, _uxImLastLineHtml,"
  + " _uxImCheckpointHtml, _uxImHistoryHtml, _uxPatchRow, _uxPruneRows };",
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
  for (const id of ["ux-imp-stages", "ux-imp-statements"]) dom[id] = makeNode();
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
  assert(got.indexOf("var(--err)") !== -1, "an interrupted run is drawn as if pending");
  // ...and the real progress is still there beside it, never replaced by the ending.
  assert(text("ux-imp-stages").indexOf("2 of 4") !== -1, got);

  resetDom();
  mod._uxImRenderStages({ stages: [{ ...ended, state: "pending" }] }, RX_CLEAN, t, tf);
  const live = html("ux-imp-stages");
  assert(live.indexOf("Interrupted") === -1, "a live run must not claim an ending");
  assert(live.indexOf("var(--err)") === -1, "a live run is not an error");
});

console.log("\n" + passed + " passed");
