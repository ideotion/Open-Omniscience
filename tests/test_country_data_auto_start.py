"""COUNTRY-DATA scheduler ride-along (2026-07-24 field-feedback Session A §2, ruled):
the Governments tab must not depend on the user first clicking "Load standard country
data" -- ``advance_country_data`` bootstraps a few never-yet-fetched curated World-Bank
indicators per online pass, mirroring the world-discovery/qualification ride-along
pattern (``advance_world_discovery``/``advance_qualification``).

``_fetch_and_store_indicator`` (the fetch+store+subscribe helper SHARED by the manual
``/load-standard`` job and this ride-along) is monkeypatched here so no network/real
store I/O runs -- the point is the RIDE-ALONG'S OWN decision logic (pending selection,
honest skips, the shared-helper call), not the underlying World Bank fetch (already
covered by ``tests/test_stats_fetch.py``/``tests/test_a2_job_endpoints.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api import governments
from src.database.models import Base, StatSubscription
from src.ingest import activate_kill_switch, clear_kill_switch
from src.stats import indicators as ind

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _clean_kill_switch():
    clear_kill_switch()
    yield
    clear_kill_switch()


@pytest.fixture(autouse=True)
def _idle_gov_job():
    """Never let a leftover real _GOV_JOB state bleed between tests."""
    governments._GOV_JOB.cancel()
    if governments._GOV_JOB._thread is not None:
        governments._GOV_JOB._thread.join(2)
    yield
    governments._GOV_JOB.cancel()
    if governments._GOV_JOB._thread is not None:
        governments._GOV_JOB._thread.join(2)


# --------------------------------------------------------------------------- #
# The indicator catalog itself (§2: "extend ... with as many items as possible").
# --------------------------------------------------------------------------- #


def test_indicator_catalog_is_expanded_and_internally_sound():
    ids = ind.indicator_ids()
    assert len(ids) >= 30, "the catalog must be meaningfully larger than the original 12"
    assert len(ids) == len(set(ids)), "no duplicate World Bank codes"
    for meta in ind.INDICATOR_CATALOG:
        assert meta["id"] and meta["label"] and meta["unit"] and meta["category"]
        # a plausible WB series-code SHAPE (dot-separated segments); catches an
        # obviously-malformed id without asserting any specific code list.
        assert "." in meta["id"] and meta["id"] == meta["id"].strip()
    assert ind.CATALOG_REVISED == "2026-07"


# --------------------------------------------------------------------------- #
# advance_country_data: honest skips.
# --------------------------------------------------------------------------- #


def test_disabled_at_zero_budget(db):
    assert governments.advance_country_data(db, per_pass=0) == {"enabled": False}


def test_skips_while_a_manual_load_is_running(db, monkeypatch):
    monkeypatch.setattr(governments._GOV_JOB, "status", lambda: {"state": "running"})
    out = governments.advance_country_data(db, per_pass=2)
    assert out == {"enabled": True, "skipped": "a manual load is already running"}


def test_skips_under_airplane_mode(db):
    activate_kill_switch()
    out = governments.advance_country_data(db, per_pass=2)
    assert out == {"enabled": True, "skipped": "airplane mode"}


def test_skips_once_the_whole_catalog_is_bootstrapped(db):
    for code in ind.indicator_ids():
        db.add(StatSubscription(source="worldbank", indicator=code, country="all"))
    db.commit()
    out = governments.advance_country_data(db, per_pass=2)
    assert out == {"enabled": True, "skipped": "the whole catalog is already bootstrapped"}


# --------------------------------------------------------------------------- #
# advance_country_data: the happy-path bootstrap, via the SHARED helper.
# --------------------------------------------------------------------------- #


def test_bootstraps_only_never_yet_subscribed_indicators_in_catalog_order(db, monkeypatch):
    ids = ind.indicator_ids()
    already = ids[0]  # pretend this one was already fetched (manually, earlier)
    db.add(StatSubscription(source="worldbank", indicator=already, country="all"))
    db.commit()

    calls: list[str] = []

    def fake_fetch(session, code):
        assert session is db
        calls.append(code)
        return {"indicator": code, "status": "ok", "fetched": 3, "stored": 3, "duplicates": 0}

    monkeypatch.setattr(governments, "_fetch_and_store_indicator", fake_fetch)
    out = governments.advance_country_data(db, per_pass=2)

    # the already-subscribed indicator is skipped; the next two IN CATALOG ORDER run
    assert calls == [ids[1], ids[2]]
    assert out["enabled"] is True and out["started"] is True
    assert out["fetched"] == 6 and out["stored"] == 6
    assert [p["indicator"] for p in out["per_indicator"]] == calls


def test_a_single_indicators_failure_is_recorded_and_never_breaks_the_pass(db, monkeypatch):
    calls: list[str] = []

    def flaky_fetch(session, code):
        calls.append(code)
        if len(calls) == 1:
            return {"indicator": code, "status": "error", "detail": "transport failed"}
        return {"indicator": code, "status": "ok", "fetched": 1, "stored": 1}

    monkeypatch.setattr(governments, "_fetch_and_store_indicator", flaky_fetch)
    out = governments.advance_country_data(db, per_pass=2)

    assert len(calls) == 2, "one indicator's failure must not stop the rest of this pass"
    statuses = [p["status"] for p in out["per_indicator"]]
    assert statuses == ["error", "ok"]
    assert out["fetched"] == 1 and out["stored"] == 1  # only the ok one counted


def test_airplane_engaged_mid_loop_stops_the_rest_of_the_batch(db, monkeypatch):
    """A concurrent kill-switch flip mid-pass surfaces as a RuntimeError from the shared
    helper (the same signal ``/load-standard`` treats as "stop, don't fabricate more
    fetches") -- the ride-along must honour it the same way."""
    calls: list[str] = []

    def racing_fetch(session, code):
        calls.append(code)
        if len(calls) == 1:
            return {"indicator": code, "status": "ok", "fetched": 1, "stored": 1}
        raise RuntimeError("network refused: airplane mode is engaged")

    monkeypatch.setattr(governments, "_fetch_and_store_indicator", racing_fetch)
    out = governments.advance_country_data(db, per_pass=5)

    assert len(calls) == 2, "no fetch after the refusal -- every later one would refuse too"
    assert out["per_indicator"][-1]["status"] == "refused"


def test_bounded_pass_advances_across_calls_never_refetching_a_bootstrapped_indicator(db, monkeypatch):
    """Two consecutive bounded ride-along passes cover distinct indicators -- the
    per-indicator StatSubscription IS the persisted cursor (no separate cursor file)."""
    ids = ind.indicator_ids()
    calls: list[str] = []

    def fake_fetch(session, code):
        calls.append(code)
        session.add(StatSubscription(source="worldbank", indicator=code, country="all"))
        return {"indicator": code, "status": "ok", "fetched": 1, "stored": 1}

    monkeypatch.setattr(governments, "_fetch_and_store_indicator", fake_fetch)
    governments.advance_country_data(db, per_pass=2)
    assert calls == ids[:2]

    governments.advance_country_data(db, per_pass=2)
    assert calls == ids[:4], "the second pass must continue from where the first left off"


# --------------------------------------------------------------------------- #
# Scheduler wiring (the world-discovery precedent test): the ride-along must be
# actually reachable from a normal online pass, under the ruled default.
# --------------------------------------------------------------------------- #


def test_scheduler_ride_along_wiring_and_setting():
    runner_src = (_ROOT / "src" / "scheduler" / "runner.py").read_text("utf-8")
    settings_src = (_ROOT / "src" / "scheduler" / "settings.py").read_text("utf-8")
    api_src = (_ROOT / "src" / "api" / "scheduler.py").read_text("utf-8")

    assert "advance_country_data(session, per_pass=settings.country_data_per_pass)" in runner_src
    assert "country_data_per_pass: int = 2" in settings_src  # default ON (the ruling)
    assert '_ranged("country_data_per_pass", 0, 100' in settings_src  # 0 = the off switch
    assert 'raw.get("country_data_per_pass")' in settings_src  # persisted round-trip
    assert "country_data_per_pass: int | None = None" in api_src  # PUT /config parity

    from src.scheduler.settings import SchedulerSettings

    assert SchedulerSettings().country_data_per_pass == 2


def test_advance_country_data_shares_the_fetch_helper_with_load_standard():
    """A source-level guard against silent drift: the manual job and the ride-along
    must keep calling the SAME helper, or the two paths could quietly diverge."""
    src = (_ROOT / "src" / "api" / "governments.py").read_text("utf-8")
    assert src.count("_fetch_and_store_indicator(") >= 3  # def + 2 call sites (manual + ride-along)
    assert "rec = _fetch_and_store_indicator(db, code)" in src  # the manual worker
    assert "rec = _fetch_and_store_indicator(session, code)" in src  # the ride-along
