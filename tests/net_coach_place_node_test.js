// The airplane coachmark's placement, driven for real (delegated click-through
// 2026-09-26, rows N, O and T; re-walk 2026-09-27, row O-1).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Four defects, one element. As a position:fixed bubble the coach covered, in turn: the
// top bar's own buttons (in Arabic every time, over #tm-open, #rate-toggle, #wiki-toggle
// and #llm); the facet-subtab strip `.chrome` relocates under the top bar; and, once it
// was pushed below the whole chrome, the first lines of every tab page -- the heading and
// the visible-by-default caveat (#living-caveat), and once scrolled a form input. A fixed
// box has no free rectangle to go to, because the page fills the viewport. The coach is
// now a STRIP IN THE CHROME, IN FLOW (index.html, app.css): it covers nothing by
// construction, which test_net_coach_placement.py pins from the markup and the CSS. What
// is left for a function to get wrong is the ARROW: it must still point at the plane, in
// both reading directions and at both widths, and `_placeCoach` must never position the
// strip itself again. That is what this file drives.
//
// EXTRACTED, never re-typed, and run against a fake DOM whose rectangles are the ones the
// Chromium walk measured (1440x950 and 375x667, en and ar).

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

const R = (l, t, r, b) => ({ left: l, top: t, right: r, bottom: b, width: r - l, height: b - t });

// Measured in Chromium on the fixed build: the plane and the strip, per layout.
// clientLeft is the strip's left border: 3 px of accent in LTR (border-inline-start),
// 1 px in RTL.
const LAYOUTS = [
  { name: "1440 ltr", plane: R(1220, 14, 1254, 48), strip: R(268, 68, 1422, 122), clientLeft: 3 },
  { name: "1440 rtl", plane: R(186, 14, 220, 48), strip: R(18, 68, 1172, 122), clientLeft: 1 },
  { name: "375 ltr", plane: R(64, 60, 98, 94), strip: R(18, 114, 357, 229), clientLeft: 3 },
  { name: "375 rtl", plane: R(277, 60, 311, 94), strip: R(18, 114, 357, 229), clientLeft: 1 },
  // A plane at the very edge of the strip: the arrow is clamped inside it, never outside.
  { name: "edge ltr", plane: R(1400, 14, 1434, 48), strip: R(268, 68, 1422, 122), clientLeft: 3 },
  { name: "edge rtl", plane: R(0, 14, 30, 48), strip: R(18, 68, 1172, 122), clientLeft: 1 },
];

function place(L) {
  const arrow = { style: {}, getBoundingClientRect: () => R(0, 0, 11, 11) };
  const writes = [];
  const style = new Proxy({}, { set(o, k, v) { writes.push(k); o[k] = v; return true; } });
  const coach = {
    style, clientLeft: L.clientLeft, clientWidth: L.strip.width - 4,   // 3 + 1 px of border
    getBoundingClientRect: () => L.strip,
    classList: { contains: (c) => c === "show" },
    querySelector: (s) => (s === ".coach-arrow" ? arrow : null),
  };
  const plane = { getBoundingClientRect: () => L.plane };
  const nodes = { "net-coach": coach, "net-toggle": plane };
  const body = extract("_placeCoach") + "\n_placeCoach();";
  new Function("$", "window", body)((id) => nodes[id] || null, { innerWidth: 1440, innerHeight: 950 });
  const left = parseFloat(arrow.style.left);
  // The arrow's box starts at the strip's PADDING edge, inside the left border.
  const arrowCentreX = L.strip.left + L.clientLeft + left + 5.5;
  return { left, arrowCentreX, stripWrites: writes };
}

let n = 0;
for (const L of LAYOUTS) {
  const out = place(L);
  n++;
  // The strip is never positioned by script again: it is in flow.
  assert.deepStrictEqual(out.stripWrites, [],
    `${L.name}: _placeCoach wrote ${out.stripWrites.join(", ")} on the coach itself -- it is in flow now`);
  assert.ok(Number.isFinite(out.left), `${L.name}: the arrow was not placed`);
  const planeX = L.plane.left + L.plane.width / 2;
  const inside = planeX >= L.strip.left + 8 && planeX <= L.strip.right - 8;
  if (inside) {
    assert.ok(Math.abs(out.arrowCentreX - planeX) <= 0.5,
      `${L.name}: the arrow (x ${out.arrowCentreX}) does not point at the plane (x ${planeX})`);
  }
  // Always inside the strip, never hanging off its ends.
  assert.ok(out.left >= 8 && out.left + 11 <= (L.strip.width - 4) - 8 + 0.01,
    `${L.name}: the arrow (left ${out.left}) leaves the strip`);
}

// The strip is never placed by `top`/`left` any more: the old fixed-bubble arithmetic is gone.
const fn = extract("_placeCoach");
for (const gone of ["el.style.top", "el.style.left", "guardBottom", "innerHeight - h"]) {
  assert.ok(!fn.includes(gone), `_placeCoach still carries "${gone}" -- the coach is in flow now`);
}

console.log("net_coach_place_node_test: " + n + " layouts ok");
