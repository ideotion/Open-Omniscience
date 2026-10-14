"""The backlog drain gives the write gate back: a batch commits at a hold target, or when a writer queues (2026-10-13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FAILURE THIS CLOSES (crash findings 2026-09-30, causes B and C). With nothing collecting, the drain
re-indexes at ``commit_batch=200`` and holds the single-writer gate from the batch's first article to its
commit: 36 s at the 333 articles a minute the field measured, 60 to 175 s on the machine that crashed. A
writer that arrives meanwhile (a save from the UI, the Wikipedia drain) waits the whole batch, and the
gate's watchdog logs the hold at its first sample past 60 s, so the log's "60.3 to 73.3 s" are detection
times and not lengths.

THE FIX IS A POLICY THE CALLER OWNS. ``reindex_articles`` takes ``should_flush(staged, held_s)``, asked after
every staged article; the drain hands it :func:`src.backup.merge.reindex_flush_policy`, which answers True
once the batch has held the gate for ``OO_REINDEX_HOLD_TARGET_S`` (default 10) or a writer is queued.
``commit_batch`` stays the CEILING: the policy can end a batch earlier and never later.

What is pinned, each with a mutant that fails it (the list is in the PR):

* the gate says how many threads are queued (``waiters``);
* the target's default, override and fallbacks, and 0 meaning "the count-only rule";
* the policy's two reasons, and that neither alone is enough;
* ``reindex_articles`` commits early when asked, never an empty batch, never past the width, and a batch's
  age restarts at each batch;
* a policy that raises is dropped, once, and the pass finishes;
* the count of commits, the early ones and the longest batch come back through ``stats``.

Time is a fake clock that moves only when an article is indexed, so no test here depends on a real second.
"""

from __future__ import annotations

import math
import threading
import time
import types
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import src.analytics.store as store_mod
from src.analytics.extract import BaselineExtractor
from src.analytics.store import reindex_articles
from src.backup import merge as merge_mod
from src.database.models import Article, Base, Source
from src.database.writer import (
    WriterGate,
    _on_after_transaction_end,
    _on_before_flush,
    _on_orm_execute,
    write_gate,
)

# --------------------------------------------------------------------------- #
# the gate says who is waiting                                                #
# --------------------------------------------------------------------------- #


def test_the_gate_counts_the_threads_queued_behind_its_holder():
    gate = WriterGate()
    assert gate.waiters() == 0
    gate.acquire()
    arrived = threading.Event()

    def _writer() -> None:
        arrived.set()
        gate.acquire()
        gate.release()

    t = threading.Thread(target=_writer, name="a-writer-that-arrives")
    t.start()
    try:
        assert arrived.wait(10)
        deadline = time.monotonic() + 10
        while gate.waiters() == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert gate.waiters() == 1, "one thread is parked behind the holder"
    finally:
        gate.release()
        t.join(timeout=30)
    assert not t.is_alive()
    assert gate.waiters() == 0, "a granted thread is no longer waiting"


# --------------------------------------------------------------------------- #
# the target and the policy                                                   #
# --------------------------------------------------------------------------- #


def test_the_hold_target_is_ten_seconds_unless_the_operator_says_otherwise(monkeypatch):
    monkeypatch.delenv("OO_REINDEX_HOLD_TARGET_S", raising=False)
    assert merge_mod.REINDEX_HOLD_TARGET_S == 10.0
    assert merge_mod.reindex_hold_target_s() == 10.0
    for raw, want in (("30", 30.0), ("2.5", 2.5), (" 4 ", 4.0), ("0", 0.0)):
        monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", raw)
        assert merge_mod.reindex_hold_target_s() == want, raw


@pytest.mark.parametrize("junk", ["abc", "-1", "nan", "inf", "-inf", "1e999", "5s"])
def test_an_unreadable_override_keeps_the_bound_instead_of_removing_it(monkeypatch, junk):
    """A typo must not switch the early commit off: that would put the 200-article holds back."""
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", junk)
    assert merge_mod.reindex_hold_target_s() == merge_mod.REINDEX_HOLD_TARGET_S


@pytest.mark.parametrize("raw", ["-0", "-0.0", "0.0", "+0"])
def test_a_negative_zero_is_a_plain_zero_and_is_published_as_one(monkeypatch, raw):
    """``float("-0")`` is ``-0.0``, which equals 0 and passes ``>= 0``: the drain published it as ``hold_target_seen``."""
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", raw)
    got = merge_mod.reindex_hold_target_s()
    assert got == 0.0 and math.copysign(1.0, got) == 1.0
    assert merge_mod.reindex_flush_policy() is None


def test_a_target_of_zero_is_the_count_only_rule_and_hands_out_no_policy(monkeypatch):
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", "0")
    assert merge_mod.reindex_flush_policy() is None
    assert merge_mod.reindex_flush_policy(0) is None
    monkeypatch.delenv("OO_REINDEX_HOLD_TARGET_S")
    assert callable(merge_mod.reindex_flush_policy())


def test_the_policy_ends_a_batch_on_age_or_on_a_queued_writer_and_on_neither_alone(monkeypatch):
    queued = {"n": 0}
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: queued["n"])
    policy = merge_mod.reindex_flush_policy(10.0)
    assert policy is not None

    assert policy(5, 9.99) is False, "young batch, nobody waiting: keep going"
    assert policy(5, 10.0) is True, "the target is reached"
    assert policy(1, 600.0) is True, "far past it"
    queued["n"] = 1
    assert policy(1, 1.0) is True, "a writer is queued and the batch has held the gate for the minimum: let it in at the next article"
    assert policy(1, 5.0) is True
    queued["n"] = 0
    assert policy(1, 5.0) is False, "and once nobody waits, back to age alone"


def test_a_queued_writer_cannot_end_a_batch_younger_than_the_minimum_hold(monkeypatch):
    """The bound that keeps a writer that is ALWAYS queued (the Wikipedia drain) from turning the drain into a commit per article."""
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: 3)
    assert merge_mod.REINDEX_QUEUED_WRITER_MIN_HOLD_S == 1.0
    policy = merge_mod.reindex_flush_policy(10.0)
    assert policy is not None
    assert policy(1, 0.0) is False, "an article was just staged: the gate is hardly held"
    assert policy(7, 0.999) is False, "seven articles, still under the minimum"
    assert policy(1, 1.0) is True, "the minimum reached with a writer waiting"
    # the minimum is for the QUEUE rule only; the age target stands alone, so a target under a second still commits at the target
    short = merge_mod.reindex_flush_policy(0.5)
    assert short is not None and short(1, 0.5) is True


# --------------------------------------------------------------------------- #
# reindex_articles obeys the policy                                           #
# --------------------------------------------------------------------------- #


def _corpus(*, gated: bool):
    """Seven articles in an in-memory store. ``gated`` attaches the REAL write-gate handlers to the session factory, as
    ``session.py`` does for the app's: ``hold_write_window`` then really takes the gate and the commit really gives it back."""
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, future=True)
    if gated:
        event.listen(maker, "before_flush", _on_before_flush)
        event.listen(maker, "do_orm_execute", _on_orm_execute)
        event.listen(maker, "after_transaction_end", _on_after_transaction_end)
    db = maker()
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    ids = []
    for i in range(7):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1, title="T",
            content=f"Climate policy number {i} shaped the energy debate and the summit.", hash=f"h{i}",
            country="fr", language="en", published_at=datetime(2024, 3, 1, tzinfo=UTC),
            created_at=datetime.now(UTC),
        )
        db.add(a)
        db.commit()
        ids.append(a.id)
    return db, ids


@pytest.fixture()
def corpus():
    """A GATED session: the hold figures below are the gate's, taken through the real ``hold_write_window``."""
    db, ids = _corpus(gated=True)
    yield db, ids
    db.close()


@pytest.fixture()
def ungated_corpus():
    """A session the gate does not cover (``hold_write_window`` returns False for it)."""
    db, ids = _corpus(gated=False)
    yield db, ids
    db.close()


@pytest.fixture()
def fake_clock(monkeypatch):
    """The store's clock moves 5 s per indexed article and at no other moment.

    Only ``monotonic`` is replaced (the one function ``store.py`` takes from ``time``), so a batch of
    ``k`` staged articles is exactly ``5 * k`` seconds old when the policy is asked."""
    now = {"t": 1000.0}
    real_index_article = store_mod.index_article

    def _slow_index_article(*a, **k):
        now["t"] += 5.0
        return real_index_article(*a, **k)

    monkeypatch.setattr(store_mod, "time", types.SimpleNamespace(monotonic=lambda: now["t"]))
    monkeypatch.setattr(store_mod, "index_article", _slow_index_article)
    return now


def _run(db, ids, *, commit_batch, should_flush=None):
    stats: dict = {}
    kw = {} if should_flush is None else {"should_flush": should_flush}
    out = reindex_articles(
        db, extractor=BaselineExtractor(), article_ids=ids, commit_batch=commit_batch, workers=0,
        stats=stats, **kw,
    )
    return out, stats


def test_without_a_policy_a_batch_ends_at_the_width_and_nowhere_else(corpus, fake_clock):
    db, ids = corpus
    out, stats = _run(db, ids, commit_batch=3)
    assert out == {"reindexed": 7, "failed": 0}
    assert stats["batch_commits"] == 3, "3 + 3 + 1"
    assert stats["early_batch_commits"] == 0
    assert stats["longest_batch_s"] == 15.0, "three articles of five seconds each, commit included at no cost"


def test_a_policy_that_says_no_changes_nothing(corpus, fake_clock):
    db, ids = corpus
    out, stats = _run(db, ids, commit_batch=3, should_flush=lambda staged, held_s: False)
    assert out == {"reindexed": 7, "failed": 0}
    assert (stats["batch_commits"], stats["early_batch_commits"]) == (3, 0)


def test_a_batch_that_has_held_the_gate_past_the_target_commits_and_the_age_restarts_each_batch(corpus, fake_clock):
    db, ids = corpus
    asked: list[tuple[int, float]] = []

    def _policy(staged: int, held_s: float) -> bool:
        asked.append((staged, held_s))
        return held_s >= 12.0

    out, stats = _run(db, ids, commit_batch=100, should_flush=_policy)

    assert out == {"reindexed": 7, "failed": 0}, "ending batches early loses no article"
    # 5, 10, 15 -> commit; 5, 10, 15 -> commit; 5 -> the final flush. A batch age that never restarted would commit EVERY
    # article after the first batch (the second batch's first article would already be 20 s old).
    assert asked == [(1, 5.0), (2, 10.0), (3, 15.0), (1, 5.0), (2, 10.0), (3, 15.0), (1, 5.0)]
    assert stats["batch_commits"] == 3 and stats["early_batch_commits"] == 2
    assert stats["longest_batch_s"] == 15.0


def test_a_policy_that_always_says_yes_still_stages_one_article_and_is_never_asked_of_an_empty_batch(corpus, fake_clock):
    db, ids = corpus
    asked: list[int] = []

    def _always(staged: int, held_s: float) -> bool:
        asked.append(staged)
        return True

    out, stats = _run(db, ids, commit_batch=100, should_flush=_always)

    assert out == {"reindexed": 7, "failed": 0}
    assert asked == [1] * 7, "one article per batch is the floor, and an empty batch is never asked about"
    assert stats["batch_commits"] == 7 and stats["early_batch_commits"] == 7


def test_the_policy_is_asked_only_of_a_batch_that_holds_an_article_and_not_after_a_width_flush(corpus, fake_clock):
    """After a width flush the batch is empty: asking then would hand a policy a zero it is documented never to see."""
    db, ids = corpus
    asked: list[int] = []

    def _policy(staged: int, held_s: float) -> bool:
        asked.append(staged)
        return False

    _run(db, ids, commit_batch=3, should_flush=_policy)
    # 1, 2 -> the third article fills the batch and the width commits it without asking; then 1, 2 again; then 1.
    assert asked == [1, 2, 1, 2, 1]


def test_the_width_stays_the_ceiling_when_the_policy_would_wait_longer(corpus, fake_clock):
    db, ids = corpus
    _, stats = _run(db, ids, commit_batch=2, should_flush=lambda staged, held_s: held_s >= 1000.0)
    assert stats["batch_commits"] == 4, "2 + 2 + 2 + 1: a policy can end a batch earlier, never later"
    assert stats["early_batch_commits"] == 0


def test_a_writer_that_is_always_queued_batches_the_drain_by_the_minimum_hold_not_one_article_a_commit(corpus, fake_clock, monkeypatch):
    """The pass with the real policy and a writer that never goes away: without the minimum this is seven commits for seven articles."""
    db, ids = corpus
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: 1)
    monkeypatch.setattr(merge_mod, "REINDEX_QUEUED_WRITER_MIN_HOLD_S", 12.0)  # the clock moves 5 s an article: 3 articles reach it
    policy = merge_mod.reindex_flush_policy(1000.0)

    out, stats = _run(db, ids, commit_batch=100, should_flush=policy)

    assert out == {"reindexed": 7, "failed": 0}
    assert stats["batch_commits"] == 3, "3 + 3 + 1, not 1 x 7"
    assert stats["early_batch_commits"] == 2
    assert stats["longest_batch_s"] == 15.0


def test_a_policy_that_raises_is_dropped_once_and_the_pass_finishes_at_the_width(corpus, fake_clock, caplog):
    db, ids = corpus
    calls = {"n": 0}

    def _boom(staged: int, held_s: float) -> bool:
        calls["n"] += 1
        raise RuntimeError("the policy's own words, which must not be recorded: s3cr3t-token")

    import logging

    with caplog.at_level(logging.WARNING):
        out, stats = _run(db, ids, commit_batch=3, should_flush=_boom)

    assert out == {"reindexed": 7, "failed": 0}
    assert calls["n"] == 1, "dropped for the rest of the call, not asked again on every article"
    assert (stats["batch_commits"], stats["early_batch_commits"]) == (3, 0), "the width alone decides from there"
    assert "RuntimeError" in caplog.text
    assert "s3cr3t-token" not in caplog.text, "the callable's text is its own: the class is all that is recorded"


def test_a_width_of_one_never_asks_the_policy(corpus, fake_clock):
    """``commit_batch=1`` is one commit per article already (the collector-running default), so there is nothing to end."""
    db, ids = corpus
    asked: list[int] = []

    def _policy(staged: int, held_s: float) -> bool:
        asked.append(staged)
        return True

    out, stats = _run(db, ids, commit_batch=1, should_flush=_policy)
    assert out == {"reindexed": 7, "failed": 0}
    assert asked == []
    # and it measures no batch: a 0.0 here would be published as "the drain's worst hold was an instant"
    assert stats["batch_commits"] == 0 and stats["longest_batch_s"] is None


# --------------------------------------------------------------------------- #
# what the stats call a hold                                                  #
# --------------------------------------------------------------------------- #


def test_a_commit_that_fails_is_not_counted_as_a_batch_commit_and_the_batch_is_still_redone(corpus, fake_clock, monkeypatch):
    """``batch_commits`` is where the commit LANDED: the failed one is redone one article at a time, and that redo is not a batch."""
    db, ids = corpus
    real_commit = db.commit
    failed_once = {"done": False}

    def _flaky_commit():
        # The first commit of the first BATCH (the clock has moved: an article was indexed); the epoch bump's commit before it is not one.
        if not failed_once["done"] and fake_clock["t"] > 1000.0:
            failed_once["done"] = True
            fake_clock["t"] += 100.0  # the hold went on for 100 s before the commit failed
            raise RuntimeError("disk I/O error")
        return real_commit()

    monkeypatch.setattr(db, "commit", _flaky_commit)
    out, stats = _run(db, ids, commit_batch=100, should_flush=lambda staged, held_s: True)

    assert out == {"reindexed": 7, "failed": 0}, "every article lands, the first through the one-at-a-time redo"
    assert (stats["batch_commits"], stats["early_batch_commits"]) == (6, 6), "the failed commit is in neither count"
    assert stats["longest_batch_s"] == 105.0, "but the hold it ended is the longest one: it is the long holds that fail"


def test_an_article_that_fails_ends_the_hold_it_was_in_and_that_hold_is_timed(corpus, fake_clock, monkeypatch):
    db, ids = corpus
    real = store_mod.index_article

    def _fails_on_the_third(session, art, **kw):
        if art.id == ids[2]:
            fake_clock["t"] += 50.0
            raise RuntimeError("a bad article")
        return real(session, art, **kw)

    monkeypatch.setattr(store_mod, "index_article", _fails_on_the_third)
    out, stats = _run(db, ids, commit_batch=100)

    assert out == {"reindexed": 6, "failed": 1}
    # two articles of 5 s staged and then 50 s into the third, all inside one gate hold that the rollback ended; the other four
    # articles are one 20 s batch.
    assert stats["longest_batch_s"] == 60.0


def test_a_batch_that_queued_for_another_writers_hold_is_not_charged_with_it(corpus, fake_clock, monkeypatch):
    """The clock starts when the batch HOLDS the gate, not when it asked: a wait behind a vacuum is the vacuum's hold."""
    db, ids = corpus
    state = {"held": False}

    def _window(session):
        if not state["held"]:
            fake_clock["t"] += 25.0  # the first article waited 25 s for someone else's hold to end
            state["held"] = True
        return True

    real_commit = db.commit

    def _commit():
        state["held"] = False  # the commit gives the gate back, so the next batch queues again
        return real_commit()

    monkeypatch.setattr("src.database.writer.hold_write_window", _window)
    monkeypatch.setattr(db, "commit", _commit)
    asked: list[tuple[int, float]] = []

    def _policy(staged: int, held_s: float) -> bool:
        asked.append((staged, held_s))
        return False

    _, stats = _run(db, ids, commit_batch=3, should_flush=_policy)

    assert asked == [(1, 5.0), (2, 10.0), (1, 5.0), (2, 10.0), (1, 5.0)], "the policy never sees the 25 s of waiting"
    assert stats["longest_batch_s"] == 15.0, "three articles of five seconds, not 15 + 25"


def test_a_window_that_could_not_be_taken_ends_no_hold_and_is_not_charged_to_the_previous_batch(corpus, fake_clock, monkeypatch):
    """The stamp of the batch before is stale: timing a hold that never began would report minutes the drain never held."""
    db, ids = corpus
    state = {"after_first_commit": False, "raised": False}
    real_commit = db.commit

    def _commit():
        if fake_clock["t"] > 1000.0:  # a batch's commit (an article was indexed), not the epoch bump's before it
            state["after_first_commit"] = True
        return real_commit()

    def _window(session):
        if state["after_first_commit"] and not state["raised"]:
            state["raised"] = True
            fake_clock["t"] += 500.0  # the wait that ended in an error
            raise RuntimeError("database is locked")
        return True

    monkeypatch.setattr("src.database.writer.hold_write_window", _window)
    monkeypatch.setattr(db, "commit", _commit)
    out, stats = _run(db, ids, commit_batch=3)

    assert out == {"reindexed": 6, "failed": 1}, "the article whose window failed is the one that failed"
    assert stats["longest_batch_s"] == 15.0, "three articles of five seconds: the 500 s was a wait, not a hold"


def test_a_session_the_gate_does_not_cover_publishes_no_hold(ungated_corpus, fake_clock):
    """There is no gate hold to time, so ``longest_batch_s`` is None: wall time from the first article is not a hold, and a
    figure that looks like one is worse than none. The commits are still counted, and the policy still sees the batch's age."""
    db, ids = ungated_corpus
    asked: list[tuple[int, float]] = []

    def _policy(staged: int, held_s: float) -> bool:
        asked.append((staged, held_s))
        return staged >= 3

    out, stats = _run(db, ids, commit_batch=100, should_flush=_policy)
    assert out == {"reindexed": 7, "failed": 0}
    assert stats["longest_batch_s"] is None
    assert stats["batch_commits"] == 3 and stats["early_batch_commits"] == 2
    assert asked[:3] == [(1, 5.0), (2, 10.0), (3, 15.0)], "the policy is asked of the batch's age whether or not a gate is held"


def test_the_real_window_is_taken_when_a_batch_opens_held_through_it_and_given_back_at_each_commit(corpus, fake_clock):
    """The real ``hold_write_window`` on a gated session, not a stand-in: the gate is held whenever the policy is asked (a
    batch is open), is free after the run, and the published hold is the time the batch held it."""
    db, ids = corpus
    held_when_asked: list[bool] = []

    def _policy(staged: int, held_s: float) -> bool:
        held_when_asked.append(bool(write_gate.stats()["held"]))
        return False

    before = write_gate.stats()["grants"]
    out, stats = _run(db, ids, commit_batch=3, should_flush=_policy)
    assert out == {"reindexed": 7, "failed": 0}
    # Seven articles at width 3: the policy is asked after articles 1, 2, 4, 5 and 7. A batch that fills the width
    # (articles 3 and 6) is flushed without asking, because there is nothing left to decide.
    assert held_when_asked == [True] * 5, "a batch is open every time the policy is asked, and the gate is held through it"
    assert not write_gate.stats()["held"], "the last commit gave it back"
    assert write_gate.stats()["grants"] - before >= 3, "one grant per batch (three batches), the epoch bump's besides"
    assert stats["longest_batch_s"] == 15.0 and stats["batch_commits"] == 3


def test_a_failed_batch_gives_the_real_gate_back_and_is_still_timed(corpus, fake_clock, monkeypatch):
    """The same real gate through a commit that raises: the rollback releases it, and the hold it ended is the one published."""
    db, ids = corpus
    real_commit = db.commit
    failed_once = {"done": False}

    def _flaky_commit():
        if not failed_once["done"] and fake_clock["t"] > 1000.0:
            failed_once["done"] = True
            fake_clock["t"] += 100.0
            raise RuntimeError("disk I/O error")
        return real_commit()

    monkeypatch.setattr(db, "commit", _flaky_commit)
    out, stats = _run(db, ids, commit_batch=100, should_flush=lambda staged, held_s: True)
    assert out == {"reindexed": 7, "failed": 0}
    assert stats["longest_batch_s"] == 105.0
    assert not write_gate.stats()["held"]
