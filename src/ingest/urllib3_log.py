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
release adds), in the log-record factory, so a name the table does not list is withheld whole instead of passing. THE FACTORY'S LIMIT: it
runs inside ``Logger.makeRecord`` BEFORE that method copies ``extra=`` onto the record, and a record that propagates up from a child never
meets the parent's filter, so for a logger outside :data:`LOGGERS` the message, the arguments and the traces are scrubbed and an ``extra``
attribute is not. No release logs on such a logger with ``extra=`` (all nine loggers are listed, and the one ``extra`` goes to a filtered
logger); the qualification test fails BY NAME on a logger it does not list, which is what makes the first such release visible. Both are installed when
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
from typing import Any, NamedTuple, cast
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
#: status, a version string, a ``Retry`` or an exception, and :func:`_carried` keeps it only as a plain token or a number and reduces an
#: object to its class name, so a position that starts to carry something else cannot quote the target.
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
    if type(arg) is not str:  # a subclass can say anything from its own methods, so it is not read as text
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
    if type(arg) is str and arg[:8].lower().startswith(("http://", "https://")):
        return withhold(arg)
    return WITHHELD


#: What a text argument that is not a request target may be made of and be kept: a host name or an address, a port, a method, a version
#: (``HTTP/1.1``), a logger name, and the ``<ClassName>`` this module writes for an object (so a second pass leaves it). The host of a connection comes from a server's ``Location`` and urllib3 accepts ``;``, ``,`` and ``=`` in it
#: (``localhost;x-amz-signature=...``), so a text with one of those, or a space or a query mark, is a value and not a name.
_PLAIN = re.compile(r"[A-Za-z0-9._:%\[\]-]*|HTTP/[0-9.]+|<[A-Za-z_][A-Za-z0-9_]*>")


def _class_name(cls: type) -> str:
    """The name of ``cls`` as the type itself holds it: a metaclass that answers ``__name__`` with other text (or with a non-text) is not read."""
    name = type.__dict__["__name__"].__get__(cls)
    return name if type(name) is str and name.isidentifier() else "object"


def _carried(arg: object) -> object:
    """What stands for an argument that is NOT a request target: a number or ``None`` as it was, a text cut the way :func:`withhold` cuts it and
    kept only when it is a plain token (see :data:`_PLAIN`; an address keeps its origin), and anything else (an exception, a ``Retry``, a
    mapping, a list, an instance of a subclass of ``str``) as ``<ClassName>``; a subclass of ``int`` or ``float`` keeps its value as a plain number. The text of such an object is the library's or the
    server's (``HeaderParsingError`` quotes the header lines the server sent after its first malformed one), so it is not read."""
    if arg is None or type(arg) in (bool, int, float):
        return arg
    if issubclass(type(arg), int):  # an ``int`` that answers ``str()`` with other text: its value, as a plain number (``%d`` still formats it)
        return int.__int__(cast(int, arg))
    if issubclass(type(arg), float):
        return float.__float__(cast(float, arg))
    if type(arg) is str:
        cut = withhold(arg)
        if cut != arg or arg[:8].lower().startswith(("http://", "https://")) or _PLAIN.fullmatch(arg):
            return cut
        return WITHHELD
    return f"<{_class_name(type(arg))}>"


def _is_withheld_message(msg: object) -> bool:
    """Whether ``msg`` is what :func:`_withhold_whole` writes when the record carried an exception: the fixed sentence and the exception's
    class name in brackets. (The sentence alone is what a second pass writes again, so it needs no case.)"""
    if type(msg) is not str:
        return False
    head = UNRECOGNISED + " ("
    return msg.startswith(head) and msg.endswith(")") and msg[len(head) : -1].isidentifier()


#: The attributes a ``LogRecord`` has of its own. Anything else on a record of these loggers came from ``extra=`` or from a log-record
#: factory, or is the ``message`` / ``asctime`` a formatter cached before this ran, and is a carrier too. (A formatter writes ``message`` and
#: ``asctime`` again when it formats, so replacing them costs nothing.)
_STANDARD = frozenset(vars(logging.LogRecord("n", 0, "p", 0, "m", (), None)))


def _drop_traces(record: logging.LogRecord) -> None:
    """Drop the exception, its cached text and the stack, and replace the value of every attribute the record does not have of its own. The
    attribute stays, with :data:`WITHHELD` as its value, because a format string that names one (a trace id another library's factory adds)
    would otherwise fail in the handler and the record would not be written."""
    record.exc_info = None
    record.exc_text = None
    record.stack_info = None
    for key in [k for k in vars(record) if k not in _STANDARD]:
        setattr(record, key, WITHHELD)


def _withhold_whole(record: logging.LogRecord) -> None:
    """Replace the record's message with :data:`UNRECOGNISED`, keeping its logger and level, and the class name of the exception it carried."""
    info = record.exc_info
    caught = info[0] if isinstance(info, tuple) and info else None
    named = _class_name(caught) if isinstance(caught, type) else None
    if not _is_withheld_message(record.msg):  # a second pass over the same record keeps what the first one left
        record.msg = f"{UNRECOGNISED} ({named})" if named else UNRECOGNISED
    record.args = ()
    _drop_traces(record)


def scrub(record: logging.LogRecord) -> None:
    """Make ``record`` safe to hand to any handler: its target arguments cut, its other arguments reduced, its exception and stack dropped; or
    its message withheld whole when the shape is not one of :data:`SHAPES`, or when anything here raised. Idempotent."""
    try:
        shape = SHAPES.get((record.name, record.msg)) if type(record.msg) is str else None
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
            setattr(record, key, WITHHELD)


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
