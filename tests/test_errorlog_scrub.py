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
import re
import sys

import pytest

from src.database import connect
from src.monitoring import errorlog
from src.monitoring import secret_scrub as ss
from tests.js_source_helper import function_body, read_static

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


def test_the_traceback_a_handler_hands_over_as_an_attribute_is_scrubbed_before_its_cut_too(journal):
    """The third place a record's text comes from (the attribute ``log_failure`` writes, which a record with no ``exc_info`` carries):
    the journal keeps the last 1,500 characters of it, and a passphrase the cut falls inside leaves the end of it when the cut is
    made first. A secret is placed so that the cut is five characters into it. MUTATION TARGET: the cut before the scrub, here."""
    assert len(HELD) == 25, "the arithmetic below: the text is 1,605 characters, the cut falls at 105, the secret starts at 100"
    journal.error("failed", extra={ss.TRACEBACK_ATTRIBUTE: "a" * 100 + HELD + "b" * 1480})
    (entry,) = errorlog.recent_errors()
    assert HELD[5:] not in entry["traceback_tail"] and HELD not in entry["traceback_tail"]
    assert entry["traceback_tail"].count("***redacted***") == 1


def test_the_cut_of_every_field_is_made_after_the_scrub_and_the_exception_text_a_record_cached_is_never_read(journal):
    """``Formatter.format`` caches the traceback it prints on the record as ``exc_text``; the journal reads the record's
    ``exc_info`` (or the attribute above), never ``exc_text``, so what another handler formatted raw is not what it writes."""
    try:
        raise ValueError(f"near {_sql(HELD)}")
    except ValueError as exc:
        journal.error("failed", exc_info=exc)
    (entry,) = errorlog.recent_errors()
    assert "ValueError: near PRAGMA key = '***redacted***'" in entry["traceback_tail"]
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, None)
    record.exc_text = f"Traceback...\nValueError: near {_sql(HELD)}"  # raw, as a handler that formatted it left it
    errorlog._JsonlErrorHandler(level=logging.WARNING).emit(record)
    last = errorlog.recent_errors()[-1]
    assert "traceback_tail" not in last and HELD not in json.dumps(last) and "PRAGMA" not in json.dumps(last)


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


# --------------------------------------------------------------------------- #
#  When what the process holds cannot be read, and what the summary counts a record for
# --------------------------------------------------------------------------- #
def test_what_the_process_holds_that_cannot_be_read_leaves_an_entry_that_says_so_and_keeps_none_of_the_records_words(
        journal, monkeypatch):
    """MUTATION TARGET: the unreadable answer treated as "nothing is held". The record is still counted (its level, its logger and
    its time are the journal's own), and neither the message nor the traceback is kept on the chance that it holds no passphrase."""
    monkeypatch.setattr(ss, "held_passphrases", lambda: None)
    try:
        raise RuntimeError(f"near {_sql(HELD)}")
    except RuntimeError as exc:
        journal.error("failed with %s", HELD, exc_info=exc)
    (entry,) = errorlog.recent_errors()
    assert entry["level"] == "ERROR" and entry["logger"] == "tests.errorlog_scrub" and entry["at"]
    assert entry["message"] == ss.UNREADABLE_TEXT and entry["traceback_tail"] == ss.UNREADABLE_TEXT
    raw = json.dumps(entry, ensure_ascii=False)
    assert HELD not in raw and "PRAGMA" not in raw and "failed with" not in raw


def test_the_browsers_and_the_responses_words_are_withheld_the_same_way_when_what_is_held_cannot_be_read(journal, monkeypatch):
    monkeypatch.setattr(ss, "held_passphrases", lambda: None)
    errorlog._frontend_last.clear()
    errorlog._http_last.clear()
    errorlog.note_frontend_error("error", f"failed with {HELD}", source=f"app.js?k={ENV}", endpoint="/api/x")
    errorlog.note_http_error("POST", "/api/unlock", 400, detail=f"bad key {HELD}")
    entries = errorlog.recent_errors()
    assert len(entries) == 2
    raw = json.dumps(entries, ensure_ascii=False)
    assert HELD not in raw and ENV not in raw and "bad key" not in raw and "failed with" not in raw
    assert all(ss.UNREADABLE_TEXT in e["message"] for e in entries)


@pytest.mark.parametrize("passphrase,message", [
    ("database", "sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked"),
    ("locked", "sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked"),
])
def test_a_passphrase_that_is_a_piece_of_a_phrase_the_summary_counts_does_not_zero_the_count(
        journal, monkeypatch, passphrase, message):
    """The summary counts a record for ``database is locked`` by its text, and the text has the passphrases out of it: a
    passphrase of ``database`` would turn the phrase into ``***redacted*** is locked`` and the count to zero (the question a soak
    asks is whether the store was locked). The flag is taken from the text as logged, before the scrub, and holds no text.
    MUTATION TARGET: the flags taken from the scrubbed text, or the summary reading the text only."""
    monkeypatch.setattr(connect, "_passphrase", passphrase)
    journal.error(message)
    (entry,) = errorlog.recent_errors()
    assert passphrase not in entry["message"] and entry["locked"] is True
    assert set(entry) == {"at", "level", "logger", "message", "locked"}, "a boolean, and no text of the record"
    assert errorlog.summary()["locked_errors_total"] == 1


@pytest.mark.parametrize("passphrase,message", [
    ("interrupted", "sqlite3.OperationalError: interrupted"),
    ("deadline", "StatementTimeout: the statement exceeded the 5 s deadline"),
])
def test_a_passphrase_that_is_a_piece_of_an_interrupt_phrase_does_not_zero_that_count_either(
        journal, monkeypatch, passphrase, message):
    monkeypatch.setattr(connect, "_passphrase", passphrase)
    try:
        raise RuntimeError(message)
    except RuntimeError as exc:
        journal.error("the statement was cut short", exc_info=exc)
    (entry,) = errorlog.recent_errors()
    assert passphrase not in entry["message"] + entry["traceback_tail"] and entry["interrupted"] is True, (
        "taken from the traceback as logged"
    )
    assert errorlog.summary()["interrupted_errors_total"] == 1


def test_a_record_that_says_none_of_those_things_carries_no_flag(journal):
    journal.error("a feed answered 404")
    (entry,) = errorlog.recent_errors()
    assert "locked" not in entry and "interrupted" not in entry
    summary = errorlog.summary()
    assert summary["locked_errors_total"] == 0 and summary["interrupted_errors_total"] == 0


def test_a_record_written_before_the_flags_existed_is_still_counted_by_its_text(journal, monkeypatch, tmp_path):
    (tmp_path / "app_errors.jsonl").write_text(
        json.dumps({"at": "2026-10-01T00:00:00+00:00", "level": "ERROR", "logger": "x", "message": "database is locked"}) + "\n",
        encoding="utf-8",
    )
    assert errorlog.summary()["locked_errors_total"] == 1


# --------------------------------------------------------------------------- #
#  The browser's words are sent whole and cut by the server after the scrub
# --------------------------------------------------------------------------- #

def test_the_browser_sends_its_words_whole_so_the_only_cut_is_the_servers_and_comes_after_the_scrub():
    """A cut made in the browser is made BEFORE the scrub and can split a passphrase, leaving a half that no scrub recognises (the
    coordinator's finding L3). MUTATION TARGET: a ``.slice(``, ``.substring(`` or ``.substr(`` put back on the message, the source or
    the endpoint the report carries; what is sliced for the throttle's signature is never sent."""
    body = function_body(read_static("app-core.js"), "_ooReportError")
    sent = [line for line in body.splitlines() if re.search(r"const msg\s*=|body\.source\s*=|body\.endpoint\s*=", line)]
    assert len(sent) == 3, sent
    assert not [line for line in sent if re.search(r"\.(slice|substring|substr)\(", line)], sent
    assert re.search(r"message:\s*msg\s*[,}]", body), "the message is sent as it was made, not as a cut of it"


def test_the_report_a_browser_posts_is_taken_whole_up_to_its_cap_and_refused_over_it_never_cut():
    from pydantic import ValidationError

    from src.api.diagnostics import _FRONTEND_TEXT_MAX, _FrontendError

    whole = "x" * _FRONTEND_TEXT_MAX
    report = _FrontendError(message=whole, source=whole, endpoint=whole)
    assert len(report.message) == len(report.source) == len(report.endpoint) == _FRONTEND_TEXT_MAX
    for field in ("message", "source", "endpoint"):
        with pytest.raises(ValidationError):
            _FrontendError(**{field: "x" * (_FRONTEND_TEXT_MAX + 1)})


def test_a_report_longer_than_the_journals_cut_has_the_passphrase_out_before_the_cut_through_the_route(journal):
    """The path the browser's report takes: the route's model, then the journal. A passphrase straddling the journal's cut (the
    500th character of the message) leaves no half of it."""
    from src.api.diagnostics import _FrontendError, report_frontend_error

    errorlog._frontend_last.clear()
    report_frontend_error(
        _FrontendError(
            message="x" * (500 - 5) + HELD + " and more " + "y" * 3000,
            source="s" * (300 - 4) + ENV,
            endpoint="/api/" + "e" * (300 - 9) + HELD,
        )
    )
    (entry,) = errorlog.recent_errors()
    assert len(entry["message"]) == 500 and HELD[:5] not in entry["message"] and entry["message"].endswith("***re")
    assert ENV[:4] not in entry["source"] and HELD[:5] not in entry["endpoint"]
    raw = json.dumps(entry, ensure_ascii=False)
    for secret in (HELD, ENV):
        for shape in _shapes(secret):
            assert shape not in raw, (shape, raw)
