"""The FTS update trigger is COLUMN-SCOPED, and a legacy unscoped one self-heals (F2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE COST THIS PINS (docs/audit/15_FIELD_INSTANCE_SLOWNESS_2026-09-21.md, finding F2).
``article_fts_au`` fired on EVERY update to ``articles``, and since PRH-01 (2026-09-07)
``index_article`` stamps ``keyword_indexed_at`` unconditionally -- so every re-index
pass updated the article row, and the trigger answered by deleting and re-inserting that
document in the FTS5 index. The 2026-08-03 throughput analysis measured that
delete+insert at 3.3-4.6 ms an article IN MEMORY and recorded it as a one-time ingest
cost; it has been a per-pass cost on a 1.34 M-document encrypted index ever since.

The tests are deliberately BEHAVIOURAL, not textual: they drive real UPDATEs through a
real FTS5 index and assert what the index then contains. A test that only grepped the
DDL for ``UPDATE OF`` would pass on a trigger that had stopped keeping the index
correct, which is the one thing that must never happen here.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.fts import ensure_fts, search_ids
from src.database.models import Article, Base, Source

#: The trigger as it was written before the scoping -- the exact SQL an older store
#: carries on disk today. Recreated here rather than imported so the heal is tested
#: against the REAL legacy shape and cannot silently start testing its replacement.
_LEGACY_AU = """
CREATE TRIGGER article_fts_au AFTER UPDATE ON articles BEGIN
    INSERT INTO article_fts(article_fts, rowid, title, content)
    VALUES ('delete', old.id, old.title, old.content);
    INSERT INTO article_fts(rowid, title, content)
    VALUES (new.id, new.title, new.content);
END
"""


def _engine():
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )


def _store(*, n=3):
    eng = _engine()
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
        for i in range(n):
            s.add(
                Article(
                    url=f"u{i}",
                    canonical_url=f"u{i}",
                    source_id=1,
                    title=f"Story {i}",
                    content=f"election inflation economy report number {i}",
                    hash=f"h{i}",
                    language="en",
                )
            )
        s.commit()
    ensure_fts(eng)
    return eng, Session


class _FtsSpy:
    """Every statement an engine executed -- used to prove a rebuild did NOT run."""

    def __init__(self, eng):
        self.stmts: list[str] = []
        event.listen(eng, "before_cursor_execute", self._rec)

    def _rec(self, conn, cursor, statement, parameters, context, executemany):
        self.stmts.append(statement)


def _fts_digest(eng) -> list[tuple]:
    """A fingerprint of the index's OWN storage, so "did the trigger fire?" is answered
    without trusting the trigger. ``article_fts_data`` is FTS5's internal b-tree: a
    delete+insert of a document rewrites blocks there, and an UPDATE the trigger
    correctly ignores leaves them byte-identical."""
    with eng.begin() as c:
        return [tuple(r) for r in c.execute(text("SELECT id, block FROM article_fts_data")).all()]


def _hits(Session, term: str) -> list[int]:
    """Ranked ids for a term -- ``search_ids`` takes a SESSION, not an engine."""
    with Session() as s:
        return search_ids(s, term) or []


def _trigger_sql(eng) -> str:
    with eng.begin() as c:
        row = c.execute(
            text("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='article_fts_au'")
        ).fetchone()
    return (row[0] if row else "") or ""


# --------------------------------------------------------------------------- #
# The scoping itself                                                          #
# --------------------------------------------------------------------------- #


def test_an_update_to_an_unindexed_column_does_not_rewrite_the_index():
    """THE MEASUREMENT THIS PR IS FOR: the re-index stamp must not re-index the document."""
    eng, Session = _store()
    before = _fts_digest(eng)
    assert before, "the index must be populated, or this test proves nothing"

    with eng.begin() as c:
        # Exactly what index_article does at the end of every pass, since PRH-01.
        c.execute(text("UPDATE articles SET keyword_indexed_at = '2026-09-21T00:00:00Z'"))

    assert _fts_digest(eng) == before, (
        "an UPDATE naming only keyword_indexed_at rewrote the FTS index"
    )


def test_an_update_to_content_still_reindexes_the_document():
    """The safe direction: the index may never go stale behind a scoped trigger."""
    eng, Session = _store()
    assert _hits(Session, "rutabaga") == []

    with eng.begin() as c:
        c.execute(text("UPDATE articles SET content = 'a rutabaga harvest' WHERE id = 1"))

    assert _hits(Session, "rutabaga") == [1]
    # And the OLD terms for that document are gone -- a delete+insert, not an insert.
    assert 1 not in _hits(Session, "inflation")


def test_an_update_to_title_still_reindexes_the_document():
    eng, Session = _store()
    with eng.begin() as c:
        c.execute(text("UPDATE articles SET title = 'Quinoa dispatch' WHERE id = 2"))
    assert _hits(Session, "quinoa") == [2]


def test_a_same_value_write_to_content_still_fires():
    """SQLite fires ``UPDATE OF`` on MENTION, not on change. Wasteful, never stale --
    and that is the direction to fail in, so it is pinned rather than left to chance."""
    eng, Session = _store()
    before = _fts_digest(eng)
    with eng.begin() as c:
        c.execute(text("UPDATE articles SET content = content WHERE id = 1"))
    assert _fts_digest(eng) != before


# --------------------------------------------------------------------------- #
# The boot self-heal                                                          #
# --------------------------------------------------------------------------- #


def test_a_legacy_unscoped_trigger_is_replaced_on_the_next_ensure():
    """``CREATE TRIGGER IF NOT EXISTS`` can never replace one, so every store built
    before the scoping would keep the unscoped trigger forever without this."""
    eng, Session = _store()
    with eng.begin() as c:
        c.execute(text("DROP TRIGGER article_fts_au"))
        c.execute(text(_LEGACY_AU))
    assert "AFTER UPDATE OF" not in _trigger_sql(eng)

    # A legacy store behaves the old way: the stamp rewrites the index.
    before = _fts_digest(eng)
    with eng.begin() as c:
        c.execute(text("UPDATE articles SET keyword_indexed_at = '2026-09-20T00:00:00Z'"))
    assert _fts_digest(eng) != before, "the legacy trigger should have rewritten the index"

    ensure_fts(eng)  # the next unlock

    assert "AFTER UPDATE OF" in " ".join(_trigger_sql(eng).split()).upper()
    healed = _fts_digest(eng)
    with eng.begin() as c:
        c.execute(text("UPDATE articles SET keyword_indexed_at = '2026-09-22T00:00:00Z'"))
    assert _fts_digest(eng) == healed
    # ...and the index still answers, so the heal did not cost the corpus its index.
    assert _hits(Session, "inflation")


def test_the_heal_never_rebuilds_the_index():
    """The P0.4 constraint: a boot may not pay a corpus-scaled cost. Dropping and
    re-creating a trigger does not touch the index, and must not trigger a rebuild."""
    eng, Session = _store()
    with eng.begin() as c:
        c.execute(text("DROP TRIGGER article_fts_au"))
        c.execute(text(_LEGACY_AU))

    spy = _FtsSpy(eng)
    action = ensure_fts(eng)

    assert action == "skipped", f"the heal must not provoke a rebuild, got {action!r}"
    assert not any("'rebuild'" in s or "'delete-all'" in s for s in spy.stmts)
    # No corpus scan either: the probe reads one sqlite_master row.
    assert not any("count(*) from articles" in s.lower() for s in spy.stmts)


def test_the_heal_is_idempotent_and_silent_on_an_already_scoped_store():
    eng, Session = _store()
    scoped = _trigger_sql(eng)
    for _ in range(3):
        ensure_fts(eng)
    assert _trigger_sql(eng) == scoped


def test_a_store_with_no_update_trigger_simply_gets_the_scoped_one():
    eng, Session = _store()
    with eng.begin() as c:
        c.execute(text("DROP TRIGGER article_fts_au"))
    ensure_fts(eng)
    assert "AFTER UPDATE OF" in " ".join(_trigger_sql(eng).split()).upper()
