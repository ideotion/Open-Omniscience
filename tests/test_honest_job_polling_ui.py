"""EPSILON E0 guard: the SPA callers of the started/job endpoints POLL to completion.

The #595/A2 background-job refactor made three heavy actions return
``{"started": true, "job": {...}}`` and finish in a daemon thread. Their SPA callers
used to parse the immediate (empty) response and DISPLAY FALSE STATEMENTS on 0.1
("Loaded 0 figures." / "Typed 0 of 0 scanned" / "Tagged undefined keyword(s)"). This
locks in the fix: each caller polls the job's ``.../status`` route to a terminal state
and reports the REAL result. A pure source-text guard (no browser), so a regression
that reverts a caller to the synchronous shape reddens here + in CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"


def _app() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def _fn_body(src: str, name: str) -> str:
    """The source of ``async function NAME(...)`` up to the next top-level function."""
    m = re.search(r"async function " + re.escape(name) + r"\s*\(", src)
    assert m, f"{name} not found in app.js"
    start = m.start()
    nxt = re.search(r"\n    (?:async )?function \w+\s*\(", src[start + 10 :])
    end = start + 10 + nxt.start() if nxt else len(src)
    return src[start:end]


def test_poll_job_status_helper_exists() -> None:
    app = _app()
    assert "async function pollJobStatus(" in app, "the shared job-poll helper is gone"
    # It must actually inspect the terminal state, not just fire once.
    body = _fn_body(app, "pollJobStatus")
    for terminal in ("done", "error", "cancelled"):
        assert f'"{terminal}"' in body, f"pollJobStatus does not check the {terminal} state"


def test_gov_load_standard_polls_to_completion() -> None:
    body = _fn_body(_app(), "govLoadStandard")
    assert "/api/governments/load-standard/status" in body, "does not poll the job status"
    assert "pollJobStatus(" in body
    # The honest result comes from the polled job's .result, never the POST body's r.stored.
    assert "st.result" in body or "res.stored" in body
    assert "r.stored" not in body, "still reads the empty start-state figure count"


def test_enrich_source_types_polls_to_completion() -> None:
    body = _fn_body(_app(), "enrichSourceTypes")
    assert "/api/diagnostics/enrich-source-types/status" in body, "does not poll the job status"
    assert "pollJobStatus(" in body
    # Never the immediate 'd.sources_typed of d.scanned' start-state (was "0 of 0").
    assert "d.sources_typed" not in body and "d.scanned" not in body


def test_kx_backfill_polls_to_completion() -> None:
    body = _fn_body(_app(), "kxBackfill")
    assert "/api/insights/keyword-tags/backfill/status" in body, "does not poll the job status"
    assert "pollJobStatus(" in body
    # Never 'r.tagged_keywords' straight off the POST (was "undefined") — read st.result.
    assert "r.tagged_keywords" not in body
    assert "res.tagged_keywords" in body


def test_keyword_explorer_auto_backfill_polls_before_rerender() -> None:
    body = _fn_body(_app(), "loadKeywordExplorer")
    assert "_kxAutoBackfilled" in body
    # The auto-backfill must POLL the job to completion before the recursive re-render,
    # otherwise the re-render fires while the job has only just STARTED (still empty).
    post = body.index("/api/insights/keyword-tags/backfill?limit=0")
    poll = body.index("/api/insights/keyword-tags/backfill/status")
    rerender = body.rindex("return loadKeywordExplorer()")
    assert post < poll < rerender, "must poll to completion before re-rendering"


def test_new_e0_keys_present_in_en_locale() -> None:
    d = json.loads((_STATIC / "locales" / "en.json").read_text(encoding="utf-8"))
    for k in (
        "Loading country data in the background…",
        "(stopped early — partial)",
        "Enriching in the background…",
        "Typed source types:",
        "Applying baseline tags in the background…",
        "Applied baseline tags:",
        "Backfill failed:",
    ):
        assert k in d, f"missing en.json key: {k!r}"
