"""Backend whole-corpus re-index JOB (keyword-engine Phase 1.1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A pausable DB-writer job that drives reindex_all_batch over the whole corpus with a
PERSISTED cursor — so it survives a tab close / app restart and resumes from where it
stopped, instead of the old client loop that restarted from article 0. The re-index is
idempotent (index_article is delete-then-reinsert with exact counter deltas), so a
resumed/repeated run loses NO keyword rows and drifts NO counters (the no-loss proof).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.extract import BaselineExtractor
from src.analytics.reindex_job import ReindexJobManager
from src.analytics.store import index_article, reconcile_keyword_counters
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def env(tmp_path):
    # A shared in-memory DB (StaticPool) so the worker thread's own session sees the
    # schema + the seeded rows; tests join() the worker before asserting (no race).
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    with Session() as s:
        s.add(Source(name="S", domain="x.test", country="fr"))
        s.commit()
    return Session, tmp_path


_BODIES = [
    "The election results show major inflation across the global economy this year.",
    "Climate policy and trade negotiations dominated the diplomatic summit in Europe.",
    "Energy prices and the drought pushed agriculture costs higher across the region.",
    "Vaccine distribution and the pandemic response shaped the public health debate.",
    "Sanctions and the refugee crisis reshaped the security situation near the border.",
]


def _seed(Session, n):
    with Session() as s:
        for i in range(n):
            s.add(
                Article(
                    url=f"https://x.test/{i}",
                    canonical_url=f"https://x.test/{i}",
                    source_id=1,
                    title=f"Story {i}",
                    content=_BODIES[i % len(_BODIES)],
                    hash=f"h{i}",
                    country="fr",
                    language="en",
                    published_at=datetime(2024, 3, 1, tzinfo=UTC),
                    created_at=datetime.now(UTC),
                )
            )
        s.commit()


def _join(mgr, t=10.0):
    if mgr._thread is not None:
        mgr._thread.join(t)


def _new_mgr(tmp):
    return ReindexJobManager(state_path=tmp / "reindex_state.json")


def _snapshot(Session):
    """Per-article (keyword, count) mention rows + per-keyword counters — the data the
    no-loss test compares before/after a re-index."""
    with Session() as s:
        mentions = sorted(
            (m.article_id, kw.normalized_term, m.count)
            for m, kw in s.query(KeywordMention, Keyword).join(
                Keyword, Keyword.id == KeywordMention.keyword_id
            )
        )
        counters = sorted(
            (kw.normalized_term, kw.mention_count, kw.article_count)
            for kw in s.query(Keyword)
        )
    return mentions, counters


def test_reindex_job_runs_to_completion(env):
    Session, tmp = env
    _seed(Session, 5)
    mgr = _new_mgr(tmp)
    st = mgr.start(_session_factory=Session, _extractor=BaselineExtractor())
    assert st["state"] == "running" and st["articles_total"] == 5
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done" and s["articles_done"] == 5
    assert s["tally"]["reindexed"] == 5 and s["tally"].get("failed", 0) == 0
    with Session() as sess:
        # every article got keyword mentions
        indexed = {row[0] for row in sess.query(KeywordMention.article_id).distinct()}
        assert indexed == {a.id for a in sess.query(Article).all()}


def test_reindex_job_is_idempotent_no_data_loss(env):
    """The no-loss proof: re-indexing an already-indexed corpus reproduces the EXACT
    keyword rows + counters (delete-then-reinsert + counter deltas are idempotent)."""
    Session, tmp = env
    _seed(Session, 5)
    ex = BaselineExtractor()
    # Index once via the normal per-article path, then snapshot.
    with Session() as s:
        for a in s.query(Article).all():
            index_article(s, a, extractor=ex, country=a.country)
    before = _snapshot(Session)

    # Run the JOB (force re-index of every article) and snapshot again.
    mgr = _new_mgr(tmp)
    mgr.start(_session_factory=Session, _extractor=ex)
    _join(mgr)
    assert mgr.status()["state"] == "done"
    after = _snapshot(Session)
    assert after == before  # zero rows lost, zero counter drift

    # And the authoritative counter reconciliation reports NO drift.
    with Session() as s:
        rep = reconcile_keyword_counters(s)
    assert rep["drift_repaired"] == 0


def test_reindex_job_pauses_and_resumes_from_cursor(env, monkeypatch):
    """Pause mid-run (one article per batch) → state=paused, partial progress; resume →
    completes the remainder. Proves the persisted-cursor resume (no restart-from-0)."""
    monkeypatch.setattr("src.analytics.reindex_job._BATCH", 1)
    Session, tmp = env
    _seed(Session, 4)
    mgr = _new_mgr(tmp)

    class _PausingExtractor:
        def __init__(self, inner, pause_at):
            self.inner, self.pause_at, self.n, self.name = inner, pause_at, 0, inner.name

        def extract(self, *a, **k):
            self.n += 1
            if self.n == self.pause_at:
                mgr.pause()  # self-pause after the 2nd article's extraction
            return self.inner.extract(*a, **k)

    mgr.start(_session_factory=Session, _extractor=_PausingExtractor(BaselineExtractor(), 2))
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "paused" and 0 < s["articles_done"] < 4
    partial = {row[0] for row in _iter_indexed(Session)}
    assert 0 < len(partial) < 4  # only some articles indexed so far

    mgr.resume()
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done" and s["articles_done"] == 4
    assert {row[0] for row in _iter_indexed(Session)} == {a.id for a in _all_articles(Session)}


def _iter_indexed(Session):
    with Session() as s:
        return list(s.query(KeywordMention.article_id).distinct())


def _all_articles(Session):
    with Session() as s:
        return s.query(Article).all()


def test_persisted_cursor_survives_an_app_restart(env):
    Session, tmp = env
    _seed(Session, 6)
    ex = BaselineExtractor()
    state = tmp / "reindex_state.json"
    # Manager A: index the first 3, persist an interrupted "running" state at that cursor.
    with Session() as s:
        arts = s.query(Article).order_by(Article.id).all()
        for a in arts[:3]:
            index_article(s, a, extractor=ex, country=a.country)
        cursor = arts[2].id
    a = ReindexJobManager(state_path=state)
    a._total, a._done, a._cursor, a._tally, a._state = 6, 3, cursor, {"reindexed": 3}, "running"
    a._save()
    # Manager B = a fresh process restart: it LOADS the interrupted run as PAUSED.
    b = ReindexJobManager(state_path=state)
    assert b.status()["state"] == "paused" and b.status()["articles_done"] == 3
    b._session_factory = Session
    b._extractor = ex
    b.resume()
    _join(b)
    assert b.status()["state"] == "done" and b.status()["articles_done"] == 6
    with Session() as s:
        indexed = {row[0] for row in s.query(KeywordMention.article_id).distinct()}
        assert indexed == {art.id for art in s.query(Article).all()}
    assert not state.exists()  # the cursor file is cleared on completion


def test_prune_after_chains_on_a_complete_pass(env):
    Session, tmp = env
    _seed(Session, 3)
    mgr = _new_mgr(tmp)
    mgr.start(prune_after=True, _session_factory=Session, _extractor=BaselineExtractor())
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done" and s["prune_after"] is True
    assert "pruned" in s["tally"]  # the orphan GC ran at the end (0 on a fresh index)


def test_idle_status_shape_and_bad_resume(env):
    _, tmp = env
    mgr = _new_mgr(tmp)
    s = mgr.status()
    assert s["state"] == "idle" and s["articles_total"] == 0 and s["eta_seconds"] is None
    with pytest.raises(RuntimeError, match="Nothing paused"):
        mgr.resume()


def test_reindex_job_keyword_only_scope(env):
    """Phase 1.2: the job threads scope="keywords" through to reindex_all_batch and
    reports it in status; the run still indexes every article's keywords."""
    Session, tmp = env
    _seed(Session, 3)
    mgr = _new_mgr(tmp)
    st = mgr.start(scope="keywords", _session_factory=Session, _extractor=BaselineExtractor())
    assert st["scope"] == "keywords"
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done" and s["scope"] == "keywords"
    with Session() as sess:
        indexed = {row[0] for row in sess.query(KeywordMention.article_id).distinct()}
        assert indexed == {a.id for a in sess.query(Article).all()}


# --------------------------------------------------------------------------- #
#  the standalone re-index uses every core, like an import already did
# --------------------------------------------------------------------------- #
def test_the_standalone_reindex_precomputes_in_the_pool_not_on_one_core(tmp_path):
    """Field report 2026-08-12: "re-index + prune keywords ... 1 cpu thread is too slow".

    It was single-core BY CONSTRUCTION. reindex_articles (the IMPORT path) got the
    parallel precompute on 2026-07-19, for the identical complaint from the restore
    side; reindex_all_batch -- what the Settings "Clean up keywords" job runs -- had no
    ``workers`` parameter at all. So this asserts the PATH the pool reports, not merely
    that the call accepts an argument: a fix that plumbed ``workers`` through to a
    window too small to parallelise, or to an extractor the pool refuses, would pass
    every output-equality test while still running on one core.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.analytics.extract import get_extractor
    from src.analytics.store import reindex_all_batch
    from src.database.models import Article, Base, Source

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    with Session() as s:
        src = Source(name="S", domain="s.test", enabled=True)
        s.add(src)
        s.commit()
        # Comfortably over _MIN_PARALLEL_BATCH (16) -- below it the pool declines by
        # design, which is correct and would make this test prove nothing.
        for i in range(24):
            s.add(Article(source_id=src.id, url=f"https://s.test/{i}", title=f"T{i}",
                          canonical_url=f"https://s.test/{i}",
                          content=f"An article about elections and the economy, number {i}. " * 12,
                          language="en", hash=f"h{i}"))
        s.commit()

    stats: dict = {}
    with Session() as s:
        out = reindex_all_batch(s, extractor=get_extractor("baseline"), limit=300, stats=stats)

    assert out["reindexed"] == 24 and out["failed"] == 0
    by_path = (stats.get("precompute") or {}).get("by_path") or {}
    assert by_path, "the delegated path reported no precompute at all"
    assert "serial" not in by_path, (
        f"the standalone re-index still precomputed on one core: {by_path}"
    )


def test_the_watermark_is_never_stamped_past_work_that_did_not_happen():
    """reindex_articles can abandon a window part-way through via should_stop, and
    ``last_id`` is a RESUME watermark. Stamping ids[-1] for a window that stopped early
    would skip every article after the stop point permanently -- so this path must not
    grow a should_stop, however tempting the symmetry. The job stops BETWEEN batches."""
    import inspect

    from src.analytics.store import reindex_all_batch

    assert "should_stop" not in inspect.signature(reindex_all_batch).parameters, (
        "an abandoned window would stamp a watermark over articles it never re-indexed"
    )


# --------------------------------------------------------------------------- #
#  a paused run is CONTINUED, never silently discarded
# --------------------------------------------------------------------------- #
def _paused_state(tmp, **over):
    """What an interrupted run leaves on disk. Written directly because that is
    exactly what _load_persisted reads at app start."""
    import json

    d = {"cursor": 812345, "total": 1048725, "done": 812345,
         "tally": {"reindexed": 812345, "failed": 0},
         "state": "running", "scope": "keywords", "prune_after": True}
    d.update(over)
    p = tmp / "rx.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def test_the_button_continues_a_paused_run_instead_of_starting_over(tmp_path, env):
    """Field report 2026-08-12: "I could not resume the keyword reindexing, in
    consequence the sequence has started all over again. Just lost 24h".

    The persistence was never broken -- an interrupted run restores as paused with its
    cursor intact. What lost the day is that ``start()`` defaulted the cursor to 0 and
    the ONLY control on the Settings surface calls ``start()``: the button a user
    reaches for discarded 812,345 articles of progress without a word, while the resume
    lived in the task manager where nobody looked. So the safe behaviour cannot depend
    on finding the right button -- it has to be what the ordinary one does.
    """
    Session, _ = env
    mgr = ReindexJobManager(state_path=_paused_state(tmp_path))
    assert mgr.status()["state"] == "paused" and mgr._cursor == 812345

    # Exactly what POST /api/insights/reindex-job?scope=keywords&prune_after=true does.
    mgr.start(scope="keywords", prune_after=True,
              _session_factory=Session, _extractor=BaselineExtractor())
    _join(mgr)
    assert mgr._cursor >= 812345, "the paused run's progress was thrown away"
    assert mgr.status()["tally"]["reindexed"] >= 812345, "and its tally with it"


def test_starting_a_DIFFERENT_run_refuses_rather_than_discarding_the_paused_one(tmp_path, env):
    """A full re-index is not the paused keywords-only one, so continuing it would be
    wrong -- but so is silently destroying a day of work. Refuse, by name, with what it
    would cost, and make starting over something the caller says out loud."""
    Session, _ = env
    mgr = ReindexJobManager(state_path=_paused_state(tmp_path))
    with pytest.raises(RuntimeError) as exc:
        mgr.start(scope="full", _session_factory=Session, _extractor=BaselineExtractor())
    msg = str(exc.value)
    assert "812,345" in msg and "keywords" in msg, f"the refusal must name what is at stake: {msg}"

    # ...and restart=True is the explicit way to discard it.
    mgr.start(scope="full", restart=True, _session_factory=Session, _extractor=BaselineExtractor())
    _join(mgr)
    assert mgr.status()["scope"] == "full"


def test_a_finished_or_cancelled_run_is_not_resurrected(tmp_path, env):
    """The twin. Continuing is right for an INTERRUPTED run; a run the operator
    cancelled, or one that completed, must start fresh -- otherwise the fix turns into
    a job that can never be restarted from the beginning."""
    Session, _ = env
    mgr = ReindexJobManager(state_path=_paused_state(tmp_path, state="done"))
    assert mgr._cursor == 0, "a finished run leaves nothing to resume"
    mgr.start(scope="keywords", prune_after=True,
              _session_factory=Session, _extractor=BaselineExtractor())
    _join(mgr)
    assert mgr.status()["state"] == "done"

    mgr2 = ReindexJobManager(state_path=_paused_state(tmp_path / "b" if False else tmp_path))
    with mgr2._lock:
        mgr2._state = "cancelled"
    mgr2.start(scope="keywords", prune_after=True,
               _session_factory=Session, _extractor=BaselineExtractor())
    _join(mgr2)
    assert mgr2._done_at_start == 0, "a cancelled run must not be silently continued"


def test_the_speed_is_reported_in_both_units_and_never_fabricated(env, tmp_path):
    """Field ask: "add a keyword average per hour so users can estimate the current
    speed". The job iterates ARTICLES, so that rate is exact; keywords/h is the mention
    rows the run actually wrote over the same window -- a real measurement of the same
    work, never the article rate times an assumed average. Both absent until real."""
    Session, tmp = env
    _seed(Session, 12)
    mgr = _new_mgr(tmp)
    idle = mgr.status()
    assert idle["articles_per_hour"] is None and idle["keywords_per_hour"] is None, (
        "a job that has done nothing must not report a rate"
    )

    mgr.start(_session_factory=Session, _extractor=BaselineExtractor())
    _join(mgr)
    s = mgr.status()
    assert s["state"] == "done"
    assert s["articles_per_hour"] and s["articles_per_hour"] > 0

    # THE NUMERATOR IS REAL. "> 0" is satisfied by any fabricated number -- a first
    # draft asserted only that, and a mutant computing keywords/h as articles x an
    # assumed 12-per-article passed it. Two assertions close that: the counter equals
    # the mention rows actually in the database, and the reported rate is derived from
    # THAT counter rather than from the article rate.
    with Session() as sess:
        real_rows = sess.query(KeywordMention).count()
    assert s["tally"]["mentions_written"] == real_rows, (
        "the counter must be what reached the database, not an estimate"
    )
    assert s["keywords_per_hour"] and s["keywords_per_hour"] > 0
    ratio = s["keywords_per_hour"] / s["articles_per_hour"]
    expect = real_rows / s["tally"]["reindexed"]
    assert abs(ratio - expect) < 0.05, (
        f"keywords/h is not the measured mentions over the same window: {ratio} vs {expect}"
    )
