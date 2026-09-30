"""The read seam over the derived keyword rows (segmented-index step 0, ruling R96).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``docs/design/SEGMENTED_DERIVED_INDEX_2026-09-24.md`` §5 step 0: the view over today's table
must be BEHAVIOUR-NEUTRAL, which is provable rather than hoped, so this file proves it:

  * the same rows come back through the view and through the table (the differential -- the
    bar the design §6 sets for every later step: "a sealed segment's rows must equal what a
    re-index into the head would have written");
  * a keyed read through the view still uses the table's index (a view that turned an index
    range scan into a full scan would be a regression the results alone cannot show);
  * the view is created by ``create_all``, re-created when the column list is stale, and
    refuses a write (writers stay on the table = the "head");
  * a RATCHET on references to the write model: readers move onto the view file by file, the
    per-file counts only fall, and a NEW file naming ``KeywordMention`` fails until it is
    either a writer (say so here) or reads through ``KeywordMentionRead``.

The ratchet counts REFERENCES, not reads: the writers (``index_article``, the merge, the bulk
build) legitimately keep theirs, so a file's count can never reach zero for them. What it
prevents is the seam eroding by addition, which is how a seam dies.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from src.database.derived_views import (
    MENTIONS_VIEW,
    KeywordMentionRead,
    ensure_derived_views,
)
from src.database.models import Article, Base, Keyword, KeywordMention, Source

_SRC = Path(__file__).resolve().parent.parent / "src"


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'seam.db'}", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.flush()
    for i in range(1, 6):
        s.add(
            Article(
                url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
                title="T", content="c", hash=f"h{i}", language="en",
                created_at=datetime.now(UTC),
            )
        )
        s.add(Keyword(term=f"k{i}", normalized_term=f"k{i}", language="en"))
    s.flush()
    for kid in (1, 2, 3):
        for aid in range(1, 5):
            s.add(
                KeywordMention(
                    keyword_id=kid, article_id=aid, count=kid + aid, first_offset=aid,
                    observed_on=date(2024, 1, aid), country="fr", language="en", source_id=1,
                )
            )
    s.commit()
    yield s
    s.close()


def test_create_all_gives_the_database_its_view(db):
    kinds = dict(
        db.execute(text("SELECT name, type FROM sqlite_master WHERE name IN (:t, :v)"),
                   {"t": "keyword_mentions", "v": MENTIONS_VIEW}).fetchall()
    )
    assert kinds == {"keyword_mentions": "table", MENTIONS_VIEW: "view"}


def test_the_view_returns_exactly_the_tables_rows(db):
    cols = "id, keyword_id, article_id, count, first_offset, observed_on, country, city, language, source_id, extractor, created_at"
    via_table = db.execute(text(f"SELECT {cols} FROM keyword_mentions ORDER BY id")).fetchall()
    via_view = db.execute(text(f"SELECT {cols} FROM {MENTIONS_VIEW} ORDER BY id")).fetchall()
    assert len(via_table) == 12 and via_view == via_table


def test_the_orm_read_model_matches_the_write_model(db):
    read = [
        (m.id, m.keyword_id, m.article_id, m.count, m.observed_on)
        for m in db.query(KeywordMentionRead).order_by(KeywordMentionRead.id)
    ]
    write = [
        (m.id, m.keyword_id, m.article_id, m.count, m.observed_on)
        for m in db.query(KeywordMention).order_by(KeywordMention.id)
    ]
    assert read == write and len(read) == 12
    assert {c.name for c in KeywordMentionRead.__table__.columns} == {
        c.name for c in KeywordMention.__table__.columns
    }


def test_the_typed_handles_cover_every_column():
    """The annotations on KeywordMentionRead exist for the type checker; a column added to
    KeywordMention without one would be readable at runtime and invisible to mypy."""
    annotated = set(KeywordMentionRead.__annotations__)
    assert annotated == {c.name for c in KeywordMention.__table__.columns}


def test_a_keyed_read_through_the_view_still_uses_an_index(db):
    plan = " ".join(
        str(r[3])
        for r in db.execute(
            text(f"EXPLAIN QUERY PLAN SELECT DISTINCT keyword_id FROM {MENTIONS_VIEW} "
                 "WHERE keyword_id > 0 AND keyword_id <= 3")
        )
    )
    assert "USING" in plan and "INDEX" in plan and "SCAN keyword_mentions " not in plan + " ", plan


def test_a_write_through_the_view_is_refused(db):
    with pytest.raises(OperationalError, match="view"):
        db.execute(text(f"INSERT INTO {MENTIONS_VIEW} (keyword_id, article_id, count) VALUES (1, 5, 1)"))
    db.rollback()


def test_ensure_is_idempotent_and_repairs_a_stale_view(db):
    bind = db.get_bind()
    assert ensure_derived_views(bind) == "ok"
    db.execute(text(f"DROP VIEW {MENTIONS_VIEW}"))
    db.commit()
    assert ensure_derived_views(bind) == "created"
    # a view frozen with an older column list (what SELECT * would leave after a migration)
    db.execute(text(f"DROP VIEW {MENTIONS_VIEW}"))
    db.execute(text(f"CREATE VIEW {MENTIONS_VIEW} AS SELECT id, keyword_id FROM keyword_mentions"))
    db.commit()
    assert ensure_derived_views(bind) == "recreated"
    assert db.query(KeywordMentionRead).count() == 12


def test_ensure_skips_a_database_with_no_table_yet(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}", future=True)
    assert ensure_derived_views(engine) == "skipped"


def test_the_prune_pilot_still_prunes_only_true_orphans(db):
    from src.analytics.store import prune_orphan_keywords

    out = prune_orphan_keywords(db, budget_s=0)
    assert out["complete"] is True
    assert {k.id for k in db.query(Keyword)} == {1, 2, 3}  # 4 and 5 had no mention


# --------------------------------------------------------------------------- ratchet
# file -> references to the WRITE model ``KeywordMention``. Recorded 2026-09-29 (R96). Falls
# as readers move onto ``KeywordMentionRead``; never rises, and a file not listed is a new
# reference. Zero slack (the CLAUDE.md size-ratchet's own rule): a count left above the real
# one fails too, so the ceiling is lowered in the same PR as the move.
_CEILING: dict[str, int] = {
    "src/ai_layer/source_tags.py": 13,
    "src/ai_layer/triage.py": 1,
    "src/analytics/article_lang_map.py": 1,
    "src/analytics/columnar.py": 7,
    "src/analytics/keyword_fold.py": 17,
    "src/analytics/serve_gate.py": 2,
    "src/analytics/store.py": 24,
    "src/api/database.py": 2,
    "src/api/diagnostics/bundle.py": 2,
    "src/api/feed.py": 6,
    "src/api/insights.py": 9,
    "src/api/link_analysis.py": 2,
    "src/api/link_preview.py": 5,
    "src/api/main.py": 25,
    # A user-facing sentence, keyed by its exact English text in the 11 bulletin catalogs
    # (configs/bulletin_i18n); renaming the model in it would orphan every translation.
    "src/bulletin/sections.py": 1,
    "src/database/maintenance.py": 3,
    "src/database/writer.py": 1,
    "src/testing/corpus_gen.py": 2,
}
_SKIP = {"src/database/models.py", "src/database/derived_views.py"}


def _actual() -> dict[str, int]:
    found: dict[str, int] = {}
    for f in _SRC.rglob("*.py"):
        rel = f.relative_to(_SRC.parent).as_posix()
        if rel in _SKIP:
            continue
        n = len(re.findall(r"\bKeywordMention\b", f.read_text(encoding="utf-8")))
        if n:
            found[rel] = n
    return found


def test_no_new_reference_to_the_write_model():
    grew = {
        f: (_CEILING.get(f, 0), n) for f, n in _actual().items() if n > _CEILING.get(f, 0)
    }
    assert not grew, (
        "new references to KeywordMention (the WRITE model). A reader must use "
        "src.database.derived_views.KeywordMentionRead (the read seam, R96); a genuine writer "
        f"raises its ceiling here with a reason: {grew}"
    )


def test_the_ceiling_is_not_left_above_the_real_count():
    actual = _actual()
    slack = {f: (c, actual.get(f, 0)) for f, c in _CEILING.items() if actual.get(f, 0) < c}
    assert not slack, f"lower the ceiling to the real count (ceiling, actual): {slack}"


# The same ratchet for RAW SQL naming the table (text() queries, the merge's INSERT..SELECT,
# DuckDB's sqlite_scan). A read written as SQL is invisible to the model-name ratchet above.
_RAW_CEILING: dict[str, int] = {
    "src/ai_layer/__init__.py": 1,
    "src/ai_layer/jobs.py": 1,
    "src/ai_layer/source_tags.py": 1,
    "src/ai_layer/source_tags_job.py": 1,
    "src/ai_layer/store.py": 1,
    "src/ai_layer/triage.py": 2,
    "src/analytics/bulk_build.py": 3,
    "src/analytics/columnar.py": 14,
    "src/analytics/concentration.py": 3,
    "src/analytics/group_stats.py": 1,
    "src/analytics/keyword_fold.py": 1,
    "src/analytics/keyword_growth.py": 6,
    "src/analytics/latest.py": 2,
    "src/analytics/map_serve.py": 1,
    "src/analytics/queries.py": 8,
    "src/analytics/source_quality.py": 1,
    "src/analytics/source_topics.py": 5,
    "src/analytics/spell_index.py": 2,
    "src/analytics/store.py": 5,
    "src/analytics/story_propagation.py": 2,
    "src/analytics/supergroup_rising.py": 1,
    "src/analytics/supergroup_stats.py": 7,
    "src/analytics/supply_chain_ripple.py": 2,
    "src/analytics/weather_signals.py": 1,
    "src/api/ai.py": 1,
    "src/api/database.py": 3,
    "src/api/diagnostics/corpus.py": 1,
    "src/api/diagnostics/keywords.py": 3,
    "src/api/diagnostics/performance.py": 2,
    "src/api/feed.py": 1,
    "src/api/insights.py": 2,
    "src/api/main.py": 4,
    "src/api/served_cache.py": 1,
    "src/api/signals.py": 1,
    "src/backup/country_codes.py": 1,
    "src/backup/import_queue.py": 1,
    "src/backup/merge.py": 22,
    "src/briefing/card_audit.py": 1,
    "src/briefing/producers.py": 1,
    "src/bulletin/articles.py": 1,
    "src/bulletin/coverage.py": 1,
    "src/bulletin/sections.py": 1,
    "src/bulletin/stories.py": 3,
    "src/database/fts.py": 1,
    "src/database/maintenance.py": 16,
    "src/database/migrate.py": 2,
    "src/database/read_snapshot.py": 2,
    "src/database/session.py": 1,
    "src/monitoring/benchmark.py": 3,
    "src/monitoring/expedition.py": 1,
    "src/monitoring/integrity.py": 4,
    "src/monitoring/rollup_benchmark.py": 5,
    "src/monitoring/slowquery.py": 4,
    "src/monitoring/storage.py": 1,
    "src/testing/scale_bench.py": 2,
}


def _actual_raw() -> dict[str, int]:
    found: dict[str, int] = {}
    for f in _SRC.rglob("*.py"):
        rel = f.relative_to(_SRC.parent).as_posix()
        if rel in _SKIP:
            continue
        n = len(re.findall(r"\bkeyword_mentions\b", f.read_text(encoding="utf-8")))
        if n:
            found[rel] = n
    return found


def test_no_new_raw_sql_reference_to_the_mentions_table():
    grew = {
        f: (_RAW_CEILING.get(f, 0), n)
        for f, n in _actual_raw().items()
        if n > _RAW_CEILING.get(f, 0)
    }
    assert not grew, (
        "new raw-SQL references to keyword_mentions. A read selects FROM keyword_mentions_all "
        f"(R96); a genuine writer raises its ceiling here with a reason: {grew}"
    )


def test_the_raw_ceiling_is_not_left_above_the_real_count():
    actual = _actual_raw()
    slack = {f: (c, actual.get(f, 0)) for f, c in _RAW_CEILING.items() if actual.get(f, 0) < c}
    assert not slack, f"lower the raw ceiling to the real count (ceiling, actual): {slack}"


# ------------------------------------------------- migrations, ordering, a missing view
def _alembic(args, data_dir):
    import os
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_SRC.parent, env={**os.environ, "OO_DATA_DIR": str(data_dir)},
        capture_output=True, text=True,
    )


def test_a_migration_can_drop_a_mentions_column_while_the_view_exists(tmp_path):
    """SQLite refuses DROP COLUMN (and a table re-create) while a view names the column. Two
    existing downgrades drop keyword_mentions columns and a future one (row B's country-code
    migration) will alter one, so env.py drops the view before ANY migration runs and the
    next init_db re-creates it. Found by the Opus review of PR #1232."""
    db = tmp_path / "open_omniscience.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)  # has the view
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM sqlite_master WHERE name=:v"),
                         {"v": MENTIONS_VIEW}).scalar() == 1
    engine.dispose()
    assert _alembic(["stamp", "head"], tmp_path).returncode == 0
    res = _alembic(["downgrade", "d6e7f8a9b0c1-1"], tmp_path)  # drops keyword_mentions.source_id
    assert res.returncode == 0, res.stdout + res.stderr
    engine = create_engine(f"sqlite:///{db}", future=True)
    assert ensure_derived_views(engine) == "created"  # the next boot puts it back
    engine.dispose()


def test_init_db_ensures_the_view_after_the_column_self_heals():
    """A view naming a column the table does not have yet blocks every ALTER..RENAME until it
    is repaired, so the ensure runs AFTER ensure_keyword_mention_source_column."""
    src = (_SRC / "database" / "session.py").read_text(encoding="utf-8")
    heal = src.index("ensure_keyword_mention_source_column(engine)")
    seam = src.index("ensure_derived_views(engine)")
    assert heal < seam


def test_a_reader_recreates_a_missing_view_instead_of_failing(db):
    from src.analytics.store import prune_orphan_keywords

    db.execute(text(f"DROP VIEW {MENTIONS_VIEW}"))
    db.commit()
    out = prune_orphan_keywords(db, budget_s=0)
    assert out["complete"] is True
    assert db.execute(text("SELECT 1 FROM sqlite_master WHERE name=:v"),
                      {"v": MENTIONS_VIEW}).fetchone()


def test_the_view_survives_the_stamp_alignment_that_init_db_runs_after_it(tmp_path):
    """``init_db`` ensures the view, THEN aligns a stamp that lags a self-healed schema; that
    alignment runs alembic, and env.py drops the view for any run that is not at head. Without
    a second ensure the first boot of such an install left every migrated reader on
    "no such table: keyword_mentions_all" until the next restart. Found by the Opus review of
    the readers slice (PR #1250)."""
    import os
    import subprocess
    import sys

    code = (
        "from src.database.session import init_db;"
        "init_db();"
        "from src.database.session import engine;"
        "from sqlalchemy import text;"
        "c = engine.connect();"
        f"n = c.execute(text(\"SELECT count(*) FROM sqlite_master WHERE type='view' AND name='{MENTIONS_VIEW}'\")).scalar();"
        "raise SystemExit(0 if n == 1 else 3)"
    )

    def boot():
        return subprocess.run(
            [sys.executable, "-c", code], cwd=_SRC.parent,
            env={**os.environ, "OO_DATA_DIR": str(tmp_path), "OO_NO_SCHEDULER": "1"},
            capture_output=True, text=True,
        )

    first = boot()
    assert first.returncode == 0, first.stdout + first.stderr
    # An install whose stamp lags its (already healed) schema: the state align_stamp_to_head advances.
    from alembic.script import ScriptDirectory

    from src.database.migrate import _alembic_config

    script = ScriptDirectory.from_config(_alembic_config())
    parent = script.get_revision(script.get_current_head()).down_revision
    assert isinstance(parent, str)
    assert _alembic(["stamp", parent], tmp_path).returncode == 0
    second = boot()
    assert second.returncode == 0, "view missing after the stamp alignment: " + second.stdout + second.stderr

