// The two DOM helpers touch only the ids the markup names, and the destructive names run only for a
// person's own gesture (audit A-004, A-011).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Run against the REAL oo-on.js with a minimal DOM. The refusals are the point: an injected
// `<img src=x data-on-error="...">` is a zero-click call of any allowed name, so what a name may do
// when it is reached that way is what bounds an HTML injection.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const listeners = {};
const looked = [];
const touched = [];
global.window = global;
global.document = {
  addEventListener() {},
  removeEventListener() {},
  // Every id resolves, to an element that records being clicked or written, so a refusal can only be
  // the helper's own.
  getElementById(id) {
    looked.push(id);
    return { id, set value(v) { touched.push(["value", id, v]); }, click() { touched.push(["click", id]); } };
  },
  documentElement: { addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); } },
  body: { classList: { toggle() {} } },
};
global.addEventListener = () => {};
const warned = [];
const realWarn = console.warn, realError = console.error;
console.warn = (m) => warned.push(String(m));
console.error = (m) => warned.push(String(m));

eval(fs.readFileSync(path.join(__dirname, "..", "src", "static", "oo-on.js"), "utf8"));

const ran = [];
for (const n of ["secureErase", "removeAuthor", "removeAnnotation", "removeUserCalendar", "removeDraftItem", "deleteSource"]) {
  global[n] = (...a) => ran.push(n + ":" + a.join(","));
}

function el(attrs) {
  return {
    nodeType: 1, attrs, parent: null,
    getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; },
    hasAttribute(n) { return n in this.attrs; },
  };
}
function fire(type, target, extra = {}) {
  const pathArr = [target, global.document, global.window];
  const ev = Object.assign({
    type, target, bubbles: !["error", "load", "toggle", "focus"].includes(type), cancelBubble: false,
    composedPath() { return pathArr; },
    stopPropagation() {}, preventDefault() {},
  }, extra);
  for (const f of (listeners[type] || [])) f(ev);
}

// 1. ooSetValue / ooClickId: the ids the markup names work, every other id is refused BEFORE the lookup.
for (const id of ["agenda-tag", "dumpread-title"]) {
  touched.length = 0;
  fire("click", el({ "data-on-click": `ooSetValue('${id}', 'v')` }), { isTrusted: true });
  assert.deepStrictEqual(touched, [["value", id, "v"]], id);
}
touched.length = 0;
fire("click", el({ "data-on-click": "ooClickId('anno-import')" }), { isTrusted: true });
assert.deepStrictEqual(touched, [["click", "anno-import"]]);

looked.length = 0; touched.length = 0;
for (const id of ["atrest-pw1", "atrest-pw2", "http-proxy", "fetch-mode", "ing-url", "constructor", "", "anno-import "]) {
  fire("click", el({ "data-on-click": `ooSetValue('${id}', 'pwned')` }), { isTrusted: true });
  fire("error", el({ "data-on-error": `ooSetValue('${id}', 'pwned')` }));
}
for (const id of ["atrest-consent", "discovery-external", "atrest-pw1", "agenda-tag", "anno-importX"]) {
  fire("error", el({ "data-on-error": `ooClickId('${id}')` }));
}
assert.deepStrictEqual(touched, [], "an id the markup does not name was written or clicked");
assert.deepStrictEqual(looked, [], "a refused id was looked up");
// ooSetValue's ids are not ooClickId's, and the other way round.
fire("error", el({ "data-on-error": "ooClickId('agenda-tag')" }));
fire("error", el({ "data-on-error": "ooSetValue('anno-import', 'x')" }));
assert.deepStrictEqual(touched, []);

// 2. The gesture-only names: a person's click (or Enter/Space on a focused control) runs them; an
//    error/load/toggle/focus/hover event, a synthetic click and any other key do not.
const NAMES = ["secureErase(8)", "removeAuthor('a')", "removeAnnotation(0)", "removeUserCalendar('k')", "removeDraftItem('d')"];
for (const call of NAMES) {
  const name = call.split("(")[0];
  ran.length = 0;
  fire("click", el({ "data-on-click": call }), { isTrusted: true });
  assert.strictEqual(ran.length, 1, name + " refused a real click");
  ran.length = 0;
  fire("keydown", el({ "data-on-keydown": call }), { isTrusted: true, key: "Enter" });
  fire("keydown", el({ "data-on-keydown": call }), { isTrusted: true, key: " " });
  assert.strictEqual(ran.length, 2, name + " refused Enter/Space");

  ran.length = 0;
  for (const type of ["error", "load", "toggle", "focus", "mouseover", "change", "input"]) {
    fire(type, el({ ["data-on-" + type]: call }), { isTrusted: true });
  }
  fire("click", el({ "data-on-click": call }), { isTrusted: false });   // el.click() from a script
  fire("click", el({ "data-on-click": call }));                          // no isTrusted at all
  fire("keydown", el({ "data-on-keydown": call }), { isTrusted: true, key: "a" });
  fire("keydown", el({ "data-on-keydown": call }), { isTrusted: false, key: "Enter" });
  assert.deepStrictEqual(ran, [], name + " ran for something that is not a person's gesture: " + ran);
}
// A name that is not gesture-only is unaffected (it confirms inside, or is not destructive).
ran.length = 0;
fire("error", el({ "data-on-error": "deleteSource(1)" }));
assert.strictEqual(ran.length, 1, "a name outside the gesture set kept working");

// 3. The set the dispatcher holds is the set this test names.
assert.deepStrictEqual(Array.from(window.ooOn.GESTURE_ONLY).sort(),
  ["removeAnnotation", "removeAuthor", "removeDraftItem", "removeUserCalendar", "secureErase"]);
assert.deepStrictEqual(Array.from(window.ooOn.SET_VALUE_IDS).sort(), ["agenda-tag", "dumpread-title"]);
assert.deepStrictEqual(Array.from(window.ooOn.CLICK_IDS).sort(), ["anno-import"]);

console.warn = realWarn; console.error = realError;
console.log("oo_on_gate_node_test.js: OK");
