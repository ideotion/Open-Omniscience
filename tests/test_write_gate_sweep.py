"""The write-gate hold sweep (2026-10-16): a bulk write that used to hold the single-writer gate for the
whole of it now holds it for one slice or one chunk at a time.

THE HOLD IS NOT READ FROM A CLOCK. A test that waited for a second would pass on a fast machine and say
nothing about a 3-million-keyword store. What is pinned is the SHAPE that makes the hold short: the gate
is taken afresh for each slice or chunk (``write_lock()`` is entered once per unit and left before the
next), the gate is FREE when each unit asks for it, and no unit's statement runs outside its own
enter/exit pair. A mutant that goes back to one hold around the loop turns every one of these red.

The sessions here carry the REAL gate handlers on a file-backed engine, the idiom of
``tests/test_mention_diff_write.py``, because a session without them never takes the gate and the
assertions would be about nothing.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, func
from sqlalchemy.orm import sessionmaker

from src.database import writer
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def gated(tmp_path):
    """A file-backed session factory with the real gate handlers, autoflush off like the app's."""
    engine = create_engine(f"sqlite:///{tmp_path / 'sweep.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, future=True)
    event.listen(maker, "before_flush", writer._on_before_flush)
    event.listen(maker, "do_orm_execute", writer._on_orm_execute)
    event.listen(maker, "after_transaction_end", writer._on_after_transaction_end)
    s = maker()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    s._sweep_engine = engine  # type: ignore[attr-defined]
    yield s
    s.close()
    engine.dispose()


def _persisted(db, sql: str):
    """Read ``sql`` on a FRESH connection: what a commit made durable, not what the writing session still holds uncommitted."""
    from sqlalchemy import text

    with db._sweep_engine.connect() as c:  # type: ignore[attr-defined]
        return c.execute(text(sql)).fetchall()


class _Log:
    """What the gate saw: ``enter``/``exit`` of every ``write_lock()`` and the statements named in ``watch``."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.free_on_entry: list[bool] = []

    def hold_widths(self, marker: str) -> list[int]:
        """How many ``marker`` events each enter/exit pair contains (statements outside any pair are counted as -1)."""
        out: list[int] = []
        depth = 0
        n = 0
        for e in self.events:
            if e == "enter":
                depth += 1
                if depth == 1:
                    n = 0
            elif e == "exit":
                depth -= 1
                if depth == 0:
                    out.append(n)
            elif e == marker:
                if depth == 0:
                    out.append(-1)
                else:
                    n += 1
        return out


@pytest.fixture()
def gate_log(gated, monkeypatch):
    log = _Log()
    real = writer.write_lock

    @contextmanager
    def _recording(timeout=None):
        log.free_on_entry.append(not writer.write_gate.held_by_current_thread())
        log.events.append("enter")
        try:
            with real(timeout):
                yield
        finally:
            log.events.append("exit")

    monkeypatch.setattr(writer, "write_lock", _recording)

    @event.listens_for(gated._sweep_engine, "before_cursor_execute")
    def _watch(_conn, _cursor, statement, _params, _context, _many):
        s = " ".join(statement.split())
        if s.startswith("DELETE FROM articles "):
            log.events.append("delete-articles")
        elif s.startswith("UPDATE keywords SET") and "WHERE keywords.id >" in s:
            log.events.append("zero-keywords")
        elif s.startswith("UPDATE keywords SET") and "WHERE keywords.id = ?" in s:
            log.events.append("update-keywords")

    return log


def _article(db, h, *, source_id=1):
    a = Article(
        url=f"https://x.test/{h}",
        canonical_url=f"https://x.test/{h}",
        source_id=source_id,
        title=f"T-{h}",
        content=f"body {h}",
        hash=h,
        language="en",
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


# --------------------------------------------------------------------------------------------------
# backfill_keyword_counters: one slice, one hold
# --------------------------------------------------------------------------------------------------


def _seed_keywords(db, n_keywords: int, mentionless: set[int]) -> dict[int, tuple[int, int]]:
    """``n_keywords`` keywords with STALE counters; every id outside ``mentionless`` is mentioned in two articles."""
    a1, a2 = _article(db, "k1"), _article(db, "k2")
    expect: dict[int, tuple[int, int]] = {}
    for i in range(1, n_keywords + 1):
        db.add(Keyword(id=i, term=f"t{i}", normalized_term=f"t{i}", mention_count=999, article_count=999))
    db.commit()
    for i in range(1, n_keywords + 1):
        if i in mentionless:
            expect[i] = (0, 0)
            continue
        db.add(KeywordMention(keyword_id=i, article_id=a1.id, count=i))
        db.add(KeywordMention(keyword_id=i, article_id=a2.id, count=1))
        expect[i] = (i + 1, 2)
    db.commit()
    return expect


def test_the_counter_backfill_takes_the_gate_once_per_slice_and_each_time_it_is_free(gated, gate_log, monkeypatch):
    from src.analytics import store
    from src.analytics.store import backfill_keyword_counters

    expect = _seed_keywords(gated, 10, mentionless={4, 5, 9})
    monkeypatch.setattr(store, "_RECONCILE_SCAN_CHUNK", 3)  # 10 keywords -> slices of 3, 3, 3, 1

    out = backfill_keyword_counters(gated)

    # Every slice zeroed its own range under its own hold: four slices, one zeroing statement in each pair, none outside one.
    assert gate_log.hold_widths("zero-keywords") == [1, 1, 1, 1]
    assert gate_log.free_on_entry == [True, True, True, True]
    # The result is the live aggregate across every slice boundary, the mentionless keywords zeroed and not left stale.
    gated.expire_all()
    got = {k.id: (k.mention_count, k.article_count) for k in gated.query(Keyword).all()}
    assert got == expect
    assert {r[0]: (r[1], r[2]) for r in _persisted(gated, "SELECT id, mention_count, article_count FROM keywords")} == expect
    assert out == {"keywords": 10, "with_mentions": 7}


def test_the_counter_backfill_of_an_empty_table_takes_no_hold(gated, gate_log):
    from src.analytics.store import backfill_keyword_counters

    assert backfill_keyword_counters(gated) == {"keywords": 0, "with_mentions": 0}
    assert gate_log.events == []


def test_the_counter_backfill_zeroes_a_stale_keyword_whose_last_mention_was_removed(gated, gate_log, monkeypatch):
    """The slice that has NO mentioned keyword at all still zeroes its range (the old code zeroed everything first)."""
    from src.analytics import store
    from src.analytics.store import backfill_keyword_counters

    expect = _seed_keywords(gated, 6, mentionless={4, 5, 6})
    monkeypatch.setattr(store, "_RECONCILE_SCAN_CHUNK", 3)
    backfill_keyword_counters(gated)
    gated.expire_all()
    assert {k.id: (k.mention_count, k.article_count) for k in gated.query(Keyword).all()} == expect
    assert gate_log.hold_widths("zero-keywords") == [1, 1]


# --------------------------------------------------------------------------------------------------
# delete_imported_newsletters: one chunk, one hold, one commit
# --------------------------------------------------------------------------------------------------


def _seed_newsletters(db, n: int):
    from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

    nl = Source(name="NL", domain=NEWSLETTER_SOURCE_DOMAINS[0], enabled=False)
    db.add(nl)
    db.commit()
    kw = Keyword(term="k", normalized_term="k")
    db.add(kw)
    db.commit()
    ids = []
    for i in range(n):
        a = _article(db, f"n{i}", source_id=nl.id)
        db.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1))
        ids.append(a.id)
    db.commit()
    keep = _article(db, "keep", source_id=1)
    db.add(KeywordMention(keyword_id=kw.id, article_id=keep.id, count=1))
    db.commit()
    return ids, keep.id


def test_the_newsletter_removal_holds_the_gate_for_one_chunk_at_a_time(gated, gate_log, monkeypatch):
    from src.ingest import email as email_mod

    ids, keep_id = _seed_newsletters(gated, 5)
    monkeypatch.setattr(email_mod, "_NEWSLETTER_DELETE_CHUNK", 2)  # 5 articles -> chunks of 2, 2, 1

    out = email_mod.delete_imported_newsletters(gated)

    assert out["removed_articles"] == 5
    # One article DELETE per hold, three holds: the gate was given back between the chunks.
    widths = gate_log.hold_widths("delete-articles")
    assert -1 not in widths, "an article DELETE ran outside any hold of the gate"
    assert [w for w in widths if w] == [1, 1, 1]  # the holds that carry a DELETE; the counter repair after them carries none
    # The holds were not nested in a longer one: each chunk found the gate free.
    assert gate_log.free_on_entry[:3] == [True, True, True]
    gated.expire_all()
    assert [r[0] for r in _persisted(gated, "SELECT id FROM articles")] == [keep_id]  # committed, not only pending in the session
    assert [a.id for a in gated.query(Article).all()] == [keep_id]
    assert gated.query(func.count(KeywordMention.id)).scalar() == 1  # the kept article's mention, nothing else
    # The counters were repaired at the end of the pass.
    kw = gated.query(Keyword).one()
    assert (kw.mention_count, kw.article_count) == (1, 1)


def test_the_newsletter_removal_chunk_stays_under_the_sqlite_variable_cap():
    """A chunk's ids are bound as variables in one ``IN (...)``: SQLite's default cap is 999, so the default chunk may not grow past 900."""
    from src.ingest import email as email_mod

    assert 1 <= email_mod._NEWSLETTER_DELETE_CHUNK <= 900


def test_an_interrupted_newsletter_removal_is_finished_by_running_it_again(gated, monkeypatch):
    """A pass that stops between two chunks leaves the earlier chunks gone and the later ones whole; the next pass finds the rest."""
    import sqlalchemy

    from src.ingest import email as email_mod

    ids, keep_id = _seed_newsletters(gated, 5)
    monkeypatch.setattr(email_mod, "_NEWSLETTER_DELETE_CHUNK", 2)  # chunks of 2, 2, 1
    real_execute = gated.execute
    seen = {"articles": 0}

    def _fail_the_third_chunk(stmt, *a, **k):
        if isinstance(stmt, sqlalchemy.sql.dml.Delete) and stmt.table.name == "articles":
            seen["articles"] += 1
            if seen["articles"] == 3:
                raise RuntimeError("stopped between chunks")
        return real_execute(stmt, *a, **k)

    monkeypatch.setattr(gated, "execute", _fail_the_third_chunk)
    with pytest.raises(RuntimeError):
        email_mod.delete_imported_newsletters(gated)
    gated.rollback()
    monkeypatch.setattr(gated, "execute", real_execute)

    # Two chunks (four articles) were committed; the fifth is still there, and so is the one that is not a newsletter.
    assert {a.id for a in gated.query(Article).all()} == {ids[4], keep_id}
    out = email_mod.delete_imported_newsletters(gated)
    assert out["removed_articles"] == 1
    assert {a.id for a in gated.query(Article).all()} == {keep_id}


# --------------------------------------------------------------------------------------------------
# reconcile_keyword_entity_status: the downgrades are written one batch per hold
# --------------------------------------------------------------------------------------------------


def test_the_entity_status_downgrades_are_written_one_batch_per_hold(gated, gate_log, monkeypatch):
    from src.analytics import store
    from src.analytics.store import reconcile_keyword_entity_status

    for i in range(12):  # Title-Case "entities" of the pre-2026-06-16 rule: every one fails the all-caps shape check
        gated.add(Keyword(term=f"Word{i}", normalized_term=f"Word{i}", is_entity=True, entity_type="entity"))
    gated.add(Keyword(term="WHO", normalized_term="WHO", is_entity=True, entity_type="entity"))  # a valid acronym: kept
    gated.commit()
    monkeypatch.setattr(store, "_LANG_UPDATE_BATCH", 5)  # 12 downgrades -> batches of 5, 5, 2

    out = reconcile_keyword_entity_status(gated)

    assert out == {"checked": 13, "downgraded": 12}
    assert gate_log.hold_widths("update-keywords") == [1, 1, 1]
    assert gate_log.free_on_entry == [True, True, True]
    gated.expire_all()
    assert gated.query(func.count(Keyword.id)).filter(Keyword.is_entity.is_(True)).scalar() == 1
    assert _persisted(gated, "SELECT count(*) FROM keywords WHERE is_entity = 1") == [(1,)]  # committed, not only pending in the session


def test_an_entity_status_pass_with_nothing_to_downgrade_takes_no_hold(gated, gate_log):
    from src.analytics.store import reconcile_keyword_entity_status

    gated.add(Keyword(term="WHO", normalized_term="WHO", is_entity=True, entity_type="entity"))
    gated.commit()
    assert reconcile_keyword_entity_status(gated) == {"checked": 1, "downgraded": 0}
    assert gate_log.events == []

