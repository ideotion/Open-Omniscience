"""Refuse a request body sent in an encoding its route does not read (R663; OPEN_QUEUE 2026-10-27 item 14, options 2 and 2b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FastAPI's strict JSON check (the third layer ``docs/SECURITY.md`` names) only guards a route that declares a required JSON body. The two
corpus-writing uploads read ``request.form()`` themselves and declare nothing, and the qualification merge declares only optional form
fields, so all three answered 200 to a POST with NO body or a ``text/plain`` one (measured 2026-10-27,
``audit-0.5.0/proposal-raw-body-content-type-2026-10-27.md``); the newsletter import then get-or-created its source row. The Origin layer
already refuses a cross-site POST, so this is depth, not a hole: each route now answers 415 to any media type it was not written to read,
before it parses or writes anything. Every caller in the app sends ``FormData`` (multipart), so no button changes.

Stated limit: multipart is itself a "simple request" type a browser sends without a preflight, so the Origin layer stays the only guard
against a cross-site multipart POST; and an EMPTY multipart POST still reaches the handler (the newsletter import still get-or-creates its
fixed source row for it, because its tally shape comes from the store call that needs the row).
"""

from __future__ import annotations

from fastapi import HTTPException, Request

MULTIPART = "multipart/form-data"
URLENCODED = "application/x-www-form-urlencoded"


def media_type(request: Request) -> str:
    """The request's media type, lower-cased, without parameters (``boundary=``, ``charset=``); empty when none was sent."""
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def require_media_type(request: Request, allowed: frozenset[str]) -> None:
    """Answer 415 unless the body was sent as one of ``allowed``. Reads only the header, never the body."""
    if media_type(request) not in allowed:
        raise HTTPException(status_code=415, detail="send the upload as " + " or ".join(sorted(allowed)))
