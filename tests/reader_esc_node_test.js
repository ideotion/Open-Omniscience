// reader.js esc() must escape quotes as well as & < > (audit F4, R200).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// esc() serialises through a DOM node's textContent -> innerHTML, which escapes & < > only, and the
// reader writes its result into double-quoted attributes. The DOM here is a two-method stand-in that
// does what a browser's does (escape those three), so what is tested is the step reader.js adds.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "reader.js"), "utf8");
const at = SRC.indexOf("function esc(");
assert.ok(at !== -1, "esc not found in reader.js -- was it renamed?");
let d = 0, j = SRC.indexOf("{", at);
for (; j < SRC.length; j++) {
  if (SRC[j] === "{") d++;
  else if (SRC[j] === "}") { d--; if (d === 0) { j++; break; } }
}
const fakeDocument = {
  createElement() {
    let text = "";
    return {
      set textContent(v) { text = v; },
      get innerHTML() { return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); },
    };
  },
};
const esc = new Function("document", SRC.slice(at, j) + "\nreturn esc;")(fakeDocument);

assert.strictEqual(esc('a"b'), "a&quot;b", "a double quote must not survive: it ends a double-quoted attribute");
assert.strictEqual(esc("a'b"), "a&#39;b", "a single quote must not survive: it ends a single-quoted attribute");
assert.strictEqual(esc("<img src=x>"), "&lt;img src=x&gt;");
assert.strictEqual(esc("a&b"), "a&amp;b", "the ampersand is escaped once, before the quotes are");
assert.strictEqual(esc(null), "");
assert.strictEqual(esc(7), "7");
const hostile = '" onmouseover="x';
assert.ok(!esc(hostile).includes('"'), "a hostile attribute value kept a raw quote: " + esc(hostile));
console.log("reader_esc_node_test: ok");
