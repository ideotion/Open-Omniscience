"""
C8 — the automatic language-cleanup step must name its own failure, and its
bulk write must not bypass the single-writer gate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two independent defects, found in the same field bundle
(``auto_cleanup.last_tally.language`` reading ``{"skipped": "error"}`` on EVERY
run, beside sibling blocks reporting full arithmetic):

1. ``maybe_cleanup_keywords``'s three ``except Exception:`` clauses each
   recorded a bare ``"error"`` string -- something failed, nothing about what.
2. The reason it failed on EVERY run: ``reconcile_keyword_language``'s write
   path is ``session.bulk_update_mappings(Keyword, updates)``, a LEGACY bulk-ORM
   operation that (empirically confirmed against this repo's pinned SQLAlchemy)
   writes through the transaction's raw ``Connection`` directly
   (``bulk_persistence._bulk_update`` -> ``persistence._emit_update_statements``)
   rather than through ``Session.execute()`` -- so it fires NEITHER
   ``before_flush`` NOR ``do_orm_execute``, the two hooks
   ``src.database.writer.register_write_gate`` relies on to take the
   single-writer gate. It reaches SQLite outside the gate every time it runs
   with a real update to make, and a concurrent long-held writer (any ordinary
   ingest write) turns that into a raw ``sqlite3.OperationalError: database is
   locked`` once ``busy_timeout`` elapses.
"""

from __future__ import annotations

import threading

from sqlalchemy import create_engine, event, insert, text
from sqlalchemy.orm import sessionmaker

from src.analytics.store import maybe_cleanup_keywords, reconcile_keyword_language
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from src.database.writer import _on_after_transaction_end, _on_before_flush, _on_orm_execute


def _wired_sessionmaker(tmp_path, *, busy_timeout_ms: int = 200):
    """A file-backed SQLite sessionmaker with the REAL gate handlers attached --
    the same idiom tests/test_write_gate.py uses, so cross-thread contention is
    genuine and a short busy_timeout means an UNGATED write fails fast."""
    db = tmp_path / "c8.db"
    engine = create_engine(
        f"sqlite:///{db}", future=True, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        cur.close()

    Base.metadata.create_all(engine)
    Maker = sessionmaker(bind=engine, autoflush=False, future=True)
    event.listen(Maker, "before_flush", _on_before_flush)
    event.listen(Maker, "do_orm_execute", _on_orm_execute)
    event.listen(Maker, "after_transaction_end", _on_after_transaction_end)
    return engine, Maker


def _seed_relanguageable_corpus(Maker):
    """One keyword whose stored language disagrees with a clear article-majority
    signature, so ``reconcile_keyword_language`` actually has something to WRITE
    (an empty ``updates`` list would never touch ``bulk_update_mappings`` at all
    and would prove nothing)."""
    s = Maker()
    s.add(Source(name="s", domain="s.example"))
    s.add(Keyword(term="k", normalized_term="k", language="fr"))  # wrong on purpose
    s.flush()
    for i in range(1, 11):
        s.add(
            Article(
                title=f"a{i}",
                url=f"https://s.example/{i}",
                canonical_url=f"https://s.example/{i}",
                source_id=1,
                hash=f"h{i}",
                content=f"body {i}",
                language="en",  # a clean, unanimous en majority
            )
        )
    s.flush()
    rows = [{"keyword_id": 1, "article_id": i, "count": 1} for i in range(1, 11)]
    s.execute(insert(KeywordMention), rows)
    s.commit()
    s.close()


def test_bulk_update_mappings_never_locked_against_a_long_held_writer(tmp_path):
    """FAILS on the current (unfixed) code: reconcile_keyword_language's
    ``session.bulk_update_mappings`` call reaches SQLite outside the gate, so a
    concurrent long-held writer (any ordinary flush-based write, held well past
    busy_timeout) makes it raise a raw 'database is locked' -- deterministically,
    because the reproducer names exactly the shape the field bundle showed."""
    engine, Maker = _wired_sessionmaker(tmp_path)
    _seed_relanguageable_corpus(Maker)

    errors: list[Exception] = []
    holder_in = threading.Event()
    reconciler_done = threading.Event()

    def holder():
        s = Maker()
        try:
            s.add(Source(name="s2", domain="s2.example"))
            s.flush()  # takes the gate AND the real SQLite write lock
            holder_in.set()
            # Hold well past busy_timeout (200ms) — the "long collection pass"
            # shape the field bundle's every-run failure implies.
            reconciler_done.wait(2)
            s.commit()
        except Exception as exc:  # noqa: BLE001 - capture for the assertion
            errors.append(exc)
        finally:
            s.close()

    def reconciler():
        holder_in.wait(2)
        s = Maker()
        try:
            out = reconcile_keyword_language(s)
            assert out["relanguaged"] == 1, f"the write should have landed: {out!r}"
        except Exception as exc:  # noqa: BLE001 - the bug lands here
            errors.append(exc)
        finally:
            s.close()
            reconciler_done.set()

    th, tr = threading.Thread(target=holder), threading.Thread(target=reconciler)
    th.start()
    tr.start()
    th.join(5)
    tr.join(5)

    assert errors == [], (
        f"a gated keyword-language write must never lock against another writer: {errors!r}"
    )
    with Maker() as s:
        lang = s.execute(text("SELECT language FROM keywords WHERE id=1")).scalar()
    assert lang == "en", f"the reconciled language should have landed as 'en', got {lang!r}"
    engine.dispose()


def test_maybe_cleanup_keywords_records_the_real_exception(monkeypatch, tmp_path):
    """FAILS on the current (unfixed) code: a forced failure in the language
    reconcile step recorded a bare ``{"skipped": "error"}`` — indistinguishable
    from any other failure. It must now name the exception class + message."""
    import src.analytics.store as store

    class _Session:
        """The minimum surface maybe_cleanup_keywords touches before it reaches
        the language step (which is monkeypatched to fail directly, so the real
        session behaviour of the earlier steps is irrelevant here)."""

        def rollback(self):
            pass

    monkeypatch.setattr(store, "keyword_cleanup_state", lambda: {"last_run": None})
    monkeypatch.setattr(store, "prune_orphan_keywords", lambda session, **kw: {"pruned": 0})
    monkeypatch.setattr(
        store, "reconcile_keyword_entity_status", lambda session: {"updated": 0}
    )

    def _boom(session):
        raise ValueError("simulated reconcile failure — a distinctive marker")

    monkeypatch.setattr(store, "reconcile_keyword_language", _boom)
    monkeypatch.setattr(store, "_cleanup_marker_path", lambda: tmp_path / "keyword_cleanup.json")

    out = maybe_cleanup_keywords(_Session())

    assert out["language"] != {"skipped": "error"}, (
        "must not regress to the old undiagnosable bare string"
    )
    assert out["language"]["skipped"].startswith("ValueError:"), (
        f"must name the exception class: {out['language']!r}"
    )
    assert "simulated reconcile failure" in out["language"]["skipped"], (
        f"must carry the exception message: {out['language']!r}"
    )


def test_a_clean_run_still_reports_real_arithmetic(tmp_path):
    """The distinguishing half: a step that succeeds must still report its real
    tally, not an error shape — so the two stay distinguishable in the bundle."""
    engine, Maker = _wired_sessionmaker(tmp_path)
    _seed_relanguageable_corpus(Maker)
    s = Maker()
    try:
        out = maybe_cleanup_keywords(s)
    finally:
        s.close()
    engine.dispose()
    assert out["language"].get("relanguaged") == 1, out["language"]
    assert "skipped" not in out["language"], out["language"]
