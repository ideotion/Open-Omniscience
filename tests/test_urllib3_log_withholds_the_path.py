"""R142: the HTTP library's own log lines do not carry a request's path or query, and a line this build does not recognise is withheld whole.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``urllib3`` logs a request's target on its own loggers: at WARNING, with the default log level, when a response has a malformed header line
("Failed to parse headers (url=...)", on a fetch that SUCCEEDS as well as on one that fails) and when a session retries; at DEBUG, the request
line and each redirect hop. The installer's download is a signed storage address, so its signature rode those lines into the error journal
that a debug bundle carries. ``src/ingest/urllib3_log.py`` rewrites the target arguments of the lines it knows before any handler sees them,
reduces every other argument and drops the exception and the stack, and withholds every other line on the library's loggers whole
(default-deny, failing closed).

Five groups of checks:

* the rewrite and the default, on records built by hand (each shape in the table, and the ways a record can fail to match it);
* EVERY CARRIER of a record (the message, an argument of any type, the exception, the stack): the first build cut the arguments that were text
  and left an exception argument and ``exc_info``, and the header-parsing warning put what the SERVER sent (a ``Location`` with its signature)
  in the journal through both;
* the REAL library against a loopback socket: a scripted adapter stands in for urllib3 entirely and could never show a line the library
  writes itself. Each real-stack case also asserts that the library DID log the line (so the case cannot pass because it stayed quiet),
  that the host is still there (so the filter did not blank the record) and that no line fell to the default (so the table matches what the
  library really logs);
* the QUALIFICATION of the installed release: the table is compared with the library's own source, so a release that logs something new, or
  passes something else in an argument, fails here by name and is read before it is allowed (``pyproject.toml`` carries the ceiling);
* the scope: the parent logger and any child, by the log-record factory.
"""

from __future__ import annotations

import ast
import contextlib
import logging
import re
import socket
import subprocess
import sys
import threading
from email.errors import MissingHeaderBodySeparatorDefect
from pathlib import Path
from typing import NamedTuple

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import HeaderParsingError, ProtocolError
from urllib3.util import Retry

import src.ingest  # noqa: F401  (importing the package is what installs the filter, which these tests rely on)
from src.ingest import urllib3_log
from src.safety import fetcher as fetcher_mod
from src.safety.settings import SafetySettings

ROOT = Path(__file__).resolve().parents[1]

SIG = "PLANTEDSIG"

_OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
#: A header line with no colon: urllib3 parses the response, finds a defect, logs it, and the request still succeeds.
_MALFORMED_HEADER = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nbadheaderwithoutcolon\r\nConnection: close\r\n\r\nok"
#: A redirect whose ``Location`` comes AFTER a malformed line: urllib3 cannot parse it, logs the unparsed header text (a signed address in it)
#: in the exception it passes as an argument and in ``exc_info``, and ``requests`` sees no ``Location``, so the fetch "succeeds" as a 302.
_SIGNED_LOCATION_AFTER_A_BAD_LINE = (
    b"HTTP/1.1 302 Found\r\nbadline\r\nLocation: https://objects.example/a?X-Amz-Signature=" + SIG.encode() + b"\r\n"
    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
)


@pytest.fixture(autouse=True)
def _no_proxy_from_the_environment(monkeypatch):
    """The cases talk to a loopback socket: a developer shell with ``HTTP_PROXY`` set would send them to the proxy and fail for another reason."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _serve(*replies: bytes | None) -> int:
    """A loopback listener that answers its Nth connection with ``replies[N]`` (``None``: read the request and close without a word)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(15)

    def run() -> None:
        try:
            for reply in replies:
                conn, _addr = srv.accept()
                with conn:
                    conn.recv(65536)
                    if reply is not None:
                        conn.sendall(reply)
        except OSError:
            pass
        finally:
            srv.close()

    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1]


def _record(name: str, msg: object, args: tuple = (), *, level: int = logging.WARNING, exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, args, exc_info)


def _run(record: logging.LogRecord) -> logging.LogRecord:
    assert urllib3_log._WithholdRequestPath().filter(record) is True, "a record is rewritten or withheld, never dropped"
    return record


# --------------------------------------------------------------------------- the rewrite itself


@pytest.mark.parametrize(
    ("arg", "expected"),
    [
        (f"/install.sh?sig={SIG}", urllib3_log.WITHHELD),
        ("/", urllib3_log.WITHHELD),
        (f"https://objects.githubusercontent.com:443/a/b?sig={SIG}", f"https://objects.githubusercontent.com:443/{urllib3_log.WITHHELD}"),
        (f"https://host.example/a#{SIG}", f"https://host.example/{urllib3_log.WITHHELD}"),
        (f"http://user:{SIG}@host.example/p", f"http://host.example/{urllib3_log.WITHHELD}"),
        (f"http://user:{SIG}@host.example", "http://host.example"),
        (f"https://host.example/?sig={SIG}", f"https://host.example/{urllib3_log.WITHHELD}"),
        (f"https://host.example?sig={SIG}", f"https://host.example/{urllib3_log.WITHHELD}"),
        (f"https://host.example/#{SIG}", f"https://host.example/{urllib3_log.WITHHELD}"),  # a fragment is something withheld, and it says so
        (f"HTTPS://Host.Example/p?sig={SIG}", f"https://host.example/{urllib3_log.WITHHELD}"),  # a scheme is read in any case
        (f"https://[::1]:8443/x?y={SIG}", f"https://[::1]:8443/{urllib3_log.WITHHELD}"),
        (f"https://host.example:notaport/x?{SIG}", urllib3_log.WITHHELD),
        ("https://host.example", "https://host.example"),
        ("https://host.example/", "https://host.example/"),
        # a "host" with a separator in it is a value: urllib3 would never log one, a hostile redirect could
        (f"https://h.example;X-Amz-Signature={SIG}", urllib3_log.WITHHELD),
        (f"https://h.example,{SIG}/x", urllib3_log.WITHHELD),
        (f"https://h.example=a{SIG}", urllib3_log.WITHHELD),
        ("https://xn--bcher-kva.example:8443", "https://xn--bcher-kva.example:8443"),
        ("host.example:443", "host.example:443"),
        ("HTTP/1.1", "HTTP/1.1"),
        ("GET", "GET"),
        (200, 200),
        (None, None),
    ],
)
def test_withhold_keeps_the_scheme_host_and_port_and_loses_the_rest(arg, expected):
    assert urllib3_log.withhold(arg) == expected


def test_a_target_position_reads_the_scheme_in_any_case():
    assert SIG not in str(urllib3_log._target(f"HTTP://h.example/p?sig={SIG}"))
    assert urllib3_log._target(f"HTTP://h.example/p?sig={SIG}") == f"http://h.example/{urllib3_log.WITHHELD}"
    assert urllib3_log._target(f"/p?sig={SIG}") == urllib3_log.WITHHELD and urllib3_log._target(None) == urllib3_log.WITHHELD


def test_a_number_none_or_bool_in_a_position_that_is_not_a_target_stays_what_it_was():
    for value in (0, 3, 1.5, True, None):
        carried = urllib3_log._carried(value)
        assert carried is value or carried == value
    record = _record("urllib3.connectionpool", '%s://%s:%s "%s %s %s" %s %s', ("https", "h.example", 443, "GET", "/p", "HTTP/1.1", 200, None))
    assert urllib3_log.scrub(record) is None
    assert record.args[-1] is None and record.args[-2] == 200 and record.args[2] == 443


def test_withhold_leaves_an_object_that_is_not_text_alone():
    exc = ConnectionError("Max retries exceeded")
    assert urllib3_log.withhold(exc) is exc


def _header_error() -> HeaderParsingError:
    """The real exception urllib3 passes: its text quotes the unparsed header lines the SERVER sent."""
    return HeaderParsingError([MissingHeaderBodySeparatorDefect()], f"badline\r\nLocation: https://objects.example/a?X-Amz-Signature={SIG}\r\n")


#: The shapes urllib3 logs a target in, as the library calls them (logger, level, template, arguments, with the REAL objects it passes), so a
#: shape that stops being covered fails here by name; the real-stack cases below show that urllib3 still logs them this way, and the
#: qualification cases that the table is the library's own.
_SHAPES = [
    ("urllib3.connection", logging.WARNING, "Failed to parse headers (url=%s): %s", (f"http://h.example:80/p?sig={SIG}", _header_error())),
    (
        "urllib3.connectionpool",
        logging.WARNING,
        "Retrying (%r) after connection broken by '%r': %s",
        (Retry(total=0), ProtocolError("Connection aborted.", ConnectionResetError(f"reset /p?sig={SIG}")), f"/p?sig={SIG}"),
    ),
    ("urllib3.connectionpool", logging.DEBUG, '%s://%s:%s "%s %s %s" %s %s', ("https", "h.example", 443, "GET", f"/p?sig={SIG}", "HTTP/1.1", 200, 2)),
    ("urllib3.connectionpool", logging.DEBUG, "Redirecting %s -> %s", (f"/a?sig={SIG}", f"https://h.example/b?sig={SIG}")),
    ("urllib3.connectionpool", logging.DEBUG, "Retry: %s", (f"/p?sig={SIG}",)),
    ("urllib3.util.retry", logging.DEBUG, "Incremented Retry for (url='%s'): %r", (f"/p?sig={SIG}", Retry(total=0))),
    ("urllib3.poolmanager", logging.INFO, "Redirecting %s -> %s", (f"/a?sig={SIG}", f"https://h.example/b?sig={SIG}")),
]


@pytest.mark.parametrize(("logger", "level", "fmt", "args"), _SHAPES, ids=[f"{s[0]}:{s[2][:24]}" for s in _SHAPES])
def test_each_shape_urllib3_logs_a_target_in_loses_it(caplog, logger, level, fmt, args):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    logging.getLogger(logger).log(level, fmt, *args)
    assert caplog.records, "the record must still be emitted: the filter rewrites, it never drops"
    assert SIG not in caplog.text
    assert urllib3_log.WITHHELD in caplog.text
    assert urllib3_log.UNRECOGNISED not in caplog.text, "a shape of the table is rewritten, not withheld whole"
    for arg in args:  # an object that is not text stands as its class name, whatever it quotes
        if arg is not None and not isinstance(arg, (str, int, float)):
            assert f"<{type(arg).__name__}>" in caplog.text


def test_a_record_with_no_target_is_left_as_it_was(caplog):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    logging.getLogger("urllib3.connectionpool").warning("Connection pool is full, discarding connection: %s. Connection pool size: %s", "h.example", 10)
    assert "Connection pool is full, discarding connection: h.example. Connection pool size: 10" in caplog.text


@pytest.mark.parametrize(("key", "shape"), sorted(urllib3_log.SHAPES.items()), ids=[f"{k[0]}:{k[1][:30]}" for k in sorted(urllib3_log.SHAPES)])
def test_every_entry_of_the_table_rewrites_exactly_its_target_positions(key, shape):
    """Table driven, over every entry: a target position holding a path, an address with a query, a form this build has not seen or an
    object that is not text comes out as the path marker (or the origin of an address), and every other position is untouched."""
    logger, template = key
    for target in (f"/p?sig={SIG}", f"GET /p?sig={SIG}", f"https://h.example:8443/p?sig={SIG}", ConnectionError(f"/p?sig={SIG}"), b"/p?sig=" + SIG.encode()):
        args = tuple(target if i in shape.target else f"KEPT{i}" for i in range(len(shape.args)))
        record = _run(_record(logger, template, args))
        assert record.msg == template and len(record.args) == len(shape.args)
        for i, got in enumerate(record.args):
            if i in shape.target:
                assert SIG not in str(got), (key, i, got)
                assert got in (urllib3_log.WITHHELD, f"https://h.example:8443/{urllib3_log.WITHHELD}"), (key, i, got)
            else:
                assert got == f"KEPT{i}", "a position that is not a target is passed as it came"


@pytest.mark.parametrize(("key", "shape"), sorted(urllib3_log.SHAPES.items()), ids=[f"{k[0]}:{k[1][:30]}" for k in sorted(urllib3_log.SHAPES)])
def test_every_entry_of_the_table_reduces_an_object_in_any_other_position_to_its_class_name(key, shape):
    """The first build left an object in a position that is not a target as it was; ``HeaderParsingError`` quotes the header lines the server
    sent. A number or ``None`` is the only thing that passes as it is."""
    logger, template = key
    args = tuple(f"/p?sig={SIG}" if i in shape.target else ConnectionError(f"/p?sig={SIG}") for i in range(len(shape.args)))
    record = _run(_record(logger, template, args))
    for i, got in enumerate(record.args):
        assert got == (urllib3_log.WITHHELD if i in shape.target else "<ConnectionError>"), (key, i, got)
    assert SIG not in repr(record.args)  # not formatted: a "%d" position holding text is only possible in this hand-made record
    numbers = _run(_record(logger, template, tuple(7 if i not in shape.target else "/p" for i in range(len(shape.args))))).args
    assert all(a == 7 for i, a in enumerate(numbers) if i not in shape.target)


# --------------------------------------------------------------------------- default-deny: a line this build does not know


def test_an_unknown_template_is_withheld_whole_even_when_the_target_is_hidden_in_a_longer_string(caplog):
    """The case the earlier, argument-by-argument filter missed: a line whose target is part of a longer string (no leading slash, no scheme)
    was left as the library wrote it. It fails without the default: the signature would be in the log text."""
    caplog.set_level(logging.DEBUG, logger="urllib3")
    logging.getLogger("urllib3.connectionpool").warning("A shape from a later release for %s", f"GET /p?sig={SIG} HTTP/1.1")
    assert caplog.records, "the record is kept"
    assert SIG not in caplog.text
    assert urllib3_log.UNRECOGNISED in caplog.text
    (rec,) = caplog.records
    assert rec.name == "urllib3.connectionpool" and rec.levelno == logging.WARNING, "the logger and the level stay"


@pytest.mark.parametrize("name", urllib3_log.LOGGERS)
def test_an_unknown_template_is_withheld_whole_on_every_logger_of_the_library(caplog, name):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    logging.getLogger(name).info("Not a line of any release we read: %s", f"/p?sig={SIG}")
    assert SIG not in caplog.text
    (rec,) = [r for r in caplog.records if r.name == name]
    assert rec.getMessage() == urllib3_log.UNRECOGNISED and rec.args == ()


def test_a_known_template_on_the_wrong_logger_is_withheld_whole(caplog):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    logging.getLogger("urllib3.poolmanager").debug("Retry: %s", f"/p?sig={SIG}")  # connectionpool's template
    assert SIG not in caplog.text and urllib3_log.UNRECOGNISED in caplog.text


@pytest.mark.parametrize("args", [(), (f"/p?sig={SIG}", "b", "c"), ("only-one-of-two",)])
def test_a_known_template_with_another_number_of_arguments_is_withheld_whole(args):
    record = _run(_record("urllib3.connectionpool", "Redirecting %s -> %s", args))
    assert record.getMessage() == urllib3_log.UNRECOGNISED and record.args == ()


@pytest.mark.parametrize("args", [None, {"url": f"/p?sig={SIG}"}, f"/p?sig={SIG}"])
def test_arguments_that_are_not_a_tuple_are_withheld_whole(args):
    record = _record("urllib3.connectionpool", "Retry: %s", ("x",))
    record.args = args  # type: ignore[assignment]
    assert _run(record).getMessage() == urllib3_log.UNRECOGNISED


@pytest.mark.parametrize("msg", [ConnectionError(f"Max retries exceeded with url: /p?sig={SIG}"), [f"/p?sig={SIG}"], {"url": f"/p?sig={SIG}"}, None, 7])
def test_a_message_that_is_not_text_is_withheld_whole_even_when_it_cannot_be_hashed(msg):
    """A list or a dict as the message cannot be a key of the table: the filter must refuse it and not raise inside the caller's log call."""
    record = _run(_record("urllib3.connectionpool", msg))
    assert SIG not in record.getMessage() and record.getMessage() == urllib3_log.UNRECOGNISED


@pytest.mark.parametrize("msg", [[f"/p?sig={SIG}"], {"url": f"/p?sig={SIG}"}])
def test_an_unhashable_message_with_an_exception_still_keeps_the_class_name_and_nothing_else(msg):
    try:
        raise ValueError(f"/p?sig={SIG}")
    except ValueError:
        exc_info = sys.exc_info()
    record = _run(_record("urllib3.connectionpool", msg, exc_info=exc_info))
    assert record.getMessage() == f"{urllib3_log.UNRECOGNISED} (ValueError)" and record.exc_info is None


def test_an_exception_class_whose_metaclass_answers_its_name_with_other_text_is_named_by_the_type():
    class Meta(type):
        @property
        def __name__(cls):  # type: ignore[override]
            return [f"/p?sig={SIG}"]

    class Odd(Exception, metaclass=Meta):
        pass

    record = _run(_record("urllib3.connection", "Unknown %s", ("x",), exc_info=(Odd, Odd(), None)))
    # the name is the one the type holds; what the metaclass answers is never read
    assert record.getMessage() == f"{urllib3_log.UNRECOGNISED} (Odd)" and SIG not in logging.Formatter("%(message)s").format(record)
    assert urllib3_log._carried(Odd()) == "<Odd>"


def test_a_stack_the_record_carries_is_dropped_with_the_rest_of_a_withheld_line():
    record = _record("urllib3.connection", "Unknown %s", ("x",))
    record.stack_info = f"Stack (most recent call last):\n  File x, in fetch(/p?sig={SIG})"
    record.exc_text = f"Traceback ... /p?sig={SIG}"
    record = _run(record)
    assert record.stack_info is None and record.exc_text is None
    assert SIG not in logging.Formatter("%(message)s").format(record)


def test_the_exception_class_is_kept_and_its_text_and_traceback_are_not():
    try:
        raise ValueError(f"bad address /p?sig={SIG}")
    except ValueError:
        exc_info = sys.exc_info()
    record = _run(_record("urllib3.connection", "A future warning with a traceback: %s", (f"/p?sig={SIG}",), exc_info=exc_info))
    assert record.exc_info is None and record.exc_text is None and record.stack_info is None
    assert record.getMessage() == f"{urllib3_log.UNRECOGNISED} (ValueError)"
    assert SIG not in logging.Formatter("%(message)s").format(record)


def test_withholding_twice_leaves_what_the_first_pass_left():
    try:
        raise OSError(f"/p?sig={SIG}")
    except OSError:
        exc_info = sys.exc_info()
    once = _run(_record("urllib3.connection", "Unknown %s", (f"/p?sig={SIG}",), exc_info=exc_info))
    first = once.getMessage()
    assert _run(once).getMessage() == first == f"{urllib3_log.UNRECOGNISED} (OSError)"
    known = _run(_record("urllib3.connectionpool", "Retry: %s", (f"/p?sig={SIG}",)))
    assert _run(known).args == (urllib3_log.WITHHELD,)


def test_a_message_that_only_starts_like_the_withheld_one_is_still_withheld():
    forged = _run(_record("urllib3.connection", f"{urllib3_log.UNRECOGNISED} (not an identifier /p?sig={SIG})"))
    assert SIG not in forged.getMessage()


@pytest.mark.parametrize("name", urllib3_log.LOGGERS)
def test_the_filter_is_on_each_logger_exactly_once(name):
    urllib3_log.install()
    urllib3_log.install()
    assert sum(isinstance(f, urllib3_log._WithholdRequestPath) for f in logging.getLogger(name).filters) == 1


def test_importing_the_fetcher_alone_installs_the_filter():
    """A process that only builds a guarded session (the installer's) gets the filter: ``src.ingest`` is imported by the fetcher and imports
    the module that installs it. Run in a fresh interpreter, because this process already has the filter, and ask the loggers by their names
    and the filter's class name, so that the check itself imports nothing from ``urllib3_log``."""
    names = (
        "urllib3", "urllib3.connection", "urllib3.connectionpool", "urllib3.contrib.emscripten.response", "urllib3.contrib.pyopenssl",
        "urllib3.http2.connection", "urllib3.poolmanager", "urllib3.response", "urllib3.util.retry",
    )
    code = (
        "import logging\n"
        "import src.safety.fetcher\n"
        f"names = {names!r}\n"
        "missing = [n for n in names if not any(type(f).__name__ == '_WithholdRequestPath' for f in logging.getLogger(n).filters)]\n"
        "print('MISSING', missing)\n"
        "print('FACTORY', type(logging.getLogRecordFactory()).__name__)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert "MISSING []" in out.stdout
    assert "FACTORY _Factory" in out.stdout
    assert set(urllib3_log.LOGGERS) == set(names)


# --------------------------------------------------------------------------- every carrier of a record


def _mapping_as_the_only_argument(log: logging.Logger) -> None:
    log.warning("%(u)s", {"u": f"/p?sig={SIG}"})


def _target_in_the_message(log: logging.Logger) -> None:
    log.warning(f"GET /p?sig={SIG}")


def _container_argument(log: logging.Logger) -> None:
    log.warning("%s", [f"/p?sig={SIG}"])


def _exception_argument(log: logging.Logger) -> None:
    log.warning("%s", ConnectionError(f"/p?sig={SIG}"))


def _exception_text_in_exc_info(log: logging.Logger) -> None:
    try:
        raise ValueError(f"bad /p?sig={SIG}")
    except ValueError:
        log.warning("A line with a traceback", exc_info=True)


def _stack_info(log: logging.Logger) -> None:
    log.warning("A line with a stack", stack_info=True, extra={})  # the stack is the caller's frames, with this module's names in it


_CARRIERS = [
    _mapping_as_the_only_argument,
    _target_in_the_message,
    _container_argument,
    _exception_argument,
    _exception_text_in_exc_info,
    _stack_info,
]


def _assert_no_carrier_leaks(caplog) -> None:
    """The planted value is in no form the record can take: the text, each formatted record (what a handler writes), the message, the cached
    exception text, and the exception itself."""
    assert caplog.records, "a record is rewritten or withheld, never dropped"
    assert SIG not in caplog.text
    for r in caplog.records:
        assert SIG not in logging.Formatter("%(message)s").format(r)
        assert SIG not in r.getMessage()
        assert SIG not in str(r.exc_text) and r.exc_info is None and r.stack_info is None
        assert SIG not in repr(r.args) and SIG not in str(r.msg)


@pytest.mark.parametrize("name", urllib3_log.LOGGERS)
@pytest.mark.parametrize("carrier", _CARRIERS, ids=[c.__name__.strip("_") for c in _CARRIERS])
def test_no_part_of_a_record_on_any_logger_of_the_library_carries_the_target(caplog, name, carrier):
    """The shapes the first build skipped (it rewrote the text arguments of a tuple and nothing else): each on every logger, and it fails when
    the tuple branch is all there is."""
    caplog.set_level(logging.DEBUG, logger="urllib3")
    carrier(logging.getLogger(name))
    _assert_no_carrier_leaks(caplog)
    assert urllib3_log.UNRECOGNISED in caplog.text


def test_the_exception_and_the_exception_argument_of_a_known_record_are_not_written(caplog):
    """The record urllib3 really writes for a malformed header: the exception is an argument AND ``exc_info``, and its text is the header
    lines the server sent after its first malformed one."""
    caplog.set_level(logging.DEBUG, logger="urllib3")
    err = _header_error()
    try:
        raise err
    except HeaderParsingError:
        logging.getLogger("urllib3.connection").warning("Failed to parse headers (url=%s): %s", f"http://h.example:80/p?sig={SIG}", err, exc_info=True)
    _assert_no_carrier_leaks(caplog)
    (rec,) = caplog.records
    assert rec.getMessage() == f"Failed to parse headers (url=http://h.example:80/{urllib3_log.WITHHELD}): <HeaderParsingError>"


def test_a_filter_that_raises_withholds_the_message_and_does_not_raise_into_the_library(caplog, monkeypatch):
    def boom(arg):
        raise RuntimeError(f"/p?sig={SIG}")

    monkeypatch.setattr(urllib3_log, "withhold", boom)
    logging.getLogger("urllib3.connectionpool").warning("Resetting dropped connection: %s", "h.example")
    (rec,) = caplog.records
    assert rec.getMessage() == urllib3_log.UNRECOGNISED and rec.args == ()
    assert SIG not in caplog.text
    monkeypatch.setattr(urllib3_log, "_target", boom)
    logging.getLogger("urllib3.connectionpool").debug("Retry: %s", f"/p?sig={SIG}")
    assert SIG not in caplog.text


def test_scrub_alone_leaves_a_record_with_nothing_when_it_raises(monkeypatch):
    """``scrub`` on its own, once (the logger's filter and the factory both run it, so a record that survives a half-done first pass is
    cleaned by the second and the cases above cannot tell): what is left after a failure is the fixed sentence and no argument or trace,
    and an attribute another library added keeps a harmless value so a format string that names it still works."""

    def boom(arg):
        raise RuntimeError(f"/p?sig={SIG}")

    monkeypatch.setattr(urllib3_log, "_carried", boom)
    Hostile = object

    try:
        raise ValueError(f"/p?sig={SIG}")
    except ValueError:
        exc_info = sys.exc_info()
    record = _record(
        "urllib3.connectionpool", "Connection pool is full, discarding connection: %s. Connection pool size: %s", (Hostile(), 3), exc_info=exc_info
    )
    record.exc_text = f"Traceback /p?sig={SIG}"
    record.stack_info = f"Stack /p?sig={SIG}"
    record.carried = f"/p?sig={SIG}"  # what extra= puts on a record
    urllib3_log.scrub(record)
    assert record.msg == urllib3_log.UNRECOGNISED and record.args == ()
    assert record.exc_info is None and record.exc_text is None and record.stack_info is None
    assert record.carried == urllib3_log.WITHHELD and record.name == "urllib3.connectionpool"


def test_an_argument_whose_class_property_raises_is_named_by_its_type_and_does_not_raise_into_the_library(caplog):
    class Hostile:
        @property
        def __class__(self):  # type: ignore[override]
            raise RuntimeError(f"/p?sig={SIG}")

    # two arguments, because the standard library reads the class of a lone argument itself, before this module sees the record
    logging.getLogger("urllib3.connectionpool").warning("Connection pool is full, discarding connection: %s. Connection pool size: %s", Hostile(), 3)
    (rec,) = caplog.records
    assert rec.getMessage() == "Connection pool is full, discarding connection: <Hostile>. Connection pool size: 3" and SIG not in caplog.text


@pytest.mark.parametrize("name", urllib3_log.LOGGERS)
def test_an_attribute_put_on_the_record_by_extra_loses_its_value_with_the_rest(caplog, name):
    """``extra=`` writes attributes onto the record, where a handler that serialises the record's dictionary (a JSON log) would write them. The
    attribute stays with a harmless value, so a format string that names it does not make the handler drop the record."""
    caplog.set_level(logging.DEBUG, logger="urllib3")
    logging.getLogger(name).warning("An unknown line", extra={"target": f"/p?sig={SIG}", "nested": {"u": f"/p?sig={SIG}"}})
    (rec,) = [r for r in caplog.records if r.name == name]
    assert rec.target == urllib3_log.WITHHELD and rec.nested == urllib3_log.WITHHELD
    assert SIG not in repr(vars(rec))
    assert logging.Formatter("%(target)s %(message)s").format(rec).startswith(urllib3_log.WITHHELD)


def test_the_attributes_a_record_has_of_its_own_are_kept(caplog):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    logging.getLogger("urllib3.connectionpool").warning("Resetting dropped connection: %s", "h.example")
    (rec,) = caplog.records
    assert (rec.name, rec.levelno, rec.levelname, rec.funcName, rec.lineno) == ("urllib3.connectionpool", logging.WARNING, "WARNING", rec.funcName, rec.lineno)
    assert rec.pathname and rec.created and rec.msecs is not None and rec.threadName and rec.processName


def test_the_retry_warning_the_library_really_logs_loses_the_value_of_its_extra(caplog):
    """The library's own ``extra={'__urllib3-retry-warning': {'host': ...}}`` is in the table as a keyword, and the attribute holds no host."""
    caplog.set_level(logging.DEBUG, logger="urllib3")
    port = _serve(None, _OK)
    session = _session()
    session.mount("http://", HTTPAdapter(max_retries=Retry(total=1, backoff_factor=0)))
    assert session.get(f"http://127.0.0.1:{port}/install.sh?sig={SIG}", timeout=10).status_code == 200
    (rec,) = [r for r in caplog.records if r.getMessage().startswith("Retrying")]
    # 2.8.0 passes the extra and 2.7.0 does not (the table names the keyword for the release that does): either way no host is left on the record
    assert vars(rec).get("__urllib3-retry-warning", urllib3_log.WITHHELD) == urllib3_log.WITHHELD


@pytest.mark.parametrize(
    "host",
    ["localhost;x-amz-signature=deadbeefcafe0123", "h.example,sig", "h.example=a" + SIG, "h.example?sig=" + SIG, "h.example sig", "h.example/p"],
)
def test_a_host_in_a_position_that_is_not_a_target_is_kept_only_as_a_plain_name(host):
    """urllib3 fills ``self.host`` from a server's ``Location`` and accepts a ``;`` or ``=`` in it, so the debug line that names the host
    could carry a signature the way a path does."""
    record = _run(_record("urllib3.connectionpool", "Starting new HTTP connection (%d): %s:%s", (1, host, "80"), level=logging.DEBUG))
    assert record.getMessage() == f"Starting new HTTP connection (1): {urllib3_log.WITHHELD}:80"


@pytest.mark.parametrize("host", ["h.example", "127.0.0.1", "::1", "[::1]", "xn--bcher-kva.example", "localhost"])
def test_a_plain_host_in_a_position_that_is_not_a_target_is_kept(host):
    record = _run(_record("urllib3.connectionpool", "Starting new HTTP connection (%d): %s:%s", (1, host, "80"), level=logging.DEBUG))
    assert record.getMessage() == f"Starting new HTTP connection (1): {host}:80"


def test_a_host_with_a_signature_in_it_reaches_no_part_of_a_record_over_a_real_socket(caplog):
    """The server's ``Location`` names a host with a ``;`` and a signature; the debug line of the connection the client then starts to make
    named it whole (found by the independent read, on 2.7.0 and 2.8.0)."""
    caplog.set_level(logging.DEBUG)
    loc = f"http://localhost;x-amz-signature={SIG}/obj".encode()
    port = _serve(b"HTTP/1.1 302 Found\r\nLocation: " + loc + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
    with contextlib.suppress(requests.RequestException):  # the host does not resolve; the record of the attempt is what is looked at
        _session().get(f"http://127.0.0.1:{port}/a", timeout=5)
    named = [r for r in caplog.records if r.name.startswith("urllib3") and "Starting new HTTP connection" in r.getMessage()]
    assert len(named) >= 2, "the redirect's connection was not attempted: the case proves nothing"
    assert SIG not in caplog.text and all(SIG not in repr(vars(r)) for r in caplog.records)


class _Lying(str):
    """A ``str`` that says something else when it is asked for its text."""

    def __str__(self) -> str:
        return f"Retry: /p?sig={SIG}"

    __repr__ = __str__


class _LyingInt(int):
    def __str__(self) -> str:
        return f"/p?sig={SIG}"

    __repr__ = __str__


def test_a_subclass_of_str_or_int_is_not_read_as_text_or_a_number():
    msg = _run(_record("urllib3.connectionpool", _Lying("Retry: %s"), ("/x",)))
    assert msg.getMessage() == urllib3_log.UNRECOGNISED
    arg = _run(_record("urllib3.connectionpool", "Starting new HTTP connection (%d): %s:%s", (_LyingInt(1), _Lying("h.example"), "80")))
    assert SIG not in arg.getMessage() and arg.getMessage() == "Starting new HTTP connection (1): <_Lying>:80"  # the number keeps %d working
    assert SIG not in str(urllib3_log._target(_Lying(f"https://h.example/p?sig={SIG}")))


class _LyingFloat(float):
    def __str__(self) -> str:
        return f"/p?sig={SIG}"

    __repr__ = __str__


class _LooksWithheld(str):
    """A ``str`` that answers every question the check for a withheld message asks the way a withheld message would, and says something else
    when it is turned into text."""

    def startswith(self, *a, **k) -> bool:  # type: ignore[override]
        return True

    def endswith(self, *a, **k) -> bool:  # type: ignore[override]
        return True

    def __getitem__(self, item):  # type: ignore[override]
        return "Retry"

    def __len__(self) -> int:
        return 1

    def __str__(self) -> str:
        return f"Retry: /p?sig={SIG}"

    __repr__ = __str__


def test_the_numbers_a_record_carries_reach_the_handler_as_plain_numbers_of_their_own_type():
    """A number is kept as it was (a ``bool`` stays a ``bool``: ``True`` is not ``1``), and an instance of a subclass of ``int`` or ``float``
    becomes the plain number it holds, so ``%s`` and ``%r`` cannot call the subclass's own text."""
    assert urllib3_log._carried(True) is True and urllib3_log._carried(False) is False
    assert urllib3_log._carried(None) is None
    assert type(urllib3_log._carried(7)) is int and type(urllib3_log._carried(1.5)) is float
    cut = urllib3_log._carried(_LyingInt(3))
    assert type(cut) is int and cut == 3 and str(cut) == "3"
    cut = urllib3_log._carried(_LyingFloat(2.5))
    assert type(cut) is float and cut == 2.5 and str(cut) == "2.5"
    record = _run(_record("urllib3.connectionpool", "Starting new HTTP connection (%d): %s:%s", (_LyingInt(1), "h.example", "80")))
    assert type(record.args[0]) is int
    assert SIG not in logging.Formatter("%(message)s").format(_run(_record("urllib3.connectionpool", "Retry: %s", (_LyingFloat(1.5),))))


def test_a_text_that_answers_like_a_withheld_message_is_replaced_not_kept():
    """The second pass over a record keeps a message the first pass wrote; a ``str`` subclass must not be able to look like one."""
    record = _run(_record("urllib3.connectionpool", _LooksWithheld("Retry: %s"), ("/x",)))
    assert record.msg == urllib3_log.UNRECOGNISED and type(record.msg) is str
    assert SIG not in logging.Formatter("%(message)s").format(record)


def test_withhold_does_not_read_a_subclass_of_str_as_text():
    lying = _Lying(f"https://h.example/p?sig={SIG}")
    assert urllib3_log.withhold(lying) is lying, "returned as it was, never taken apart with its own methods"


def test_a_class_whose_name_is_not_a_plain_identifier_is_named_object():
    """``cls.__name__`` can be set to any text, and an exception of such a class is what an error message names."""
    Evil = type("Retry", (ValueError,), {})
    Evil.__name__ = f"Retry /p?sig={SIG}"
    assert urllib3_log._class_name(Evil) == "object"
    record = _run(_record("urllib3.connectionpool", "unknown %s", ("x",), exc_info=(Evil, Evil("e"), None)))
    assert SIG not in repr(vars(record)) and record.msg == f"{urllib3_log.UNRECOGNISED} (object)"

    class Name(str):
        def __str__(self) -> str:
            return f"/p?sig={SIG}"

        __repr__ = __str__

    Odd = type("Odd", (ValueError,), {})
    Odd.__name__ = Name("Odd")
    assert urllib3_log._class_name(Odd) == "object", "a str subclass is not read, even when it is an identifier"


def test_the_exception_a_record_carries_is_read_once():
    """``record.exc_info`` is read into a local once; three reads would let a value that changes between them (a property, another thread)
    decide the check and the use differently."""

    class Flipping(logging.LogRecord):
        @property
        def exc_info(self):  # type: ignore[override]
            self.__dict__["_reads"] = self.__dict__.get("_reads", 0) + 1
            return (ValueError, ValueError("e"), None) if self.__dict__["_reads"] == 1 else None

        @exc_info.setter
        def exc_info(self, value) -> None:
            self.__dict__["_set"] = value

    record = Flipping("urllib3.connectionpool", logging.WARNING, __file__, 1, "unknown %s", ("x",), None)
    urllib3_log.scrub(record)
    assert record.msg == f"{urllib3_log.UNRECOGNISED} (ValueError)"


def test_a_message_a_formatter_cached_before_the_scrub_holds_no_text_of_the_record():
    record = _record("urllib3.connectionpool", "Retry: %s", (f"/p?sig={SIG}",))
    record.message = record.getMessage()
    record.asctime = f"cached {SIG}"
    urllib3_log.scrub(record)
    assert SIG not in repr(vars(record))
    assert logging.Formatter("%(message)s").format(record) == f"Retry: {urllib3_log.WITHHELD}"


def test_a_format_string_that_names_an_attribute_another_library_added_still_writes_the_record():
    old = logging.getLogRecordFactory()

    def factory(*a, **k):
        r = old(*a, **k)
        r.trace_id = "abc123"
        return r

    logging.setLogRecordFactory(factory)
    try:
        record = logging.makeLogRecord({"name": "urllib3.connectionpool", "msg": "Retry: %s", "args": (f"/p?sig={SIG}",), "levelno": logging.WARNING})
        record.trace_id = "abc123"
        urllib3_log.scrub(record)
        assert logging.Formatter("%(trace_id)s %(message)s").format(record) == f"{urllib3_log.WITHHELD} Retry: {urllib3_log.WITHHELD}"
    finally:
        logging.setLogRecordFactory(old)


# --------------------------------------------------------------------------- the scope: the parent, a child, a module the table does not list


@pytest.mark.parametrize("name", ["urllib3", "urllib3.connectionpool.child", "urllib3.futuremodule", "urllib3.util.ssl_"])
def test_a_logger_under_the_library_name_that_the_table_does_not_list_is_withheld_whole(caplog, name):
    """A filter on a logger sees only the records that logger creates, so a child (or a module a later release adds) would have passed. The
    log-record factory covers the whole name."""
    caplog.set_level(logging.DEBUG, logger="urllib3")
    logging.getLogger(name).warning("Something %s", f"GET /p?sig={SIG}")
    assert SIG not in caplog.text and urllib3_log.UNRECOGNISED in caplog.text


def test_the_factory_cuts_an_unlisted_logger_s_text_and_traces_but_not_its_extra_and_the_docs_say_so(caplog):
    """THE LIMIT, pinned so the sentence in the module docstring, docs/SECURITY.md and the queue stays true: ``Logger.makeRecord`` runs the
    factory BEFORE it copies ``extra=`` onto the record, and a record that propagates from a child never meets the parent's filter, so an
    ``extra`` attribute on a logger outside ``LOGGERS`` is not cut. No release does this (the nine loggers are listed and the only ``extra``
    goes to a filtered one); a release that adds a logger fails the qualification test by name. If this test fails because the extra IS cut
    now, delete the sentence about the limit in the three places and make this test assert the cut."""
    caplog.set_level(logging.DEBUG, logger="urllib3")
    name = "urllib3.futuremodule.child"
    assert name not in urllib3_log.LOGGERS
    logging.getLogger(name).warning("Something %s", f"GET /p?sig={SIG}", extra={"target": f"/p?sig={SIG}"}, exc_info=ValueError(SIG))
    (record,) = [r for r in caplog.records if r.name == name]
    assert SIG not in record.getMessage() and urllib3_log.UNRECOGNISED in record.getMessage()
    assert record.exc_info is None and record.exc_text is None
    assert vars(record)["target"] == f"/p?sig={SIG}", "the extra survives on an unlisted logger (the stated limit)"
    assert "THE FACTORY'S LIMIT" in (urllib3_log.__doc__ or ""), "the module docstring states the limit"


@pytest.mark.parametrize("name", ["urllib3x", "my.urllib3", "requests", "app.fetch", "urllib"])
def test_a_logger_that_is_not_under_the_library_name_is_left_alone(caplog, name):
    logging.getLogger(name).warning("Fetching %s", "https://h.example/p")
    assert "Fetching https://h.example/p" in caplog.text and urllib3_log.UNRECOGNISED not in caplog.text


def test_the_factory_wraps_the_previous_one_once_and_is_put_back_if_something_replaces_it():
    current = logging.getLogRecordFactory()
    assert isinstance(current, urllib3_log._Factory)
    urllib3_log.install()
    urllib3_log.install()
    assert logging.getLogRecordFactory() is current, "installing again must not nest"

    ran: list[str] = []

    def tagging(*args, **kwargs):
        ran.append(args[0])
        return logging.LogRecord(*args, **kwargs)

    try:
        logging.setLogRecordFactory(tagging)  # another library replaces the factory
        urllib3_log.install()
        now = logging.getLogRecordFactory()
        assert isinstance(now, urllib3_log._Factory) and now.inner is tagging
        record = logging.getLogger("urllib3.connectionpool.child").makeRecord("urllib3.connectionpool.child", logging.WARNING, __file__, 1, "x %s", (f"/p?sig={SIG}",), None)
        assert ran == ["urllib3.connectionpool.child"], "the factory it wraps still runs"
        assert SIG not in record.getMessage()
    finally:
        logging.setLogRecordFactory(current)


@pytest.fixture()
def filter_off():
    """The library's loggers as they would be without this module: no filter on them and the factory it wraps."""
    saved = {n: list(logging.getLogger(n).filters) for n in urllib3_log.LOGGERS}
    factory = logging.getLogRecordFactory()
    for n, filters in saved.items():
        logging.getLogger(n).filters[:] = [f for f in filters if not isinstance(f, urllib3_log._WithholdRequestPath)]
    if isinstance(factory, urllib3_log._Factory):
        logging.setLogRecordFactory(factory.inner)
    yield
    for n, filters in saved.items():
        logging.getLogger(n).filters[:] = filters
    logging.setLogRecordFactory(factory)


# --------------------------------------------------------------------------- the real library, a real socket


def test_a_response_with_a_malformed_header_logs_without_the_path_and_the_fetch_still_succeeds(caplog):
    """The reproduction of the read's finding B1, at the default level, on a SUCCESSFUL fetch."""
    caplog.set_level(logging.WARNING)
    port = _serve(_MALFORMED_HEADER)
    resp = _session().get(f"http://127.0.0.1:{port}/install.sh?sig={SIG}", timeout=10)
    assert resp.status_code == 200 and resp.content == b"ok"
    assert "Failed to parse headers" in caplog.text, "urllib3 must have logged the line, or this case proves nothing"
    assert f"127.0.0.1:{port}" in caplog.text
    assert SIG not in caplog.text
    assert "install.sh" not in caplog.text
    assert urllib3_log.UNRECOGNISED not in caplog.text, "the library's real line is a shape of the table"


def test_a_signed_location_after_a_malformed_line_reaches_no_part_of_a_record(caplog):
    """The coordinator's reproduction of the leak in #1414's filter: the address is not the request's but the SERVER's, in the unparsed header
    text the exception carries (as an argument and as ``exc_info``). The fetch "succeeds" as a 302 and the record must still be emitted."""
    caplog.set_level(logging.DEBUG, logger="urllib3")
    port = _serve(_SIGNED_LOCATION_AFTER_A_BAD_LINE)
    resp = _session().get(f"http://127.0.0.1:{port}/install.sh", timeout=10, allow_redirects=False)
    assert resp.status_code == 302
    assert "Failed to parse headers" in caplog.text, "urllib3 must have logged the line, or this case proves nothing"
    assert "<HeaderParsingError>" in caplog.text
    _assert_no_carrier_leaks(caplog)
    assert "objects.example" not in caplog.text and "X-Amz-Signature" not in caplog.text


def test_the_signed_location_case_does_leak_when_the_filter_is_off(caplog, filter_off):
    """The case above can fail: without the filter and the factory the same exchange puts the signature in the log text and in the traceback."""
    caplog.set_level(logging.DEBUG, logger="urllib3")
    port = _serve(_SIGNED_LOCATION_AFTER_A_BAD_LINE)
    _session().get(f"http://127.0.0.1:{port}/install.sh", timeout=10, allow_redirects=False)
    assert SIG in caplog.text
    assert any(SIG in logging.Formatter().format(r) for r in caplog.records)


def test_a_retry_logs_without_the_path(caplog):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    port = _serve(None, _OK)
    session = _session()
    session.mount("http://", HTTPAdapter(max_retries=Retry(total=1, backoff_factor=0)))
    resp = session.get(f"http://127.0.0.1:{port}/install.sh?sig={SIG}", timeout=10)
    assert resp.status_code == 200
    assert "Retrying" in caplog.text, "urllib3 must have logged the retry, or this case proves nothing"
    assert "Incremented Retry" in caplog.text, "and the retry object's own debug line"
    assert SIG not in caplog.text
    assert "install.sh" not in caplog.text
    assert urllib3_log.UNRECOGNISED not in caplog.text


def test_the_debug_request_line_and_the_redirect_hop_log_without_the_path(caplog):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    redirect = b"HTTP/1.1 302 Found\r\nLocation: /next.sh?sig=" + SIG.encode() + b"2\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    port = _serve(redirect, _OK)
    resp = _session().get(f"http://127.0.0.1:{port}/install.sh?sig={SIG}", timeout=10)
    assert resp.status_code == 200
    assert 'HTTP/1.1" 302' in caplog.text and 'HTTP/1.1" 200' in caplog.text, "urllib3 must have logged both request lines"
    assert SIG not in caplog.text
    assert "install.sh" not in caplog.text and "next.sh" not in caplog.text
    assert urllib3_log.UNRECOGNISED not in caplog.text


def test_the_installers_own_download_logs_nothing_of_the_signed_address_even_when_the_library_does(caplog, monkeypatch):
    """The installer's real path (``_default_get_bytes`` through ``_get_within`` and a ``GuardedSession``) against a loopback server whose
    answer has a malformed header: the download succeeds and the signature is in no log record. Only the host-list check is patched, because
    the listed hosts are https on port 443 and this is a loopback socket."""
    from src.llm import installer

    monkeypatch.setattr(fetcher_mod, "load_settings", lambda: SafetySettings(fetch_mode="transparent"))
    monkeypatch.setattr(fetcher_mod, "refuse_unlisted_host", lambda url, allowed: None)
    caplog.set_level(logging.DEBUG, logger="urllib3")
    caplog.set_level(logging.DEBUG)
    port = _serve(_MALFORMED_HEADER)
    body = installer._default_get_bytes(f"http://127.0.0.1:{port}/ollama/ollama/releases/download/v1/install.sh?X-Amz-Signature={SIG}")
    assert body == b"ok"
    assert "Failed to parse headers" in caplog.text, "urllib3 must have logged the line, or this case proves nothing"
    assert SIG not in caplog.text
    assert "X-Amz-Signature" not in caplog.text and "releases/download" not in caplog.text
    assert urllib3_log.UNRECOGNISED not in caplog.text


# --------------------------------------------------------------------------- the installed release is the one the table was read from


_LEVEL_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "fatal", "exception", "log"}
_LOGGER_LIKE = re.compile(r"(^|\.)_*(log|logger|logging)$", re.IGNORECASE)


class _Reading(NamedTuple):
    #: ``(module, template) -> [(argument sources, keyword sources), ...]``, EVERY call that has that template (two calls with one template
    #: and different arguments are two entries, not one overwriting the other).
    calls: dict[tuple[str, str], list[tuple[tuple[str, ...], tuple[str, ...]]]]
    #: Every module that creates a logger, however it is bound.
    loggers: set[str]
    #: Everything the reading could not attribute: a call whose message is not a text constant, a call on something that looks like a logger
    #: but was not bound from ``getLogger``, a logger created and never bound.
    unclassified: list[str]


def _is_get_logger(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == "getLogger") or (isinstance(node.func, ast.Attribute) and node.func.attr == "getLogger")
    )


def _read_library(root: Path) -> _Reading:
    """Read a ``urllib3`` source tree: every ``<logger>.<level>("template", args..., keywords...)`` call. A logger is bound by any assignment of
    a ``getLogger`` call (a plain name, an annotated name, ``self.log``), however ``getLogger`` was imported, or is the ``getLogger`` call
    itself. The first reading matched only ``name = x.getLogger(...)`` and a new module written another way was invisible to it."""
    calls: dict[tuple[str, str], list[tuple[tuple[str, ...], tuple[str, ...]]]] = {}
    loggers: set[str] = set()
    unclassified: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).with_suffix("")
        module = ".".join(rel.parts[:-1] if rel.name == "__init__" else rel.parts)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        creators = [n for n in ast.walk(tree) if _is_get_logger(n)]
        bound: set[str] = set()
        followed: set[int] = set()  # the getLogger calls the reading knows how to follow: assigned to a name, or logged on directly
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and _is_get_logger(n.value):
                bound.update(ast.unparse(target) for target in n.targets)
                followed.add(id(n.value))
            elif isinstance(n, ast.AnnAssign) and n.value is not None and _is_get_logger(n.value):
                bound.add(ast.unparse(n.target))
                followed.add(id(n.value))
            elif isinstance(n, ast.Attribute) and _is_get_logger(n.value):  # chained: ``getLogger(__name__).warning(...)`` or ``.addHandler(...)``
                followed.add(id(n.value))
        if creators:
            loggers.add(module)
        for c in creators:
            # the filters cover the NAMES in LOGGERS, and the calls are filed under the module: a logger named anything else (the root, a name
            # outside urllib3) would be neither covered nor reported
            named = c.args[0] if len(c.args) == 1 and not c.keywords else None
            if not (named is not None and (ast.unparse(named) == "__name__" or (isinstance(named, ast.Constant) and named.value == module))):
                unclassified.append(f"{module}:{c.lineno} getLogger does not name the module's own logger: {ast.unparse(c)}")
            if id(c) not in followed:
                unclassified.append(f"{module}:{c.lineno} a getLogger call the reading cannot follow (not assigned to a name and not logged on directly)")
        chained = 0
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _LEVEL_METHODS):
                continue
            base = ast.unparse(n.func.value)
            direct = _is_get_logger(n.func.value)
            if not (base in bound or direct):
                if _LOGGER_LIKE.search(base):
                    unclassified.append(f"{module}:{n.lineno} logs on {base!r}, which is not bound from getLogger")
                continue
            chained += direct
            first = n.args[0] if n.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                args = tuple(ast.unparse(a) for a in n.args[1:])
                keywords = tuple(sorted(ast.unparse(k) for k in n.keywords))
                calls.setdefault((module, first.value), []).append((args, keywords))
            else:
                unclassified.append(f"{module}:{n.lineno} logs a message that is not a text constant")
        if creators and not bound and not chained:
            unclassified.append(f"{module} creates a logger and never binds it")
    return _Reading(calls, loggers, unclassified)


def _installed_urllib3_calls() -> _Reading:
    import urllib3

    return _read_library(Path(urllib3.__file__).resolve().parent)


def _against_the_table(reading: _Reading) -> tuple[list, list, list]:
    """``(new, gone, changed)``: calls the table does not know, entries the library no longer has, and calls whose arguments or keywords differ
    from the entry's, whichever of several calls with one template it is."""
    table = urllib3_log.SHAPES
    new = sorted(set(reading.calls) - set(table))
    gone = sorted(set(table) - set(reading.calls))
    # the arguments must be the entry's; the keywords must be among the entry's (a release may drop one: 2.7.0 has no ``extra=`` on the retry warning)
    changed = sorted(
        k for k in set(reading.calls) & set(table) if any(args != table[k].args or not set(kws) <= set(table[k].kwargs) for args, kws in reading.calls[k])
    )
    return new, gone, changed


def test_every_log_call_of_the_installed_urllib3_is_a_shape_the_table_knows():
    """THE QUALIFICATION. A release that logs a new line, changes what a known line passes, or drops a line fails here, by name; read the
    release's change, extend the table, and only then lift the ``pyproject.toml`` ceiling (docs/maintenance/EXTERNAL_DEPENDENCIES.md)."""
    reading = _installed_urllib3_calls()
    assert reading.unclassified == [], f"a log call or a logger this reading cannot attribute: {reading.unclassified}"
    assert sum(len(v) for v in reading.calls.values()) >= 16, "the reading found the library's calls (a reading that finds none proves nothing)"
    new, gone, changed = _against_the_table(reading)
    assert (new, gone, changed) == ([], [], []), f"new in the library: {new}; in the table only: {gone}; arguments or keywords changed: {changed}"


def test_every_logger_the_installed_urllib3_defines_is_covered():
    reading = _installed_urllib3_calls()
    assert len(reading.loggers) >= 9, "the reading found the library's loggers"
    assert reading.loggers == set(urllib3_log.LOGGERS), f"missing {sorted(reading.loggers - set(urllib3_log.LOGGERS))}, extra {sorted(set(urllib3_log.LOGGERS) - reading.loggers)}"


def _fake_library(tmp_path: Path, **modules: str) -> Path:
    root = tmp_path / "urllib3"
    for name, source in modules.items():
        path = root / f"{name}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    "source",
    [
        "from logging import getLogger\nlog = getLogger(__name__)\nlog.warning('Fetched %s', url)\n",
        "import logging\nlog: logging.Logger = logging.getLogger(__name__)\nlog.warning('Fetched %s', url)\n",
        "import logging\nclass C:\n    def __init__(self):\n        self.log = logging.getLogger(__name__)\n    def f(self, url):\n        self.log.warning('Fetched %s', url)\n",
        "import logging\nlogging.getLogger(__name__).warning('Fetched %s', url)\n",
        "import logging as lg\nlogger = lg.getLogger('urllib3.util.newmod')\nlogger.warning('Fetched %s', url)\n",
    ],
    ids=["from-import", "annotated", "self attribute", "chained", "aliased module"],
)
def test_the_reading_finds_a_logger_however_it_is_bound(tmp_path, source):
    """The first reading matched ``name = x.getLogger(...)`` and nothing else, so a new module that bound its logger another way was invisible
    to both qualification tests and unfiltered at run time."""
    reading = _read_library(_fake_library(tmp_path, **{"util/newmod": source}))
    assert reading.loggers == {"urllib3.util.newmod"}
    assert list(reading.calls) == [("urllib3.util.newmod", "Fetched %s")]
    assert reading.unclassified == []


@pytest.mark.parametrize(
    ("source", "what"),
    [
        ("import logging\nlogging.warning('Fetched %s', url)\n", "not bound from getLogger"),
        ("import logging\nlog = logging.getLogger(__name__)\nlog.warning(message, url)\n", "not a text constant"),
        ("import logging\nlog = logging.getLogger(__name__)\nlog.warning(f'Fetched {url}')\n", "not a text constant"),
        ("import logging\nconfigure(logging.getLogger(__name__))\n", "never binds it"),
        ("import logging\nlog = logging.getLogger(__name__)\nother = make()\nother.logger.warning('x %s', url)\n", "not bound from getLogger"),
        ("import logging\nlog = logging.getLogger()\nlog.debug('Retry: %s', url)\n", "does not name the module's own logger"),
        ("import logging\nlog = logging.getLogger('requests.packages.urllib3')\nlog.debug('Retry: %s', url)\n", "does not name the module's own logger"),
        ("import logging\nlog = logging.getLogger(NAME)\nlog.debug('Retry: %s', url)\n", "does not name the module's own logger"),
        ("import logging\nlog = logging.getLogger(__name__)\nfoo, chan = 1, logging.getLogger(__name__)\nchan.warning('Leak %s', url)\n", "cannot follow"),
        ("import logging\nlog = logging.getLogger(__name__)\n(chan := logging.getLogger(__name__)).warning('Leak %s', url)\n", "cannot follow"),
    ],
    ids=[
        "root logger",
        "variable message",
        "f-string message",
        "unbound logger",
        "unbound attribute logger",
        "getLogger() with no name",
        "a name outside urllib3",
        "a name held in a variable",
        "second logger bound by unpacking",
        "second logger bound by walrus",
    ],
)
def test_the_reading_names_what_it_cannot_attribute(tmp_path, source, what):
    reading = _read_library(_fake_library(tmp_path, **{"util/newmod": source}))
    assert any(what in line for line in reading.unclassified), reading.unclassified


def test_two_calls_with_one_template_are_both_compared(tmp_path):
    """The reading keyed calls by (module, template) in a dict, so a second call with the same template overwrote the first and an earlier call
    with another argument was invisible."""
    source = "import logging\nlog = logging.getLogger(__name__)\nlog.debug('Retry: %s', other)\nlog.debug('Retry: %s', url)\n"
    reading = _read_library(_fake_library(tmp_path, **{"connectionpool": source}))
    assert reading.calls[("urllib3.connectionpool", "Retry: %s")] == [(("other",), ()), (("url",), ())]
    new, gone, changed = _against_the_table(reading)
    assert ("urllib3.connectionpool", "Retry: %s") in changed


def test_a_keyword_the_library_adds_to_a_known_call_is_a_change(tmp_path):
    """``extra=`` puts attributes on the record, ``exc_info=`` an exception: neither is an argument, and neither was compared."""
    source = "import logging\nlog = logging.getLogger(__name__)\nlog.debug('Retry: %s', url, extra={'target': url})\n"
    reading = _read_library(_fake_library(tmp_path, **{"connectionpool": source}))
    assert reading.calls[("urllib3.connectionpool", "Retry: %s")] == [(("url",), ("extra={'target': url}",))]
    assert ("urllib3.connectionpool", "Retry: %s") in _against_the_table(reading)[2]


def test_each_entry_of_the_table_names_the_keywords_the_library_passes():
    """Today's keywords are the ``exc_info=True`` of the header-parsing warning (the exception is dropped) and the retry warning's ``extra``
    (an attribute with the host, which is dropped too); the qualification compares them like the arguments."""
    with_keywords = {k: v.kwargs for k, v in urllib3_log.SHAPES.items() if v.kwargs}
    assert with_keywords == {
        ("urllib3.connection", "Failed to parse headers (url=%s): %s"): ("exc_info=True",),
        ("urllib3.connectionpool", "Retrying (%r) after connection broken by '%r': %s"): ("extra={'__urllib3-retry-warning': {'host': self.host}}",),
    }


#: Which positions of which call carry a request target, written out a second time on purpose: the qualification above proves the table
#: names the library's own arguments, but WHICH of them are addresses is a judgement the source cannot make, and a test that read its
#: expectation from the table would pass when a position was dropped from it.
_EXPECTED_TARGETS = {
    ("urllib3.connection", "Failed to parse headers (url=%s): %s"): (0,),
    ("urllib3.connectionpool", '%s://%s:%s "%s %s %s" %s %s'): (4,),
    ("urllib3.connectionpool", "Retrying (%r) after connection broken by '%r': %s"): (2,),
    ("urllib3.connectionpool", "Redirecting %s -> %s"): (0, 1),
    ("urllib3.connectionpool", "Retry: %s"): (0,),
    ("urllib3.poolmanager", "Redirecting %s -> %s"): (0, 1),
    ("urllib3.util.retry", "Incremented Retry for (url='%s'): %r"): (0,),
}


def test_the_positions_that_carry_a_target_are_the_ones_written_out_here():
    assert {k: v.target for k, v in urllib3_log.SHAPES.items() if v.target} == _EXPECTED_TARGETS


def test_each_entry_of_the_table_has_as_many_arguments_as_its_template_has_conversions_and_its_targets_are_among_them():
    for key, shape in urllib3_log.SHAPES.items():
        assert all(0 <= i < len(shape.args) for i in shape.target), key
        assert len(shape.args) == len(re.findall(r"%[-#0 +]*\d*(?:\.\d+)?[sdr]", key[1])), key


def test_the_installed_urllib3_is_inside_the_range_pyproject_qualifies():
    import urllib3

    from src.maintenance import registry as R

    m = re.search(r'"urllib3>=([0-9.]+),<([0-9.]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert m, "pyproject.toml's urllib3 requirement lost its floor or its ceiling (see the comment above it)"
    assert R._ver_ge(urllib3.__version__, m.group(1)) and not R._ver_ge(urllib3.__version__, m.group(2)), (
        f"urllib3 {urllib3.__version__} is outside {m.group(1)} to below {m.group(2)}, the releases this table was read from"
    )
