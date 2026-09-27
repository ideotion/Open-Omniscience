// The Quality gates panel's repaint and refusal paths, run as REAL code (the 2026-09-26
// delegated click-through, row S: S1, S2 and S8).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// WHY BEHAVIOURAL. Each defect here was a line that existed and did the wrong thing:
//   S1 -- `_apiErrorMessage(e)` read `res.status` with no `res`, so the catch block that
//         was meant to SHOW the merge's refusal threw a TypeError itself, and the line
//         under the button read "Merging…" forever. A grep for "_apiErrorMessage" finds
//         the call either way.
//   S2 -- `undoAdmission` refreshed two of the panel's three live parts; the headline
//         stayed stale. Only calling it shows which loaders run.
//   S8 -- the audit printed its stamps raw. Only rendering a row shows what the reader
//         gets.
// EXTRACTED from the shipped modules, never re-typed: a copy would pass while the real
// code stayed broken.

"use strict";

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const start = APP.slice(at - 6, at) === "async " ? at - 6 : at;
  // Balanced PARENS first, then the body brace (a `{}` default parameter would
  // otherwise truncate the slice to the signature).
  let i = APP.indexOf("(", at), depth = 0;
  for (; i < APP.length; i++) {
    if (APP[i] === "(") depth++;
    else if (APP[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = APP.indexOf("{", i);
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(start, j);
}

const ESC = "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n";

function load(names, prelude, exportsList) {
  const src = ESC + (prelude || "") + "\n" + names.map(extract).join("\n") +
    "\nmodule.exports = {" + (exportsList || names).join(",") + "};";
  const m = { exports: {} };
  new Function("module", "exports", "require", src)(m, m.exports, require);
  return m.exports;
}

(async () => {
  // ------------------------------------------------------------------ S1, the helper
  {
    const { _apiErrorMessage } = load(["_apiErrorMessage"]);
    // THE REGRESSION: one argument, an Error with no `.detail`. It used to throw.
    let out;
    assert.doesNotThrow(() => { out = _apiErrorMessage(new Error("x.yml: not valid JSON (…)")); },
      "a caught Error with no .detail must not throw inside the catch block");
    assert.strictEqual(out, "x.yml: not valid JSON (…)");
    // An Error that api() raised carries `.detail`, and the detail still wins.
    const e = new Error("ignored"); e.detail = "the server's own words";
    assert.strictEqual(_apiErrorMessage(e), "the server's own words");
    // Every pre-existing two-argument shape is unchanged.
    const res = { status: 409, statusText: "Conflict" };
    assert.strictEqual(_apiErrorMessage(null, res), "409 Conflict");
    assert.strictEqual(_apiErrorMessage({ detail: "" }, res), "409 Conflict");
    assert.strictEqual(_apiErrorMessage({ detail: [{ msg: "a" }, { msg: "b" }] }, res), "a; b");
  }

  // ------------------------------------------------------------------ S1, the merge
  // The server refuses the upload; the refusal must reach the line under the button, the
  // button must come back, and nothing may download.
  for (const body of [
    { status: 400, statusText: "Bad Request", json: { detail: "x.yml: not valid JSON (Expecting value)." } },
    { status: 500, statusText: "Internal Server Error", json: null },   // a plain-text body
  ]) {
    const els = {
      "qual-ov-merge-out": { textContent: "", innerHTML: "" },
      "qual-ov-files": { files: [{ name: "x.yml" }] },
    };
    const saved = [];
    const mod = load(["_apiErrorMessage", "overlayMerge"], `
      var window = {};
      var _qualMergeLast = null;
      function _renderOverlayMerge() { throw new Error("a refusal must not render a report"); }
      function $(id) { return __els[id]; }
      function _qualTf(s, v) { return String(s).replace(/\\{(\\w+)\\}/g, (m, k) => v[k]); }
      function _overlaySaveAs(text, name) { __saved.push(name); }
      class FormData { append() {} }
      async function fetch() {
        return { ok: false, status: __body.status, statusText: __body.statusText,
                 json: async () => { if (__body.json === null) throw new SyntaxError("Unexpected token I"); return __body.json; } };
      }
      var __els, __saved, __body;
      module.exports.__set = (e, s, b) => { __els = e; __saved = s; __body = b; };
    `, ["overlayMerge", "__set: module.exports.__set"]);
    mod.__set(els, saved, body);
    const btn = { disabled: false };
    await mod.overlayMerge(btn);
    const shown = els["qual-ov-merge-out"].textContent;
    assert.ok(shown !== "Merging…", "the merge line is stuck on Merging…: " + shown);
    if (body.json) assert.strictEqual(shown, body.json.detail, "the server's refusal must be shown verbatim");
    else assert.strictEqual(shown, "500 Internal Server Error", "a body with no detail still says its status");
    assert.strictEqual(saved.length, 0, "a refused merge must not download anything");
    assert.strictEqual(btn.disabled, false, "the button must come back after a refusal");
  }

  // ------------------------------------------------------------------ S3, the merge report
  // A merge report is tf() frames welded to counts, so a language switch must be able to
  // redraw it from the payload it kept -- and a LATER refusal must drop that payload, or
  // the next switch would paint an old success over the refusal the operator is reading.
  {
    const els = {
      "qual-ov-merge-out": { textContent: "", innerHTML: "" },
      "qual-ov-files": { files: [] },
    };
    const mod = load(["_apiErrorMessage", "overlayMerge", "_renderOverlayMerge"], `
      var window = { OOI18N: { t: (s) => __lang + ":" + s, tf: (s, v) => __lang + ":" + String(s).replace(/\\{(\\w+)\\}/g, (m, k) => v[k]) } };
      var OOI18N = window.OOI18N;
      var _qualMergeLast = null;
      function _qualTf(s, v) { return OOI18N.tf(s, v); }
      function $(id) { return __els[id]; }
      function _overlaySaveAs() {}
      class FormData { append() {} }
      async function fetch() { return __res; }
      var __els, __lang = "en", __res;
      module.exports.__set = (e) => { __els = e; };
      module.exports.__lang = (l) => { __lang = l; };
      module.exports.__res = (r) => { __res = r; };
    `, ["overlayMerge", "_renderOverlayMerge", "__set: module.exports.__set",
        "__lang: module.exports.__lang", "__res: module.exports.__res"]);
    mod.__set(els);
    mod.__res({ ok: true, status: 200, json: async () => ({
      merged_verdicts: 2, overlay_yaml: "verdicts: []\n", note: "Nothing was written.",
      report: { added: 1, updated: 0, carried_through_untouched: 1, conflicts: [], inputs: [] } }) });
    await mod.overlayMerge({ disabled: false });
    assert.ok(els["qual-ov-merge-out"].innerHTML.includes("en:2 verdicts in the merged file"),
      els["qual-ov-merge-out"].innerHTML);
    mod.__lang("fr");
    mod._renderOverlayMerge();
    assert.ok(els["qual-ov-merge-out"].innerHTML.includes("fr:2 verdicts in the merged file"),
      "the kept report must repaint in the new language: " + els["qual-ov-merge-out"].innerHTML);
    mod.__res({ ok: false, status: 400, statusText: "Bad Request",
                json: async () => ({ detail: "junk.yml: no 'verdicts' list" }) });
    await mod.overlayMerge({ disabled: false });
    mod.__lang("zh");
    mod._renderOverlayMerge();
    assert.strictEqual(els["qual-ov-merge-out"].textContent, "junk.yml: no 'verdicts' list",
      "a repaint after a refusal must leave the refusal on screen");
  }

  // ------------------------------------------------------------------ S2, the undo
  {
    const calls = [];
    const mod = load(["undoAdmission"], `
      var window = {};
      async function api() { return { undone: true }; }
      function toast() {}
      function loadQualificationGates() { __calls.push("gates"); }
      function loadAdmissionAudit() { __calls.push("audit"); }
      function _qualScopeCount() { __calls.push("scope"); }
      function _apiErrorMessage(e) { return e.message; }
      var __calls;
      module.exports.__set = (c) => { __calls = c; };
    `, ["undoAdmission", "__set: module.exports.__set"]);
    mod.__set(calls);
    await mod.undoAdmission(7, { disabled: false });
    assert.ok(calls.includes("gates"),
      "an undo must repaint the WHOLE panel (the headline too), not only the audit: " + calls);
  }

  // ------------------------------------------------------------------ S8, the stamps
  {
    const BASE = {
      id: 7, source_id: 3, domain: "example.test", name: "Example",
      occurred_at: "2026-09-18T09:00:00+00:00", verdict: "qualified",
      prior_enabled: false, prior_status: "unqualified",
      undone: true, undone_at: "2026-09-26T19:56:47+00:00",
      reversible: false, blocked_by: "already-undone",
    };
    const withFmt = load(["ooLabelHtml", "_admissionRow"],
      "var window = {};\nfunction fmtDateTime(ts) { return 'FMT[' + ts + ']'; }");
    const out = withFmt._admissionRow(BASE);
    for (const iso of [BASE.occurred_at, BASE.undone_at]) {
      assert.ok(out.includes("FMT[" + iso + "]"),
        "each stamp must go through the shared date formatter: " + out);
      assert.ok(out.includes('title="' + iso + '"'), "the exact stamp stays in the hover: " + out);
    }
    const stamps = out.match(/<span class="qual-when"[^>]*>/g) || [];
    assert.strictEqual(stamps.length, 2, "both stamps are marked: " + out);
    for (const s of stamps) assert.ok(/white-space:nowrap/.test(s), "a stamp must not wrap mid-token: " + s);
    assert.ok(/<div style="flex:0 0 auto">/.test(out),
      "the action column must size to its content, so the info column is not squeezed: " + out);
    assert.ok(!/dir="ltr"/.test(out), "a localised date must not be forced left-to-right: " + out);

    // Without the formatter (a node harness, a boot-time render) the raw stamp still shows.
    const bare = load(["ooLabelHtml", "_admissionRow"], "var window = {};")._admissionRow(BASE);
    assert.ok(bare.includes(BASE.occurred_at), bare);
  }

  console.log("quality_gates_repaint_node_test: all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
