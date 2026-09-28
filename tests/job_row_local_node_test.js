// The task manager's controls for the LOCAL DB-writer jobs, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Row M5 of the 2026-09-26 delegated click-through: the keyword fold's row read
// "running · Folding keyword forms into their base form · 551 / 2254" with ZERO buttons,
// although /api/jobs listed ["pause","cancel"] (running) and ["resume","cancel"] (paused),
// and the fold button promises "pausable from the task manager". Both renderers drew
// controls only for the collect job, the download kinds and (app-core only) the re-index.
//
// What must NOT happen matters too: a Resume that asks to go online (a fold opens no
// connection), a Cancel beside Pause on a running job (both would pause), or a control the
// server did not list.
//
// Extracted from the shipped files; a re-typed copy would pass while the real one broke.
// TWO renderers draw a job row: app-core.js's in-app window and taskmanager.html (the page
// the top-bar task-manager button opens), so every assertion runs against BOTH.

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const TM = require("./app_source.js").pageSource("taskmanager.html");

function extract(SRC, name) {
  const at = SRC.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = SRC.indexOf("(", at), depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "(") depth++;
    else if (SRC[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = SRC.indexOf("{", i);
  let d = 0, j = open;
  for (; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return SRC.slice(at, j);
}

function statement(SRC, head) {
  const at = SRC.indexOf(head);
  assert.ok(at !== -1, head + " is gone -- was it renamed?");
  return SRC.slice(at, SRC.indexOf(";", at) + 1);
}

const ESC = "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}\n";

// app-core.js's _jobRow(j, queuedKeysByKind, t)
const appSrc = ESC +
  "function _fmtBytes(n){return n+' B';}\nfunction fmtNum(n){return String(n);}\n" +
  "function _rateNote(){return '';}\n" +
  statement(APP, "const _isDownloadKind") + "\n" +
  statement(APP, "const _LOCAL_JOB_KINDS") + "\n" +
  statement(APP, "const _dlKey") + "\n" +
  extract(APP, "_jobWhy") + "\n" + extract(APP, "_jobPct") + "\n" + extract(APP, "_jobLabel") + "\n" +
  extract(APP, "_jobRow");
const appRow = (() => {
  const m = { exports: {} };
  new Function("module", "exports", appSrc + "\nmodule.exports = _jobRow;")(m, m.exports);
  return (j, t) => m.exports(j, {}, t);
})();

// taskmanager.html's jobRow(j, queuedKeysByKind), with a page-global t()
// Each `var x = function (...) { ... };` is one line ending in "};".
function varFn(SRC, head) {
  const at = SRC.indexOf(head);
  assert.ok(at !== -1, "taskmanager.html: " + head + " is gone -- was it renamed?");
  return SRC.slice(at, SRC.indexOf("};", at) + 2);
}
const tmSrc = extract(TM, "esc") + "\n" + extract(TM, "fmtBytes") + "\n" + extract(TM, "tf") + "\n" +
  extract(TM, "fmtNum") + "\n" + extract(TM, "fmtDur") + "\n" + "var _langDN = {};\n" +
  extract(TM, "langName") + "\n" + extract(TM, "jobPct") + "\n" + extract(TM, "jobLabel") + "\n" +
  varFn(TM, "var isDl = function") + "\n" + varFn(TM, "var isLocal = function") + "\n" +
  varFn(TM, "var dlKey = function") + "\n" + extract(TM, "jobWhy") + "\n" + extract(TM, "jobRow");
const tmRow = (j, t) => {
  const m = { exports: {} };
  new Function("module", "exports", "t", tmSrc + "\nmodule.exports = jobRow;")(m, m.exports, t);
  return m.exports(j, {});
};

const t = (s) => s;
const buttons = (html) => [...html.matchAll(/<button([^>]*)>([^<]*)<\/button>/g)]
  .map((m) => ({ label: m[2], onclick: (m[1].match(/(?:data-on-click|onclick)="([^"]*)"/) || [])[1] ||
    // taskmanager.js binds by data-tm="<action>" through one delegated listener.
    ((m[1].match(/data-tm="([a-z]+)"/) || [])[1] ? "TM." + m[1].match(/data-tm="([a-z]+)"/)[1] + "(" : "") }));
const labels = (html) => buttons(html).map((b) => b.label);

const fold = (state, actions) => ({
  id: "keyword-fold", kind: "keyword-fold", state, actions,
  label: "Folding keyword forms into their base form",
  progress: { done: 551, total: 2254, unit: "keywords", percent: 24.4 },
});

for (const [R, row] of [["app-core.js _jobRow", appRow], ["taskmanager.html jobRow", tmRow]]) {
  // --- the fold: the controls the server lists, and only those ------------------------ //
  assert.deepStrictEqual(labels(row(fold("running", ["pause", "cancel"]), t)), ["Pause"],
    R + ": a running fold draws Pause, and never a second button that also pauses");
  assert.deepStrictEqual(labels(row(fold("paused", ["resume", "cancel"]), t)), ["Resume", "Cancel"], R);
  assert.deepStrictEqual(labels(row(fold("failed", ["resume", "cancel"]), t)), ["Resume", "Cancel"], R);
  assert.deepStrictEqual(labels(row(fold("paused", []), t)), [], R + ": a control the server did not list");
  // Pause and Cancel go to the jobs cancel route (it pauses a running fold, cancels a stopped
  // one); Resume to the resume route.
  const paused = buttons(row(fold("paused", ["resume", "cancel"]), t));
  assert.ok(/(jobResume|TM\.resume)\(/.test(paused[0].onclick), R + ": " + paused[0].onclick);
  assert.ok(/(jobCancel|TM\.cancel)\(/.test(paused[1].onclick), R + ": " + paused[1].onclick);

  // --- the other two local jobs keep Pause / Resume; no Cancel that would only pause --- //
  for (const kind of ["reindex", "search-reindex"]) {
    const j = (state, actions) => ({ id: kind, kind, state, actions, label: "x" });
    assert.deepStrictEqual(labels(row(j("running", ["pause", "cancel"]), t)), ["Pause"], R + " " + kind);
    assert.deepStrictEqual(labels(row(j("paused", ["resume", "cancel"]), t)), ["Resume"], R + " " + kind);
  }

  // --- a download is untouched: its own grammar still draws ----------------------------- //
  assert.deepStrictEqual(labels(row({ id: "dump:x", kind: "wiki-dump", state: "running", label: "d" }, t)), ["Pause"], R);

  // --- the label and the buttons go through the translator ----------------------------- //
  const shout = (s) => s.toUpperCase();
  const out = row(fold("paused", ["resume", "cancel"]), shout);
  assert.ok(out.includes("FOLDING KEYWORD FORMS INTO THEIR BASE FORM"), R + ": the job label bypassed t(): " + out);
  assert.deepStrictEqual(labels(out), ["RESUME", "CANCEL"], R);
}

// The in-app Resume of a LOCAL job never asks to go online (a fold opens no connection);
// a download's Resume still does (invariant #14).
{
  const html = appRow(fold("paused", ["resume", "cancel"]), t);
  assert.ok(/jobResume\([^)]*, true\)/.test(html), "the fold's Resume must pass local=true: " + html);
  const body = extract(APP, "jobResume");
  assert.ok(/!local && typeof ensureOnline/.test(body), "jobResume must skip the consent popup only for a local job");
  const dl = appRow({ id: "dump:x", kind: "wiki-dump", state: "paused", label: "d" }, t);
  assert.ok(/jobResume\("dump:x"\)/.test(dl.replace(/&quot;/g, '"')), "a download's Resume must still ask: " + dl);
}

console.log("job_row_local_node_test: all assertions passed");
