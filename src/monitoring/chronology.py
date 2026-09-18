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


def _sessions(records: list[dict[str, Any]], current: dict[str, Any], now: float) -> list[dict[str, Any]]:
    ends: dict[str, dict[str, Any]] = {}
    suspends: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        sid = str(r.get("session_id") or "")
        if r.get("kind") == "end":
            ends[sid] = r  # the last word wins: the next boot may have closed it first
        elif r.get("kind") == "suspend":
            suspends.setdefault(sid, []).append(r)
    out: list[dict[str, Any]] = []
    cur_id = current.get("session_id")
    for r in records:
        if r.get("kind") != "boot":
            continue
        sid = str(r.get("session_id") or "")
        start = _epoch(r.get("at"))
        if start is None:
            continue
        end = ends.get(sid)
        is_current = bool(cur_id and sid == cur_id)
        if is_current and end is None:
            end_at, clean, basis, unknown = None, None, "running now", False
        elif end is None:
            # A boot with no end and not us: the process died and no boot has closed
            # it yet (this one would have) -- or the ledger was compacted past it.
            end_at, clean, basis, unknown = None, None, "no end record", True
        else:
            end_at = _epoch(end.get("at"))
            clean = end.get("clean")
            basis = str(end.get("basis") or "")
            unknown = end_at is None
        # Stretches: the session split at every suspend the ticks recorded.
        cut = sorted(
            ((_epoch(s.get("from")), _epoch(s.get("to"))) for s in suspends.get(sid, [])),
            key=lambda ab: ab[0] or 0.0,
        )
        stretches: list[dict[str, Any]] = []
        cursor = start
        for a, b in cut:
            if a is None or b is None or a <= cursor:
                continue
            stretches.append({"started_at": _iso(cursor), "ended_at": _iso(a), "seconds": round(a - cursor), "ended_by": "suspend"})
            cursor = max(cursor, b)
        stop = now if (is_current and end_at is None) else end_at
        if unknown:
            stretches.append({"started_at": _iso(cursor), "ended_at": None, "seconds": None,
                              "ended_by": "unknown (the end has no time)"})
        else:
            assert stop is not None
            stretches.append({
                "started_at": _iso(cursor), "ended_at": None if is_current and end_at is None else _iso(stop),
                "seconds": round(max(0.0, stop - cursor)),
                "ended_by": "running" if (is_current and end_at is None) else ("clean shutdown" if clean else "unclean end"),
                "current": bool(is_current and end_at is None),
            })
        out.append({
            "session_id": sid,
            "started_at": r.get("at"),
            "ended_at": _iso(end_at) if end_at is not None else None,
            "clean": clean,
            "end_basis": basis,
            "end_unknown": unknown,
            "current": is_current,
            "pid": r.get("pid"),
            "app_version": r.get("app_version"),
            "uptime_s": (round(now - start) if (is_current and end_at is None) else (round(end_at - start) if end_at is not None else None)),
            "suspends": len(cut),
            "stretches": stretches,
        })
    return out


def _gaps(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for prev, nxt in zip(sessions, sessions[1:], strict=False):
        a, b = _epoch(prev.get("ended_at")), _epoch(nxt.get("started_at"))
        if b is None:
            continue
        if a is None:
            gaps.append({"from": None, "to": nxt["started_at"], "seconds": None,
                         "basis": "the previous session's end has no time, so the gap has no length"})
        else:
            gaps.append({"from": prev["ended_at"], "to": nxt["started_at"], "seconds": round(max(0.0, b - a)),
                         "basis": "no record between an end and the next boot; the app cannot know what happened while it was not running"})
    return gaps


# --------------------------------------------------------------------------- #
#  Events (the ledger's, and the release run's)
# --------------------------------------------------------------------------- #


def _ledger_events(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ev: list[dict[str, Any]] = []
    for r in records:
        kind = r.get("kind")
        if kind == "boot":
            ev.append({"at": r.get("at"), "kind": "boot", "label": "boot", "session_id": r.get("session_id"),
                       "detail": {"pid": r.get("pid"), "app_version": r.get("app_version"),
                                  "previous_sentinel_state": r.get("previous_sentinel_state")}})
        elif kind == "end":
            clean = r.get("clean")
            k = "end-clean" if clean else ("end-unknown" if clean is None else "end-unclean")
            ev.append({"at": r.get("at"), "kind": k, "label": k.replace("-", " "), "session_id": r.get("session_id"),
                       "detail": {"basis": r.get("basis"), "reason": r.get("reason"), "uptime_s": r.get("uptime_s")}})
        elif kind == "suspend":
            ev.append({"at": r.get("from"), "to": r.get("to"), "kind": "suspend", "label": "suspend (clock jump)",
                       "session_id": r.get("session_id"), "detail": {"gap_s": r.get("gap_s"), "basis": r.get("basis")}})
        elif kind == "event":
            name = str(r.get("event") or "event")
            detail = {k: v for k, v in r.items() if k not in ("kind", "event", "session_id", "at", "schema")}
            label = name
            if name == "network":
                label = "online" if detail.get("online") else "offline"
            ev.append({"at": r.get("at"), "kind": f"event:{name}", "label": label, "session_id": r.get("session_id"),
                       "detail": detail})
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
        # The phase in flight when the state was last written (or when the process died).
        last_start = None
        for ph in reversed(state.get("phases") or []):
            last_start = ph.get("ended_at") or last_start
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
    }


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


def _summary(sessions: list[dict[str, Any]], anchor_at: float, anchor: str, anchor_basis: str,
             now: float, bar_hours: float) -> dict[str, Any]:
    stretches = _clip([st for s in sessions for st in s["stretches"]], anchor_at, now)
    known = [s for s in stretches if s.get("seconds") is not None]
    unknown = [s for s in stretches if s.get("seconds") is None]
    boots_after = [s for s in sessions if (_epoch(s["started_at"]) or 0) > anchor_at]
    cur = next((s for s in sessions if s.get("current")), None)
    cur_stretch = next((s for s in reversed(known) if s.get("current")), None)
    longest = max(known, key=lambda s: s["seconds"]) if known else None
    bar_s = bar_hours * 3600.0
    reached_at = None
    for s in known:  # chronological: the FIRST stretch that reached the bar
        if s["seconds"] >= bar_s:
            a = _epoch(s["started_at"])
            reached_at = _iso(a + bar_s) if a is not None else None
            break
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
        "sessions_in_window": len([s for s in sessions if (_epoch(s.get("ended_at")) or now) >= anchor_at]),
        "unclean_ends": len([s for s in sessions if s.get("clean") is False and (_epoch(s["started_at"]) or 0) >= anchor_at - 1]),
        "suspends": sum(int(s.get("suspends") or 0) for s in sessions if (_epoch(s.get("ended_at")) or now) >= anchor_at),
        "unknown_end_sessions": len(unknown),
        "stretches": len(known),
        "longest_stretch": ({"seconds": longest["seconds"], "started_at": longest["started_at"],
                             "ended_at": longest.get("ended_at"), "current": bool(longest.get("current"))}
                            if longest else None),
        "current_stretch": ({"seconds": cur_stretch["seconds"], "started_at": cur_stretch["started_at"]}
                            if cur_stretch else None),
        "bar_hours": bar_hours,
        "bar_reached": reached_at is not None,
        "bar_reached_at": reached_at,
        "hours_remaining_on_current_stretch": (
            None if (reached_at is not None or cur_stretch is None)
            else round(max(0.0, bar_s - cur_stretch["seconds"]) / 3600.0, 2)),
        "discontinuous_total_s": round(up),
        "method": (
            "Sessions from the session ledger (boot/end lines; a dead session's end from "
            "its last liveness tick); stretches are sessions split at suspends the two clocks "
            "recorded; sums are over stretches clipped to the anchor. The bar is CONTINUOUS "
            "(gate row B): one stretch of at least bar_hours; the discontinuous total is "
            "reported beside it and is not the bar."
        ),
        "caveats": [
            "the app cannot know what happened while it was not running: a gap has bounds and no cause",
            "a suspend is inferred from wall-clock vs monotonic time between liveness ticks, not from the OS",
        ],
    }
    if unknown:
        out["caveats"].append(
            f"{len(unknown)} session(s) have an end with no time and contribute nothing to the sums")
    if wall > 0 and not unknown:
        # Stretches are rounded to the second and the wall clock is not, so a fresh
        # session can read 33 s of 32.6 s; a share above one is that rounding, never
        # more uptime than time, and it is capped rather than shown.
        out["uptime_share"] = min(1.0, round(up / wall, 4))
    return out


# --------------------------------------------------------------------------- #
#  The one entry point
# --------------------------------------------------------------------------- #


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
    events = _ledger_events(records)
    first_boot = _epoch(sessions[0]["started_at"]) if sessions else None
    anchor_used, anchor_at, basis = anchor, None, ""
    if anchor == "run" and run_block and _epoch(run_block.get("started_at")) is not None:
        anchor_at = _epoch(run_block["started_at"])
        basis = f"the release run {run_block['run_id']} started here"
    elif first_boot is not None:
        anchor_used = "install"
        anchor_at = first_boot
        basis = ("the ledger's first boot; sessions before the ledger existed are unknown"
                 + (" (no release run has started, so the run anchor fell back to it)" if anchor == "run" else ""))
    summary = (_summary(sessions, anchor_at, anchor_used, basis, now, bar_hours) if anchor_at is not None
               else {"anchor": anchor_used, "anchor_at": None, "anchor_basis": "no session has been recorded yet",
                     "now": _iso(now), "restarts": 0, "bar_hours": bar_hours, "bar_reached": False,
                     "method": "no ledger yet", "caveats": ["the ledger begins with this build's first boot"]})
    return {
        "schema": "oo-chronology-1",
        "generated_at": _iso(now),
        "current_session": current,
        "sessions": sessions,
        "gaps": gaps,
        "events": sorted(events, key=lambda e: e.get("at") or ""),
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
