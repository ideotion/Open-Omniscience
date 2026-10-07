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
``(no route matched)``, and no query. A record that is not the five-part line the server writes is replaced by a fixed text.
"""

from __future__ import annotations

import logging
from copy import copy
from urllib.parse import unquote

from starlette.routing import Match
from uvicorn.logging import AccessFormatter as _AccessFormatter

from src.monitoring.request_label import UNMATCHED_ROUTE, safe_method

#: What replaces a record that is not the server's five-part access line.
ACCESS_LINE_WITHHELD = "access line withheld: its shape is not the server's"


def _route_of(path: str, method: str) -> str:
    """The template of the app's route that ``path`` matches (a full match first, else a partial one, as the router itself
    chooses), or :data:`UNMATCHED_ROUTE`. Never raises."""
    try:
        # the app owns the routes; imported when the first line is written, long after it exists
        from src.api.main import app

        scope = {"type": "http", "path": unquote(path), "method": method, "root_path": "", "headers": []}
        partial = None
        for route in app.routes:
            match, _ = route.matches(scope)
            if match == Match.FULL:
                return str(getattr(route, "path", ""))
            if match == Match.PARTIAL and partial is None:
                partial = str(getattr(route, "path", ""))
        return partial or UNMATCHED_ROUTE
    except Exception:  # noqa: BLE001 - a log filter must never break the request it describes
        return UNMATCHED_ROUTE


class AccessLineFilter(logging.Filter):
    """Rewrites the server's access record to name the request by a standard method and its route template, with no query."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        try:
            args = record.args
            if isinstance(args, tuple) and len(args) == 5:
                client, method, full_path, version, status = args
                standard = safe_method(method)
                route = _route_of(str(full_path).split("?", 1)[0], standard) if isinstance(full_path, str) else UNMATCHED_ROUTE
                record.args = (client, standard, route, version, status)
            else:
                record.msg, record.args = ACCESS_LINE_WITHHELD, ()
        except Exception:  # noqa: BLE001 - a record that cannot be rewritten is written as a fixed line
            record.msg, record.args = ACCESS_LINE_WITHHELD, ()
        return True


def install_access_line_filter() -> AccessLineFilter:
    """Put one :class:`AccessLineFilter` on the ``uvicorn.access`` logger (a second call adds none) and return it."""
    log = logging.getLogger("uvicorn.access")
    for existing in log.filters:
        if isinstance(existing, AccessLineFilter):
            return existing
    found = AccessLineFilter()
    log.addFilter(found)
    return found


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
