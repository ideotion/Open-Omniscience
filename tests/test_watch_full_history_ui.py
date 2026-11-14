"""Insights > Watches: show every firing of a watch (R684, Lane M).

``GET /api/watches/{id}/history`` had no button: the Watches list carries only the
last few firings per watch. A watch that shows that many now offers "Show every
firing", which reads its whole history (newest first, capped and said so) and keeps
it across a language repaint.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.js_source_helper import function_body

_ROOT = Path(__file__).resolve().parents[1]
_INS = (_ROOT / "src" / "static" / "app-insights.js").read_text(encoding="utf-8")
_ENGINE = (_ROOT / "src" / "analytics" / "watches.py").read_text(encoding="utf-8")
_API = (_ROOT / "src" / "api" / "watches.py").read_text(encoding="utf-8")


def test_the_button_threshold_is_the_lists_own_history_size():
    n = re.search(r"def list_watches\(session: Session, \*, history_limit: int = (\d+)\)", _ENGINE)
    assert n, "list_watches signature moved"
    assert f"const WT_LIST_HISTORY = {n.group(1)};" in _INS


def test_the_full_read_stays_within_the_routes_cap_and_says_when_it_is_cut():
    cap = re.search(r"limit: int = Query\(50, ge=1, le=(\d+)\)", _API)
    assert cap and f"const WT_FULL_LIMIT = {cap.group(1)};" in _INS
    more = function_body(_INS, "wtHistMoreHtml")
    assert "full.length >= WT_FULL_LIMIT" in more and "Earlier ones are kept but not shown here." in more


def test_it_reads_one_watch_and_repaints_without_a_second_request():
    load = function_body(_INS, "_wtLoadFull")
    assert '"/api/watches/" + id + "/history?limit=" + WT_FULL_LIMIT' in load
    assert "_renderWatches()" in load
    render = function_body(_INS, "_renderWatches")
    assert "api(" not in render, "a language repaint must not fetch"
    assert "_wtFull[w.id]" in render
    assert "_wtFull = {};" in function_body(_INS, "loadWatches"), "a fresh load forgets stale full histories"


def test_one_delegated_listener_and_no_inline_handler_on_the_new_button():
    assert 'button[data-wt-hist]' in function_body(_INS, "_wtWireOpen")
    assert "data-on-click" not in function_body(_INS, "wtHistMoreHtml")
    assert "saved_search" in function_body(_INS, "wtHistMoreHtml"), "a saved search never fires, so no button"
