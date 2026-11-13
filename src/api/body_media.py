"""Refuse a request body sent in an encoding its route does not read (R663; OPEN_QUEUE 2026-10-27 item 14, options 2 and 2b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FastAPI's strict JSON check (the third layer ``docs/SECURITY.md`` names) only guards a route that declares a required JSON body. The two
corpus-writing uploads read ``request.form()`` themselves and declare nothing, and the qualification merge declares only optional form
fields, so all three answered 200 to a POST with NO body or a ``text/plain`` one (measured 2026-10-27,
``audit-0.5.0/proposal-raw-body-content-type-2026-10-27.md``); the newsletter import then get-or-created its source row. The Origin layer
already refuses a cross-site POST, so this is depth, not a hole: each route now answers 415 to any media type it was not written to read,
before its handler runs (the uploads check before they read the form; for the merge FastAPI asks Starlette for the form first, which reads
nothing for a refused type). Every caller in the app sends ``FormData`` (multipart), so no button changes.

Stated limits: multipart and url-encoded are both "simple request" types a browser sends without a preflight, so against a cross-site POST
in those encodings the Origin layer stays the only guard: for the merge this removes only ``text/plain`` and the body-less POST (the
uploads lose url-encoded too). Any multipart POST,
EMPTY or carrying real files, still reaches all three handlers, and any url-encoded POST, empty included, still reaches the merge (which
then walks the whole corpus). The newsletter import still get-or-creates its fixed source row for an empty multipart POST, because its
tally shape comes from the store call that needs the row.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

MULTIPART = "multipart/form-data"
URLENCODED = "application/x-www-form-urlencoded"


def media_type(request: Request) -> str:
    """The request's media type, lower-cased, without parameters (``boundary=``, ``charset=``); empty when none was sent."""
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def require_media_type(request: Request, allowed: frozenset[str], what: str = "upload") -> None:
    """Answer 415 unless the body was sent as one of ``allowed``. Reads only the header, never the body; the detail is built from
    constants only, nothing the request sent is echoed."""
    if media_type(request) not in allowed:
        raise HTTPException(status_code=415, detail=f"send the {what} as " + " or ".join(sorted(allowed)))
