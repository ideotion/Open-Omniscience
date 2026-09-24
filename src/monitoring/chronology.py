"""The chronology -- sessions, gaps, stretches and the numbers a returning operator
asked for, read off the session ledger and the release run's own state.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT IT ANSWERS (2026-09-18, the maintainer's question: *"what if I don't know when
the machine stopped? how will I know when it will have been 72 hours?"*):
- how long the app has been up in total since an ANCHOR (the release run's start, or
  the ledger's first boot), how much of that wall-clock time it was actually running;
- how many times it restarted, and how long since the last restart;
- the longest CONTINUOUS stretch, with its dates -- because the soak bar (gate row B)
  is continuous: a restart or a suspend starts a new stretch, and the sum of stretches
  is reported beside it, plainly labelled as NOT the bar;
- whether the 72 h bar has been reached on one stretch, and if the current stretch is
  the one that could reach it, how many hours it still needs.

WHAT IT REFUSES TO KNOW. A session whose end has no time (no sentinel, no liveness
tick -- a build before the ledger, or a lost file) contributes no seconds to any sum,
and the summary says how many such sessions it left out. A gap between an end and the
next boot is drawn with its bounds and no cause. A suspend is the clocks' inference,
labelled as such. ``measured`` never appears next to a number that was not.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from src.monitoring import session_history as sh

BAR_HOURS = 72.0
ANCHORS = ("run", "install")


def _epoch(iso: Any) -> float | None:
    if not iso or not isinstance(iso, str):
        return None
    try:
        s = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    except ValueError:
        return None


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
#  Sessions and their stretches
# --------------------------------------------------------------------------- #

#: A boot stamp that disagrees with the session's own clocks by more than this is
#: re-based. The same bound as the ledger's suspend and clock-step thresholds: under it,
#: rounding and NTP slewing; over it, a clock that was changed.
REBASE_TOLERANCE_S = 120.0


class _SessionClock:
    """One session's records, put on ONE time scale: the wall clock as it read at the
    session's latest record (RR-5).

    A wall stamp taken before a recorded ``clock-step`` is moved by every step recorded
    after it (record ORDER is causal order: the ledger is append-only), and a record that
    carries the session's monotonic uptime is placed from the start and that uptime, plus
    the suspends before it, rather than from its stamp at all. The start itself is the boot
    stamp, unless the session's own span (the boot-time clock, or the monotonic uptime plus
    the inferred suspends) disagrees with it, in which case the start is RE-BASED onto the
    span and the session says so. That is the NUC's case: a boot stamp 12 hours fast, a
    backward correction nothing recorded, and an uptime that was right all along."""

    def __init__(self, steps: list[tuple[int, float]], suspends: list[dict[str, Any]]) -> None:
        self.steps = steps
        # (uptime at the detecting tick, gap) for the suspends a reader can place by uptime
        self.placed = sorted(
            (float(r["uptime_s"]), float(r.get("gap_s") or 0.0))
            for r in suspends if r.get("uptime_s") is not None and r.get("gap_s") is not None
        )
        self.start: float = 0.0

    def correct(self, epoch: float | None, index: int) -> float | None:
        if epoch is None:
            return None
        return epoch + sum(step for i, step in self.steps if i > index)

    def suspended_before(self, uptime: float) -> float:
        return sum(g for u, g in self.placed if u <= uptime)

    def at_uptime(self, uptime: float) -> float:
        return self.start + uptime + self.suspended_before(uptime)

    def place(self, rec: dict[str, Any], index: int) -> float | None:
        """Where a record sits: by its uptime when it has one, else its corrected stamp."""
        up = rec.get("uptime_s")
        if isinstance(up, (int, float)):
            return self.at_uptime(float(up))
        return self.correct(_epoch(rec.get("at")), index)


def _index(records: list[dict[str, Any]]) -> dict[str, dict[str, list[tuple[int, dict[str, Any]]]]]:
    """Every record of every session, by kind, with its position in the file."""
    by: dict[str, dict[str, list[tuple[int, dict[str, Any]]]]] = {}
    for i, r in enumerate(records):
        sid = str(r.get("session_id") or "")
        by.setdefault(sid, {}).setdefault(str(r.get("kind") or ""), []).append((i, r))
    return by


def _cut(start: float, stop: float | None, holes: list[tuple[float, float]], *, current: bool,
         end_label: str) -> list[dict[str, Any]]:
    """[start, stop] minus the holes (suspends), as stretches. ``stop`` None = unknown."""
    out: list[dict[str, Any]] = []
    cursor = start
    for a, b in sorted(holes):
        if a <= cursor or (stop is not None and a >= stop):
            cursor = max(cursor, b) if a <= cursor else cursor
            continue
        out.append({"started_at": _iso(cursor), "ended_at": _iso(a), "seconds": round(a - cursor), "ended_by": "suspend"})
        cursor = max(cursor, b)
    if stop is None:
        out.append({"started_at": _iso(cursor), "ended_at": None, "seconds": None,
                    "ended_by": "unknown (the end has no time)"})
    else:
        out.append({"started_at": _iso(cursor), "ended_at": None if current else _iso(stop),
                    "seconds": round(max(0.0, stop - cursor)), "ended_by": end_label, "current": current})
    return out


def _collection_intervals(clock: _SessionClock, events: list[tuple[int, dict[str, Any]]],
                          stop: float | None) -> list[tuple[float, float | None, str]]:
    """RR-10: when the scheduler's collection loop was actually running in this session,
    from the loop's OWN start and exit events. A loop still running at the session's end
    ends there (the process took it down); an end with no time leaves it unknown."""
    out: list[tuple[float, float | None, str]] = []
    on: float | None = None
    for i, ev in events:
        if ev.get("event") != "collection":
            continue
        p = clock.place(ev, i)
        if p is None:
            continue
        if ev.get("running") and on is None:
            on = p
        elif not ev.get("running") and on is not None:
            out.append((on, p, "collection stopped"))
            on = None
    if on is not None:
        out.append((on, stop, "session end"))
    return out


def _sessions(records: list[dict[str, Any]], current: dict[str, Any], now: float) -> list[dict[str, Any]]:  # noqa: C901
    by = _index(records)
    out: list[dict[str, Any]] = []
    cur_id = current.get("session_id")
    wall_now = time.time()
    for bi, r in enumerate(records):
        if r.get("kind") != "boot":
            continue
        sid = str(r.get("session_id") or "")
        mine = by.get(sid, {})
        boot_raw = _epoch(r.get("at"))
        if boot_raw is None:
            continue
        steps = [(i, float(x.get("step_s") or 0.0)) for i, x in mine.get("clock-step", [])]
        suspend_recs = [x for _, x in mine.get("suspend", [])]
        clock = _SessionClock(steps, suspend_recs)
        boot_at = clock.correct(boot_raw, bi)
        assert boot_at is not None
        ends = mine.get("end") or []
        end_pair = ends[-1] if ends else None  # the last word wins: the next boot may have closed it first
        end = end_pair[1] if end_pair else None
        is_current = bool(cur_id and sid == cur_id)
        span: float | None = None
        end_at: float | None = None
        if is_current and end is None:
            clean, basis, unknown = None, "running now", False
            sp = current.get("span_s")
            if isinstance(sp, (int, float)):
                # The span as of `now` on the current clock's scale.
                span = float(sp) + (now - wall_now)
        elif end is None:
            # A boot with no end and not us: the process died and no boot has closed
            # it yet (this one would have) -- or the ledger was compacted past it.
            clean, basis, unknown = None, "no end record", True
        else:
            assert end_pair is not None
            end_at = clock.correct(_epoch(end.get("at")), end_pair[0])
            clean = end.get("clean")
            basis = str(end.get("basis") or "")
            unknown = end_at is None
            if end.get("span_s") is not None:
                span = float(end["span_s"])
            elif end.get("uptime_s") is not None:
                span = float(end["uptime_s"]) + sum(float(x.get("gap_s") or 0.0) for x in suspend_recs)
        # The start: the boot stamp, or the span's answer when the two disagree.
        start, rebased = boot_at, None
        anchor_end = now if (is_current and end is None) else end_at
        if span is not None and anchor_end is not None:
            derived = anchor_end - span
            if abs(derived - boot_at) > REBASE_TOLERANCE_S:
                start = derived
                rebased = {
                    "boot_stamp": r.get("at"), "moved_s": round(derived - boot_at),
                    "basis": ("the boot stamp disagreed with this session's own clocks (its "
                              "span on the boot-time or monotonic clock) by more than "
                              f"{REBASE_TOLERANCE_S:.0f} s, so the start is placed from the span: "
                              "the wall clock was changed during the session and the change "
                              "left no clock-step record"),
                }
        clock.start = start
        stop = now if (is_current and end_at is None and end is None) else end_at
        # Suspends: placed by uptime when the record carries it, else by corrected stamps.
        holes: list[tuple[float, float]] = []
        unplaced = 0
        for i, x in mine.get("suspend", []):
            gap = float(x.get("gap_s") or 0.0)
            if x.get("uptime_s") is not None:
                a = clock.start + float(x["uptime_s"]) + clock.suspended_before(float(x["uptime_s"])) - gap
                b = a + gap
            else:
                a0, b0 = clock.correct(_epoch(x.get("from")), i), clock.correct(_epoch(x.get("to")), i)
                if a0 is None or b0 is None:
                    unplaced += 1
                    continue
                a, b = a0, b0
            if a < start or (stop is not None and b > stop + REBASE_TOLERANCE_S):
                unplaced += 1
                continue
            holes.append((a, b))
        end_label = ("running" if (is_current and end is None)
                     else ("clean shutdown" if clean else "unclean end"))
        stretches = _cut(start, None if unknown else stop, holes,
                         current=bool(is_current and end is None), end_label=end_label)
        # Collection (RR-10), cut at the same suspends.
        coll: list[dict[str, Any]] = []
        for ca, cb, why in _collection_intervals(clock, mine.get("event", []), None if unknown else stop):
            for st in _cut(ca, cb, [h for h in holes if h[0] >= ca and (cb is None or h[0] < cb)],
                           current=bool(is_current and end is None and why == "session end"),
                           end_label=("running" if (is_current and end is None and why == "session end") else why)):
                coll.append(st)
        features = r.get("ledger_features") or []
        uptime_s: float | None
        if is_current and end is None:
            uptime_s = round(now - start)
        elif end_at is not None:
            uptime_s = round(end_at - start)
        else:
            uptime_s = None
        out.append({
            "session_id": sid,
            "started_at": _iso(start),
            "ended_at": _iso(end_at) if end_at is not None else None,
            "clean": clean,
            "end_basis": basis,
            "end_unknown": unknown,
            "current": is_current,
            "pid": r.get("pid"),
            "app_version": r.get("app_version"),
            "source": r.get("source") or "ledger",
            "machine_boot_id": r.get("machine_boot_id"),
            "uptime_s": uptime_s,
            "running_s": (round(float(current["uptime_s"])) if (is_current and end is None and current.get("uptime_s") is not None)
                          else (round(float(end["uptime_s"])) if (end and end.get("uptime_s") is not None) else None)),
            "suspends": len(holes),
            "suspends_unplaced": unplaced,
            "clock_steps": [{"at": _iso(clock.correct(_epoch(x.get("at")), i)), "step_s": x.get("step_s"),
                             "clocks": x.get("clocks")} for i, x in mine.get("clock-step", [])],
            "rebased": rebased,
            "stretches": stretches,
            "collection_recorded": "collection" in features,
            "collection_stretches": coll,
            "_clock": clock,
        })
    return out


def _gaps(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for prev, nxt in zip(sessions, sessions[1:], strict=False):
        a, b = _epoch(prev.get("ended_at")), _epoch(nxt.get("started_at"))
        if b is None:
            continue
        ida, idb = prev.get("machine_boot_id"), nxt.get("machine_boot_id")
        machine = None
        if ida and idb:
            # The one thing about a gap the app CAN know: the kernel's boot id changed or
            # it did not. Nothing about why.
            machine = "rebooted" if ida != idb else "same boot"
        if a is None:
            g = {"from": None, "to": nxt["started_at"], "seconds": None,
                 "basis": "the previous session's end has no time, so the gap has no length"}
        else:
            g = {"from": prev["ended_at"], "to": nxt["started_at"], "seconds": round(max(0.0, b - a)),
                 "basis": "no record between an end and the next boot; the app cannot know what happened while it was not running"}
        g["machine"] = machine
        if machine == "rebooted":
            g["basis"] += " -- the machine itself restarted in this gap (its kernel boot id changed)"
        elif machine == "same boot":
            g["basis"] += " -- the machine did not restart: the same kernel boot id, so the app alone was restarted"
        gaps.append(g)
    return gaps


# --------------------------------------------------------------------------- #
#  Events (the ledger's, and the release run's)
# --------------------------------------------------------------------------- #


def _ledger_events(records: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:  # noqa: C901
    """Every record a reader wants on the timeline, each placed on its session's clock
    (RR-5): an event that carries its uptime is placed from it, a stamp from before a
    recorded clock step is moved by it. Records of a session the ledger no longer holds
    a boot for keep their raw stamps."""
    clocks = {s["session_id"]: s for s in sessions}
    ev: list[dict[str, Any]] = []
    for i, r in enumerate(records):
        kind = r.get("kind")
        sid = str(r.get("session_id") or "")
        sess = clocks.get(sid)
        clock = sess.get("_clock") if sess else None

        def _at(rec: dict[str, Any] = r, idx: int = i, c: Any = clock) -> str | None:
            if c is None:
                return rec.get("at")
            placed = c.place(rec, idx)
            return _iso(placed) if placed is not None else rec.get("at")

        if kind == "boot":
            ev.append({"at": sess["started_at"] if sess else r.get("at"), "kind": "boot", "label": "boot",
                       "session_id": r.get("session_id"), "_i": i,
                       "detail": {"pid": r.get("pid"), "app_version": r.get("app_version"),
                                  "previous_sentinel_state": r.get("previous_sentinel_state"),
                                  "source": r.get("source") or "ledger",
                                  "rebased": (sess or {}).get("rebased")}})
        elif kind == "end":
            clean = r.get("clean")
            k = "end-clean" if clean else ("end-unknown" if clean is None else "end-unclean")
            end_at = _at()
            ev.append({"at": end_at, "kind": k, "label": k.replace("-", " "), "session_id": r.get("session_id"), "_i": i,
                       "detail": {"basis": r.get("basis"), "reason": r.get("reason"), "uptime_s": r.get("uptime_s"),
                                  "source": r.get("source") or "ledger", "previous_peaks": r.get("previous_peaks")}})
        elif kind == "suspend":
            label = "suspend" if r.get("clocks") == "boot-time" else "suspend (clock jump)"
            if clock is not None and r.get("uptime_s") is not None:
                gap = float(r.get("gap_s") or 0.0)
                b = clock.at_uptime(float(r["uptime_s"]))
                frm, to = _iso(b - gap), _iso(b)
            else:
                frm = _iso(clock.correct(_epoch(r.get("from")), i)) if clock else r.get("from")
                to = _iso(clock.correct(_epoch(r.get("to")), i)) if clock else r.get("to")
            ev.append({"at": frm, "to": to, "kind": "suspend", "label": label, "_i": i,
                       "session_id": r.get("session_id"), "detail": {"gap_s": r.get("gap_s"), "basis": r.get("basis"),
                                                                     "clocks": r.get("clocks")}})
        elif kind == "clock-step":
            ev.append({"at": _at(), "kind": "clock-step",
                       "label": "clock set " + ("forward" if (r.get("step_s") or 0) > 0 else "back"),
                       "session_id": r.get("session_id"), "_i": i,
                       "detail": {"step_s": r.get("step_s"), "clocks": r.get("clocks"), "basis": r.get("basis")}})
        elif kind == "event":
            name = str(r.get("event") or "event")
            detail = {k: v for k, v in r.items() if k not in ("kind", "event", "session_id", "at", "schema")}
            label = name
            if name == "network":
                label = "online" if detail.get("online") else "offline"
            elif name == "collection":
                label = "collection started" if detail.get("running") else "collection stopped"
            ev.append({"at": _at(), "kind": f"event:{name}", "label": label, "session_id": r.get("session_id"),
                       "_i": i, "detail": detail})
    return ev


def _release_run_block(state: dict[str, Any]) -> dict[str, Any] | None:
    if not state or not state.get("run_id"):
        return None
    phases = []
    for ph in state.get("phases") or []:
        phases.append({"name": ph.get("name"), "started_at": ph.get("started_at"), "ended_at": ph.get("ended_at"),
                       "status": ph.get("status")})
    cur = state.get("phase")
    if cur and state.get("outcome") is None:
        # The phase in flight when the state was last written (or when the process died):
        # its own start when the state records one, else the end of the LAST finished
        # phase. (The loop this replaced walked the list backwards without stopping, so
        # it returned the FIRST phase's end -- on the NUC the soak read as having started
        # at the preflight.)
        last_start = state.get("phase_started_at")
        if not last_start:
            for ph in reversed(state.get("phases") or []):
                if ph.get("ended_at"):
                    last_start = ph.get("ended_at")
                    break
        phases.append({"name": cur, "started_at": last_start or state.get("updated_at"), "ended_at": None, "status": "in-flight"})
    beats = [{"at": h.get("at"), "rss_mb": h.get("rss_mb"), "elapsed_h": h.get("elapsed_h"),
              "memory_guard_engaged": (h.get("memory_guard") or {}).get("engaged")}
             for h in (state.get("heartbeats") or []) if isinstance(h, dict)]
    return {
        "run_id": state.get("run_id"),
        "profile": state.get("profile"),
        "started_at": state.get("started_at"),
        "outcome": state.get("outcome"),
        "phase": cur,
        "updated_at": state.get("updated_at"),
        "pid": state.get("pid"),
        "phases": phases,
        "soak": state.get("soak") or {},
        "soak_stretches": state.get("soak_stretches") or [],
        "sessions": state.get("sessions") or [],
        "heartbeats": beats,
        "heartbeats_dropped": state.get("heartbeats_dropped"),
        "clock_adjustments": state.get("clock_adjustments") or [],
    }


def _run_note(run_block: dict[str, Any] | None) -> str | None:
    """RR-10's second half: when the run the anchor names never measured a soak, say so
    beside the bar, so a bar read off collection AFTER a cancelled run is not taken for
    the run's own."""
    if not run_block:
        return None
    names = {p.get("name"): p for p in run_block.get("phases") or []}
    soak = names.get("soak")
    outcome = run_block.get("outcome")
    if outcome == "cancelled" and (soak is None or soak.get("status") not in ("measured", "in-flight")):
        return (f"the release run {run_block.get('run_id')} was cancelled before its soak ran, so no "
                "collection in this window is that run's soak")
    if soak is None:
        if outcome is None:
            return (f"the release run {run_block.get('run_id')} has not reached its soak "
                    f"(it is at {run_block.get('phase') or 'an earlier phase'})")
        return f"the release run {run_block.get('run_id')} never reached its soak"
    if soak.get("status") == "skipped":
        return f"the release run {run_block.get('run_id')} never armed its soak"
    return None


# --------------------------------------------------------------------------- #
#  The summary
# --------------------------------------------------------------------------- #


def _clip(stretches: list[dict[str, Any]], anchor: float, now: float) -> list[dict[str, Any]]:
    """Stretches restricted to [anchor, now]; an unknown-length stretch stays unknown."""
    out: list[dict[str, Any]] = []
    for s in stretches:
        a = _epoch(s.get("started_at"))
        if a is None:
            continue
        if s.get("seconds") is None:
            if a >= anchor:
                out.append(dict(s))
            continue
        b = _epoch(s.get("ended_at")) if s.get("ended_at") else now
        if b is None or b <= anchor:
            continue
        a2 = max(a, anchor)
        c = dict(s)
        c["started_at"] = _iso(a2)
        c["seconds"] = round(max(0.0, b - a2))
        out.append(c)
    return out


def _bar(known: list[dict[str, Any]], bar_s: float) -> tuple[str | None, dict[str, Any] | None, float | None]:
    """The FIRST stretch that reached the bar (its date), the current stretch, and the
    hours it still needs -- over one list of stretches, never their sum."""
    reached_at = None
    for s in known:  # chronological
        if s["seconds"] >= bar_s:
            a = _epoch(s["started_at"])
            reached_at = _iso(a + bar_s) if a is not None else None
            break
    cur = next((s for s in reversed(known) if s.get("current")), None)
    remaining = None if (reached_at is not None or cur is None) else round(max(0.0, bar_s - cur["seconds"]) / 3600.0, 2)
    return reached_at, cur, remaining


def _summary(sessions: list[dict[str, Any]], anchor_at: float, anchor: str, anchor_basis: str,  # noqa: C901
             now: float, bar_hours: float, run_note: str | None = None) -> dict[str, Any]:
    stretches = _clip([st for s in sessions for st in s["stretches"]], anchor_at, now)
    known = [s for s in stretches if s.get("seconds") is not None]
    unknown = [s for s in stretches if s.get("seconds") is None]
    boots_after = [s for s in sessions if (_epoch(s["started_at"]) or 0) > anchor_at]
    cur = next((s for s in sessions if s.get("current")), None)
    longest = max(known, key=lambda s: s["seconds"]) if known else None
    bar_s = bar_hours * 3600.0
    up_reached_at, cur_stretch, up_remaining = _bar(known, bar_s)
    # COLLECTION (RR-10). The bar is gate row B's: continuous COLLECTION. Only sessions
    # from a build that records the collection loop's start and exit can answer it; a
    # session that ran that build and recorded no start collected nothing, which IS an
    # answer, while an older session's silence is not.
    in_window = [s for s in sessions if (_epoch(s.get("ended_at")) or now) >= anchor_at]
    recorded = [s for s in in_window if s.get("collection_recorded")]
    unrecorded = [s for s in in_window if not s.get("collection_recorded")]
    coll_all = _clip([st for s in recorded for st in s.get("collection_stretches") or []], anchor_at, now)
    coll_known = [s for s in coll_all if s.get("seconds") is not None]
    c_reached_at, c_cur, c_remaining = _bar(coll_known, bar_s)
    c_longest = max(coll_known, key=lambda s: s["seconds"]) if coll_known else None
    collection = {
        "recorded": bool(recorded),
        "sessions_recorded": len(recorded),
        "sessions_unrecorded": len(unrecorded),
        "running_now": bool(c_cur),
        "stretches": len(coll_known),
        "unknown_length_stretches": len(coll_all) - len(coll_known),
        "total_s": round(float(sum(s["seconds"] for s in coll_known))),
        "longest_stretch": ({"seconds": c_longest["seconds"], "started_at": c_longest["started_at"],
                             "ended_at": c_longest.get("ended_at"), "ended_by": c_longest.get("ended_by"),
                             "current": bool(c_longest.get("current"))} if c_longest else None),
        "current_stretch": ({"seconds": c_cur["seconds"], "started_at": c_cur["started_at"]} if c_cur else None),
        "method": (
            "Collection stretches are the intervals between the scheduler's collection loop "
            "starting and exiting, each recorded by that loop as a ledger event, cut at every "
            "suspend and closed at the end of the session that ran them. A session from a "
            "build that did not record them contributes nothing and is counted as unrecorded."
        ),
    }
    if recorded:
        bar_reached: bool | None = c_reached_at is not None
        bar_basis = "collection"
    else:
        bar_reached, c_reached_at, c_cur, c_remaining = None, None, None, None
        bar_basis = "not recorded"
    wall = max(0.0, now - anchor_at)
    up = float(sum(s["seconds"] for s in known))
    out: dict[str, Any] = {
        "anchor": anchor,
        "anchor_at": _iso(anchor_at),
        "anchor_basis": anchor_basis,
        "now": _iso(now),
        "wall_clock_s": round(wall),
        "uptime_total_s": round(up),
        "downtime_s": round(max(0.0, wall - up)) if not unknown else None,
        "restarts": len(boots_after),
        "since_last_restart_s": (round(now - (_epoch(cur["started_at"]) or now)) if cur else None),
        "current_session_started_at": cur["started_at"] if cur else None,
        "sessions_in_window": len(in_window),
        "unclean_ends": len([s for s in sessions if s.get("clean") is False and (_epoch(s["started_at"]) or 0) >= anchor_at - 1]),
        "suspends": sum(int(s.get("suspends") or 0) for s in in_window),
        "clock_steps": sum(len(s.get("clock_steps") or []) for s in in_window),
        "rebased_sessions": len([s for s in in_window if s.get("rebased")]),
        "pre_ledger_sessions": len([s for s in in_window if s.get("source") == "forensics-sentinel"]),
        "unknown_end_sessions": len(unknown),
        "stretches": len(known),
        "longest_stretch": ({"seconds": longest["seconds"], "started_at": longest["started_at"],
                             "ended_at": longest.get("ended_at"), "current": bool(longest.get("current"))}
                            if longest else None),
        "current_stretch": ({"seconds": cur_stretch["seconds"], "started_at": cur_stretch["started_at"]}
                            if cur_stretch else None),
        "bar_hours": bar_hours,
        # THE BAR: continuous collection (gate row B, R20). None when no session in the
        # window recorded collection, because then the bar cannot be read at all.
        "bar_basis": bar_basis,
        "bar_reached": bar_reached,
        "bar_reached_at": c_reached_at,
        "bar_current_stretch": ({"seconds": c_cur["seconds"], "started_at": c_cur["started_at"]} if c_cur else None),
        "hours_remaining_on_current_stretch": c_remaining,
        # The process half of row B's clause ("the process stayed up for the window"),
        # on process stretches. Beside the bar, never the bar: a process that ran five
        # days with its collector stopped reaches this and not the bar (Lenn, RR-10).
        "process_bar": {"reached": up_reached_at is not None, "reached_at": up_reached_at,
                        "hours_remaining_on_current_stretch": up_remaining},
        "run_note": run_note,
        "collection": collection,
        "discontinuous_total_s": round(up),
        "method": (
            "Sessions from the session ledger (boot/end lines; a dead session's end from "
            "its last liveness tick); every duration is read from the session's own clocks "
            "(its monotonic uptime and span), never from two wall stamps a clock change may "
            "lie between; stretches are sessions split at suspends; sums are over stretches "
            "clipped to the anchor. The bar is CONTINUOUS COLLECTION (gate row B): one "
            "collection stretch of at least bar_hours; the process stretches and the "
            "discontinuous total are reported beside it and are not the bar."
        ),
        "caveats": [
            "the app cannot know what happened while it was not running: a gap has bounds and no cause",
            ("a suspend is read from the boot-time clock against the monotonic clock where the "
             "platform has one; elsewhere from the wall clock against the monotonic clock, which "
             "cannot tell a suspend from a forward clock change"),
        ],
    }
    if unknown:
        out["caveats"].append(
            f"{len(unknown)} session(s) have an end with no time and contribute nothing to the sums")
    if unrecorded and recorded:
        out["caveats"].append(
            f"{len(unrecorded)} session(s) in this window ran a build that did not record collection; "
            "they contribute nothing to the bar")
    if not recorded:
        out["caveats"].append(
            "no session in this window recorded when collection ran, so the continuous-collection "
            "bar cannot be read; the process stretches beside it are not the bar")
    if out["rebased_sessions"]:
        out["caveats"].append(
            f"{out['rebased_sessions']} session(s) had a boot stamp that disagreed with their own clocks "
            "and were placed from their span instead (a clock change during the session)")
    if out["pre_ledger_sessions"]:
        out["caveats"].append(
            "the session before the ledger existed is shown from forensics' sentinel: its start and "
            "how it ended, nothing in between")
    if run_note:
        out["caveats"].append(run_note)
    if wall > 0 and not unknown:
        # Stretches are rounded to the second and the wall clock is not, so a fresh
        # session can read 33 s of 32.6 s; a share above one is that rounding, never
        # more uptime than time, and it is capped rather than shown.
        out["uptime_share"] = min(1.0, round(up / wall, 4))
    return out


# --------------------------------------------------------------------------- #
#  The one entry point
# --------------------------------------------------------------------------- #


def _run_anchor(records: list[dict[str, Any]], sessions: list[dict[str, Any]],
                run_block: dict[str, Any]) -> float | None:
    """The release run's start on the chronology's one time scale: the ledger's own
    ``release-run start`` event, placed on its session's clock, when the ledger has it;
    the state file's wall stamp otherwise. (The state stamp was taken on whatever the
    clock read at the start -- 12 hours fast on the NUC.)"""
    by_id = {s["session_id"]: s for s in sessions}
    for i, r in enumerate(records):
        if (r.get("kind") == "event" and r.get("event") == "release-run" and r.get("action") == "start"
                and str(r.get("run_id")) == str(run_block.get("run_id"))):
            sess = by_id.get(str(r.get("session_id") or ""))
            if sess is not None:
                placed = sess["_clock"].place(r, i)
                if placed is not None:
                    return placed
            return _epoch(r.get("at"))
    return _epoch(run_block.get("started_at"))


def chronology(*, anchor: str = "run", now: float | None = None, bar_hours: float = BAR_HOURS) -> dict[str, Any]:
    """Everything the chronology panel draws. Read-only; a plain file read plus the
    release run's state file. ``anchor`` is ``run`` (the release run's start, falling
    back to the ledger's first boot when no run exists) or ``install`` (the ledger's
    first boot -- sessions before the ledger existed are unknown, and it says so)."""
    from src.monitoring.release_run import read_state

    if anchor not in ANCHORS:
        anchor = "run"
    now = time.time() if now is None else now
    records = sh.read_records()
    current = sh.current_session()
    sessions = _sessions(records, current, now)
    gaps = _gaps(sessions)
    run_block = _release_run_block(read_state())
    events = _ledger_events(records, sessions)
    first_boot = _epoch(sessions[0]["started_at"]) if sessions else None
    anchor_used, anchor_at, basis = anchor, None, ""
    run_start = _run_anchor(records, sessions, run_block) if run_block else None
    if anchor == "run" and run_block and run_start is not None:
        anchor_at = run_start
        basis = f"the release run {run_block['run_id']} started here"
    elif first_boot is not None:
        anchor_used = "install"
        anchor_at = first_boot
        basis = (("the first session the ledger knows of, seeded from forensics' sentinel (it ran before "
                  "the ledger existed); anything earlier is unknown")
                 if sessions[0].get("source") == "forensics-sentinel"
                 else "the ledger's first boot; sessions before the ledger existed are unknown")
        basis += " (no release run has started, so the run anchor fell back to it)" if anchor == "run" else ""
    note = _run_note(run_block) if anchor_used == "run" else None
    summary = (_summary(sessions, anchor_at, anchor_used, basis, now, bar_hours, run_note=note) if anchor_at is not None
               else {"anchor": anchor_used, "anchor_at": None, "anchor_basis": "no session has been recorded yet",
                     "now": _iso(now), "restarts": 0, "bar_hours": bar_hours, "bar_reached": None,
                     "bar_basis": "not recorded",
                     "method": "no ledger yet", "caveats": ["the ledger begins with this build's first boot"]})
    public = [{k: v for k, v in s.items() if not k.startswith("_")} for s in sessions]
    events.sort(key=lambda e: (e.get("at") or "", e.get("_i", 0)))
    for e in events:
        e.pop("_i", None)
    return {
        "schema": "oo-chronology-1",
        "generated_at": _iso(now),
        "current_session": current,
        "sessions": public,
        "gaps": gaps,
        "events": events,
        "release_run": run_block,
        "summary": summary,
        "ledger": {"path": str(sh.ledger_path()), "records": len(records), "liveness": sh.read_liveness()},
    }


_VITALS_CACHE: dict[str, Any] = {"at": 0.0, "value": None}


def for_vitals(max_age_s: float = 30.0) -> dict[str, Any]:
    """The three numbers the task manager's System tab shows, cached briefly because
    the vitals poll is frequent and the ledger is a file."""
    now = time.time()
    if _VITALS_CACHE["value"] is not None and now - _VITALS_CACHE["at"] < max_age_s:
        v = dict(_VITALS_CACHE["value"])
        cur = sh.current_session()
        v["uptime_s"] = cur.get("uptime_s")
        v["since_last_restart_s"] = cur.get("uptime_s")
        return v
    c = chronology(anchor="install", now=now)
    s = c.get("summary") or {}
    cur = c.get("current_session") or {}
    prev = None
    for sess in reversed(c.get("sessions") or []):
        if not sess.get("current"):
            prev = sess
            break
    value = {
        "uptime_s": cur.get("uptime_s"),
        "since_last_restart_s": cur.get("uptime_s"),
        "restarts_since_ledger_start": s.get("restarts"),
        "ledger_since": s.get("anchor_at"),
        "sessions_recorded": len(c.get("sessions") or []),
        "previous_session_end": ({"at": prev.get("ended_at"), "clean": prev.get("clean"), "basis": prev.get("end_basis")}
                                 if prev else None),
        "longest_stretch_s": ((s.get("longest_stretch") or {}).get("seconds")),
        "method": "the session ledger (data/session_history.jsonl); restarts are boots after the ledger's first boot",
    }
    _VITALS_CACHE["at"], _VITALS_CACHE["value"] = now, value
    return dict(value)
