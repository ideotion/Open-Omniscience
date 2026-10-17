// The Library keywords-per-article tile, run as REAL code (extracted from the shipped module, not re-typed).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The server answers the first figures request with the count "computing" and says since when (pending_since). In a narrow race
// (the background refresh finishes before the start time is read) pending_since is null; `new Date(null)` is the EPOCH, so the tile
// printed "since 01:00:00": a made-up time. An unknown start is drawn as unknown.

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

const src = extract("_kwPerArticleTile") + "\nmodule.exports = { _kwPerArticleTile };";
const { _kwPerArticleTile } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const t = (s) => s;
const num = (n) => String(n);
const tile = (value, label, hint) => ({ value, label, hint });
const epoch = new Date(null).toLocaleTimeString();

// --- an unknown start is not the epoch -------------------------------------- //
{
  const out = _kwPerArticleTile({ keyword_mentions_state: "computing", pending_since: null }, t, num, tile);
  assert.ok(!out.hint.includes(epoch), "the computing tile printed the epoch as its start: " + out.hint);
  assert.ok(out.hint.includes("—"), "an unknown start is not drawn as unknown: " + out.hint);
}

// --- a known start is drawn --------------------------------------------------- //
{
  const iso = "2026-10-17T10:15:30Z";
  const out = _kwPerArticleTile({ keyword_mentions_state: "computing", pending_since: iso }, t, num, tile);
  assert.ok(out.hint.includes(new Date(iso).toLocaleTimeString()), "the known start is not drawn: " + out.hint);
}

// --- the failure times and the memory stop ----------------------------------- //
{
  const f = { kind: "memory-short", deadline_s: 300, at: "2026-10-17T10:15:30Z", retry_after_s: 900 };
  const out = _kwPerArticleTile({ keyword_mentions_state: "failed", keyword_mentions_failure: f }, t, num, tile);
  assert.ok(out.hint.includes("stopped because the machine was nearly out of memory"), "a memory stop is not named: " + out.hint);
  assert.ok(!out.hint.includes("limit"), "a memory stop was named as a time limit: " + out.hint);
  const g = Object.assign({}, f, { kind: "statement-deadline" });
  const o2 = _kwPerArticleTile({ keyword_mentions_state: "failed", keyword_mentions_failure: g }, t, num, tile);
  assert.ok(o2.hint.includes("passed its 300 s limit"), "the deadline is not named: " + o2.hint);
}
console.log("library_kw_tile: ok");
