"""An unreadable custody-settings store is not an unset one (queue:1255, THE FIELD DEFECTS OUTSIDE THE WRITE PATH).

The settings live in the main database's key-value table, so an exhausted pool (or a damaged row) made
``load_settings()`` fall back to the legacy default -- auto-log ON -- and an operator who had switched auto-log OFF
could see an ingest logged. Now the read says ``store_unreadable``, auto-log reads OFF, and the ingest path queues the
entry as owed instead of writing it under a guessed setting; it is paid only once the setting reads as ON again.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.custody import pending, settings
from src.custody.settings import CustodySettings, CustodySettingsError, load_settings, save_settings
from src.database.models import Article, Base, Source


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")


def _refuse():
    raise CustodySettingsError("the database refused the read")


def test_an_unreadable_store_reads_as_auto_log_off_and_says_so(monkeypatch):
    monkeypatch.setattr(settings, "_read_raw_checked", _refuse)
    monkeypatch.setattr(settings, "_read_raw_strict", _refuse)
    prefs = load_settings()
    assert prefs.store_unreadable and not prefs.auto_log_on_ingest
    assert prefs.to_dict()["store_unreadable"] is True  # the settings route shows it
    with pytest.raises(CustodySettingsError):
        load_settings(strict=True)


def test_a_missing_store_still_takes_the_legacy_default():
    prefs = load_settings()
    assert not prefs.store_unreadable and prefs.auto_log_on_ingest


def test_store_unreadable_is_never_saved(tmp_path, monkeypatch):
    path = tmp_path / "elsewhere.json"  # a redirected path is read and written as JSON, so the file can be inspected
    monkeypatch.setattr(settings, "_settings_path", lambda: path)
    save_settings({"auto_log_on_ingest": False})
    assert "store_unreadable" not in json.loads(path.read_text(encoding="utf-8"))
    assert not load_settings().auto_log_on_ingest


@pytest.fixture()
def article():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    src = Source(name="c", domain="c.example", rss_url="https://c.example/feed.xml", language="en")
    s.add(src)
    s.flush()
    tag = uuid.uuid4().hex[:6]
    a = Article(url=f"https://c.example/{tag}", canonical_url=f"https://c.example/{tag}", source_id=src.id, title="t",
                content="body", hash=f"hash-{tag}")
    s.add(a)
    s.commit()
    yield a
    s.close()


def test_ingest_queues_the_entry_as_owed_and_writes_nothing(article, monkeypatch):
    from src.custody.log import CustodyLog
    from src.ingest.pipeline import _maybe_record_custody

    monkeypatch.setattr("src.custody.settings.load_settings",
                        lambda: CustodySettings(auto_log_on_ingest=False, store_unreadable=True))
    opened = []
    monkeypatch.setattr(CustodyLog, "__init__", lambda self, *a, **k: opened.append(1) or _refuse())
    _maybe_record_custody(article)
    assert not opened
    assert pending.pending_count() == 1
    # ...and the end-of-pass repayment waits while the setting still cannot be read.
    assert pending.drain_owed() is None


def test_auto_log_switched_off_still_writes_and_queues_nothing(article, monkeypatch):
    from src.custody.log import CustodyLog
    from src.ingest.pipeline import _maybe_record_custody

    monkeypatch.setattr("src.custody.settings.load_settings", lambda: CustodySettings(auto_log_on_ingest=False))
    opened = []
    monkeypatch.setattr(CustodyLog, "__init__", lambda self, *a, **k: opened.append(1) or _refuse())
    _maybe_record_custody(article)
    assert pending.pending_count() == 0 and not opened


# --- from the security read: real stores, the batch path, the manual drain ---------------------------------------------


def _damage(tmp_path, text):
    import sqlite3

    from src.config import kv_store

    con = sqlite3.connect(tmp_path / "open_omniscience.db")
    con.execute("UPDATE app_state SET value = ? WHERE key = ?", (text, settings._KV_KEY))
    con.commit()
    con.close()
    kv_store.kv_invalidate()


@pytest.fixture()
def fresh_kv():
    from src.config import kv_store

    kv_store.kv_invalidate()
    yield
    kv_store.kv_invalidate()


def test_a_real_damaged_row_reads_as_unreadable_and_a_save_still_refuses(tmp_path, fresh_kv):
    save_settings({"auto_log_on_ingest": True, "pqc_enabled": True})
    assert load_settings().pqc_enabled
    _damage(tmp_path, '{"auto_log_on_ingest": tru')
    prefs = load_settings()
    assert prefs.store_unreadable and not prefs.auto_log_on_ingest
    with pytest.raises(CustodySettingsError):
        save_settings({"default_actor": "x"})  # a save never writes the defaults over a row it could not read


@pytest.mark.parametrize("plaintext", [True, False])
def test_a_fresh_install_reads_as_unset_and_creates_no_database(tmp_path, monkeypatch, fresh_kv, plaintext):
    if not plaintext:
        monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
        monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    prefs = load_settings()
    assert not prefs.store_unreadable and prefs.auto_log_on_ingest
    assert not (tmp_path / "open_omniscience.db").exists()


def test_a_batch_opens_no_log_and_owes_every_entry(article, monkeypatch, caplog):
    from src.ingest.pipeline import _CustodyBatch, _maybe_record_custody

    monkeypatch.setattr("src.custody.settings.load_settings",
                        lambda: CustodySettings(auto_log_on_ingest=False, store_unreadable=True))
    with caplog.at_level("WARNING"), _CustodyBatch() as batch:
        _maybe_record_custody(article, batch=batch)
        _maybe_record_custody(article, batch=batch)
        assert batch.opened == 0 and batch.settings_unreadable == 2
    assert pending.pending_count() == 2
    lines = [r for r in caplog.records if "custody" in r.getMessage()]
    assert len(lines) == 1 and lines[0].exc_info is None  # one line for the flush, no traceback per article


def test_the_manual_drain_waits_while_the_settings_cannot_be_read(article, monkeypatch):
    from src.custody.log import CustodyLog
    from src.ingest.pipeline import _maybe_record_custody

    monkeypatch.setattr("src.custody.settings.load_settings",
                        lambda: CustodySettings(auto_log_on_ingest=False, store_unreadable=True))
    _maybe_record_custody(article)
    opened = []
    monkeypatch.setattr(CustodyLog, "__init__", lambda self, *a, **k: opened.append(1) or _refuse())
    out = pending.drain()
    assert out["settings_unreadable"] and out["recorded"] == 0 and out["still_pending"] == 1 and not opened
    assert pending.pending_count() == 1


def test_a_log_opened_on_an_unreadable_store_signs_nothing(tmp_path, monkeypatch):
    """Row 32: the caller read the settings fine, the log's own read failed -- PQC off and local anchoring would be guesses."""
    from src.custody.log import CustodyAction, CustodyLog
    from src.custody.settings import CustodySettingsUnreadable

    monkeypatch.setattr(settings, "_read_raw_checked", _refuse)
    log = CustodyLog(db_path=str(tmp_path / "c.db"))
    try:
        assert log.prefs_unreadable
        with pytest.raises(CustodySettingsUnreadable):
            log.record("article:1", "a" * 64, CustodyAction.INGEST)
        assert log.all_entries() == []
    finally:
        log.close()
    # Given explicitly, nothing is guessed: the log signs.
    from src.custody.signing import HybridSigner

    with CustodyLog(db_path=str(tmp_path / "c.db"), signer=HybridSigner(use_pqc=False), anchoring_mode="local") as ok:
        assert not ok.prefs_unreadable
        ok.record("article:1", "a" * 64, CustodyAction.INGEST)


def test_the_log_route_answers_503_on_an_unreadable_store(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setattr(settings, "_read_raw_checked", _refuse)
    r = TestClient(app).post("/api/custody/log", json={"item_id": "article:1", "item_hash": "a" * 64,
                                                        "action": "ingest"})
    assert r.status_code == 503 and "could not be read" in r.json()["detail"]


def test_a_drain_stops_when_the_log_opens_on_an_unreadable_store(tmp_path):
    """The drain read its settings fine; the log it opens could not: nothing is tried, every entry stays owed."""

    class _Log:
        prefs_unreadable = True
        closed = False

        def close(self):
            _Log.closed = True

    pending.note_failed(1, item_hash="a" * 64)
    out = pending.drain(prefs=CustodySettings(), log_factory=_Log)
    assert out["settings_unreadable"] is True and out["recorded"] == 0 and out["still_pending"] == 1 and _Log.closed


def test_a_batch_drops_a_log_that_opened_on_an_unreadable_store(article, monkeypatch):
    """The pipeline's read is fine, the batch log's own read is not: that entry is owed and the next article reopens."""
    from src.custody.log import CustodyLog
    from src.ingest.pipeline import _CustodyBatch, _maybe_record_custody

    reads = iter([CustodySettings(), CustodySettings(auto_log_on_ingest=False, store_unreadable=True),
                  CustodySettings(), CustodySettings()])
    monkeypatch.setattr("src.custody.settings.load_settings", lambda *a, **k: next(reads))
    with _CustodyBatch() as batch:
        _maybe_record_custody(article, batch=batch)  # the log opens on the unreadable read: refused, owed
        _maybe_record_custody(article, batch=batch)  # a fresh log, read fine: written
        assert batch.opened == 2 and batch.settings_unreadable == 1
    assert pending.pending_count() == 1
    with CustodyLog(signer=__import__("src.custody.signing", fromlist=["x"]).HybridSigner(use_pqc=False),
                    anchoring_mode="local") as log:
        assert len(log.entries_for(f"article:{article.id}")) == 1


def test_the_settings_panel_and_the_reconcile_result_say_what_could_not_be_read():
    """Row 33: store_unreadable, a drain's settings_unreadable and its queue_read_error each reach the screen, x12."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "src" / "static" / "app-ai-tools.js").read_text(encoding="utf-8")
    assert "s.store_unreadable ?" in js and "r.settings_unreadable" in js and "r.queue_read_error" in js
    assert js.count("const notes = _custDrainNotes(d)") == 2  # the gap check and the record-gaps button both say it
    keys = [
        "The custody settings could not be read, so automatic logging is off and each new entry is queued until they can "
        "be read. The switches below show the defaults, not your saved choice, and saving is refused until the settings "
        "read again.",
        "Nothing was recorded: the custody settings could not be read, so no entry is signed under guessed preferences. "
        "The entries stay queued; try again once the settings can be read.",
        "The queue of owed entries could not be read ({reason}), so the count of queued entries may be low.",
    ]
    for loc in sorted((root / "src" / "static" / "locales").glob("*.json")):
        data = json.loads(loc.read_text(encoding="utf-8"))
        for k in keys:
            assert data.get(k), (loc.name, k[:40])
            assert ("{reason}" in data[k]) == ("{reason}" in k), loc.name
