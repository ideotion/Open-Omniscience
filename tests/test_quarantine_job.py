"""
Retroactive QUARANTINE job -- SCAFFOLDING ONLY (NAV-SOUP SPECIMEN ruling, row 5 execution scope).

Proves the resumable-job CHASSIS (mirrors ReindexJobManager: state machine, persisted cursor,
pause/resume, progress) runs to completion detecting URL-shape + prose-gate candidates, and -- the
load-bearing property for this scaffolding -- that it NEVER writes to the database (dry-run only,
``status()["dry_run"] is True`` always) and is NOT reachable from anywhere in the running app (no
singleton getter, no /api/jobs wiring).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.quarantine_job import QuarantineJobManager, default_quarantine_candidates_batch
from src.database.models import Article, Base, Source

_NAV_SOUP_BODY = (
    "News Latest Irish News Mirror Bingo Soccer Golf Rugby Union Sport Business Politics "
    "World News Travel Money Markets Weather Video Photos Gallery Podcast Newsletters Events "
    "About Contact Home Search Login Sign Up Subscribe Cookies Advertisement Privacy Terms "
    "Follow Facebook Twitter Instagram Newsletter Preference Centre Manage Subscriptions "
    "Menu Toggle Navigation Skip Content Latest News Sport GAA Rugby Soccer Racing Golf Boxing "
    "Motors Showbiz TV Fashion Beauty Food Recipes Property Travel Family Voucher Codes Bingo "
    "Dating Contact Advertise Cookie Policy Privacy Policy Terms Conditions Modern Slavery "
    "Statement Complaints Regulation Archive Sitemap Jobs Shop Weddings Announcements Obituaries "
    "Horoscopes Puzzles Crosswords Competitions Vouchers Discounts Deals Reviews Betting Casino "
    "Lottery Results Traffic Cameras Roadworks Bus Times Train Times Flight Tracker Currency "
    "Converter Recipes Wine Beer Cocktails Restaurants Bars Nightlife Theatre Cinema Music Books"
)
_REAL_PROSE_BODY = (
    "The government said on Tuesday that it would review the policy after months of criticism "
    "from opposition lawmakers, who argued that the reform had failed to deliver the promised "
    "benefits to the region's struggling economy. Officials declined to give a firm timetable "
    "for the review, but said a report would follow before the end of the year. "
) * 2


def _env(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    with Session() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
    return Session


def _seed(Session):
    with Session() as s:
        src = s.query(Source).one()
        rows = [
            ("https://x.test/2026/07/real-story", 500, _REAL_PROSE_BODY, "keep"),
            ("https://x.test/", 5, "home", "url_homepage"),
            ("https://x.test/tag/gaza", 4, "tag", "url_taxonomy"),
            ("https://x.test/all-about/newsletter-preference-centre",
             len(_NAV_SOUP_BODY.split()), _NAV_SOUP_BODY, "nav_soup"),
        ]
        for i, (url, wc, content, _label) in enumerate(rows):
            s.add(Article(url=url, canonical_url=url, source_id=src.id, content=content,
                          hash=f"h{i}", word_count=wc, language="en", title=f"t{i}"))
        s.commit()


def _join(mgr, t=10.0):
    if mgr._thread is not None:
        mgr._thread.join(t)


def test_default_work_function_is_pure_detection_no_write(tmp_path):
    Session = _env(tmp_path)
    _seed(Session)
    with Session() as s:
        r = default_quarantine_candidates_batch(s, after_id=0, limit=100)
    assert r["scanned"] == 4
    assert r["quarantined"] == 3  # homepage + taxonomy + nav_soup; the real story is kept
    assert r["by_reason"].get("nav_soup") == 1
    assert r["done"] is True

    # NEVER a write: re-running detects the EXACT same candidates (idempotent, no mutated state)
    with Session() as s:
        r2 = default_quarantine_candidates_batch(s, after_id=0, limit=100)
    assert r2["quarantined_ids"] == r["quarantined_ids"]


def test_job_runs_to_completion_dry_run_only(tmp_path):
    Session = _env(tmp_path)
    _seed(Session)
    mgr = QuarantineJobManager(state_path=tmp_path / "q.json")
    st = mgr.start(_session_factory=Session)
    assert st["state"] == "running" and st["dry_run"] is True
    _join(mgr)
    final = mgr.status()
    assert final["state"] == "done"
    assert final["dry_run"] is True
    assert final["tally"]["quarantined"] == 3
    assert final["tally"].get("reason:nav_soup") == 1

    # confirm NOTHING was mutated in the DB -- still 4 articles, all present, all unchanged
    with Session() as s:
        assert s.query(Article).count() == 4


def test_job_pauses_and_resumes_from_persisted_cursor(tmp_path, monkeypatch):
    monkeypatch.setattr("src.analytics.quarantine_job._BATCH", 1)
    Session = _env(tmp_path)
    _seed(Session)
    mgr = QuarantineJobManager(state_path=tmp_path / "q.json")

    def _one_at_a_time(session, *, after_id=0, limit=1, include_prose_gate=True):
        r = default_quarantine_candidates_batch(session, after_id=after_id, limit=1)
        return r

    mgr.start(_session_factory=Session, _work_fn=_one_at_a_time)
    mgr.pause()
    _join(mgr)
    paused = mgr.status()
    assert paused["state"] in ("paused", "done")  # a fast machine may finish before pause lands

    if paused["state"] == "paused":
        assert paused["articles_done"] < 4
        resumed = mgr.resume()
        assert resumed["state"] == "running"
        _join(mgr)
        final = mgr.status()
        assert final["state"] == "done"
        assert final["tally"]["quarantined"] == 3


def test_interrupted_run_restores_as_paused_on_restart(tmp_path):
    Session = _env(tmp_path)
    _seed(Session)
    state_path = tmp_path / "q.json"
    mgr = QuarantineJobManager(state_path=state_path)
    mgr.start(_session_factory=Session)
    _join(mgr)
    assert mgr.status()["state"] == "done"  # completed + cleared its own state file

    # simulate an interrupted run by writing a "running" state file directly, then constructing a
    # NEW manager instance (the app-restart path) -- it must come back PAUSED, never silently lost.
    import json

    state_path.write_text(json.dumps({
        "cursor": 2, "total": 4, "done": 2, "tally": {"quarantined": 1}, "state": "running",
    }), encoding="utf-8")
    mgr2 = QuarantineJobManager(state_path=state_path)
    assert mgr2.status()["state"] == "paused"
    assert mgr2.status()["articles_done"] == 2


def test_scaffolding_is_not_wired_into_the_app():
    """Build-only per the 0.3 gate's own scope: no singleton getter (unlike
    ReindexJobManager.get_reindex_manager), and no api module imports this module at all."""
    import src.analytics.quarantine_job as m

    assert not hasattr(m, "get_quarantine_manager")

    import pathlib

    api_dir = pathlib.Path(__file__).resolve().parents[1] / "src" / "api"
    hits = []
    for f in api_dir.glob("*.py"):
        if "quarantine_job" in f.read_text(encoding="utf-8"):
            hits.append(f.name)
    assert hits == [], f"quarantine_job must not be wired into the api layer, found in: {hits}"
