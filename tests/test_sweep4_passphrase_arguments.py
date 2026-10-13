"""The held passphrase is handed to ``log_failure`` where a function holds one (sink sweep 4/4, the independent read's three finds).

A driver error can carry the key; ``log_failure`` takes it out only if it is passed. Each test plants a passphrase in the exception a
site catches and fails if the site stops passing it: dropping the argument from ``log_failure`` makes the planted text reach the log.
"""

from __future__ import annotations

import contextlib
import logging

PASS = "planted-passphrase-for-sweep-four"


def _no_leak(caplog):
    text = "\n".join(r.getMessage() + str(getattr(r, "scrubbed_traceback", "")) + str(r.exc_info) for r in caplog.records)
    assert PASS not in text, text
    return text


def test_corpus_facts_scrubs_the_key_it_opened_the_store_with(tmp_path, monkeypatch, caplog):
    from src.backup import stream_backup
    from src.database import connect as connect_mod

    def boom(*a, **k):
        raise RuntimeError(f"driver said {PASS}")

    monkeypatch.setattr(connect_mod, "connect", boom)
    with caplog.at_level(logging.WARNING):
        stream_backup._corpus_facts(tmp_path / "x.db", key=PASS)
    assert "could not open the corpus for stats" in _no_leak(caplog)


def test_snapshot_preserving_scrubs_the_process_passphrase(tmp_path, monkeypatch, caplog):
    from src.database import connect as connect_mod

    src = tmp_path / "src.db"
    src.write_bytes(b"x")

    def boom(*a, **k):
        raise RuntimeError(f"copy failed {PASS}")

    monkeypatch.setattr(connect_mod, "is_encrypted_file", lambda p: True)
    monkeypatch.setattr(connect_mod, "get_passphrase", lambda: PASS)
    monkeypatch.setattr(connect_mod, "_quiesced_file_copy", boom)
    with caplog.at_level(logging.WARNING), contextlib.suppress(Exception):  # the codec path after the log needs a real store
        connect_mod.snapshot_preserving(src, tmp_path / "dest.db", allow_file_copy=True)
    assert "the quiesced file-copy snapshot failed" in _no_leak(caplog)


def test_import_queue_scrubs_the_backups_passphrase(tmp_path, monkeypatch, caplog):
    from src.backup import import_queue
    from src.scheduler import runner

    def boom():
        raise RuntimeError(f"window failed {PASS}")

    class _Window:
        def __enter__(self):
            boom()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(runner, "exclusive_window", lambda *a, **k: _Window())
    mgr = import_queue.ImportQueueManager(state_path=tmp_path / "state.json")
    monkeypatch.setattr(mgr, "_drive", lambda: None)
    mgr._passphrase = PASS
    with caplog.at_level(logging.WARNING):
        with contextlib.suppress(Exception):  # only the log line is under test
            mgr._run()
    assert "the exclusive window for the import failed" in _no_leak(caplog)
