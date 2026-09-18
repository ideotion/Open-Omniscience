// The 0.4 release-run panel renderer, run as REAL code (2026-09-18).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// WHAT IS GUARDED: that every board row the report carries reaches the screen with
// its OWN status word (a renderer that drew only the tally would hide which row is
// not-measurable-here), that an INTERIM report is marked as one (a partial reading
// presented as the final is the two-hour-reading-with-a-three-day-label defect), that
// the note beside a row is drawn (the note is where "measured" is qualified), and that
// both download links are offered. Extracted from the shipped module, never re-typed.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
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
  return APP.slice(at, j);
}

const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  "var window = { OOI18N: { t: (s) => '[' + s + ']' } };\n" +
  // A bare `OOI18N` read inside `window.OOI18N && OOI18N.t` needs the global too.
  "var OOI18N = window.OOI18N;\n" +
  extract("_rrRenderReport") + "\n" +
  "module.exports = { _rrRenderReport };";
const { _rrRenderReport } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const report = {
  interim: true,
  warnings: ["the 'million' profile was chosen but this corpus holds 412 articles"],
  soak: { elapsed_hours: 1.5, hours_requested: 72, ended_by: "collect-now" },
  board_rows: [
    { row: "A", status: "measured", clause: "one committed import", note: "the drain's outcome is on row E" },
    { row: "B", status: "not-measurable-here", clause: "memory flat across >= 72 h", note: "" },
    { row: "C", status: "error", clause: "one bundle", note: "the bundle did not finish here" },
  ],
  summary: { rows_by_status: { "measured": 1, "not-measurable-here": 1, "error": 1 }, note: "A tally of statuses, never a score." },
};

// 1. every row, with its own status word, uppercased so it reads as a verdict token
const host = { innerHTML: "" };
_rrRenderReport(host, report);
const html = host.innerHTML;
assert.ok(html.includes("[MEASURED]") && html.includes("A —"), "row A with its status: " + html);
assert.ok(html.includes("[NOT-MEASURABLE-HERE]") && html.includes("B —"), "row B with its status");
assert.ok(html.includes("[ERROR]") && html.includes("C —"), "row C with its status");

// 2. the note beside a row is drawn (mutation: dropping the note branch reddens here)
assert.ok(html.includes("the drain&#39;s outcome is on row E") || html.includes("the drain's outcome is on row E"),
  "row A's note must render");

// 3. an interim report says so, and the soak line carries what the window actually got
assert.ok(html.includes("INTERIM"), "an interim report must be marked INTERIM");
assert.ok(html.includes("1.5 / 72 h") && html.includes("collect-now"), "the soak line: " + html);

// 4. the tally, the warning, the summary note, both download links -- through t()
assert.ok(html.includes("measured 1") && html.includes("error 1"), "the tally");
assert.ok(html.includes("412 articles"), "warnings render");
assert.ok(html.includes("never a score"), "the summary note");
assert.ok(html.includes("/api/diagnostics/release-run/download?format=json"), "json link");
assert.ok(html.includes("/api/diagnostics/release-run/download?format=txt"), "txt link");
assert.ok(html.includes("[Download report (.json)]"), "the link label goes through t()");

// 5. a final report is NOT marked interim; a report with no rows still renders the links
const host2 = { innerHTML: "" };
_rrRenderReport(host2, { interim: false, board_rows: [], summary: {} });
assert.ok(!host2.innerHTML.includes("INTERIM"), "a final report carries no INTERIM mark");
assert.ok(host2.innerHTML.includes("download?format=json"), "links even with no rows");

// 6. a null host is a no-op, never a throw (the renderer may run before the panel exists)
_rrRenderReport(null, report);

console.log("release_run_panel_node_test: 6 checks passed");
