"""
WORLD source discovery as a background job — the whole-planet automation of the
in-app Wikidata discovery (maintainer-asked 2026-07-15: ~3,000 catalog sources
"is a minimal start … should be significantly increased").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The bounded ``POST /api/diagnostics/discover-sources`` endpoint (12 countries per
synchronous call) cannot honestly cover ~250 countries; this worker walks EVERY
requested country through the SAME :func:`src.catalog.discover.discover_sources`
machinery, one country at a time, as a cancellable :class:`BackgroundJob`:

* every insert stays a DISABLED ``Source`` row with ``via:wikidata-discovery``
  provenance — review-before-enable, never auto-scraped (the standing ruling);
* each country runs in its OWN session (the writer gate is taken per country for
  the insert batch only, never held across a network fetch);
* progress is a PERSISTED CURSOR (``data_dir()/world_discovery.json``): countries
  already completed are skipped on the next start, so a cancel / crash / airplane
  pause resumes instead of re-querying the world (dedup-by-domain makes a re-query
  merely wasteful, never wrong — the cursor is an efficiency net, not the
  correctness net);
* the kill switch PAUSES the run cleanly between countries (an engaged airplane
  mode is a user choice, never an "error"); the cursor makes the pause resumable;
* a country whose every query failed is NOT marked done (it is retried on the next
  start), and a run stops honestly after several CONSECUTIVE all-failed countries
  (total network loss must not spin through 200 doomed queries).

No score anywhere; per-country tallies are counts. The transport underneath is the
guarded factory (kill switch + proxy + per-country circuit isolation) exactly as
the bounded endpoint uses — this module adds orchestration, never a fetch path.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

_LOG = logging.getLogger(__name__)

_STATE_FILENAME = "world_discovery.json"
_MAX_CONSECUTIVE_FAILURES = 5  # all-specs-failed countries in a row before an honest stop
_MAX_RECORDED_ERRORS = 30  # keep the newest N error strings in the state file


def _default_state_path() -> Path:
    from src.paths import data_dir

    return data_dir() / _STATE_FILENAME


def load_state(state_path: Path | None = None) -> dict:
    """The persisted cursor ({} when no run ever happened / the file is unreadable)."""
    p = state_path or _default_state_path()
    try:
        data = json.loads(p.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - a missing/corrupt cursor just means "start fresh"
        return {}


def _save_state(state: dict, state_path: Path) -> None:
    """Atomic write (tmp + os.replace) so a crash mid-save never corrupts the cursor."""
    tmp = state_path.with_name(state_path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), "utf-8")
    os.replace(tmp, state_path)


def all_country_codes() -> list[str]:
    """Every ISO 3166-1 alpha-2 code, lowercase, sorted — the default 'world' list."""
    from src.catalog.countries import ISO_3166_1_ALPHA2

    return sorted(ISO_3166_1_ALPHA2)


def _country_failed_entirely(result: dict) -> bool:
    """True when EVERY query for the country errored (nothing parsed, errors recorded).

    ``generate_catalog`` records per-query failures instead of raising, so a total
    network loss surfaces as errors + zero raw entries — that country must be
    retried later, not marked done. A country with SOME successful specs (partial
    errors) still counts as done; its errors ride in the state for honesty.

    NB ``discover_sources`` SPREADS the generate_catalog stats into the top level of
    its return value (``{"added": …, **result["stats"]}``) — read them there.
    """
    return bool(result.get("errors")) and int(result.get("raw_entries") or 0) == 0


def run_world_discovery(
    ctx,
    *,
    countries: Iterable[str] | None = None,
    per_spec_limit: int | None = None,
    restart: bool = False,
    max_countries: int | None = None,
    run_query=None,
    session_factory=None,
    state_path: Path | None = None,
    world_codes: list[str] | None = None,
    sleep_s: float = 1.0,
) -> dict:
    """Walk the requested countries (default: the whole world) through
    :func:`discover_sources`, persisting a resume cursor per country.

    ``ctx`` is the :class:`src.jobs.background.JobContext` (cooperative stop +
    progress). ``max_countries`` bounds ONE call (the scheduler ride-along's
    per-pass budget) — a bounded call ends cleanly with ``complete: False`` and
    the cursor advanced. ``run_query`` / ``session_factory`` / ``state_path`` /
    ``world_codes`` / ``sleep_s`` are test seams; production uses the guarded
    WDQS transport, the app's ``session_scope`` and ``data_dir()``. Returns an
    honest summary — ``complete`` is True only when every requested country is
    done; a pause names its reason. The persisted ``completed_at`` stamp is set
    only when the WHOLE WORLD is done (a subset run must never mark the world
    complete — the ride-along reads that stamp to know when to stop).
    """
    from src.catalog.discover import discover_sources
    from src.ingest import kill_switch_active

    if session_factory is None:
        from src.database.session import session_scope

        session_factory = session_scope

    path = state_path or _default_state_path()
    codes = [c.strip().lower() for c in (countries or all_country_codes()) if c and c.strip()]
    state = {} if restart else load_state(path)
    done: set[str] = {str(c).lower() for c in state.get("done", [])}
    per_country: dict[str, int] = dict(state.get("per_country", {}))
    errors: list[str] = list(state.get("errors", []))
    added_total = int(state.get("added_total", 0))
    if not state.get("started_at"):
        state["started_at"] = datetime.now(UTC).isoformat(timespec="seconds")

    total = len(codes)
    done_in_run = sum(1 for c in codes if c in done)
    added_this_run = 0
    processed = 0  # countries attempted THIS call (the max_countries budget)
    paused_reason: str | None = None
    consecutive_failures = 0

    ctx.set_progress(done=done_in_run, total=total, detail="starting…")

    for cc in codes:
        if cc in done:
            continue
        if max_countries is not None and processed >= max_countries:
            break  # the per-pass budget is spent — a clean bounded end, not a pause
        processed += 1
        if ctx.stopping:
            paused_reason = "cancelled — progress is saved; start again to resume"
            break
        if kill_switch_active():
            paused_reason = "airplane mode engaged — progress is saved; start again to resume"
            break
        try:
            with session_factory() as db:
                result = discover_sources(
                    db, [cc], run_query=run_query, per_spec_limit=per_spec_limit
                )
        except RuntimeError as exc:
            if "airplane" in str(exc):  # the kill switch raced the loop check
                paused_reason = "airplane mode engaged — progress is saved; start again to resume"
                break
            errors.append(f"{cc}: {exc}"[:200])
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                paused_reason = (
                    f"stopped after {consecutive_failures} consecutive failed countries "
                    "— is the network reachable? Progress is saved; start again to resume"
                )
                break
            continue
        except Exception as exc:  # noqa: BLE001 - one country must never abort the world
            errors.append(f"{cc}: {type(exc).__name__}: {exc}"[:200])
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                paused_reason = (
                    f"stopped after {consecutive_failures} consecutive failed countries "
                    "— is the network reachable? Progress is saved; start again to resume"
                )
                break
            continue

        for err in result.get("errors") or []:  # per-spec failures (stats spread top-level)
            errors.append(str(err)[:200])
        if _country_failed_entirely(result):
            # nothing parsed + every query errored: retry this country next run
            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                paused_reason = (
                    f"stopped after {consecutive_failures} consecutive failed countries "
                    "— is the network reachable? Progress is saved; start again to resume"
                )
                break
            continue

        consecutive_failures = 0
        added = int(result.get("added") or 0)
        added_total += added
        added_this_run += added
        done.add(cc)
        done_in_run += 1
        per_country[cc] = added
        state.update(
            {
                "done": sorted(done),
                "per_country": per_country,
                "added_total": added_total,
                "errors": errors[-_MAX_RECORDED_ERRORS:],
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        _save_state(state, path)
        ctx.set_progress(
            done=done_in_run,
            total=total,
            detail=f"{cc}: +{added} new disabled sources · {added_total} total",
        )
        if sleep_s and done_in_run < total:
            time.sleep(sleep_s)  # politeness between countries (specs already ran serially)

    complete = all(c in done for c in codes)
    # The persisted stamp means THE WORLD is done — never a requested subset (a
    # subset job run must not stop the background ride-along for the other ~240
    # countries). world_codes is the test seam for this computation only.
    world = world_codes or all_country_codes()
    if all(c in done for c in world):
        state["completed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    state.update(
        {
            "done": sorted(done),
            "per_country": per_country,
            "added_total": added_total,
            "errors": errors[-_MAX_RECORDED_ERRORS:],
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    _save_state(state, path)

    summary = {
        "countries_requested": total,
        "countries_done": done_in_run,
        "countries_remaining": total - done_in_run,
        "added_this_run": added_this_run,
        "added_total": added_total,
        "complete": complete,
        "errors": errors[-_MAX_RECORDED_ERRORS:],
        "note": (
            "New sources are DISABLED for review in Settings → Sources — "
            "nothing is scraped until you enable it."
        ),
    }
    if paused_reason:
        summary["paused_reason"] = paused_reason
    return summary


class _NullCtx:
    """A no-op JobContext for the scheduler ride-along (no stop event, no display)."""

    stopping = False

    def set_progress(self, **_kw) -> None:  # noqa: D401 - interface parity
        return None


def advance_world_discovery(
    *,
    per_pass: int,
    run_query=None,
    session_factory=None,
    state_path: Path | None = None,
    world_codes: list[str] | None = None,
    sleep_s: float = 1.0,
) -> dict:
    """The scheduler RIDE-ALONG (maintainer ruled 2026-07-15: source scraping/discovery
    should be "background and automated"): advance the persisted world-discovery cursor
    a bounded number of countries per online collection pass, through the same guarded
    transport the pass itself uses. AUTOMATION COVERS DISCOVERY, NEVER ENABLING — every
    find stays a DISABLED source for review (the standing review-before-enable ruling).

    Skips honestly (each skip named in the returned dict) when: the budget is 0 (the
    off switch, ``world_discovery_per_pass=0``), airplane mode is engaged, the MANUAL
    world-discovery job is running (never two writers on the same cursor), or the world
    is already complete (the ``completed_at`` stamp; ``restart=1`` on the manual
    endpoint re-runs). Best-effort by contract — the caller wraps it so a failure never
    breaks a scrape.
    """
    if per_pass <= 0:
        return {"enabled": False}
    from src.ingest import kill_switch_active

    if kill_switch_active():
        return {"enabled": True, "skipped": "airplane mode engaged"}
    from src.jobs.background import get_job

    job = get_job("discover-world-sources")
    if job is not None and job.status().get("running"):
        return {"enabled": True, "skipped": "the manual world-discovery job is running"}
    state = load_state(state_path)
    if state.get("completed_at"):
        return {
            "enabled": True,
            "skipped": "world discovery already complete",
            "added_total": state.get("added_total", 0),
        }
    return {
        "enabled": True,
        **run_world_discovery(
            _NullCtx(),
            max_countries=per_pass,
            run_query=run_query,
            session_factory=session_factory,
            state_path=state_path,
            world_codes=world_codes,
            sleep_s=sleep_s,
        ),
    }
