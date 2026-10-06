"""The global exception handler (``src/api/main.py``) writes the text of an unhandled exception twice, to the log and to the
caller, and an engine's error can quote the statement that held the key. Both are written with every passphrase the process
holds taken out of them, in every shape the code writes one in, and when the scrub itself cannot run the exception's own words
are written nowhere.

``tests/test_p0_validation.py`` reads the ``except`` blocks of the functions that hold a passphrase. The exception here is a
PARAMETER of the handler, not a caught one, so that walk reads nothing of it: the handler is held by behaviour below and by a
read of its source.

The server logs the exception once more itself, as the middleware re-raises it after this handler has answered, and a
passphrase typed into the request being served (the unlock screen's) is not held yet: both are recorded in
``docs/ledger/OPEN_QUEUE.md`` as outside what the handler can do.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest
from starlette.requests import Request

import src.api.main as main
from src.database import connect
from src.monitoring import secret_scrub as ss

HELD = "kQ7!vLm-it's-the-held-key"  # an apostrophe: the statement that carries it quotes it twice
ENV = "zR4#nPt-the-env-key"


@pytest.fixture
def both_held(monkeypatch):
    monkeypatch.setattr(connect, "_passphrase", HELD)
    monkeypatch.setenv("OO_DB_PASSPHRASE", ENV)


def _call(exc: BaseException):
    scope = {"type": "http", "method": "GET", "path": "/api/whatever", "headers": []}
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(main.unhandled_exception_handler(Request(scope), exc))
    finally:
        loop.close()


def _sql(secret: str) -> str:
    return f"PRAGMA key = '{secret.replace(chr(39), chr(39) * 2)}'"


def _shapes(secret: str) -> set[str]:
    """The ways the code writes a secret, listed here and not by the helper under test."""
    doubled = secret.replace("'", "''")
    return {
        secret,
        doubled,
        repr(secret)[1:-1],
        repr(doubled)[1:-1],
        json.dumps(secret)[1:-1],
        json.dumps(secret, ensure_ascii=False)[1:-1],
    }


def test_the_response_and_the_log_have_every_passphrase_out_in_every_shape_and_keep_the_rest(both_held, caplog):
    caplog.set_level(logging.DEBUG, logger="api")
    try:
        raise RuntimeError(f"near {_sql(HELD)}: syntax error ({ENV}) args={(HELD,)!r} {json.dumps({'k': ENV})}")
    except RuntimeError as exc:
        resp = _call(exc)
    assert resp.status_code == 500 and resp.media_type == "application/json"
    expected = (
        "internal error: near PRAGMA key = '***redacted***': syntax error (***redacted***) "
        'args=("***redacted***",) {"k": "***redacted***"}'
    )
    assert json.loads(resp.body) == {"detail": expected}

    records = [r for r in caplog.records if r.name == "api" and r.getMessage().startswith("unhandled error on GET /api/whatever")]
    assert len(records) == 1 and records[0].levelno == logging.ERROR
    record = records[0]
    assert record.getMessage().startswith(
        "unhandled error on GET /api/whatever: RuntimeError: near PRAGMA key = '***redacted***': syntax error"
    )
    assert record.exc_info is None, "a record carrying exc_info prints the exception as it was raised"
    tail = getattr(record, ss.TRACEBACK_ATTRIBUTE)
    assert "Traceback (most recent call last)" in tail and "test_the_response_and_the_log_have_every_passphrase" in tail
    assert "RuntimeError: near PRAGMA key = '***redacted***'" in tail, "the frames AND the failure's own line"
    for text in (resp.body.decode(), caplog.text, record.getMessage(), tail):
        for secret in (HELD, ENV):
            for shape in _shapes(secret):
                assert shape not in text, (shape, text)


def test_an_exception_that_holds_no_passphrase_is_written_as_it_always_was(both_held, caplog):
    caplog.set_level(logging.DEBUG, logger="api")
    resp = _call(ValueError("kaboom"))
    assert json.loads(resp.body) == {"detail": "internal error: kaboom"}
    assert "unhandled error on GET /api/whatever: ValueError: kaboom" in caplog.text


def test_with_no_passphrase_held_nothing_is_taken_out(monkeypatch, caplog):
    monkeypatch.setattr(connect, "_passphrase", None)
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    caplog.set_level(logging.DEBUG, logger="api")
    assert ss.held_passphrases() == ()
    resp = _call(RuntimeError("the key hunter2 was refused"))
    assert json.loads(resp.body) == {"detail": "internal error: the key hunter2 was refused"}


def test_the_passphrases_are_read_when_the_error_happens_and_an_empty_one_is_not_one(monkeypatch):
    monkeypatch.setattr(connect, "_passphrase", "first")
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    assert ss.held_passphrases() == ("first",)
    connect.set_passphrase("second")  # a lock, an unlock or an erase in between: nothing was kept
    try:
        monkeypatch.setenv("OO_DB_PASSPHRASE", "third")
        assert ss.held_passphrases() == ("second", "third")
    finally:
        connect.set_passphrase(None)


def test_the_store_is_looked_up_among_the_imported_modules_and_never_imported_by_a_scrub(monkeypatch):
    """MUTATION TARGET: a handler runs inside whatever failed, an import in progress among it, and an import from there can wait on
    an import lock or fail on one. A store that was never imported holds no session passphrase; the environment's is still read."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", ENV)
    monkeypatch.delitem(sys.modules, "src.database.connect")
    assert ss.held_passphrases() == (ENV,)
    assert "src.database.connect" not in sys.modules


def test_a_store_that_cannot_say_what_it_holds_does_not_stop_the_environments_passphrase_being_read(monkeypatch):
    def half_imported():
        raise RuntimeError("the store is half imported")

    monkeypatch.setenv("OO_DB_PASSPHRASE", ENV)
    monkeypatch.setattr(connect, "get_passphrase", half_imported)
    assert ss.held_passphrases() == (ENV,)
    monkeypatch.delattr(connect, "get_passphrase")  # an attribute that is not there yet is the same case
    assert ss.held_passphrases() == (ENV,)


@pytest.mark.parametrize("broken", ["scrubbed", "log_failure"])
def test_when_the_scrub_cannot_run_the_exceptions_own_words_are_written_nowhere(both_held, caplog, monkeypatch, broken):
    """MUTATION TARGET: the fallback. Whichever step fails, the response says it is withheld and the log names the
    exception's class and nothing it said."""

    def boom(*args, **kwargs):
        raise RuntimeError(f"the scrub broke on {HELD}")

    monkeypatch.setattr(main, broken, boom)
    caplog.set_level(logging.DEBUG, logger="api")
    resp = _call(RuntimeError(f"the key {HELD} was refused"))
    assert resp.status_code == 500
    assert json.loads(resp.body) == {"detail": "internal error (its text is withheld: the scrub could not run)"}
    assert "unhandled error (RuntimeError): its text is withheld, the scrub could not run" in caplog.text
    assert HELD not in resp.body.decode() + caplog.text and "refused" not in resp.body.decode() + caplog.text


def test_an_exception_whose_text_cannot_be_made_is_answered_not_raised_again(both_held):
    class Broken(Exception):
        def __str__(self) -> str:
            raise ValueError("no text")

    resp = _call(Broken())
    assert resp.status_code == 500
    assert json.loads(resp.body) == {"detail": "internal error (its text is withheld: the scrub could not run)"}


def test_the_handler_uses_its_exception_only_inside_a_scrub_that_is_given_every_passphrase_it_holds():
    """MUTATION TARGET: a use of ``exc`` outside the scrubbing calls, a scrubbing call not given ``*held``, a traceback written
    by ``.exception()`` or ``exc_info``. A read of the source, because the static guard in ``test_p0_validation.py`` reads the
    handlers of ``except`` blocks and the exception here is the handler's parameter."""
    tree = ast.parse(Path(main.__file__).read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "unhandled_exception_handler"
    )
    allowed: set[int] = set()
    scrubbing = 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        assert not (isinstance(node.func, ast.Attribute) and node.func.attr == "exception"), f"line {node.lineno}"
        assert not any(kw.arg == "exc_info" for kw in node.keywords), f"line {node.lineno}: exc_info"
        if isinstance(node.func, ast.Name) and node.func.id in {"scrubbed", "log_failure"}:
            given = [
                a for a in node.args if isinstance(a, ast.Starred) and isinstance(a.value, ast.Name) and a.value.id == "held"
            ]
            assert given, f"line {node.lineno}: {node.func.id} is not given *held"
            allowed |= {id(n) for n in ast.walk(node)}
            scrubbing += 1
        elif isinstance(node.func, ast.Name) and node.func.id == "type" and len(node.args) == 1:
            allowed.add(id(node.args[0]))  # its class, for the line that says the scrub could not run
    outside = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "exc" and id(n) not in allowed]
    assert not outside, f"the exception is used outside a scrub on lines {outside}"
    assert scrubbing == 3, "the log line's words, the log record and the response: the walk must not be left looking at nothing"
