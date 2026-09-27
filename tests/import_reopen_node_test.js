// Reopening the Import dialog after a scan: the WHOLE scan goes (2026-09-27 re-walk, I-5).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// THE DEFECT. `openUnifiedImport` cleared the checklist, the status, the passphrase row and
// the Run button, but never the two other things a scan leaves behind: the trust row
// (`#ux-imp-trust-row`, which only a scan sets) and the folder in `#ux-imp-src`. A reopen
// showed a trust checkbox and its caveat under an empty checklist -- a statement about a
// scan the page no longer shows -- where S04-02 S2's acceptance for a reopen is "the line,
// nothing else".
//
// EXTRACTED from the shipped module, never re-typed, and RUN: the trust row is hidden by a
// call into `_uxImTrustRow`, so a grep for the id would pass whether or not the branch that
// hides it is the one reached.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  let at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  if (APP.slice(at - 6, at) === "async ") at -= 6;
  let i = APP.indexOf("(", APP.indexOf("function", at)), depth = 0;
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

// The dialog as a finished SCAN left it: a checklist, a status line, the passphrase row,
// Run enabled, the trust row up with its box ticked, and the scanned folder in the field.
function scannedDom() {
  const el = (extra) => Object.assign({ innerHTML: "", textContent: "", value: "", style: {} }, extra);
  const ids = {
    "ux-imp-checklist": el({ innerHTML: "<label>Restore corpus backup</label>" }),
    "ux-imp-status": el({ textContent: "What do you want to import?" }),
    "ux-imp-progress": el(), "ux-imp-summary": el(), "ux-imp-last": el(),
    "ux-imp-bar": el({ style: { display: "block" } }),
    "ux-imp-pass-row": el({ style: { display: "block" } }),
    "ux-imp-run": el({ disabled: false }),
    "ux-imp-trust-row": el({ style: { display: "block" } }),
    "ux-imp-trust": el({ checked: true }),
    "ux-imp-src": el({ value: "/tmp/claude-0/rewalk/I/backups" }),
    "ux-import": el({ opened: 0, showModal() { this.opened += 1; } }),
  };
  return { ids, getElementById: (id) => ids[id] || null };
}

function load(dom) {
  const src =
    "var document = __dom;\n" +
    "var _uxImSummaryArgs = 1, _uxImFound = {corpus: []}, _uxImSrc = '/x', _uxImRx = {}, _uxImRxAt = 5;\n" +
    "var api = async function () { return {}; };\n" +
    // collaborators that are not what is under test
    "function _uxImResetRunView() {} function _uxImLastLine() {}\n" +
    "function _uxImCheckpointNote() {} function _uxImReattach() {}\n" +
    extract("_uxImTrustRow") + "\n" +
    extract("_uxImTrust") + "\n" +
    extract("openUnifiedImport") + "\n" +
    "module.exports = { openUnifiedImport, _uxImTrust, state: () => ({ _uxImFound, _uxImSrc }) };";
  const m = { exports: {} };
  new Function("module", "exports", "__dom", src)(m, m.exports, dom);
  return m.exports;
}

let passed = 0;
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

test("I-5: a reopen hides the previous scan's trust row", () => {
  const dom = scannedDom();
  const mod = load(dom);
  mod.openUnifiedImport();
  assert.strictEqual(dom.ids["ux-imp-trust-row"].style.display, "none",
    "the trust statement stood under an empty checklist");
  // ...and a hidden row answers nothing for the operator on the next run
  assert.strictEqual(mod._uxImTrust(), null);
});

test("I-5: a reopen clears the folder the dialog no longer considers scanned", () => {
  const dom = scannedDom();
  const mod = load(dom);
  mod.openUnifiedImport();
  assert.strictEqual(dom.ids["ux-imp-src"].value, "", "the old folder stayed in the field");
  assert.strictEqual(mod.state()._uxImSrc, "");
  assert.strictEqual(mod.state()._uxImFound, null);
});

test("I-5: the rest of the fresh page is unchanged -- nothing left half-scanned", () => {
  const dom = scannedDom();
  load(dom).openUnifiedImport();
  assert.strictEqual(dom.ids["ux-imp-checklist"].innerHTML, "");
  assert.strictEqual(dom.ids["ux-imp-status"].textContent, "");
  assert.strictEqual(dom.ids["ux-imp-pass-row"].style.display, "none");
  assert.strictEqual(dom.ids["ux-imp-run"].disabled, true);
  assert.strictEqual(dom.ids["ux-import"].opened, 1, "the dialog still opens");
});

console.log("\n" + passed + " passed");
