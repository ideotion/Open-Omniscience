"""R827 R10 / R830 (row 408 PR 3): imported articles wait in a screening queue, leave the aggregates while they wait, and a
background worker judges them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import threading

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, Keyword, ScreeningPending
from tests.test_quarantine_leaves_keyword_figures import WORD, _corpus, _junk, db  # noqa: F401 - db is a fixture

__all__ = ["db"]


def _queue(db, articles) -> None:
    for a in articles:
        db.add(ScreeningPending(article_id=a.id))
    db.commit()


def _queued(db) -> int:
    return int(db.execute(select(func.count()).select_from(ScreeningPending)).scalar() or 0)


def _counter(db) -> tuple[int, int]:
    db.expire_all()
    kw = db.query(Keyword).filter(Keyword.normalized_term == WORD).one()
    return int(kw.mention_count), int(kw.article_count)


def _top(db, **kw) -> dict:
    return {r["normalized"]: r for r in q.top_terms(db, limit=50, **kw)["terms"]}


def test_a_judged_chunk_leaves_the_queue_in_the_same_commit_as_its_stamps(db):
    from src.analytics.quarantine_job import default_quarantine_candidates_batch

    clean = _corpus(db)
    junk = [_junk(db, n) for n in range(2)]
    _queue(db, clean + junk)
    before = _counter(db)
    r = default_quarantine_candidates_batch(
        db, article_ids=[a.id for a in clean + junk], write=True, release_pending=True
    )
    assert r["released"] == 5 and r["newly_written"] == 2
    assert _queued(db) == 0
    db.expire_all()
    assert {a.id for a in db.query(Article).filter(Article.quarantined.is_(True))} == {j.id for j in junk}
    # Only the junk left the counters (the screening keeps them as it always has); the clean articles stay counted.
    after = _counter(db)
    assert after[1] == before[1] - 2


def test_a_queued_article_leaves_every_aggregate_until_it_is_screened(db):
    from src.analytics.quarantine_job import default_quarantine_candidates_batch

    arts = _corpus(db)
    assert _top(db)[WORD]["articles"] == 3
    _queue(db, arts[:1])
    # the corpus-wide counters path takes the queued article out at query time; the windowed path filters it
    assert _top(db)[WORD]["articles"] == 2
    assert _top(db, days=30)[WORD]["articles"] == 2
    assert _counter(db)[1] == 3, "the stored counters are not touched by the queue"
    default_quarantine_candidates_batch(db, article_ids=[arts[0].id], write=True, release_pending=True)
    assert _top(db)[WORD]["articles"] == 3
    assert _top(db, days=30)[WORD]["articles"] == 3


def test_the_tally_says_how_many_wait_and_nothing_it_cannot_read(db):
    from src.analytics.quarantine_scope import not_counted_tally

    arts = _corpus(db)
    assert not_counted_tally(db) == {"not_screened": 0}
    _queue(db, arts[:2])
    assert not_counted_tally(db) == {"not_screened": 2}

    class _Broken:
        def execute(self, *_a, **_k):
            raise RuntimeError("unreadable")

    assert not_counted_tally(_Broken()) == {}


def test_the_worker_drains_the_queue_and_stamps_the_junk(db):
    from src.analytics.screening_drain import ScreeningDrain

    clean = _corpus(db)
    junk = [_junk(db, n) for n in range(2)]
    _queue(db, clean + junk)
    factory = sessionmaker(bind=db.get_bind(), future=True)
    drain = ScreeningDrain(session_factory=factory)
    assert drain.kick() is True
    drain._thread.join(30)
    assert drain.status()["state"] == "idle"
    assert drain.status()["screened"] == 5 and drain.status()["quarantined"] == 2
    db.expire_all()
    assert _queued(db) == 0
    assert db.query(Article).filter(Article.quarantined.is_(True)).count() == 2


def test_the_worker_waits_while_an_import_owns_the_machine(db, monkeypatch):
    import src.analytics.screening_drain as sd

    _queue(db, _corpus(db))
    owned = {"n": 0}

    def _owns() -> bool:
        owned["n"] += 1
        return owned["n"] <= 2

    monkeypatch.setattr(sd, "_import_owns_the_machine", _owns)
    monkeypatch.setattr(sd, "_POLL_S", 0.01)
    drain = sd.ScreeningDrain(session_factory=sessionmaker(bind=db.get_bind(), future=True))
    drain.kick()
    drain._thread.join(30)
    assert owned["n"] >= 3
    db.expire_all()
    assert _queued(db) == 0


def test_a_chunk_that_cannot_leave_the_queue_stops_the_worker(db, monkeypatch):
    """A queue row that a judged chunk does not remove would come back forever: the worker stops instead of spinning."""
    import src.analytics.quarantine_job as qj
    import src.analytics.screening_drain as sd

    _queue(db, _corpus(db))
    real = qj.default_quarantine_candidates_batch
    calls = {"n": 0}

    def _no_release(session, **kw):
        calls["n"] += 1
        kw["release_pending"] = False
        return real(session, **kw)

    monkeypatch.setattr(qj, "default_quarantine_candidates_batch", _no_release)
    drain = sd.ScreeningDrain(session_factory=sessionmaker(bind=db.get_bind(), future=True))
    drain.kick()
    drain._thread.join(30)
    assert calls["n"] == 1
    assert _queued(db) == 3, "nothing was judged as screened, so everything still waits"


def test_autostart_is_declined_by_its_switch(monkeypatch):
    import src.analytics.screening_drain as sd

    monkeypatch.setenv("OO_SCREENING_AUTOSTART", "0")
    started = []
    monkeypatch.setattr(sd.ScreeningDrain, "kick", lambda self: started.append(1) or True)
    assert sd.kick_if_allowed() is False and sd.kick_if_pending() is False
    assert started == []


def test_one_worker_per_process():
    from src.analytics.screening_drain import ScreeningDrain

    gate = threading.Event()
    drain = ScreeningDrain()
    drain._run = lambda: gate.wait(5)  # type: ignore[method-assign]
    try:
        assert drain.kick() is True
        assert drain.kick() is False
    finally:
        gate.set()
        drain._thread.join(5)


def test_the_merge_queues_what_it_adds_and_the_restore_does_not_screen_in_its_window():
    """Source pins: the article step queues the batch's new rows (not the ones that arrive quarantined), and the post-swap
    stage hands them to the worker whenever the corpus has the queue, screening in the window only what was not queued."""
    import inspect

    from src.backup import merge

    art = inspect.getsource(merge._merge_articles)
    assert "INSERT OR IGNORE INTO main.screening_pending" in art
    assert "NOT IN (SELECT id FROM main.articles WHERE quarantined IS 1)" in art
    src = inspect.getsource(merge)
    i = src.index("queued = _queued_for_screening(_q_sess, q_batches)")
    j = src.index("elif new_article_ids:", i)
    block = src[i:j]
    assert "kick_if_allowed()" in block
    # inside the queue branch, the window screens only what the queue does not hold and the import did not stamp
    k = block.index("default_quarantine_candidates_batch(")
    assert "_not_stamped([i for i in new_article_ids if i not in queued]" in block[:k]
    assert "screening_pending" in merge._MERGE_NOT_CARRIED


def test_a_queue_covering_the_whole_top_of_the_list_is_one_ordered_read(db):
    """Review of #2389: every counted article queued must not walk the keyword table page by page; the word simply drops."""
    arts = _corpus(db)
    _queue(db, arts)
    assert WORD not in _top(db)
    from src.analytics.screening_drain import ScreeningDrain

    drain = ScreeningDrain(session_factory=sessionmaker(bind=db.get_bind(), future=True))
    drain.kick()
    drain._thread.join(30)
    assert _top(db)[WORD]["articles"] == 3


def test_a_drain_bumps_the_epoch_once_not_once_per_chunk(db, monkeypatch):
    import src.analytics.screening_drain as sd
    from src.analytics.corpus_epoch import get_corpus_epoch

    clean = _corpus(db)
    junk = [_junk(db, n) for n in range(2)]
    _queue(db, clean + junk)
    monkeypatch.setattr(sd, "CHUNK", 1)  # five chunks
    before = get_corpus_epoch(db)
    drain = sd.ScreeningDrain(session_factory=sessionmaker(bind=db.get_bind(), future=True))
    drain.kick()
    drain._thread.join(30)
    db.expire_all()
    assert drain.status()["chunks"] == 5 and _queued(db) == 0
    assert get_corpus_epoch(db) == before + 1


def test_a_chunk_that_raises_is_tried_again_before_the_worker_stops(db, monkeypatch):
    import src.analytics.screening_drain as sd

    _queue(db, _corpus(db))
    monkeypatch.setattr(sd, "_RETRY_FIRST_S", 0.01)
    drain = sd.ScreeningDrain(session_factory=sessionmaker(bind=db.get_bind(), future=True))
    real = drain._one_chunk
    fails = {"n": 0}

    def _flaky() -> int:
        if fails["n"] < 2:
            fails["n"] += 1
            raise RuntimeError("database is locked")
        return real()

    drain._one_chunk = _flaky  # type: ignore[method-assign]
    drain.kick()
    drain._thread.join(30)
    assert drain.status()["state"] == "idle" and fails["n"] == 2
    db.expire_all()
    assert _queued(db) == 0


def test_a_kick_while_the_worker_runs_makes_it_read_the_queue_again():
    import src.analytics.screening_drain as sd

    calls = {"n": 0}
    gate = threading.Event()
    drain = sd.ScreeningDrain()

    def _chunk() -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            gate.wait(5)  # the worker is about to find the queue empty when the second kick arrives
        return 0

    drain._one_chunk = _chunk  # type: ignore[method-assign]
    drain._pay_bump = lambda *, force: None  # type: ignore[method-assign]
    import unittest.mock as um

    with um.patch.object(sd, "_import_owns_the_machine", lambda: False):
        assert drain.kick() is True
        assert drain.kick() is False
        gate.set()
        drain._thread.join(5)
    assert calls["n"] == 2, "the second kick was honoured by one more read"
    assert drain.kick() is True  # and a later kick starts a fresh run
    drain._thread.join(5)
