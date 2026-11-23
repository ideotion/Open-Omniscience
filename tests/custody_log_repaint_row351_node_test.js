// Row 351: the custody log table draws its headers, Action and Time cells in the active language, keeps
// the walker out, and a live language switch repaints it from the entries it holds (never a fetch).
"use strict";
const assert = require("assert");

const APP = require("./app_source.js").appJs();
const fn = (name) => {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at >= 0, name);
  let i = APP.indexOf("{", APP.indexOf(")", at)), depth = 0;
  for (; i < APP.length; i++) { if (APP[i] === "{") depth++; else if (APP[i] === "}" && --depth === 0) break; }
  return APP.slice(at, i + 1);
};
const words = /const _CUSTODY_ACTION_WORDS = \{[\s\S]*?\n\s*\};/.exec(APP);
assert.ok(words, "_CUSTODY_ACTION_WORDS");
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
let lang = "xx";
const host = { attrs: {}, innerHTML: "", setAttribute(k, v) { this.attrs[k] = v; } };
const window = { OOI18N: { t: (s) => lang + "[" + s + "]" } };
const $ = (id) => (id === "cust-entries" ? host : null);
const R = new Function("esc", "window", "$", "OOI18N",
  words[0] + "\n" + ["custodyEntryTimeHtml", "custodyActionHtml", "custodySigHtml", "custodyEntriesPaint", "custodyEntriesRepaint"]
    .map(fn).join("\n") + "\nreturn {custodyEntriesPaint, custodyEntriesRepaint};")(esc, window, $, window.OOI18N);

// nothing painted yet: a switch does nothing and never throws
R.custodyEntriesRepaint();
assert.strictEqual(host.innerHTML, "");

const entries = [
  { seq: 0, action: "ingest", actor: "<b>me</b>", timestamp: { asserted_time: "2026-11-23T10:00:00Z" }, signature: { algorithm: "ed25519" } },
  { seq: 1, action: "anchor", actor: "me", timestamp: { kind: "opentimestamps" }, signature: { algorithm: "ed25519" } },
  { seq: 2, action: "future_kind", actor: "me", timestamp: null, signature: null },
];
R.custodyEntriesPaint(host, entries);
let h = host.innerHTML;
assert.ok("data-i18n-dyn" in host.attrs, "the walker keeps out");
assert.strictEqual(host._ooCustEntries, entries);
for (const w of ["Action", "Actor", "Time", "Signature", "Item ingested", "Item anchored"]) assert.ok(h.includes("xx[" + w + "]"), w + "\n" + h);
assert.ok(h.includes("xx[OpenTimestamps proof:"), h);
assert.ok(h.includes('<code dir="ltr">future_kind</code>'), h);
assert.ok(h.includes("&lt;b&gt;me&lt;/b&gt;") && !h.includes("<b>me</b>"), "actor is data");

// a live language switch repaints from memory, every word in the new language
lang = "yy";
R.custodyEntriesRepaint();
h = host.innerHTML;
assert.ok(h.includes("yy[Action]") && h.includes("yy[Item ingested]") && h.includes("yy[OpenTimestamps proof:"), h);
assert.ok(!h.includes("xx["), h);

// a failed load clears the kept entries, so a switch cannot bring an old chain back
host._ooCustEntries = null; host.innerHTML = "";
R.custodyEntriesRepaint();
assert.strictEqual(host.innerHTML, "");
// a reply without its entries list throws in the paint (viewChain's catch then clears and toasts),
// never draws an empty chain
assert.throws(() => R.custodyEntriesPaint(host, undefined));
console.log("custody log repaint row 351: all checks passed");
