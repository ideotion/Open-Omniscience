// The admission audit's row renderer, run as REAL code (S04-12 S1, ruling Q1101).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// WHY THIS IS BEHAVIOURAL AND NOT A SOURCE GREP. What is guarded is that an Undo button
// is NOT drawn for a row the endpoint would refuse -- and the draw call for that button
// sits INSIDE the branch that decides. So neutering the decision leaves every token the
// grep looks for exactly where it was: `assert "data-undo" in src` passes against a
// renderer that offers the button unconditionally, and `assert "reversible" in src`
// passes against one that ignores the field. Only running the function can tell a live
// branch from a dead one. (The recorded "a source guard cannot tell a live branch from a
// dead one" lesson; this is the case it names.)
//
// EXTRACTED from the shipped module rather than re-typed -- a re-typed copy would pass
// while the real renderer was broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace: a `{}` in a default parameter would
  // otherwise truncate the slice to the signature alone (the recorded ooChart trap).
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
  "var window = {};\n" +   // OOI18N absent = the boot-time state, so t()'s fallback runs
  extract("_admissionRow") + "\n" +
  "module.exports = { _admissionRow };";
const { _admissionRow } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const BASE = {
  id: 7, source_id: 3, domain: "example.test", name: "Example",
  occurred_at: "2026-09-18T00:00:00", verdict: "qualified",
  prior_enabled: false, prior_status: "unqualified", undone_at: null, undone: false,
};

// --- a reversible row OFFERS the button ------------------------------------ //
{
  const out = _admissionRow({ ...BASE, reversible: true, blocked_by: null });
  assert.ok(/data-undo="7"/.test(out), "a reversible row must offer Undo: " + out);
  assert.ok(/<button/.test(out), out);
}

// --- a row a LATER VERDICT replaced offers NO button, and says why ---------- //
{
  const out = _admissionRow({
    ...BASE, reversible: false, blocked_by: "later-verdict-in-effect",
  });
  assert.ok(!/data-undo/.test(out),
    "a row the endpoint would refuse must NOT offer an Undo button: " + out);
  assert.ok(!/<button/.test(out), "no button at all on a refused row: " + out);
  assert.ok(/A later verdict replaced this one/.test(out),
    "the reason the panel gives must name the later verdict: " + out);
}

// --- a row a LATER ADMISSION supersedes says THAT, not the same sentence ---- //
{
  const out = _admissionRow({
    ...BASE, reversible: false, blocked_by: "later-admission-in-effect",
  });
  assert.ok(!/data-undo/.test(out), out);
  assert.ok(/A later admission of this source is in effect/.test(out),
    "the two blockers must not collapse onto one sentence: " + out);
}

// --- an unknown token still refuses, and never falls through to a button ---- //
// A token this renderer has no label for is a payload from a newer server; drawing the
// button would be the one outcome that is wrong in both directions at once.
{
  const out = _admissionRow({ ...BASE, reversible: false, blocked_by: "something-new" });
  assert.ok(!/data-undo/.test(out), "an unknown blocker must not restore the button: " + out);
  assert.ok(/Cannot be undone/.test(out), out);
}

// --- an UNDONE row keeps its own treatment, unchanged ---------------------- //
// `undone` and `reversible` are different questions; an undone row already had a
// rendering and must not start reading as "blocked" instead.
{
  const out = _admissionRow({
    ...BASE, undone: true, undone_at: "2026-09-19T00:00:00",
    reversible: false, blocked_by: "already-undone",
  });
  assert.ok(!/data-undo/.test(out), out);
  assert.ok(/Undone/.test(out), "an undone row must still read as undone: " + out);
  assert.ok(!/Already undone/.test(out),
    "the undone branch owns this row -- the blocker sentence must not double it: " + out);
}

// --- NEGATIVE-SPACE TWIN: an OLD payload (no `reversible` at all) still works //
// A client can be newer than its server across a reload, and an absent field must not be
// read as "blocked" -- that would silently remove the safety valve from every row.
{
  const out = _admissionRow({ ...BASE });
  assert.ok(/data-undo="7"/.test(out),
    "a payload with no `reversible` field must keep offering Undo: " + out);
}

console.log("admission_row_node_test: all assertions passed");
