"""Which members of the Diagnostics build are SCANS, what each costs, and the time Quick spends on them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE SPLIT (R119, R124; docs/plans/2026-10-06-diagnostics-redesign/PLAN.md section 8). A build used to
run every member inside one exclusive window, so collection stood still for all of it: 9 to 48
minutes, measured over 17 builds. Most of that is not the records. Of the members, 60 read state
(histories, counts, settings, the session's own forensics) and took 163 to 225 s in every build
read; 16 re-read the corpus or time the machine, and took 380 to 2,661 s. So:

* the RECORDS run first, with collection still running, and
* the SCANS run after them, under the exclusive window, in one of two modes:
  - ``quick`` (the default): one shared budget, :data:`SCAN_BUDGET_S`, scans shortest first;
  - ``thorough``: no shared budget, every scan under its own 300 s deadline, as before.

A scan that does not fit is NAMED (``skipped-budget``, with its own estimate and the reason), never
dropped without a word and never written as a smaller version of itself.

WHAT THE NUMBERS PROTECT. :data:`SCAN_BUDGET_S` protects two costs, and nothing else: the time
collection is paused (the scans hold the machine exclusive), and the time before the user has a
file. It is not a size limit and not a quality bar. :data:`SCAN_FLOOR_S` protects a scan from being
started with so little time left that all it could do is begin: it is named as skipped, with the
reason, instead of being written as a file that gathered next to nothing. (A scan the budget cuts
after it has started is ``partial-deadline`` with what it had, the outcome eight members already
end with at their 300 s deadline.)

WHERE THE ESTIMATES COME FROM. ``est_s`` is the member's median wall time over the 17 field bundles
read on 2026-10-06 (``members.csv`` of the plan), taken over the builds in which it had work to do
and capped at the 300 s deadline every scan already ran under. Three members cost under a second in
the median over all 17 only because eleven builds declined them (the Light profile) or the machine
did; their figures here are the cost where they ran (300, 300 and 167 s). An estimate only ORDERS the
scans (shortest first, so that a Quick build runs as many as fit); it never decides that a scan is
too long: a scan starts if :data:`SCAN_FLOOR_S` are left, whatever it is expected to cost, and is
asked to stop at the time that is left. That bounds the pause, not to the second: a database scan stops at its next
progress check, Python work after its last query is not interrupted, and a scan that is not a database read is abandoned on
its thread, which runs on, so a scan can hold the window past the budget by that overrun (its ``wall_s`` against its ``deadline_s`` says by how much).

A scan an owner adds states its estimate by one line in :data:`SCAN_EST_S` (the slot table has no
estimate field); one that states none counts as :data:`DEFAULT_SCAN_S`. This module is a table and four small functions. It reads nothing, opens no
file and imports nothing heavy, so the tests can pin it.
"""

from __future__ import annotations

from typing import Any

#: The two modes. ``quick`` is what the panel asks for unless the user ticks Thorough.
MODES = ("quick", "thorough")

#: The time Quick spends on all the scans together, in seconds. It protects the collection pause and
#: the user's wait before there is a file (see the module docstring), and a scan that does not fit
#: is named in the manifest. A bound on what a scan is ASKED for, not a promise to the second: a scan's own deadline is the
#: smaller of its 300 s and the time left here, and one that does not stop on request can pass it (see the module docstring).
SCAN_BUDGET_S = 600.0

#: A scan is started only while at least this much of the budget is left.
SCAN_FLOOR_S = 30.0

#: The deadline every scan ran under before the budget existed, and the cost taken for a scan that
#: states no estimate: the longest a scan was ever allowed.
DEFAULT_SCAN_S = 300.0

#: The 16 scans of the build, with ``est_s`` (see the module docstring for where each comes from).
SCAN_EST_S: dict[str, float] = {
    "country-code-duplicates.json": 20.0,
    "merge-diag.json": 25.5,
    "non-article-scan.json": 58.4,
    "card-audit.json": 60.5,
    "criteria-calibration.json": 61.8,
    "date-extraction.json": 64.9,
    "lemma-preview.json": 75.4,
    "article-length.json": 103.2,
    "keyword-growth.json": 113.3,
    "keyword-log-digest.json": 167.0,
    "keyword-engine.json": 231.0,
    "leads-quality.json": 275.0,
    "benchmark.json": 300.0,
    "bulletin-weekly.json": 300.0,
    "performance.json": 300.0,
    "source-audit.json": 300.0,
}


#: The topical classes of the zip, so a reader opening a bundle on a machine that crashed can go to
#: "memory" or "database" rather than read 50 file names (the manifest's ``area`` per member; R119).
#: A class says WHAT A MEMBER IS ABOUT, never how serious it is, and no member is in two.
AREAS = (
    "overview", "memory", "storage", "database", "sessions", "runs", "keywords",
    "interface", "sources", "ai", "selftests", "build",
)

#: Member to area, for every member ``bundle.py`` lists itself (the slots carry their own, in
#: ``diagnostics_slots``). ``tests/test_diagnostic_slots.py`` fails on a member without one.
MEMBER_AREAS: dict[str, str] = {
    "debug-bundle.json": "overview",
    "home-cards.json": "interface",
    "card-audit.json": "interface",
    "frontend-errors.json": "interface",
    "bulletin-weekly.json": "interface",
    "bulletin-language.json": "interface",
    "request-latency.json": "interface",
    "search-timing.json": "interface",
    "kpi.json": "interface",
    "leads-quality.json": "interface",
    "keyword-engine.json": "keywords",
    "keyword-log-digest.json": "keywords",
    "keyword-growth.json": "keywords",
    "lemma-preview.json": "keywords",
    "month-occupancy.json": "keywords",
    "article-length.json": "keywords",
    "date-extraction.json": "keywords",
    "selftests.json": "selftests",
    "performance.json": "memory",
    "benchmark.json": "memory",
    "merge-diag.json": "memory",
    "columnar.json": "storage",
    "storage.json": "storage",
    "windows-locks.json": "storage",
    "fixity.json": "storage",
    "contention.json": "database",
    "slow-queries.json": "database",
    "schema-drift.json": "database",
    "corpus-integrity.json": "database",
    "country-code-duplicates.json": "database",
    "session-forensics.json": "sessions",
    "chronology.json": "sessions",
    "release-run.json": "sessions",
    "p0-validation.json": "sessions",
    "run-journal.json": "runs",
    "run-timeline.json": "runs",
    "soak-window.json": "runs",
    "wiki-lane-history.json": "runs",
    "source-audit.json": "sources",
    "non-article-scan.json": "sources",
    "criteria-calibration.json": "sources",
    "source-qualification-export.json": "sources",
    "qualification-integrity.json": "sources",
    "law-coverage.json": "sources",
    "law-ingest.json": "sources",
    "network.json": "sources",
    "ai.json": "ai",
    "ai-runs.json": "ai",
    "ai-activity.json": "ai",
    "freshness.json": "build",
}

#: What a member that nobody classified reads as; ``tests/test_diagnostic_slots.py`` fails on it.
UNCLASSIFIED_AREA = "unclassified"


def resolve_mode(requested: Any) -> str:
    """The mode a caller asked for. ``thorough`` for anything that is not a recognised name.

    The direction is deliberate: a typo, a stale client or a future mode name must never produce a
    SMALLER build than the user believes they asked for. A Quick build that was meant to be Thorough
    costs the scans that did not run; a Thorough one that was meant to be Quick costs time, which
    the progress text names while it runs. (A call that passes no mode at all, over HTTP, gets the
    route's own default, which is ``quick``: this function sees only what the caller wrote.)"""
    if not isinstance(requested, str):
        return "thorough"
    value = requested.strip().lower()
    return value if value in MODES else "thorough"


def scan_est_s(name: str, table: dict[str, float] | None = None) -> float:
    """What the scan ``name`` is expected to cost, in seconds; :data:`DEFAULT_SCAN_S` where none is stated."""
    return float((SCAN_EST_S if table is None else table).get(name, DEFAULT_SCAN_S))


def is_scan(name: str, table: dict[str, float] | None = None) -> bool:
    """Whether ``name`` is a scan (a member that re-reads the corpus or times the machine)."""
    return name in (SCAN_EST_S if table is None else table)


def split_members(
    members: list[tuple[str, Any]], table: dict[str, float] | None = None
) -> tuple[list[tuple[str, Any]], list[tuple[str, Any]]]:
    """``(records, scans)`` from a member list: records in the order given, scans shortest first.

    Ties keep the order of the list, so the same corpus produces the same order every build, which
    is what lets a reader compare two manifests."""
    est = SCAN_EST_S if table is None else table
    records = [m for m in members if m[0] not in est]
    scans = [m for m in members if m[0] in est]
    scans.sort(key=lambda m: scan_est_s(m[0], est))  # stable: ties keep the list's order
    return records, scans


def scan_deadline_s(cap_s: float, elapsed_s: float, budget_s: float | None) -> tuple[float | None, bool]:
    """The deadline a scan runs under, and whether the budget (not its own cap) is what sets it.

    ``cap_s`` is the scan's own deadline (300 s by default), ``elapsed_s`` the time the scans have
    taken so far, ``budget_s`` the shared budget (``None`` in Thorough: no budget). Returns
    ``(None, False)`` when the scan must not start: fewer than :data:`SCAN_FLOOR_S` of the budget are
    left. Otherwise the smaller of the cap and the time left: what the scan is asked to stop at, so the budget bounds the
    pause up to the overrun of a scan that does not stop on request."""
    if budget_s is None:
        return cap_s, False
    left = budget_s - elapsed_s
    if left < SCAN_FLOOR_S:
        return None, False
    if left < cap_s:
        return left, True
    return cap_s, False


def scans_block(
    results: list[dict[str, Any]], *, mode: str, budget_s: float | None,
    table: dict[str, float] | None = None,
) -> dict[str, Any]:
    """The manifest's ``scans`` block: what was planned, what ran, what was cut and what was skipped.

    Built from the member results the build wrote, so it can never say something the members do not:
    ``planned`` is every scan that has an entry, in the order it was run; ``ran`` those that began
    (any outcome but a skip or a decline); ``partial`` those the deadline or the budget cut after
    they had gathered something; ``skipped`` those that never began for want of budget, each with
    its own estimate and the reason."""
    est = SCAN_EST_S if table is None else table
    scans = [r for r in results if r.get("file") in est]
    planned = [{"file": r["file"], "est_s": scan_est_s(r["file"], est)} for r in scans]
    ran = [r["file"] for r in scans if r.get("outcome") not in ("skipped-budget", "declined-ram", "declined-light")]
    partial = [r["file"] for r in scans if r.get("outcome") == "partial-deadline"]
    skipped = [
        {"file": r["file"], "est_s": scan_est_s(r["file"], est), "reason": r.get("skipped_reason")}
        for r in scans if r.get("outcome") == "skipped-budget"
    ]
    declined = [r["file"] for r in scans if r.get("outcome") in ("declined-ram", "declined-light")]
    # ``ran`` counts a scan that began, whatever the budget left it: the ones the budget STOPPED are named here (a scan
    # whose deadline was the time the budget had left AND that ended on a deadline: partial with what it had, or cut to
    # nothing, which is ``skipped-deadline``), so the budget's effect is one list. A scan that had less than its own
    # 300 s left and finished anyway carries ``budget_cut`` on its entry (that was its deadline) and is not listed.
    cut_by_budget = [
        r["file"] for r in scans
        if r.get("budget_cut") and r.get("outcome") in ("partial-deadline", "skipped-deadline")
    ]
    return {
        "mode": mode,
        "scan_budget_s": budget_s,
        "floor_s": SCAN_FLOOR_S if budget_s is not None else None,
        "order": "shortest estimate first (est_s), ties in the build's own order",
        "planned": planned,
        "ran": ran,
        "partial": partial,
        "cut_by_budget": cut_by_budget,
        "skipped": skipped,
        "declined": declined,
        "scan_seconds": round(sum(float(r.get("wall_s") or 0.0) for r in scans), 1),
    }
