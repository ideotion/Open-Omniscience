// No DOM helper clicks or fills a control by id, and the destructive names run only for a
// person's own click (audit A-004, A-011; A-024 stage 2: the trust rule replaced the 31-name GESTURE_ONLY list).
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
// The 31 names that used to be on GESTURE_ONLY: still the interesting set (destructive or job-control, no confirm of
// their own, some now with one), now protected by the rule for EVERY name rather than by being listed.
const GESTURE = [
  "_uxPauseResume", "cancelP0Validation", "cancelPull", "disableUnmanagedLanguages", "dumpFtsCancel",
  "excludeKeyword", "familyResetGroup", "familySplit", "jobCancel", "kxHide", "kxRemoveTag", "lawSetWatched",
  "maintAction", "mbRun", "osmPickRemove", "pauseDump", "pauseOsm", "qualifyBulkCancel", "releaseRunCancel", "removeAnnotation",
  "removeAuthor", "removeDraftItem", "removeUserCalendar", "revertAllCollapse", "runAiCheck", "schedulerStop",
  "secureErase", "sgRemoveMember", "stopVllm", "toggleAiCoordinator", "unattendedStop",
];
for (const n of [...GESTURE, "deleteSource"]) {
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

// 1. No helper clicks or fills a control by id (A-004, R443). ooClickId / ooSetValue were removed; the three bindings that used
//    them are named handlers (annoImportPick, agendaSetTag, dumpReadSetTitle) that each touch one fixed field. An injected
//    binding that names the old helpers, or any id-taking call, is refused by the parser and reaches no element.
for (const bad of ["ooClickId('anno-import')", "ooSetValue('agenda-tag', 'v')", "ooSetValue('atrest-pw1', 'pwned')", "ooClickId('discovery-external')"]) {
  assert.throws(() => window.ooOn.parse(bad), /not in OO_ACTIONS/, bad);
  fire("click", el({ "data-on-click": bad }), { isTrusted: true });
  fire("error", el({ "data-on-error": bad }));
}
assert.deepStrictEqual(touched, [], "a removed helper still touched an element");
assert.deepStrictEqual(looked, [], "a removed helper still looked an element up");

// 2. The destructive names: a person's click runs them; an error/load/toggle/focus/hover event (no table row) and a
//    synthetic click or keydown (not isTrusted) do not.
const NAMES = GESTURE.map((n) => n + (n === "secureErase" ? "(8)" : n === "lawSetWatched" ? "('a', false)" : "('a')"));
for (const call of NAMES) {
  const name = call.split("(")[0];
  ran.length = 0;
  fire("click", el({ "data-on-click": call }), { isTrusted: true });
  assert.strictEqual(ran.length, 1, name + " refused a real click");
  // Enter or Space on a focused button arrives as a CLICK; no markup binds one of these names to a keydown (the per-event
  // table has no keydown entry for one, A-024 stage 1), so a keydown binding on it is refused like any other event.
  ran.length = 0;
  fire("keydown", el({ "data-on-keydown": call }), { isTrusted: true, key: "Enter" });
  fire("keydown", el({ "data-on-keydown": call }), { isTrusted: true, key: " " });
  assert.strictEqual(ran.length, 0, name + " ran for a keydown that no markup binds");

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
// 2b. The trust rule must hold on its own, not only because the table refuses first. Give every destructive name a row on
//     click, keydown and submit here (a test-only widening, undone below) and an event a script made is still refused, while
//     a person's click and key press run it. `submit` has no row in the markup at all, so this is the only thing that
//     exercises it. (Before stage 2 this section pinned GESTURE_ONLY, which also refused error/load/hover on a widened
//     table; the per-event table is what refuses those now, and the section above pins that.)
const TYPES = ["click", "keydown", "submit"];
const saved = {};
for (const t of TYPES) { saved[t] = window.ooOn.EVENT_ACTIONS[t]; window.ooOn.EVENT_ACTIONS[t] = new Set([...(saved[t] || []), ...GESTURE]); }
for (const call of NAMES) {
  const name = call.split("(")[0];
  for (const type of TYPES) {
    ran.length = 0;
    fire(type, el({ ["data-on-" + type]: call }), { isTrusted: true, key: "a" });
    assert.strictEqual(ran.length, 1, name + " (widened) refused a person's " + type);
    ran.length = 0;
    fire(type, el({ ["data-on-" + type]: call }), { isTrusted: false, key: "Enter" });   // a script's el.click() / dispatched event
    fire(type, el({ ["data-on-" + type]: call }), { key: "Enter" });                      // no isTrusted at all
    assert.deepStrictEqual(ran, [], name + " (widened) ran for a " + type + " a script made: " + ran);
  }
}
for (const t of TYPES) { if (saved[t]) window.ooOn.EVENT_ACTIONS[t] = saved[t]; else delete window.ooOn.EVENT_ACTIONS[t]; }
// ... and change/input/toggle are NOT in the rule (ruled R443: Playwright's selectOption and an extension's autofill fire them
// untrusted), so with a row they run for a script too.
for (const t of ["change", "input", "toggle"]) {
  assert(!window.ooOn.TRUSTED_EVENTS.has(t), t + " must stay out of the trust rule");
}

// A name outside that set still runs for the event the markup binds it to (it confirms inside, or is not
// destructive) ...
ran.length = 0;
fire("click", el({ "data-on-click": "deleteSource(1)" }), { isTrusted: true });
assert.strictEqual(ran.length, 1, "a name outside the gesture set kept working for its click");
// ... and, since A-024 stage 1, NOT for an injected error/load/toggle: this used to assert that it ran.
ran.length = 0;
for (const type of ["error", "load", "toggle", "focus", "mouseover"]) fire(type, el({ ["data-on-" + type]: "deleteSource(1)" }));
assert.strictEqual(ran.length, 0, "a name outside the gesture set ran for an event no markup binds it to");

// 3. The events the dispatcher holds to a person are the ones this test names.
assert.deepStrictEqual(Array.from(window.ooOn.TRUSTED_EVENTS).sort(), ["click", "keydown", "submit"]);
assert.strictEqual(window.ooOn.GESTURE_ONLY, undefined, "the 31-name list is gone: the rule covers every name");
assert.strictEqual(window.ooOn.SET_VALUE_IDS, undefined, "the id-fill helper's id set is gone with the helper");
assert.strictEqual(window.ooOn.CLICK_IDS, undefined, "the id-click helper's id set is gone with the helper");

console.warn = realWarn; console.error = realError;
console.log("oo_on_gate_node_test.js: OK");
