"""The planet's prior, summarised once per country (v0.6.0, R435): a CACHE of one function of ``osm_history_changes``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE PROBLEM, MEASURED. The surfaces that read the planet's past (``trends._prior``: tag adoption, openings and closures; ``profile._prior``: brands,
channels, freshness) group the whole ``osm_history_changes`` table of a country by month on EVERY request. On a synthetic Germany-scale lane
(2.0 million places, 12 million history rows) that is 23 s to 67 s a surface, growing with the history, and nothing was kept.

WHAT THIS MODULE DOES. When a history cut finishes, ONE pass over the country's history rows computes exactly the aggregate rows the readers
already compute, and stores them (``osm_history_monthly``, headed by ``osm_history_summaries``). A reader then selects a few hundred rows. A cut
that already exists gets the same pass on request (``start_build``), because a GET never writes.

WHAT MUST STAY TRUE.

* A CACHE, NEVER A SECOND SOURCE OF TRUTH. The stored rows are the very tuples the computed path hands the series builders
  (``_adoption_series`` and its siblings), so both paths go through the same code from there on; ``surface_rows`` is the ONE definition of
  what is counted, used by the reader's fallback and by the writer alike. The parity test runs both paths and compares the answers.
* STALE IS SAID, NEVER SERVED. A summary is used only when its rule digest equals the code's (``rule_version``: the key sets and a revision
  number for the SQL) AND its ``cut_finished_at`` equals the cut's. Otherwise the reader computes from the history, as before, and the answer
  carries ``source: "computed"`` with the reason (``summary.state``). It never returns an empty prior as if there were no history.
* UNKNOWN STAYS UNKNOWN. A month with no row has no stored row; the series builders fill it exactly as they do today.
* THE METHOD AND CAVEAT STRINGS ARE UNCHANGED, and the vintage still states the history file's own date (from the cut, not the summary).
* READ-ONLY READERS STAY READ-ONLY. Only the cut job and the POST route write; the build is local work, makes no request, and a failed build is
  logged and leaves the computed path in place.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

#: Bump when the SQL that produces the rows changes in a way the key sets below do not show.
RULE_REVISION = 1

#: The surfaces that read the planet's past. ``trends`` is analytic surfaces 2 and 3; the rest are ``profile.SURFACES``.
SURFACES = ("trends", "brands", "channels", "freshness")

_RUN_LOCK = threading.Lock()
_RUNNING: set[str] = set()


def rule_version() -> str:
    """A digest of everything that decides WHAT is counted: adding a key to a group makes every stored summary stale, by construction."""
    from src.osm.profile import _FRESH_FIELDS, BRAND_GROUPS, SOCIAL_GROUPS
    from src.osm.trends import CLOSED_VALUES, SIGNALS, _default_groups

    parts = repr((RULE_REVISION, _default_groups(), BRAND_GROUPS, SOCIAL_GROUPS, SIGNALS, CLOSED_VALUES, _FRESH_FIELDS))
    return hashlib.sha256(parts.encode()).hexdigest()[:12]


def is_building(alpha3: str) -> bool:
    with _RUN_LOCK:
        return alpha3 in _RUNNING


def surface_rows(s, alpha3: str, surface: str, h, month, where) -> dict[str, list[tuple]]:
    """THE definition of what the prior counts, for one surface: ``{kind: rows}`` inside an open ``_history_scope``.

    ``adoption`` rows are ``(month, tag group, "gained" | "lost", places)``; ``signal``, ``event`` and ``fresh`` rows are ``(month, name, places)``.
    """
    from sqlalchemy import select

    from src.osm.profile import BRAND_GROUPS, SOCIAL_GROUPS, _freshness_rows
    from src.osm.trends import _adoption_rows, _obj, _signal

    if surface == "freshness":
        return {"fresh": [tuple(r) for r in _freshness_rows(s, h, month, *where)]}
    if surface in ("brands", "channels"):
        groups = BRAND_GROUPS if surface == "brands" else SOCIAL_GROUPS
        return {"adoption": [tuple(r) for r in _adoption_rows(s, h, month, *where, groups=groups)]}
    sig = _signal(h)
    signal_rows = s.execute(select(month, sig, _obj(h)).where(*where, sig.is_not(None)).group_by(month, sig)).all()
    # Object-level rows: created / deleted (restored is its own fact and not a closure or an opening here).
    event_rows = s.execute(
        select(month, h.c.change, _obj(h))
        .where(h.c.country_alpha3 == alpha3, h.c.key.is_(None), h.c.change.in_(("created", "deleted")), h.c.version_timestamp.is_not(None))
        .group_by(month, h.c.change)
    ).all()
    return {
        "adoption": [tuple(r) for r in _adoption_rows(s, h, month, *where)],
        "signal": [tuple(r) for r in signal_rows],
        "event": [tuple(r) for r in event_rows],
    }


def computed_rows(s, alpha3: str, surface: str) -> dict[str, list[tuple]]:
    """The fallback: the rows of one surface, computed from the history rows now (the cost the summary exists to avoid)."""
    from src.osm.trends import _history_scope

    with _history_scope(s, alpha3) as (h, month, where):
        return surface_rows(s, alpha3, surface, h, month, where)


def _head_state(head, cut) -> str:
    """``current``, or why a stored header may not be served: ``not-built``, ``stale-rule`` (another rule wrote it) or ``stale-cut`` (the cut was run again)."""
    if head is None:
        return "not-built"
    if head.rule_version != rule_version():
        return "stale-rule"
    if head.cut_finished_at != cut.finished_at:
        return "stale-cut"
    return "current"


def rows_for(s, alpha3: str, surface: str, cut, have: set[str]) -> tuple[dict[str, list[tuple]], dict[str, Any]]:
    """``(rows by kind, how they were got)``: from the stored summary when it is current, else computed from the history, saying why."""
    from sqlalchemy import select

    from src.osm.lane_models import OsmHistoryMonthly, OsmHistorySummary

    info: dict[str, Any] = {"source": "computed", "state": "not-built", "building": is_building(alpha3)}
    if OsmHistorySummary.__tablename__ not in have or OsmHistoryMonthly.__tablename__ not in have:
        info["state"] = "no-summary-table"
    else:
        head = s.query(OsmHistorySummary).filter_by(alpha3=alpha3, surface=surface).one_or_none()
        state = _head_state(head, cut)
        if state != "current":
            info["state"] = state
        else:
            m = OsmHistoryMonthly.__table__
            rows = s.execute(select(m.c.kind, m.c.bucket, m.c.name, m.c.direction, m.c.n).where(m.c.alpha3 == alpha3, m.c.surface == surface)).all()
            by: dict[str, list[tuple]] = {}
            for kind, bucket, name, direction, n in rows:
                by.setdefault(kind, []).append((bucket, name, direction, int(n)) if kind == "adoption" else (bucket, name, int(n)))
            built = head.built_at.isoformat() if head.built_at else None
            info.update(source="summary", state="current", built_at=built, seconds=head.seconds)
            return by, info
    return computed_rows(s, alpha3, surface), info


def summary_state(alpha3: str) -> dict[str, Any]:
    """What the page asks while a build runs: the country's summary state, from the headers alone (milliseconds, read-only, never raises).

    ``current`` only when EVERY surface's header is current; otherwise the first reason found. ``building`` is this process's own flag.
    """
    from sqlalchemy import inspect

    from src.osm.lane_models import OsmHistoryMonthly, OsmHistorySummary
    from src.osm.trends import _prior_cut
    from src.versioned import store

    out: dict[str, Any] = {"country": alpha3, "building": is_building(alpha3)}
    try:
        if not store.lane_exists("osm"):
            return {**out, "state": "lane-never-run"}
        with store.lane_session("osm") as s:
            have = set(inspect(s.get_bind()).get_table_names())
            cut, why = _prior_cut(s, alpha3, have)
            if cut is None:
                return {**out, "state": "no-cut", "reason": (why or {}).get("reason")}
            if OsmHistorySummary.__tablename__ not in have or OsmHistoryMonthly.__tablename__ not in have:
                return {**out, "state": "no-summary-table"}
            heads = {h.surface: h for h in s.query(OsmHistorySummary).filter_by(alpha3=alpha3)}
            states = [_head_state(heads.get(surface), cut) for surface in SURFACES]
            bad = next((x for x in states if x != "current"), "current")
            built = [h.built_at for h in heads.values() if h.built_at]
            return {**out, "state": bad, "built_at": max(built).isoformat() if built and bad == "current" else None}
    except Exception as exc:  # noqa: BLE001 - the page keeps the computed answer it has
        log_failure(_LOG, f"osm: the {alpha3} planet-prior summary state could not be read", exc, level=logging.WARNING)
        return {**out, "state": "unreadable"}


def build_summary(alpha3: str, *, only_if_missing: bool = False) -> dict[str, Any]:
    """Compute and store every surface's monthly rows for one country in ONE pass over its history rows. Raises only on a lane failure.

    The read and the write are two sessions on purpose: the pass can take a minute, and a write after a long read in the same transaction can
    be refused by a writer that committed meanwhile. The cut's ``finished_at`` is read FIRST and stored with the rows, so a cut that is re-run
    during the pass leaves a summary that reads as stale, never one that passes for current.
    """
    from sqlalchemy import delete, insert, inspect

    from src.osm.lane_models import OsmHistoryCut, OsmHistoryMonthly, OsmHistorySummary
    from src.osm.trends import _history_scope, _prior_cut
    from src.versioned import store

    if not store.lane_exists("osm"):
        return {"status": "lane-never-run"}
    # A lane file cut by an older build lacks the two tables, and only a writer may add them: ``create_lane`` is idempotent and additive
    # (``create_all`` for the tables the file does not have), the same call every cut makes, so a summary can be built for a cut that exists.
    store.create_lane("osm")
    rule = rule_version()
    t0 = time.monotonic()
    with store.lane_session("osm") as s:
        have = set(inspect(s.get_bind()).get_table_names())
        cut, why = _prior_cut(s, alpha3, have)
        if cut is None:
            return {"status": "no-cut", "reason": (why or {}).get("reason")}
        finished, vintage = cut.finished_at, cut.history_vintage
        if only_if_missing:
            heads = s.query(OsmHistorySummary).filter_by(alpha3=alpha3).all()
            if {h.surface for h in heads if h.rule_version == rule and h.cut_finished_at == finished} >= set(SURFACES):
                return {"status": "current"}
        data: dict[str, dict[str, list[tuple]]] = {}
        with _history_scope(s, alpha3) as (h, month, where):
            for surface in SURFACES:
                data[surface] = surface_rows(s, alpha3, surface, h, month, where)
    seconds = round(time.monotonic() - t0, 3)
    with store.lane_session("osm") as s:
        now_cut = s.query(OsmHistoryCut).filter_by(alpha3=alpha3).one_or_none()
        if now_cut is None or now_cut.status != "complete" or now_cut.finished_at != finished:
            return {"status": "superseded"}
        s.execute(delete(OsmHistoryMonthly).where(OsmHistoryMonthly.alpha3 == alpha3))
        s.execute(delete(OsmHistorySummary).where(OsmHistorySummary.alpha3 == alpha3))
        total = 0
        for surface, kinds in data.items():
            flat: list[dict[str, Any]] = []
            for kind, rows in kinds.items():
                for r in rows:
                    direction = r[2] if kind == "adoption" else None
                    flat.append({"alpha3": alpha3, "surface": surface, "kind": kind, "bucket": r[0], "name": r[1], "direction": direction, "n": int(r[-1])})
            if flat:
                s.execute(insert(OsmHistoryMonthly), flat)
            s.add(
                OsmHistorySummary(
                    alpha3=alpha3, surface=surface, rule_version=rule, cut_finished_at=finished, history_vintage=vintage, seconds=seconds, rows=len(flat)
                )
            )
            total += len(flat)
    return {"status": "built", "rows": total, "seconds": seconds}


def build_quietly(alpha3: str) -> None:
    """The cut job's hook: a failed summary must never fail (or hide) a finished cut; the readers compute until it is rebuilt."""
    with _RUN_LOCK:
        if alpha3 in _RUNNING:
            return
        _RUNNING.add(alpha3)
    try:
        res = build_summary(alpha3)
        _LOG.info("osm: the %s planet-prior summary: %s", alpha3, res.get("status"))
    except Exception as exc:  # noqa: BLE001 - recorded in the log; the computed path stays in place
        log_failure(_LOG, f"osm: the {alpha3} planet-prior summary could not be built", exc, level=logging.WARNING)
    finally:
        with _RUN_LOCK:
            _RUNNING.discard(alpha3)


def start_build(alpha3: str) -> dict[str, Any]:
    """Start :func:`build_summary` on a thread of its own, for a cut that already exists; ``{"started": bool, "status": ...}``.

    Nothing that can refuse needs the lane, so this answers at once; the thread skips a country whose summary is already current.
    """
    with _RUN_LOCK:
        if alpha3 in _RUNNING:
            return {"started": False, "status": "building"}
        _RUNNING.add(alpha3)

    def run() -> None:
        try:
            res = build_summary(alpha3, only_if_missing=True)
            _LOG.info("osm: the %s planet-prior summary: %s", alpha3, res.get("status"))
        except Exception as exc:  # noqa: BLE001 - logged; the readers keep computing
            log_failure(_LOG, f"osm: the {alpha3} planet-prior summary could not be built", exc, level=logging.WARNING)
        finally:
            with _RUN_LOCK:
                _RUNNING.discard(alpha3)

    threading.Thread(target=run, name=f"osm-prior-summary-{alpha3}", daemon=True).start()
    return {"started": True, "status": "building"}
