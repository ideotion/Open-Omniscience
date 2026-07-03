"""D4 source_coverage rollup (scaling 5A-bis): a per-country coverage cache keyed by the
corpus epoch, byte-faithful to the live source_country_counts query.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins: parity with the live query (counts match exactly), the epoch/watermark refresh
decision (full rebuild on epoch change or new ingest, else fresh), honest mean-tone (a
country with no scored/English article reports None, never a fabricated zero), the
unlocated bucket, and the benchmark payload shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source

pytest.importorskip("duckdb")


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _source(db, sid, domain, country):
    db.add(Source(id=sid, name=f"S{sid}", domain=domain, country=country))
    db.commit()


def _article(db, sid, hash_, text, *, tone=None, lang="en"):
    # The mention country is the SOURCE's country (denormalised at index time), matching
    # how source_country_counts groups mentions -- required for a like-for-like parity.
    country = db.get(Source, sid).country
    a = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=sid,
        title="T",
        content=text,
        hash=hash_,
        language=lang,
        sentiment_score=tone,
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    index_article(db, a, extractor=BaselineExtractor(), country=country)
    return a


def _seed(db):
    _source(db, 1, "fr.test", "fr")
    _source(db, 2, "us.test", "us")
    _source(db, 3, "unl.test", None)  # unlocated
    _article(db, 1, "a1", "Climate policy and trade dominated the summit.", tone=0.4)
    _article(db, 2, "a2", "Climate policy again and elections everywhere.", tone=-0.2)
    _article(db, 2, "a3", "Elections and the economy in focus.", tone=None)  # no score
    _article(db, 3, "a4", "Trade and climate in the newsletter.", tone=0.1)


def test_rollup_matches_live_source_country_counts(db):
    from src.analytics import columnar
    from src.analytics.corpus_epoch import get_corpus_epoch
    from src.analytics.queries import source_country_counts

    _seed(db)
    con = columnar.connect()
    assert con is not None
    try:
        res = columnar.refresh_source_coverage(con, db, corpus_epoch=get_corpus_epoch(db))
        assert res["mode"] == "full"
        parity = columnar.source_coverage_parity(con, db)
        assert parity["counts_match"], parity
        assert parity["countries_compared"] >= 2

        # Explicit per-country equality against the live query.
        live = {r["country"]: r for r in source_country_counts(db)["by_country"]}
        roll = {r["country"]: r for r in columnar.source_coverage_rows(con) if r["country"]}
        for cc in ("fr", "us"):
            assert (roll[cc]["sources"], roll[cc]["articles"], roll[cc]["keywords"]) == (
                live[cc]["sources"], live[cc]["articles"], live[cc]["keywords"]
            )
    finally:
        con.close()


def test_mean_tone_is_honest_never_a_fabricated_zero(db):
    # index_article scores sentiment via VADER (English-lexicon only), so a country whose
    # only articles are non-English is UNSCORED -> its mean tone must be None (no data),
    # never a fabricated 0.0. A scored country's mean must equal the live query exactly.
    from src.analytics import columnar
    from src.analytics.corpus_epoch import get_corpus_epoch
    from src.analytics.queries import source_country_counts

    _source(db, 1, "en.test", "gb")
    _source(db, 2, "ar.test", "sa")
    _article(db, 1, "e1", "Climate policy and trade dominated the summit.", lang="en")
    _article(db, 2, "n1", "طقس مناخ سياسة تجارة", lang="ar")  # non-English -> unscored

    con = columnar.connect()
    try:
        columnar.refresh_source_coverage(con, db, corpus_epoch=get_corpus_epoch(db))
        roll = {r["country"]: r for r in columnar.source_coverage_rows(con)}
        live = {r["country"]: r for r in source_country_counts(db)["by_country"]}
        # sa: only a non-English article -> no scored article -> None, not 0.0.
        assert roll["sa"]["sentiment"] is None and roll["sa"]["sentiment_n"] == 0
        # gb: a scored (English) article -> a real mean that MATCHES the live query.
        assert roll["gb"]["sentiment"] == live["gb"]["sentiment"]
        assert roll["gb"]["sentiment_n"] == live["gb"]["sentiment_n"] >= 1
    finally:
        con.close()


def test_unlocated_bucket_present(db):
    from src.analytics import columnar
    from src.analytics.corpus_epoch import get_corpus_epoch

    _seed(db)
    con = columnar.connect()
    try:
        columnar.refresh_source_coverage(con, db, corpus_epoch=get_corpus_epoch(db))
        rows = {r["country"]: r for r in columnar.source_coverage_rows(con)}
        assert "" in rows  # the country-less source/article -> unlocated bucket
        assert rows[""]["articles"] == 1 and rows[""]["sources"] == 1
        # A country-less bucket is NEVER a mapped country row.
        assert "" not in {r["country"] for r in columnar.source_coverage_rows(con) if r["country"]}
    finally:
        con.close()


def test_refresh_rebuilds_on_epoch_change_and_new_ingest(db):
    from src.analytics import columnar
    from src.analytics.corpus_epoch import bump_corpus_epoch, get_corpus_epoch

    _seed(db)
    con = columnar.connect()
    try:
        e0 = get_corpus_epoch(db)
        assert columnar.refresh_source_coverage(con, db, corpus_epoch=e0)["mode"] == "full"
        # No change -> a no-op fresh serve.
        assert columnar.refresh_source_coverage(con, db, corpus_epoch=e0)["mode"] == "fresh"
        # Epoch change (re-index/prune/restore) -> full rebuild.
        e1 = bump_corpus_epoch(db)
        assert columnar.refresh_source_coverage(con, db, corpus_epoch=e1)["mode"] == "full"
        assert columnar.refresh_source_coverage(con, db, corpus_epoch=e1)["mode"] == "fresh"
        # New ingest (watermark advances) WITHOUT an epoch change -> full rebuild too.
        _article(db, 1, "a5", "More climate coverage today.", tone=0.2)
        assert columnar.refresh_source_coverage(con, db, corpus_epoch=e1)["mode"] == "full"
    finally:
        con.close()


def test_benchmark_payload_is_self_describing_with_parity(db):
    from src.monitoring.source_coverage_benchmark import run_source_coverage_benchmark

    _seed(db)
    out = run_source_coverage_benchmark(db, repeats=2)
    assert out["available"] is True
    assert out["parity"]["counts_match"] is True
    assert out["build"]["mode"] == "full"
    # The honesty envelope shape {value, basis, as_of, method, n}.
    cov = out["coverage"]
    assert cov["basis"] == "estimated" and cov["as_of"] and cov["method"]
    assert isinstance(cov["value"], list) and cov["n"] >= 1
    # No score field anywhere in the payload keys.
    assert "speedup_x" in out["read"]
