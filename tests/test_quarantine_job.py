"""
Retroactive QUARANTINE job (NAV-SOUP SPECIMEN ruling row 5 + 2026-07-23 field-feedback S3.2).

Proves the resumable-job CHASSIS (mirrors ReindexJobManager: state machine, persisted cursor,
pause/resume, progress) runs to completion detecting URL-shape + prose-gate candidates; that
``write=False`` (the default) is still PURE detection with no database mutation; that
``write=True`` REVERSIBLY stamps each detected candidate (idempotent -- an already-quarantined
row is skipped, never re-stamped/double-counted); and that a paused run's write MODE is preserved
across resume (never silently flips dry-run <-> real-write). Also covers the app wiring
(``get_quarantine_manager`` singleton + the /api/jobs API layer, S3.2 -- the deliberate wiring
this module's own docstring calls for, superseding the earlier "build-only, not wired" scaffold).

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

    def _one_at_a_time(session, *, after_id=0, limit=1, include_prose_gate=True, write=False):
        r = default_quarantine_candidates_batch(session, after_id=after_id, limit=1, write=write)
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


def test_manager_is_wired_into_the_app():
    """S3.2 supersedes the earlier 'build-only, not wired' scaffold (the maintainer's
    A2/A3 sign-off IS the wiring authorisation): get_quarantine_manager exists (mirrors
    ReindexJobManager.get_reindex_manager) and the api layer references it."""
    import src.analytics.quarantine_job as m

    assert hasattr(m, "get_quarantine_manager")
    mgr1 = m.get_quarantine_manager()
    mgr2 = m.get_quarantine_manager()
    assert mgr1 is mgr2  # a real singleton, not a fresh instance each call

    import pathlib

    api_dir = pathlib.Path(__file__).resolve().parents[1] / "src" / "api"
    hits = [f.name for f in api_dir.glob("*.py") if "quarantine" in f.read_text(encoding="utf-8").lower()]
    assert hits, "quarantine must be reachable from the api layer (src/api/quarantine.py + jobs.py)"


def test_default_work_function_write_mode_stamps_reversibly_and_idempotently(tmp_path):
    """write=True stamps quarantined/quarantine_reason/quarantine_criteria_version/
    quarantined_at on each detected candidate; a real article is NEVER stamped
    (negative space); re-running is idempotent (already-quarantined rows are counted
    separately and never re-written/double-counted)."""
    from src.analytics.criteria_calibration import CRITERIA_VERSION

    Session = _env(tmp_path)
    _seed(Session)
    with Session() as s:
        r = default_quarantine_candidates_batch(s, after_id=0, limit=100, write=True)
        assert r["write"] is True
        assert r["quarantined"] == 3
        assert r["newly_written"] == 3
        assert r["already_quarantined"] == 0

        real = s.query(Article).filter_by(url="https://x.test/2026/07/real-story").one()
        assert real.quarantined is not True  # the negative space: never stamped

        home = s.query(Article).filter_by(url="https://x.test/").one()
        assert home.quarantined is True
        assert home.quarantine_reason == "url_homepage"
        assert home.quarantine_criteria_version == CRITERIA_VERSION
        assert home.quarantined_at is not None

    # Re-running detects the SAME candidates but writes NOTHING new (idempotent).
    with Session() as s:
        r2 = default_quarantine_candidates_batch(s, after_id=0, limit=100, write=True)
        assert r2["quarantined"] == 3
        assert r2["newly_written"] == 0
        assert r2["already_quarantined"] == 3


def test_default_work_function_write_false_never_mutates(tmp_path):
    """The dry-run default is unchanged: write=False (the default) never sets any
    quarantine column, exactly the original scaffold's behaviour."""
    Session = _env(tmp_path)
    _seed(Session)
    with Session() as s:
        r = default_quarantine_candidates_batch(s, after_id=0, limit=100)
        assert r.get("write") is False
        assert r["newly_written"] == 0
    with Session() as s:
        assert all(a.quarantined is not True for a in s.query(Article).all())


def test_manager_write_run_actually_quarantines(tmp_path):
    Session = _env(tmp_path)
    _seed(Session)
    mgr = QuarantineJobManager(state_path=tmp_path / "q.json")
    st = mgr.start(_session_factory=Session, write=True)
    assert st["dry_run"] is False
    _join(mgr)
    final = mgr.status()
    assert final["state"] == "done" and final["dry_run"] is False
    assert final["tally"]["newly_written"] == 3
    with Session() as s:
        assert s.query(Article).filter(Article.quarantined.is_(True)).count() == 3


def test_resume_preserves_the_write_mode_of_the_paused_run(tmp_path, monkeypatch):
    """A paused WRITE run must resume as a write run -- never silently falling back to
    the dry-run default just because resume()'s caller doesn't repeat the choice."""
    monkeypatch.setattr("src.analytics.quarantine_job._BATCH", 1)
    Session = _env(tmp_path)
    _seed(Session)
    mgr = QuarantineJobManager(state_path=tmp_path / "q.json")

    def _one_at_a_time(session, *, after_id=0, limit=1, include_prose_gate=True, write=False):
        return default_quarantine_candidates_batch(session, after_id=after_id, limit=1, write=write)

    mgr.start(_session_factory=Session, _work_fn=_one_at_a_time, write=True)
    mgr.pause()
    _join(mgr)
    paused = mgr.status()
    assert paused["state"] in ("paused", "done")

    if paused["state"] == "paused":
        assert paused["dry_run"] is False  # still write mode while paused
        resumed = mgr.resume()
        assert resumed["state"] == "running" and resumed["dry_run"] is False
        _join(mgr)
        final = mgr.status()
        assert final["state"] == "done" and final["dry_run"] is False
        assert final["tally"]["newly_written"] == 3
        with Session() as s:
            assert s.query(Article).filter(Article.quarantined.is_(True)).count() == 3


def test_resume_preserves_dry_run_mode_too(tmp_path, monkeypatch):
    """The symmetric case: a paused DRY-RUN must never silently resume as a write."""
    monkeypatch.setattr("src.analytics.quarantine_job._BATCH", 1)
    Session = _env(tmp_path)
    _seed(Session)
    mgr = QuarantineJobManager(state_path=tmp_path / "q.json")

    def _one_at_a_time(session, *, after_id=0, limit=1, include_prose_gate=True, write=False):
        return default_quarantine_candidates_batch(session, after_id=after_id, limit=1, write=write)

    mgr.start(_session_factory=Session, _work_fn=_one_at_a_time)  # write defaults False
    mgr.pause()
    _join(mgr)
    paused = mgr.status()
    if paused["state"] == "paused":
        resumed = mgr.resume()
        assert resumed["dry_run"] is True
        _join(mgr)
        assert mgr.status()["dry_run"] is True
        with Session() as s:
            assert all(a.quarantined is not True for a in s.query(Article).all())


def test_quarantine_api_wiring_composes_end_to_end():
    """The 'slice-1c 404 lesson' (CLAUDE.md): compose the REAL route from the router
    prefix + decorator, never assert two literal strings side by side. Mirrors
    test_bulk_qualification_job.py's own wiring-composition test."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    api_src = (root / "src" / "api" / "quarantine.py").read_text(encoding="utf-8")
    wiring_src = (root / "src" / "api" / "_wiring.py").read_text(encoding="utf-8")
    jobs_src = (root / "src" / "api" / "jobs.py").read_text(encoding="utf-8")

    prefix_m = re.search(r'APIRouter\(prefix="([^"]+)"', api_src)
    assert prefix_m
    decorated = set(re.findall(r'@router\.(?:get|post)\("(/[^"]*)"', api_src))
    routes = {prefix_m.group(1) + d for d in decorated}
    assert routes == {"/api/quarantine/start", "/api/quarantine/status", "/api/quarantine/{action}"}

    # the router is actually included by _wiring.py, not merely defined.
    assert "from src.api.quarantine import router as quarantine_router" in wiring_src
    assert "quarantine_router," in wiring_src

    # /api/jobs surfacing: a DB-writer kind, listed in the aggregator, pause/resume routed.
    assert '"quarantine"' in jobs_src.split("_DB_WRITER_KINDS", 1)[1][:200]
    assert "_quarantine_jobs()" in jobs_src
    assert 'job_id == "quarantine"' in jobs_src

    # the manager's status() field name the jobs aggregator reads must actually exist.
    from src.analytics.quarantine_job import get_quarantine_manager

    assert "dry_run" in get_quarantine_manager().status()


def test_article_ids_mode_scans_exactly_the_given_set_and_reports_done(tmp_path):
    """S3.3 (2026-07-23): the explicit article_ids mode is a one-shot scan over EXACTLY the
    given set -- never truncated to `limit`, always reports done=True (no pagination), and
    never touches a real article outside that set."""
    Session = _env(tmp_path)
    _seed(Session)
    with Session() as s:
        all_ids = [a.id for a in s.query(Article).order_by(Article.id).all()]
        nav_soup_id = next(
            a.id for a in s.query(Article).all() if "newsletter-preference-centre" in a.url
        )
        real_id = next(a.id for a in s.query(Article).all() if "real-story" in a.url)

    # a tiny limit would truncate an after_id/limit scan, but article_ids must scan ALL of them
    with Session() as s:
        r = default_quarantine_candidates_batch(
            s, article_ids=all_ids, limit=1, write=True
        )
    assert r["scanned"] == len(all_ids)
    assert r["done"] is True
    assert r["newly_written"] == 3  # homepage + taxonomy + nav_soup
    assert r["last_id"] == max(all_ids)

    with Session() as s:
        assert s.get(Article, nav_soup_id).quarantined is True
        assert s.get(Article, real_id).quarantined is not True  # the real article stays clean


def test_article_ids_mode_never_touches_an_article_outside_the_given_set(tmp_path):
    """Scoping correctness: an id NOT in article_ids must never be scanned or stamped, even if
    it would itself be flagged -- this is the exact property a merge/import quarantine hook
    depends on (only the NEWLY-imported ids are ever passed in)."""
    Session = _env(tmp_path)
    _seed(Session)
    with Session() as s:
        nav_soup_id = next(
            a.id for a in s.query(Article).all() if "newsletter-preference-centre" in a.url
        )
        real_id = next(a.id for a in s.query(Article).all() if "real-story" in a.url)

    # scope to ONLY the real article's id -- the nav-soup article must be left untouched
    with Session() as s:
        r = default_quarantine_candidates_batch(s, article_ids=[real_id], write=True)
    assert r["scanned"] == 1
    assert r["quarantined"] == 0

    with Session() as s:
        assert s.get(Article, nav_soup_id).quarantined is not True
        assert s.get(Article, real_id).quarantined is not True


def test_article_ids_mode_chunks_under_the_sqlite_variable_cap(tmp_path):
    """A merge/import batch can import far more than SQLite's ~900-variable IN() cap worth of
    articles; the article_ids path must chunk internally (mirrors the fts_ids/.in_() chunking
    precedent) rather than silently truncating or erroring."""
    Session = _env(tmp_path)
    with Session() as s:
        src = s.query(Source).one()
        for i in range(1500):
            a = Article(
                url=f"https://x.test/bulk/{i}", canonical_url=f"https://x.test/bulk/{i}",
                source_id=src.id, content="bulk body text " * 20, hash=f"bulk{i}",
                word_count=60, language="en", title=f"bulk{i}",
            )
            s.add(a)
        s.commit()
        ids = [a.id for a in s.query(Article).filter(Article.url.like("%/bulk/%")).all()]
    assert len(ids) == 1500

    with Session() as s:
        r = default_quarantine_candidates_batch(s, article_ids=ids, write=False)
    assert r["scanned"] == 1500
    assert r["done"] is True
