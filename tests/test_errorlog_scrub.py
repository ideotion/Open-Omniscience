"""The debug bundle's error journal (``src/monitoring/errorlog.py``) is where every WARNING-or-above record of every logger in the
process becomes a record, and the bundle carries it. Whatever module wrote the record and however it wrote the exception, the
passphrases the process holds are out of its message and its traceback, in every shape the code writes one in, before the cut
that keeps their first 500 and last 1,500 characters.

A handler that holds a passphrase writes through ``secret_scrub.log_failure``, which keeps the exception out of ``exc_info``; the
journal then takes the tail of the traceback from the attribute that record carries, so the frames that say where it failed are
still in the bundle.
"""

from __future__ import annotations

import json
import logging
import sys

import pytest

from src.database import connect
from src.monitoring import errorlog
from src.monitoring import secret_scrub as ss

HELD = "kQ7!vLm-it's-the-held-key"  # an apostrophe: the statement that carries it quotes it twice
ENV = "zR4#nPt-the-env-key"


@pytest.fixture
def journal(monkeypatch, tmp_path):
    """A logger of its own with the journal's handler on it, writing to a temporary file, and both passphrases held."""
    monkeypatch.setattr(errorlog, "_log_path", lambda: tmp_path / "app_errors.jsonl")
    monkeypatch.setattr(connect, "_passphrase", HELD)
    monkeypatch.setenv("OO_DB_PASSPHRASE", ENV)
    log = logging.getLogger("tests.errorlog_scrub")
    log.propagate = False
    log.setLevel(logging.DEBUG)
    handler = errorlog._JsonlErrorHandler(level=logging.WARNING)
    log.addHandler(handler)
    try:
        yield log
    finally:
        log.removeHandler(handler)


def _sql(secret: str) -> str:
    return f"PRAGMA key = '{secret.replace(chr(39), chr(39) * 2)}'"


def _shapes(secret: str) -> set[str]:
    doubled = secret.replace("'", "''")
    return {
        secret,
        doubled,
        repr(secret)[1:-1],
        repr(doubled)[1:-1],
        json.dumps(secret)[1:-1],
        json.dumps(secret, ensure_ascii=False)[1:-1],
    }


def test_a_record_with_exc_info_from_any_logger_has_every_passphrase_out_of_its_message_and_its_traceback(journal):
    """The shape the server's own record has when the middleware re-raises: another logger, ``exc_info``, the exception as raised."""
    try:
        raise RuntimeError(f"near {_sql(HELD)}: syntax error ({ENV}) args={(HELD,)!r}")
    except RuntimeError as exc:
        journal.error("Exception in ASGI application\n%s", f"({ENV})", exc_info=exc)
    (entry,) = errorlog.recent_errors()
    assert entry["level"] == "ERROR" and entry["logger"] == "tests.errorlog_scrub"
    assert entry["message"] == "Exception in ASGI application\n(***redacted***)"
    tail = entry["traceback_tail"]
    assert "RuntimeError: near PRAGMA key = '***redacted***': syntax error (***redacted***)" in tail
    assert "Traceback (most recent call last)" in tail, "the frames are kept"
    raw = json.dumps(entry, ensure_ascii=False)
    for secret in (HELD, ENV):
        for shape in _shapes(secret):
            assert shape not in raw, (shape, raw)


def test_the_scrub_comes_before_the_cut_so_a_passphrase_at_the_edge_of_either_leaves_no_half_of_it(journal):
    """A message cut at 500 characters and a traceback cut at its last 1,500, each BEFORE the scrub, keep the part of a passphrase the
    cut fell inside."""
    journal.error("x" * (500 - 5) + HELD + " and the rest")
    try:
        raise ValueError("z" * 100 + HELD + "w" * 1480)
    except ValueError as exc:
        journal.error("failed", exc_info=exc)
    message_entry, traceback_entry = errorlog.recent_errors()
    assert len(message_entry["message"]) == 500 and HELD[:5] not in message_entry["message"]
    assert HELD[-19:] not in traceback_entry["traceback_tail"] and HELD not in traceback_entry["traceback_tail"]
    assert traceback_entry["traceback_tail"].count("***redacted***") == 1, "the tail still shows that something was taken out"


def test_a_record_written_through_log_failure_keeps_the_frames_in_the_tail_and_the_secrets_out_of_them(journal):
    def where_it_failed():
        raise ValueError(f"the key {HELD} did not open the header")

    try:
        where_it_failed()
    except ValueError as exc:
        ss.log_failure(journal, "unhandled error on GET /api/x", exc, HELD)
    (entry,) = errorlog.recent_errors()
    assert entry["message"].startswith("unhandled error on GET /api/x: ValueError: the key ***redacted*** did not open")
    tail = entry["traceback_tail"]
    assert "in where_it_failed" in tail, "the frame of the failure is in the tail"
    assert "ValueError: the key ***redacted*** did not open the header" in tail
    assert HELD not in json.dumps(entry)


def test_the_structural_fields_of_a_record_are_never_scrubbed_even_for_a_passphrase_that_is_a_level_name(
        journal, monkeypatch):
    """Only the words of the record are scrubbed. A passphrase of ``ERROR`` must not turn the level into a marker, or the log
    stops counting its problems."""
    monkeypatch.setattr(connect, "_passphrase", "ERROR")
    journal.error("ERROR: something failed in tests.errorlog_scrub")
    (entry,) = errorlog.recent_errors()
    assert entry["level"] == "ERROR" and entry["logger"] == "tests.errorlog_scrub" and entry["at"]
    assert entry["message"] == "***redacted***: something failed in tests.errorlog_scrub"


def test_a_record_that_holds_no_passphrase_is_written_as_it_always_was(journal):
    journal.warning("a feed answered 404")
    (entry,) = errorlog.recent_errors()
    assert entry["message"] == "a feed answered 404" and "traceback_tail" not in entry


def test_the_environments_passphrase_is_still_taken_out_when_the_store_module_cannot_be_imported(journal, monkeypatch):
    monkeypatch.setitem(sys.modules, "src.database.connect", None)  # an import of it raises
    assert ss.held_passphrases() == (ENV,)
    journal.error(f"failed with {ENV} and {HELD}")
    (entry,) = errorlog.recent_errors()
    assert ENV not in entry["message"] and "failed with ***redacted*** and" in entry["message"]


def test_a_record_from_a_site_that_was_not_given_the_held_passphrase_is_scrubbed_of_it_by_the_journal(journal):
    """A site that holds a backup's passphrase scrubs that one; the exception it caught can still carry the corpus's, which the
    journal knows. The message and the traceback tail it takes from the attribute are scrubbed again here."""
    other = "a-backups-own-passphrase"
    try:
        raise OSError(f"{other} and {HELD} in one message")
    except OSError as exc:
        ss.log_failure(journal, "backup failed", exc, other)
    (entry,) = errorlog.recent_errors()
    raw = json.dumps(entry, ensure_ascii=False)
    for secret in (HELD, other):
        for shape in _shapes(secret):
            assert shape not in raw, (shape, raw)
    assert "OSError: ***redacted*** and ***redacted*** in one message" in entry["traceback_tail"]


def test_a_browser_error_has_the_passphrases_out_of_every_field_and_the_cut_comes_after(journal):
    """``note_frontend_error`` writes what the browser said. The frontend is told to send nothing typed, and the journal does not rely
    on it: the passphrases the process holds are out of the message, the source, the endpoint and the rest, before each is cut."""
    errorlog._frontend_last.clear()
    errorlog.note_frontend_error(
        "error",
        "x" * (500 - 5) + HELD + " and more",
        source=f"app.js?k={ENV}",
        endpoint=f"/api/unlock/{HELD}",
        ui_lang=HELD,
    )
    (entry,) = errorlog.recent_errors()
    assert entry["logger"] == "frontend" and entry["kind"] == "error"
    assert len(entry["message"]) == 500 and HELD[:5] not in entry["message"] and entry["message"].endswith("***re")
    assert entry["source"] == "app.js?k=***redacted***" and entry["endpoint"] == "/api/unlock/***redacted***"
    assert entry["ui_lang"] == "***redacted***"
    raw = json.dumps(entry, ensure_ascii=False)
    for secret in (HELD, ENV):
        for shape in _shapes(secret):
            assert shape not in raw, (shape, raw)


def test_the_throttle_of_browser_errors_keys_on_the_scrubbed_text(journal):
    """The same error twice is one record, and the table the throttle keeps its keys in holds the text with the passphrase out of it:
    a copy of the passphrase must not sit in memory in a table of error texts."""
    errorlog._frontend_last.clear()
    errorlog.note_frontend_error("error", f"failed with {HELD}")
    errorlog.note_frontend_error("error", f"failed with {HELD}")
    assert len(errorlog.recent_errors()) == 1
    assert all(HELD not in repr(k) for k in errorlog._frontend_last)


def test_the_detail_of_an_http_error_has_the_passphrases_out_of_it(journal):
    errorlog._http_last.clear()
    errorlog.note_http_error("POST", "/api/unlock", 400, detail=f"bad key {HELD} and {ENV} " + "y" * 300)
    (entry,) = errorlog.recent_errors()
    assert entry["message"].startswith("HTTP 400 POST /api/unlock — bad key ***redacted*** and ***redacted*** yyy")
    assert HELD not in json.dumps(entry) and ENV not in json.dumps(entry)
