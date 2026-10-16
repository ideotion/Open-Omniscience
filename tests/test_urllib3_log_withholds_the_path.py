"""R142: the HTTP library's own log lines do not carry a request's path or query, and a line this build does not recognise is withheld whole.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``urllib3`` logs a request's target on its own loggers: at WARNING, with the default log level, when a response has a malformed header line
("Failed to parse headers (url=...)", on a fetch that SUCCEEDS as well as on one that fails) and when a session retries; at DEBUG, the request
line and each redirect hop. The installer's download is a signed storage address, so its signature rode those lines into the error journal
that a debug bundle carries. ``src/ingest/urllib3_log.py`` rewrites the target arguments of the lines it knows before any handler sees them,
and withholds every other line on the library's loggers whole (default-deny).

Four groups of checks:

* the rewrite and the default, on records built by hand (each shape in the table, and the ways a record can fail to match it);
* the REAL library against a loopback socket: a scripted adapter stands in for urllib3 entirely and could never show a line the library
  writes itself. Each real-stack case also asserts that the library DID log the line (so the case cannot pass because it stayed quiet),
  that the host is still there (so the filter did not blank the record) and that no line fell to the default (so the table matches what the
  library really logs);
* the QUALIFICATION of the installed release: the table is compared with the library's own source, so a release that logs something new, or
  passes something else in an argument, fails here by name and is read before it is allowed (``pyproject.toml`` carries the ceiling);
* the objects the table leaves unchanged (a ``Retry``, an error) are measured not to quote the target.
"""

from __future__ import annotations

import ast
import logging
import re
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import requests
from requests.adapters import HTTPAdapter
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
        (f"https://[::1]:8443/x?y={SIG}", f"https://[::1]:8443/{urllib3_log.WITHHELD}"),
        (f"https://host.example:notaport/x?{SIG}", urllib3_log.WITHHELD),
        ("https://host.example", "https://host.example"),
        ("https://host.example/", "https://host.example/"),
        ("host.example:443", "host.example:443"),
        ("HTTP/1.1", "HTTP/1.1"),
        ("GET", "GET"),
        (200, 200),
        (None, None),
    ],
)
def test_withhold_keeps_the_scheme_host_and_port_and_loses_the_rest(arg, expected):
    assert urllib3_log.withhold(arg) == expected


def test_withhold_leaves_an_object_that_is_not_text_alone():
    exc = ConnectionError("Max retries exceeded")
    assert urllib3_log.withhold(exc) is exc


#: The shapes urllib3 logs a target in, as the library calls them (logger, level, template, arguments), so a shape that stops being covered
#: fails here by name; the real-stack cases below show that urllib3 still logs them this way, and the qualification cases that the table
#: is the library's own.
_SHAPES = [
    ("urllib3.connection", logging.WARNING, "Failed to parse headers (url=%s): %s", (f"http://h.example:80/p?sig={SIG}", "MissingHeaderBodySeparatorDefect")),
    ("urllib3.connectionpool", logging.WARNING, "Retrying (%r) after connection broken by '%r': %s", ("Retry(total=0)", "ProtocolError", f"/p?sig={SIG}")),
    ("urllib3.connectionpool", logging.DEBUG, '%s://%s:%s "%s %s %s" %s %s', ("https", "h.example", 443, "GET", f"/p?sig={SIG}", "HTTP/1.1", 200, 2)),
    ("urllib3.connectionpool", logging.DEBUG, "Redirecting %s -> %s", (f"/a?sig={SIG}", f"https://h.example/b?sig={SIG}")),
    ("urllib3.connectionpool", logging.DEBUG, "Retry: %s", (f"/p?sig={SIG}",)),
    ("urllib3.util.retry", logging.DEBUG, "Incremented Retry for (url='%s'): %r", (f"/p?sig={SIG}", "Retry(total=0)")),
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
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert "MISSING []" in out.stdout
    assert set(urllib3_log.LOGGERS) == set(names)


# --------------------------------------------------------------------------- the real library, a real socket


def test_a_response_with_a_malformed_header_logs_without_the_path_and_the_fetch_still_succeeds(caplog):
    """The reproduction of the read's finding B1, at the default level, on a SUCCESSFUL fetch."""
    caplog.set_level(logging.WARNING)
    port = _serve(_MALFORMED_HEADER)
    resp = requests.get(f"http://127.0.0.1:{port}/install.sh?sig={SIG}", timeout=10)
    assert resp.status_code == 200 and resp.content == b"ok"
    assert "Failed to parse headers" in caplog.text, "urllib3 must have logged the line, or this case proves nothing"
    assert f"127.0.0.1:{port}" in caplog.text
    assert SIG not in caplog.text
    assert "install.sh" not in caplog.text
    assert urllib3_log.UNRECOGNISED not in caplog.text, "the library's real line is a shape of the table"


def test_a_retry_logs_without_the_path(caplog):
    caplog.set_level(logging.DEBUG, logger="urllib3")
    port = _serve(None, _OK)
    session = requests.Session()
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
    resp = requests.get(f"http://127.0.0.1:{port}/install.sh?sig={SIG}", timeout=10)
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


def _installed_urllib3_calls() -> tuple[dict[tuple[str, str], tuple[str, ...]], set[str], list[str]]:
    """Read the INSTALLED ``urllib3``'s source: every ``log.<level>("template", args...)`` call as ``(logger, template) -> argument sources``,
    the modules that define a logger, and the calls this reading cannot classify (a first argument that is not a text constant)."""
    import urllib3

    root = Path(urllib3.__file__).resolve().parent
    calls: dict[tuple[str, str], tuple[str, ...]] = {}
    loggers: set[str] = set()
    unclassified: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).with_suffix("")
        module = ".".join(rel.parts[:-1] if rel.name == "__init__" else rel.parts)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            t.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and getattr(n.value.func, "attr", "") == "getLogger"
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        if names:
            loggers.add(module)
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id in names):
                continue
            if n.func.attr not in {"debug", "info", "warning", "error", "critical", "exception", "log"}:
                continue
            first = n.args[0] if n.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                calls[(module, first.value)] = tuple(ast.unparse(a) for a in n.args[1:])
            else:
                unclassified.append(f"{module}:{n.lineno}")
    return calls, loggers, unclassified


def test_every_log_call_of_the_installed_urllib3_is_a_shape_the_table_knows():
    """THE QUALIFICATION. A release that logs a new line, changes what a known line passes, or drops a line fails here, by name; read the
    release's change, extend the table, and only then lift the ``pyproject.toml`` ceiling (docs/maintenance/EXTERNAL_DEPENDENCIES.md)."""
    calls, _loggers, unclassified = _installed_urllib3_calls()
    assert unclassified == [], f"a log call whose message is not a text constant cannot be classified: {unclassified}"
    table = {k: v.args for k, v in urllib3_log.SHAPES.items()}
    new = sorted(set(calls) - set(table))
    gone = sorted(set(table) - set(calls))
    changed = sorted(k for k in set(calls) & set(table) if calls[k] != table[k])
    assert (new, gone, changed) == ([], [], []), f"new in the library: {new}; in the table only: {gone}; arguments changed: {changed}"


def test_every_logger_the_installed_urllib3_defines_is_covered():
    _calls, loggers, _unclassified = _installed_urllib3_calls()
    assert loggers == set(urllib3_log.LOGGERS), f"missing {sorted(loggers - set(urllib3_log.LOGGERS))}, extra {sorted(set(urllib3_log.LOGGERS) - loggers)}"


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


def test_the_objects_the_table_passes_unchanged_do_not_quote_the_target():
    """The positions that are not targets include a ``Retry`` (after an increment that was given the target) and an error. Measured here,
    not assumed: neither repr nor text of the objects urllib3 builds from a failed request quotes the address."""
    from urllib3.exceptions import ProtocolError, ReadTimeoutError

    target = f"/p?sig={SIG}"
    retry = Retry(total=3).increment(method="GET", url=target, error=ProtocolError("Connection aborted."))
    assert SIG not in repr(retry) and SIG not in str(retry)
    assert SIG not in repr(ReadTimeoutError(None, target, "Read timed out.")) and SIG not in str(ReadTimeoutError(None, target, "Read timed out."))
    assert SIG not in repr(ProtocolError("Connection aborted.")) and "sig" not in repr(Retry(total=3))
