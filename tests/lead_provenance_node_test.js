// A Lead's provenance travels into its analysis window, and is shown there.
// Rulings 15/16 (field feedback 2026-08-07).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// EXTRACTED from src/static/app.js rather than re-typed -- a copy would pass while the
// shipped code was broken.
//
// WHY BEHAVIOURAL: the two claims that matter are "the caveat is VISIBLE, not behind the
// details toggle" (invariant #23) and "an analysis with no Lead behind it shows NO
// header rather than an invented one". A source grep proves neither -- the recorded trap
// is that a guard over a disclosure survives the mutation that deletes the disclosure,
// because the identifier still appears in the surrounding code and comments. So the real
// renderer is driven and its OUTPUT is read.

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const APP = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app.js"), "utf8");

function fnSource(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found in app.js -- renamed?");
  let i = APP.indexOf("(", at), depth = 0;
  for (; i < APP.length; i++) {                    // balance the SIGNATURE parens first,
    if (APP[i] === "(") depth++;                   // so a `{}` default parameter cannot
    else if (APP[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = APP.indexOf("{", i);                // ...THEN take the body brace.
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j);
}
function objLiteral(name) {
  const at = APP.indexOf("const " + name + " = {");
  assert.ok(at !== -1, name + " not found");
  const open = APP.indexOf("{", at);
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j) + ";";
}

// ---- a minimal host element + the stubs the renderer legitimately depends on ----
function makeHost() {
  const style = {
    _v: {},
    setProperty(k, v) { this._v[k] = v; },
    removeProperty(k) { delete this._v[k]; },
  };
  return { hidden: false, innerHTML: "", style };
}

function load(host) {
  const ctx = {};
  const prelude = `
    const $ = (id) => (id === "an-prov" ? __host : null);
    const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
      c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));
    const window = {};      // no OOI18N -> t() falls back to identity, as in a fresh boot
  `;
  new Function("__host", "ctx",
    prelude + objLiteral("FAM_HUE") + "\n" + fnSource("famHue") + "\n"
    + fnSource("_anRenderProvenance")
    + "\nctx.render = _anRenderProvenance;")(host, ctx);
  return ctx.render;
}

const CAVEAT = "Co-occurrence in your corpus, never causation.";
const METHOD = "Distinct sources citing the same origin, counted.";
const FULL = {
  card: "Three outlets cite one origin",
  bucket: "overtold",
  family: "Overtold",
  producer: "source_laundering",
  trigger: { plain: "Several sources trace back to one origin.",
             math: [{ label: "distinct sources", value: "3" }] },
  method: METHOD,
  caveat: CAVEAT,
};

// ---------------------------------------------------------------------------
// 1. All six fields ruling 16 names actually reach the reader.
// ---------------------------------------------------------------------------
{
  const host = makeHost();
  load(host)(FULL);
  assert.strictEqual(host.hidden, false, "a Lead-opened analysis must show its header");
  const h = host.innerHTML;
  assert.ok(h.includes("Three outlets cite one origin"), "the CARD is missing");
  assert.ok(h.includes("Overtold"), "the FAMILY is missing");
  assert.ok(h.includes("source laundering"), "the PRODUCER is missing");
  assert.ok(h.includes("Several sources trace back to one origin."), "the TRIGGER is missing");
  assert.ok(h.includes("distinct sources") && h.includes("3"), "the trigger MATH is missing");
  assert.ok(h.includes(METHOD), "the METHOD is missing");
  assert.ok(h.includes(CAVEAT), "the CAVEAT is missing");
}

// ---------------------------------------------------------------------------
// 2. INVARIANT #23: the caveat is VISIBLE, never inside the collapsed <details>
//    that holds the exact math. Checked positionally on the rendered output --
//    "the string appears somewhere" would pass with it buried in the toggle.
// ---------------------------------------------------------------------------
{
  const host = makeHost();
  load(host)(FULL);
  const h = host.innerHTML;
  const cav = h.indexOf(CAVEAT);
  const det = h.indexOf("<details");
  assert.ok(cav !== -1, "caveat absent");
  assert.ok(det !== -1, "precondition: this fixture has math, so a <details> must exist");
  assert.ok(cav < det, "the caveat must render BEFORE (outside) the collapsed details block");
  assert.ok(/class="card-caveat"/.test(h), "the caveat must use the visible .card-caveat line");
}

// ---------------------------------------------------------------------------
// 3. NEGATIVE SPACE: an analysis that did NOT come from a Lead shows no header.
//    Attributing a plain search to a producer that never ran would be a
//    fabricated attribution -- the failure that matters more than a missing box.
// ---------------------------------------------------------------------------
{
  for (const empty of [null, undefined, {}, { bucket: "rising" }]) {
    const host = makeHost();
    host.hidden = false; host.innerHTML = "stale";
    load(host)(empty);
    assert.strictEqual(host.hidden, true,
      "no card provenance must mean NO header, not an empty or invented one: "
      + JSON.stringify(empty));
    assert.strictEqual(host.innerHTML, "", "a stale header must be cleared, not left behind");
  }
}

// ---------------------------------------------------------------------------
// 4. A partial provenance renders what it HAS and invents nothing. An older
//    persisted seed can legitimately lack the trigger.
// ---------------------------------------------------------------------------
{
  const host = makeHost();
  load(host)({ card: "A lead", producer: "rising", caveat: CAVEAT });
  const h = host.innerHTML;
  assert.strictEqual(host.hidden, false);
  assert.ok(h.includes("A lead") && h.includes(CAVEAT));
  assert.ok(!h.includes("<details"), "no math -> no empty math toggle");
  assert.ok(!/Why am I seeing this\?/.test(h), "no trigger -> no empty 'why' heading");
  assert.ok(!/undefined|null|NaN/.test(h), "a missing field must be omitted, never printed: " + h);
}

// ---------------------------------------------------------------------------
// 5. The family colour is the SAME function Home paints with, keyed on the same
//    stable bucket name -- a Lead and its analysis must read as one family.
// ---------------------------------------------------------------------------
{
  const host = makeHost();
  const render = load(host);
  render(FULL);
  const ctx = {};
  new Function("ctx", objLiteral("FAM_HUE") + "\n" + fnSource("famHue")
    + "\nctx.famHue = famHue;")(ctx);
  assert.strictEqual(host.style._v["--fam"], ctx.famHue("overtold"),
    "the header must use famHue(bucket), so it matches the card on Home");
  // ...and a provenance with no family must not paint a stale accent.
  const host2 = makeHost();
  host2.style.setProperty("--fam", "hsl(1 1% 1%)");
  load(host2)({ card: "x", producer: "rising" });
  assert.strictEqual(host2.style._v["--fam"], undefined,
    "no family -> no accent, never the previous card's colour");
}

console.log("lead_provenance_node_test: OK - 5 groups passed");
