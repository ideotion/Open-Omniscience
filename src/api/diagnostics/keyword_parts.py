"""One file of a numbered set of keyword-log parts, by name (1 MB parts, 2026-10-01).

A NEW slice imported late, for the reason ``qualification_merge.py`` and ``country_codes.py`` give:
the split guard pins every earlier route's POSITION, so a route is added by a file imported at the
end, which appends entries and moves nothing. It sits just BEFORE ``release_run.py``, whose eight
routes ``test_release_run`` pins as the package's last. The set is BUILT by
``/keywords?format=parts`` (``keywords.py``); this serves what that listed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
import json
import os

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse

from src.analytics.keyword_log_export import PARTS_DIR_PREFIX

from ._base import router
from .keywords import _PARTS_SET_RE, _SET_LISTING, _parts_root

_KEYWORD_PARTS_GONE = (
    "no set of keyword-log files is kept on this machine (a newer export replaced it, the "
    "twelve-hour sweep removed it, or it was removed to make room for a build that did not "
    "finish): build it again with /api/diagnostics/keywords?format=parts"
)


@router.get("/keywords/parts/latest")
def keyword_parts_latest() -> JSONResponse:
    """The listing of the newest set still on disk (names, sizes, SHA-256), without rebuilding it:
    what the page's "Last keyword files, again" button reads. A set stays until the next build
    retires it or the sweep does, so this is the way to save the files a second time."""
    newest = None
    with contextlib.suppress(OSError):
        for d in _parts_root().iterdir():
            if d.name.startswith(PARTS_DIR_PREFIX) and (d / _SET_LISTING).is_file():
                built = (d / _SET_LISTING).stat().st_mtime
                if newest is None or built > newest[0]:
                    newest = (built, d)
    if newest is None:
        raise HTTPException(status_code=404, detail=_KEYWORD_PARTS_GONE)
    try:
        listing = json.loads((newest[1] / _SET_LISTING).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=_KEYWORD_PARTS_GONE) from exc
    return JSONResponse(listing)


@router.get("/keywords/parts/{set_id}/{name}")
def keyword_part_download(set_id: str, name: str) -> FileResponse:
    """One file of a set built by ``/keywords?format=parts``, by name. The set and the name are
    checked against the listing written when the set was built, so nothing outside it is
    reachable and a leftover file that merely sits in the folder is not served."""
    if not _PARTS_SET_RE.fullmatch(set_id):
        raise HTTPException(status_code=404, detail="not a set of keyword-log parts")
    d = _parts_root() / set_id
    try:
        listing = json.loads((d / _SET_LISTING).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=404,
            detail="that set is gone (a newer export replaced it, or it was removed to make room "
                   "for a build that did not finish): build it again with "
                   "/api/diagnostics/keywords?format=parts",
        ) from exc
    if name not in {f["name"] for f in listing["files"]}:
        raise HTTPException(status_code=404, detail=f"{name!r} is not a file of this set")
    path = d / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name!r} is missing from the set")
    # A download is use: the folder's age is what the next build's grace and the twelve-hour
    # sweep read, so a person still saving files an hour in is never cut off by either.
    with contextlib.suppress(OSError):
        os.utime(d)
    return FileResponse(str(path), media_type="application/zip", filename=name)
