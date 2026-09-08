// P0 regression: inner-JS-string breakout in inline onclick="…openLinkPreview('…')"
// handlers. esc() (app-core.js) HTML-entity-escapes the OUTER attribute delimiter
// correctly (audit 0.0.9, finding G1) -- but a hand-written INNER single-quoted JS
// string literal around the escaped value is a second, independent delimiter that
// esc()'s output was never designed to protect: '&#39;' round-trips back to a
// literal "'" once the browser HTML-decodes the attribute, *after* esc() has already
// run, and by then nothing stops it from closing the inner JS string early. A URL
// such as http://evil.example/'-alert(document.cookie)-' passes safeUrl() unmodified
// (only the scheme is checked) and reaches this pattern via a stored article's own
// URL (src/briefing/producers.py builds Home-feed evidence directly from it) --
// fully attacker-controlled, and reachable simply by ingesting a hostile site
// through the app's normal collection pipeline.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// EXTRACTED from the real source (extLink(), and the evidence-link map inside
// cardHtml()) rather than re-typed, for the same reason lead_provenance_node_test.js
// gives: a hand-typed copy of the fix would pass this test even if the shipped code
// regressed to the vulnerable shape.
//
// WHY BEHAVIOURAL, NOT A SOURCE GREP: a grep for "JSON.stringify" proves the idiom is
// present, not that it closes the hole for every JS-string-meaningful character. The
// real fix is verified end to end: render the anchor with a hostile URL, HTML-decode
// its onclick attribute exactly as a browser would (entity references resolved AFTER
// esc() ran), then hand the decoded text to a real JS engine as the handler body and
// observe whether the payload executes or arrives inert as a single string argument.

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const vm = require("vm");

const APP = require("./app_source.js").appJs();

function fnSource(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found in app.js -- renamed?");
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

// The evidence-link inline form lives inside cardHtml(), which pulls in far more
// than this bug touches (OOI18N, dismiss/collapse buttons, weather corroboration…).
// Lift just the vulnerable statement by exact markers instead of the whole function,
// so the harness stays a direct test of the fixed statement, not of cardHtml's world.
function evidenceLinkBlockSource() {
  const startMarker = "const evid = (c.evidence || [])";
  const endMarker = '}).join("");';
  const at = APP.indexOf(startMarker);
  assert.ok(at !== -1, "the evidence-link map in cardHtml() was not found -- moved or renamed?");
  const endAt = APP.indexOf(endMarker, at);
  assert.ok(endAt !== -1, "could not find the end of the evidence-link map");
  return APP.slice(at, endAt + endMarker.length);
}

// esc()/safeUrl() are not the code under test here (the bug is in how their OUTPUT
// gets interpolated), so they are redeclared identically to production rather than
// extracted -- exactly as lead_provenance_node_test.js redeclares esc() in its own
// prelude. The vulnerable call sites (extLink(), the evidence-link block) ARE
// extracted from the real source, below.
const HELPERS = `
  const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));
  const safeUrl = (u) => {
    const cleaned = String(u == null ? "" : u).replace(/[\\x00-\\x20\\x7f]+/g, "");
    if (/^https?:\\/\\//i.test(cleaned)) return cleaned;
    if (/^[a-z][a-z0-9+.\\-]*:/i.test(cleaned)) return "";
    return cleaned;
  };
`;

// Simulates what a browser actually does with an HTML attribute value before handing
// it to the JS engine as an event-handler body: resolve character references. This
// happens AFTER esc() has already produced its output -- which is exactly the step
// the original bug's fix has to survive.
function htmlDecodeAttr(s) {
  return s.replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

// Renders `html`, pulls the onclick="…" attribute out of it, decodes it as a browser
// would, then actually EXECUTES the decoded text as the handler body (mirroring how
// the browser compiles an intrinsic event-handler attribute into a function) against
// stubs that record whether the payload ran as CODE or arrived as inert DATA.
function runOnclick(html, cookieValue) {
  const m = html.match(/onclick="([^"]*)"/);
  assert.ok(m, "rendered markup carries no onclick attribute:\n" + html);
  const decoded = htmlDecodeAttr(m[1]);

  let alertFired = false;
  let capturedArg = null;
  const sandbox = {
    document: { cookie: cookieValue },
    alert: () => { alertFired = true; },
    openLinkPreview: (u) => { capturedArg = u; },
  };
  vm.createContext(sandbox);
  let threw = null;
  try {
    const handler = vm.runInContext("(function(event){ " + decoded + " })", sandbox);
    handler({ preventDefault() {} });
  } catch (e) {
    threw = e;
  }
  return { decoded, alertFired, capturedArg, threw };
}

// A representative set of JS-string-meaningful characters, not just the apostrophe
// the audit's own reproduction used -- the fix must not be narrow enough to close
// only that one case (the prompt calls this out explicitly re: backslashes).
const PAYLOADS = [
  "http://evil.example/'-alert(document.cookie)-'",
  'http://evil.example/"-alert(document.cookie)-"',
  "http://evil.example/\\'-alert(document.cookie)-\\'",
  "http://evil.example/</script><script>alert(document.cookie)</script>",
];

// ---------------------------------------------------------------------------
// 1. extLink() -- the ONE shared renderer for every outbound "source ↗" link
//    (invariant #6e). This is the site the audit's own reproduction names.
// ---------------------------------------------------------------------------
for (const payload of PAYLOADS) {
  const ctx = {};
  new Function("ctx", HELPERS + fnSource("extLink") +
    "\nctx.html = extLink(" + JSON.stringify(payload) + ", 'evidence');")(ctx);

  const { alertFired, capturedArg, threw } = runOnclick(ctx.html, "SECRET_COOKIE");
  assert.strictEqual(alertFired, false,
    "extLink(): injected script executed for payload " + JSON.stringify(payload) +
    " -- inner-JS-string breakout regressed");
  assert.strictEqual(capturedArg, payload,
    "extLink(): openLinkPreview did not receive the URL intact for payload " +
    JSON.stringify(payload) + (threw ? " (handler threw: " + threw.message + ")" : ""));
}

// ---------------------------------------------------------------------------
// 2. The evidence-link inline form inside cardHtml() -- the companion site named
//    in the audit (a Home briefing card's own evidence list), fed straight from
//    a stored article's URL (src/briefing/producers.py) -- fully attacker-
//    controlled once a hostile site has been ingested.
// ---------------------------------------------------------------------------
for (const payload of PAYLOADS) {
  const ctx = {};
  new Function("ctx", HELPERS +
    // `evid` in the real source is already `(...).map(...).join("")` -- a single
    // HTML string of all evidence <span>s concatenated, not an array.
    "\nfunction buildEvidence(c) {\n" + evidenceLinkBlockSource() + "\n  return evid; }" +
    "\nctx.html = buildEvidence({ evidence: [{ url: " + JSON.stringify(payload) + ", title: 'x' }] });"
  )(ctx);

  assert.ok(ctx.html.includes("<a "), "expected the evidence link to render an anchor:\n" + ctx.html);
  const { alertFired, capturedArg, threw } = runOnclick(ctx.html, "SECRET_COOKIE");
  assert.strictEqual(alertFired, false,
    "evidence-link: injected script executed for payload " + JSON.stringify(payload) +
    " -- inner-JS-string breakout regressed");
  assert.strictEqual(capturedArg, payload,
    "evidence-link: openLinkPreview did not receive the URL intact for payload " +
    JSON.stringify(payload) + (threw ? " (handler threw: " + threw.message + ")" : ""));
}

console.log("onclick_xss_esc_node_test.js: OK (" + (PAYLOADS.length * 2) + " checks)");
