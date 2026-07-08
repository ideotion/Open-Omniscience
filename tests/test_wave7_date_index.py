"""Article observed-date expression index (field-test 2026-07-08 Item 8 P0).

The single biggest field-measured cost was the corpus date-range probe
``SELECT min(coalesce(published_at, created_at)), max(coalesce(published_at,
created_at)) FROM articles`` (4,775 ms x 154 calls = 735 s): a bare
``SCAN articles`` that dragged every ~35 KB article row through the SQLCipher
codec because ``coalesce(published_at, created_at)`` had no index. The SAME
expression is a ``>= cutoff`` range filter in src/integrity/*, src/api/
link_analysis.py and src/analytics/{copypasta,headline_body,recycled_claim}.py.

This suite pins the fix: the expression index ``ix_article_observed`` is created
by BOTH the alembic migration (5ea842778603) and the idempotent boot self-heal
(maintenance.ensure_hot_indexes), and it turns those full scans into index-only
plans. Classification follows the ledger lesson: SQLite marks both a bare table
scan AND an index-only scan with the word ``SCAN`` -- a ``SCAN <table> USING
[COVERING] INDEX ...`` is HEALTHY (index-only) and only a bare ``SCAN <table>``
with no ``USING`` is the scaling smell.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import datetime
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.database.maintenance import HOT_INDEXES, ensure_hot_indexes
from src.database.models import Article, Base

_INDEX = "ix_article_observed"
REPO = Path(__file__).resolve().parents[1]

# The exact expression every call site compiles to (verified: producers.py's
# corpus-range probe and the integrity/analytics/link-analysis cutoff filters
# all use func.coalesce(Article.published_at, Article.created_at)). SQLite only
# uses an expression index when the query expression matches, so the tests build
# the query straight from the model rather than hand-writing SQL.
_OBSERVED = func.coalesce(Article.published_at, Article.created_at)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _engine() -> Engine:
    """An isolated in-memory SQLite DB with the full model schema. Never
    SessionLocal (a plain Session on this engine has no write-gate/event hooks),
    so the tests can never touch the shared suite store."""
    eng = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(eng: Engine, n: int = 600) -> None:
    base = datetime.datetime(2024, 1, 1)
    with Session(eng) as s:
        for i in range(n):
            created = base + datetime.timedelta(days=i % 400, seconds=i)
            # ~1/3 of rows have a NULL published_at so coalesce actually falls
            # back to created_at (exercises the whole expression, not just col 1).
            published = (created - datetime.timedelta(days=1)) if i % 3 else None
            s.add(
                Article(
                    url=f"https://wave7.example/{i}",
                    canonical_url=f"https://wave7.example/{i}",
                    hash=f"{i:064d}",
                    title=f"article {i}",
                    content="lorem ipsum " * 30,
                    published_at=published,
                    created_at=created,
                    source_id=i % 40,
                )
            )
        s.commit()


def _plan(eng: Engine, stmt) -> list[str]:
    """The EXPLAIN QUERY PLAN detail column for a SQLAlchemy statement."""
    sql = str(stmt.compile(eng, compile_kwargs={"literal_binds": True}))
    with eng.connect() as conn:
        return [row[3] for row in conn.exec_driver_sql("EXPLAIN QUERY PLAN " + sql)]


def _uses_index(plan: list[str], name: str) -> bool:
    """True when the plan reads via the named index (index-only = HEALTHY).

    Accepts both wordings across SQLite versions: ``USING INDEX <name>`` (e.g.
    3.45, the stdlib driver) and ``USING COVERING INDEX <name>`` (e.g. 3.51, the
    bundled SQLCipher driver)."""
    return any(
        f"USING INDEX {name}" in ln or f"USING COVERING INDEX {name}" in ln for ln in plan
    )


def _has_bare_scan(plan: list[str], table: str) -> bool:
    """The scaling smell: a ``SCAN <table>`` with no ``USING`` (full heap scan)."""
    return any(ln.strip().startswith(f"SCAN {table}") and "USING" not in ln for ln in plan)


def _index_sql(eng: Engine) -> str | None:
    with eng.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name = ?", (_INDEX,)
        ).fetchone()
    return row[0] if row else None


# --------------------------------------------------------------------------- #
# The boot self-heal creates the index (idempotently)
# --------------------------------------------------------------------------- #
def test_ensure_hot_indexes_creates_the_expression_index() -> None:
    eng = _engine()
    # The two keyword-mention hot indexes are declared on the model, so create_all
    # already built them; the article expression index is NOT on any model (SQLite
    # can't reflect expression indexes -> no alembic drift), so it is the ONLY hot
    # index the boot self-heal must add.
    created = ensure_hot_indexes(eng)
    assert created == [_INDEX], created
    # Read the index straight from sqlite_master: SQLAlchemy's reflection skips
    # expression indexes (that same skip is why alembic sees no model drift), so
    # inspect().get_indexes() would never surface it.
    sql = _index_sql(eng)
    assert sql is not None, "index missing after self-heal"
    assert "coalesce(published_at, created_at)" in sql.lower()


def test_ensure_hot_indexes_is_idempotent() -> None:
    eng = _engine()
    assert ensure_hot_indexes(eng) == [_INDEX]
    # A second run creates nothing (PRAGMA/sqlite_master-checked no-op), and a
    # third confirms stability.
    assert ensure_hot_indexes(eng) == []
    assert ensure_hot_indexes(eng) == []


def test_ensure_hot_indexes_no_op_when_index_preexists() -> None:
    eng = _engine()
    # Simulate an install migrated before booting: create the index first, exactly
    # as the migration does, then the self-heal must NOT try to re-create it.
    with eng.begin() as conn:
        conn.execute(text(HOT_INDEXES[_INDEX]))
    created = ensure_hot_indexes(eng)
    assert _INDEX not in created


# --------------------------------------------------------------------------- #
# The migration creates the index (and is reachable from the single head)
# --------------------------------------------------------------------------- #
def test_migration_upgrade_head_creates_the_index(tmp_path) -> None:
    # Run the real migration path end-to-end (mirrors tests/test_migrations.py):
    # `alembic upgrade head` builds the whole schema through every migration,
    # proving our migration runs and is chained off the single head. The suite
    # runs OO_DB_PLAINTEXT=1 (conftest), inherited here, so no passphrase.
    env = {**os.environ, "OO_DATA_DIR": str(tmp_path)}
    res = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    db = tmp_path / "open_omniscience.db"
    eng = create_engine(f"sqlite:///{db}")
    try:
        assert _index_sql(eng) is not None, "migration did not create ix_article_observed"
        assert "coalesce(published_at, created_at)" in _index_sql(eng).lower()
    finally:
        eng.dispose()


def test_migration_and_self_heal_create_identical_ddl() -> None:
    """Lock-step guard: SQLite expression-index matching is by parse tree, so the
    migration and the boot self-heal MUST create byte-identical DDL — otherwise
    one creator's index could silently stop matching the queries."""
    spec = importlib.util.spec_from_file_location(
        "_wave7_migration",
        REPO / "migrations" / "versions" / "5ea842778603_article_observed_date_expression_index_.py",
    )
    assert spec and spec.loader
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig._CREATE.strip() == HOT_INDEXES[_INDEX].strip()
    assert mig.down_revision == "c1d2e3f4a5b6"  # chained off the single head


# --------------------------------------------------------------------------- #
# The measured hot queries now go index-only (EXPLAIN QUERY PLAN)
# --------------------------------------------------------------------------- #
def test_corpus_range_probe_is_a_bare_scan_without_the_index() -> None:
    # The pre-fix state the field test measured: the min/max probe over the
    # coalesce expression cannot use the model's single-column published_at/
    # created_at indexes, so it is a full SCAN articles.
    eng = _engine()
    _seed(eng)
    stmt = select(func.min(_OBSERVED), func.max(_OBSERVED))
    plan = _plan(eng, stmt)
    assert _has_bare_scan(plan, "articles"), plan
    assert not _uses_index(plan, _INDEX), plan


def test_corpus_range_probe_uses_the_index() -> None:
    # The exact producers._corpus_age_days probe.
    eng = _engine()
    _seed(eng)
    ensure_hot_indexes(eng)
    with eng.begin() as conn:
        conn.execute(text("ANALYZE"))  # what optimize_at_boot does on the real store
    stmt = select(func.min(_OBSERVED), func.max(_OBSERVED))
    plan = _plan(eng, stmt)
    assert _uses_index(plan, _INDEX), plan  # index-only = HEALTHY
    assert not _has_bare_scan(plan, "articles"), plan  # no bare heap scan = the smell is gone


def test_corpus_range_probe_index_does_not_change_results() -> None:
    # Zero drift: an index never changes an answer, so min/max are identical with
    # and without it (proves the plan-change is purely a performance win).
    eng = _engine()
    _seed(eng)
    stmt = select(func.min(_OBSERVED), func.max(_OBSERVED))
    with Session(eng) as s:
        before = s.execute(stmt).one()
    ensure_hot_indexes(eng)
    with Session(eng) as s:
        after = s.execute(stmt).one()
    assert before == after
    assert after[0] is not None and after[1] is not None


def test_cutoff_filter_uses_the_index() -> None:
    # The other shape covered by the SAME index: the `>= cutoff` range filter used
    # by src/integrity/{collapse,actors,profile}.py, src/api/link_analysis.py and
    # src/analytics/{copypasta,headline_body,recycled_claim}.py. Documents that a
    # single index serves every observed-date scan site.
    eng = _engine()
    _seed(eng)
    ensure_hot_indexes(eng)
    with eng.begin() as conn:
        conn.execute(text("ANALYZE"))
    cutoff = datetime.datetime(2024, 6, 1)
    stmt = select(func.count()).select_from(Article).where(_OBSERVED >= cutoff)
    plan = _plan(eng, stmt)
    assert _uses_index(plan, _INDEX), plan
    assert not _has_bare_scan(plan, "articles"), plan
