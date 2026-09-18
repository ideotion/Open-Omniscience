/*
 * Open Omniscience — ooTimeline: the chronology's deterministic layout.
 * GPL-3.0-or-later.
 *
 * WHAT IT IS (2026-09-18, maintainer-asked): the pure half of the chronology
 * drawn in Settings → Advanced → Diagnostics — process sessions as bars, the
 * stretches a suspend split them into, the gaps between an end and the next boot,
 * the release run's phases, and the events the ledger recorded. Geometry only:
 * no DOM, no fetch, no clock of its own (the caller passes `now`), so a node test
 * can drive the shipped bytes.
 *
 * WHY IT IS NOT AN ooChart SERIES. ooChart (invariant #16) draws MEASURED CURVES —
 * a value over time, full resolution, bars under ten points. A chronology is a set
 * of INTERVALS and INSTANTS: a session is a span with a start and an end (or an
 * unknown end), a gap is the absence of a record, an event is a moment. There is
 * no y-value to interpolate and nothing to thin, which is the property invariant
 * #16 protects; what this module shares with ooChart is the interaction grammar
 * (wheel = cursor-anchored zoom, drag = pan, double-click = reset, hover = the
 * exact reading) and the refusal to draw what was not measured.
 *
 * THE HONESTY RULES, in the geometry:
 *   - a session whose end has no time is drawn OPEN (a dotted bar to the next
 *     boot, flagged `unknown`), never closed at a guessed moment;
 *   - a gap is drawn as a gap with its bounds, flagged `unknown` when its length
 *     is not known; no gap is ever given a cause;
 *   - a suspend is an interval INSIDE a session, drawn as the clocks recorded it;
 *   - the 72 h bar is a mark on ONE stretch (reached, or projected on the current
 *     one), never on a sum;
 *   - events closer than a few pixels are CLUSTERED with their count, never
 *     dropped.
 *
 * Dual node/browser like oosky.js: attaches root.ooTimeline AND module.exports.
 */
(function (root) {
  "use strict";

  var HOUR = 3600e3, DAY = 86400e3;

  function parse(iso) {
    if (iso == null) return null;
    if (typeof iso === "number") return isFinite(iso) ? iso : null;
    var t = Date.parse(String(iso));
    return isFinite(t) ? t : null;
  }

  // "3 d 04 h 12 m" — days / hours / minutes; under a minute, seconds. Deterministic
  // and locale-free (the units are SI-style symbols, the caller translates the
  // sentence around it).
  function fmtDur(seconds) {
    if (seconds == null || !isFinite(seconds)) return "—";
    var s = Math.max(0, Math.round(seconds));
    if (s < 60) return s + " s";
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    var out = [];
    if (d) out.push(d + " d");
    if (d || h) out.push((d && h < 10 ? "0" : "") + h + " h");
    out.push((out.length && m < 10 ? "0" : "") + m + " m");
    return out.join(" ");
  }

  var STEPS = [HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY];

  // Tick positions for a span: the smallest step that keeps ticks at least
  // `minPx` apart. Labels are ISO date or HH:MM in UTC — the caller may re-label.
  function ticks(t0, t1, width, minPx) {
    minPx = minPx || 70;
    var span = Math.max(1, t1 - t0);
    var step = STEPS[STEPS.length - 1];
    for (var i = 0; i < STEPS.length; i++) {
      if (width * STEPS[i] / span >= minPx) { step = STEPS[i]; break; }
    }
    var out = [];
    var first = Math.ceil(t0 / step) * step;
    for (var t = first; t <= t1; t += step) {
      var d = new Date(t);
      var dayTick = step >= DAY || d.getUTCHours() === 0 && d.getUTCMinutes() === 0;
      var label = dayTick
        ? d.toISOString().slice(0, 10)
        : (("0" + d.getUTCHours()).slice(-2) + ":" + ("0" + d.getUTCMinutes()).slice(-2));
      out.push({ t: t, x: (t - t0) / span * width, label: label, major: dayTick });
    }
    return { step: step, ticks: out };
  }

  // The full span of what there is to draw: the earliest session or run start to
  // `now`, with a small margin so the last bar has an edge to be read against.
  function fullSpan(chrono, now) {
    var starts = [];
    (chrono.sessions || []).forEach(function (s) { var t = parse(s.started_at); if (t != null) starts.push(t); });
    var rr = chrono.release_run;
    if (rr && parse(rr.started_at) != null) starts.push(parse(rr.started_at));
    var t0 = starts.length ? Math.min.apply(null, starts) : now - DAY;
    var t1 = now;
    if (t1 - t0 < HOUR) t0 = t1 - HOUR;
    var margin = (t1 - t0) * 0.02;
    return { t0: t0 - margin, t1: t1 + margin };
  }

  function clampSpan(span, full) {
    var w = Math.min(span.t1 - span.t0, full.t1 - full.t0);
    var t0 = Math.max(full.t0, Math.min(span.t0, full.t1 - w));
    return { t0: t0, t1: t0 + w };
  }

  function zoomAround(span, cursorT, factor, full) {
    var w = (span.t1 - span.t0) * factor;
    if (w < 10 * 60e3) w = 10 * 60e3;                    // ten minutes: the liveness tick's own grain
    var frac = (cursorT - span.t0) / Math.max(1, span.t1 - span.t0);
    return clampSpan({ t0: cursorT - frac * w, t1: cursorT + (1 - frac) * w }, full);
  }

  function pan(span, dt, full) {
    return clampSpan({ t0: span.t0 + dt, t1: span.t1 + dt }, full);
  }

  function layout(chrono, opts) {
    opts = opts || {};
    var width = Math.max(120, opts.width || 800);
    var padL = opts.padL == null ? 8 : opts.padL, padR = opts.padR == null ? 8 : opts.padR;
    var now = opts.now != null ? opts.now : Date.now();
    var full = fullSpan(chrono, now);
    var t0 = opts.t0 != null ? opts.t0 : full.t0, t1 = opts.t1 != null ? opts.t1 : full.t1;
    var span = Math.max(1, t1 - t0);
    var plotW = width - padL - padR;
    var X = function (t) { return padL + (t - t0) / span * plotW; };
    var clip = function (a, b) {
      var A = Math.max(a, t0), B = Math.min(b, t1);
      return B > A ? { x: X(A), w: Math.max(1, X(B) - X(A)) } : null;
    };
    var rowH = opts.rowH || 18, gapY = 6;
    var rows = {
      sessions: { y: 0, h: rowH, key: "sessions" },
      run: { y: rowH + gapY, h: rowH, key: "run" },
      events: { y: 2 * (rowH + gapY), h: rowH, key: "events" },
    };
    var sessions = [], gaps = [], suspends = [];
    var list = chrono.sessions || [];
    list.forEach(function (s, i) {
      var a = parse(s.started_at);
      if (a == null) return;
      var end = parse(s.ended_at);
      var unknown = !!s.end_unknown;
      var next = list[i + 1] ? parse(list[i + 1].started_at) : null;
      var b = end != null ? end : (s.current ? now : (next != null ? next : now));
      var box = clip(a, b);
      var bar = {
        session_id: s.session_id, started_at: s.started_at, ended_at: s.ended_at,
        current: !!s.current, clean: s.clean, unknown: unknown, uptime_s: s.uptime_s,
        end_basis: s.end_basis, x: box ? box.x : null, w: box ? box.w : 0, y: rows.sessions.y, h: rows.sessions.h,
        stretches: [],
      };
      (s.stretches || []).forEach(function (st) {
        var sa = parse(st.started_at);
        if (sa == null) return;
        var sb = st.ended_at ? parse(st.ended_at) : (st.seconds == null ? b : (st.current ? now : sa + (st.seconds || 0) * 1000));
        var c = clip(sa, sb);
        if (!c) return;
        bar.stretches.push({ x: c.x, w: c.w, seconds: st.seconds, ended_by: st.ended_by, current: !!st.current,
                             started_at: st.started_at, ended_at: st.ended_at, unknown: st.seconds == null });
      });
      // Suspends: the holes between consecutive stretches inside one session.
      for (var k = 1; k < bar.stretches.length; k++) {
        var p = bar.stretches[k - 1], q = bar.stretches[k];
        if (q.x > p.x + p.w) suspends.push({ x: p.x + p.w, w: q.x - (p.x + p.w), y: rows.sessions.y, h: rows.sessions.h,
                                             session_id: s.session_id, from: p.ended_at, to: q.started_at });
      }
      sessions.push(bar);
    });
    (chrono.gaps || []).forEach(function (g) {
      var b = parse(g.to);
      if (b == null) return;
      if (g.seconds == null || parse(g.from) == null) {
        var xb = X(b);
        if (xb >= padL && xb <= padL + plotW)
          gaps.push({ x: Math.max(padL, xb - 24), w: Math.min(24, xb - padL), unknown: true, to: g.to, basis: g.basis,
                      y: rows.sessions.y, h: rows.sessions.h });
        return;
      }
      var c = clip(parse(g.from), b);
      if (c) gaps.push({ x: c.x, w: c.w, unknown: false, seconds: g.seconds, from: g.from, to: g.to, basis: g.basis,
                         y: rows.sessions.y, h: rows.sessions.h });
    });
    var phases = [];
    var rr = chrono.release_run;
    if (rr) {
      (rr.phases || []).forEach(function (ph) {
        var a = parse(ph.started_at);
        if (a == null) return;
        var inflight = !ph.ended_at;
        var b = inflight ? (rr.outcome == null && rr.pid === (chrono.current_session || {}).pid ? now : (parse(rr.updated_at) || now)) : parse(ph.ended_at);
        var c = clip(a, Math.max(b, a + 1000));
        if (c) phases.push({ x: c.x, w: c.w, y: rows.run.y, h: rows.run.h, name: ph.name, status: ph.status,
                             inflight: inflight, started_at: ph.started_at, ended_at: ph.ended_at });
      });
    }
    // Events: instants, clustered when closer than 6 px so nothing is dropped.
    var pts = [];
    (chrono.events || []).forEach(function (e) {
      var t = parse(e.at);
      if (t == null || t < t0 || t > t1) return;
      pts.push({ t: t, x: X(t), kind: e.kind, label: e.label, at: e.at, detail: e.detail || {} });
    });
    pts.sort(function (a, b) { return a.t - b.t; });
    var events = [];
    pts.forEach(function (p) {
      var last = events[events.length - 1];
      if (last && p.x - last.x < 6) { last.count += 1; last.items.push(p); last.kinds[p.kind] = (last.kinds[p.kind] || 0) + 1; return; }
      var kinds = {}; kinds[p.kind] = 1;
      events.push({ x: p.x, y: rows.events.y, h: rows.events.h, count: 1, kind: p.kind, label: p.label, at: p.at, items: [p], kinds: kinds });
    });
    // The bar: reached on one stretch, or projected on the current one.
    var bar = null, sm = chrono.summary || {};
    var reachedAt = parse(sm.bar_reached_at);
    if (reachedAt != null) {
      bar = { t: reachedAt, x: X(reachedAt), reached: true, visible: reachedAt >= t0 && reachedAt <= t1, hours: sm.bar_hours };
    } else if (sm.current_stretch && parse(sm.current_stretch.started_at) != null && sm.bar_hours) {
      var due = parse(sm.current_stretch.started_at) + sm.bar_hours * HOUR;
      bar = { t: due, x: X(due), reached: false, projected: true, visible: due >= t0 && due <= t1, hours: sm.bar_hours,
              remaining_h: sm.hours_remaining_on_current_stretch };
    }
    var tk = ticks(t0, t1, plotW, opts.tickMinPx);
    tk.ticks.forEach(function (t) { t.x += padL; });
    return {
      t0: t0, t1: t1, now: now, width: width, plotW: plotW, padL: padL, padR: padR, X: X,
      height: rows.events.y + rows.events.h + 22,
      rows: rows, sessions: sessions, suspends: suspends, gaps: gaps, phases: phases, events: events, bar: bar,
      ticks: tk.ticks, tickStep: tk.step, nowX: X(now), nowVisible: now >= t0 && now <= t1,
      full: full,
    };
  }

  var API = { HOUR: HOUR, DAY: DAY, parse: parse, fmtDur: fmtDur, ticks: ticks, fullSpan: fullSpan,
              zoomAround: zoomAround, pan: pan, layout: layout };
  root.ooTimeline = API;
  if (typeof module !== "undefined" && module.exports) module.exports = API; // node test
})(typeof self !== "undefined" ? self : typeof globalThis !== "undefined" ? globalThis : this);
