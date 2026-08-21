// The family identity colour, run as real code (ruling 14, field feedback 2026-08-07).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// famHue was keyed on the family's POSITION in the rendered list, so a family with no
// cards this pass shifted every family after it to a different colour. An identity
// colour that moves for reasons unrelated to the identity is worse than no colour.
//
// EXTRACTED from src/static/app.js rather than re-typed -- a re-typed copy would pass
// while the shipped function was broken.
//
// WHY BEHAVIOURAL AND NOT A SOURCE GREP: the fix's own comment necessarily quotes the
// old `bi * 53` form to explain what was removed, so a source assertion would be
// satisfied by the explanation of the rule it guards (the recorded trap). What matters
// is what the function RETURNS for a given family, so families are fed in.

const fs = require("fs");
const path = require("path");
const assert = require("assert");

// The UI engine is ordered modules since the S-3 decomposition; ask the shared
// helper, which reads the module list out of index.html and cannot drift.
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Scan to the signature's balanced parens, THEN take the body brace, so a `{}` in a
  // default parameter cannot truncate the slice to the signature alone.
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, "famHue not found in app.js -- was it renamed?");
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

function objectLiteral(name) {
  const at = APP.indexOf("const " + name + " = {");
  assert.ok(at !== -1, name + " not found in app.js");
  const open = APP.indexOf("{", at);
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j) + ";";
}

// Load the REAL shipped code.
const ctx = {};
new Function("ctx", objectLiteral("FAM_HUE") + "\n" + extract("famHue")
  + "\nctx.famHue = famHue; ctx.FAM_HUE = FAM_HUE;")(ctx);
const { famHue, FAM_HUE } = ctx;

const hueOf = (s) => {
  const m = /^hsl\((\d+(?:\.\d+)?) /.exec(s);
  assert.ok(m, "famHue must return an hsl() string, got: " + s);
  return parseFloat(m[1]);
};

// The eight shipped families, in src/briefing/card.py BUCKETS order.
const BUCKETS = ["rising", "overtold", "undertold", "investigate",
                 "debunk", "watch", "context", "trust"];

// ---------------------------------------------------------------------------
// 1. THE DISCRIMINATING CASE. The old implementation took the index, so removing
//    an empty family shifted every later family's colour. Keyed on the name, the
//    colour is a property of the family and nothing else.
// ---------------------------------------------------------------------------
{
  const full = BUCKETS.map(famHue);
  // "overtold" produced no cards this pass, so it is omitted from the render.
  const without = BUCKETS.filter((b) => b !== "overtold");
  without.forEach((b) => {
    assert.strictEqual(
      famHue(b), full[BUCKETS.indexOf(b)],
      `${b} changed colour because a DIFFERENT family was empty -- that is the bug`);
  });
}

// ---------------------------------------------------------------------------
// 2. It must key on the machine name, never the translated label. A French
//    reader and an English reader must see the same family in the same colour.
// ---------------------------------------------------------------------------
{
  assert.strictEqual(famHue("rising"), famHue("rising"));
  assert.notStrictEqual(
    famHue("rising"), famHue("Rising now"),
    "a display label must not be a valid key -- if it were, translating it would recolour the family");
}

// ---------------------------------------------------------------------------
// 3. The eight shipped families must be pairwise DISTINGUISHABLE. A hash alone
//    can place two of them a few degrees apart, and "these two look the same" is
//    the failure being fixed, so the curated table is checked, not assumed.
// ---------------------------------------------------------------------------
{
  const hues = BUCKETS.map((b) => hueOf(famHue(b)));
  hues.forEach((h, i) => {
    hues.forEach((k, j) => {
      if (i >= j) return;
      const d = Math.abs(h - k);
      const sep = Math.min(d, 360 - d);   // hue is circular
      assert.ok(sep >= 30,
        `${BUCKETS[i]} (${h}) and ${BUCKETS[j]} (${k}) are only ${sep}deg apart`);
    });
  });
  assert.strictEqual(new Set(hues).size, BUCKETS.length, "two families share a hue");
  // Every shipped family is curated, so none of them depends on the fallback.
  BUCKETS.forEach((b) => assert.ok(FAM_HUE[b] != null, b + " is not in the curated table"));
}

// ---------------------------------------------------------------------------
// 4. NEGATIVE SPACE: a family added later, with no curated entry, must still get
//    a stable colour rather than throwing or rendering "hsl(undefined ...)".
// ---------------------------------------------------------------------------
{
  const a = famHue("some-future-family");
  assert.strictEqual(a, famHue("some-future-family"), "the fallback must be deterministic");
  const h = hueOf(a);
  assert.ok(h >= 0 && h < 360, "fallback hue out of range: " + h);
  assert.ok(!/NaN|undefined/.test(a), "fallback produced a broken colour: " + a);
  // A missing/empty key must degrade, never throw -- a colour is decorative and must
  // never be able to take the Home feed down.
  ["", null, undefined].forEach((k) => {
    const c = famHue(k);
    assert.ok(!/NaN|undefined/.test(c), "famHue(" + String(k) + ") produced: " + c);
  });
}

console.log("fam_hue_node_test: OK - 4 groups passed");
