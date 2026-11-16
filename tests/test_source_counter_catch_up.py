"""Row 75 (field test 2026-11-14, report 5.5): ``Source.article_count`` read low on 10-134 sources per instance.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

No write path maintains the counter; only the reconcile sets it, and that runs in the idle window a continuously
collecting machine does not get. ``catch_up_source_counters`` recounts, at each pass end, the sources with an article
above a watermark. Pinned: it repairs exactly those sources, leaves the others' stamps alone, starts from the oldest
stamp on a store without a watermark, skips a never-counted store, and the pass tail calls it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.store import (
    SOURCE_COUNTER_WATERMARK_KEY,
    _cursor_get,
    catch_up_source_counters,
    reconcile_source_counters,
)
from src.database.models import Article, Base, Source

ROOT = Path(__file__).resolve().parents[1]


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def _src(s, name):
    src = Source(name=name, domain=f"{name}.test")
    s.add(src)
    s.flush()
    return src


_seq = [0]


def _art(s, src_id, n, *, at=None):
    for _ in range(n):
        _seq[0] += 1
        k = _seq[0]
        s.add(Article(url=f"u{k}", canonical_url=f"u{k}", source_id=src_id, title="t", content="body",
                      hash=f"h{k}", language="en", created_at=at or datetime.now(UTC)))
    s.flush()


def _live(s, sid):
    return s.query(func.count(Article.id)).filter(Article.source_id == sid).scalar()


def test_a_pass_end_recounts_only_the_sources_that_gained_articles():
    s = _session()
    wiki, rss, quiet = _src(s, "wiki"), _src(s, "rss"), _src(s, "quiet")
    early = datetime.now(UTC) - timedelta(hours=2)  # older than the catch-up's created_at margin
    _art(s, wiki.id, 5, at=early)
    _art(s, rss.id, 3, at=early)
    _art(s, quiet.id, 2, at=early)
    s.commit()
    reconcile_source_counters(s)  # the idle-window count, which sets the watermark
    stamp_quiet = s.get(Source, quiet.id).counter_reconciled_at
    _art(s, wiki.id, 4)  # the stream keeps adding while no idle window comes
    _art(s, rss.id, 1)
    s.commit()
    assert s.get(Source, wiki.id).article_count == 5  # the field symptom: low
    out = catch_up_source_counters(s)
    assert out["sources"] == 2 and out["start"] == "watermark"
    s.expire_all()
    for src in (wiki, rss, quiet):
        assert s.get(Source, src.id).article_count == _live(s, src.id)
    assert s.get(Source, quiet.id).counter_reconciled_at == stamp_quiet  # not recounted, so not re-stamped
    assert _cursor_get(s, SOURCE_COUNTER_WATERMARK_KEY) == s.query(func.max(Article.id)).scalar()
    again = catch_up_source_counters(s)
    assert again["sources"] == 2  # the margin re-reads the recent articles; the counts stay exact
    s.expire_all()
    assert s.get(Source, quiet.id).counter_reconciled_at == stamp_quiet


def test_a_store_without_a_watermark_starts_from_the_oldest_stamp():
    """An upgraded store has counters from an old idle count and no watermark yet."""
    s = _session()
    a, b = _src(s, "a"), _src(s, "b")
    old = datetime.now(UTC) - timedelta(hours=6)
    _art(s, a.id, 3, at=old - timedelta(hours=1))
    _art(s, b.id, 2, at=old - timedelta(hours=1))
    s.commit()
    for src, n in ((a, 3), (b, 2)):
        row = s.get(Source, src.id)
        row.article_count, row.counter_reconciled_at = n, old
    s.commit()
    _art(s, a.id, 2)  # after the stamp
    s.commit()
    out = catch_up_source_counters(s)
    assert out["start"] == "oldest-stamp" and out["sources"] == 1
    s.expire_all()
    assert s.get(Source, a.id).article_count == 5
    assert s.get(Source, b.id).counter_reconciled_at.replace(tzinfo=None) == old.replace(tzinfo=None)


def test_a_never_counted_store_is_left_to_the_live_count():
    s = _session()
    a = _src(s, "a")
    _art(s, a.id, 2)
    s.commit()
    assert catch_up_source_counters(s) == {"skipped": "never-reconciled"}
    assert s.get(Source, a.id).article_count is None  # NULL: the readers count live


def test_the_pass_tail_catches_the_counters_up():
    src = (ROOT / "src" / "scheduler" / "runner.py").read_text(encoding="utf-8")
    assert '_tail_phase("source-counters"' in src and "catch_up_source_counters" in src


def test_a_reused_id_below_the_watermark_is_still_counted():
    """articles.id has no AUTOINCREMENT: delete the newest rows and the next inserts take their ids (Opus read)."""
    s = _session()
    a, b = _src(s, "a"), _src(s, "b")
    _art(s, a.id, 4)
    s.commit()
    reconcile_source_counters(s)
    top = s.query(func.max(Article.id)).scalar()
    assert _cursor_get(s, SOURCE_COUNTER_WATERMARK_KEY) == top  # the unscoped count sets the watermark
    newest = s.query(Article).filter(Article.source_id == a.id).order_by(Article.id.desc()).limit(2).all()
    for art in newest:
        s.delete(art)
    s.commit()
    _art(s, b.id, 2)  # takes the two freed ids, at or below the watermark
    s.commit()
    assert s.query(func.max(Article.id)).scalar() == top
    out = catch_up_source_counters(s)
    assert out["sources"] >= 1
    s.expire_all()
    assert s.get(Source, b.id).article_count == _live(s, b.id) == 2


def test_a_catch_up_naming_more_sources_than_one_query_can_bind_still_runs(monkeypatch):
    """The chunk is shrunk so a small store needs many IN lists; every chunk's sources are counted."""
    import src.analytics.store as store

    monkeypatch.setattr(store, "_SOURCE_ID_CHUNK", 7)
    s = _session()
    srcs = [_src(s, f"s{i}") for i in range(2000)]
    s.commit()
    reconcile_source_counters(s)
    for src in srcs:
        _art(s, src.id, 1)
    s.commit()
    out = catch_up_source_counters(s)
    assert out["sources"] == 2000, out
    s.expire_all()
    assert all(s.get(Source, src.id).article_count == 1 for src in srcs[::97])


def test_a_failing_catch_up_rolls_back_and_says_so(monkeypatch):
    import src.analytics.store as store

    s = _session()
    a = _src(s, "a")
    _art(s, a.id, 1)
    s.commit()
    reconcile_source_counters(s)
    _art(s, a.id, 1)
    s.commit()

    def boom(*_a, **_k):
        raise RuntimeError("x")

    monkeypatch.setattr(store, "reconcile_source_counters", boom)
    assert catch_up_source_counters(s) == {"skipped": "error"}
    s.expire_all()
    assert s.get(Source, a.id).article_count == 1  # unchanged, and the next pass retries
