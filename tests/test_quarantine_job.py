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

import textwrap

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

    def _one_at_a_time(session, *, after_id=0, limit=1, include_prose_gate=True, write=False,
                       index_page_tiers=None):
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

    def _one_at_a_time(session, *, after_id=0, limit=1, include_prose_gate=True, write=False,
                       index_page_tiers=None):
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

    def _one_at_a_time(session, *, after_id=0, limit=1, include_prose_gate=True, write=False,
                       index_page_tiers=None):
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


def test_the_work_fn_doubles_in_this_file_match_the_real_batch_signature():
    """A hand-written work-fn double drifts from the function it stands in for, and the drift
    surfaces as a TypeError raised INSIDE the worker thread -- which the job turns into
    ``state == "error"``, i.e. a failure that looks like a job bug rather than a stale test.
    That is exactly how adding ``index_page_tiers`` first presented. Pin the doubles to the
    real keyword-only parameter set so the next addition reddens HERE, by name."""
    import inspect

    import ast

    real = {
        name for name, p in
        inspect.signature(default_quarantine_candidates_batch).parameters.items()
        if p.kind is inspect.Parameter.KEYWORD_ONLY
    }

    # DERIVE the set the manager actually passes from _run's own call, rather than
    # hardcoding it. A hardcoded list cannot redden on "the next addition" -- it only
    # records the additions someone remembered to add to it, which is how
    # ``include_prose_gate`` was threaded through the manager while this guard stayed
    # green. Walk the real source for the work(...) call and read its keywords.
    run_src = inspect.getsource(QuarantineJobManager._run)
    calls = [
        n for n in ast.walk(ast.parse(textwrap.dedent(run_src)))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "work"
    ]
    assert len(calls) == 1, f"expected exactly one work(...) call in _run, found {len(calls)}"
    manager_passes = {kw.arg for kw in calls[0].keywords if kw.arg}
    assert manager_passes, "derived no keywords -- the AST walk found the wrong call"
    assert "include_prose_gate" in manager_passes, (
        "the manager must choose the criteria explicitly rather than inheriting the "
        "work function's default -- that default reaches a larger population than the "
        "URL-shape rules do"
    )
    assert manager_passes <= real, manager_passes - real

    src = inspect.getsource(test_job_pauses_and_resumes_from_persisted_cursor)
    for kw in manager_passes:
        assert kw in src, f"the double in this file does not accept {kw!r}"


def test_resume_preserves_the_index_page_tier_mode_of_the_paused_run(tmp_path):
    """``index_page_tiers`` changes WHICH articles a run detects, so it is part of the run's
    mode exactly like ``write``. A resume that let it fall back to the default would silently
    narrow the scope half way through and file the result under one run's name -- the 2026-07-23
    S3.2 lesson ("a resumable job's execution mode must be explicitly re-supplied on resume").
    Driven through the REAL start/pause/resume path, not by reading the source.

    The pause is requested BY THE WORK FN on its first batch rather than from the test thread,
    so a paused state is guaranteed rather than raced -- otherwise a fast machine finishes the
    4-article fixture first, no resume happens, and the test passes while proving nothing about
    resume at all.
    """
    Session = _env(tmp_path)
    _seed(Session)
    mgr = QuarantineJobManager(state_path=tmp_path / "q.json")
    seen: list[frozenset] = []

    def _one_at_a_time(session, *, after_id=0, limit=1, include_prose_gate=True, write=False,
                       index_page_tiers=None):
        seen.append(frozenset(index_page_tiers or ()))
        if len(seen) == 1:
            mgr.pause()  # deterministic: the loop checks _stop before the next batch
        return default_quarantine_candidates_batch(
            session, after_id=after_id, limit=1, write=write,
            index_page_tiers=index_page_tiers,
        )

    mgr.start(_session_factory=Session, _work_fn=_one_at_a_time, index_page_tiers={1})
    _join(mgr)
    assert mgr.status()["state"] == "paused", mgr.status()
    assert len(seen) == 1, seen

    mgr.resume()
    _join(mgr)
    assert len(seen) > 1, "the resume ran no further batch, so it proves nothing"
    assert all(t == frozenset({1}) for t in seen), seen


def _reasons(Session):
    """What the corpus is actually stamped with, by reason -- read back from the rows."""
    with Session() as s:
        out: dict[str, int] = {}
        for a in s.query(Article).filter(Article.quarantined.is_(True)).all():
            out[a.quarantine_reason] = out.get(a.quarantine_reason, 0) + 1
        return out


def test_a_tier_a_run_applies_the_url_rules_without_the_prose_gate(tmp_path):
    """``include_prose_gate=False`` runs the URL-shape rules ALONE.

    The two criteria reach DIFFERENT populations: the URL rules fire only below the
    ``_ARTICLE_MIN_WORDS`` guard, while the prose gate fires only on bodies that guard
    KEEPS. So a run agreed as "the URL-shape drop path" must not silently also apply a
    criterion to every long body in the corpus -- on a real corpus that is an unmeasured
    population, and the size of it is not knowable from the run's own report.

    Driven through the REAL manager start path, and asserted on the STAMPED ROWS rather
    than the tally, because the tally is what a wrong criterion would also inflate.
    """
    Session = _env(tmp_path)
    _seed(Session)
    mgr = QuarantineJobManager(state_path=tmp_path / "q.json")
    mgr.start(_session_factory=Session, write=True, include_prose_gate=False)
    _join(mgr)

    assert mgr.status()["state"] == "done"
    assert _reasons(Session) == {"url_homepage": 1, "url_taxonomy": 1}

    # the nav-soup body is reachable ONLY by the prose gate: it clears the word guard,
    # so no URL rule applies to it. It must still be a normal article after a Tier A run.
    with Session() as s:
        nav = s.query(Article).filter(
            Article.url.like("%newsletter-preference-centre%")
        ).one()
        assert nav.quarantined is not True
        assert nav.quarantine_reason is None


def test_the_prose_gate_still_fires_when_it_is_not_switched_off(tmp_path):
    """The negative-space twin of the test above, and the one that makes it mean anything.

    Without this, a change that disabled the prose gate outright -- or broke it -- would
    satisfy the Tier A test perfectly while quietly removing a criterion the default run
    is supposed to apply.
    """
    Session = _env(tmp_path)
    _seed(Session)
    mgr = QuarantineJobManager(state_path=tmp_path / "q.json")
    mgr.start(_session_factory=Session, write=True)  # include_prose_gate defaults True
    _join(mgr)

    assert mgr.status()["state"] == "done"
    assert _reasons(Session) == {"url_homepage": 1, "url_taxonomy": 1, "nav_soup": 1}


def test_resume_preserves_the_prose_gate_mode_of_the_paused_run(tmp_path):
    """``include_prose_gate`` changes WHICH articles a run detects, so it is part of the
    run mode exactly like ``write`` and ``index_page_tiers``. A resume that let it fall
    back to its default would WIDEN the criteria half way through a run agreed as Tier A
    and file both halves under one run's name.

    The pause is requested by the work fn on its first batch, so a paused state is
    guaranteed rather than raced against a fast machine finishing the small fixture.
    """
    Session = _env(tmp_path)
    _seed(Session)
    mgr = QuarantineJobManager(state_path=tmp_path / "q.json")
    seen: list[bool] = []

    def _pause_after_first(session, *, after_id=0, limit=1, include_prose_gate=True,
                           write=False, index_page_tiers=None):
        seen.append(include_prose_gate)
        if len(seen) == 1:
            mgr.pause()
        return default_quarantine_candidates_batch(
            session, after_id=after_id, limit=1, write=write,
            include_prose_gate=include_prose_gate, index_page_tiers=index_page_tiers,
        )

    mgr.start(_session_factory=Session, _work_fn=_pause_after_first, write=True,
              include_prose_gate=False)
    _join(mgr)
    assert mgr.status()["state"] == "paused"

    mgr.resume()
    _join(mgr)
    assert mgr.status()["state"] == "done"

    # every batch, on both sides of the pause, ran under the mode the run started in
    assert len(seen) > 1, "the run never resumed, so this proves nothing about resume"
    assert seen == [False] * len(seen), seen
    assert "nav_soup" not in _reasons(Session)


def test_a_restart_restores_every_dimension_of_the_run_mode(tmp_path):
    """An interrupted run is restored as PAUSED on the next construction -- and it must come
    back under the same CRITERIA, not just the same write flag.

    Persisting only ``write`` meant a restart silently reset the other two dimensions: a
    Tier A run would resume applying the prose gate (wider), and a tier run would resume
    without its tiers (narrower). Both file the result under one run's name, which is the
    thing the run-mode rule exists to prevent.
    """
    import json

    state = tmp_path / "q.json"
    Session = _env(tmp_path)
    _seed(Session)

    mgr = QuarantineJobManager(state_path=state)
    mgr.start(_session_factory=Session, _work_fn=lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("should not run")), write=True, include_prose_gate=False,
        index_page_tiers={1})
    mgr.pause()
    _join(mgr)

    # the state file itself carries all three, not just write
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["write"] is True
    assert saved["include_prose_gate"] is False
    assert saved["index_page_tiers"] == [1]

    # a FRESH manager (the app-restart path) restores them
    restored = QuarantineJobManager(state_path=state)
    assert restored._write is True
    assert restored._include_prose_gate is False
    assert restored._index_page_tiers == frozenset({1})


def test_a_state_file_written_before_these_were_persisted_still_restores(tmp_path):
    """Forward-compatibility: a run paused by an older build has no ``include_prose_gate``
    or ``index_page_tiers`` key. It must restore under the values ``start()`` itself
    defaults to, rather than crashing or inventing a mode nobody chose."""
    import json

    state = tmp_path / "q.json"
    state.write_text(json.dumps({
        "cursor": 7, "total": 10, "done": 7, "tally": {}, "state": "paused", "write": True,
    }), encoding="utf-8")

    mgr = QuarantineJobManager(state_path=state)
    assert mgr._write is True
    assert mgr._include_prose_gate is True          # start()'s own default
    assert mgr._index_page_tiers == frozenset()     # start()'s own default
    assert mgr.status()["state"] == "paused"


def test_the_endpoint_forwards_the_operators_criteria_choice_to_the_manager():
    """The API is the layer an operator actually runs this from, so a parameter accepted
    there and dropped on the way to the manager is worse than one that was never offered:
    the run reports itself as the mode that was asked for while applying another.

    Driven through a real TestClient rather than by reading the source, because FastAPI is
    what turns the query string into arguments -- and because a route called directly
    receives ``Query(...)`` SENTINEL objects, which are truthy, so a source-level or
    direct-call check would pass on exactly the bug it is meant to catch.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.quarantine import router

    seen: list[dict] = []

    class _Recorder:
        def start(self, **kw):
            seen.append(kw)
            return {"state": "running", **kw}

    app = FastAPI()
    app.include_router(router)
    import src.analytics.quarantine_job as qj

    real = qj.get_quarantine_manager
    qj.get_quarantine_manager = lambda: _Recorder()  # type: ignore[assignment]
    try:
        c = TestClient(app)
        assert c.post("/api/quarantine/start?write=true&include_prose_gate=false").status_code == 200
        assert seen[-1] == {"write": True, "include_prose_gate": False}

        # ...and the twin: omitting it must not silently narrow a default run either.
        assert c.post("/api/quarantine/start").status_code == 200
        assert seen[-1] == {"write": False, "include_prose_gate": True}
    finally:
        qj.get_quarantine_manager = real  # type: ignore[assignment]


def test_status_says_which_criteria_the_run_is_applying(tmp_path):
    """``dry_run`` alone cannot distinguish two runs that stamp different populations.
    A Tier A run and a default run are both ``dry_run: false`` with a tally of stamped
    articles, so without the criteria in the payload the tally can never be read back
    against the scope it was agreed under -- in the task manager or in a saved report."""
    Session = _env(tmp_path)
    _seed(Session)
    mgr = QuarantineJobManager(state_path=tmp_path / "q.json")
    mgr.start(_session_factory=Session, write=True, include_prose_gate=False)
    _join(mgr)

    st = mgr.status()
    assert st["dry_run"] is False
    assert st["include_prose_gate"] is False
    assert st["index_page_tiers"] == []

    # the default run reports the other mode, so the field actually discriminates
    Session2 = _env(tmp_path / "b")
    _seed(Session2)
    mgr2 = QuarantineJobManager(state_path=tmp_path / "q2.json")
    mgr2.start(_session_factory=Session2, write=True)
    _join(mgr2)
    assert mgr2.status()["include_prose_gate"] is True
