/**
 * Behavioural node test for the notes under the vLLM server-log view (what the shown text leaves
 * out, and where a complete copy of a failed start is). Run by tests/test_vllm_log_notes.py, and
 * standalone: `node tests/vllm_log_notes_node_test.js`. The function is EXTRACTED FROM THE REAL
 * FILE, never re-typed here.
 */
"use strict";
const APP = require("./app_source.js").appJs();
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert(at !== -1, "could not find " + name);
  let depth = 0;
  for (let j = APP.indexOf("{", at); j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces");
}
const window = {};
const vllmLogNotes = eval("(" + extract("vllmLogNotes") + ")");

assert(vllmLogNotes(null).length === 0 && vllmLogNotes({}).length === 0, "nothing to say, nothing said");
const whole = vllmLogNotes({ server_log: { available: true, scanned_whole: true } });
assert(whole.length === 0, "a whole-scanned log carries no note");
const part = vllmLogNotes({ server_log: { available: true, scanned_whole: false } });
assert(part.length === 1 && /middle of this log was not read/.test(part[0]), "a partly scanned log says its middle was not read");
const server = vllmLogNotes({ server_log: { available: true, tail_note: "TAIL-NOTE", held_back_note: "HELD-NOTE" } });
assert(server[0] === "TAIL-NOTE" && server[1] === "HELD-NOTE", "the server's own notes are shown as written, in order");
const kept = vllmLogNotes({ start_outcome: { preserved_log_path: "/d/failed/x.log" } });
assert(kept.length === 1 && kept[0].indexOf("/d/failed/x.log") !== -1, "the path of the complete copy is named");
const why = vllmLogNotes({ start_outcome: { preserved_log_reason: "REASON-TEXT" } });
assert(why.length === 1 && why[0].indexOf("REASON-TEXT") !== -1, "the reason there is no copy is named");
const both = vllmLogNotes({ start_outcome: { preserved_log_path: "/p", preserved_log_reason: "R" } });
assert(both.length === 1 && both[0].indexOf("/p") !== -1, "a path wins over a reason");
const pend = vllmLogNotes({ start_outcome: { preserved_log_reason: "STILL-COPYING", preserved_log_pending: true } });
assert(pend.length === 1 && pend[0] === "STILL-COPYING", "a copy in progress is said as it is, not as 'no copy'");
console.log("VLLM LOG NOTES OK");
