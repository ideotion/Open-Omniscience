// The five fixes from the simulated-journalist walk (2026-09-30), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What is driven, each function EXTRACTED from the shipped modules by name (a re-typed copy
// would pass while the real one was broken):
//   1. the Observatory canvas is never sized from a HIDDEN container (it froze at 320 px);
//   2. the Timescale's snap is undone when the reader returns to Days;
//   3. the Explore trend's commodity overlay: a commodity with prices switches to Indexed and
//      SAYS so, one without prices changes nothing;
//   4. the Home card's signal value goes through the shared formatter;
//   5. the World map's selection outline, and the close button that clears it.
// (The chart zoom hint and the y-tick spacing live in oochart_legend_resize_node_test.js and
// axis_honesty_node_test.js, beside the harnesses that already drive ooChart and honestTicks.)

"use strict";
const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extractFn(name) {
  // Balanced PARENS first, then the body brace, so a default parameter cannot truncate the
  // slice to the signature alone (the recorded ooChart trap).
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
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  let depth = 0;
  for (let j = at; j < APP.length; j++) {
    const c = APP[j];
    if (c === "(" || c === "[" || c === "{") depth++;
    else if (c === ")" || c === "]" || c === "}") depth--;
    else if (c === ";" && depth === 0) return APP.slice(at, j + 1);
  }
  throw new Error("unterminated const " + name);
}

let passed = 0;
const pending = [];
const ok = (name, fn) => {
  const r = fn();
  if (r && typeof r.then === "function") {
    pending.push(r.then(() => { passed++; }, (e) => { console.error("FAIL - " + name); throw e; }));
  } else passed++;
};

// ---------------------------------------------------------------- 1. the Observatory canvas
{
  const build = (stageWidth) => {
    const calls = [];
    const stage = { clientWidth: stageWidth };
    const cv = { parentElement: stage };
    const ctx = {};
    const state = {
      layout: { any: true }, view: {}, rOuter: null, payload: null, raf: 0,
    };
    const W = {
      ooViz: { setupCanvas: (c, w, h) => { calls.push(["setup", w, h]); return ctx; } },
      ooSky: { drawSky: () => { calls.push(["draw"]); } },
    };
    const src = extractFn("_obsOuterFor") + "\n" + extractFn("_obsPaintNow") + "\nreturn _obsPaintNow;";
    const paint = new Function("$", "_obs", "window", "_obsTheme", src)(
      () => cv, state, W, () => ({}));
    return { paint, calls, stage, state };
  };
  ok("a HIDDEN stage paints nothing (it used to freeze a 320 px sky)", () => {
    const b = build(0);
    b.paint();
    assert.deepStrictEqual(b.calls, [], "a zero-width stage was measured and painted: " + JSON.stringify(b.calls));
  });
  ok("the same stage paints at its own width the moment it is laid out", () => {
    const b = build(0);
    b.paint();
    b.stage.clientWidth = 800;
    b.paint();
    assert.deepStrictEqual(b.calls[0], ["setup", 800, 496]);
    assert.deepStrictEqual(b.calls[1], ["draw"]);
  });
  ok("a phone-width stage is not floored past its own width", () => {
    const b = build(303);
    b.paint();
    assert.strictEqual(b.calls[0][1], 303, "a 303 px stage was painted at " + b.calls[0][1] + " and clipped");
  });
}

// ---------------------------------------------------------------- 2. the Timescale undo
{
  class El {
    constructor(sel) {
      this.sel = sel; this.listeners = {}; this.style = {}; this.attrs = {}; this.value = "";
      this.classList = { add() {}, remove() {}, contains() { return false; } };
      this.dataset = {};
    }
    addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
    setAttribute(k, v) { this.attrs[k] = v; }
    focus() {}
    getBoundingClientRect() { return { left: 0, width: 100 }; }
    fire(ev) { (this.listeners[ev] || []).forEach((fn) => fn({ target: this, preventDefault() {}, stopPropagation() {} })); }
  }
  const src = [
    extractConst("_TS_DAY"), extractConst("_TS_PRESETS"), extractConst("_TS_SCALE_LABEL"),
    extractConst("TS_SCALES"), extractConst("esc"),
    ...["_tsSnap", "_tsStep", "_tsParse", "_tsIso", "ooTimeScope"].map(extractFn),
    "return ooTimeScope;",
  ].join("\n");
  const I18N = { t: (s) => s };
  const ooTimeScope = new Function("window", "OOI18N", src)({ OOI18N: I18N, addEventListener() {} }, I18N);
  const make = () => {
    const els = {};
    const container = {
      classList: { add() {} },
      set innerHTML(v) { this._html = v; },
      querySelector(sel) { return els[sel] || (els[sel] = new El(sel)); },
    };
    const ctl = ooTimeScope(container, { min: "2026-01-01", max: "2026-12-31", from: "2026-03-10", to: "2026-09-16" });
    const scale = els[".ts-scale"];
    return { ctl, scale, els, pick(v) { scale.value = v; scale.fire("change"); } };
  };
  ok("Days again puts back the range a coarser scale snapped", () => {
    const m = make();
    assert.deepStrictEqual([m.ctl.get().from, m.ctl.get().to], ["2026-03-10", "2026-09-16"]);
    m.pick("month");
    assert.deepStrictEqual([m.ctl.get().from, m.ctl.get().to, m.ctl.get().scale], ["2026-03-01", "2026-09-30", "month"]);
    m.pick("day");
    assert.deepStrictEqual([m.ctl.get().from, m.ctl.get().to, m.ctl.get().scale], ["2026-03-10", "2026-09-16", "day"]);
  });
  ok("week then month then Days still returns to the original bounds", () => {
    const m = make();
    m.pick("week"); m.pick("month"); m.pick("day");
    assert.deepStrictEqual([m.ctl.get().from, m.ctl.get().to], ["2026-03-10", "2026-09-16"]);
  });
  ok("a bound the reader moves while snapped is theirs: Days keeps it", () => {
    const m = make();
    m.pick("month");
    m.els[".ts-from"].value = "2026-04-05";
    m.els[".ts-from"].fire("change");
    m.pick("day");
    // April 5 snapped to the 1st of April; the earlier memory (March 10) is gone.
    assert.strictEqual(m.ctl.get().from, "2026-04-01");
    assert.strictEqual(m.ctl.get().to, "2026-09-30");
  });
  ok("the label says what the control does (it snaps a range, it does not re-bin)", () => {
    assert.ok(/ts-scale-l[\s\S]*Snap range to/.test(APP.slice(APP.indexOf("function ooTimeScope("),
      APP.indexOf("function ooTimeScope(") + 4000)), "the select's label is not the honest one");
  });
}

// ---------------------------------------------------------------- 3. the commodity overlay
{
  const build = (prices) => {
    const calls = [];
    const _anTrend = { picked: {}, mode: "counts", autoIndexed: false };
    const api = async () => ({ prices });
    const drawAnTrend = () => calls.push("draw");
    const src = "async " + extractFn("anTrendPick") + "\nreturn anTrendPick;";
    const pick = new Function("_anTrend", "api", "drawAnTrend", src)(_anTrend, api, drawAnTrend);
    return { pick, _anTrend, calls };
  };
  const row = { currency: "USD", unit: "bbl", observed_on: "2026-09-01", price: 71.2 };
  ok("a commodity WITH prices switches to Indexed and remembers that it did so", async () => {
    const b = build([row]);
    await b.pick("WTI");
    assert.strictEqual(b._anTrend.mode, "indexed");
    assert.strictEqual(b._anTrend.autoIndexed, true);
    assert.ok(b._anTrend.picked.WTI, "the pick was not kept");
  });
  ok("a commodity with NO stored prices changes nothing: no Indexed flip, but the pick stays", async () => {
    const b = build([]);
    await b.pick("WTI");
    assert.strictEqual(b._anTrend.mode, "counts", "an empty overlay still flipped the axis");
    assert.strictEqual(b._anTrend.autoIndexed, false);
    assert.deepStrictEqual(b._anTrend.picked.WTI.prices, [], "the pick must be kept so its note can say why nothing is drawn");
  });
  ok("picking it again takes the overlay off", async () => {
    const b = build([row]);
    await b.pick("WTI"); await b.pick("WTI");
    assert.strictEqual(b._anTrend.picked.WTI, undefined);
  });
}

// ---------------------------------------------------------------- 4. the Home signal value
{
  const src = extractFn("fmtNum") + "\n" + extractFn("_sigValueText") + "\nreturn _sigValueText;";
  const f = new Function(src)();
  ok("a raw float tail never reaches the card (0.4090909090909091)", () => {
    assert.strictEqual(f(0.4090909090909091), "0.409");
  });
  ok("a small share is not rounded to a false zero", () => {
    assert.strictEqual(f(0.00042), "0.00042");
    assert.notStrictEqual(f(0.0004), "0");
  });
  ok("whole numbers, words and non-finite values pass through untouched", () => {
    assert.strictEqual(f(3), 3);
    assert.strictEqual(f("es"), "es");
    assert.ok(Number.isNaN(f(NaN)));
  });
  ok("a larger fraction reads with the shared precision", () => {
    assert.strictEqual(f(12.3456), "12.35");
    assert.ok(/^1\s234\.6$/.test(f(1234.5678)), "got " + JSON.stringify(f(1234.5678)));   // the shared grouping space
  });
}

// ---------------------------------------------------------------- 5. the map selection
{
  const mkEl = (iso, extra) => {
    const cls = new Set();
    return {
      _cls: cls, dataset: { iso },
      classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c) },
      getAttribute: (k) => (k === "data-iso" ? iso : null),
      hasAttribute: (k) => !!(extra && extra[k]),
    };
  };
  const els = [mkEl("zm"), mkEl("ye"), mkEl("ye", { "data-oomap-disputed": true }), mkEl("zm")];
  const document = {
    querySelectorAll: (sel) => {
      if (sel === "#oo-choro .oomap-sel") return els.filter((e) => e._cls.has("oomap-sel"));
      if (sel === "#oo-choro [data-iso]") return els;
      return [];
    },
  };
  const host = { innerHTML: "x" };
  const src = "let _ooMapSelIso = null, _ooMapDetailLast = { kind: 'country' };\n"
    + extractFn("_ooMapMarkSelected") + "\n" + extractFn("ooMapCloseDetail")
    + "\nreturn { mark: _ooMapMarkSelected, close: ooMapCloseDetail, sel: () => _ooMapSelIso, last: () => _ooMapDetailLast };";
  const M = new Function("document", "$", src)(document, () => host);
  ok("the clicked country is outlined, and only that one (a contested hatch is left alone)", () => {
    M.mark("ye");
    assert.deepStrictEqual(els.map((e) => e._cls.has("oomap-sel")), [false, true, false, false]);
    M.mark("zm");
    assert.deepStrictEqual(els.map((e) => e._cls.has("oomap-sel")), [true, false, false, true],
      "a region carrying the country's code is outlined with it, and the old one is cleared");
  });
  ok("closing the card clears the outline and forgets the card", () => {
    M.mark("zm");
    M.close();
    assert.strictEqual(els.some((e) => e._cls.has("oomap-sel")), false);
    assert.strictEqual(host.innerHTML, "");
    assert.strictEqual(M.last(), null);
    assert.strictEqual(M.sel(), null);
  });
}

Promise.all(pending).then(
  () => { console.log("journalist_fixes_node_test: " + passed + " checks passed"); },
  (e) => { console.error(e); process.exit(1); },
);
