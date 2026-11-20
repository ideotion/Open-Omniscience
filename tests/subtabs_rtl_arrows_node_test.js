// ooSubtabs arrow keys follow the strip's writing direction (row 192; invariant #18).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Found on the Arabic dossier walk: ArrowLeft meant "previous" in every direction, so in a
// right-to-left strip it moved the selection visually RIGHT. Left and right are visual keys; up,
// down, Home and End keep DOM order. The component is EXTRACTED from the shipped app-markets.js,
// never re-typed, and driven over a minimal DOM in both directions, read both ways it can be: the
// computed style (a browser) and the nearest dir attribute (no style available).

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const MK = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-markets.js"), "utf-8");
const at = MK.indexOf("function ooSubtabs(");
assert.ok(at !== -1, "ooSubtabs not found -- was it renamed?");
const src = MK.slice(at);
let depth = 0, end = src.indexOf("{");
for (; end < src.length; end++) {
  if (src[end] === "{") depth++;
  else if (src[end] === "}") { depth--; if (depth === 0) { end++; break; } }
}
const body = src.slice(0, end);

let n = 0;
function check(cond, msg) { assert.ok(cond, msg); n++; }

global.document = {activeElement: null};
// style: "rtl" | "ltr" | null (no getComputedStyle); attr: the nearest [dir] value or null
function make(style, attr) {
  const getComputedStyle = style === null ? undefined : () => ({direction: style});
  const ooSubtabs = new Function("getComputedStyle", body + "; return ooSubtabs;")(getComputedStyle);
  const keys = ["a", "b", "c", "d"];
  const buttons = keys.map((k, i) => {
    const cls = new Set(i === 0 ? ["active"] : []);
    return {dataset: {tab: k}, attrs: {}, tabIndex: 0, type: "button",
      classList: {contains: (c) => cls.has(c), toggle: (c, on) => (on ? cls.add(c) : cls.delete(c))},
      setAttribute(a, v) { this.attrs[a] = v; }, getAttribute(a) { return this.attrs[a] || null; },
      focus() { global.document.activeElement = this; }, closest() { return this; }};
  });
  const host = attr === null ? null : {getAttribute: () => attr};
  const nav = {listeners: {}, scrollWidth: 0, clientWidth: 0, querySelectorAll: () => buttons,
    setAttribute() {}, addEventListener(type, fn) { this.listeners[type] = fn; }, contains: () => true,
    closest: (sel) => (sel === "[dir]" ? host : null)};
  const picked = [];
  ooSubtabs(nav, (k) => picked.push(k));
  return {
    press(fromKey, key) {
      global.document.activeElement = buttons.find((b) => b.dataset.tab === fromKey);
      let prevented = false;
      nav.listeners.keydown({key, preventDefault() { prevented = true; }});
      return {to: buttons.find((b) => b.attrs["aria-selected"] === "true").dataset.tab, prevented, picked};
    },
  };
}

for (const [label, style, attr] of [["computed style", "ltr", null], ["dir attribute", null, "ltr"],
                                    ["no direction at all", null, null]]) {
  const s = make(style, attr);
  check(s.press("b", "ArrowRight").to === "c", `left to right (${label}): ArrowRight goes to the next tab`);
  check(s.press("b", "ArrowLeft").to === "a", `left to right (${label}): ArrowLeft goes to the previous tab`);
}
for (const [label, style, attr] of [["computed style", "rtl", null], ["dir attribute", null, "rtl"],
                                    ["dir attribute, upper case", null, "RTL"]]) {
  const s = make(style, attr);
  check(s.press("b", "ArrowLeft").to === "c", `right to left (${label}): ArrowLeft goes to the next tab`);
  check(s.press("b", "ArrowRight").to === "a", `right to left (${label}): ArrowRight goes to the previous tab`);
  // wrapping follows the same mirror
  check(s.press("d", "ArrowLeft").to === "a", `right to left (${label}): ArrowLeft wraps from the last tab to the first`);
  check(s.press("a", "ArrowRight").to === "d", `right to left (${label}): ArrowRight wraps from the first tab to the last`);
}
// the computed style wins over a stale attribute: the style is what the reader sees
check(make("ltr", "rtl").press("b", "ArrowRight").to === "c", "the computed direction wins over a dir attribute");
// up, down, Home and End keep DOM order in both directions
for (const style of ["ltr", "rtl"]) {
  const s = make(style, null);
  check(s.press("b", "ArrowDown").to === "c", `${style}: ArrowDown is the next tab`);
  check(s.press("b", "ArrowUp").to === "a", `${style}: ArrowUp is the previous tab`);
  check(s.press("c", "Home").to === "a", `${style}: Home is the first tab`);
  check(s.press("b", "End").to === "d", `${style}: End is the last tab`);
  const r = s.press("b", "Enter");
  check(r.to === "d" && !r.prevented, `${style}: any other key is left alone and not swallowed`);
}
// a key press selects through the canonical switch, so the surface's own callback fires
const s = make("rtl", null);
const r = s.press("a", "ArrowLeft");
check(r.prevented && r.picked[r.picked.length - 1] === "b", "an arrow key selects and fires the surface's callback");

console.log(n + " checks, all checks passed");
