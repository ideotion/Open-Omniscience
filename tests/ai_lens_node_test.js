// The reader's AI-derived lens, rendered and driven as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// WHY BEHAVIOURAL AND NOT A SOURCE GREP. The first draft of these guards was exactly
// that, and the mutation matrix refuted both in one run -- which is the whole argument
// for this file:
//
//   * `assert "loadAiLens()" in body` survived neutering the CALL, because a
//     zero-argument function's own DECLARATION contains `loadAiLens()`. The guard could
//     not tell wired from defined -- the recorded non-unique-needle trap, verbatim.
//   * `assert '"POST"' in body` survived deleting the confirm request's method, because
//     reader.js has ANOTHER POST (summarize/translate) thirty lines away.
//
// So the real functions are extracted from the shipped file and run: what is asserted
// is the markup a reader ends up with and the request that actually leaves the page.

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "reader.js"), "utf8");

function functionSource(src, name) {
  const at = src.indexOf("function " + name + "(");
  assert.ok(at >= 0, "no function named " + name);
  // Balance the PARENTHESES first: a `{}` in a default parameter would otherwise
  // truncate the slice to the signature and every assertion over it would pass free.
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = src.indexOf("{", i);
  depth = 0;
  let j = open;
  for (; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) { j++; break; } }
  }
  const body = src.slice(at, j);
  assert.ok(body.length > ("function " + name + "()").length + 5, name + " sliced to nothing");
  return body;
}

let passed = 0;
function check(name, fn) {
  fn();
  console.log("  ok  " + name);
  passed++;
}

// One sandbox for every function under test: `app-*.js`-style modules share ONE global
// scope, and two `runInNewContext` blocks each defining the same global throw.
function sandbox(extra) {
  const host = { innerHTML: "" };
  const ctx = {
    document: {
      getElementById: (id) => (id === "r-ailens" ? host : null),
      createElement: () => ({ set textContent(v) { this._t = String(v == null ? "" : v); },
                              get innerHTML() {
                                return (this._t || "").replace(/&/g, "&amp;")
                                  .replace(/</g, "&lt;").replace(/>/g, "&gt;");
                              } }),
      addEventListener: () => {},
    },
    console,
    ...extra,
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(functionSource(SRC, "esc"), ctx);
  vm.runInContext(functionSource(SRC, "renderAiLens"), ctx);
  return { ctx, host };
}

check("a grounded term shows the snippet from the reader's own copy", () => {
  const { ctx, host } = sandbox({});
  ctx.renderAiLens({ keywords: [
    { id: 1, term: "Ministry of Health", kind: "keyword", confirmed: false,
      evidence: "The Ministry of Health said on Tuesday…" },
  ]});
  assert.ok(host.innerHTML.includes("Ministry of Health"), "the term");
  assert.ok(host.innerHTML.includes("said on Tuesday"), "and where it occurs");
  assert.ok(!host.innerHTML.includes("Not found in your stored copy"),
    "a grounded term must NOT carry the ungrounded notice");
});

check("an UNGROUNDED term says so — the absence is the finding", () => {
  const { ctx, host } = sandbox({});
  ctx.renderAiLens({ keywords: [
    // `evidence_absent` is the server saying it SEARCHED the stored copy and the term
    // is not in it. That is the informative case.
    { id: 2, term: "Atlantis", kind: "keyword", confirmed: false, evidence_absent: true },
  ]});
  assert.ok(host.innerHTML.includes("Not found in your stored copy of this article"),
    "a term the model produced that is not in the text was inferred, translated or " +
    "invented — an empty slot would read as 'nothing to show'");
  assert.ok(/class="r-aiev r-aigap"/.test(host.innerHTML),
    "and it is styled as the caveat it is, not as an evidence line");
});

check("a row with NEITHER key never claims a search that did not happen", () => {
  // THE DEFECT THIS GUARDS. Rows written before the evidence writer existed hold NULL,
  // and the lens used to render every one of them as "not found in your stored copy" —
  // stating a search nobody ran. The server now omits BOTH keys when the stored copy has
  // no text to search, and that is a different sentence, not a softer one.
  const { ctx, host } = sandbox({});
  ctx.renderAiLens({ keywords: [
    { id: 3, term: "Atlantis", kind: "keyword", confirmed: false },
  ]});
  assert.ok(!host.innerHTML.includes("Not found in your stored copy"),
    "with no search performed, the lens must NOT assert that the term is absent");
  assert.ok(host.innerHTML.includes("Your stored copy has no text to search"),
    "it says which of the three states this is, rather than leaving a blank");
  assert.ok(/class="r-aiev r-aigap"/.test(host.innerHTML),
    "still styled as the caveat it is");
});

check("the lens is LABELLED at the point of display and never merged into the index", () => {
  const { ctx, host } = sandbox({});
  ctx.renderAiLens({ keywords: [{ id: 3, term: "x", kind: "keyword", confirmed: false }] });
  assert.ok(host.innerHTML.includes("AI-derived — unreliable"), "the two-class convention");
  assert.ok(/never part of the trusted keyword index/.test(host.innerHTML),
    "and the caveat is VISIBLE BY DEFAULT, not behind a toggle");
});

check("a confirmed row reads confirmed and STAYS AI-derived", () => {
  const { ctx, host } = sandbox({});
  ctx.renderAiLens({ keywords: [
    { id: 4, term: "x", kind: "keyword", confirmed: true, evidence: "e" },
  ]});
  assert.ok(/data-on="1"/.test(host.innerHTML) && host.innerHTML.includes("Confirmed"));
  assert.ok(host.innerHTML.includes("AI-derived — unreliable"),
    "confirming curates the lens IN PLACE — it never promotes a row out of it");
});

check("model output is escaped, never injected", () => {
  const { ctx, host } = sandbox({});
  ctx.renderAiLens({ keywords: [
    { id: 5, term: "<img onerror=x>", kind: "k", confirmed: false, evidence: "<b>no</b>" },
  ]});
  assert.ok(!host.innerHTML.includes("<img"), "a model term is text, never markup");
  assert.ok(!host.innerHTML.includes("<b>no</b>"));
  assert.ok(host.innerHTML.includes("&lt;img"));
});

// --- the WIRING, which the source greps could not see ------------------------------ //

check("the Keywords pane loads the lens (the call, not the declaration)", () => {
  // The trap this replaces: `"loadAiLens()" in src` is satisfied by
  // `function loadAiLens() {`. Slicing renderKeywords is what distinguishes them.
  const body = functionSource(SRC, "renderKeywords");
  assert.ok(body.includes("loadAiLens()"),
    "the trusted-keyword pane must INVOKE the lens, not merely have one defined");
  assert.ok(body.includes('id="r-ailens"'), "and give it somewhere to render");
});

check("confirming POSTs the id and the wanted state, and reads the answer back", () => {
  const calls = [];
  const ctx = {
    console,
    fetch: (url, opts) => { calls.push([url, opts]); return Promise.resolve({ ok: true,
      json: () => Promise.resolve({ id: 7, confirmed: true, ok: true }) }); },
  };
  ctx.window = ctx;
  let handler = null;
  ctx.document = { addEventListener: (ev, fn) => { if (ev === "click") handler = fn; },
                   getElementById: () => null, createElement: () => ({ innerHTML: "" }) };
  vm.createContext(ctx);
  // The delegated listener registers at module scope, so the whole IIFE body between
  // the marker comments is not extractable by name — run the registration statement.
  const at = SRC.indexOf('document.addEventListener("click"');
  assert.ok(at >= 0, "the confirm control must be a DELEGATED listener, not inline onclick");
  const stmt = SRC.slice(at, SRC.indexOf("\n  });", at) + 6);
  vm.runInContext(stmt, ctx);
  assert.ok(handler, "a click listener must be registered");

  const btn = { _attrs: { "data-aikw": "7" }, disabled: false, textContent: "Confirm",
    getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; },
    setAttribute(k, v) { this._attrs[k] = v; },
    removeAttribute(k) { delete this._attrs[k]; },
    closest: () => btn };
  handler({ target: btn });
  assert.strictEqual(calls.length, 1, "exactly one request per click");
  const [url, opts] = calls[0];
  assert.strictEqual(url, "/api/ai/keywords/confirm", "the endpoint that had no consumer");
  assert.strictEqual(opts.method, "POST",
    "asserted on THIS request's options — reader.js has another POST, so a whole-file " +
    "grep for the word cannot tell them apart");
  assert.deepStrictEqual(JSON.parse(opts.body), { id: 7, confirmed: true });
});

console.log(passed + " passed");
