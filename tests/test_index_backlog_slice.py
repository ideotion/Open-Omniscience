"""The never-attempted indexing backlog drains on the server (2026-11-08, the background-mode thread).

Only the Insights page drained it, through its status poll, so an instance left running with its browser closed never caught
up. ``index_backlog_slice`` runs the same batches inside the idle-maintenance window, with the page's own rules: the backlog is
``never_attempted`` (never ``remaining``), a batch that does not shrink it ends the slice, and a stop is honoured between batches.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, KeywordMention, Source
from src.scheduler import maintenance as m

_REAL = (
    "Parliament approved the regional infrastructure budget after a long committee "
    "inquiry into energy policy and inflation across the northern districts. "
) * 6


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(m, "_backlog_clear_at", 0.0)
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Backlog News", domain="backlog.test", enabled=True))
    s.commit()
    return s


def _add(db, key: str, body: str = _REAL) -> Article:
    a = Article(url=f"https://backlog.test/{key}", canonical_url=f"https://backlog.test/{key}", source_id=1,
                title="", content=body, hash=key, language="en")
    db.add(a)
    db.commit()
    return a


def _indexed(db) -> set[int]:
    return {a for (a,) in db.query(KeywordMention.article_id).distinct()}


def test_a_backlog_drains_in_batches_and_says_so(db, monkeypatch):
    monkeypatch.setattr(m, "BACKLOG_BATCH", 3)
    ids = [_add(db, f"r{i}").id for i in range(7)]
    out = m.index_backlog_slice(db, budget_s=60)
    assert out["complete"] is True and out["ended"] == "drained"
    assert out["batches"] == 3 and out["attempted"] == 7 and out["newly_indexed"] == 7
    assert _indexed(db) == set(ids)


def test_an_empty_backlog_costs_one_check_and_no_batch(db):
    a = _add(db, "done")
    index_article(db, a, extractor=BaselineExtractor())
    out = m.index_backlog_slice(db, budget_s=60)
    assert out == {"complete": True, "batches": 0}
    # and the next window does not even check again for an hour
    assert m.index_backlog_slice(db, budget_s=60)["skipped"] == "checked_recently"


def test_an_article_indexed_before_the_stamp_existed_is_not_a_backlog(db):
    """keyword_indexed_at was added with no backfill: an old indexed article reads NULL and must not look pending forever."""
    a = _add(db, "legacy")
    index_article(db, a, extractor=BaselineExtractor())
    a.keyword_indexed_at = None
    db.commit()
    assert m.index_backlog_slice(db, budget_s=60) == {"complete": True, "batches": 0}


def test_a_stop_is_honoured_before_the_first_batch_and_between_batches(db, monkeypatch):
    monkeypatch.setattr(m, "BACKLOG_BATCH", 2)
    for i in range(6):
        _add(db, f"s{i}")
    calls = iter([False, True])
    out = m.index_backlog_slice(db, should_stop=lambda: next(calls, True), budget_s=60)
    assert out["ended"] == "stopping" and out["batches"] == 1 and out["complete"] is False
    assert out["never_attempted_left"] == 4


def test_the_budget_ends_a_slice_and_zero_declines_it(db, monkeypatch):
    monkeypatch.setattr(m, "BACKLOG_BATCH", 1)
    for i in range(4):
        _add(db, f"b{i}")
    out = m.index_backlog_slice(db, budget_s=1e-9)
    assert out["ended"] == "budget" and out["batches"] == 1 and out["complete"] is False
    assert m.index_backlog_slice(db, budget_s=0) == {"skipped": "disabled"}
    monkeypatch.setenv("OO_BACKLOG_BUDGET_S", "0")
    assert m.backlog_budget_s() == 0.0


def test_the_idle_window_runs_the_slice():
    from pathlib import Path

    src = Path(m.__file__).read_text(encoding="utf-8")
    assert "out[\"index_backlog\"] = index_backlog_slice(session, should_stop=stop)" in src


def test_a_stop_before_the_first_batch_never_reads_as_complete(db):
    """Opus read: left stayed None, `not left` read as drained, and the known backlog was hidden for an hour."""
    _add(db, "x")
    out = m.index_backlog_slice(db, should_stop=lambda: True, budget_s=60)
    assert out["complete"] is False and out["ended"] == "stopping" and out["batches"] == 0
    assert m.index_backlog_slice(db, budget_s=60)["complete"] is True  # not "checked_recently": it ran


@pytest.mark.parametrize("busy", ["reindex_running", "corpus_lease_held", "writer_job_running"])
def test_the_slice_yields_to_work_that_owns_the_same_rows(db, monkeypatch, busy):
    _add(db, "y")
    if busy == "reindex_running":
        from src.analytics import reindex_job

        monkeypatch.setattr(reindex_job, "get_reindex_manager",
                            lambda: type("M", (), {"status": lambda self: {"state": "running"}})())
    elif busy == "corpus_lease_held":
        from src.database import corpus_lease

        monkeypatch.setattr(corpus_lease, "active_leases", lambda: ["keyword-fold"])
    else:
        from src.jobs import background

        monkeypatch.setattr(background, "all_job_statuses", lambda: [{"running": True, "is_writer": True}])
    assert m.index_backlog_slice(db, budget_s=60) == {"skipped": busy}
    assert not _indexed(db)


def test_the_offline_timers_own_lease_is_not_a_rival(db, monkeypatch):
    from src.database import corpus_lease
    from src.scheduler import offline_maintenance

    assert offline_maintenance._LEASE == "offline-maintenance"
    monkeypatch.setattr(corpus_lease, "active_leases", lambda: [offline_maintenance._LEASE])
    _add(db, "z")
    assert m.index_backlog_slice(db, budget_s=60)["complete"] is True
