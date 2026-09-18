/**
 * Behavioural node test for ooTimeline, the chronology's deterministic layout
 * (src/static/ootimeline.js, 2026-09-18, maintainer-asked).
 *
 * REQUIRED directly (the dual node/browser shape of oosky.js), so the shipped bytes
 * are what is tested. Mostly negative space, as with ooSky: what must NOT be drawn
 * -- no closed end for a session whose end has no time, no length for a gap that
 * has none, no bar on a sum of stretches, no event dropped when two crowd one pixel.
 *
 * Run by tests/test_release_run.py (and standalone: `node tests/ootimeline_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const T = require("../src/static/ootimeline.js");

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

const H = T.HOUR;
const NOW = Date.parse("2023-11-16T14:13:20Z");
function iso(ms) { return new Date(ms).toISOString().replace(".000Z", "Z"); }
const B1 = Date.parse("2023-11-14T22:13:20Z");

function chrono(over) {
  return Object.assign({
    sessions: [
      { session_id: "s1", started_at: iso(B1), ended_at: iso(B1 + 30 * H), clean: false, end_unknown: false, uptime_s: 30 * 3600,
        stretches: [
          { started_at: iso(B1), ended_at: iso(B1 + 120e3), seconds: 120, ended_by: "suspend" },
          { started_at: iso(B1 + 6 * H + 120e3), ended_at: iso(B1 + 30 * H), seconds: 86280, ended_by: "unclean end" },
        ] },
      { session_id: "s2", started_at: iso(B1 + 32 * H), ended_at: null, current: true, uptime_s: 8 * 3600,
        stretches: [{ started_at: iso(B1 + 32 * H), ended_at: null, seconds: 8 * 3600, ended_by: "running", current: true }] },
    ],
    gaps: [{ from: iso(B1 + 30 * H), to: iso(B1 + 32 * H), seconds: 7200, basis: "no record" }],
    events: [
      { at: iso(B1), kind: "boot", label: "boot" },
      { at: iso(B1 + 1000), kind: "event:network", label: "online" },
      { at: iso(B1 + 32 * H), kind: "boot", label: "boot" },
    ],
    release_run: { started_at: iso(B1 + 2 * H), outcome: null, pid: 2, updated_at: iso(B1 + 30 * H),
      phases: [{ name: "preflight", started_at: iso(B1 + 2 * H), ended_at: iso(B1 + 2 * H + 60e3), status: "measured" },
               { name: "soak", started_at: iso(B1 + 2 * H + 60e3), ended_at: null, status: "in-flight" }] },
    summary: { bar_hours: 72, current_stretch: { started_at: iso(B1 + 32 * H), seconds: 8 * 3600 }, hours_remaining_on_current_stretch: 64 },
    current_session: { pid: 2 },
  }, over || {});
}

test("fmtDur is deterministic, locale-free, and never rounds a minute into an hour", () => {
  assert(T.fmtDur(0) === "0 s", "zero");
  assert(T.fmtDur(59) === "59 s", "under a minute stays in seconds: " + T.fmtDur(59));
  assert(T.fmtDur(3600 * 26 + 120) === "1 d 02 h 02 m", "d/h/m: " + T.fmtDur(3600 * 26 + 120));
  assert(T.fmtDur(86280) === "23 h 58 m", "no day when under one: " + T.fmtDur(86280));
  assert(T.fmtDur(null) === "—" && T.fmtDur(NaN) === "—", "an absent value is a dash, never 0");
});

test("the full span runs from the earliest start to now, and never under an hour", () => {
  const s = T.fullSpan(chrono(), NOW);
  assert(s.t0 < B1 && s.t1 > NOW, "margins on both sides");
  const tiny = T.fullSpan({ sessions: [{ started_at: iso(NOW - 1000) }] }, NOW);
  assert(tiny.t1 - tiny.t0 >= H, "a one-second history still gets an hour of axis");
});

test("every session, stretch, suspend, gap, phase and event is laid out; nothing is dropped", () => {
  const L = T.layout(chrono(), { width: 800, now: NOW });
  assert(L.sessions.length === 2, "two sessions");
  assert(L.sessions[0].stretches.length === 2 && L.sessions[1].stretches.length === 1, "stretches per session");
  assert(L.suspends.length === 1, "one suspend between the two stretches of session 1");
  assert(L.gaps.length === 1 && L.gaps[0].unknown === false && L.gaps[0].seconds === 7200, "the 2 h gap, with its length");
  assert(L.phases.length === 2 && L.phases[1].inflight === true, "the in-flight phase is drawn open");
  const total = L.events.reduce((n, e) => n + e.count, 0);
  assert(total === 3, "three events survive clustering: " + total);
  assert(L.events.length === 2 && L.events[0].count === 2, "boot + online one second apart cluster into one marker with count 2");
  assert(L.sessions[1].current === true && L.sessions[1].x + L.sessions[1].w <= L.nowX + 0.01, "the running session ends at now");
});

test("the bar is projected on the CURRENT stretch, never on the sum of stretches", () => {
  const L = T.layout(chrono(), { width: 800, now: NOW });
  assert(L.bar && L.bar.projected === true && L.bar.reached === false, "projected");
  assert(Math.abs(L.bar.t - (B1 + 32 * H + 72 * H)) < 1, "72 h after the current stretch's start");
  assert(L.bar.visible === false, "64 h away is outside the default span");
  // reached: the summary says when, and the mark sits there
  const c = chrono({ summary: { bar_hours: 72, bar_reached_at: iso(B1 + 5 * H) } });
  const L2 = T.layout(c, { width: 800, now: NOW });
  assert(L2.bar.reached === true && Math.abs(L2.bar.t - (B1 + 5 * H)) < 1 && L2.bar.visible === true, "reached mark");
  // no current stretch and not reached: no bar at all
  const L3 = T.layout(chrono({ summary: { bar_hours: 72 } }), { width: 800, now: NOW });
  assert(L3.bar === null, "no bar without a stretch to project on");
});

test("a session whose end has no time is drawn OPEN and its gap has no length", () => {
  const c = chrono();
  c.sessions[0].ended_at = null; c.sessions[0].end_unknown = true; c.sessions[0].uptime_s = null;
  c.sessions[0].stretches = [{ started_at: iso(B1), ended_at: null, seconds: null, ended_by: "unknown (the end has no time)" }];
  c.gaps = [{ from: null, to: iso(B1 + 32 * H), seconds: null, basis: "the previous session's end has no time" }];
  const L = T.layout(c, { width: 800, now: NOW });
  assert(L.sessions[0].unknown === true, "flagged unknown");
  assert(L.sessions[0].stretches[0].unknown === true && L.sessions[0].stretches[0].seconds == null, "the stretch has no length");
  assert(L.gaps.length === 1 && L.gaps[0].unknown === true && L.gaps[0].seconds == null, "the gap has no length");
  assert(L.gaps[0].w <= 24, "an unknown gap is a small marker before the boot, not a span");
});

test("zoom is anchored at the cursor and clamped to the full span; pan cannot leave it", () => {
  const full = { t0: 0, t1: 100 * H };
  const z = T.zoomAround({ t0: 0, t1: 100 * H }, 50 * H, 0.5, full);
  assert(z.t1 - z.t0 === 50 * H && Math.abs(z.t0 - 25 * H) < 1, "half the span, centred on the cursor");
  const out = T.zoomAround({ t0: 0, t1: 100 * H }, 50 * H, 3, full);
  assert(out.t0 === 0 && out.t1 === 100 * H, "zooming out stops at the full span");
  const p = T.pan({ t0: 10 * H, t1: 20 * H }, -50 * H, full);
  assert(p.t0 === 0 && p.t1 === 10 * H, "pan clamps at the left edge");
  const floor = T.zoomAround({ t0: 0, t1: 20 * 60e3 }, 10 * 60e3, 0.01, full);
  assert(floor.t1 - floor.t0 === 10 * 60e3, "the zoom floor is ten minutes (the liveness tick's grain)");
});

test("ticks keep a minimum pixel spacing and label days on day boundaries", () => {
  const k = T.ticks(0, 48 * H, 800, 70);
  assert(k.step >= 6 * H, "48 h over 800 px needs at least 6 h steps: " + k.step / H);
  for (let i = 1; i < k.ticks.length; i++) assert(k.ticks[i].x - k.ticks[i - 1].x >= 69.9, "spacing");
  const day = k.ticks.find((t) => t.major);
  assert(day && /^\d{4}-\d{2}-\d{2}$/.test(day.label), "a day tick is labelled as a date");
});

console.log(passed + " ootimeline checks passed");
