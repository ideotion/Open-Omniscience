// What a folder RESTORE tells the operator it turned away, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The restore hashes every file as it streams and DISCARDS a member whose bytes do not
// match the checksum the backup recorded -- before it reaches the live data directory.
// That refusal is only honest end to end if the operator is told: a run that silently
// dropped three rotted dumps and printed "Done." reads as a complete restore, and the
// missing files surface later as a mystery. So the render is the honesty rail, and
// there is no browser here, so it is driven in node.
//
// EXTRACTED from the shipped module rather than re-typed: a re-typed copy would pass
// while the real renderer was broken. And asserted on what it SAYS, never on an
// identifier appearing somewhere in the file -- a guard over a disclosure survives the
// mutation that deletes the disclosure (the recorded `d.other` trap).

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

// OOI18N is absent, which is also the boot-time state, so this exercises the English
// fallback path -- the one a reader actually sees if i18n has not loaded yet.
const src = "var window = {};\n"
  + extract("_fbRefusalLines") + "\n"
  + "module.exports = { _fbRefusalLines };";
const { _fbRefusalLines } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

// --- a clean restore says nothing -------------------------------------------------
// The negative-space half, and it is load-bearing: a renderer that announced a refusal
// on every restore would satisfy every "the refusal is visible" assertion below while
// making the message meaningless.
assert.deepStrictEqual(
  _fbRefusalLines({ restored: 12, skipped: 3, corrupt_refused: 0, corrupt: [], restored_unverified: 0 }),
  [],
  "a restore that refused nothing and verified everything must render no caveat at all"
);
assert.deepStrictEqual(_fbRefusalLines({}), [], "an empty progress payload must not invent a refusal");

// --- a refusal is stated, with a count and the names ------------------------------
const refused = _fbRefusalLines({
  restored: 9,
  corrupt_refused: 2,
  corrupt: [
    { category: "wiki_dumps", rel: "enwiki-latest.xml.bz2" },
    { category: "osm_regions", rel: "europe/france.osm.pbf" },
  ],
  restored_unverified: 0,
});
assert.strictEqual(refused.length, 1, "one refusal line, not one per file: " + JSON.stringify(refused));
const line = refused[0];
assert.ok(/NOT restored/.test(line), "the line must say the files were not restored: " + line);
assert.ok(/checksum/.test(line), "the line must say WHY they were refused: " + line);
assert.ok(/: 2/.test(line), "the count must be stated, not implied: " + line);
// The NAMES are the actionable half -- they are what the operator re-downloads.
assert.ok(line.includes("wiki_dumps/enwiki-latest.xml.bz2"), "name the refused member: " + line);
assert.ok(line.includes("osm_regions/europe/france.osm.pbf"), "name every refused member: " + line);
assert.ok(!/more \(not shown\)/.test(line), "nothing was hidden, so nothing may claim to be: " + line);

// --- a long list is bounded, and says how much it bounded -------------------------
// Truncation stated, never silent: the backend caps the named list at 200, and the line
// shows a few. A reader must be able to tell "these are all of them" from "these are
// some of them", which is the whole difference between a list and a sample.
const many = [];
for (let i = 0; i < 20; i++) many.push({ category: "models", rel: "blobs/sha256-" + i });
const bounded = _fbRefusalLines({ corrupt_refused: 20, corrupt: many })[0];
assert.ok(/: 20/.test(bounded), "the TOTAL is the count, never the number shown: " + bounded);
assert.ok(/\+ 14 more \(not shown\)/.test(bounded), "the remainder must be stated: " + bounded);
assert.ok(bounded.includes("models/blobs/sha256-0"), "the shown names are still real: " + bounded);
assert.ok(!bounded.includes("models/blobs/sha256-19"), "20 names on one line is not a line: " + bounded);

// A count with no names at all (a payload that carried only the tally) must still
// state the refusal -- the count is the part that cannot be lost.
const countOnly = _fbRefusalLines({ corrupt_refused: 3 })[0];
assert.ok(/: 3/.test(countOnly), "a nameless refusal is still a refusal: " + countOnly);
assert.ok(!/—\s*$/.test(countOnly), "no dangling separator when there is nothing to name: " + countOnly);

// --- the unverified gap is its own line, and is NOT a refusal ---------------------
// Two different facts: "we checked and refused it" and "we could not check". Collapsing
// them would either invent a refusal or hide a gap.
const gap = _fbRefusalLines({ restored: 40, corrupt_refused: 0, restored_unverified: 40 });
assert.strictEqual(gap.length, 1, "the gap is one line: " + JSON.stringify(gap));
assert.ok(/: 40/.test(gap[0]), "the gap states its count: " + gap[0]);
assert.ok(!/NOT restored/.test(gap[0]), "an unverified file WAS restored -- it must not read as refused: " + gap[0]);
assert.ok(/not content-verified|no checksum/.test(gap[0]), "the gap must say what is missing: " + gap[0]);

// Both at once: two distinct lines, refusal first.
const both = _fbRefusalLines({ corrupt_refused: 1, corrupt: [{ category: "models", rel: "a" }], restored_unverified: 7 });
assert.strictEqual(both.length, 2, "a refusal and a gap are two facts: " + JSON.stringify(both));
assert.ok(/NOT restored/.test(both[0]), "the refusal leads -- it is the one that needs action");

console.log("all assertions passed");
