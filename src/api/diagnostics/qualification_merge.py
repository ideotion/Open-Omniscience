"""The qualification-merge ACTION (B5, 2026-09-15; complements Q1106 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A NEW slice rather than a route appended to an existing one. The Q1139 split's guard pins
every route's POSITION, not just its presence, and the snapshot it compares against is the
pre-split table -- so the least disruptive way to add a route is a file imported LAST,
which appends one entry and moves nothing. ``country_codes.py`` set that precedent for the
same reason; this follows it.

The merge itself lives in ``src.catalog.qualification_merge``, shared verbatim with
``scripts/merge_source_qualification.py``. One implementation, two front doors: the four
refusals that decide what may ship to every fresh install are not something this project
wants two copies of.
"""

from __future__ import annotations

from fastapi import Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.database.session import get_db

from ._base import router

# How many uploads one merge run will read, and how big each may be. The ceiling on a
# single file is the shared one the bundle reader already enforces; the count is here
# because an endpoint, unlike a command line, is reachable without anybody typing the
# list out. Both are stated in the refusal, so a run that hits them says which.
_MAX_MERGE_UPLOADS = 25


@router.post("/source-qualification-merge")
def source_qualification_merge(
    files: list[UploadFile] = File(default=[]),
    accept_newest: bool = Form(default=False),
    include_this_instance: bool = Form(default=True),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """MERGE per-instance qualification exports into the shipped overlay -- B5's
    "automate the script run within the diagnostics" (2026-09-15), the run that until now
    meant ``python scripts/merge_source_qualification.py`` on the maintainer's machine.

    Same merge, literally: this and the script call one core
    (``src.catalog.qualification_merge``), so the four refusals hold identically here --
    a disagreement between instances is REPORTED and left alone rather than resolved, an
    inherited verdict is never counted as corroboration, ``qualified_at`` is never
    re-stamped, and an existing overlay row no export mentions is carried through
    untouched.

    ``include_this_instance`` is what makes it an action rather than an upload form: the
    running corpus's own export is merged in without exporting it first, so a
    single-instance operator gets the merged overlay in one click. Uploads are optional
    and mix freely with it.

    IT DOES NOT WRITE ``configs/source_qualification.yml``. The merged file comes back as
    text to review and commit -- the overlay stays operator-generated (brief S04-12 S2),
    and an endpoint that edited what the app ships to every install would be automating a
    decision that is nobody's to automate. LOCAL AND READ-ONLY besides: no network, and
    nothing in this corpus is judged, stamped or altered.

    PLAIN ``def`` -> threadpool, off the event loop. It was written ``async`` for
    ``await upload.read()`` and ``tests/test_handlers_off_the_event_loop`` refused it:
    ``build_overlay_export`` walks every source in the corpus, and on the single loop that
    freezes every other request (the guard records a measured 12.6 s handler turning a
    trivial poll into 41.7 s). The uploads are read through ``upload.file``, the
    ``SpooledTemporaryFile`` underneath, which is exactly what a threadpool handler should
    read synchronously -- so nothing is lost by not awaiting.
    """
    from src.catalog.qualification_export import build_overlay_export
    from src.catalog.qualification_merge import (
        MAX_MEMBER_BYTES,
        REFUSE_NOTHING,
        REFUSE_TOO_BIG,
        REFUSE_TOO_MANY,
        MergeInputError,
        existing_from_text,
        merge,
        refusal_payload,
        render,
        repair_record_flags,
        repair_record_flags_of_export_bytes,
        rows_from_bundle_bytes,
        rows_from_export_bytes,
    )
    from src.catalog.qualification_overlay import DEFAULT_OVERLAY_PATH

    # Every refusal is a 400 that says itself twice: ``detail`` in English, exactly as
    # before (and as the command line prints it), and ``detail_i18n`` / ``detail_vars``
    # for the panel, which writes it in the UI language with the file name kept as data
    # (the 2026-09-27 re-walk, S-6). Returned rather than raised: an ``HTTPException``
    # carries one ``detail``, and a caller reading it as a string keeps reading a string.
    def refuse(frame: str, **values: object) -> JSONResponse:
        return JSONResponse(status_code=400, content=refusal_payload(frame, **values))

    uploads = [f for f in (files or []) if f is not None and (f.filename or "").strip()]
    if len(uploads) > _MAX_MERGE_UPLOADS:
        return refuse(REFUSE_TOO_MANY, n=len(uploads), limit=_MAX_MERGE_UPLOADS)

    exports: list[list[dict]] = []
    # Which route each input took, recorded in the report. An operator reviewing a merged
    # overlay weeks later needs to know how many instances it rests on AND by which road;
    # an upload has no --from-bundle flag to remember, so the answer has to be written
    # down rather than inferred from what was clicked.
    inputs: list[dict] = []
    for upload in uploads:
        raw = upload.file.read()
        name = (upload.filename or "upload").strip()
        if len(raw) > MAX_MEMBER_BYTES:
            return refuse(REFUSE_TOO_BIG, file=name, size=len(raw), limit=MAX_MEMBER_BYTES)
        is_zip = raw[:4] == b"PK\x03\x04"
        try:
            rows = (
                rows_from_bundle_bytes(raw, name)
                if is_zip
                else rows_from_export_bytes(raw, name)
            )
        except MergeInputError as exc:
            # The core's refusal, verbatim, as a 400. Rewording it here would leave the
            # operator reading one explanation in the app and another on the command
            # line for the same file. Its frame travels beside it, so the app can say the
            # same refusal in the operator's language (re-walk S-6).
            return refuse(exc.i18n, **exc.vars)
        exports.append(rows)
        entry = {
            "name": name,
            "route": "all-diagnostics bundle" if is_zip else "export json",
            "verdicts": len(rows),
        }
        if not is_zip:
            entry.update(repair_record_flags_of_export_bytes(raw))
        inputs.append(entry)

    if include_this_instance:
        own_export = build_overlay_export(db)
        own = own_export["verdicts"]
        exports.append(own)
        inputs.append({
            "name": "this instance", "route": "measured here", "verdicts": len(own),
            **repair_record_flags(own_export.get("basis")),
        })

    if not exports:
        return refuse(REFUSE_NOTHING)

    existing_text = (
        DEFAULT_OVERLAY_PATH.read_text(encoding="utf-8")
        if DEFAULT_OVERLAY_PATH.exists() else ""
    )
    out = merge(exports, existing_from_text(existing_text), accept_newest=accept_newest)
    report = dict(out["report"])
    report["inputs"] = inputs
    report["existing_overlay"] = {
        "path": str(DEFAULT_OVERLAY_PATH),
        "exists": DEFAULT_OVERLAY_PATH.exists(),
        "verdicts": len(existing_from_text(existing_text)),
    }
    yaml_text = render(out["merged"])
    return JSONResponse({
        "report": report,
        "overlay_yaml": yaml_text,
        "overlay_bytes": len(yaml_text.encode("utf-8")),
        "merged_verdicts": len(out["merged"]),
        "written": False,
        "note": (
            "Nothing was written. Review this file and commit it as "
            "configs/source_qualification.yml — it ships to every fresh install, so the "
            "app does not edit it for you."
        ),
        "conflicts_note": (
            "A domain two instances disagree about is left at whatever the existing "
            "overlay said and listed under 'conflicts'. Re-run with 'accept newest' only "
            "after looking at them: an auto-resolved disagreement ships a verdict nobody "
            "reviewed."
        ),
    })
