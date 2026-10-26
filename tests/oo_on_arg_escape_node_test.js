// A value written into a data-on-* argument must survive the browser's attribute decoding AND the
// oo-on.js parser as ONE string argument (audit F6, R203).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The browser decodes entities in an attribute BEFORE oo-on.js reads it, so `'${esc(x)}'` is not safe:
// esc() writes an apostrophe as &#39;, the decode turns it back into ', and the grammar's string closes.
// The shipped form is `${esc(JSON.stringify(x))}`. This replays both forms through the REAL oo-on.js
// parser (loaded into a vm with a stub document) with the payload that was reproduced in Chromium.

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const src = fs.readFileSync(path.join(__dirname, "..", "src", "static", "oo-on.js"), "utf8");
const sandbox = {
  console,
  document: { documentElement: { addEventListener() {} } },
  Proxy, Reflect, Object, Map, Set, Number, String, Math, JSON, SyntaxError, RegExp,
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const parse = sandbox.window.ooOn.parse;

const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c])));
// What the browser hands oo-on.js: the attribute value after entity decoding (the five esc() writes).
const decode = (s) => s.replace(/&quot;/g, "\"").replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");

const INJECTION = "x'); appShutdown(); ooSetValue('a','b";

// 1. The old form injects: three calls where one was written. This is the defect, kept as a control so
//    the test cannot pass because the parser stopped being able to see it.
{
  const attr = decode("ooSetValue('agenda-tag', '" + esc(INJECTION) + "');renderAgenda()");
  const calls = Array.from(parse(attr), (s) => s.name);
  assert.strictEqual(calls.join(","), "ooSetValue,appShutdown,ooSetValue,renderAgenda",
    "control: the single-quoted esc form no longer injects, so this test proves nothing: " + calls);
}

// 2. The shipped form is one call whose argument is exactly the value, for every hostile value.
const HOSTILE = [
  INJECTION, "plain", "it's", "say \"hi\"", "back\\slash", "a\\'b", "\\", "'", "\"", "');x('",
  "</script><img src=x onerror=1>", "line\nbreak", "tab\tx", " ", "&amp; &#39; &quot;", "名前", "", "0", "true", "null",
];
for (const v of HOSTILE) {
  const attr = decode("ooSetValue('agenda-tag', " + esc(JSON.stringify(v)) + ");renderAgenda()");
  const stmts = parse(attr);
  assert.strictEqual(Array.from(stmts, (s) => s.name).join(","), "ooSetValue,renderAgenda",
    "a value changed which calls run: " + JSON.stringify(v) + " -> " + stmts.map((s) => s.name));
  const arg = stmts[0].args[1];
  assert.strictEqual(arg.k, "lit");
  assert.strictEqual(arg.v, v, "the argument is not the value: " + JSON.stringify(v) + " -> " + JSON.stringify(arg.v));
}
console.log("oo_on_arg_escape_node_test: ok (" + HOSTILE.length + " values)");
