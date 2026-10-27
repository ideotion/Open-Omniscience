// src/static/oo-on.js: a name runs ONLY for an event type whose EVENT_ACTIONS row lists it (audit A-023/A-024, stage 1).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Run as REAL code against a minimal DOM. The whole truth table is walked: every event type the dispatcher listens for x
// every name it can call. The expected answer is computed from the table the file itself declares, so the refusals are
// the point: 33 of 38 event types have no row, and a click-only name is refused on `change`.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const listeners = {};
global.window = global;
global.document = {
  addEventListener() {},
  removeEventListener() {},
  getElementById() { return null; },
  documentElement: { addEventListener(t, f) { (listeners[t] = listeners[t] || []).push(f); } },
  body: { classList: { toggle() {} } },
};
global.addEventListener = () => {};
const warned = [];
const realWarn = console.warn, realError = console.error;
console.warn = (m) => warned.push(String(m));
console.error = (m) => warned.push(String(m));

eval(fs.readFileSync(path.join(__dirname, "..", "src", "static", "oo-on.js"), "utf8"));

const { EVENTS, ACTIONS, EVENT_ACTIONS, GESTURE_ONLY } = window.ooOn;
const names = Object.keys(ACTIONS);                      // the 471 actions and the 9 helpers
const ran = [];
for (const n of names) { ACTIONS[n] = () => ran.push(n); }   // every name records itself, helpers included

function el(attrs) {
  return {
    nodeType: 1, attrs,
    getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; },
    hasAttribute(n) { return n in this.attrs; },
  };
}
const NON_BUBBLING = ["error", "load", "toggle", "focus", "blur", "mouseenter", "mouseleave", "close", "cancel", "scroll"];
function fire(type, target, extra = {}) {
  const pathArr = [target, global.document, global.window];
  const ev = Object.assign({
    type, target, bubbles: !NON_BUBBLING.includes(type), cancelBubble: false,
    composedPath() { return pathArr; },
    stopPropagation() {}, preventDefault() {},
  }, extra);
  for (const f of (listeners[type] || [])) f(ev);
}

assert.strictEqual(EVENTS.length, 38, "the dispatcher listens for 38 event types");
const rowTypes = Object.keys(EVENT_ACTIONS).sort();
assert.deepStrictEqual(rowTypes, ["change", "click", "input", "keydown", "toggle"], "the types that have a row: " + rowTypes);
assert(EVENTS.length - rowTypes.length === 33, "33 event types have no row");

let checked = 0;
for (const type of EVENTS) {
  const row = EVENT_ACTIONS[type];
  for (const name of names) {
    ran.length = 0;
    // a trusted event of this type; keydown gets Enter, so a gesture-only name is not refused for its key
    fire(type, el({ ["data-on-" + type]: name + "()" }), { isTrusted: true, key: "Enter" });
    const listed = !!row && row.has(name);
    const gestureOk = !GESTURE_ONLY.has(name) || type === "click" || type === "keydown";
    const want = listed && gestureOk ? [name] : [];
    assert.deepStrictEqual(ran, want, `${name} on ${type}: expected ${want.length ? "to run" : "refused"}, got ${JSON.stringify(ran)}`);
    checked++;
  }
}
assert(checked === EVENTS.length * names.length && checked > 15000, "the truth table was walked: " + checked);

// The case the audit named: an injected zero-click binding calls NOTHING, whatever the name.
for (const type of ["error", "load", "toggle", "focus", "mouseover", "mouseenter", "pointerdown", "touchstart", "drop"]) {
  for (const n of ["deleteSource", "addSource", "ingestUrl", "installOneModel", "bulletinPublish", "removeAuthor"]) {
    ran.length = 0;
    fire(type, el({ ["data-on-" + type]: n + "('x')" }), { isTrusted: true });
    assert.deepStrictEqual(ran, [], `${n} ran for an injected ${type}`);
  }
}
// A name bound to a click in the markup is refused for a change, an input and a keydown unless that row lists it.
for (const n of ["addSource", "ingestUrl", "deleteSource"]) {
  for (const type of ["change", "input", "keydown"]) {
    assert(!EVENT_ACTIONS[type].has(n), n + " is bound to " + type + " now: pick a name that is click-only for this check");
    ran.length = 0;
    fire(type, el({ ["data-on-" + type]: n + "()" }), { isTrusted: true, key: "Enter" });
    assert.deepStrictEqual(ran, [], `${n} (click-only) ran for ${type}`);
  }
}
// The refusal is named, never silent.
warned.length = 0;
fire("error", el({ "data-on-error": "addSource()" }), {});
assert(warned.some((w) => w.includes("addSource") && w.includes("error")), "the refusal says which name and which event: " + warned);
// A real click of a click-row name still runs; so does a nested call under the same event.
ran.length = 0;
fire("click", el({ "data-on-click": "showTab('home')" }), { isTrusted: true });
assert.deepStrictEqual(ran, ["showTab"]);

console.warn = realWarn; console.error = realError;
console.log("oo_on_event_table_node_test.js: OK (" + checked + " event x name pairs)");
