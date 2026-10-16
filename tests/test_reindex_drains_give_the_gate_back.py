"""The three drains that ended a batch by count alone now hand the batch the hold policy too (WAL / disk, write-gate holds, 2026-10-16).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT WAS LEFT. ``reindex_articles(..., should_flush=)`` and ``merge.reindex_flush_policy`` (2026-10-13) let a batch end at the hold target
or when a writer queues, and the backlog drain handed it to every batch. Three callers still ended a batch by its width alone:

* ``store.reindex_all_batch`` had no ``should_flush`` parameter, so nothing above it could pass one;
* ``ReindexJobManager`` (the corpus-wide re-index) called it with ``OO_REINDEX_COMMIT_BATCH`` as the only bound;
* ``merge.run_restore``'s post-merge re-index ran at ``import_reindex_commit_batch()`` (200) with no policy, because "nothing else is
  writing" while the import owns the machine -- and a save from the UI still waits behind 200 articles, 36 s at the field's rate.

What is pinned, each with a mutant that fails it: the parameter is forwarded and its default is the count rule; the job hands every page
a policy, re-reads the target per page, and counts how its batches ended; the restore's call hands one and publishes the target in force.
Time is a fake clock that moves only when an article is indexed.
"""

from __future__ import annotations

import ast
import inspect
import types
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.analytics.reindex_job as job_mod
import src.analytics.store as store_mod
from src.analytics.extract import BaselineExtractor
from src.analytics.reindex_job import ReindexJobManager
from src.analytics.store import reindex_all_batch
from src.backup import merge as merge_mod
from src.database.models import Article, Base, Source


@pytest.fixture()
def world(tmp_path):
    """Seven articles in a shared in-memory store (the job's own thread sees them) and a clock that moves 5 s per indexed article."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, future=True, autoflush=False)
    with maker() as s:
        s.add(Source(name="S", domain="x.test", country="fr"))
        s.commit()
        for i in range(7):
            s.add(
                Article(
                    url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1, title="T",
                    content=f"Climate policy number {i} shaped the energy debate and the summit.", hash=f"h{i}",
                    country="fr", language="en", published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
                )
            )
        s.commit()
    yield maker, tmp_path
    engine.dispose()


@pytest.fixture()
def fake_clock(monkeypatch):
    now = {"t": 1000.0}
    real_index_article = store_mod.index_article

    def _slow_index_article(*a, **k):
        now["t"] += 5.0
        return real_index_article(*a, **k)

    monkeypatch.setattr(store_mod, "time", types.SimpleNamespace(monotonic=lambda: now["t"]))
    monkeypatch.setattr(store_mod, "index_article", _slow_index_article)
    return now


# --------------------------------------------------------------------------- #
#  store.reindex_all_batch forwards the caller's policy
# --------------------------------------------------------------------------- #
def _batch(maker, *, should_flush=None, commit_batch=100):
    stats: dict = {}
    kw = {} if should_flush is None else {"should_flush": should_flush}
    with maker() as s:
        out = reindex_all_batch(
            s, extractor=BaselineExtractor(), limit=100, after_id=0, commit_batch=commit_batch, workers=0, stats=stats, **kw
        )
    return out, stats


def test_reindex_all_batch_hands_the_callers_policy_to_the_pass(world, fake_clock):
    maker, _ = world
    out, stats = _batch(maker, should_flush=lambda staged, held_s: held_s >= 12.0)
    assert (out["reindexed"], out["failed"], out["done"]) == (7, 0, True), "ending batches early loses no article"
    assert stats["batch_commits"] == 3 and stats["early_batch_commits"] == 2, "3 + 3 + 1, the policy ended two of them"


def test_reindex_all_batch_without_a_policy_is_the_count_rule_byte_for_byte(world, fake_clock):
    maker, _ = world
    out, stats = _batch(maker)
    assert out["reindexed"] == 7
    assert stats["batch_commits"] == 1 and stats["early_batch_commits"] == 0, "one batch at the width, no early commit"
    assert inspect.signature(reindex_all_batch).parameters["should_flush"].default is None


def test_reindex_all_batch_passes_the_very_callable_it_was_given(world, monkeypatch):
    """Identity, not behaviour: a wrapper that swallowed or replaced the policy would pass the tests above on a slow enough clock."""
    maker, _ = world
    seen: dict = {}

    def _spy(session, **kw):
        seen.update(kw)
        return {"reindexed": 0, "failed": 0}

    monkeypatch.setattr(store_mod, "reindex_articles", _spy)

    def _policy(staged, held_s):
        return False

    _batch(maker, should_flush=_policy)
    assert seen["should_flush"] is _policy


# --------------------------------------------------------------------------- #
#  the job
# --------------------------------------------------------------------------- #
def _join(mgr, t=30.0):
    if mgr._thread is not None:
        mgr._thread.join(t)


def _run_job(maker, tmp_path):
    mgr = ReindexJobManager(state_path=tmp_path / "reindex_state.json")
    mgr.start(_session_factory=maker, _extractor=BaselineExtractor())
    _join(mgr)
    return mgr.status()


def test_the_job_hands_every_batch_the_policy_and_counts_how_they_ended(world, fake_clock, monkeypatch):
    maker, tmp = world
    monkeypatch.setenv("OO_REINDEX_COMMIT_BATCH", "100")
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", "12")
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: 0)

    status = _run_job(maker, tmp)

    assert status["state"] == "done" and status["tally"]["reindexed"] == 7
    # 5, 10, 15 -> commit; 5, 10, 15 -> commit; 5 -> the final flush. The width alone would be ONE commit of 7 articles, 35 s of gate.
    assert status["tally"]["batch_commits"] == 3 and status["tally"]["early_batch_commits"] == 2


def test_a_target_of_zero_is_the_count_rule_in_the_job_too(world, fake_clock, monkeypatch):
    maker, tmp = world
    monkeypatch.setenv("OO_REINDEX_COMMIT_BATCH", "100")
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", "0")

    status = _run_job(maker, tmp)

    assert status["state"] == "done" and status["tally"]["reindexed"] == 7
    assert status["tally"]["batch_commits"] == 1 and status["tally"]["early_batch_commits"] == 0


def test_the_job_re_reads_the_target_for_every_page(world, monkeypatch):
    """A run measured in days must follow the knob: the operator may change it between two pages."""
    maker, tmp = world
    monkeypatch.setattr(job_mod, "_BATCH", 3)
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: 0)
    targets = iter([1000.0, 4.0, 0.0])
    monkeypatch.setattr("src.backup.merge.reindex_hold_target_s", lambda: next(targets))
    seen: list = []

    def _page(session, *, extractor, limit, after_id, should_flush=None, **kw):
        seen.append(should_flush)
        rows = session.query(Article.id).filter(Article.id > after_id).order_by(Article.id).limit(limit).all()
        last = rows[-1][0] if rows else after_id
        remaining = session.query(Article.id).filter(Article.id > last).count()
        return {"reindexed": len(rows), "failed": 0, "last_id": last, "remaining": remaining, "done": remaining == 0}

    monkeypatch.setattr(store_mod, "reindex_all_batch", _page)

    status = _run_job(maker, tmp)

    assert status["state"] == "done" and len(seen) == 3, "7 articles in pages of 3"
    first, second, third = seen
    assert callable(first) and first(1, 999.9) is False and first(1, 1000.0) is True
    assert callable(second) and second(1, 3.9) is False and second(1, 4.0) is True
    assert third is None, "0 is the count-only rule, read for this page and no other"


def test_the_batch_counts_add_up_across_pages_and_do_not_restart_on_each(world, fake_clock, monkeypatch):
    """A run is many pages: the tally is a running total, so the last page's two commits are not the run's two commits."""
    maker, tmp = world
    monkeypatch.setattr(job_mod, "_BATCH", 3)
    monkeypatch.setenv("OO_REINDEX_COMMIT_BATCH", "100")
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", "12")
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: 0)

    tally = _run_job(maker, tmp)["tally"]

    # pages of 3, 3 and 1: the policy ends the first two at their third article (15 s old), the last is a final flush
    assert tally["reindexed"] == 7
    assert tally["batch_commits"] == 3 and tally["early_batch_commits"] == 2


def test_the_batch_counts_are_whole_numbers_because_the_persisted_tally_is_int_only(world, fake_clock, monkeypatch):
    """``_load_persisted`` int()s every tally value, so a float here would be truncated across a restart: both counts must be ints."""
    maker, tmp = world
    monkeypatch.setenv("OO_REINDEX_COMMIT_BATCH", "100")
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", "12")
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: 0)

    tally = _run_job(maker, tmp)["tally"]

    assert all(isinstance(v, int) for v in tally.values())
    assert tally["batch_commits"] == 3 and tally["early_batch_commits"] == 2


# --------------------------------------------------------------------------- #
#  the restore's re-index
# --------------------------------------------------------------------------- #
def _run_restore_tree() -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(merge_mod))
    (fn,) = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_restore"]
    return fn


def test_run_restore_hands_its_reindex_the_policy_and_the_target_it_publishes():
    calls = [
        n
        for n in ast.walk(_run_restore_tree())
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "reindex_imported_articles"
    ]
    assert len(calls) == 1, "one post-swap re-index call"
    (flush,) = [k for k in calls[0].keywords if k.arg == "should_flush"]
    assert isinstance(flush.value, ast.Call) and isinstance(flush.value.func, ast.Name)
    assert flush.value.func.id == "_restore_reindex_policy", "the policy comes from the one helper that also publishes the target"
    assert [a.id for a in flush.value.args if isinstance(a, ast.Name)] == ["_rx_stats"], "and publishes it on the report's re-index block"


def test_the_restore_helper_publishes_the_target_in_force_and_returns_the_policy(monkeypatch):
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: 0)
    monkeypatch.delenv("OO_REINDEX_HOLD_TARGET_S", raising=False)
    stats: dict = {}
    policy = merge_mod._restore_reindex_policy(stats)
    assert stats == {"hold_target_s": 10.0}
    assert callable(policy) and policy(1, 9.9) is False and policy(1, 10.0) is True


def test_the_restore_helper_with_a_target_of_zero_returns_no_policy_and_says_so(monkeypatch):
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", "0")
    stats: dict = {}
    assert merge_mod._restore_reindex_policy(stats) is None
    assert stats == {"hold_target_s": 0.0}, "the rule that ran is published beside the seconds it produced"


def test_the_restore_helper_re_reads_the_knob_on_every_call(monkeypatch):
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: 0)
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", "25")
    first: dict = {}
    merge_mod._restore_reindex_policy(first)
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", "4")
    second: dict = {}
    merge_mod._restore_reindex_policy(second)
    assert (first["hold_target_s"], second["hold_target_s"]) == (25.0, 4.0)
