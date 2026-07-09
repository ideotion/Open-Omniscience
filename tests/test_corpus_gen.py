"""
Synthetic corpus generator (scale harness G1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Guards the three properties the generator MUST hold so a benchmark run over it is
trustworthy:
  * SCHEMA PARITY -- every table comes from ``Base.metadata`` (create_all), so it
    can never drift from the models; the FTS vtable + model hot-indexes are present
    and the ONE index the app self-heals at unlock (``ix_article_observed``) is
    deliberately absent (so the cold-unlock benchmark has real work to do).
  * DETERMINISM -- a fixed spec produces byte-identical row data (no wall clock).
  * The visible SYNTHETIC MARKER -- so a generated corpus can never be mistaken for
    real user data; counters are drift-free; there are no orphan mentions.

Uses isolated ``tmp_path`` databases with the generator's OWN engine -- never
``SessionLocal`` / the shared data dir.
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

from src.testing.corpus_gen import (
    SYNTHETIC_APPLICATION_ID,
    SYNTHETIC_MARKER_KEY,
    CorpusSpec,
    generate_corpus,
    is_synthetic,
)

# Small, fast spec for the unit tier (the ~200 MB tier is the -m scale_smoke test).
_SMALL = {
    "sources": 12,
    "mentions_per_article": 24,
    "fresh_keywords_per_article": 6,
    "head_pool": 1500,
    "content_words": 90,
    "batch_articles": 100,
}


def _row_fingerprint(db_path) -> str:
    """A stable content fingerprint over the row data (not file bytes)."""
    con = sqlite3.connect(str(db_path))
    try:
        h = hashlib.sha256()
        for table, cols in (
            ("sources", "id,domain,language,country,source_type,tags"),
            ("articles", "id,url,hash,content,published_at,language,country,word_count"),
            ("keywords", "id,term,normalized_term,language,mention_count,article_count"),
            ("keyword_mentions", "keyword_id,article_id,count,observed_on,source_id"),
            ("app_state", "key,value"),
        ):
            for row in con.execute(f"SELECT {cols} FROM {table} ORDER BY 1,2"):
                h.update(repr(row).encode())
        return h.hexdigest()
    finally:
        con.close()


def _tables(db_path) -> set[str]:
    con = sqlite3.connect(str(db_path))
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def _indexes(db_path) -> set[str]:
    con = sqlite3.connect(str(db_path))
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Schema parity -- the generated schema NEVER drifts from Base.metadata
# --------------------------------------------------------------------------- #
def test_schema_parity_every_model_table_is_present(tmp_path):
    from src.database.models import Base

    db = tmp_path / "corpus.db"
    generate_corpus(db, CorpusSpec(articles=200, **_SMALL))

    present = _tables(db)
    model_tables = set(Base.metadata.tables)
    # Every model table exists (create_all -> zero drift).
    assert model_tables - present == set(), f"missing model tables: {model_tables - present}"
    # The FTS virtual table + its shadow tables exist (search works).
    assert "article_fts" in present


def test_hot_indexes_present_but_unlock_index_absent(tmp_path):
    """The model's covering mention index is built by create_all; the expression
    index the app self-heals at unlock (ix_article_observed, not on any model) is
    absent on purpose so the cold-unlock benchmark reproduces the real build cost."""
    db = tmp_path / "corpus.db"
    generate_corpus(db, CorpusSpec(articles=200, **_SMALL))
    idx = _indexes(db)
    assert "ix_mention_covering" in idx
    assert "ix_mention_date_keyword" in idx
    assert "idx_keyword_mention_count" in idx
    assert "ix_article_observed" not in idx  # the unlock self-heal builds this


def test_no_query_planner_stats_pre_unlock(tmp_path):
    """A freshly bulk-loaded corpus has no ANALYZE stats yet (the unlock's
    optimize_at_boot builds them); the generator must not pre-bake them."""
    db = tmp_path / "corpus.db"
    generate_corpus(db, CorpusSpec(articles=200, **_SMALL))
    assert "sqlite_stat1" not in _tables(db)


# --------------------------------------------------------------------------- #
# Determinism -- a fixed spec is byte-reproducible (no wall clock)
# --------------------------------------------------------------------------- #
def test_generation_is_deterministic(tmp_path):
    spec = CorpusSpec(articles=300, seed=4242, **_SMALL)
    a = tmp_path / "a.db"
    b = tmp_path / "b.db"
    generate_corpus(a, spec)
    generate_corpus(b, spec)
    assert _row_fingerprint(a) == _row_fingerprint(b)


def test_different_seed_changes_the_corpus(tmp_path):
    a = tmp_path / "a.db"
    b = tmp_path / "b.db"
    generate_corpus(a, CorpusSpec(articles=300, seed=1, **_SMALL))
    generate_corpus(b, CorpusSpec(articles=300, seed=2, **_SMALL))
    assert _row_fingerprint(a) != _row_fingerprint(b)


# --------------------------------------------------------------------------- #
# The visible synthetic marker -- never mistakable for real data
# --------------------------------------------------------------------------- #
def test_synthetic_marker_row_and_application_id(tmp_path):
    db = tmp_path / "corpus.db"
    summary = generate_corpus(db, CorpusSpec(articles=200, **_SMALL))
    assert summary["synthetic"] is True

    marker = is_synthetic(db)
    assert marker is not None
    assert marker["synthetic"] is True
    assert marker["generator"] == "src.testing.corpus_gen"
    assert "SYNTHETIC" in marker["warning"]

    con = sqlite3.connect(str(db))
    try:
        appid = con.execute("PRAGMA application_id").fetchone()[0]
        # SQLite reads application_id as a signed 32-bit int.
        assert (appid & 0xFFFFFFFF) == SYNTHETIC_APPLICATION_ID
        val = con.execute(
            "SELECT value FROM app_state WHERE key=?", (SYNTHETIC_MARKER_KEY,)
        ).fetchone()
        assert val is not None
    finally:
        con.close()


def test_is_synthetic_returns_none_for_a_non_synthetic_db(tmp_path):
    """A real corpus (no marker row) is honestly NOT flagged synthetic."""
    db = tmp_path / "real.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.commit()
    con.close()
    assert is_synthetic(db) is None
    # A missing file is likewise None, never an error.
    assert is_synthetic(tmp_path / "does-not-exist.db") is None


def test_is_synthetic_never_crashes_on_unreadable_files(tmp_path):
    """is_synthetic is a POSITIVE flag: a garbage file, or an encrypted file we
    cannot open, is 'not proven synthetic' -> None, never a raised exception."""
    # A non-SQLite garbage file.
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not a sqlite database at all" * 4)
    assert is_synthetic(garbage) is None

    # A real synthetic corpus but ENCRYPTED, opened WITHOUT the passphrase.
    from src.database.connect import have_driver

    if have_driver():
        enc = tmp_path / "enc.db"
        generate_corpus(enc, CorpusSpec(articles=80, passphrase="right-pass", **_SMALL))
        assert is_synthetic(enc) is None  # no passphrase -> can't prove -> None
        assert is_synthetic(enc, passphrase="wrong-pass") is None  # wrong -> None
        assert is_synthetic(enc, passphrase="right-pass") is not None  # right -> flagged


# --------------------------------------------------------------------------- #
# Data integrity -- drift-free counters, no orphans, realistic tail
# --------------------------------------------------------------------------- #
def test_counters_match_the_live_mention_aggregation(tmp_path):
    db = tmp_path / "corpus.db"
    generate_corpus(db, CorpusSpec(articles=400, **_SMALL))
    con = sqlite3.connect(str(db))
    try:
        # Every keyword's denormalised counters equal the canonical GROUP BY.
        mismatches = con.execute(
            """
            SELECT k.id FROM keywords k WHERE
              k.mention_count != COALESCE(
                (SELECT SUM(count) FROM keyword_mentions m WHERE m.keyword_id=k.id), 0)
              OR k.article_count != COALESCE(
                (SELECT COUNT(DISTINCT article_id) FROM keyword_mentions m
                 WHERE m.keyword_id=k.id), 0)
            LIMIT 5
            """
        ).fetchall()
        assert mismatches == []
        # No orphan mentions (every mention has a keyword row) -- FK-consistent.
        orphans = con.execute(
            "SELECT COUNT(*) FROM keyword_mentions m "
            "WHERE NOT EXISTS (SELECT 1 FROM keywords k WHERE k.id=m.keyword_id)"
        ).fetchone()[0]
        assert orphans == 0
        # No keyword with zero mentions (the pipeline never creates orphan keywords).
        zero = con.execute("SELECT COUNT(*) FROM keywords WHERE mention_count=0").fetchone()[0]
        assert zero == 0
    finally:
        con.close()


def test_single_article_keyword_tail_is_realistic(tmp_path):
    """The long single-article tail (71 % in the field) is reproduced within a band."""
    db = tmp_path / "corpus.db"
    summary = generate_corpus(db, CorpusSpec(articles=1200, **_SMALL))
    frac = summary["single_article_fraction"]
    assert 0.45 <= frac <= 0.92, f"single-article fraction {frac} outside a realistic band"
    # And it is a real count backed by the DB, not a fabricated ratio.
    con = sqlite3.connect(str(db))
    try:
        single = con.execute("SELECT COUNT(*) FROM keywords WHERE article_count=1").fetchone()[0]
    finally:
        con.close()
    assert single == summary["single_article_keywords"]


def test_fts_matches_a_head_keyword_in_article_bodies(tmp_path):
    db = tmp_path / "corpus.db"
    generate_corpus(db, CorpusSpec(articles=300, **_SMALL))
    con = sqlite3.connect(str(db))
    try:
        term = con.execute("SELECT term FROM keywords WHERE id=1").fetchone()[0]
        hits = con.execute(
            "SELECT COUNT(*) FROM article_fts WHERE article_fts MATCH ?", (f'"{term}"',)
        ).fetchone()[0]
    finally:
        con.close()
    assert hits > 0  # the common head terms are searchable in article content


# --------------------------------------------------------------------------- #
# Encryption + target-size + guards
# --------------------------------------------------------------------------- #
def test_encrypted_corpus_is_ciphertext_and_marker_readable(tmp_path):
    from src.database.connect import have_driver, is_encrypted_file

    if not have_driver():  # pragma: no cover - sqlcipher3 is a core dependency
        pytest.skip("sqlcipher3 driver unavailable")
    db = tmp_path / "enc.db"
    generate_corpus(db, CorpusSpec(articles=150, passphrase="bench-only-pass", **_SMALL))
    assert is_encrypted_file(db) is True
    marker = is_synthetic(db, passphrase="bench-only-pass")
    assert marker is not None and marker["synthetic"] is True


def test_target_size_reaches_approximately_the_target(tmp_path):
    db = tmp_path / "corpus.db"
    target = 4 * 1024 * 1024
    summary = generate_corpus(
        db, CorpusSpec(target_bytes=target, batch_articles=40, sources=12,
                       mentions_per_article=24, fresh_keywords_per_article=6,
                       head_pool=3000, content_words=90)
    )
    # At least the target, and not wildly over (a small-target run overshoots by
    # at most ~one batch; larger tiers are far tighter).
    assert summary["bytes"] >= target
    assert summary["bytes"] < target * 2


def test_max_articles_backstop_engages_in_target_mode(tmp_path):
    """A target that would never be reached must stop at the max_articles backstop,
    never run away."""
    db = tmp_path / "corpus.db"
    summary = generate_corpus(
        db,
        CorpusSpec(
            target_bytes=10 * 1024 * 1024 * 1024,  # 10 GiB target, never reached here
            max_articles=250,                       # the backstop that must engage
            **_SMALL,
        ),
    )
    assert summary["articles"] == 250  # stopped at the backstop, not the target


def test_determinism_survives_hash_randomization(tmp_path):
    """The byte-identical claim must hold across processes with DIFFERENT
    PYTHONHASHSEED -- generation must never depend on set/dict iteration order."""
    import os as _os
    import subprocess

    script = (
        "import hashlib, sqlite3, sys\n"
        "from src.testing.corpus_gen import generate_corpus, CorpusSpec\n"
        "db = sys.argv[1]\n"
        "generate_corpus(db, CorpusSpec(articles=250, seed=99, sources=10,\n"
        "  mentions_per_article=20, fresh_keywords_per_article=5, head_pool=1200,\n"
        "  content_words=80, batch_articles=100))\n"
        "con = sqlite3.connect(db); h = hashlib.sha256()\n"
        "for r in con.execute('SELECT keyword_id,article_id,count,observed_on "
        "FROM keyword_mentions ORDER BY keyword_id,article_id'): h.update(repr(r).encode())\n"
        "for r in con.execute('SELECT id,term,mention_count,article_count FROM keywords "
        "ORDER BY id'): h.update(repr(r).encode())\n"
        # sources carried the set-join defect (tags order flipped with PYTHONHASHSEED);
        # the fingerprint must cover the table that broke, or the test is blind to it.
        "for r in con.execute('SELECT id,name,domain,tags,language,country FROM sources "
        "ORDER BY id'): h.update(repr(r).encode())\n"
        "print(h.hexdigest())\n"
    )
    root = str(Path(__file__).resolve().parents[1])

    def _fp(seed: str, dbname: str) -> str:
        env = {**_os.environ, "PYTHONHASHSEED": seed, "OO_DB_PLAINTEXT": "1"}
        proc = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / dbname)],
            cwd=root, env=env, capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip()

    assert _fp("0", "h0.db") == _fp("1", "h1.db")


def test_generator_never_overwrites(tmp_path):
    db = tmp_path / "corpus.db"
    generate_corpus(db, CorpusSpec(articles=100, **_SMALL))
    with pytest.raises(FileExistsError):
        generate_corpus(db, CorpusSpec(articles=100, **_SMALL))


@pytest.mark.parametrize(
    "kwargs",
    [
        {},  # neither articles nor target_bytes
        {"articles": 0},
        {"articles": 10, "sources": 0},
        {"articles": 10, "mentions_per_article": 0},
        {"articles": 10, "fresh_keywords_per_article": 999, "mentions_per_article": 5},
    ],
)
def test_invalid_specs_raise(tmp_path, kwargs):
    with pytest.raises(ValueError):
        generate_corpus(tmp_path / "x.db", CorpusSpec(**kwargs))
