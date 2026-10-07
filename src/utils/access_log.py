"""
The server's access-log line, for a record that is no longer the five-part one the server writes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``uvicorn.logging.AccessFormatter`` unpacks exactly five arguments from every record it formats: the client, the method, the path,
the HTTP version and the status. The passphrase filter in front of the access handler (``secret_scrub.SecretFilter``, put there
by ``logging_config.uvicorn_log_config``) hands the formatter a record with NO arguments when it withheld the line (the process
holds a passphrase under the floor of what can be taken out of a text, and the line contains it: ``abc`` in
``GET /api/search?q=abc``) or rewrote it as one text (a passphrase that the template and an argument write between them). The
server's formatter then raised ``ValueError: not enough values to unpack`` for every such request, which the logging module
printed as ``--- Logging error ---`` with a call stack on ``stderr``, and no access line was written at all.

This formatter formats the five-part record exactly as the server's own does, and any other record as its text, behind the
level prefix the server's own formats begin with. It adds no word to a line and takes none out: what the filter decided to
write is what is written.

THE LINE ITSELF NAMES THE REQUEST, AND THE REQUEST IS WHAT THE CLIENT TYPED (2026-10-07). The server writes ``GET /api/x?q=<anything>``
with the path and the query as they came, and the lines of a console go to journald, ``docker logs`` and a launcher's redirect, none
of which the app can keep them out of; a LOCKED app holds no passphrase for the filter to take out, and one typed into the address bar
is a path. So :class:`AccessLineFilter`, attached to the ``uvicorn.access`` logger by the app itself (the logger is the one that makes
the record, so it holds however the server is started: the command line, ``uvicorn.run``, a ``--log-config``), rewrites the record
before any handler sees it: a standard method or ``(other method)``, the route TEMPLATE the path matches among the app's routes or
``(no route matched)``, and no query. A record that is not the five-part line the server writes is replaced by a fixed text, with its exception, stack and extra fields dropped. The client is written only when it parses as an address (behind a trusted proxy ``X-Forwarded-For`` is free text). A WebSocket upgrade is written by the server on ``uvicorn.error`` with the client and the full path and query; :class:`WebSocketLineFilter` labels those three lines the same way, and the app runs the server with ``ws="none"``, so no upgrade is answered but a plain 403 with no such line.
"""

from __future__ import annotations

import logging
from copy import copy
from typing import Any
from urllib.parse import unquote

from starlette.routing import Match
from uvicorn.logging import AccessFormatter as _AccessFormatter

from src.monitoring.request_label import UNMATCHED_ROUTE, safe_client, safe_method

#: What replaces a record that is not the server's five-part access line.
ACCESS_LINE_WITHHELD = "access line withheld: its shape is not the server's"


def _route_contexts(routes: Any) -> list[Any]:
    """The app's routes as the router matches them. FastAPI from 0.138 keeps an included router as one object that has no ``.path``
    (its routes are reached through ``fastapi.routing.iter_route_contexts``, each with its EFFECTIVE path, prefixes included); an
    older FastAPI keeps a flat list that carries the path itself."""
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        return list(routes)
    return list(iter_route_contexts(routes))


def _route_of(path: str, method: str, app: Any = None) -> str:
    """The template of the app's route that ``path`` matches (a full match first, else a partial one, as the router itself
    chooses), or :data:`UNMATCHED_ROUTE`; never an empty text. ``app`` is the app whose routes are read (the app of this process
    when none is given). Never raises."""
    try:
        if app is None:
            # the app owns the routes; imported when the first line is written, long after it exists
            from src.api.main import app as the_app

            app = the_app
        scope = {"type": "http", "path": unquote(path), "method": method, "root_path": "", "headers": []}
        partial = None
        for route in _route_contexts(app.routes):
            match, _ = route.matches(scope)
            template = str(getattr(route, "path", "") or "")
            if match == Match.FULL and template:
                return template
            if match == Match.PARTIAL and template and partial is None:
                partial = template
        return partial or UNMATCHED_ROUTE
    except Exception:  # noqa: BLE001 - a log filter must never break the request it describes
        return UNMATCHED_ROUTE


#: The record attributes the logging module makes itself: whatever else a record carries was put there by the caller.
_STANDARD_ATTRIBUTES = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


def _withhold(record: logging.LogRecord, text: str) -> None:
    """Replace what a record says by ``text``, and drop what it carries beside it (an exception, a stack, every extra field), any of
    which can hold the typed text the fixed line replaces."""
    record.msg, record.args = text, ()
    record.exc_info = record.exc_text = record.stack_info = None
    for name in [n for n in vars(record) if n not in _STANDARD_ATTRIBUTES]:
        delattr(record, name)


class AccessLineFilter(logging.Filter):
    """Rewrites the server's access record to name the request by a standard method and its route template, with no query, and
    the client by its address or a fixed word (:func:`safe_client`). ``app`` is the app whose routes are read: none means the app of
    this process (a test hands in a small one)."""

    def __init__(self, app: Any = None) -> None:
        super().__init__()
        self.app = app

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        try:
            args = record.args
            if isinstance(args, tuple) and len(args) == 5:
                client, method, full_path, version, status = args
                standard = safe_method(method)
                route = _route_of(str(full_path).split("?", 1)[0], standard, self.app) if isinstance(full_path, str) else UNMATCHED_ROUTE
                record.args = (safe_client(client), standard, route, version, status)
            else:
                _withhold(record, ACCESS_LINE_WITHHELD)
        except Exception:  # noqa: BLE001 - a record that cannot be rewritten is written as a fixed line
            _withhold(record, ACCESS_LINE_WITHHELD)
        return True


#: The three lines the server writes for a WebSocket upgrade, on ``uvicorn.error`` at INFO, each with the client and the FULL path
#: and query the client typed: accepted, refused with 403, and closed with a code.
_WEBSOCKET_FORMATS = ('%s - "WebSocket %s" [accepted]', '%s - "WebSocket %s" 403', '%s - "WebSocket %s" %d')
#: What a WebSocket line names instead of the path: this app serves no WebSocket route, so none is ever matched.
WEBSOCKET_ROUTE = UNMATCHED_ROUTE


class WebSocketLineFilter(logging.Filter):
    """Labels the server's WebSocket lines as the access line is: the client by :func:`safe_client`, the path by
    :data:`WEBSOCKET_ROUTE`; every other record of the logger passes unchanged."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        try:
            if record.msg in _WEBSOCKET_FORMATS and isinstance(record.args, tuple) and len(record.args) in (2, 3):
                client, _path, *rest = record.args
                code = rest[0] if rest and isinstance(rest[0], int) and not isinstance(rest[0], bool) else 0
                record.args = (safe_client(client), WEBSOCKET_ROUTE, *([code] if rest else []))
        except Exception:  # noqa: BLE001 - a record that cannot be rewritten is written as a fixed line
            _withhold(record, ACCESS_LINE_WITHHELD)
        return True


def _install(logger_name: str, kind: type[logging.Filter]) -> Any:
    log = logging.getLogger(logger_name)
    for existing in log.filters:
        if isinstance(existing, kind):
            return existing
    found = kind()
    log.addFilter(found)
    return found


def install_access_line_filter() -> AccessLineFilter:
    """Put one :class:`AccessLineFilter` on the ``uvicorn.access`` logger and one :class:`WebSocketLineFilter` on ``uvicorn.error``
    (a second call adds none) and return the first."""
    _install("uvicorn.error", WebSocketLineFilter)
    return _install("uvicorn.access", AccessLineFilter)  # type: ignore[no-any-return]


class AccessFormatter(_AccessFormatter):
    """The server's access formatter, which also writes a record that is not an access line (see the module docstring)."""

    #: How many arguments the server's formatter unpacks from a record's ``args``.
    _ACCESS_ARGUMENTS = 5

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802 - the name the logging module calls
        args = record.args
        if isinstance(args, tuple) and len(args) == self._ACCESS_ARGUMENTS:
            return super().formatMessage(record)
        recordcopy = copy(record)
        level = recordcopy.levelname
        if self.use_colors:
            level = self.color_level_name(level, recordcopy.levelno)
        # ``getMessage`` formats ``msg % args`` only when there are arguments, so a text that holds a ``%`` is written as it is.
        return f"{level}:{' ' * (8 - len(recordcopy.levelname))} {recordcopy.getMessage()}"
