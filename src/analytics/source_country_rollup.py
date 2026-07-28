"""In-memory serve for the ``/api/database/countries`` per-country source breakdown.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-07-26 hardware diagnostics: every one of 7 field instances showed
``/api/database/countries`` as a dominant server-cost item (12-81% of total uptime),
the sole cause of the KPI board's "K2 interactive p95" red verdict everywhere. Root
cause: ``db.query(Source.country, Source.enabled, Source.tags).all()`` (the live
``_compute()`` in ``src.api.database.sources_by_country``) is a bare ``SCAN sources``
-- ``tags`` isn't covered by any index -- combined with a ``_cached`` wrapper gated on
``PRAGMA data_version``, which bumps on ANY write anywhere in the database, so the
30s TTL cache almost never actually serves a hit on an actively-collecting install.

Unlike :mod:`src.analytics.rollup_serve`/:mod:`src.analytics.map_serve` (DuckDB
columnar rollups, gated behind the optional ``[columnar]`` extra, needed because
their source data is genuinely large), this is a PLAIN in-memory Python dict --
``sources`` rows are few (hundreds-thousands, not millions), so a full rescan is
cheap, mirroring :func:`src.analytics.store.reconcile_source_counters`'s own
"CHEAP by design... no cursor/budget needed" reasoning for the closely-analogous
``Source.article_count`` counter. Refreshed UNCONDITIONALLY on the existing off-peak
``run_idle_maintenance`` cadence (``OO_MAINT_INTERVAL_S``, default 300s) -- no
change-token gating needed, since (unlike the DuckDB rollups) a full rebuild here is
cheap enough to just always do.

SAFE BY CONSTRUCTION: any miss/cold-start/bind-mismatch/stale-epoch/exception in
:func:`served` returns ``None`` and the caller falls straight back to the unmodified
live path -- the response is NEVER wrong, only sometimes not-yet-warm or up to the
refresh interval stale, and that staleness is disclosed via ``basis.as_of`` rather
than hidden.

BIND-AWARE (mirrors ``map_serve._same_bind``): a session on a DIFFERENT engine (a test
fixture, any ad-hoc connection) always falls back to live. Bind identity alone is
NOT enough, though (skeptic finding, 2026-07-26): a restore/merge disposes the pool
and atomically swaps the on-disk file (``src.backup.merge.run_restore``'s commit
stage) but keeps the SAME module-level ``Engine`` object, so ``session.get_bind() is
built_bind`` stays True for a corpus that has been entirely replaced. This module is
therefore ALSO CORPUS-EPOCH-AWARE (the canonical D3 double-count guard,
:mod:`src.analytics.corpus_epoch` -- restore-merge already bumps it): a rollup
records the epoch it was built at, and ``served()`` falls back to live whenever the
current epoch differs, exactly the pattern ``rollup_serve``/``columnar.py`` already
use for the DuckDB rollups.
"""

from __future__ import annotations

import copy
import threading
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy.orm import Session

_LOCK = threading.Lock()
_STATE: dict = {"payload": None, "bind": None, "built_at": None, "epoch": None}

# Matches OO_MAINT_INTERVAL_S's default (src.scheduler.runner) -- disclosed in basis()
# so a viewer knows the worst-case staleness; not itself an env-tunable knob here,
# since run_idle_maintenance's own throttle is the real cadence control.
_REFRESH_INTERVAL_S = 300


def _live_sources_by_country(session: Session) -> dict:
    """The exact live compute ``src.api.database.sources_by_country`` used to run on
    every request -- extracted verbatim so the live fallback and the rollup builder
    can never drift apart (the single source of truth for this payload's shape)."""
    from src.catalog.countries import ISO_3166_1_ALPHA2, continent_of, country_display_name
    from src.database.models import Source

    rows = session.query(Source.country, Source.enabled, Source.tags).all()
    per: dict[str, dict] = {}
    for country, enabled, tags in rows:
        cc = (country or "").strip().lower() or "(none)"
        slot = per.setdefault(cc, {"sources": 0, "enabled": 0, "tags": Counter()})
        slot["sources"] += 1
        if enabled:
            slot["enabled"] += 1
        for t in (tags or "").split(","):
            t = t.strip()
            if t:
                slot["tags"][t] += 1

    countries = [
        {
            "code": cc,
            "name": None if cc == "(none)" else country_display_name(cc),
            "region": None if cc == "(none)" else continent_of(cc),
            "sources": d["sources"],
            "enabled": d["enabled"],
            "top_tags": d["tags"].most_common(8),
        }
        for cc, d in per.items()
    ]
    countries.sort(key=lambda c: (-c["sources"], c["code"]))

    present = {cc for cc in per if cc != "(none)"}
    missing = sorted(c for c in ISO_3166_1_ALPHA2 if c not in present)
    return {
        "countries": countries,
        "covered": len(present),
        "total_countries": len(ISO_3166_1_ALPHA2),
        "missing": missing,
        "missing_names": {c: country_display_name(c) for c in missing},
        "missing_count": len(missing),
    }


def _same_bind(session: Session | None, built_bind) -> bool:
    """True only when ``session`` queries the SAME database the current rollup was
    built over (mirrors ``map_serve._same_bind``) -- a process-lifetime singleton
    must never answer for a database it was not built from."""
    if session is None or built_bind is None:
        return False
    try:
        return session.get_bind() is built_bind
    except Exception:  # noqa: BLE001 - any doubt -> live fallback
        return False


def _current_epoch(session: Session) -> int:
    """The corpus epoch, degrading to ``0`` (never-bumped) on any read failure --
    mirrors :func:`src.analytics.corpus_epoch.get_corpus_epoch`'s own degrade, and
    a failure here must never break ``refresh()``/``served()``."""
    try:
        from src.analytics.corpus_epoch import get_corpus_epoch

        return get_corpus_epoch(session)
    except Exception:  # noqa: BLE001 - a coordination read must never break its caller
        return 0


def refresh(session: Session) -> None:
    """Unconditional full rebuild -- called from ``run_idle_maintenance``, mirroring
    ``reconcile_source_counters``: sources are few, so no change-token gating is
    needed (unlike ``rollup_serve``/``map_serve``'s expensive DuckDB rebuilds, which
    need one to bound rebuild cost)."""
    payload = _live_sources_by_country(session)
    epoch = _current_epoch(session)
    with _LOCK:
        _STATE["payload"] = payload
        _STATE["bind"] = session.get_bind()
        _STATE["built_at"] = datetime.now(UTC)
        _STATE["epoch"] = epoch


def served(session: Session) -> dict | None:
    """The ``sources_by_country``-shaped payload served from the in-memory rollup, or
    ``None`` to fall back to the live query. ``None`` on: never built yet, a session
    bound to a DIFFERENT database, a corpus epoch bump since the rollup was built
    (a restore/re-index/prune -- see the module docstring), or any internal error --
    never a fabricated/wrong value (the docstring's contract; this function must
    itself never raise, so its whole body is guarded)."""
    try:
        with _LOCK:
            payload = _STATE["payload"]
            built_bind = _STATE["bind"]
            built_at = _STATE["built_at"]
            built_epoch = _STATE["epoch"]
        if payload is None or not _same_bind(session, built_bind):
            return None
        if built_epoch != _current_epoch(session):
            return None
        # A shallow dict(payload) would share the nested `countries`/`missing`/
        # `missing_names` containers with the singleton across EVERY caller until
        # the next refresh (skeptic finding, 2026-07-26): an in-place mutation by
        # any future caller (a diagnostics pass, an in-place .sort()) would
        # silently corrupt the process-global rollup for every other caller too.
        # Deep-copy the small payload so a returned response is always this
        # caller's own to mutate.
        out = copy.deepcopy(payload)
        out["basis"] = {
            "source": "rollup",
            "as_of": built_at.isoformat(timespec="seconds") if built_at else None,
            "refresh_interval_s": _REFRESH_INTERVAL_S,
        }
        return out
    except Exception:  # noqa: BLE001 - the documented contract: never raise, always fall back
        return None


def _reset_for_tests() -> None:
    """Drop the process-global rollup singleton (test hook) -- the SAME
    order-dependent-pollution class the write-gate/memory-guard/robots-cache/
    dedup-front autouse fixtures in tests/conftest.py already guard against: any
    test that calls ``refresh()`` against the shared real engine (e.g. an
    off-peak-maintenance wiring test) would otherwise leave a WARM rollup that a
    LATER, unrelated test sees via the SAME bind -- serving stale data instead of
    the fresh live compute that test expects (caught 2026-07-26:
    tests/test_database_api.py::test_countries_breakdown_counts_and_keywords
    failed only when preceded by tests/test_offpeak_maintenance.py, never alone)."""
    with _LOCK:
        _STATE["payload"] = None
        _STATE["bind"] = None
        _STATE["built_at"] = None
        _STATE["epoch"] = None
