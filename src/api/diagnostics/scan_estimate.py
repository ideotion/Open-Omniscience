"""What a Thorough Diagnostics build is expected to cost, asked before it is started (R459, finding F9 of the 2026-11-07 Windows run).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read-only and cheap: one stored key and one indexed MAX, no scan. The figure is this machine's own earlier scan times scaled by today's
mention rows, with the field medians for a scan never timed here (see ``diagnostics_plan.thorough_estimate``). It ORDERS nothing and
decides nothing: ``est_s`` in the plan stays an ordering of the scans.

A NEW slice imported LAST, so the split guard's pinned route positions stay where they were.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import Depends, Response

from src.api import diagnostics_plan as _plan
from src.api.cross_site import refuse_cross_site_get
from src.monitoring.secret_scrub import log_failure

from ._base import _LOG, router


@router.get("/all-job/estimate", dependencies=[Depends(refuse_cross_site_get)])
def all_diagnostics_estimate() -> Response:
    """What a Thorough build is expected to hold the machine for, and what it was scaled by. Quick is bounded by its own budget."""
    from src.api.country_wire import CountryWireResponse as JSONResponse

    try:
        from src.config.kv_store import kv_get_json

        history = kv_get_json(_plan.SCAN_WALLS_KEY)
    except Exception:  # noqa: BLE001 - no history is the field medians, said as such
        history = None
    rows = _mention_rows()
    return JSONResponse(
        {
            "thorough": _plan.thorough_estimate(history, rows),
            "quick": {"budget_s": _plan.SCAN_BUDGET_S},
            "mention_rows": rows,
        }
    )


def _mention_rows() -> int | None:
    """The largest mention id: the O(1) stand-in for its row count, an upper bound that is exact for a corpus never pruned. ``None`` when unreadable."""
    try:
        from sqlalchemy import text

        from src.database.read_snapshot import read_snapshot_session

        with read_snapshot_session() as s:
            v = s.execute(text("SELECT MAX(id) FROM keyword_mentions_all")).scalar()
        return int(v) if v else None
    except Exception:  # noqa: BLE001 - an estimate's input never fails a build
        return None


def _remember_scan_walls(results: list[dict]) -> None:
    """Keep how long each scan took, with the mention rows of the day, so the next Thorough estimate is this machine's own. Never raises."""
    try:
        from src.config.kv_store import kv_get_json, kv_set_json

        fresh = _plan.walls_to_remember(results, _mention_rows(), datetime.now(UTC).isoformat(timespec="seconds"))
        if not fresh:
            return
        kept = kv_get_json(_plan.SCAN_WALLS_KEY)
        merged = {**(kept if isinstance(kept, dict) else {}), **fresh}
        kv_set_json(_plan.SCAN_WALLS_KEY, merged)
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "all-diagnostics could not keep the scan times for the next estimate", exc, level=logging.DEBUG)
