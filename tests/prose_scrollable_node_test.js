// A horizontally scrolling Help code block is reachable by keyboard — run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// `.prose pre` carries `overflow-x:auto`, so a wide code sample scrolls sideways with a
// mouse and, with no tabindex, not at all with a keyboard — the reader never sees the
// right-hand side of the line. axe-core's `scrollable-region-focusable` (WCAG 2.1.1),
// measured n=3 on the Help surface.
//
// The interesting half is what must NOT be marked: a tab stop on a block that does not
// scroll is a keystroke that does nothing, so a document of short samples would become a
// corridor of dead stops. That is a decision about real geometry, which a source grep
// cannot check — hence this runs the function.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = APP.indexOf("{", APP.indexOf(")", at));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j);
}

// A <pre> stub carrying the two geometry numbers the browser would report.
function pre(scrollWidth, clientWidth, attrs) {
  return {
    scrollWidth, clientWidth,
    _a: Object.assign({}, attrs || {}),
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._a, k) ? this._a[k] : null; },
    setAttribute(k, v) { this._a[k] = String(v); },
    removeAttribute(k) { delete this._a[k]; },
  };
}
function host(pres) {
  return { querySelectorAll: (sel) => (sel === "pre" ? pres : []) };
}

const src = "function document_stub(){}\n" + extract("markScrollableProse")
  + "\nreturn markScrollableProse;";
const markScrollableProse = new Function("document", src)({ getElementById: () => null });

// --- only genuinely overflowing blocks become focusable ------------------------ //
const wide = pre(800, 400), narrow = pre(300, 400), exact = pre(400, 400);
assert.strictEqual(markScrollableProse(host([wide, narrow, exact])), 1,
  "exactly one of the three overflows");
assert.strictEqual(wide.getAttribute("tabindex"), "0", "a scrolling block must take focus");
assert.strictEqual(narrow.getAttribute("tabindex"), null,
  "a block that fits must NOT become a dead tab stop");
assert.strictEqual(exact.getAttribute("tabindex"), null,
  "scrollWidth == clientWidth does not scroll, so it is not marked");

// --- the mark is removed when a block stops overflowing ------------------------ //
// The Help find-box re-renders the prose with narrower content; a tab stop left behind
// there is the same dead keystroke arriving by a different route.
const shrunk = pre(300, 400, {tabindex: "0"});
markScrollableProse(host([shrunk]));
assert.strictEqual(shrunk.getAttribute("tabindex"), null,
  "a previously-scrolling block that now fits must lose its tab stop");

// --- an author's own tabindex is not clobbered --------------------------------- //
const authored = pre(300, 400, {tabindex: "-1"});
markScrollableProse(host([authored]));
assert.strictEqual(authored.getAttribute("tabindex"), "-1",
  "only the tabindex this function sets is removed, never a different one");

// --- idempotent across re-renders ---------------------------------------------- //
const w2 = pre(800, 400);
assert.strictEqual(markScrollableProse(host([w2])), 1);
assert.strictEqual(markScrollableProse(host([w2])), 1, "running twice changes nothing");
assert.strictEqual(w2.getAttribute("tabindex"), "0");

// --- no role="region", deliberately -------------------------------------------- //
// role=region demands an accessible name; inventing "code sample 3" per block is noise
// for a screen reader, and tabindex alone satisfies the rule.
assert.ok(!/role/.test(extract("markScrollableProse")),
  "no role is set — that would trade this rule for the accessible-name one");

// --- degrades rather than throwing --------------------------------------------- //
assert.strictEqual(markScrollableProse(null), 0, "no host and no #doc-prose: no crash");
assert.strictEqual(markScrollableProse({}), 0, "a host without querySelectorAll: no crash");
assert.strictEqual(markScrollableProse(host([])), 0, "a document with no code blocks");

// --- missing geometry is treated as not-scrolling ------------------------------ //
const bare = { _a: {}, getAttribute() { return null; }, setAttribute() { assert.fail(
  "an element reporting no geometry must not be marked"); }, removeAttribute() {} };
assert.strictEqual(markScrollableProse(host([bare])), 0);

console.log("prose_scrollable_node_test: all assertions passed");
