"""
Tests for the encrypted ``event_imports`` DB table + its dual-write mirror (D1, Wave 4 J).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Imported calendar events move off the cleartext ``calendar_feed_imports.json`` side-file
into a durable, encrypted, backup-carried DB row. This conservative slice ships the table +
a lazy access layer (the kv_store template) + a DUAL-WRITE MIRROR at the single imports-save
chokepoint, keeping the JSON authoritative (reads + restore-merge unchanged). Pins: the
mirror stays a faithful copy (full replace), the round-trip reconstructs the imports shape,
empty families survive, a non-SQLite backend is a safe no-op, and the table is registered in
the merge's ignore set so a restore report stays clean.
"""

from __future__ import annotations

from src.database.models import Base


def _fresh_db(tmp_path, monkeypatch):
    """Point the lazy event store at an isolated tmp SQLite file (self-heal creates the table)."""
    from src.events import event_store

    db = tmp_path / "corpus.db"
    monkeypatch.setattr(event_store, "_db_path", lambda: str(db))
    return event_store, str(db)


_IMPORTS = {
    "holidays": {
        "name": "Public holidays",
        "imported_at": "2026-01-01T00:00:00",
        "events": {
            "new year|2026-01-01": {
                "title": "New Year", "date": "2026-01-01",
                "sources": ["feed-a", "feed-b"], "uids": ["u1"],
            },
            "labour day|2026-05-01": {
                "title": "Labour Day", "date": "2026-05-01", "sources": ["feed-a"], "uids": [],
            },
        },
    },
    "user-mine": {  # a user-uploaded calendar (carries the user flag)
        "name": "My calendar", "user": True, "imported_at": "2026-02-02T00:00:00",
        "events": {
            "dentist|2026-03-03": {
                "title": "Dentist", "date": "2026-03-03", "sources": ["user-mine"], "uids": [],
            },
        },
    },
}


def test_sync_then_load_reconstructs_the_imports_shape(tmp_path, monkeypatch):
    event_store, _ = _fresh_db(tmp_path, monkeypatch)
    res = event_store.sync_imports(_IMPORTS)
    assert res["synced"] is True
    assert res["rows"] == 3  # three events across the two families
    assert event_store.count() == 3
    assert event_store.load_imports() == _IMPORTS  # faithful round-trip (incl. user flag)


def test_sync_is_a_full_replace_not_an_append(tmp_path, monkeypatch):
    event_store, _ = _fresh_db(tmp_path, monkeypatch)
    event_store.sync_imports(_IMPORTS)
    smaller = {"holidays": {"name": "Public holidays", "events": {
        "new year|2026-01-01": {"title": "New Year", "date": "2026-01-01",
                                "sources": ["feed-a"], "uids": []},
    }}}
    event_store.sync_imports(smaller)
    # The DB mirrors the LATEST dict exactly — the removed events are gone, not accumulated.
    assert event_store.count() == 1
    assert event_store.load_imports() == smaller


def test_empty_family_survives_the_round_trip(tmp_path, monkeypatch):
    event_store, _ = _fresh_db(tmp_path, monkeypatch)
    data = {"bare": {"name": "Bare family", "events": {}}}
    event_store.sync_imports(data)
    assert event_store.load_imports() == data  # family metadata preserved via a marker row


def test_non_sqlite_backend_is_a_safe_no_op(tmp_path, monkeypatch):
    from src.events import event_store

    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/x")
    assert event_store._db_path() is None
    assert event_store.sync_imports(_IMPORTS) == {"synced": False, "reason": "non-sqlite backend"}
    assert event_store.load_imports() == {}
    assert event_store.count() == 0


def test_self_heal_creates_the_table_on_a_never_initialised_db(tmp_path, monkeypatch):
    # A fresh tmp DB that never ran init_db / migrations: load is an honest empty, and the
    # first sync self-creates the table (the kv_store belt), then reads back.
    event_store, _ = _fresh_db(tmp_path, monkeypatch)
    assert event_store.load_imports() == {}  # no table yet -> {} (never a traceback)
    event_store.sync_imports(_IMPORTS)
    assert event_store.load_imports() == _IMPORTS


def test_dual_write_mirror_fires_on_the_imports_save_chokepoint(tmp_path, monkeypatch):
    # feeds._save_json("calendar_feed_imports.json", ...) is the single chokepoint EVERY event
    # write goes through (import_feed / import_ics_* / auto-import / the restore UNION-merge /
    # remove_user_feed). Saving there must mirror into the DB while writing the JSON.
    from src.events import event_store, feeds

    monkeypatch.setattr(feeds, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(event_store, "_db_path", lambda: str(tmp_path / "corpus.db"))

    feeds._save_json("calendar_feed_imports.json", _IMPORTS)

    # JSON authoritative (still written) AND the DB mirror is in sync.
    assert (tmp_path / "calendar_feed_imports.json").exists()
    assert event_store.load_imports() == _IMPORTS

    # A NON-imports side-file (verdicts) must NOT touch the mirror.
    event_store.sync_imports({})  # clear
    feeds._save_json("calendar_feed_checks.json", {"feed-a": {"status": "ok"}})
    assert event_store.count() == 0


def test_event_imports_is_registered_and_ignored_by_the_merge(tmp_path, monkeypatch):
    # The dual-write mirror table must be in _MERGE_IGNORED so an incoming corpus's mirror
    # rows never show up as an "unmerged table" in a restore report (the events themselves
    # still restore via the JSON side-file UNION-merge).
    import src.backup.merge as merge

    assert "event_imports" in merge._MERGE_IGNORED
    # And the model is registered on the metadata (create_all builds it).
    assert "event_imports" in Base.metadata.tables
