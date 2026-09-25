// The task manager's "why is this download not moving" line, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// S04-08's S5 (Q1014): a download held by airplane mode read as a bare "paused", the same
// as one the operator stopped, and a failed one showed no reason though the owner kept
// it -- a proxy that refused was invisible here. `_jobWhy` names the cause. What it must
// NOT do matters as much: draw a cause for a running download, draw one for a job kind
// that is not a download, or guess a cause the payload did not carry.
//
// Extracted from the shipped files; a re-typed copy would pass while the real one broke.
// TWO renderers draw a job row: app-core.js's in-app window, and taskmanager.html -- the
// page the top-bar task-manager button actually opens. The first walk found the cause on
// the one nobody was looking at, so every assertion below runs against BOTH.

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const TM = fs.readFileSync(path.join(__dirname, "..", "src", "static", "taskmanager.html"), "utf8");

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

function load(src, name) {
  const m = { exports: {} };
  new Function("module", "exports", src + "\nmodule.exports = " + name + ";")(m, m.exports);
  return m.exports;
}

// app-core.js: `_isDownloadKind` is a const arrow, one statement -- take it by its own
// terminator. Its esc is shared from elsewhere in the bundle, so a stand-in is used.
const kAt = APP.indexOf("const _isDownloadKind");
assert.ok(kAt !== -1, "_isDownloadKind is gone -- was it renamed?");
const appWhy = load(
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  APP.slice(kAt, APP.indexOf(";", kAt) + 1) + "\n" + extract(APP, "_jobWhy"), "_jobWhy");

// taskmanager.html: its OWN esc and isDl, and a page-global t() -- bound per call here.
const dAt = TM.indexOf("var isDl = function");
assert.ok(dAt !== -1, "taskmanager.html's isDl is gone -- was it renamed?");
const tmSrc = extract(TM, "esc") + "\n" + TM.slice(dAt, TM.indexOf("};", dAt) + 2) + "\n" +
  extract(TM, "jobWhy");
const tmWhy = (j, t) => {
  const m = { exports: {} };
  new Function("module", "exports", "t", tmSrc + "\nmodule.exports = jobWhy;")(m, m.exports, t);
  return m.exports(j);
};

const t = (s) => s;
const KINDS = ["wiki-dump", "osm-map"];

for (const [RENDERER, _jobWhy] of [["app-core.js _jobWhy", appWhy], ["taskmanager.html jobWhy", tmWhy]]) {

  // --- each cause, on both download kinds -------------------------------------------- //
  for (const kind of KINDS) {
    const why = (j) => _jobWhy(Object.assign({ kind }, j), t);
    assert.ok(/Paused by airplane mode/.test(why({ state: "paused", paused_by: "airplane" })), RENDERER + " " + kind);
    assert.ok(/Resume asks to go online first/.test(why({ state: "paused", paused_by: "airplane" })),
      RENDERER + " " + kind + ": the airplane line does not say what Resume will do");
    assert.ok(/Paused by you\./.test(why({ state: "paused", paused_by: "operator" })), RENDERER + " " + kind);
    assert.ok(/partial file is kept/.test(why({ state: "paused", paused_by: "restart" })), RENDERER + " " + kind);
    // The airplane cause must never read as the operator's own pause, nor the reverse.
    assert.ok(!/by you/.test(why({ state: "paused", paused_by: "airplane" })), RENDERER + " " + kind);
    assert.ok(!/airplane/.test(why({ state: "paused", paused_by: "operator" })), RENDERER + " " + kind);
    // No cause in the payload (an entry saved before the field): say nothing, never guess.
    assert.strictEqual(why({ state: "paused" }), "", RENDERER + " " + kind + ": a cause was guessed");
    assert.strictEqual(why({ state: "paused", paused_by: "someone-new" }), "",
      RENDERER + " " + kind + ": an unknown cause was drawn as a known one");
    // Failed: the owner's own error, verbatim and escaped.
    const f = why({ state: "failed", error: "TransportUnavailable: <no proxy>" });
    assert.ok(f.includes("Failed: TransportUnavailable: &lt;no proxy&gt;"), RENDERER + " " + kind + ": " + f);
    assert.strictEqual(why({ state: "failed", error: null }), "", RENDERER + " " + kind + ": a failure with no error drew a line");
    // A running or queued download has nothing to explain, even with a stale cause.
    for (const state of ["running", "queued", "done"]) {
      assert.strictEqual(why({ state, paused_by: "airplane", error: "x" }), "", RENDERER + " " + kind + "/" + state);
    }
  }

  // --- a job that is not a download is not this function's to explain ---------------- //
  for (const kind of ["collect", "folder-import", "reindex"]) {
    assert.strictEqual(_jobWhy({ kind, state: "paused", paused_by: "airplane" }, t), "", RENDERER + " " + kind);
    assert.strictEqual(_jobWhy({ kind, state: "failed", error: "boom" }, t), "", RENDERER + " " + kind);
  }

  // --- translated: the causes are caveat text, so they ship x12 ----------------------- //
  {
    const shout = (s) => s.toUpperCase();
    const out = _jobWhy({ kind: "wiki-dump", state: "paused", paused_by: "airplane" }, shout);
    assert.ok(out.includes("PAUSED BY AIRPLANE MODE"), RENDERER + ": the cause bypassed the translator: " + out);
    // ...but the owner's error is data, not prose: it is never sent through t().
    const f = _jobWhy({ kind: "osm-map", state: "failed", error: "OSError: reset" }, shout);
    assert.ok(f.includes("FAILED: OSError: reset"), RENDERER + ": " + f);
  }

}

// Each renderer must actually DRAW the line, not only define it.
assert.ok(/prog \+ jobWhy\(j\)/.test(TM), "taskmanager.html defines jobWhy but its rows never call it");
assert.ok(/\$\{prog\}\$\{_jobWhy\(j, t\)\}/.test(APP), "app-core.js defines _jobWhy but its rows never call it");

console.log("job_why_node_test: all assertions passed");
