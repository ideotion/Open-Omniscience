// The airplane coachmark's placement, driven for real (delegated click-through
// 2026-09-26, rows N, O and T).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Three defects, one function. In Arabic the plane sits at the LEFT of the top bar, so
// the old "to the right of the button" branch was taken every time and its clamp pulled
// the coach into the top bar over #tm-open, #rate-toggle, #wiki-toggle and #llm. In every
// language, "below the top-bar buttons" still landed on the facet-subtab strip that
// `.chrome` relocates under the top bar (Settings, Living sources). And nothing
// re-placed it on a language switch, which is a wiring fact pinned in
// test_net_coach_placement.py; this file is the geometry.
//
// EXTRACTED, never re-typed, and run against a fake DOM whose rectangles are the ones
// the Chromium walk measured (1440x950 and 375x800, en and ar). Mostly negative space:
// what the coach may never cover.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
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

const GUARD_DECL = (function () {
  const m = /const _COACH_GUARD = \[[^\]]+\];/.exec(APP);
  assert.ok(m, "the coach's protected-button list (_COACH_GUARD) is gone");
  return m[0];
})();

const R = (l, t, r, b) => ({ left: l, top: t, right: r, bottom: b, width: r - l, height: b - t });

function el(rect, extra) {
  return Object.assign({ getBoundingClientRect: () => rect, style: {} }, extra || {});
}

// One layout = the viewport, the chrome, the main column and every top-bar control.
function layout(width, height, dir, chromeBottom) {
  const rtl = dir === "rtl";
  // Measured positions (Chromium, 2026-09-26). LTR mirrors RTL around the main column.
  let ids;
  if (width >= 1000) {
    const col = rtl ? R(0, 0, 1200, height) : R(240, 0, 1440, height);
    // The LTR x positions; RTL is the mirror image inside the viewport.
    const ltr = {
      "tm-open": [1112, 14, 1146, 48], "rate-toggle": [1148, 14, 1182, 48],
      "wiki-toggle": [1184, 14, 1218, 48], "net-toggle": [1220, 14, 1254, 48],
      "lang-switch": [1256, 14, 1320, 48], "app-shutdown": [1396, 14, 1430, 48],
      "llm": [1030, 20, 1100, 42],
    };
    ids = {};
    for (const [k, [l, t, r, b]] of Object.entries(ltr)) {
      ids[k] = rtl ? R(width - r, t, width - l, b) : R(l, t, r, b);
    }
    return { width, height, rtl, col, chrome: R(col.left, 0, col.right, chromeBottom), ids };
  }
  // Phone: the top bar wraps into two rows and the sidebar is an off-canvas drawer.
  const col = R(0, 0, width, height);
  const ltr = {
    "tm-open": [276, 8, 310, 42], "rate-toggle": [318, 8, 352, 42],
    "wiki-toggle": [18, 60, 52, 94], "net-toggle": [64, 60, 98, 94],
    "lang-switch": [106, 60, 170, 94], "app-shutdown": [222, 60, 256, 94],
    "llm": [220, 18, 262, 38],
  };
  ids = {};
  for (const [k, [l, t, r, b]] of Object.entries(ltr)) {
    ids[k] = rtl ? R(width - r, t, width - l, b) : R(l, t, r, b);
  }
  return { width, height, rtl, col, chrome: R(0, 0, width, chromeBottom), ids };
}

function place(L, coachW, coachH) {
  const arrow = el(R(0, 0, 0, 0));
  const coach = el(R(0, 0, 0, 0), {
    offsetWidth: coachW, offsetHeight: coachH,
    classList: { contains: (c) => c === "show" },
    querySelector: (s) => (s === ".coach-arrow" ? arrow : null),
  });
  const chrome = el(L.chrome), col = el(L.col);
  const nodes = {};
  for (const [id, rect] of Object.entries(L.ids)) {
    nodes[id] = el(rect, {
      closest: (sel) => (sel === ".chrome" ? chrome : sel === ".main-col" ? col : null),
    });
  }
  nodes["net-coach"] = coach;
  const body = GUARD_DECL + "\n" + extract("_placeCoach") + "\n_placeCoach();";
  new Function("$", "getComputedStyle", "window", body)(
    (id) => nodes[id] || null,
    () => ({ direction: L.rtl ? "rtl" : "ltr" }),
    { innerWidth: L.width, innerHeight: L.height },
  );
  const left = parseFloat(coach.style.left), top = parseFloat(coach.style.top);
  return {
    rect: R(left, top, left + coachW, top + coachH),
    arrowCentreX: left + parseFloat(arrow.style.left) + 5.5,
    arrowTop: arrow.style.top,
  };
}

const overlaps = (a, b) => !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);

const CASES = [];
for (const [w, h] of [[1440, 950], [375, 800]]) {
  for (const dir of ["ltr", "rtl"]) {
    // Home (no subtab strip) and a tab whose strip wraps under the top bar.
    const bottoms = w >= 1000 ? [62, 113] : [108, 241];
    for (const cb of bottoms) CASES.push([w, h, dir, cb]);
  }
}

for (const [w, h, dir, cb] of CASES) {
  const L = layout(w, h, dir, cb);
  const name = `${w}x${h} ${dir} chrome-bottom ${cb}`;
  const out = place(L, 270, 173);
  const c = out.rect;
  // Never on the top bar, nor on the subtab strip under it.
  assert.ok(c.top >= L.chrome.bottom, `${name}: the coach (top ${c.top}) overlaps the chrome (bottom ${L.chrome.bottom})`);
  for (const [id, r] of Object.entries(L.ids)) {
    assert.ok(!overlaps(c, r), `${name}: the coach covers #${id} (${JSON.stringify(c)} vs ${JSON.stringify(r)})`);
  }
  // Never on the sidebar: inside the main column, on screen.
  assert.ok(c.left >= L.col.left && c.right <= L.col.right,
    `${name}: the coach leaves the main column (${c.left}..${c.right} vs ${L.col.left}..${L.col.right})`);
  assert.ok(c.left >= 0 && c.right <= w && c.bottom <= h, `${name}: off screen`);
  // Still pointing at the plane: the arrow sits on the top edge, over the plane's span.
  const p = L.ids["net-toggle"];
  assert.strictEqual(out.arrowTop, "-6px", `${name}: the arrow left the top edge`);
  assert.ok(out.arrowCentreX >= p.left && out.arrowCentreX <= p.right,
    `${name}: the arrow (x ${out.arrowCentreX}) no longer points at the plane (${p.left}..${p.right})`);
}

// Direction-aware: in RTL the coach hangs toward the page from the plane's LEFT edge, in
// LTR from its right edge -- mirror images, not the same pixel rule.
{
  const ltr = place(layout(1440, 950, "ltr", 62), 270, 173).rect;
  const rtl = place(layout(1440, 950, "rtl", 62), 270, 173).rect;
  assert.strictEqual(ltr.right, 1254, "LTR: the coach's right edge should meet the plane's");
  assert.strictEqual(rtl.left, 186, "RTL: the coach's left edge should meet the plane's");
}

console.log("net_coach_place_node_test: " + CASES.length + " layouts ok");
