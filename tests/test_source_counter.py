"""
S6 — the maintained per-Source article counter.

Pins: reconcile == live GROUP BY after ingest + delete; the honesty envelope (NULL -> live
fallback, populated -> exact/estimated by freshness); the read surface + idle maintenance +
delete-path wiring. Never a keyword_mentions->articles join (counts on Article.source_id).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.store import reconcile_source_counters, source_counter_envelope
from src.database.models import Article, Base, Source


def _session():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def _src(s, name):
    src = Source(name=name, domain=f"{name}.test")
    s.add(src)
    s.flush()
    return src


def _art(s, src_id, n):
    for i in range(n):
        s.add(Article(url=f"{src_id}-{i}", canonical_url=f"{src_id}-{i}", source_id=src_id,
                      title="t", content="body", hash=f"{src_id}-{i}", language="en",
                      created_at=datetime.now(UTC)))
    s.flush()


def _live(s):
    return dict(s.query(Article.source_id, func.count(Article.id)).group_by(Article.source_id).all())


def test_reconcile_equals_live_group_by_after_ingest_and_delete():
    s = _session()
    a, b = _src(s, "a"), _src(s, "b")
    _art(s, a.id, 5)
    _art(s, b.id, 2)
    s.commit()
    out = reconcile_source_counters(s)
    assert out["sources"] == 2 and out["drift_repaired"] == 2  # both went NULL -> value
    for src in (a, b):
        s.refresh(src)
        assert src.article_count == _live(s).get(src.id, 0)
    assert a.article_count == 5 and b.article_count == 2
    # delete some of a's articles (bulk, bypasses maintenance) -> reconcile repairs.
    for art in s.query(Article).filter_by(source_id=a.id).limit(3).all():
        s.delete(art)
    s.commit()
    out2 = reconcile_source_counters(s)
    s.refresh(a)
    assert a.article_count == 2 and out2["drift_repaired"] == 1  # only a changed


def test_envelope_null_falls_back_to_live():
    s = _session()
    a = _src(s, "a")
    _art(s, a.id, 4)
    s.commit()
    # never reconciled -> article_count is NULL -> the envelope counts live.
    env = source_counter_envelope(s, a)
    assert env["basis"] == "live" and env["value"] == 4 and env["as_of"] is None


def test_envelope_exact_when_fresh_and_estimated_when_stale():
    s = _session()
    a = _src(s, "a")
    _art(s, a.id, 3)
    s.commit()
    reconcile_source_counters(s)
    s.refresh(a)
    env = source_counter_envelope(s, a)
    assert env["basis"] == "exact" and env["value"] == 3 and env["as_of"]
    # make the reconcile stamp old -> estimated (stale but disclosed, not wrong).
    a.counter_reconciled_at = datetime.now(UTC) - timedelta(hours=48)
    s.commit()
    env2 = source_counter_envelope(s, a, fresh_within_hours=24.0)
    assert env2["basis"] == "estimated" and env2["value"] == 3


def test_no_score_key_in_the_reconcile_or_envelope():
    s = _session()
    a = _src(s, "a")
    _art(s, a.id, 1)
    s.commit()
    for payload in (reconcile_source_counters(s), source_counter_envelope(s, a)):
        for k in payload:
            assert not any(b in k.lower() for b in ("score", "ranking", "rating", "grade"))


# --------------------------------------------------------------------------- #
#  Wiring (source-inspected — no app import needed)
# --------------------------------------------------------------------------- #
def test_self_heal_backfills_the_counter_on_an_upgraded_store():
    """An EXISTING store (many articles) must not have a NULL-counter window after upgrade —
    the self-heal backfills from the live articles at once (the skeptic's sort-consistency fix)."""
    from sqlalchemy import text

    from src.database.maintenance import ensure_source_counter_columns

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        src = Source(name="a", domain="a.test")
        s.add(src)
        s.flush()
        _art(s, src.id, 7)
        s.commit()
        sid = src.id
    # simulate a pre-S6 store: drop the counter columns, then self-heal them back.
    with eng.begin() as c:
        c.execute(text("ALTER TABLE sources DROP COLUMN article_count"))
        c.execute(text("ALTER TABLE sources DROP COLUMN counter_reconciled_at"))
    added = ensure_source_counter_columns(eng)
    assert "sources.article_count" in added
    with Session() as s:
        got = s.get(Source, sid)
        assert got.article_count == 7 and got.counter_reconciled_at is not None  # backfilled


def test_source_io_reads_the_counter_with_a_freshness_aware_basis():
    src = Path("src/api/source_io.py").read_text(encoding="utf-8")
    # the O(articles) join+group_by for the count is gone; the counter is read.
    assert "db.query(Source, art_count).outerjoin" not in src
    assert "Source.article_count" in src and '"count_basis"' in src
    # the basis is freshness-aware (a stale counter is "estimated", never a wrong "exact").
    assert "counter_reconciled_at" in src and '"estimated"' in src
    # the "articles" sort coalesces NULL so order never contradicts the displayed count.
    assert "func.coalesce(Source.article_count" in src


def test_reconcile_is_wired_into_idle_maintenance_delete_and_restore():
    for path in ("src/scheduler/maintenance.py", "src/ingest/email.py", "src/backup/merge.py"):
        assert "reconcile_source_counters" in Path(path).read_text(encoding="utf-8"), path
