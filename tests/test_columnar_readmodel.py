"""Columnar read-model maintenance + byte-identical projection (data-arch Slice 4 PR-2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The columnar read-model is a DISPOSABLE projection of the canonical store. PR-2 proves
the maintenance + a first byte-identical projection (the Slice-2 keyword counters) +
the cold-store fallback. It is NOT yet wired to the hot endpoints (offline it is
in-memory = a per-process rebuild = no gain over the counters; the win is the persisted
store across restarts — gated on the crypto-extension packaging decision).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

duckdb = pytest.importorskip("duckdb")  # optional [columnar] extra

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.analytics import columnar  # noqa: E402
from src.analytics.extract import BaselineExtractor  # noqa: E402
from src.analytics.queries import kind_of  # noqa: E402
from src.analytics.store import index_article  # noqa: E402
from src.database.models import Article, Base, Keyword, Source  # noqa: E402


@pytest.fixture()
def db(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(tmp_path))
    monkeypatch.delenv("OO_COLUMNAR", raising=False)
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ex = BaselineExtractor()
    texts = [
        "The Senate passed the federal budget after a long debate.",
        "The federal budget debate continued in the Senate chamber.",
        "Climate policy dominated the federal budget debate.",
    ]
    for i, txt in enumerate(texts):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title="T", content=txt, hash=f"h{i}", language="en",
            published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=ex)
    return s


def _canonical(db) -> dict:
    """The canonical keyword counters as {normalized: (mentions, articles, kind)}."""
    return {
        kw.normalized_term: (int(kw.mention_count), int(kw.article_count), kind_of(kw))
        for kw in db.query(Keyword).filter(Keyword.mention_count > 0)
    }


def test_read_model_is_a_byte_identical_projection_of_the_counters(db):
    con = columnar.connect(passphrase="correct horse battery staple")
    assert con is not None
    n = columnar.build_keyword_read_model(con, db)
    canon = _canonical(db)
    assert n == len(canon)

    raw = columnar.top_terms_raw(con, limit=1000)
    projected = {r["normalized"]: (r["mentions"], r["articles"], r["kind"]) for r in raw}
    assert projected == canon  # exact, order-independent projection
    con.close()


def test_read_model_ordering_matches_counter_ranking(db):
    con = columnar.connect(passphrase="x")
    columnar.build_keyword_read_model(con, db)
    raw = columnar.top_terms_raw(con, limit=5)
    # Non-increasing by mentions (the counter ranking the live top_terms uses).
    mentions = [r["mentions"] for r in raw]
    assert mentions == sorted(mentions, reverse=True)
    # The top term equals the canonical max-mention keyword.
    canon = _canonical(db)
    top_canon = max(canon.values(), key=lambda v: v[0])[0]
    assert raw[0]["mentions"] == top_canon
    con.close()


def test_cold_store_returns_nothing_so_the_seam_falls_back_to_live(db):
    con = columnar.connect(passphrase="x")
    # No build() called -> the keyword_agg table is absent -> reader returns [] (the
    # canonical correctness path never DEPENDS on the derived store; it is an accelerator).
    assert columnar.top_terms_raw(con, limit=10) == []
    con.close()


def test_kind_filter_matches(db):
    con = columnar.connect(passphrase="x")
    columnar.build_keyword_read_model(con, db)
    terms_only = columnar.top_terms_raw(con, kind="term", limit=1000)
    assert all(r["kind"] == "term" for r in terms_only)
    con.close()


def test_persisted_refresh_is_a_noop_when_not_persisted(db):
    # Slice 4 D: the background read-model refresh persists ONLY when the store is the
    # encrypted PERSISTED one. Offline (no secure crypto extension) it is in-memory, so
    # this is a deliberate no-op (never wasted work, never a plaintext file).
    if columnar.secure_crypto_available():
        pytest.skip("secure crypto present -> the persisted path is exercised elsewhere")
    assert columnar.refresh_persisted_read_model(db, passphrase="x")["skipped"] == "in-memory"
    assert columnar.refresh_persisted_read_model(db, passphrase=None)["skipped"] == "in-memory"


def test_status_is_honest_about_the_engine_mode(db, monkeypatch):
    # In-memory here (no secure crypto): status must say so, never claim persistence.
    st = columnar.status("a-passphrase")
    assert st["available"] is True
    assert st["mode"] in ("memory", "persisted")
    assert st["encrypted"] == (st["mode"] == "persisted")
    monkeypatch.setenv("OO_COLUMNAR", "0")
    assert columnar.status("x")["mode"] == "unavailable"


def test_diagnostics_columnar_endpoint_is_observable_and_honest():
    # Slice 4 D: the maintainer can SEE the engine mode + geo vintage to decide on the
    # crypto-extension packaging. No score.
    from src.api.diagnostics import columnar_status

    out = columnar_status()
    assert set(out) >= {"columnar", "ip_geo", "method"}
    assert out["columnar"]["mode"] in ("memory", "persisted", "unavailable")
    assert "DB-IP" in out["ip_geo"]["attribution"]
    import json

    assert "score" not in json.dumps(out["columnar"]).lower()


def test_store_format_marker_round_trips_and_detects_incompatibility(db):
    # COMPATIBILITY: the store self-describes the DuckDB major.minor + schema rev, so a
    # store written by an incompatible version is detected (and rebuilt, never crashed on).
    con = columnar.connect(passphrase="x")
    # connect() stamps the marker (even in-memory).
    assert columnar.read_store_meta(con) == columnar.store_format_marker()
    assert columnar.marker_compatible(columnar.store_format_marker()) is True
    # An old/foreign marker is incompatible -> connect() would drop + rebuild the file.
    assert columnar.marker_compatible("duckdb-0.1/schema-0") is False
    assert columnar.marker_compatible(None) is False  # unmarked handled as 'adopt', not compatible
    con.close()


def test_connect_never_crashes_with_a_garbage_store_file(db, monkeypatch, tmp_path):
    # A corrupt/incompatible file at the store path must NEVER crash the engine: offline
    # it falls back to in-memory; with secure crypto it would delete+rebuild. Either way a
    # usable connection comes back (the canonical store is the source of truth).
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(tmp_path))
    (tmp_path / "analytics.duckdb").write_bytes(b"not a valid duckdb file \x00\x01\x02")
    con = columnar.connect(passphrase="correct horse battery staple")
    assert con is not None
    con.execute("CREATE TABLE t (n INTEGER); INSERT INTO t VALUES (1)")
    assert con.execute("SELECT SUM(n) FROM t").fetchone()[0] == 1
    con.close()
