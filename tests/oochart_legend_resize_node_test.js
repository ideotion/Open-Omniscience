// ooChart's legend and its host width, run as real code (the 2026-09-26 delegated
// click-through, row N defect N3 and row U defect U10).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// N3: hiding a series removed its legend chip, and the chip was the only control that
// could show the series again -- measured in Chromium as six chips becoming five after
// one click, with the band gone for good.
// U10: the canvas is sized in fixed px when it is drawn, and nothing refitted it when the
// host narrowed -- a window taken from 1440 to 375 px kept a 937 px canvas and the page
// scrolled sideways by 562 px.
//
// ooChart and its helpers are EXTRACTED from the shipped modules by name (a re-typed copy
// would pass while the real renderer was broken) and driven against a small fake DOM:
// just enough element, canvas and ResizeObserver for the component to run end to end.

"use strict";
const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extractFn(name) {
  // Balanced PARENS first, then the body brace: `opts = {}` in ooChart's signature would
  // otherwise truncate the slice to the signature alone (the recorded ooChart trap).
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = APP.indexOf("(", at), depth = 0;
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
function extractConst(name) {
  const at = APP.indexOf("const " + name + " =");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let depth = 0;
  for (let j = at; j < APP.length; j++) {
    const c = APP[j];
    if (c === "(" || c === "[" || c === "{") depth++;
    else if (c === ")" || c === "]" || c === "}") depth--;
    else if (c === ";" && depth === 0) return APP.slice(at, j + 1);
  }
  throw new Error("unterminated const " + name);
}

// ------------------------------------------------------------------ the fake DOM
class FakeEl {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = []; this.parentElement = null;
    this.style = {}; this.attrs = {}; this.dataset = {}; this.listeners = {};
    this.className = ""; this.textContent = ""; this.clientWidth = 0; this._html = "";
    this.classList = {toggle() {}, add() {}, remove() {}, contains() { return false; }};
  }
  set innerHTML(v) { this._html = String(v); this.children = []; this._chips = null; }
  get innerHTML() { return this._html; }
  appendChild(c) { c.parentElement = this; this.children.push(c); return c; }
  insertBefore(c, ref) {
    c.parentElement = this;
    const i = this.children.indexOf(ref);
    this.children.splice(i < 0 ? this.children.length : i, 0, c);
    return c;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  getBoundingClientRect() { return {left: 0, top: 0, width: this.clientWidth, height: 0}; }
  getContext() {
    // Every 2D call is a no-op; the component's own state is what is under test.
    return new Proxy({}, {
      get: (t, k) => (k in t ? t[k] : (k === "getLineDash" ? () => [] : () => ({width: 10}))),
      set: (t, k, v) => { t[k] = v; return true; },
    });
  }
  // ooChart only ever queries its legend for the chips it just rendered. The chips are
  // parsed out of the HTML it wrote and kept, so a click reaches the listener the
  // component attached rather than a copy.
  querySelectorAll(sel) {
    if (sel !== "[data-oo-leg]") return [];
    if (!this._chips) {
      this._chips = [...this._html.matchAll(/data-oo-leg="(\d+)" aria-pressed="(true|false)"/g)]
        .map((m) => {
          const c = new FakeEl("button");
          c.dataset.ooLeg = m[1];
          c.attrs["aria-pressed"] = m[2];
          return c;
        });
    }
    return this._chips;
  }
}
const observers = [];
class FakeRO {
  constructor(cb) { this.cb = cb; this.targets = []; this.live = true; observers.push(this); }
  observe(el) { this.targets.push(el); }
  disconnect() { this.live = false; }
  fire() { if (this.live) this.cb([]); }
}
const document = {
  createElement: (tag) => new FakeEl(tag),
  documentElement: new FakeEl("html"),
};

const NAMES_FN = ["_figStyle", "_figMarkerPath", "_figMarkerCanvas", "_figGlyph",
                  "_chartAria", "_chartSrTable", "_allInteger", "honestTicks", "_msLabel", "_seriesRuns",
                  "_stackSeries", "_stackPick", "_ooChartWatch", "ooChart"];
const NAMES_CONST = ["esc", "_SPARSE_BAR_MAX", "_FIG_STYLES", "_FIG_STROKE_MARKERS", "_missing",
                     "_GAP_FACTOR"];
const src = NAMES_CONST.map(extractConst).join("\n") + "\n"
  + NAMES_FN.map(extractFn).join("\n") + "\n"
  + "return {ooChart};";
// A synchronous setTimeout: the refit is debounced, and what is under test is WHAT it
// redraws, not how long it waits.
const { ooChart } = new Function(
  "document", "window", "ResizeObserver", "getComputedStyle", "setTimeout", "clearTimeout",
  src,
)(document, {devicePixelRatio: 1}, FakeRO,
  () => ({getPropertyValue: () => "#888"}), (fn) => fn(), () => {});

function host(width) {
  const parent = new FakeEl("div"); parent.clientWidth = width;
  const el = new FakeEl("div"); el.clientWidth = width;
  parent.appendChild(el);
  return el;
}
const canvasOf = (el) => el.children[0].children.find((c) => c.tagName === "CANVAS");
const legendOf = (el) => el.children[0].children.find((c) => /fig-leg/.test(c.innerHTML));
const readoutOf = (el) => el.children[0].children.find((c) => c.className === "hint");
const chips = (el) => legendOf(el).querySelectorAll("[data-oo-leg]");
const click = (chip) => (chip.listeners.click || []).forEach((fn) => fn());
const pts = (n, base) => Array.from({length: n}, (_, i) =>
  ({t: Date.UTC(2026, 0, 1 + i), v: base + i}));

// ---------------------------------------------------------------- N3: the legend
{
  const el = host(700);
  ooChart(el, [{label: "eng", points: pts(12, 5)}, {label: "fra", points: pts(12, 1)},
               {label: "deu", points: pts(12, 2)}], {height: 200});
  assert.strictEqual(chips(el).length, 3, "the fixture does not draw three chips");
  click(chips(el)[0]);
  // The hidden series KEEPS its chip, dimmed and announced as not pressed.
  const after = chips(el);
  assert.strictEqual(after.length, 3,
    "hiding a series removed its chip, so it can never be shown again");
  assert.strictEqual(after[0].getAttribute("aria-pressed"), "false",
    "the hidden series' chip does not say it is off");
  assert.ok(/data-oo-leg="0" aria-pressed="false" style="opacity:\.4"/.test(legendOf(el).innerHTML),
    "the hidden series' chip is not dimmed");
  // ...and a second click on that same chip brings it back.
  click(after[0]);
  assert.strictEqual(chips(el)[0].getAttribute("aria-pressed"), "true",
    "a second click did not restore the series");
}
// Hiding EVERY series still leaves every chip, and the readout names the state instead
// of sending the reader to "zoom out".
{
  const el = host(700);
  ooChart(el, [{label: "only", points: pts(4, 3)}], {height: 200});
  click(chips(el)[0]);
  assert.strictEqual(chips(el).length, 1, "hiding the last series removed the last chip");
  assert.ok(/hidden/i.test(readoutOf(el).textContent),
    "an all-hidden chart reads as an empty window: " + readoutOf(el).textContent);
  click(chips(el)[0]);
  assert.strictEqual(chips(el)[0].getAttribute("aria-pressed"), "true");
}

// ---------------------------------------------------------------- U10: the host width
{
  observers.length = 0;
  const el = host(937);
  ooChart(el, [{label: "Cu", points: pts(30, 9)}], {height: 200, maxWidth: 1200});
  assert.strictEqual(canvasOf(el).style.cssText.match(/width:(\d+)px/)[1], "937");
  const first = observers.find((o) => o.live && o.targets.includes(el));
  assert.ok(first, "nothing watches the host once the chart is drawn");
  // The window narrows to a phone: the chart refits to the new width.
  el.clientWidth = 343;
  first.fire();
  assert.strictEqual(canvasOf(el).style.cssText.match(/width:(\d+)px/)[1], "343",
    "the canvas kept its old width after the host narrowed");
  // ONE observer per host: the chart it replaced no longer watches anything.
  assert.strictEqual(first.live, false, "the replaced chart's observer is still connected");
  assert.strictEqual(observers.filter((o) => o.live && o.targets.includes(el)).length, 1,
    "more than one observer watches one host");
  // A sub-pixel wobble is not a resize, and a hidden host keeps its drawing.
  const cv = canvasOf(el);
  const second = observers.find((o) => o.live && o.targets.includes(el));
  el.clientWidth = 345; second.fire();
  assert.strictEqual(canvasOf(el), cv, "a 2 px wobble redrew the chart");
  el.clientWidth = 0; el.parentElement.clientWidth = 0; second.fire();
  assert.strictEqual(canvasOf(el), cv, "a hidden host threw its drawing away");
  // The full series survives the refit (invariant #16: never thinned to fit).
  assert.ok(/n=30/.test(legendOf(el).innerHTML), "the refit dropped points");
}
// A host that is not laid out yet is drawn as soon as it gains a width -- with the
// series it was LAST given, not the ones a first, hidden call happened to carry.
{
  observers.length = 0;
  const el = host(0);
  ooChart(el, [{label: "old", points: pts(3, 1)}], {});
  ooChart(el, [{label: "new", points: pts(3, 1)}], {});
  assert.strictEqual(observers.filter((o) => o.live).length, 1, "two pending observers on one host");
  el.clientWidth = 400; el.parentElement.clientWidth = 400;
  observers.find((o) => o.live).fire();
  assert.ok(legendOf(el) && /new/.test(legendOf(el).innerHTML),
    "the pending chart drew a stale series list");
}

// ------------------------------------------------- the journalist walk (2026-09-30): the hint
// Wheel, drag and double-click all worked and nothing on the screen said so. The idle
// readout line now does, and it comes back when the pointer leaves with nothing pinned.
{
  const HINT = "Scroll to zoom \u00b7 drag to pan \u00b7 double-click to reset";
  const leave = (el) => (canvasOf(el).listeners.pointerleave || []).forEach((fn) => fn({}));
  const el = host(700);
  ooChart(el, [{label: "eng", points: pts(12, 5)}], {height: 200});
  assert.strictEqual(readoutOf(el).textContent, HINT, "an idle chart does not say how to zoom");
  readoutOf(el).textContent = "eng: 7 \u00b7 2026-01-03";      // what a hover writes
  leave(el);
  assert.strictEqual(readoutOf(el).textContent, HINT, "leaving the chart left the last hover value on screen");
  // An empty state is NOT overwritten by the hint on leave, and clearing it restores the hint.
  click(chips(el)[0]);
  assert.ok(/hidden/i.test(readoutOf(el).textContent));
  leave(el);
  assert.ok(/hidden/i.test(readoutOf(el).textContent),
    "leaving replaced the 'every series is hidden' state with the hint: " + readoutOf(el).textContent);
  click(chips(el)[0]);
  assert.strictEqual(readoutOf(el).textContent, HINT, "showing the series again left the empty-state note behind");
}

console.log("oochart_legend_resize_node_test: all assertions passed");
