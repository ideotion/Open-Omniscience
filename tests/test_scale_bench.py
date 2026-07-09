"""
Scale benchmark runner (scale harness G2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Guards the runner's engine-mode phases (unlock/wal), the RSS sampler, the endpoint
measurement, the report shape + the NO-SCORE honesty rule, and the drift guard that
keeps the unlock sequence in lock-step with the app's real ``init_db``.

The backup/restore/endpoint-against-the-real-app phases are process-mode (they use
``live_db_path`` / the real app engine), so they are exercised end-to-end by the
opt-in ``-m scale_smoke`` tier, not here. These tests stay isolated: they use the
runner's OWN engine on ``tmp_path`` synthetic corpora -- never ``SessionLocal`` /
the shared data dir.
"""

from __future__ import annotations

import inspect
import re

import pytest

from src.testing import scale_bench as sb
from src.testing.corpus_gen import CorpusSpec, generate_corpus

_SMALL = {
    "sources": 10,
    "mentions_per_article": 20,
    "fresh_keywords_per_article": 5,
    "head_pool": 1200,
    "content_words": 80,
    "batch_articles": 100,
}


def _score_like_keys(obj) -> list[str]:
    """Every score/ranking KEY anywhere in the report (honesty: counts only)."""
    found: list[str] = []

    def walk(d):
        if isinstance(d, dict):
            for k, v in d.items():
                kl = str(k).lower()
                if "score" in kl or "ranking" in kl or kl == "rank" or "grade" in kl:
                    found.append(str(k))
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)

    walk(obj)
    return found


def _indexes(db_path) -> set[str]:
    import sqlite3

    con = sqlite3.connect(str(db_path))
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# unlock phase -- cold builds the self-heal index, warm is a near no-op
# --------------------------------------------------------------------------- #
def test_unlock_bench_cold_builds_index_warm_is_fast(tmp_path):
    db = tmp_path / "corpus.db"
    generate_corpus(db, CorpusSpec(articles=400, **_SMALL))

    result = sb.unlock_bench(db)
    # The cold unlock builds the expression index the app self-heals; the warm
    # re-run finds it present (nothing new) -- the P0.4 discriminator.
    assert "ix_article_observed" in result["hot_indexes_created_cold"]
    assert result["hot_indexes_created_warm"] == []
    assert result["cold_unlock_s"] >= 0.0
    assert result["warm_unlock_s"] >= 0.0
    assert isinstance(result["cold_peak_rss_mb"], float)
    assert "method" in result


def test_unlock_bench_does_not_mutate_the_source_corpus(tmp_path):
    """The unlock runs on a COLD COPY, so the source stays reusable (still lacks
    the self-heal index) for a repeat measurement."""
    db = tmp_path / "corpus.db"
    generate_corpus(db, CorpusSpec(articles=300, **_SMALL))
    assert "ix_article_observed" not in _indexes(db)
    sb.unlock_bench(db)
    assert "ix_article_observed" not in _indexes(db)  # source untouched


# --------------------------------------------------------------------------- #
# wal phase
# --------------------------------------------------------------------------- #
def test_wal_bench_reports_growth_and_checkpoints(tmp_path):
    db = tmp_path / "corpus.db"
    generate_corpus(db, CorpusSpec(articles=200, **_SMALL))
    out = sb.wal_bench(db, writes=1000)
    assert out["writes"] == 1000
    assert out["wal_peak_bytes"] > 0
    assert out["wal_bytes_after_checkpoint"] == 0  # TRUNCATE folds the WAL back
    assert "method" in out


# --------------------------------------------------------------------------- #
# RSS sampler -- a real sampled maximum
# --------------------------------------------------------------------------- #
def test_rss_sampler_reports_a_positive_peak():
    with sb.sample_peak_rss(interval_s=0.01) as peak:
        blob = [bytearray(50_000) for _ in range(200)]  # allocate to move RSS
        assert len(blob) == 200
    assert peak.peak_bytes > 0


# --------------------------------------------------------------------------- #
# endpoint measurement -- shape, percentiles, status (tiny fake app)
# --------------------------------------------------------------------------- #
def test_endpoint_bench_measures_p50_p95_and_status():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/a")
    def a() -> dict:
        return {"ok": 1}

    @app.get("/b")
    def b() -> dict:
        return {"ok": 2}

    with TestClient(app) as client:
        out = sb.endpoint_bench(client, [("/a", "a"), ("/b", "b")], repeats=5, warmup=1)

    rows = out["endpoints"]
    assert [r["label"] for r in rows] == ["a", "b"]
    for r in rows:
        assert r["status"] == 200
        assert r["n"] == 5
        assert r["method"] == "GET"
        assert r["p95_ms"] >= r["p50_ms"]
        assert r["error"] is None
    assert _score_like_keys(out) == []


def test_endpoint_bench_reports_non_200_without_failing():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()  # no routes -> every GET is a 404

    with TestClient(app) as client:
        out = sb.endpoint_bench(client, [("/missing", "missing")], repeats=3)
    assert out["endpoints"][0]["status"] == 404  # measured, not a bench failure


# --------------------------------------------------------------------------- #
# report shape + the NO-SCORE honesty rule (engine-mode phases in-process)
# --------------------------------------------------------------------------- #
def test_run_full_report_shape_and_no_scores(tmp_path):
    # unlock + wal are engine-mode (own engine on the explicit corpus path), so a
    # subset run is fully isolated -- it never touches live_db_path / the app.
    generate_corpus(tmp_path / "open_omniscience.db", CorpusSpec(articles=250, **_SMALL))
    report = sb.run_full(
        tmp_path, backup_passphrase="", phases=["unlock", "wal"], wal_writes=500
    )
    assert report["report_schema"] == sb.REPORT_SCHEMA
    assert "generated_at" in report
    assert report["machine"]["cpu_count"] is not None
    assert report["corpus"]["synthetic"] is True
    assert report["corpus"]["row_counts"]["articles"] == 250
    assert set(report["phases"]) == {"unlock", "wal"}
    # The whole report is counts/times/status only -- NO score/ranking key anywhere.
    assert _score_like_keys(report) == []


def test_run_full_injected_clock_is_used(tmp_path):
    """generated_at comes from the injected clock (no hidden wall-clock read)."""
    from datetime import UTC, datetime

    generate_corpus(tmp_path / "open_omniscience.db", CorpusSpec(articles=120, **_SMALL))
    fixed = datetime(2026, 7, 9, 13, 6, 0, tzinfo=UTC)
    report = sb.run_full(
        tmp_path, backup_passphrase="", phases=["unlock"], now=lambda: fixed
    )
    assert report["generated_at"].startswith("2026-07-09T13:06:00")


def test_run_full_missing_corpus_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        sb.run_full(tmp_path, backup_passphrase="", phases=["unlock"])


# --------------------------------------------------------------------------- #
# drift guard -- the unlock sequence stays in lock-step with the real init_db
# --------------------------------------------------------------------------- #
def test_unlock_sequence_covers_every_init_db_self_heal():
    """If init_db gains a new ensure_* self-heal, the bench must run it too, or the
    cold-unlock measurement understates the real unlock cost. This composes the two
    sources rather than asserting a hand-copied list."""
    from src.database.session import init_db

    ensure_re = re.compile(r"\bensure_[a-z_]+\b")
    init_names = set(ensure_re.findall(inspect.getsource(init_db)))
    bench_names = set(ensure_re.findall(inspect.getsource(sb._run_init_sequence)))

    # Every self-heal init_db runs is also run by the bench (bench may run more,
    # e.g. optimize_at_boot, which is not an ensure_*).
    missing = init_names - bench_names
    assert missing == set(), f"bench unlock sequence is missing init_db self-heals: {missing}"
    # Sanity: the sequence is non-trivial (guards against both regexes matching {}).
    assert "ensure_hot_indexes" in bench_names


def test_plaintext_report_carries_the_loud_acceptance_caveat(tmp_path):
    """The acceptance-instrument guard (post-merge audit 2026-07-09): a report over a
    PLAINTEXT corpus must carry the loud plaintext_caveat (codec costs absent — never
    usable for scale-acceptance), and an ENCRYPTED corpus's report must NOT carry it."""
    from src.testing.corpus_gen import CorpusSpec, generate_corpus
    from src.testing.scale_bench import run_full

    pdir = tmp_path / "plain"; pdir.mkdir(); plain = pdir / "open_omniscience.db"
    generate_corpus(plain, CorpusSpec(articles=20, seed=7, sources=3, mentions_per_article=4,
                                      fresh_keywords_per_article=2, content_words=30))
    rep = run_full(pdir, phases=("wal",), wal_writes=5, backup_passphrase="bp")
    assert "PLAINTEXT corpus" in rep.get("plaintext_caveat", "")
    assert "encrypted" in rep["plaintext_caveat"]  # says how to fix it

    edir = tmp_path / "enc"; edir.mkdir(); enc = edir / "open_omniscience.db"
    generate_corpus(enc, CorpusSpec(articles=20, seed=7, sources=3, mentions_per_article=4,
                                    fresh_keywords_per_article=2, content_words=30,
                                    passphrase="bench-secret"))
    rep2 = run_full(edir, phases=("wal",), wal_writes=5, corpus_passphrase="bench-secret",
                    backup_passphrase="bp")
    assert "plaintext_caveat" not in rep2
    assert rep2["corpus"]["encrypted"] is True
