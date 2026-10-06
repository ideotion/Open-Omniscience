"""The last check before a handler writes: the passphrases the process holds are taken out of the record (2026-10-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``secret_scrub.log_failure`` and the handlers the static guard reads (``tests/test_p0_validation.py``) take a passphrase out of
what they write where they write it. A record written any other way (a ``logger.exception`` in a module nobody read, a
library's, the server's own ``Exception in ASGI application``) carries the exception as it made its message, and a handler
writes it as it is. ``SecretFilter`` is the net under them: a filter of each handler the app builds, which takes the passphrases
the process holds out of the message, the exception and the stack, and fails closed. It hands the handler a COPY of the record
and leaves the record as it was, because the record is shared by every handler it reaches and the error journal, which counts
what it reads off the words as logged, stands behind no filter of its own and takes the passphrases out itself.

A filter of a HANDLER and not of a logger, because a record that propagates meets the handlers of every logger on the way and the
filters of none; so the second half of this file pins WHERE it is attached (the audit files and the console of
``setup_logging``, the server's own handlers, the console the migration environment builds, and that no module of the app builds
another handler without it), and the third runs the handlers the app configures at boot in one process and writes an exception
that carries the key through every one of them.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import logging
import logging.handlers
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from src.monitoring import errorlog
from src.monitoring import secret_scrub as S

PASS = "Qv9#k'L-72mZpx"
ROOT = Path(__file__).resolve().parents[1]
_SEEN = iter(range(10_000))


@pytest.fixture
def held(monkeypatch):
    """A process that holds ``PASS``: the environment's, as ``OO_DB_PASSPHRASE`` stays in it after a lock."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", PASS)
    monkeypatch.setattr("src.database.connect._passphrase", None)


@pytest.fixture
def nothing_held(monkeypatch):
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", None)


@contextlib.contextmanager
def _logger(*, protect: bool = True):
    """A private logger whose one handler writes what a console would, behind the filter or not: ``(logger, stream)``."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    if protect:
        S.protect_handler(handler)
    log = logging.getLogger(f"oo.test_secret_filter.{next(_SEEN)}")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    log.addHandler(handler)
    try:
        yield log, stream
    finally:
        log.removeHandler(handler)


def _record(msg="m", args=(), exc_info=None, **extra) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, msg, args, exc_info)
    record.__dict__.update(extra)
    return record


def _filtered(record: logging.LogRecord) -> logging.LogRecord:
    """The record a handler behind the filter is handed: a copy when the filter changed anything, the record itself when not."""
    out = S.SecretFilter().filter(record)
    return record if out is True else out


def _raised(message: str) -> tuple:
    try:
        raise RuntimeError(message)
    except RuntimeError:
        return sys.exc_info()


# --------------------------------------------------------------------------- #
#  What the filter does to a record
# --------------------------------------------------------------------------- #
def test_a_message_that_holds_the_passphrase_is_written_without_it(held):
    """MUTATION TARGET: the message left as it was."""
    with _logger() as (log, stream):
        log.error("the store refused the key %s", PASS)
        log.error("a %(what)s was refused: %(key)r", {"what": "key", "key": PASS})
        log.error("nothing to hide here")
    out = stream.getvalue()
    assert PASS not in out and repr(PASS) not in out
    assert out.splitlines() == [
        f"ERROR the store refused the key {S.REDACTED}",
        f'ERROR a key was refused: "{S.REDACTED}"',
        "ERROR nothing to hide here",
    ]


def test_an_exception_written_as_an_argument_is_taken_out_as_the_text_it_makes(held):
    with _logger() as (log, stream):
        log.warning("failed: %s", RuntimeError(f"near '{PASS.replace(chr(39), chr(39) * 2)}': syntax error"))
    assert PASS not in stream.getvalue() and PASS.replace("'", "''") not in stream.getvalue()
    assert f"WARNING failed: near '{S.REDACTED}': syntax error" in stream.getvalue()


def test_an_exception_logged_with_its_traceback_is_written_without_the_passphrase(held):
    """MUTATION TARGET: the exception text left to the formatter. ``logger.exception`` writes the exception as it made its message,
    its chain included."""
    with _logger() as (log, stream):
        try:
            try:
                raise ValueError(f"the cause names {PASS}")
            except ValueError as cause:
                raise RuntimeError(f"the store refused {PASS}") from cause
        except RuntimeError:
            log.exception("failed")
    out = stream.getvalue()
    assert PASS not in out
    assert out.startswith("ERROR failed\nTraceback (most recent call last):")
    assert f"RuntimeError: the store refused {S.REDACTED}" in out and f"ValueError: the cause names {S.REDACTED}" in out
    assert "The above exception was the direct cause" in out, "the chain is kept, with the secret out of it"


def test_an_exception_text_an_earlier_handler_cached_is_scrubbed_before_this_one_writes_it(held):
    """A formatter caches an exception's text on the record, and the next handler is handed that text: the filter reads the
    cache too. (The first handler here is not behind a filter and writes what it is given: only the handlers that carry one are
    covered.)"""
    first, second = io.StringIO(), io.StringIO()
    handlers = [logging.StreamHandler(first), S.protect_handler(logging.StreamHandler(second))]
    for h in handlers:
        h.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger(f"oo.test_secret_filter.{next(_SEEN)}")
    log.propagate = False
    for h in handlers:
        log.addHandler(h)
    try:
        try:
            raise RuntimeError(f"the store refused {PASS}")
        except RuntimeError:
            log.exception("failed")
    finally:
        for h in handlers:
            log.removeHandler(h)
    assert PASS in first.getvalue(), "the control: a handler without the filter writes the exception as it made its message"
    assert PASS not in second.getvalue() and f"RuntimeError: the store refused {S.REDACTED}" in second.getvalue()


def test_the_stack_of_a_record_is_taken_out_too(held):
    record = _record()
    record.stack_info = f"Stack (most recent call last):\n  login({PASS})"
    out = _filtered(record)
    assert PASS not in out.stack_info and S.REDACTED in out.stack_info
    assert PASS in record.stack_info, "the record the other handlers read is left as it was"


def test_a_record_is_passed_as_it_is_while_no_passphrase_is_held(nothing_held):
    """A plaintext install holds none: the filter reads two variables and passes the record on as it is, arguments and all."""
    args = ("a", 1)
    record = _record("x %s %d", args)
    assert S.SecretFilter().filter(record) is True
    assert record.msg == "x %s %d" and record.args is args and record.exc_text is None


def test_a_record_that_holds_none_is_passed_as_it_is_with_its_arguments(held):
    """The server's access line unpacks five arguments from the record; a filter that formatted every message into one text and
    cleared the arguments would have broken it for every request."""
    from uvicorn.logging import AccessFormatter

    args = ("127.0.0.1:50000", "GET", "/api/health", "1.1", 200)
    record = _record('%s - "%s %s HTTP/%s" %d', args)
    assert S.SecretFilter().filter(record) is True
    assert record.args is args
    formatter = AccessFormatter(fmt='%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)
    assert formatter.format(record) == '127.0.0.1:50000 - "GET /api/health HTTP/1.1" 200 OK'


def test_a_record_that_holds_it_keeps_its_arguments_where_a_formatter_reads_them(held):
    """MUTATION TARGET: the arguments cleared whenever the passphrase is found. The access line of a request whose path carries the
    key must still be written, as the formatter that unpacks its five arguments writes it, with the key out of it."""
    from uvicorn.logging import AccessFormatter

    args = ("127.0.0.1:50000", "GET", f"/api/search?q={PASS}", "1.1", 200)
    record = _record('%s - "%s %s HTTP/%s" %d', args)
    out = _filtered(record)
    assert out is not record and len(out.args) == 5 and out.args[2] == f"/api/search?q={S.REDACTED}"
    formatter = AccessFormatter(fmt='%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)
    assert formatter.format(out) == f'127.0.0.1:50000 - "GET /api/search?q={S.REDACTED} HTTP/1.1" 200 OK'
    assert record.args is args, "and the record the other handlers read is the one that was logged"


def test_a_record_whose_arguments_cannot_be_kept_is_written_as_one_text(held):
    """An argument that is no text but writes one (an exception), and a passphrase that a template and an argument write between
    them: neither is in any one of the pieces, so the pieces cannot be scrubbed one by one."""
    out = _filtered(_record("failed: %s", (RuntimeError(f"near {PASS}"),)))
    assert out.args == () and out.msg == f"failed: near {S.REDACTED}"
    half = PASS[:8]
    out = _filtered(_record(f"the key {half}%s was refused", (PASS[8:],)))
    assert PASS not in out.getMessage() and out.args == () and out.getMessage() == f"the key {S.REDACTED} was refused"


def test_the_record_itself_is_left_as_it_was_for_the_handlers_after_this_one(held):
    """MUTATION TARGET: the record scrubbed in place. It is shared by every handler it reaches, and the error journal's counts
    are read off the words as logged."""
    exc_info = _raised(f"the store refused {PASS}")
    record = _record("key %s", (PASS,), exc_info, stack_info=f"login({PASS})")
    before = dict(record.__dict__)
    out = S.SecretFilter().filter(record)
    assert isinstance(out, logging.LogRecord) and out is not record
    assert record.__dict__ == before, "nothing of the record the other handlers read was written to"
    assert out.exc_info is None and PASS not in out.exc_text and PASS not in out.getMessage() and PASS not in out.stack_info
    assert record.exc_info is exc_info and PASS in record.getMessage()


def test_a_record_that_cannot_be_checked_is_written_as_a_fixed_line_with_no_exception(held, monkeypatch):
    """MUTATION TARGET: the failure left to propagate (a record that logging could not write) or the words kept."""
    with _logger() as (log, stream):
        monkeypatch.setattr(S, "_scrubbed_copy", broken)
        try:
            raise RuntimeError(f"the store refused {PASS}")
        except RuntimeError:
            log.exception("failed with %s", PASS)
    assert stream.getvalue() == f"ERROR {S.WITHHELD_RECORD}\n"


def broken(*args, **kwargs):
    raise RuntimeError("the scrub broke")


def test_a_record_is_withheld_when_what_the_process_holds_cannot_be_read(monkeypatch):
    """MUTATION TARGET: ``None`` read as "nothing is held", which writes every record as it is. What is held is read off the
    store and the environment, and when that fails a record is not kept on the chance that it holds nothing."""
    with _logger() as (log, stream):
        monkeypatch.setattr(S, "held_passphrases", lambda: None)
        try:
            raise RuntimeError("some words")
        except RuntimeError:
            log.exception("a line that holds no secret at all")
    assert stream.getvalue() == f"ERROR {S.WITHHELD_RECORD}\n"


def test_a_record_that_cannot_even_be_copied_is_not_written(held, monkeypatch):
    with _logger() as (log, stream):
        monkeypatch.setattr(S, "_scrubbed_copy", broken)
        monkeypatch.setattr(S, "copy", types.SimpleNamespace(copy=broken))
        log.error("failed with %s", PASS)
    assert stream.getvalue() == ""


def test_a_record_whose_message_cannot_be_formatted_is_withheld_too(held):
    with _logger() as (log, stream):
        log.error("%d keys were refused", "the held one")
    assert stream.getvalue() == f"ERROR {S.WITHHELD_RECORD}\n"


def test_below_python_3_12_the_filter_writes_the_scrubbed_words_into_the_record_it_was_given(held, monkeypatch):
    """MUTATION TARGET: the copy handed back on an interpreter where a filter's answer is only a truthy "write this one": the
    handler then writes the ORIGINAL, passphrase and all. (The suite runs on 3.13, so the seam is the constant the filter reads.)"""
    monkeypatch.setattr(S, "_FILTER_MAY_REPLACE", False)
    record = _record("the key is " + PASS)
    assert S.SecretFilter().filter(record) is True
    assert record.getMessage() == f"the key is {S.REDACTED}"
    record = _record("failed", exc_info=_raised(f"the store refused {PASS}"))
    assert S.SecretFilter().filter(record) is True
    assert record.exc_info is None and PASS not in (record.exc_text or "") and S.REDACTED in record.exc_text
    untouched = _record("nothing to take out of %s", ("x",))
    assert S.SecretFilter().filter(untouched) is True and untouched.getMessage() == "nothing to take out of x"
    with _logger() as (log, stream):
        log.error("the key %s again", PASS)
    assert stream.getvalue() == f"ERROR the key {S.REDACTED} again\n"


def test_below_python_3_12_a_record_that_cannot_be_checked_is_withheld_in_the_record_itself(monkeypatch):
    monkeypatch.setattr(S, "_FILTER_MAY_REPLACE", False)
    monkeypatch.setattr(S, "held_passphrases", lambda: None)
    record = _record("the key is " + PASS, exc_info=_raised("refused " + PASS))
    assert S.SecretFilter().filter(record) is True
    assert record.getMessage() == S.WITHHELD_RECORD and record.exc_info is None and record.exc_text is None

    class Frozen:  # a record with no ``__dict__`` cannot take the words, and is not written
        __slots__ = ("msg",)

    monkeypatch.setattr(S.SecretFilter, "_answer", staticmethod(lambda r: _record("x")))
    assert S.SecretFilter().filter(Frozen()) is False


def _floor_of_the_project() -> dict[str, tuple[int, int]]:
    """Every place the tree names the interpreter it runs on, as ``(major, minor)``: the package's ``requires-python``, the
    version file, every CI and release job, the offline bundle's build, and the two installers' checks."""
    found: dict[str, tuple[int, int]] = {}

    def add(where: str, text: str, pattern: str) -> None:
        for n, m in enumerate(re.finditer(pattern, text)):
            found[f"{where}#{n}"] = (int(m.group(1)), int(m.group(2)))

    add("pyproject.toml", (ROOT / "pyproject.toml").read_text(encoding="utf-8"), r'requires-python\s*=\s*">=\s*(\d+)\.(\d+)')
    add(".python-version", (ROOT / ".python-version").read_text(encoding="utf-8"), r"^\s*(\d+)\.(\d+)")
    add("install.ps1", (ROOT / "install.ps1").read_text(encoding="utf-8"), r"MinPython\s*=\s*\[version\]'(\d+)\.(\d+)'")
    add("install-offline.sh", (ROOT / "install-offline.sh").read_text(encoding="utf-8"), r"sys\.version_info\[:2\] >= \((\d+), (\d+)\)")
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        add(path.name + " python-version", text, r"python-version:\s*[\"']?(\d+)\.(\d+)")
        add(path.name + " python3.N", text, r"python(3)\.(\d+)")
    add("scripts/build_offline_bundle.sh", (ROOT / "scripts" / "build_offline_bundle.sh").read_text(encoding="utf-8"), r"python(3)\.(\d+)")
    return found


def test_the_interpreter_floor_of_the_project_is_the_one_that_lets_a_filter_hand_on_a_copy():
    """A filter's returned record replaces the one it was given from Python 3.12 (``_FILTER_MAY_REPLACE``). The package, the version
    file, the installers and every CI, release and packaging job say 3.13; if one of them is lowered under 3.12 the filter's copy
    is no longer what the handler writes, and the seam above is the only thing left holding the passphrase out. A walk that finds
    nothing passes for the wrong reason, so it must see the places it names."""
    found = _floor_of_the_project()
    wanted = {"pyproject.toml#0", ".python-version#0", "install.ps1#0", "install-offline.sh#0"}
    assert wanted <= set(found), f"the walk no longer reads {sorted(wanted - set(found))}"
    assert sum(1 for where in found if " python-version#" in where) >= 8, found
    below = {where: version for where, version in found.items() if version < (3, 12)}
    assert not below, f"an interpreter below 3.12 is named where the filter's copy would not be written: {below}"
    assert S._FILTER_MAY_REPLACE is (sys.version_info >= (3, 12)) and sys.version_info >= (3, 12)


SHORT = "xK7"  # three characters: under ``MIN_SECRET_CHARS``, so no text can have it taken out


@pytest.fixture
def short_held(monkeypatch):
    """A process that holds a passphrase too short to take out of a text (an older store's, which the unlock accepts and holds)."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", SHORT)
    monkeypatch.setattr("src.database.connect._passphrase", None)


def test_a_record_that_holds_a_secret_under_the_floor_is_withheld_whole_and_one_that_does_not_is_written_as_it_was(short_held):
    """MUTATION TARGET: the floor's withholding left out of the filter's check, which wrote such a record as it was. One to three
    characters cannot be taken out of a text without taking the text out, so the record that holds them is not written; the one
    that does not is, because a secret under the floor taken out of every record would leave none that says anything."""
    with _logger() as (log, stream):
        log.error("the store refused the key %s", SHORT)
        log.error("a key was refused: %r", SHORT)
        log.error("nothing to hide here")
    assert stream.getvalue().splitlines() == [
        f"ERROR {S.WITHHELD_RECORD}",
        f"ERROR {S.WITHHELD_RECORD}",
        "ERROR nothing to hide here",
    ]


def test_an_exception_that_names_a_secret_under_the_floor_is_written_as_its_class_and_none_of_its_words(short_held):
    """The message of the record says nothing of it and is kept; the traceback, whose text holds the secret, is the exception's
    class and the words that say its text is withheld (``traceback_text``'s own), never the words of the exception."""
    with _logger() as (log, stream):
        try:
            raise RuntimeError(f"the store refused {SHORT}")
        except RuntimeError:
            log.exception("failed")
    out = stream.getvalue()
    assert SHORT not in out and "Traceback" not in out and "refused" not in out
    assert out.splitlines() == ["ERROR failed", "RuntimeError: its text is withheld"]


def test_a_frame_whose_source_line_holds_a_secret_under_the_floor_withholds_the_traceback_and_keeps_the_message(short_held):
    """The message says nothing of the secret and the exception does not either, but a traceback prints each frame's source line,
    and this one holds it: the traceback as a whole is the exception's class and the words that say its text is withheld, and
    the message stays."""
    with _logger() as (log, stream):
        try:
            raise RuntimeError("the store was refused")  # the line of the frame, which a traceback prints: xK7
        except RuntimeError:
            log.exception("failed")
    out = stream.getvalue()
    assert SHORT not in out and "Traceback" not in out and "refused" not in out
    assert out.splitlines() == ["ERROR failed", "RuntimeError: its text is withheld"]


def test_a_secret_under_the_floor_and_one_over_it_are_both_handled_by_the_record_that_holds_either(monkeypatch):
    """Two passphrases held at once (the session's and the environment's): the long one is taken out of the text and the short one
    withholds it."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", PASS)
    monkeypatch.setattr("src.database.connect._passphrase", SHORT)
    with _logger() as (log, stream):
        log.error("the key %s", PASS)
        log.error("the key %s", SHORT)
        log.error("neither")
    assert stream.getvalue().splitlines() == [f"ERROR the key {S.REDACTED}", f"ERROR {S.WITHHELD_RECORD}", "ERROR neither"]


# --------------------------------------------------------------------------- #
#  The error journal stands beside it, not behind it
# --------------------------------------------------------------------------- #
def test_the_journals_handler_says_by_the_name_the_filter_reads_that_it_scrubs_its_own_records():
    """MUTATION TARGET: the two spellings of the attribute drifting apart, which puts the journal behind a filter again."""
    assert S.SCRUBS_ITS_OWN_RECORDS == "scrubs_its_own_records"
    assert getattr(errorlog._JsonlErrorHandler, S.SCRUBS_ITS_OWN_RECORDS) is True


def test_a_handler_whose_class_scrubs_its_own_records_gets_no_filter():
    handler = errorlog._JsonlErrorHandler(level=logging.WARNING)
    assert S.protect_handler(handler) is handler and handler.filters == []
    assert S.protect_handlers() >= 0 and handler.filters == []


def test_a_passphrase_that_is_a_piece_of_a_counted_phrase_still_counts_beside_a_filtered_handler(monkeypatch, tmp_path):
    """MUTATION TARGET: the journal's handler behind a filter, or the filter scrubbing the record it shares. The summary counts
    ``database is locked`` off the words as logged; a passphrase that is a piece of that phrase would take it out first and the
    count would read zero on the one machine whose lock error is being chased. The filtered handler is added FIRST, the order in
    which a filter that wrote to the shared record would reach the journal after it."""
    monkeypatch.setattr(errorlog, "_log_path", lambda: tmp_path / "app_errors.jsonl")
    monkeypatch.setenv("OO_DB_PASSPHRASE", "is locked")
    monkeypatch.setattr("src.database.connect._passphrase", None)
    stream = io.StringIO()
    shown = S.protect_handler(logging.StreamHandler(stream))
    journal = S.protect_handler(errorlog._JsonlErrorHandler(level=logging.WARNING))
    log = logging.getLogger(f"oo.test_secret_filter.{next(_SEEN)}")
    log.propagate = False
    log.addHandler(shown)
    log.addHandler(journal)
    try:
        log.error("sqlite3.OperationalError: database is locked")
    finally:
        log.removeHandler(shown)
        log.removeHandler(journal)
    assert "is locked" not in stream.getvalue() and S.REDACTED in stream.getvalue()
    (entry,) = errorlog.recent_errors()
    assert entry.get("locked") is True, "the count is read off the words as logged"
    assert "is locked" not in json.dumps(entry) and S.REDACTED in entry["message"], "and the entry itself is scrubbed"


# --------------------------------------------------------------------------- #
#  Where it is attached
# --------------------------------------------------------------------------- #
def test_a_handler_is_protected_once():
    handler = logging.StreamHandler(io.StringIO())
    assert S.protect_handler(S.protect_handler(handler)) is handler
    assert [type(f) for f in handler.filters] == [S.SecretFilter]


@pytest.fixture
def construction_hook():
    """The real hook for one test (the suite stubs the public ``protect_new_handlers``), and the process left as it was found."""
    original = logging.Handler.__init__
    assert S._HANDLER_INIT is None and original.__name__ == "__init__"
    yield
    S._unhook_handler_construction()
    assert logging.Handler.__init__ is original and S._HANDLER_INIT is None


def test_a_handler_built_after_the_hook_has_the_filter_and_one_built_before_it_does_not(construction_hook, tmp_path):
    """MUTATION TARGET: the hook that never replaces the constructor, one that filters before the handler has a filter list, or
    a second install that wraps the wrapper."""
    before = logging.StreamHandler(io.StringIO())
    assert S._hook_handler_construction() is True and S._hook_handler_construction() is False
    after = logging.StreamHandler(io.StringIO())
    assert [type(f) for f in after.filters] == [S.SecretFilter] and before.filters == []

    class Derived(logging.Handler):
        def __init__(self):
            super().__init__(logging.ERROR)

    class Explicit(logging.Handler):
        def __init__(self):
            logging.Handler.__init__(self)

    class Journal(logging.Handler):
        scrubs_its_own_records = True

    assert [type(f) for f in Derived().filters] == [S.SecretFilter] and Derived().level == logging.ERROR
    assert [type(f) for f in Explicit().filters] == [S.SecretFilter]
    assert Journal().filters == [], "a class that scrubs its own records stays without"
    rotating = logging.handlers.RotatingFileHandler(tmp_path / "probe.log", delay=True)
    assert [type(f) for f in rotating.filters] == [S.SecretFilter]
    assert S._unhook_handler_construction() is True and S._unhook_handler_construction() is False
    assert logging.StreamHandler(io.StringIO()).filters == [], "taken out, a handler is built as it was"


def test_a_handler_a_library_adds_after_startup_writes_the_record_without_the_passphrase(held, construction_hook):
    """The handler is built by code that never heard of the filter, and is added to the root logger after boot's one pass."""
    assert S._hook_handler_construction() is True
    stream = io.StringIO()
    late = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(late)
    try:
        try:
            raise RuntimeError(f"the store refused {PASS}")
        except RuntimeError:
            logging.getLogger("some.library").error("failed with %s", PASS, exc_info=True)
    finally:
        root.removeHandler(late)
    assert PASS not in stream.getvalue() and S.REDACTED in stream.getvalue() and "RuntimeError: the store refused" in stream.getvalue()


def test_protecting_the_handlers_that_exist_also_protects_the_ones_built_later(monkeypatch):
    """MUTATION TARGET: ``protect_handlers`` without the call; it is what ``errorlog.install`` and the migration environment
    reach, and neither would put the hook in place otherwise."""
    calls: list[int] = []
    monkeypatch.setattr(S, "protect_new_handlers", lambda: calls.append(1))
    S.protect_handlers()
    assert calls == [1]


def test_every_handler_that_exists_is_protected_and_a_second_call_finds_nothing_new():
    """The migration environment's ``fileConfig`` builds one on the root logger, and a library's ``basicConfig`` another."""
    log = logging.getLogger(f"oo.test_secret_filter.{next(_SEEN)}")
    log.propagate = False
    handler = logging.StreamHandler(io.StringIO())
    log.addHandler(handler)
    try:
        assert S.protect_handlers() >= 1
        assert any(isinstance(f, S.SecretFilter) for f in handler.filters)
        if logging.lastResort is not None:
            assert any(isinstance(f, S.SecretFilter) for f in logging.lastResort.filters)
        assert S.protect_handlers() == 0
    finally:
        log.removeHandler(handler)


def test_installing_the_error_log_at_boot_protects_the_handlers_that_exist_then_and_not_its_own(monkeypatch, tmp_path):
    """MUTATION TARGET: the call left out of ``install``. A library's ``basicConfig`` console exists by then, and nothing else
    would put a filter in front of it. The journal's own handler is the one that stays without."""
    monkeypatch.setattr(errorlog, "_log_path", lambda: tmp_path / "app_errors.jsonl")
    monkeypatch.setattr(errorlog, "_installed", False)
    root = logging.getLogger()
    before = list(root.handlers)
    log = logging.getLogger(f"oo.test_secret_filter.{next(_SEEN)}")
    log.propagate = False
    handler = logging.StreamHandler(io.StringIO())
    log.addHandler(handler)
    console = logging.StreamHandler(io.StringIO())  # what a library's basicConfig leaves on the root logger
    root.addHandler(console)
    try:
        errorlog.install()
        assert any(isinstance(f, S.SecretFilter) for f in handler.filters)
        assert any(isinstance(f, S.SecretFilter) for f in console.filters), "the root's console exists by then and is protected"
        journals = [h for h in root.handlers if isinstance(h, errorlog._JsonlErrorHandler)]
        assert journals and all(h.filters == [] for h in journals), "the journal scrubs its own records"
        # pytest's own handlers (``tests/conftest.py`` marks them, for the reason it gives there) are the others without one.
        assert all(
            any(isinstance(f, S.SecretFilter) for f in h.filters)
            for h in root.handlers
            if h not in journals and not getattr(h, S.SCRUBS_ITS_OWN_RECORDS, False)
        )
    finally:
        log.removeHandler(handler)
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)


def test_the_audit_files_and_the_console_of_setup_logging_are_behind_the_filter(held, monkeypatch, tmp_path, capsys):
    """MUTATION TARGET: a handler of ``setup_logging`` added without the filter. The audit file keeps what it is written."""
    from src.utils import logging_config

    monkeypatch.setattr(logging_config, "AUDIT_DIR", tmp_path)
    log = logging_config.setup_logging(f"oo_test_audit_{next(_SEEN)}", "audit.log", level=logging.DEBUG)
    try:
        assert all(any(isinstance(f, S.SecretFilter) for f in h.filters) for h in log.handlers) and len(log.handlers) == 2
        try:
            raise RuntimeError(f"the store refused {PASS}")
        except RuntimeError:
            log.exception("failed")
        for h in log.handlers:
            h.flush()
    finally:
        for h in list(log.handlers):
            log.removeHandler(h)
            h.close()
    written = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert PASS not in written and f"RuntimeError: the store refused {S.REDACTED}" in written
    shown = capsys.readouterr()
    assert PASS not in shown.out + shown.err and f"RuntimeError: the store refused {S.REDACTED}" in shown.err + shown.out


def test_the_servers_log_configuration_has_the_filter_behind_each_of_its_handlers_and_leaves_the_servers_own_alone():
    from uvicorn.config import LOGGING_CONFIG

    from src.utils.logging_config import uvicorn_log_config

    config = uvicorn_log_config()
    assert config["filters"] == {"oo_passphrase": {"()": "src.monitoring.secret_scrub.SecretFilter"}}
    assert set(config["handlers"]) >= {"default", "access"}
    assert all(h["filters"] == ["oo_passphrase"] for h in config["handlers"].values())
    assert "filters" not in LOGGING_CONFIG and all("filters" not in h for h in LOGGING_CONFIG["handlers"].values())
    assert config["loggers"] == LOGGING_CONFIG["loggers"] and config["formatters"]["default"] == LOGGING_CONFIG["formatters"]["default"]
    assert config["formatters"]["access"] == {**LOGGING_CONFIG["formatters"]["access"], "()": "src.utils.access_log.AccessFormatter"}, (
        "the access formatter is ours and nothing else about it differs from the server's"
    )


def _access_handler(stream):
    """The server's access handler as ``uvicorn_log_config`` builds it (its formatter class resolved from the dotted name the
    configuration gives, as ``dictConfig`` does) writing to ``stream``, behind the filter."""
    import importlib

    from src.utils.logging_config import uvicorn_log_config

    spec = uvicorn_log_config()["formatters"]["access"]
    module, _, name = spec["()"].rpartition(".")
    formatter = getattr(importlib.import_module(module), name)(fmt=spec["fmt"], use_colors=False)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    handler.addFilter(S.SecretFilter())
    return handler


@pytest.mark.parametrize(
    ("held_secret", "path", "written"),
    [
        ("abc", "/api/search?q=abc", S.WITHHELD_RECORD),  # under the floor: the line is withheld whole
        ("GET /api/x", "/api/x/1", f'"{S.REDACTED}/1 HTTP/1.1"'),  # written between the template and an argument: one text
    ],
)
def test_the_access_handler_writes_a_line_for_a_record_the_filter_withheld_or_rewrote_as_one_text(
    monkeypatch, capsys, held_secret, path, written
):
    """MUTATION TARGETS: the formatter's own class named in the configuration, and its fallback. The server's formatter unpacks
    five arguments from every record, so a record the filter handed on with none raised ``ValueError`` for every such request:
    the logging module printed ``--- Logging error ---`` with a call stack and no access line was written (the read of the
    core-limit head, 2026-10-06)."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", held_secret)
    monkeypatch.setattr("src.database.connect._passphrase", None)
    stream = io.StringIO()
    log = logging.getLogger(f"oo.test_secret_filter.access.{next(_SEEN)}")
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(_access_handler(stream))
    log.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5555", "GET", path, "1.1", 200)
    assert capsys.readouterr().err == "", "the logging module reported an error: the line was not written"
    line = stream.getvalue()
    assert line.startswith("INFO:") and written in line and line.endswith("\n"), line
    assert held_secret not in line.replace(S.WITHHELD_RECORD, ""), "the passphrase is not in the line"


def test_the_access_handler_writes_an_ordinary_line_exactly_as_the_server_does(nothing_held, capsys):
    from uvicorn.logging import AccessFormatter

    stream = io.StringIO()
    log = logging.getLogger(f"oo.test_secret_filter.access.{next(_SEEN)}")
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(_access_handler(stream))
    args = ("127.0.0.1:5555", "GET", "/api/search?q=%20x%25", "1.1", 404)
    log.info('%s - "%s %s HTTP/%s" %d', *args)
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', args, None)
    theirs = AccessFormatter(fmt=_access_handler(io.StringIO()).formatter._fmt, use_colors=False).format(record)  # type: ignore[union-attr]
    assert stream.getvalue() == theirs + "\n" == 'INFO:     127.0.0.1:5555 - "GET /api/search?q=%20x%25 HTTP/1.1" 404 Not Found\n'
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("template", "args", "written"),
    [
        ("%s", ("one",), "one"),
        ("%s %s %s %s", ("a", "b", "c", "d"), "a b c d"),
        ("%s %s %s %s %s %s", ("a", "b", "c", "d", "e", "f"), "a b c d e f"),
        ("%(name)s", ({"name": "mapping"},), "mapping"),
        ("100% sure", (), "100% sure"),
    ],
)
def test_the_access_handler_writes_a_record_that_is_not_the_five_part_one_as_its_text(nothing_held, capsys, template, args, written):
    """MUTATION TARGET: the count of arguments the formatter tests. The server's formatter unpacks exactly five, so a record with
    any other number (or a mapping, or none) is the text it makes, behind the same level prefix, and is never an error."""
    stream = io.StringIO()
    log = logging.getLogger(f"oo.test_secret_filter.access.{next(_SEEN)}")
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(_access_handler(stream))
    log.info(template, *args)
    assert capsys.readouterr().err == ""
    assert stream.getvalue() == f"INFO:     {written}\n"


def test_the_server_is_started_with_that_configuration():
    """MUTATION TARGET: ``log_config=`` left out of ``uvicorn.run``, which gives the server its own unfiltered handlers."""
    tree = ast.parse((ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8"))
    serve = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_serve")
    runs = [
        n
        for n in ast.walk(serve)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run" and ast.unparse(n.func.value) == "uvicorn"
    ]
    assert len(runs) == 1
    given = {kw.arg: ast.unparse(kw.value) for kw in runs[0].keywords}
    assert given.get("log_config") == "uvicorn_log_config()", given


def _child(code: str, tmp_path, *, env: dict | None = None) -> str:
    """What a process that holds ``PASS`` writes to its console, both streams: a child, because the configuration it is given
    replaces the handlers of the logger tree."""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={
            "PYTHONPATH": str(ROOT),
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "OO_DB_PASSPHRASE": PASS,
            "PYTHONDONTWRITEBYTECODE": "1",
            **(env or {}),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout + proc.stderr


_SERVER_LOGS = """
import logging, logging.config, os, sys
{setup}
log = logging.getLogger("uvicorn.error")
try:
    raise RuntimeError("the store refused " + os.environ["OO_DB_PASSPHRASE"])
except RuntimeError:
    log.error("Exception in ASGI application", exc_info=True)
log.info("the key %s again", os.environ["OO_DB_PASSPHRASE"])
logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/api/health", "1.1", 200)
"""


def test_the_server_writes_the_exception_that_escaped_the_application_without_the_passphrase(tmp_path):
    """The control first: the server's own configuration writes the passphrase, so the test measures something."""
    bare = _child(_SERVER_LOGS.format(setup="from uvicorn.config import LOGGING_CONFIG\nlogging.config.dictConfig(LOGGING_CONFIG)"), tmp_path)
    assert PASS in bare, "the control: without the filter the server writes the exception as it made its message"
    filtered = _child(
        _SERVER_LOGS.format(setup="from src.utils.logging_config import uvicorn_log_config\nlogging.config.dictConfig(uvicorn_log_config())"),
        tmp_path,
    )
    assert PASS not in filtered
    assert f"RuntimeError: the store refused {S.REDACTED}" in filtered and f"the key {S.REDACTED} again" in filtered
    assert '127.0.0.1:1 - "GET /api/health HTTP/1.1" 200 OK' in filtered, "the access line is written as it was"


#: What a server writes in the window BEFORE the error journal installs (``init_db`` and the seeding run while the process
#: holds the key from the environment, and a module logger outside ``api`` and ``uvicorn`` has no handler of its own: the root
#: logger has none either, so the record goes to ``logging.lastResort``, which writes every WARNING to ``stderr`` as it is).
_PRE_WINDOW = """
import logging, logging.config, os
from pathlib import Path
from src.utils import logging_config
{guard}
logging_config.AUDIT_DIR = Path(os.environ["OO_TEST_DIR"])
logging_config.setup_logging("api", "api.log")
logging.config.dictConfig(logging_config.uvicorn_log_config())
key = os.environ["OO_DB_PASSPHRASE"]
try:
    raise RuntimeError("near PRAGMA key = " + chr(39) + key + chr(39) + ": syntax error")
except RuntimeError:
    logging.getLogger("database.session").warning("could not open the store", exc_info=True)
logging.getLogger("database.session").warning("the key was %s", key)
"""


def test_a_module_loggers_warning_before_the_error_journal_installs_is_written_without_the_passphrase_once_the_process_is_guarded(tmp_path):
    """MUTATION TARGET: the log half of ``guard_process``. The control writes the key (the last-resort handler has no filter),
    so the run measures something; ``_serve`` and the lifespan call ``guard_process`` first (``tests/test_core_guard.py`` pins
    that), and the store module calls it where a process comes to hold a key."""
    bare = _child(_PRE_WINDOW.format(guard=""), tmp_path, env={"OO_TEST_DIR": str(tmp_path)})
    assert PASS in bare, "the control: with nothing guarding the process the last-resort handler writes the exception as it was"
    guarded = _child(
        _PRE_WINDOW.format(guard="from src.monitoring.secret_scrub import guard_process\nguard_process()"), tmp_path, env={"OO_TEST_DIR": str(tmp_path)}
    )
    assert PASS not in guarded and not any(shape in guarded for shape in S._forms(PASS))
    assert f"RuntimeError: near PRAGMA key = '{S.REDACTED}': syntax error" in guarded and f"the key was {S.REDACTED}" in guarded


def test_a_process_that_holds_the_key_from_the_environment_guards_its_log_handlers_when_the_store_module_is_imported(tmp_path):
    """MUTATION TARGET: ``connect``'s import-time guard. Nothing but the import of the store module runs before the record."""
    out = _child(
        "import logging, os\nfrom src.database import connect\nkey = os.environ['OO_DB_PASSPHRASE']\n"
        "logging.getLogger('database.session').warning('the store refused %s', key)\n",
        tmp_path,
    )
    assert PASS not in out and f"the store refused {S.REDACTED}" in out


_MIGRATION_CONSOLE = """
import logging, logging.config, os
logging.config.fileConfig("alembic.ini", disable_existing_loggers=False)
{protect}
try:
    raise RuntimeError("the store refused " + os.environ["OO_DB_PASSPHRASE"])
except RuntimeError:
    logging.getLogger("src.some.module").exception("failed")
"""


def test_the_console_the_migration_environment_builds_is_behind_the_filter_once_it_calls_protect_handlers(tmp_path):
    """``fileConfig`` replaces the root logger's handlers with a console that writes every WARNING and above as it is."""
    bare = _child(_MIGRATION_CONSOLE.format(protect=""), tmp_path)
    assert PASS in bare, "the control: the console fileConfig builds writes the exception as it made its message"
    protected = _child(_MIGRATION_CONSOLE.format(protect="from src.monitoring.secret_scrub import protect_handlers\nprotect_handlers()"), tmp_path)
    assert PASS not in protected and f"RuntimeError: the store refused {S.REDACTED}" in protected


def test_the_migration_environment_protects_the_handlers_the_moment_fileConfig_has_built_them():
    """MUTATION TARGET: the call dropped or moved above ``fileConfig``, which replaces the handlers it protected."""
    tree = ast.parse((ROOT / "migrations" / "env.py").read_text(encoding="utf-8"))
    blocks = [
        n.body
        for n in ast.walk(tree)
        if isinstance(n, ast.If) and any(isinstance(s, ast.Expr) and ast.unparse(s.value).startswith("fileConfig(") for s in n.body)
    ]
    assert len(blocks) == 1
    names = [ast.unparse(s.value).split("(")[0] for s in blocks[0] if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)]
    assert names.index("protect_handlers") == names.index("fileConfig") + 1, names


#: What builds a handler that writes a record somewhere, or the configuration that builds them.
_BUILDERS = frozenset(
    {
        "StreamHandler", "FileHandler", "RotatingFileHandler", "TimedRotatingFileHandler", "WatchedFileHandler", "SysLogHandler",
        "SocketHandler", "DatagramHandler", "SMTPHandler", "HTTPHandler", "NTEventLogHandler", "QueueHandler",
        "fileConfig", "dictConfig", "basicConfig",
    }
)  # fmt: skip
#: The handlers of the app that are classes of its own and name no filter, with why they need none. (The error journal's
#: handler scrubs its own records and says so, ``scrubs_its_own_records``, and ``errorlog.install`` calls ``protect_handlers`` for
#: every other handler that exists then: the module names the filter, so it is not listed here.)
_HANDLER_CLASSES = {
    "monitoring/vitals_history.py": "``_CountHandler`` counts the records by logger and level and keeps no text of them",
}


def _handlers_a_module_builds(tree: ast.AST) -> list[str]:
    """The calls of ``_BUILDERS`` and the classes derived from a logging handler in a module: where a record can be written."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name in _BUILDERS:
                found.append(f"{name}(), line {node.lineno}")
        elif isinstance(node, ast.ClassDef):
            if any(ast.unparse(b).startswith("logging.") and ast.unparse(b).endswith("Handler") or ast.unparse(b) == "Handler" for b in node.bases):
                found.append(f"class {node.name}, line {node.lineno}")
    return found


def test_no_module_builds_a_handler_that_writes_a_record_without_the_filter_or_a_reason():
    """The next ``StreamHandler`` or ``fileConfig`` is how the next record is written as it is, and nothing else would see it. The
    walk reads ``src/``, ``migrations/`` and ``scripts/`` for the calls that build a handler and the classes that are one. Each module
    that does has to name the filter (``protect_handler``, ``protect_handlers`` or ``SecretFilter``) or be in ``_HANDLER_CLASSES``
    with its reason, and an entry that no longer builds one has to come out: held to zero slack both ways."""
    built: dict[str, list[str]] = {}
    unprotected: dict[str, str] = {}
    for base in ("src", "migrations", "scripts"):
        for path in sorted((ROOT / base).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            found = _handlers_a_module_builds(ast.parse(text))
            if not found:
                continue
            rel = path.relative_to(ROOT / "src").as_posix() if base == "src" else path.relative_to(ROOT).as_posix()
            built[rel] = found
            if not any(word in text for word in ("protect_handler", "SecretFilter")):
                unprotected[rel] = ", ".join(found)
    assert {"utils/logging_config.py", "migrations/env.py", "monitoring/errorlog.py"} <= set(built), (
        f"the walk must find them, not nothing: {sorted(built)}"
    )
    assert set(unprotected) == set(_HANDLER_CLASSES), (
        f"build a handler with no filter and no reason: {sorted(set(unprotected) - set(_HANDLER_CLASSES))}; "
        f"listed but no longer building one (take them out): {sorted(set(_HANDLER_CLASSES) - set(unprotected))}"
    )
    assert all(len(reason) > 40 for reason in _HANDLER_CLASSES.values()), "a reason, not a placeholder"


# --------------------------------------------------------------------------- #
#  An exception that carries the key, through every handler the app configures at boot
# --------------------------------------------------------------------------- #
#: The handlers a running server has, built the way boot builds them in one process: the audit files and console of
#: ``setup_logging`` (``api``), the error journal and every handler that exists then (``errorlog.install``), and the server's own
#: (``uvicorn_log_config``). A module's logger reaches the journal through the root logger, as the 12 ``exc_info`` sites of
#: ``src/analytics/store.py`` and the 22 of ``src/backup/merge.py`` do; none of them is edited to be covered. A user who turns
#: debug logging on is covered too: SQLAlchemy's pool writes the text of a failed connect (a failed ``PRAGMA key``) at DEBUG
#: (``Error on connect(): %s``), a record that reaches the root logger's handlers whatever their own levels allow, so the run
#: puts a console on the root logger before the journal installs (a launcher's ``basicConfig``) and makes a real pool fail.
_BOOT = """
import logging, logging.config, os
from pathlib import Path
from src.monitoring import errorlog, secret_scrub
from src.utils import logging_config

if os.environ.get("OO_TEST_DEAD_FILTER"):
    secret_scrub.SecretFilter.filter = lambda self, record: True  # the control: the filter stands there and checks nothing
if os.environ.get("OO_TEST_NO_HOOK"):
    secret_scrub.protect_new_handlers = lambda: None  # the control: handlers built after boot's pass are built as they are
work = Path(os.environ["OO_TEST_DIR"])
logging_config.AUDIT_DIR = work
errorlog._log_path = lambda: work / "app_errors.jsonl"
logging_config.setup_logging("api", "api.log")                      # at import: every module that sets up a logger
logging.config.dictConfig(logging_config.uvicorn_log_config())      # uvicorn.run: Config() configures logging, before the lifespan
logging.getLogger().addHandler(logging.StreamHandler())             # a launcher's basicConfig console, there before the journal installs
errorlog.install()                                                  # run_deferred_startup, in the lifespan, once unlocked
logging.getLogger().addHandler(logging.FileHandler(work / "late.log"))  # a library adding a handler after all of that
key = os.environ["OO_DB_PASSPHRASE"]
sql = key.replace(chr(39), chr(39) * 2)
for name in ("api", "src.analytics.store", "src.backup.merge", "uvicorn.error", "uvicorn", "some.library"):
    log = logging.getLogger(name)
    try:
        raise RuntimeError(f"{name}: the store refused PRAGMA key = '{sql}' ({key!r})")
    except RuntimeError:
        log.exception("failed in %s", name)
        log.warning("the key was %s", key)
logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/api/search?q=" + key, "1.1", 200)

import sqlite3                                                       # debug logging on: the pool writes a failed connect's text itself
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool, QueuePool
logging.getLogger("sqlalchemy.pool").setLevel(logging.DEBUG)
def creator():
    raise sqlite3.OperationalError("near " + chr(34) + key + chr(34) + ": syntax error in PRAGMA key = '" + sql + "' (" + repr(key) + ")")
for pool in (NullPool, QueuePool):
    try:
        create_engine("sqlite://", creator=creator, poolclass=pool).connect()
    except sqlite3.Error:
        pass
    except Exception as exc:                                         # SQLAlchemy wraps what the driver raised; the app's route would scrub it
        assert key in str(exc), "the exception that left the pool carries the key, so the record below is the pool's own"
"""


def _boot_outputs(tmp_path, **env) -> dict[str, str]:
    work = tmp_path / f"boot{next(_SEEN)}"
    work.mkdir()
    console = _child(_BOOT, tmp_path, env={"OO_TEST_DIR": str(work), **env})
    audit = (work / "api.log").read_text(encoding="utf-8") if (work / "api.log").exists() else ""
    journal = (work / "app_errors.jsonl").read_text(encoding="utf-8") if (work / "app_errors.jsonl").exists() else ""
    late = (work / "late.log").read_text(encoding="utf-8") if (work / "late.log").exists() else ""
    return {"console": console, "audit file": audit, "error journal": journal, "late handler": late}


def test_an_exception_that_carries_the_key_is_written_without_it_through_every_handler_the_app_configures(tmp_path):
    """The coordinator's check of the runners PR: the 34 ``exc_info`` sites of ``src/analytics/store.py`` and
    ``src/backup/merge.py`` are not edited, so what covers them is the net under every handler. Each logger below is written
    through the handlers boot builds, and no shape of the key (as typed, as an SQL literal, as ``repr`` and as JSON write
    it, each written again by the others) is in any of the places a record lands. The control runs the same boot with the
    filter's check removed and finds the key in the console and the audit file, so the run measures something; the journal
    takes the passphrases out of its own records and finds none either way."""
    dead = _boot_outputs(tmp_path, OO_TEST_DEAD_FILTER="1")
    assert PASS in dead["console"] and PASS in dead["audit file"], "the control: a dead filter writes the key"
    for where in ("console", "late handler"):
        raw = [line for line in dead[where].splitlines() if line.startswith("Error on connect()")]
        assert len(raw) == 2 and all(PASS in line for line in raw), f"the control: {where} writes the pool's DEBUG line as the driver said it"
    assert all(shape not in dead["error journal"] for shape in S._forms(PASS)), "the journal scrubs its own, filter or none"
    unhooked = _boot_outputs(tmp_path, OO_TEST_NO_HOOK="1")
    assert PASS in unhooked["late handler"], "the control: a handler built after boot's pass is not protected without the hook"
    assert not any(shape in unhooked[where] for shape in S._forms(PASS) for where in ("console", "audit file", "error journal")), (
        "and every handler boot built is, so the hook is the only thing between the key and the late one"
    )

    live = _boot_outputs(tmp_path)
    for where, text in live.items():
        assert text, f"{where} wrote nothing: the run did not reach it"
        leaked = [shape for shape in S._forms(PASS) if shape in text]
        assert not leaked, f"{where} holds the key as {leaked}"
    assert live["console"].count(S.REDACTED) >= 6 and "failed in uvicorn.error" in live["console"]
    assert "failed in some.library" in live["late handler"] and S.REDACTED in live["late handler"], "the late handler wrote"
    assert "/api/search?q=" + S.REDACTED in live["console"], "the access line is written, with the key out of its path"
    for where in ("console", "late handler"):
        written = [line for line in live[where].splitlines() if line.startswith("Error on connect()")]
        assert len(written) == 2 and all(S.REDACTED in line for line in written), (
            f"{where}: the line the pool writes at DEBUG for a failed PRAGMA key (one for each pool class) is there, with the key out of it"
        )
    assert "src.analytics.store" in live["error journal"] and "src.backup.merge" in live["error journal"]
    assert S.REDACTED in live["audit file"]
    entries = [json.loads(line) for line in live["error journal"].splitlines() if line.strip()]
    assert {e["logger"] for e in entries} >= {"src.analytics.store", "src.backup.merge", "some.library"}
    assert all("traceback_tail" in e for e in entries if e["message"].startswith("failed in")), "the frames are kept"
