"""
The EXPEDITION LOG — a bounded, incrementally-maintained digest of an unattended run.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-08-12 field ask: the operator dedicates a slow machine to a multi-day unattended
run and needs, on return, ONE thing to copy and paste back — "a log that incrementally
aggregates data during my absence that I can copy paste at whatever stage", explicitly
including a stage where some jobs have NOT finished, and explicitly without crippling
the machine to produce it.

THE TWO CONSTRAINTS THAT DECIDE THE DESIGN
------------------------------------------
1. READING IT MUST BE FREE. The whole point is a button pressed on a slow box holding a
   million-article corpus. So this module NEVER scans the corpus. Every count it reports
   is READ BACK from a row the hourly recorder already wrote
   (:func:`src.database.snapshots.maybe_snapshot_library_stats`, wired into the
   scheduler's idle maintenance) — one small indexed row per metric per hour, ~240 rows
   per metric over ten days. Composing a digest from them is a bounded index read.
   Nothing here calls ``count()`` on ``articles``, and nothing here touches
   ``keyword_mentions``.

2. WRITING IT MUST BE BOUNDED. This project has twice been bitten by an append-only
   stream whose safety rested on "these events are rare" (the run journal's 11 MB ->
   1,615 MB blowup, and the boot-time reader that then OOM-killed the app before the
   unlock screen). So the file here has a CEILING BY CONSTRUCTION: fixed-size counters
   plus a capped ring of notable events (:data:`_MAX_EVENTS`), rewritten in place
   atomically. It cannot grow without bound no matter how long the run lasts or how
   noisy it gets, and a full ring SAYS it dropped older entries rather than presenting a
   truncated history as a complete one.

HONESTY
-------
A metric the recorder has not yet written reports ``null`` with a stated reason, never
0 — "the recorder has not run yet" and "there are none" are different facts, and on a
fresh run the first is the common one. Deltas are first-vs-last WITHIN the stated
window, and the window is reported beside them. No score, no composite, no ETA derived
from a rate the run has not actually sustained.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

# The events ring. Sized so the file stays comfortably copy-pasteable (a few hundred KB
# at most) across a ten-day run: notable events only, never a per-pass or per-article
# breadcrumb. The cap is REPORTED whenever it bites, per the run-journal lesson that a
# bounded read must state its gap rather than let two retained halves read as contiguous.
_MAX_EVENTS = 200

# Notable-event kinds. Deliberately coarse: the digest answers "what happened while I was
# away", not "what happened this second".
EVENT_KINDS = (
    "armed", "disarmed", "job-started", "job-finished", "job-failed",
    "paused", "resumed", "note",
)

# The counters worth carrying, in report order. Every one of these is written by the
# hourly recorder, so reading them back costs one indexed query each.
_TRACKED = (
    "articles",
    "sources",
    "keywords",
    "sources_qualified",
    "sources_disqualified",
    "sources_never_judged",
    "sources_candidates",
    "law_documents",
    "wiki_pages",
)


def _path():
    return data_dir() / "expedition.json"


def _read() -> dict[str, Any]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(state: dict[str, Any]) -> None:
    """Atomic in-place rewrite. Best-effort by design: losing the log must never break
    the run the log exists to describe (the sidecar-resilience lesson — a telemetry
    write path added for resilience must itself degrade, never raise)."""
    try:
        p = _path()
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        _LOG.warning("could not persist expedition.json", exc_info=True)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------- #
# Arming + events                                                             #
# --------------------------------------------------------------------------- #

def arm(*, safety: dict[str, Any] | None = None, note: str = "") -> dict[str, Any]:
    """Mark the start of an unattended run. Idempotent in the sense that re-arming an
    already-armed run keeps the ORIGINAL ``started_at`` — the window a returning operator
    cares about is the whole absence, not the last button press."""
    state = _read()
    if not state.get("armed"):
        state = {
            "armed": True,
            "started_at": _now_iso(),
            "events": state.get("events", [])[-_MAX_EVENTS:],
            "events_dropped": int(state.get("events_dropped", 0)),
        }
    state["armed"] = True
    state["safety"] = safety or {}
    if note:
        state["note"] = note
    _write(state)
    record_event("armed", note or "unattended run armed")
    return state


def disarm(reason: str = "") -> dict[str, Any]:
    state = _read()
    state["armed"] = False
    state["ended_at"] = _now_iso()
    _write(state)
    record_event("disarmed", reason or "unattended run disarmed")
    return _read()


def record_event(kind: str, message: str) -> None:
    """Append one notable event, trimming the ring. Best-effort; never raises."""
    try:
        state = _read()
        events = list(state.get("events") or [])
        events.append({"t": _now_iso(), "kind": str(kind)[:32], "message": str(message)[:400]})
        if len(events) > _MAX_EVENTS:
            dropped = len(events) - _MAX_EVENTS
            state["events_dropped"] = int(state.get("events_dropped", 0)) + dropped
            events = events[-_MAX_EVENTS:]
        state["events"] = events
        _write(state)
    except Exception:  # noqa: BLE001 - a log that breaks the run defeats its own purpose
        _LOG.warning("expedition event not recorded", exc_info=True)


# --------------------------------------------------------------------------- #
# The digest                                                                  #
# --------------------------------------------------------------------------- #

def _series_window(session, metric: str, *, days: int) -> dict[str, Any]:
    """First/last/delta for one recorded metric over the window — read back from the
    hourly snapshot rows, never recomputed from the corpus."""
    from src.database.snapshots import metric_history

    try:
        hist = metric_history(session, metric=metric, days=days)
    except Exception as exc:  # noqa: BLE001 - one unreadable metric must not blank the digest
        return {"metric": metric, "value": None, "reason": f"unreadable ({type(exc).__name__})"}
    series = hist.get("series") or []
    if not series:
        return {
            "metric": metric, "value": None, "first": None, "delta": None,
            "reason": (
                "no snapshot recorded yet — the hourly recorder runs in the scheduler's "
                "idle maintenance, so this fills in once the run has been up an hour"
            ),
            "recording_began_at": hist.get("recording_began_at"),
        }
    first, last = series[0], series[-1]
    return {
        "metric": metric,
        "value": last["n"],
        "first": first["n"],
        "delta": last["n"] - first["n"],
        "first_at": first["t"],
        "last_at": last["t"],
        "samples": len(series),
        "recording_began_at": hist.get("recording_began_at"),
    }


def _window_days(state: dict[str, Any]) -> int:
    """Days to read back: the run's own age, rounded up, clamped to something a bounded
    read can always serve. Never a fixed constant — a two-day run reporting a 30-day
    delta would attribute pre-run growth to the run."""
    started = state.get("started_at")
    if not started:
        return 1
    try:
        began = datetime.fromisoformat(started)
    except ValueError:
        return 1
    age = datetime.now(UTC) - began
    return max(1, min(60, int(age / timedelta(days=1)) + 1))


def _memory() -> dict[str, Any]:
    """Available RAM, read from /proc/meminfo where it exists. Honest ``null`` elsewhere —
    never a guess, and never a refusal derived from a measurement we could not take."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return {"available_mb": int(line.split()[1]) // 1024, "source": "/proc/meminfo"}
    except (OSError, ValueError, IndexError):
        pass
    return {"available_mb": None, "reason": "not readable on this platform"}


def _jobs() -> list[dict[str, Any]]:
    """Live job states, from the in-memory registry. No DB access.

    Idle jobs are omitted: a returning operator wants what RAN, and every registered
    job reports idle most of the time. A job that ERRORED is kept — a run that failed
    on day two is exactly what the log exists to surface."""
    try:
        from src.jobs.background import all_job_statuses

        out = []
        for st in all_job_statuses():
            state = st.get("state")
            if state in (None, "idle"):
                continue
            out.append({
                "job": st.get("label") or st.get("kind"),
                "state": state,
                "detail": st.get("detail"),
                "done": st.get("done"),
                "total": st.get("total"),
                "error": st.get("error"),
            })
        return out
    except Exception:  # noqa: BLE001 - the registry shape is not worth failing a digest over
        return []


def refresh(session) -> dict[str, Any]:
    """Recompute the digest's counter block and persist it. Cheap by construction:
    bounded index reads over already-recorded snapshot rows plus in-memory state.

    Called from the scheduler's post-pass housekeeping, so it rides work that is already
    happening rather than adding a poller of its own."""
    state = _read()
    days = _window_days(state)
    try:
        state["counters"] = [_series_window(session, m, days=days) for m in _TRACKED]
        state["window_days"] = days
        state["refreshed_at"] = _now_iso()
    except Exception:  # noqa: BLE001
        _LOG.warning("expedition refresh failed", exc_info=True)
        return state
    _write(state)
    return state


def digest() -> dict[str, Any]:
    """The stored digest plus live, free-to-read state. A PLAIN FILE READ — this is the
    call behind the operator's copy-paste button, and it must stay O(1) in corpus size."""
    state = _read()
    if not state:
        return {
            "armed": False,
            "reason": "no unattended run has been armed on this machine yet",
            "events": [],
        }
    from src.ingest import kill_switch_active

    live: dict[str, Any] = {"memory": _memory(), "jobs": _jobs()}
    try:
        live["airplane_mode"] = bool(kill_switch_active())
    except Exception:  # noqa: BLE001
        live["airplane_mode"] = None
    try:
        from src.scheduler.runner import get_scheduler

        sched = get_scheduler()
        live["collecting"] = bool(sched.is_running())
    except Exception:  # noqa: BLE001
        live["collecting"] = None
    try:
        from src.monitoring.forensics import previous_session_report

        live["previous_session"] = previous_session_report().get("previous_session")
    except Exception:  # noqa: BLE001
        live["previous_session"] = None

    return {
        **state,
        "live": live,
        "method": (
            "Counters are read back from the hourly snapshot rows the recorder already "
            "writes — this digest never scans the corpus, so producing it costs the "
            "machine nothing. Deltas are first-vs-last within the stated window. A "
            "counter with no snapshot yet reports null with its reason, never 0."
        ),
    }


def render_text(d: dict[str, Any] | None = None) -> str:
    """A compact, copy-pasteable rendering. Built to be readable when PASTED INTO A CHAT
    — no colour, no wide tables, and every absence stated in words."""
    d = d if d is not None else digest()
    # Render whenever there is ANYTHING to show. Gating on "armed" alone would hide
    # events the app had already recorded (a job that failed before anyone armed a run
    # is exactly the kind of thing this log exists to surface) -- found by its own test.
    if not d.get("armed") and not d.get("started_at") and not d.get("events"):
        return "No unattended run has been armed on this machine yet."

    lines: list[str] = ["# Open Omniscience — expedition log", ""]
    started = d.get("started_at")
    lines.append(f"- armed at: {started or 'unknown'}")
    if d.get("ended_at"):
        lines.append(f"- disarmed at: {d['ended_at']}")
    lines.append(f"- still armed: {'yes' if d.get('armed') else 'no'}")
    if started:
        try:
            age = datetime.now(UTC) - datetime.fromisoformat(started)
            lines.append(f"- elapsed: {age.days}d {age.seconds // 3600}h")
        except ValueError:
            pass
    lines.append(f"- digest refreshed: {d.get('refreshed_at') or 'not yet'}")

    live = d.get("live") or {}
    lines += ["", "## Right now", ""]
    lines.append(f"- collecting: {live.get('collecting')}")
    lines.append(f"- airplane mode: {live.get('airplane_mode')}")
    mem = live.get("memory") or {}
    lines.append(
        f"- memory available: {mem.get('available_mb')} MB"
        if mem.get("available_mb") is not None
        else f"- memory available: not measured ({mem.get('reason')})"
    )
    if live.get("previous_session"):
        lines.append(f"- previous session ended: {live['previous_session']}")

    safety = d.get("safety") or {}
    if safety:
        lines += ["", "## Safety decision taken at arming", ""]
        for k, v in safety.items():
            lines.append(f"- {k}: {v}")

    lines += ["", f"## Counters (window: last {d.get('window_days', '?')} day(s))", ""]
    for c in d.get("counters") or []:
        name = c.get("metric")
        if c.get("value") is None:
            lines.append(f"- {name}: not recorded yet — {c.get('reason')}")
            continue
        delta = c.get("delta")
        sign = "+" if (delta or 0) >= 0 else ""
        lines.append(
            f"- {name}: {c['value']:,} ({sign}{delta:,} over {c.get('samples')} hourly samples)"
        )

    jobs = live.get("jobs") or []
    lines += ["", "## Jobs not idle", ""]
    if not jobs:
        lines.append("- none running")
    for j in jobs:
        prog = ""
        if j.get("total"):
            prog = f" [{j.get('done')}/{j.get('total')}]"
        lines.append(f"- {j.get('job')}: {j.get('state')}{prog} {j.get('detail') or ''}".rstrip())
        if j.get("error"):
            lines.append(f"  - error: {j['error']}")

    events = d.get("events") or []
    dropped = int(d.get("events_dropped") or 0)
    lines += ["", f"## Events (most recent {len(events)})", ""]
    if dropped:
        lines.append(
            f"_{dropped} older event(s) dropped — this ring keeps the newest "
            f"{_MAX_EVENTS} so the file cannot grow without bound._"
        )
        lines.append("")
    for e in events:
        lines.append(f"- {e.get('t')} · {e.get('kind')} · {e.get('message')}")

    lines += ["", "---", d.get("method", "")]
    return "\n".join(lines)


# ------------------------------------------------------------------- #
# Unattended-run safety                                               #
# ------------------------------------------------------------------- #

# Scan-memory heuristic. A qualification batch judges its candidates through
# source_audit.per_source_metrics -> source_quality.collect_article_stats, which
# materialises one dict entry AND one stat object per article in the WHOLE corpus
# (src/analytics/source_quality.py) -- each stat carrying its own metrics dict and
# url string, which is most of the weight.
#
# MEASURED 2026-08-13, against the real ArticleStat + compute_metrics rather than a
# hand-written lookalike: 797 / 795 / 796 bytes per article at n = 50k / 100k / 200k
# -- flat, so it extrapolates linearly to ~759 MiB of traced allocation at 1M
# articles. The constant is deliberately left ABOVE that: tracemalloc counts Python
# allocations, while what the OOM killer reads is RSS, which additionally carries
# allocator overhead and fragmentation. So this is a measurement-backed figure for
# the scan, not a measurement of THIS machine's peak -- which is why the decision
# below still travels with its basis rather than being presented as a fact.
SCAN_MB_PER_MILLION_ARTICLES = 1000
SCAN_WORKING_MARGIN_MB = 1000


def latest_recorded_articles(session) -> int | None:
    """Newest recorded article count, read back from the hourly snapshot rows.

    Deliberately NOT a live ``count()``: this runs on a slow box holding a million
    articles, and the whole point of the safety check is to avoid making the machine
    do expensive work. A corpus with no snapshot yet returns None -- unmeasured, and
    the caller must not turn that into a refusal."""
    try:
        from src.database.snapshots import metric_history

        series = (metric_history(session, metric="articles", days=30) or {}).get("series") or []
        return int(series[-1]["n"]) if series else None
    except Exception:  # noqa: BLE001 - an unreadable snapshot is unmeasured, never a verdict
        return None


def qualification_safety(session) -> dict:
    """Decide whether a bulk qualification run is safe to start unattended here.

    THE ASYMMETRY IS DELIBERATE. An OOM on day two costs the entire absence -- the app
    dies, collection stops, and nothing is measured. Skipping the backlog drain costs
    only the backlog, which is a queue rather than a release blocker. So a MEASURED
    shortfall declines; but an UNMEASURED one does not decline on our behalf, because
    refusing on a measurement we could not take is the fabricated-refusal mirror of a
    fabricated pass -- it is reported, and the memory guard (which pauses the job
    between batches) remains the net it has always been."""
    mem = _memory()
    avail = mem.get("available_mb")
    articles = latest_recorded_articles(session)

    if avail is None:
        return {
            "safe": True, "basis": "unmeasured",
            "reason": (
                "available memory could not be read on this platform, so no shortfall was "
                "measured; the memory guard still pauses the job between batches"
            ),
            "available_mb": None, "articles": articles,
        }
    if articles is None:
        return {
            "safe": True, "basis": "unmeasured",
            "reason": (
                "no article snapshot recorded yet, so the scan's size could not be estimated; "
                "the memory guard still pauses the job between batches"
            ),
            "available_mb": avail, "articles": None,
        }

    need = int(SCAN_WORKING_MARGIN_MB + (articles / 1_000_000) * SCAN_MB_PER_MILLION_ARTICLES)
    safe = avail >= need
    return {
        "safe": safe,
        "basis": "estimated",
        "available_mb": avail,
        "articles": articles,
        "estimated_need_mb": need,
        "reason": (
            f"a qualification batch scans the whole corpus in memory; at {articles:,} articles "
            f"that is estimated at ~{need} MB and {avail} MB is available"
            + ("" if safe else " — bulk qualification was NOT started, so a slow unattended run "
                              "cannot be ended by an out-of-memory kill")
        ),
    }
