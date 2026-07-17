"""No per-run source cap: collection covers EVERY source (maintainer 2026-06-13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A cap silently selects which sources to skip, which cannot be justified. The
setting now defaults to 0 = UNBOUNDED; a positive value is honoured as an
explicit soft cap. SQLite ``LIMIT 0`` returns nothing, so ``capped`` guards it.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.database.query import capped
from src.scheduler.runner import plan_preview
from src.scheduler.settings import SchedulerSettings, _coerce_int, load_settings, save_settings


def _db_with_sources(n: int):
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    for i in range(n):
        s.add(Source(name=f"S{i}", domain=f"s{i}.test", enabled=True, priority=i))
    s.commit()
    return s


def test_capped_zero_is_unbounded():
    s = _db_with_sources(5)
    assert capped(s.query(Source), 0).count() == 5  # 0 = all, NOT SQLite LIMIT 0
    assert capped(s.query(Source), None).count() == 5
    assert capped(s.query(Source), -1).count() == 5


def test_capped_positive_is_a_soft_cap():
    s = _db_with_sources(5)
    assert capped(s.query(Source), 2).count() == 2


def test_default_settings_have_no_cap():
    assert SchedulerSettings().max_sources_per_run == 0


def test_coercion_allows_zero_unbounded():
    # The old clamp was [1, 1000] -- it could neither express "unbounded" (0)
    # nor cover more than 1000 sources. Now 0 is allowed and the ceiling is high.
    assert _coerce_int(0, 0, 0, 1_000_000) == 0
    assert _coerce_int(50000, 0, 0, 1_000_000) == 50000


def test_save_settings_accepts_max_sources_per_run_zero_and_above_1000():
    """Audit finding 2026-07-17: save_settings's own range validator for
    max_sources_per_run was still `1, 1000` even though the field is documented
    + tested (this file) as "0 = UNBOUNDED -- the default", and load_settings
    (above) already coerces it with bounds (0, 1_000_000). A client could never
    explicitly PUT {"max_sources_per_run": 0} to reset the cap back to
    unbounded via the API, and could never set a cap above 1000 either -- a
    real regression against the maintainer's own no-source-cap ruling."""
    save_settings({"max_sources_per_run": 5})
    assert load_settings().max_sources_per_run == 5

    save_settings({"max_sources_per_run": 0})  # must NOT raise -- resets to unbounded
    assert load_settings().max_sources_per_run == 0

    save_settings({"max_sources_per_run": 50000})  # above the old stale 1000 ceiling
    assert load_settings().max_sources_per_run == 50000

    save_settings({"max_sources_per_run": 0})  # restore the default for later tests
    assert load_settings().max_sources_per_run == 0


def test_plan_preview_covers_every_source_when_uncapped():
    s = _db_with_sources(7)
    plan = plan_preview(s, SchedulerSettings(mode="rss", max_sources_per_run=0), last_result=None)
    assert plan["planned_total"] == 7  # every enabled source, no selection


def test_plan_preview_honours_an_explicit_soft_cap():
    s = _db_with_sources(7)
    plan = plan_preview(s, SchedulerSettings(mode="rss", max_sources_per_run=3), last_result=None)
    assert plan["planned_total"] == 3


def test_plan_preview_bounds_the_materialised_sample(monkeypatch):
    """Field perf 2026-06-17: /api/scheduler/activity was the #1 endpoint by
    server time because this preview loaded the WHOLE enabled-source set on every
    poll. It must report the TRUE total (a cheap COUNT) but only materialise a
    BOUNDED sample for its 8 preview domains + the representative delay."""
    import src.scheduler.runner as runner

    s = _db_with_sources(300)  # well over the sample bound
    seen: dict[str, int] = {}
    original = runner.stratified_interleave

    def _spy(rows, **kw):
        seen["n"] = len(rows)
        return original(rows, **kw)

    monkeypatch.setattr(runner, "stratified_interleave", _spy)
    plan = plan_preview(s, SchedulerSettings(mode="rss", max_sources_per_run=0), last_result=None)

    assert plan["planned_total"] == 300  # the honest total (no cap), via COUNT
    assert seen["n"] <= runner._PLAN_PREVIEW_SAMPLE  # only a bounded sample built
    assert seen["n"] < 300  # NOT the whole set
    assert len(plan["next_targets"]) == 8  # still a full 8-domain preview
    # estimate still uses the TRUE total: 300 sources × 2.0s default politeness
    # delay (Source.rate_limit_ms defaults to 2000ms) × 1 fetch each = 600s.
    assert plan["estimated_seconds"] == 600
