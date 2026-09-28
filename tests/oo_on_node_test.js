// src/static/oo-on.js — the declarative binding that replaced inline handlers (Q1127 = a).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Run as REAL code against a minimal DOM. Two halves, and the refusals are the point:
//   * what an inline handler did, a binding still does -- the element as `this`, the
//     event, the bubbling walk and its stopPropagation, `return false`, the key filter,
//     a non-bubbling event staying on its target;
//   * what an inline handler could do and a binding must NOT -- call a name that is not
//     in the allowlist, call a method off an object, reach `constructor`, assign. If the
//     grammar grew into an evaluator, dropping 'unsafe-inline' would buy nothing.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const listeners = {};
const calls = [];
global.window = global;
global.document = {
  addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); },
  removeEventListener(t, f) { listeners[t] = (listeners[t] || []).filter((x) => x !== f); },
  getElementById() { return null; },
  documentElement: {addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); }},
  body: { classList: { toggle() {} } },
};
const winListeners = {};
global.addEventListener = (t, f) => { (winListeners[t] = winListeners[t] || []).push(f); };
const errors = [];
const realError = console.error, realWarn = console.warn;
console.error = (e) => errors.push(String(e && e.message || e));
console.warn = (e) => errors.push(String(e));

const src = fs.readFileSync(path.join(__dirname, "..", "src", "static", "oo-on.js"), "utf8");
// A test-only name is added to the allowlist the same way a real one is listed.
eval(src.replace('const OO_ACTIONS = [', 'const OO_ACTIONS = ["probe", "probe2", "probeThrow", "anParams", '));

global.probe = function (...args) { calls.push({fn: "probe", self: this, args}); };
global.probe2 = function (...args) { calls.push({fn: "probe2", self: this, args}); };
global.anParams = function () { return {q: "x"}; };
global.notListed = function () { calls.push({fn: "notListed"}); };

function el(attrs, parent) {
  return {
    nodeType: 1, attrs, parent, value: "v1", checked: true, dataset: {k: "dk"},
    getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; },
    hasAttribute(n) { return n in this.attrs; },
  };
}
function fire(type, target, extra = {}) {
  const pathArr = [];
  for (let n = target; n; n = n.parent) pathArr.push(n);
  pathArr.push(global.document, global.window);
  const ev = Object.assign({
    type, target, bubbles: true, cancelBubble: false, defaultPrevented: false,
    composedPath() { return pathArr; },
    stopPropagation() { this.cancelBubble = true; },
    preventDefault() { this.defaultPrevented = true; },
  }, extra);
  for (const f of (listeners[type] || [])) f(ev);
  for (const f of (winListeners[type] || [])) f(ev);
  return ev;
}

// 1. literals, `this`, `this.prop`, `event`, nested allowed call
calls.length = 0;
const b1 = el({"data-on-click": `probe('a', "b", 3, -1.5, true, null, [1, 'x'], {k: 'v', "q": 2}, this, this.value, this.dataset.k, event.type, anParams())`});
fire("click", b1);
assert.strictEqual(calls.length, 1);
const a = calls[0].args;
assert.deepStrictEqual(a.slice(0, 8), ["a", "b", 3, -1.5, true, null, [1, "x"], {k: "v", q: 2}]);
assert.strictEqual(a[8], b1, "`this` is the element carrying the binding");
assert.strictEqual(calls[0].self, b1, "the function runs with the element as this, as inline did");
assert.strictEqual(a[9], "v1");
assert.strictEqual(a[10], "dk");
assert.strictEqual(a[11], "click");
assert.deepStrictEqual(a[12], {q: "x"});

// 1b. event.currentTarget is the bound element, as it was for an inline handler
calls.length = 0;
const b1b = el({"data-on-click": "probe(event)"});
fire("click", b1b);
assert.strictEqual(calls[0].args[0].currentTarget, b1b);
assert.strictEqual(calls[0].args[0].type, "click");

// 2. sequence, helpers, return false
calls.length = 0;
const b2 = el({"data-on-click": "ooStop(event);probe(1);probe2(2);return false"});
const parent2 = el({"data-on-click": "probe('parent')"});
b2.parent = parent2;
let ev = fire("click", b2);
assert.deepStrictEqual(calls.map((c) => c.fn + ":" + c.args[0]), ["probe:1", "probe2:2"]);
assert.ok(ev.defaultPrevented, "return false cancels the default");
assert.ok(ev.cancelBubble, "ooStop stopped propagation");

// 3. bubbling reaches the ancestor's binding; the child's runs first
calls.length = 0;
const parent3 = el({"data-on-click": "probe('outer')"});
const child3 = el({"data-on-click": "probe('inner')"}, parent3);
ev = fire("click", child3);
assert.deepStrictEqual(calls.map((c) => c.args[0]), ["inner", "outer"]);
assert.ok(!ev.defaultPrevented, "a call's return value never cancels; only `return false` does");

// 4. a non-bubbling event runs only its target's binding
calls.length = 0;
const parent4 = el({"data-on-focus": "probe('outer')"});
const child4 = el({"data-on-focus": "probe('inner')"}, parent4);
fire("focus", child4, {bubbles: false});
assert.deepStrictEqual(calls.map((c) => c.args[0]), ["inner"]);

// 5. the key filter
calls.length = 0;
const i5 = el({"data-on-keydown": "probe('k')", "data-on-key": "Enter Space"});
fire("keydown", i5, {key: "a"});
fire("keydown", i5, {key: "Enter"});
fire("keydown", i5, {key: " "});
assert.strictEqual(calls.length, 2, "only Enter and Space run the binding");

// 6. THE REFUSALS: each is logged, and nothing runs.
const refused = [
  "notListed()",                         // not in the allowlist
  "window.probe()",                      // no member calls
  "document.body.remove()",
  "probe(this.constructor)",             // no prototype walk
  "probe(event.__proto__)",
  "x = 1",                               // no assignment
  "probe(1) || probe(2)",                // no operators
  "if (1) probe()",
  "eval('1')",
  "probe(`t`)",                          // no template literals
  "probe(alert)",                        // no bare identifiers as values
  "new probe()",
];
for (const s of refused) {
  calls.length = 0; errors.length = 0;
  fire("click", el({"data-on-click": s}));
  assert.strictEqual(calls.filter((c) => c.fn === "notListed" || c.fn === "probe").length, 0, `ran: ${s}`);
  assert.ok(errors.length >= 1, `refused silently: ${s}`);
}

// 7. a binding that throws does not stop the next one, like an inline handler's error
global.probeThrow = () => { throw new Error("boom"); };
calls.length = 0; errors.length = 0;
fire("click", el({"data-on-click": "probeThrow();probe('after')"}));
assert.strictEqual(calls.length, 1, "the statement after a throwing one still ran");
assert.ok(errors.some((e) => e.includes("boom")), "the error was logged, not swallowed");

// 8. ooOpenUrl refuses anything but a path on this app
let opened = [];
global.open = (u) => opened.push(u);
for (const u of ["https://example.org/", "//evil.example/x", "javascript:alert(1)", "data:x"]) {
  fire("click", el({"data-on-click": `ooOpenUrl('${u}')`}));
}
assert.deepStrictEqual(opened, []);
fire("click", el({"data-on-click": "ooOpenUrl('/api/catalog/export.csv')"}));
assert.deepStrictEqual(opened, ["/api/catalog/export.csv"]);

console.error = realError; console.warn = realWarn;
console.log("oo_on_node_test.js: OK");
