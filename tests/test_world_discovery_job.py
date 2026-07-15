"""
Tests for the WORLD source-discovery background job (src/catalog/discover_job.py).

In-memory SQLite + injected run_query/session_factory/state_path — no network, runs
in CI. Covers: discovery over several countries (disabled rows + provenance), the
persisted RESUME cursor (skip done countries; survives a "restart"), cooperative
cancel, the clean airplane PAUSE (never an error), the consecutive-failure breaker
(a failed country is retried, never marked done), and restart=True. Plus a wiring
guard that COMPOSES the real routes (router prefix + decorator) and matches them
against the frontend caller — the slice-1c 404 lesson.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.discover_job import advance_world_discovery, load_state, run_world_discovery
from src.database.models import Base, Source
from src.ingest import activate_kill_switch, clear_kill_switch

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def scope(db):
    """A session factory that yields the SAME test session (never closes it)."""

    @contextmanager
    def _scope():
        yield db
        db.commit()

    return _scope


class _Ctx:
    """A stand-in JobContext: cooperative stop + recorded progress."""

    def __init__(self, stop_after: int | None = None):
        self.progress: list[dict] = []
        self._stop_after = stop_after  # flip .stopping after N progress reports
        self._stopped = False

    @property
    def stopping(self) -> bool:
        return self._stopped

    def set_progress(self, **kw):
        self.progress.append(kw)
        if self._stop_after is not None and len(self.progress) > self._stop_after:
            self._stopped = True


def _payload(name, website):
    return {"results": {"bindings": [
        {"itemLabel": {"value": name}, "website": {"value": website}},
    ]}}


def _rq_per_country(calls=None):
    """One distinct hit per country; records which countries were queried."""
    calls = calls if calls is not None else []

    def run_query(cc, type_qids):
        calls.append(cc)
        return _payload(f"Outlet {cc.upper()}", f"https://outlet-{cc}.example/")

    return run_query, calls


def test_discovers_all_countries_and_persists_cursor(db, scope, tmp_path):
    state_path = tmp_path / "wd.json"
    rq, calls = _rq_per_country()
    res = run_world_discovery(
        _Ctx(), countries=["ke", "ng"], run_query=rq,
        session_factory=scope, state_path=state_path, world_codes=["ke", "ng"], sleep_s=0,
    )
    assert res["complete"] is True
    assert res["countries_done"] == 2 and res["countries_remaining"] == 0
    assert res["added_this_run"] == 2 and res["added_total"] == 2
    for cc in ("ke", "ng"):
        src = db.query(Source).filter_by(domain=f"outlet-{cc}.example").one()
        assert src.enabled is False  # review-before-enable, always
        assert "via:wikidata-discovery" in (src.tags or "")
    st = json.loads(state_path.read_text("utf-8"))
    assert st["done"] == ["ke", "ng"] and st["added_total"] == 2
    assert st.get("completed_at")  # done covers world_codes -> the world stamp


def test_a_subset_run_never_marks_the_world_complete(db, scope, tmp_path):
    """The interaction hazard the ride-along depends on: a manual job over a SUBSET
    must not set the world completed_at stamp, or the background ride-along would
    silently stop for the other ~240 countries."""
    state_path = tmp_path / "wd.json"
    rq, _calls = _rq_per_country()
    res = run_world_discovery(
        _Ctx(), countries=["ke", "ng"], run_query=rq,
        session_factory=scope, state_path=state_path, sleep_s=0,  # real world_codes
    )
    assert res["complete"] is True  # the requested subset IS done…
    assert not load_state(state_path).get("completed_at")  # …but the world is not


def test_resume_skips_countries_already_done(db, scope, tmp_path):
    state_path = tmp_path / "wd.json"
    state_path.write_text(json.dumps({"done": ["ke"], "added_total": 5}), "utf-8")
    rq, calls = _rq_per_country()
    res = run_world_discovery(
        _Ctx(), countries=["ke", "ng"], run_query=rq,
        session_factory=scope, state_path=state_path, sleep_s=0,
    )
    assert "ke" not in calls and "ng" in calls  # the cursor skipped ke
    assert res["complete"] is True
    assert res["added_total"] == 6  # 5 carried + 1 new


def test_restart_ignores_the_cursor(db, scope, tmp_path):
    state_path = tmp_path / "wd.json"
    state_path.write_text(json.dumps({"done": ["ke", "ng"], "added_total": 5}), "utf-8")
    rq, calls = _rq_per_country()
    res = run_world_discovery(
        _Ctx(), countries=["ke", "ng"], restart=True, run_query=rq,
        session_factory=scope, state_path=state_path, sleep_s=0,
    )
    assert sorted(set(calls)) == ["ke", "ng"]  # everything re-queried
    assert res["complete"] is True and res["added_total"] == 2  # fresh tallies


def test_cancel_stops_between_countries_and_saves_progress(db, scope, tmp_path):
    state_path = tmp_path / "wd.json"
    rq, calls = _rq_per_country()
    # stop after the first country's progress report (the "starting…" report is #1)
    res = run_world_discovery(
        _Ctx(stop_after=1), countries=["ke", "ng", "br"], run_query=rq,
        session_factory=scope, state_path=state_path, sleep_s=0,
    )
    assert res["complete"] is False
    assert "cancelled" in res["paused_reason"]
    assert res["countries_done"] == 1 and res["countries_remaining"] == 2
    assert load_state(state_path)["done"] == ["ke"]  # resumable


def test_airplane_mode_pauses_cleanly_without_error(db, scope, tmp_path):
    state_path = tmp_path / "wd.json"
    rq, calls = _rq_per_country()
    activate_kill_switch()
    try:
        res = run_world_discovery(
            _Ctx(), countries=["ke", "ng"], run_query=rq,
            session_factory=scope, state_path=state_path, sleep_s=0,
        )
    finally:
        clear_kill_switch()
    assert calls == []  # no query attempted offline
    assert res["complete"] is False
    assert "airplane" in res["paused_reason"]
    assert res["errors"] == []  # a user choice is never an "error"


def test_failed_country_is_retried_and_breaker_stops_a_dead_network(db, scope, tmp_path):
    state_path = tmp_path / "wd.json"

    def rq(cc, type_qids):
        raise OSError("connection refused")

    res = run_world_discovery(
        _Ctx(), countries=["ke", "ng", "br", "fr", "de", "jp", "us"], run_query=rq,
        session_factory=scope, state_path=state_path, sleep_s=0,
    )
    assert res["complete"] is False
    assert "consecutive failed countries" in res["paused_reason"]
    assert load_state(state_path).get("done", []) == []  # nothing falsely marked done
    assert res["countries_done"] == 0
    assert any("connection refused" in e for e in res["errors"])


def test_all_specs_failed_country_is_not_marked_done(db, scope, tmp_path):
    """generate_catalog records per-query failures instead of raising — a country whose
    EVERY query errored must be retried next run, never silently marked done."""
    state_path = tmp_path / "wd.json"
    attempts: list[str] = []

    def rq(cc, type_qids):
        attempts.append(cc)
        if cc == "ke":
            raise OSError("timeout")  # recorded by generate_catalog, not raised to us
        return _payload(f"Outlet {cc.upper()}", f"https://outlet-{cc}.example/")

    res = run_world_discovery(
        _Ctx(), countries=["ke", "ng"], run_query=rq,
        session_factory=scope, state_path=state_path, sleep_s=0,
    )
    done = load_state(state_path).get("done", [])
    assert "ng" in done and "ke" not in done
    assert res["complete"] is False and res["countries_remaining"] == 1
    assert any("timeout" in e for e in res["errors"])


# --------------------------------------------------------------------------- #
# The scheduler RIDE-ALONG (maintainer ruled 2026-07-15 "background and automated"):
# a bounded per-pass advance of the same persisted cursor.
# --------------------------------------------------------------------------- #

def test_bounded_pass_advances_and_never_stamps_completion(db, scope, tmp_path):
    state_path = tmp_path / "wd.json"
    rq, calls = _rq_per_country()
    res = run_world_discovery(
        _Ctx(), countries=["ke", "ng", "br"], max_countries=1, run_query=rq,
        session_factory=scope, state_path=state_path, world_codes=["ke", "ng", "br"], sleep_s=0,
    )
    assert calls == ["ke"] * len(calls) and res["countries_done"] == 1  # one country only
    assert res["complete"] is False and "paused_reason" not in res  # a clean bounded end
    assert not load_state(state_path).get("completed_at")
    # the next bounded pass CONTINUES from the cursor
    res2 = run_world_discovery(
        _Ctx(), countries=["ke", "ng", "br"], max_countries=1, run_query=rq,
        session_factory=scope, state_path=state_path, world_codes=["ke", "ng", "br"], sleep_s=0,
    )
    assert res2["countries_done"] == 2 and load_state(state_path)["done"] == ["ke", "ng"]


def test_advance_world_discovery_budget_and_skips(db, scope, tmp_path):
    state_path = tmp_path / "wd.json"
    rq, calls = _rq_per_country()
    # budget 0 = the off switch: nothing touched, no state file created
    assert advance_world_discovery(per_pass=0, state_path=state_path) == {"enabled": False}
    assert not state_path.exists()
    # airplane mode = an honest skip, no query
    activate_kill_switch()
    try:
        out = advance_world_discovery(
            per_pass=2, run_query=rq, session_factory=scope, state_path=state_path, sleep_s=0,
        )
    finally:
        clear_kill_switch()
    assert out["skipped"] == "airplane mode engaged" and calls == []
    # a normal pass advances per_pass countries through the SAME cursor — over the
    # REAL world list (alphabetical ISO-2: ad, ae, …), the production default
    out = advance_world_discovery(
        per_pass=2, run_query=rq, session_factory=scope, state_path=state_path, sleep_s=0,
    )
    assert out["enabled"] is True and out["countries_done"] == 2
    assert load_state(state_path)["done"] == ["ad", "ae"]
    # a completed world = an honest skip (restart=1 on the manual endpoint re-runs)
    st = load_state(state_path)
    st["completed_at"] = "2026-07-15T00:00:00+00:00"
    state_path.write_text(json.dumps(st), "utf-8")
    out = advance_world_discovery(
        per_pass=2, run_query=rq, session_factory=scope, state_path=state_path, sleep_s=0,
    )
    assert out["skipped"] == "world discovery already complete"


def test_advance_skips_while_the_manual_job_is_running(db, scope, tmp_path):
    """Never two writers on the same cursor: the ride-along yields to the manual job."""
    import threading

    from src.jobs.background import BackgroundJob, get_job, register_job

    release = threading.Event()
    prior = get_job("discover-world-sources")
    register_job(BackgroundJob(
        "discover-world-sources", "T", lambda ctx: release.wait(5), cancellable=True,
    ))
    try:
        job = get_job("discover-world-sources")
        job.start()
        rq, calls = _rq_per_country()
        out = advance_world_discovery(
            per_pass=2, run_query=rq, session_factory=scope,
            state_path=tmp_path / "wd.json", sleep_s=0,
        )
        assert out["skipped"] == "the manual world-discovery job is running"
        assert calls == []
    finally:
        release.set()
        if prior is not None:
            register_job(prior)  # restore whatever was registered before


def test_scheduler_ride_along_wiring_and_setting():
    """Source-level guard: the runner advances the cursor under the new setting, the
    setting exists with the ruled default (2, 0=off, ranged), and the config API
    exposes it — so the 'background and automated' ruling cannot silently regress."""
    runner_src = (_ROOT / "src" / "scheduler" / "runner.py").read_text("utf-8")
    settings_src = (_ROOT / "src" / "scheduler" / "settings.py").read_text("utf-8")
    api_src = (_ROOT / "src" / "api" / "scheduler.py").read_text("utf-8")

    assert "advance_world_discovery(per_pass=settings.world_discovery_per_pass)" in runner_src
    assert "world_discovery_per_pass: int = 2" in settings_src  # default ON (the ruling)
    assert '_ranged("world_discovery_per_pass", 0, 12' in settings_src  # 0 = the off switch
    assert 'raw.get("world_discovery_per_pass")' in settings_src  # persisted round-trip
    assert "world_discovery_per_pass: int | None = None" in api_src  # PUT /config parity

    from src.scheduler.settings import SchedulerSettings

    assert SchedulerSettings().world_discovery_per_pass == 2


# --------------------------------------------------------------------------- #
# Wiring guard (the slice-1c 404 lesson): COMPOSE the backend routes from the
# router prefix + decorators and require the frontend to call exactly those.
# --------------------------------------------------------------------------- #

def test_world_discovery_wiring_composes_end_to_end():
    api_src = (_ROOT / "src" / "api" / "diagnostics.py").read_text("utf-8")
    js_src = (_ROOT / "src" / "static" / "app.js").read_text("utf-8")
    html_src = (_ROOT / "src" / "static" / "index.html").read_text("utf-8")

    prefix = re.search(r'APIRouter\(prefix="([^"]+)"', api_src).group(1)
    decorated = set(re.findall(r'@router\.(?:get|post)\("(/discover-world[^"]*)"\)', api_src))
    backend_routes = {prefix + d for d in decorated}
    assert backend_routes == {
        "/api/diagnostics/discover-world",
        "/api/diagnostics/discover-world/status",
        "/api/diagnostics/discover-world/cancel",
    }

    frontend_routes = set(re.findall(r'"(/api/diagnostics/discover-world[^"?]*)"', js_src))
    assert frontend_routes, "the frontend must call the world-discovery endpoints"
    assert frontend_routes - backend_routes == set()  # every JS call hits a real route

    # the Diagnostics panel wires the button + status line, consent-gated
    assert 'onclick="discoverWorld(this)"' in html_src
    assert 'id="discover-world-status"' in html_src
    assert "ensureOnline" in js_src.split("async function discoverWorld", 1)[1][:1500]

    # the worker is a cooperatively-cancellable, WRITER background job
    assert '"discover-world-sources"' in api_src
    assert "cancellable=True" in api_src.split('"discover-world-sources"', 1)[1][:400]
