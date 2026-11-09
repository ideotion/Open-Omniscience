"""Field checks (R603, 2026-11-08): the routes behind the Diagnostics panel's "Field checks" box.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The list is ``configs/field_checks.yml``; the runners and the rules they keep are in
``src/monitoring/field_checks.py``. Three routes: the list (with each check's last result), run one
check, and save the report. An ONLINE check is refused here without ``consent: true``, which the
page sends only after the one network consent popup (``ensureOnline``, invariant #14), so a caller
that never went through the page gets the same honest refusal.

A NEW slice imported before the release run, the way ``country_form.py`` and ``source_samples.py``
are, so the split guard's pinned positions stay where they were.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from src.api.cross_site import refuse_cross_site_get
from src.database.session import get_db
from src.monitoring.secret_scrub import record_text

from ._base import router


class FieldCheckRun(BaseModel):
    id: str = Field(..., max_length=80)
    consent: bool = False
    #: The panel's input: a folder for the drive check; an answer, a note and the page's counters
    #: for a check that needs hands. Nothing secret is asked for, and the result is scrubbed.
    inputs: dict[str, Any] = Field(default_factory=dict)
    INPUT_KEYS_MAX: ClassVar[int] = 8
    INPUT_CHARS_MAX: ClassVar[int] = 8192

    @field_validator("inputs")
    @classmethod
    def _bounded(cls, v: dict[str, Any]) -> dict[str, Any]:
        # A folder path, an answer, a 500-character note and three counters fit in far less; a bound keeps
        # an oversized body from being held in the results and copied into the report.
        if len(v) > cls.INPUT_KEYS_MAX or len(json.dumps(v, ensure_ascii=False, default=str)) > cls.INPUT_CHARS_MAX:
            raise ValueError(f"inputs are limited to {cls.INPUT_KEYS_MAX} keys and {cls.INPUT_CHARS_MAX} characters")
        return v


@router.get("/field-checks", dependencies=[Depends(refuse_cross_site_get)])
def field_checks_list() -> dict:
    """Every check in the manifest (active and retired), whether it applies here, and its last result
    in this process. Reads one YAML file; runs nothing."""
    from src.monitoring import field_checks as fc

    try:
        return fc.panel_view()
    except fc.FieldCheckError as exc:
        raise HTTPException(status_code=500, detail=record_text(exc, limit=300)) from None


@router.post("/field-checks/run")
def field_checks_run(body: FieldCheckRun, db: Session = Depends(get_db)) -> dict:
    """Run ONE active check. Plain ``def``: it runs in the threadpool, and the longest (a 256 MiB write
    on a slow USB stick, a tens-of-megabytes download) takes a minute or two."""
    from src.monitoring import field_checks as fc

    try:
        return fc.run_check(body.id, consent=body.consent, inputs=body.inputs, db=db)
    except fc.FieldCheckError as exc:
        raise HTTPException(status_code=400, detail=record_text(exc, limit=300)) from None


@router.get("/field-checks/report", dependencies=[Depends(refuse_cross_site_get)])
def field_checks_report() -> Response:
    """The one file to bring back: every result this process holds, scrubbed, as JSON."""
    from datetime import datetime

    from src.monitoring import field_checks as fc

    try:
        report = fc.build_report()
    except fc.FieldCheckError as exc:
        raise HTTPException(status_code=500, detail=record_text(exc, limit=300)) from None
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        content=json.dumps(report, ensure_ascii=False, indent=1).encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="oo-field-checks-{stamp}.json"'},
    )
