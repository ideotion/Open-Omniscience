"""Keep the path and the query of a request, and anything else a record carries, out of the HTTP library's own log lines (R142).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``urllib3`` (under every ``requests`` session) logs, on its own loggers, lines that carry the request target. At WARNING, with the
default log level: ``Failed to parse headers (url=...)`` when a response has a malformed header line, on a fetch that SUCCEEDS as well as
on one that fails, and ``Retrying (...) after connection broken by ...: <target>`` for a session that retries. At DEBUG: the request line,
each redirect hop and each retry. The target of a signed storage download carries its signature in the query, a feed or an API fetch can
carry a key, and a debug bundle carries the error journal these lines land in. This app logs none of them itself and does not turn those
loggers to DEBUG; the one place to cut the target is the library's own logger, before any handler sees the record.

A RECORD HAS FIVE CARRIERS, and the filter treats every one of them as untrusted (the first build cut the arguments that were text and
left the others, and the header-parsing warning leaked through an argument that was an exception and through ``exc_info``, both of which
carry what the SERVER sent after its first malformed line, a ``Location`` with its signature included): the message (``msg``), each
argument (whatever its type), the exception (``exc_info`` and the cached ``exc_text``) and the stack (``stack_info``).

THE FILTER IS DEFAULT-DENY. :data:`SHAPES` lists, for each logger the library defines, every log call it makes in the releases this app is
qualified for (the ``urllib3`` range in ``pyproject.toml``): the message template, the source text of each argument, and which argument
positions carry a request target. A record that matches an entry keeps its template and has its arguments rewritten one by one: a target
position becomes ``[path withheld]`` or, for an absolute address, its scheme, host and port; any other position keeps a number or ``None``,
has a text argument cut the same way, and is replaced by ``<ClassName>`` when it is anything else (an exception, a ``Retry``, a mapping,
a list: their text is the library's or the server's and is not read). The exception and the stack are dropped. A record that matches NO
entry (a template this build does not know, a different number of arguments, a message that is not text) has its message withheld whole:
the logger and the level stay, the arguments and any traceback go, and the name of the exception class, when there was one, is kept. If
anything in the filter raises, the record's message is withheld whole too. The record is never dropped, and a filter never raises into the
library's own log call.

WHERE IT RUNS. On each logger of :data:`LOGGERS` (a filter runs before any handler: console, file, the error journal) and, for the
records of any other logger under the ``urllib3`` name (the parent, a child someone adds under one of these names, a module a later
release adds), in the log-record factory, so a name the table does not list is withheld whole instead of passing. Both are installed when
this module is imported, which ``src/ingest/__init__.py`` does: a process that never imports ``src.ingest`` (a script that only imports
``requests``) has neither, and the library puts a ``NullHandler`` on its own logger, so it prints nothing there unless the script configures
logging itself.

What keeps the table true is ``tests/test_urllib3_log_withholds_the_path.py``: it reads the installed library's source and fails, by name,
on a log call that is not in the table, a changed argument, a table entry the library no longer has, or a logger this module does not
cover, so a release that changes what it logs cannot be installed unnoticed (the pyproject ceiling is the first release not read, and
``configs/external_artifacts.yml`` records it).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any, NamedTuple
from urllib.parse import urlsplit

#: Every logger ``urllib3`` defines: one ``logging.getLogger(__name__)`` per module that has one. The qualification test scans the installed
#: library and fails on a module with a logger that is not here, so a release that adds one is found before it ships.
LOGGERS = (
    "urllib3",
    "urllib3.connection",
    "urllib3.connectionpool",
    "urllib3.contrib.emscripten.response",
    "urllib3.contrib.pyopenssl",
    "urllib3.http2.connection",
    "urllib3.poolmanager",
    "urllib3.response",
    "urllib3.util.retry",
)

#: What stands where a path and a query were.
WITHHELD = "[path withheld]"

#: What stands where a whole record's message was, when its shape is not one this build knows.
UNRECOGNISED = "[urllib3 log line withheld: not a shape this build knows]"


class Shape(NamedTuple):
    """One log call of the library: the source text of each argument, the positions among them that carry a request target, and the source
    text of each keyword it passes in any release read (``exc_info=True``, ``extra=...``): the qualification test requires the keywords of a
    call to be among these."""

    args: tuple[str, ...]
    target: tuple[int, ...] = ()
    kwargs: tuple[str, ...] = ()


#: ``(logger, message template)`` to what the library passes. The ``args`` are the library's own source expressions, compared against the
#: installed release by the qualification test, so an argument that starts to carry something else is found there and not here. A position
#: is a ``target`` when it can be a path, a query or an address (rewritten); every other position is a host, a port, a count, a method, a
#: status, a version string, a ``Retry`` or an exception, measured by the same test not to quote the target.
SHAPES: dict[tuple[str, str], Shape] = {
    ("urllib3", "Added a stderr logging handler to logger: %s"): Shape(("__name__",)),
    ("urllib3.connection", "Certificate did not match expected hostname: %s. Certificate: %s"): Shape(("asserted_hostname", "cert")),
    ("urllib3.connection", "Failed to parse headers (url=%s): %s"): Shape(("_url_from_connection(self, resp_options.request_url)", "hpe"), (0,), ("exc_info=True",)),
    ("urllib3.connectionpool", "Starting new HTTP connection (%d): %s:%s"): Shape(("self.num_connections", "self.host", "self.port or '80'")),
    ("urllib3.connectionpool", "Starting new HTTPS connection (%d): %s:%s"): Shape(("self.num_connections", "self.host", "self.port or '443'")),
    ("urllib3.connectionpool", '%s://%s:%s "%s %s %s" %s %s'): Shape(
        ("self.scheme", "self.host", "self.port", "method", "url", "response.version_string", "response.status", "response.length_remaining"), (4,)
    ),
    ("urllib3.connectionpool", "Resetting dropped connection: %s"): Shape(("self.host",)),
    ("urllib3.connectionpool", "Retrying (%r) after connection broken by '%r': %s"): Shape(("retries", "err", "url"), (2,), ("extra={'__urllib3-retry-warning': {'host': self.host}}",)),
    ("urllib3.connectionpool", "Redirecting %s -> %s"): Shape(("url", "redirect_location"), (0, 1)),
    ("urllib3.connectionpool", "Retry: %s"): Shape(("url",), (0,)),
    ("urllib3.connectionpool", "Connection pool is full, discarding connection: %s. Connection pool size: %s"): Shape(("self.host", "self.pool.qsize()")),
    ("urllib3.contrib.pyopenssl", "A problem was encountered with the certificate that prevented urllib3 from finding the SubjectAlternativeName field. This can affect certificate validation. The error was %s"): Shape(("e",)),
    ("urllib3.poolmanager", "Redirecting %s -> %s"): Shape(("url", "redirect_location"), (0, 1)),
    ("urllib3.response", "Received response with both Content-Length and Transfer-Encoding set. This is expressly forbidden by RFC 7230 sec 3.3.2. Ignoring Content-Length and attempting to process response as Transfer-Encoding: chunked."): Shape(()),
    ("urllib3.util.retry", "Converted retries value: %r -> %r"): Shape(("retries", "new_retries")),
    ("urllib3.util.retry", "Incremented Retry for (url='%s'): %r"): Shape(("url", "new_retry"), (0,)),
}


#: What a host name or an address can be made of. Anything else in the "host" of an address (a ``;``, a ``,``, an ``=``) is not a host.
_HOST = re.compile(r"[A-Za-z0-9._:%-]+")


def withhold(arg: object) -> object:
    """``arg`` with a request target or an address's path and query replaced; anything else is returned as it was."""
    if not isinstance(arg, str):
        return arg
    if arg.startswith("/"):
        return WITHHELD
    if not arg[:8].lower().startswith(("http://", "https://")):
        return arg
    try:
        parts = urlsplit(arg)
        host = parts.hostname
        port = parts.port
    except ValueError:  # an address the library could not read either: nothing of it is worth keeping
        return WITHHELD
    if host and not _HOST.fullmatch(host):  # a host with a separator in it (``h.example;X-Amz-Signature=...``) is a value, not a name
        return WITHHELD
    shown = f"[{host}]" if host and ":" in host else (host or "")
    origin = f"{parts.scheme}://{shown}{f':{port}' if port else ''}"
    if parts.path in ("", "/") and not parts.query and not parts.fragment:
        return origin + parts.path
    return f"{origin}/{WITHHELD}"


def _target(arg: object) -> object:
    """What stands for an argument the library gives as a request target: an absolute address keeps its origin, and anything else (a path,
    a form this build has not seen, an object that is not text) is withheld whole."""
    if isinstance(arg, str) and arg[:8].lower().startswith(("http://", "https://")):
        return withhold(arg)
    return WITHHELD


def _carried(arg: object) -> object:
    """What stands for an argument that is NOT a request target: a number or ``None`` as it was, a text cut the way :func:`withhold` cuts it, and
    anything else (an exception, a ``Retry``, a mapping, a list) as ``<ClassName>``. The text of such an object is the library's or the
    server's (``HeaderParsingError`` quotes the header lines the server sent after its first malformed one), so it is not read."""
    if arg is None or isinstance(arg, (bool, int, float)):
        return arg
    if isinstance(arg, str):
        return withhold(arg)
    return f"<{type(arg).__name__}>"


def _is_withheld_message(msg: object) -> bool:
    """Whether ``msg`` is what :func:`_withhold_whole` writes when the record carried an exception: the fixed sentence and the exception's
    class name in brackets. (The sentence alone is what a second pass writes again, so it needs no case.)"""
    if not isinstance(msg, str):
        return False
    head = UNRECOGNISED + " ("
    return msg.startswith(head) and msg.endswith(")") and msg[len(head) : -1].isidentifier()


#: The attributes a ``LogRecord`` has of its own (and the two a formatter adds). Anything else on a record of these loggers came from ``extra=``
#: or from a log-record factory, and is a carrier too.
_STANDARD = frozenset(vars(logging.LogRecord("n", 0, "p", 0, "m", (), None))) | {"message", "asctime"}


def _drop_traces(record: logging.LogRecord) -> None:
    """Drop the exception, its cached text, the stack and every attribute the record does not have of its own."""
    record.exc_info = None
    record.exc_text = None
    record.stack_info = None
    for key in [k for k in vars(record) if k not in _STANDARD]:
        delattr(record, key)


def _withhold_whole(record: logging.LogRecord) -> None:
    """Replace the record's message with :data:`UNRECOGNISED`, keeping its logger and level, and the class name of the exception it carried."""
    caught = record.exc_info[0] if isinstance(record.exc_info, tuple) and record.exc_info else None
    named = getattr(caught, "__name__", None)
    if not _is_withheld_message(record.msg):  # a second pass over the same record keeps what the first one left
        record.msg = f"{UNRECOGNISED} ({named})" if isinstance(named, str) else UNRECOGNISED
    record.args = ()
    _drop_traces(record)


def scrub(record: logging.LogRecord) -> None:
    """Make ``record`` safe to hand to any handler: its target arguments cut, its other arguments reduced, its exception and stack dropped; or
    its message withheld whole when the shape is not one of :data:`SHAPES`, or when anything here raised. Idempotent."""
    try:
        shape = SHAPES.get((record.name, record.msg)) if isinstance(record.msg, str) else None
        args = record.args
        if shape is None or not isinstance(args, tuple) or len(args) != len(shape.args):
            _withhold_whole(record)
            return
        record.args = tuple(_target(a) if i in shape.target else _carried(a) for i, a in enumerate(args))
        _drop_traces(record)
    except Exception:  # fail closed: whatever the record carried, the message is withheld and the record still goes out
        record.msg = UNRECOGNISED
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        for key in [k for k in vars(record) if k not in _STANDARD]:
            delattr(record, key)


class _WithholdRequestPath(logging.Filter):
    """Scrubs every record of its logger before any handler sees it; never drops one."""

    def filter(self, record: logging.LogRecord) -> bool:
        scrub(record)
        return True


def _under_urllib3(name: object) -> bool:
    return isinstance(name, str) and (name == "urllib3" or name.startswith("urllib3."))


class _Factory:
    """The log-record factory with this module's scrub after it, for the records of ``urllib3`` and every logger under it. It covers the
    names the per-logger filters do not (a child someone adds, a module a later release adds); the filters stay because another library can
    replace the factory."""

    def __init__(self, inner: Callable[..., logging.LogRecord]) -> None:
        self.inner = inner

    def __call__(self, *args: Any, **kwargs: Any) -> logging.LogRecord:
        record = self.inner(*args, **kwargs)
        if _under_urllib3(record.name):
            scrub(record)
        return record


def install() -> None:
    """Put the filter on each logger of :data:`LOGGERS`, once, and the scrub in the log-record factory, once. A filter on a logger sees the
    records that logger CREATES, which is every record ``urllib3`` makes on these names, whatever handler (console, file, error journal) later
    receives it."""
    for name in LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, _WithholdRequestPath) for f in logger.filters):
            logger.addFilter(_WithholdRequestPath())
    current = logging.getLogRecordFactory()
    if not isinstance(current, _Factory):
        logging.setLogRecordFactory(_Factory(current))


install()
