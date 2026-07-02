"""
Recursive-augmentation diagnostic logs (maintainer 2026-07-02): the 5 logs that let a
developer find bugs WITHOUT the operator spotting each by eye.

  #1 frontend JS-error capture   #2 request-latency + event-loop-block
  #3 slow-query + EXPLAIN         #4 schema/index drift
  #5 corpus-integrity/counter-drift

These test the pure module logic against a real in-memory SQLite corpus (no crypto, no
network), so they run everywhere. The FastAPI endpoint wiring is covered by the
diagnostics endpoint suite / CI.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def session() -> Session:
    eng = create_engine("sqlite://", future=True)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


def _seed(s: Session, *, drift: bool = False, orphan: bool = False) -> None:
    src = Source(name="S", domain="s.example")
    s.add(src)
    s.flush()
    a = Article(
        title="A", content="x", url="http://s.example/a",
        canonical_url="http://s.example/a", source_id=src.id, hash="h1",
    )
    s.add(a)
    s.flush()
    k = Keyword(term="alpha", normalized_term="alpha")
    s.add(k)
    s.flush()
    s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=3))
    # A correctly-maintained corpus: the counters match the live aggregate (3 mentions,
    # 1 article). index_article maintains these in production; the raw seed sets them.
    k.mention_count = 3
    k.article_count = 1
    if drift:  # stored counters lie
        k.mention_count = 99
        k.article_count = 9
    if orphan:  # a keyword with zero mentions (the prune target)
        s.add(Keyword(term="orphan", normalized_term="orphan"))
    s.commit()


# -- #4 schema drift ------------------------------------------------------------- #


def test_schema_drift_clean_on_a_fresh_schema(session):
    from src.monitoring.schema_drift import schema_drift

    r = schema_drift(session)
    assert r["supported"] is True
    assert r["drift"] is False
    assert r["counts"]["missing_tables"] == 0
    assert r["counts"]["missing_columns"] == 0
    assert r["counts"]["missing_indexes"] == 0


def test_schema_drift_detects_a_missing_column(session):
    from src.monitoring.schema_drift import schema_drift
    from sqlalchemy import text

    # Simulate a self-heal gap: drop a column the model declares. Drop the index that
    # covers it first (SQLite refuses to drop an indexed column).
    session.execute(text("DROP INDEX IF EXISTS idx_keyword_mention_count"))
    session.execute(text("ALTER TABLE keywords DROP COLUMN mention_count"))
    session.commit()
    r = schema_drift(session)
    assert r["drift"] is True
    assert r["counts"]["missing_columns"] >= 1
    kw = next(t for t in r["tables"] if t["table"] == "keywords")
    assert "mention_count" in kw["missing_columns"]


# -- #5 corpus integrity --------------------------------------------------------- #


def test_integrity_clean_corpus_has_no_drift(session):
    from src.monitoring.integrity import corpus_integrity

    _seed(session)
    r = corpus_integrity(session, sample=100)
    assert r["supported"] is True
    assert r["drift"] is False
    assert r["orphan_keywords"] == 0
    assert r["counter_drift"]["keywords_with_mention_drift"] == 0


def test_integrity_flags_counter_drift_and_orphans(session):
    from src.monitoring.integrity import corpus_integrity

    _seed(session, drift=True, orphan=True)
    r = corpus_integrity(session, sample=100)
    assert r["drift"] is True
    assert r["orphan_keywords"] == 1
    cd = r["counter_drift"]
    assert cd["keywords_with_mention_drift"] == 1
    assert cd["keywords_with_article_drift"] == 1
    ex = cd["examples"][0]
    assert ex["mention_count"] == 99 and ex["live_mentions"] == 3


# -- #3 slow query + EXPLAIN ----------------------------------------------------- #


def test_slowquery_normalises_and_records(session):
    from src.monitoring import slowquery

    slowquery._RING.clear()
    slowquery._AGG.clear()
    slowquery._record("SELECT * FROM keywords WHERE id = 42 AND term = 'hi'", 1234.0)
    got = slowquery.recent(10)
    assert got, "the slow query was recorded"
    # bound values stripped — no corpus content leaks, identical shapes aggregate
    assert "42" not in got[-1]["sql"]
    assert "'hi'" not in got[-1]["sql"]
    assert "'?'" in got[-1]["sql"] and " = ?" in got[-1]["sql"]


def test_slowquery_explain_flags_only_bare_scans(session):
    from src.monitoring.slowquery import explain_probes

    _seed(session)
    probes = explain_probes(session)
    assert probes, "the EXPLAIN probes ran"
    for p in probes:
        if "plan" in p:
            # a plan step that is a SCAN WITHOUT an index is the only thing flagged
            for step in p["scans"]:
                assert "USING" not in step.upper()


# -- #2 latency ------------------------------------------------------------------ #


def test_latency_percentiles_and_block_events():
    from src.monitoring import latency

    latency._ROUTES.clear()
    latency._EVENTS.clear()
    for i, ms in enumerate([10.0, 20.0, 30.0, 40.0, 1000.0]):
        latency.note_start(i, "GET /api/x")
        latency.record(i, "GET /api/x", 200, ms)
    s = latency.summary()
    route = next(r for r in s["routes"] if r["route"] == "GET /api/x")
    assert route["count"] == 5
    assert route["max_ms"] == 1000.0
    assert route["p50_ms"] <= route["p99_ms"]
    # a synthetic loop-block event is recorded above threshold
    latency._record_block(latency._loop_block_ms() + 100.0)
    assert latency.summary()["watchdog"]["events_captured"] >= 1


# -- #1 frontend error capture --------------------------------------------------- #


def test_frontend_error_capture_and_summary(tmp_path, monkeypatch):
    import src.monitoring.errorlog as el

    monkeypatch.setattr(el, "_log_path", lambda: tmp_path / "app_errors.jsonl")
    el._frontend_last.clear()
    el.note_boot()
    el.note_frontend_error("error", "t is not defined", source="app.js:123", ui_lang="fr")
    recs = [r for r in el.recent_errors(50) if r.get("level") == "FRONTEND"]
    assert len(recs) == 1
    assert recs[0]["kind"] == "error"
    assert recs[0]["message"] == "t is not defined"
    summ = el.summary()
    assert summ["frontend_errors_total"] == 1
    assert summ["frontend_kind_breakdown"].get("error") == 1


def test_frontend_error_is_throttled(tmp_path, monkeypatch):
    import src.monitoring.errorlog as el

    monkeypatch.setattr(el, "_log_path", lambda: tmp_path / "app_errors.jsonl")
    el._frontend_last.clear()
    for _ in range(5):  # identical → collapsed to one within the throttle window
        el.note_frontend_error("error", "same boom", source="x.js")
    recs = [r for r in el.recent_errors(50) if r.get("level") == "FRONTEND"]
    assert len(recs) == 1


# -- automatic keyword cleanup (maintainer 2026-07-02) --------------------------- #


def test_automatic_keyword_cleanup_prunes_orphans_then_gates_fresh(session, tmp_path, monkeypatch):
    """The cheap cleanup runs unprompted (prune orphans + reconcile language), records a
    marker, and is a no-op within the freshness window — no manual "Clean up keywords"."""
    import src.analytics.store as store

    monkeypatch.setattr(store, "_cleanup_marker_path", lambda: tmp_path / "keyword_cleanup.json")
    _seed(session, orphan=True)  # one keyword with mentions, one orphan
    r1 = store.maybe_cleanup_keywords(session)
    assert r1["prune"]["orphans"] == 1 and r1["prune"]["pruned"] == 1
    # the marker persists and gates the next call within the window
    assert store.keyword_cleanup_state()["last_run"] is not None
    r2 = store.maybe_cleanup_keywords(session)
    assert r2.get("skipped") == "fresh"
