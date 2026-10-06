"""The global exception handler (``src/api/main.py``) writes the text of an unhandled exception twice, to the log and to the
caller, and an engine's error can quote the statement that held the key. Both are written with every passphrase the process
holds taken out of them, in every shape the code writes one in, and when the scrub itself cannot run the exception's own words
are written nowhere.

``tests/test_p0_validation.py`` reads the ``except`` blocks of the functions that hold a passphrase. The exception here is a
PARAMETER of the handler, not a caught one, so that walk reads nothing of it: the handler is held by behaviour below and by a
read of its source.

The server logs the exception once more itself, as the middleware re-raises it after this handler has answered, and a
passphrase typed into the request being served (the unlock screen's) is not held yet: both are recorded in
``docs/ledger/OPEN_QUEUE.md`` as outside what the handler can do. The routes that take a typed key convert what escapes them
(``secret_scrub.scrub_and_reraise``), so the exception that reaches this handler from one is already scrubbed.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import sys
import threading
from pathlib import Path

import pytest
from starlette.requests import Request

import src.api.main as main
from src.database import connect
from src.monitoring import secret_scrub as ss

HELD = "kQ7!vLm-it's-the-held-key"  # an apostrophe: the statement that carries it quotes it twice
ENV = "zR4#nPt-the-env-key"
#: What the response says when the scrub could not run, could not read what the process holds, or holds a passphrase it cannot
#: take out of a text (``secret_scrub.MIN_SECRET_CHARS``).
WITHHELD = "internal error (its text is withheld: the scrub could not run, or could not take a passphrase out of it)"


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


def test_the_sessions_passphrase_is_read_without_the_stores_lock_so_a_record_written_under_it_does_not_wait_on_itself(monkeypatch):
    """MUTATION TARGET: the read of the store's global. ``connect.get_passphrase`` takes the store's lock, which is not
    reentrant, and a log record is written by a thread that may hold it (the unlock holds it for the whole of its work): a scrub
    that waited on it would hang the thread that is trying to say why it failed."""
    monkeypatch.setattr(connect, "_passphrase", HELD)
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    answered: list[object] = []
    with connect._lock:
        reader = threading.Thread(target=lambda: answered.append(ss.held_passphrases()), daemon=True)
        reader.start()
        reader.join(5)
        assert not reader.is_alive(), "the read waited on the store's lock"
    assert answered == [(HELD,)]


def test_what_the_process_holds_that_cannot_be_read_is_none_and_never_an_empty_answer(monkeypatch):
    """MUTATION TARGET: ``None`` for a read that failed. An empty tuple would say "nothing is held" and every net would keep
    the text it could not check; ``None`` is what makes each of them withhold it."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", ENV)
    monkeypatch.setattr(connect, "_passphrase", b"not text")  # a store whose global holds something that is no passphrase
    assert ss.held_passphrases() is None
    monkeypatch.setattr(connect, "_passphrase", HELD)
    monkeypatch.setenv("OO_DB_PASSPHRASE", ENV)
    assert ss.held_passphrases() == (HELD, ENV)
    monkeypatch.setattr(ss, "vars", lambda *_a: (_ for _ in ()).throw(TypeError("no namespace")), raising=False)
    assert ss.held_passphrases() is None


def test_a_handler_that_cannot_read_what_the_process_holds_writes_none_of_the_exceptions_words(both_held, caplog, monkeypatch):
    """MUTATION TARGET: the unreadable answer treated as "nothing is held", in the response, in the log line or in the
    log record: each would keep the text on the chance that it holds no passphrase."""
    monkeypatch.setattr(ss, "held_passphrases", lambda: None)
    caplog.set_level(logging.DEBUG, logger="api")
    resp = _call(RuntimeError(f"the key {HELD} was refused"))
    assert resp.status_code == 500
    assert json.loads(resp.body) == {"detail": WITHHELD}
    written = resp.body.decode() + caplog.text
    assert HELD not in written and "refused" not in written
    (record,) = [r for r in caplog.records if r.name == "api"]
    assert "RuntimeError: its text is withheld" in record.getMessage() and record.exc_info is None


def test_a_short_held_passphrase_withholds_the_words_of_the_response_and_the_log_line_that_hold_it(monkeypatch, caplog):
    """A correct passphrase of an older store can be one to three characters, and it cannot be taken out of a text, so a response
    and a log line that hold it are withheld whole (the class stays), and one that holds none of its shapes is written as it was.
    MUTATION TARGET: a handler whose scrub reads only the long shapes of what the process holds."""
    monkeypatch.setattr(connect, "_passphrase", "zq")
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    ss.forget_held()
    caplog.set_level(logging.DEBUG, logger="api")
    resp = _call(RuntimeError("the key zq was refused"))
    assert resp.status_code == 500 and json.loads(resp.body) == {"detail": WITHHELD}
    (record,) = [r for r in caplog.records if r.name == "api"]
    assert record.getMessage().endswith("RuntimeError: its text is withheld\nRuntimeError: its text is withheld")
    assert "refused" not in caplog.text and "zq" not in record.getMessage()
    caplog.clear()
    resp = _call(RuntimeError("the file was refused"))
    assert json.loads(resp.body) == {"detail": "internal error: the file was refused"}
    assert "the file was refused" in caplog.text


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


def test_the_handler_uses_its_exception_only_inside_the_scrubbing_helpers_and_reads_no_passphrase_itself():
    """MUTATION TARGET: a use of ``exc`` outside the scrubbing calls, a traceback written by ``.exception()`` or ``exc_info``, or
    a second reading of what the process holds. ``scrubbed`` and ``log_failure`` take out every passphrase the process holds
    themselves (pinned by behaviour in ``test_secret_scrub.py``), so the handler is handed none and reads none: a handler that
    reads them itself is one more place where "what is held" is decided, and the one that is read differently leaves a text
    unscrubbed. A read of the source, because the static guard in ``test_p0_validation.py`` reads the handlers of ``except``
    blocks and the exception here is the handler's parameter."""
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
            allowed |= {id(n) for n in ast.walk(node)}
            scrubbing += 1
        elif isinstance(node.func, ast.Name) and node.func.id == "type" and len(node.args) == 1:
            allowed.add(id(node.args[0]))  # its class, for the line that says the scrub could not run
    outside = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "exc" and id(n) not in allowed]
    assert not outside, f"the exception is used outside a scrub on lines {outside}"
    assert scrubbing == 3, "the log line's words, the log record and the response: the walk must not be left looking at nothing"
    reads = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "held_passphrases"]
    assert not reads, f"the handler reads what the process holds itself, on lines {reads}"
