"""
The collection-activity surface: per-host rates, run progress, plan preview.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled (2026-06-10): the activity chip opens a detailed collection
view — live progress (domains only), upcoming targets, an honest duration
estimate with its method stated, and per-source transfer rates measured from
the app's OWN responses (never OS-wide counters).
"""

from __future__ import annotations

from src.monitoring.activity import ActivityMonitor
from src.scheduler.runner import _progress_set, current_progress, plan_preview
from src.scheduler.settings import SchedulerSettings


# --------------------------------------------------------------------------- #
#  Per-host transfer rates (app-attributed, honest)
# --------------------------------------------------------------------------- #
def test_per_host_rates_from_own_fetches():
    m = ActivityMonitor()
    m.fetch_started("https://alpha.test/feed.xml")
    m.fetch_bytes(102400)  # 100 KB while alpha.test is in flight
    m.fetch_finished()
    m.fetch_started("https://beta.test/page")
    m.fetch_bytes(51200)
    m.fetch_finished()
    rates = m.per_host_rates()
    hosts = {r["host"] for r in rates}
    assert hosts == {"alpha.test", "beta.test"}
    alpha = next(r for r in rates if r["host"] == "alpha.test")
    assert alpha["bytes"] == 102400 and alpha["fetches"] == 1 and alpha["kbps"] > 0


def test_per_host_rates_empty_when_nothing_fetched():
    assert ActivityMonitor().per_host_rates() == []  # never a fabricated number


# --------------------------------------------------------------------------- #
#  Run progress snapshot (module-level, one run at a time by design)
# --------------------------------------------------------------------------- #
def test_progress_set_and_clear():
    _progress_set(_clear=True)
    assert current_progress() is None
    _progress_set(mode="rss", total=4, done=0, current=None, pages=0)
    _progress_set(current="alpha.test", done=2, pages=7)
    p = current_progress()
    assert p == {"mode": "rss", "total": 4, "done": 2, "current": "alpha.test", "pages": 7}
    _progress_set(_clear=True)
    assert current_progress() is None


# --------------------------------------------------------------------------- #
#  Plan preview: targets are DOMAINS; the estimate states its method
# --------------------------------------------------------------------------- #
def test_plan_preview_targets_and_estimate(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, Source

    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    for i in range(3):
        s.add(
            Source(
                name=f"S{i}",
                domain=f"s{i}.test",
                rss_url=f"https://s{i}.test/feed.xml",
                enabled=True,
                status="qualified",
                rate_limit_ms=2000,
            )
        )
    s.commit()

    settings = SchedulerSettings(mode="rss", max_sources_per_run=10)
    plan = plan_preview(s, settings, last_result={"sources_processed": 3, "pages_fetched": 6})
    assert plan["planned_total"] == 3
    # next_targets reflects the SAME stratified, TRUE-RANDOM per-pass order the run uses
    # (maintainer 2026-06-17: "scrape with TRUE RANDOMNESS by language AND source tags"),
    # so the order varies pass to pass — assert the SET of domains, not a fixed order.
    assert sorted(plan["next_targets"]) == ["s0.test", "s1.test", "s2.test"]  # domains, no URLs
    assert all("/" not in t for t in plan["next_targets"])
    # 3 sources x 2.0s median delay x 2 fetches each (6/3 from the last run) = 12s
    assert plan["estimated_seconds"] == 12
    assert "assumption" in plan["estimate_method"]  # honesty: stated, not promised


def test_plan_preview_reports_actual_language_and_tag_strata(monkeypatch, tmp_path):
    """Field test 2026-06-22 (#5): the queue preview must DISPLAY the actual strata it
    interleaves by (languages + tags), derived cheaply from the bounded sample already
    fetched, with the honest re-randomisation note — not just claim 'stratified'."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, Source

    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    seed = [
        ("en", "news"), ("en", "news"), ("en", "science"),
        ("fr", "news"), ("de", "finance"), ("ar", ""),  # blank tag -> ·untagged bucket
    ]
    for i, (lang, tags) in enumerate(seed):
        s.add(Source(name=f"S{i}", domain=f"s{i}.test", rss_url=f"https://s{i}.test/f.xml",
                     enabled=True, status="qualified", language=lang, tags=tags))
    s.commit()

    plan = plan_preview(s, SchedulerSettings(mode="rss"), last_result=None)
    strata = plan["strata"]
    langs = {x["key"]: x["n"] for x in strata["languages"]}
    tags = {x["key"]: x["n"] for x in strata["tags"]}
    assert langs == {"en": 3, "fr": 1, "de": 1, "ar": 1}  # real counts, no fabrication
    assert tags["news"] == 3 and tags["science"] == 1 and tags["finance"] == 1
    assert tags["·untagged"] == 1  # the blank-tag source is bucketed, never dropped
    assert strata["sampled"] == 6
    # The honest caveat travels with it (a rotation, never a fixed queue).
    assert "re-randomises" in strata["note"]


def test_activity_endpoint_shape():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.get("/api/scheduler/activity")
        assert r.status_code == 200
        body = r.json()
        for key in ("running", "active", "progress", "plan", "per_host_rates"):
            assert key in body
        assert "estimate_method" in body["plan"]


def test_network_mode_toggle_endpoints():
    """The app-wide online/offline switch (the kill switch as a first-class
    top-bar control, maintainer-ruled 2026-06-11)."""
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.ingest import clear_kill_switch, kill_switch_active

    with TestClient(app) as c:
        assert c.get("/api/system/network").json()["online"] is True
        r = c.post("/api/system/network", json={"online": False})
        assert r.json()["online"] is False and kill_switch_active() is True
        r = c.post("/api/system/network", json={"online": True})
        assert r.json()["online"] is True and kill_switch_active() is False
    clear_kill_switch()
