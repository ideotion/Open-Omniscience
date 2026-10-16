"""Keep the path and the query of a request out of the HTTP library's own log lines (R142).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``urllib3`` (under every ``requests`` session) logs, on its own loggers, lines that carry the request target. At WARNING, with the
default log level: ``Failed to parse headers (url=...)`` when a response has a malformed header line, on a fetch that SUCCEEDS as well as
on one that fails, and ``Retrying (...) after connection broken by ...: <target>`` for a session that retries. At DEBUG: the request line,
each redirect hop and each retry. The target of a signed storage download carries its signature in the query, a feed or an API fetch can
carry a key, and a debug bundle carries the error journal these lines land in. This app logs none of them itself and does not turn those
loggers to DEBUG; the one place to cut the target is the library's own logger, before any handler sees the record.

The filter rewrites a positional argument of such a record that is a request target (``/path?query``) or an absolute address with a path,
a query or a fragment: the target becomes ``[path withheld]`` and the address keeps its scheme, host and port and loses userinfo, path,
query and fragment. What it does NOT do, stated so nobody reads more into it: it knows the shapes ``urllib3`` 2.8.0 logs (a target as a
whole argument), so a release that formats the target INTO a longer string would not be covered, and the tests in
``tests/test_urllib3_log_withholds_the_path.py`` drive the real library to show which shapes are; and it rewrites the ARGUMENTS only, so
an exception the library attaches to a record (``exc_info``) is untouched (the ones logged today carry the server's header text, not the
address).
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

#: The ``urllib3`` loggers whose records can carry a request target (grep ``log.`` over ``urllib3`` 2.8.0): the connection (the header
#: warning), the pool (the request line, the redirect, the retry), the pool manager (a redirect) and the retry object (its increment).
LOGGERS = ("urllib3.connection", "urllib3.connectionpool", "urllib3.poolmanager", "urllib3.util.retry")

#: What stands where a path and a query were.
WITHHELD = "[path withheld]"


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


class _WithholdRequestPath(logging.Filter):
    """Rewrites the target arguments of a record before any handler sees it; never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and args:
            record.args = tuple(withhold(a) for a in args)
        return True


def install() -> None:
    """Put the filter on each logger of :data:`LOGGERS`, once. A filter on a logger sees the records that logger CREATES, which is every
    record ``urllib3`` makes on these names, whatever handler (console, file, error journal) later receives it."""
    for name in LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, _WithholdRequestPath) for f in logger.filters):
            logger.addFilter(_WithholdRequestPath())


install()
