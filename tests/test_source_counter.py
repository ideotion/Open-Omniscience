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


# --------------------------------------------------------------------------- #
# F6: 86,470 sources, 32 minutes, and a docstring that said "sources are few"  #
# --------------------------------------------------------------------------- #


def _seed(session, *, sources=4, per_source=3):
    """A corpus with a known per-source count, and deliberately wrong counters."""
    made = []
    for i in range(sources):
        src = _src(session, f"f6s{i}")
        src.article_count = 999
        made.append(src)
    session.flush()
    for src in made:
        _art(session, src.id, per_source)
    session.commit()
    return [src.id for src in made]


def test_an_unscoped_run_still_reconciles_every_source():
    """The authoritative whole-corpus repair is UNCHANGED, and the scheduler's maintenance
    pass still calls it that way. Scoping must not quietly become the only mode."""
    s = _session()
    ids = _seed(s)
    out = reconcile_source_counters(s)

    assert out["scope"] == "all"
    assert out["sources"] == len(ids) and out["drift_repaired"] == len(ids)
    rows = s.query(Source).filter(Source.id.in_(ids)).all()
    assert {r.article_count for r in rows} == {3}
    assert all(r.counter_reconciled_at is not None for r in rows)


def test_a_scoped_run_touches_ONLY_the_named_sources():
    """R25/F6: an import knows which sources it touched, and the ones it did not touch
    cannot have drifted from it. 86,470 sources at 32 minutes is what the unscoped call
    cost inside the import's corpus-epoch bump."""
    s = _session()
    ids = _seed(s)
    out = reconcile_source_counters(s, source_ids=ids[:2])

    assert out["scope"] == "scoped" and out["scoped_to"] == 2 and out["sources"] == 2
    by_id = {r.id: r for r in s.query(Source).all()}
    assert [by_id[i].article_count for i in ids[:2]] == [3, 3]
    # ...and the untouched ones keep their wrong counter, because nothing verified them.
    assert [by_id[i].article_count for i in ids[2:]] == [999, 999]


def test_a_scoped_run_STAMPS_ONLY_WHAT_IT_VERIFIED():
    """THE HONESTY CLAUSE, and the reason scoping is not free. `source_counter_envelope`
    reads `counter_reconciled_at` to say exact vs estimated. Stamping a source this call
    never looked at would be a false freshness claim -- an untouched source keeps its older
    stamp and is honestly reported as older."""
    s = _session()
    ids = _seed(s)
    reconcile_source_counters(s, source_ids=ids[:2])

    by_id = {r.id: r for r in s.query(Source).all()}
    assert all(by_id[i].counter_reconciled_at is not None for i in ids[:2])
    assert all(by_id[i].counter_reconciled_at is None for i in ids[2:]), (
        "a source this run never verified was stamped as verified"
    )


def test_an_empty_scope_is_a_no_op_rather_than_a_whole_corpus_run():
    """THE DIRECTION THAT MATTERS. `source_ids=[]` means "nothing was touched"; falling
    back to the whole corpus there would turn the cheapest possible call into the most
    expensive one, which is precisely the 32 minutes this change exists to remove."""
    s = _session()
    ids = _seed(s)
    out = reconcile_source_counters(s, source_ids=[])

    assert out["sources"] == 0 and out["scope"] == "scoped"
    rows = s.query(Source).filter(Source.id.in_(ids)).all()
    assert {r.article_count for r in rows} == {999}


def test_a_source_with_no_articles_is_reconciled_to_zero_not_skipped():
    """A source whose articles all went away must go to 0, not keep its old count. The
    GROUP BY has no row for it, so this is the branch a `live.get(sid, 0)` default carries
    -- and the one a naive "iterate the GROUP BY" rewrite would silently drop."""
    s = _session()
    ids = _seed(s)
    s.query(Article).filter(Article.source_id == ids[0]).delete()
    s.commit()

    reconcile_source_counters(s, source_ids=[ids[0]])
    assert s.get(Source, ids[0]).article_count == 0


def test_the_docstring_no_longer_CLAIMS_sources_are_few():
    """The claim that made this cost invisible for months sat directly above a loop that
    flushed one UPDATE per source: "CHEAP by design: sources are few (hundreds-thousands)".
    The phrase survives only inside the correction that names what it cost -- asserted that
    way round, because deleting the history would lose the reason anyone should care."""
    import inspect

    doc = inspect.getdoc(reconcile_source_counters) or ""

    # It must still SAY what it cost -- deleting the history would lose the reason
    # anyone should care that this call is now scopeable.
    assert "86,470" in doc and "32 MINUTES" in doc.upper()

    # ...and the old claim may survive ONLY as quoted history. Asserting its plain
    # ABSENCE was this test's first cut and it failed against the correction that
    # quotes it -- a guard that forbids naming the defect is a guard against the
    # documentation, not against the defect.
    for line in doc.splitlines():
        if "CHEAP by design" in line or "sources are few" in line:
            assert "USED TO SAY" in line, f"stated as a live claim: {line}"
