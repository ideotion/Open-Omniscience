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
"""

from __future__ import annotations

import logging
from copy import copy

from uvicorn.logging import AccessFormatter as _AccessFormatter


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
