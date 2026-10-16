"""Keep the path and the query of a request out of the HTTP library's own log lines, and withhold any line it does not recognise (R142).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``urllib3`` (under every ``requests`` session) logs, on its own loggers, lines that carry the request target. At WARNING, with the
default log level: ``Failed to parse headers (url=...)`` when a response has a malformed header line, on a fetch that SUCCEEDS as well as
on one that fails, and ``Retrying (...) after connection broken by ...: <target>`` for a session that retries. At DEBUG: the request line,
each redirect hop and each retry. The target of a signed storage download carries its signature in the query, a feed or an API fetch can
carry a key, and a debug bundle carries the error journal these lines land in. This app logs none of them itself and does not turn those
loggers to DEBUG; the one place to cut the target is the library's own logger, before any handler sees the record.

THE FILTER IS DEFAULT-DENY. :data:`SHAPES` lists, for each logger the library defines, every log call it makes in the releases this app is
qualified for (the ``urllib3`` range in ``pyproject.toml``): the message template, the source text of each argument, and which argument
positions carry a request target. A record that matches an entry has its target positions rewritten (``/path?query`` becomes
``[path withheld]``; an absolute address keeps its scheme, host and port and loses userinfo, path, query and fragment) and everything else
passes. A record that matches NO entry (a template this build does not know, a different number of arguments, a message that is not text)
has its message withheld whole: the logger and the level stay, the arguments and any traceback go, and the name of the exception class,
when there was one, is kept. The record is never dropped.

What keeps the table true is ``tests/test_urllib3_log_withholds_the_path.py``: it reads the installed library's source and fails, by name,
on a log call that is not in the table, a changed argument, a table entry the library no longer has, or a logger this module does not
cover, so a release that changes what it logs cannot be installed unnoticed (the pyproject ceiling is the first release not read, and
``configs/external_artifacts.yml`` records it). What it does NOT do, stated so nobody reads more into it: it covers the loggers listed in
:data:`LOGGERS` and not a child logger someone creates under them; and the traceback of a KNOWN shape (the header-parsing warning logs the
defect it caught) is left as the library logs it, because that is the server's header text and not the address.
"""

from __future__ import annotations

import logging
from typing import NamedTuple
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
    """One log call of the library: the source text of each argument, and the positions among them that carry a request target."""

    args: tuple[str, ...]
    target: tuple[int, ...] = ()


#: ``(logger, message template)`` to what the library passes. The ``args`` are the library's own source expressions, compared against the
#: installed release by the qualification test, so an argument that starts to carry something else is found there and not here. A position
#: is a ``target`` when it can be a path, a query or an address (rewritten); every other position is a host, a port, a count, a method, a
#: status, a version string, a ``Retry`` or an exception, measured by the same test not to quote the target.
SHAPES: dict[tuple[str, str], Shape] = {
    ("urllib3", "Added a stderr logging handler to logger: %s"): Shape(("__name__",)),
    ("urllib3.connection", "Certificate did not match expected hostname: %s. Certificate: %s"): Shape(("asserted_hostname", "cert")),
    ("urllib3.connection", "Failed to parse headers (url=%s): %s"): Shape(("_url_from_connection(self, resp_options.request_url)", "hpe"), (0,)),
    ("urllib3.connectionpool", "Starting new HTTP connection (%d): %s:%s"): Shape(("self.num_connections", "self.host", "self.port or '80'")),
    ("urllib3.connectionpool", "Starting new HTTPS connection (%d): %s:%s"): Shape(("self.num_connections", "self.host", "self.port or '443'")),
    ("urllib3.connectionpool", '%s://%s:%s "%s %s %s" %s %s'): Shape(
        ("self.scheme", "self.host", "self.port", "method", "url", "response.version_string", "response.status", "response.length_remaining"), (4,)
    ),
    ("urllib3.connectionpool", "Resetting dropped connection: %s"): Shape(("self.host",)),
    ("urllib3.connectionpool", "Retrying (%r) after connection broken by '%r': %s"): Shape(("retries", "err", "url"), (2,)),
    ("urllib3.connectionpool", "Redirecting %s -> %s"): Shape(("url", "redirect_location"), (0, 1)),
    ("urllib3.connectionpool", "Retry: %s"): Shape(("url",), (0,)),
    ("urllib3.connectionpool", "Connection pool is full, discarding connection: %s. Connection pool size: %s"): Shape(("self.host", "self.pool.qsize()")),
    ("urllib3.contrib.pyopenssl", "A problem was encountered with the certificate that prevented urllib3 from finding the SubjectAlternativeName field. This can affect certificate validation. The error was %s"): Shape(("e",)),
    ("urllib3.poolmanager", "Redirecting %s -> %s"): Shape(("url", "redirect_location"), (0, 1)),
    ("urllib3.response", "Received response with both Content-Length and Transfer-Encoding set. This is expressly forbidden by RFC 7230 sec 3.3.2. Ignoring Content-Length and attempting to process response as Transfer-Encoding: chunked."): Shape(()),
    ("urllib3.util.retry", "Converted retries value: %r -> %r"): Shape(("retries", "new_retries")),
    ("urllib3.util.retry", "Incremented Retry for (url='%s'): %r"): Shape(("url", "new_retry"), (0,)),
}


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


def _is_withheld_message(msg: object) -> bool:
    """Whether ``msg`` is exactly what :func:`_withhold_whole` writes: the fixed sentence, alone or with one identifier in brackets."""
    if not isinstance(msg, str):
        return False
    if msg == UNRECOGNISED:
        return True
    head = UNRECOGNISED + " ("
    return msg.startswith(head) and msg.endswith(")") and msg[len(head) : -1].isidentifier()


def _withhold_whole(record: logging.LogRecord) -> None:
    """Replace the record's message with :data:`UNRECOGNISED`, keeping its logger and level, and the class name of the exception it carried."""
    caught = record.exc_info[0] if isinstance(record.exc_info, tuple) and record.exc_info else None
    named = getattr(caught, "__name__", None)
    if not _is_withheld_message(record.msg):  # a second pass over the same record keeps what the first one left
        record.msg = f"{UNRECOGNISED} ({named})" if isinstance(named, str) else UNRECOGNISED
    record.args = ()
    record.exc_info = None
    record.exc_text = None
    record.stack_info = None


class _WithholdRequestPath(logging.Filter):
    """Rewrites the target arguments of a known record, and withholds an unknown one whole, before any handler sees it; never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        shape = SHAPES.get((record.name, record.msg)) if isinstance(record.msg, str) else None
        args = record.args
        if shape is None or not isinstance(args, tuple) or len(args) != len(shape.args):
            _withhold_whole(record)
            return True
        if shape.target:
            record.args = tuple(_target(a) if i in shape.target else a for i, a in enumerate(args))
        return True


def install() -> None:
    """Put the filter on each logger of :data:`LOGGERS`, once. A filter on a logger sees the records that logger CREATES, which is every
    record ``urllib3`` makes on these names, whatever handler (console, file, error journal) later receives it."""
    for name in LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, _WithholdRequestPath) for f in logger.filters):
            logger.addFilter(_WithholdRequestPath())


install()
