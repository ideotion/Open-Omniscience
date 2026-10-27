// The Wikidata fetch button's refusal, run as REAL code (invariant #14e's corollary; the same anchoring R298 gave the Python side).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// `entitySpineFetch` named the kill switch by a phrase search over the error text (`/airplane mode/i`), so a failure whose text merely
// QUOTED those words (a 502 that echoed a remote page, a redirect text) toasted "Refused: airplane mode is on". Now a 409 (the route's one
// refusal) or a message that STARTS with our own sentence is a refusal; everything else keeps its own text. EXTRACTED from the shipped
// module (a re-typed copy would pass while the real handler was broken).

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const marker = "function " + name + "(";
  const at0 = APP.indexOf(marker);
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
  const at = APP.slice(at0 - 6, at0) === "async " ? at0 - 6 : at0;
  let i = APP.indexOf("(", at0), depth = 0;
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

const REFUSED = "Refused: airplane mode is on. Turn the network on to fetch Wikidata items.";
// THE SENTENCE THE ROUTES RAISE, as the Python side defines it (`NETWORK_REFUSED` in src/ingest/fetch_verdict.py; R328). The pytest driver passes
// it in, so a rewording of the constant that leaves the reader's pattern behind turns this red. Only the cases that carry NO status reach the text
// (the route's own refusal is a 409, taken by status before the text is read), so those are the ones that go red; a direct `node` run falls back
// to this copy and says so.
const FROM_CONSTANT = typeof process.env.OO_NETWORK_REFUSED === "string" && process.env.OO_NETWORK_REFUSED.length > 0;
const SENTENCE = FROM_CONSTANT ? process.env.OO_NETWORK_REFUSED : "network refused: airplane mode is engaged";

async function press(err) {
  const st = { textContent: "" };
  const src = [extract("_wikidataRefusedByAirplaneMode"), extract("entitySpineFetch"), "return entitySpineFetch;"].join("\n");
  const f = new Function("$", "api", "ensureOnline", "pollJobStatus", "loadEntitySpine", "_jobStillRunning", "window", src);
  const run = f(() => st, async () => { throw err; }, async () => true, async () => ({}), () => {}, () => false, {});
  await run();
  return st.textContent;
}

function http(status, message) {
  const e = new Error(message);
  e.status = status;
  return e;
}

(async () => {
  // The refusals: the route's own 409, and a message that starts with our sentences (bare, or the socket guard's).
  assert.strictEqual(await press(http(409, SENTENCE)), REFUSED);
  assert.strictEqual(await press(http(409, "anything at all")), REFUSED, "a 409 from this route is the kill switch");
  assert.strictEqual(await press(new Error(SENTENCE)), REFUSED, "a message that STARTS with the constant's sentence is the kill switch");
  assert.strictEqual(await press(new Error(SENTENCE + " (kill switch)")), REFUSED, "a writer that builds on the sentence keeps it as its opening words");
  assert.strictEqual(await press(new Error("  Airplane mode is engaged: refusing a network connection to 'www.wikidata.org'")), REFUSED);

  // The controls: the same words INSIDE another failure stay that failure's text.
  for (const msg of [
    "502 Bad Gateway: the page said airplane mode is engaged: refusing a network connection",
    "Redirect to https://h.test/airplane mode is engaged",
    "the upstream answered: " + SENTENCE,
    "please turn airplane mode off",
  ]) {
    const got = await press(http(502, msg));
    assert.ok(got.startsWith("Wikidata fetch failed:") && got.endsWith(msg), "a quoted phrase is not a refusal: " + got);
  }
  assert.strictEqual(await press(http(500, "boom")), "Wikidata fetch failed: boom");
  console.log("wikidata_refusal_node_test.js: OK (sentence from " + (FROM_CONSTANT ? "the constant" : "this file's own copy") + ")");
})().catch((e) => { console.error(e); process.exit(1); });
