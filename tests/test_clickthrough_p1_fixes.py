"""The three P1 causes the 2026-09-26 delegated click-through found, pinned at the source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each was proven in Chromium before and after the fix (``docs/audit/delegated-
clickthrough-2026-09-26/``): 15 of 15 consent-popup lane hovers went from covered to
topmost, the task-manager page from "online" to "Airplane mode", and a deep-linked analysis
tab from issuing the restored tab's request to issuing only its own. CI runs no browser, so
these tests pin the MECHANISM each fix relies on; the route fix is tested behaviourally in
``tests/test_collection_activity.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parent.parent / "src" / "static"


def _read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def _tip_init() -> str:
    src = _read("app-boot.js")
    start = src.index("(function ooTipInit()")
    return src[start : src.index("})();", start)]


def test_the_hover_bubble_is_hosted_in_the_open_dialog_that_holds_its_element():
    # A showModal() dialog is in the browser's TOP LAYER, which no z-index reaches, so a
    # bubble left on <body> is drawn UNDER it: Q1002's per-lane hosts were unreadable.
    body = _tip_init()
    show = body[body.index("function show(") : body.index("function hide(")]
    assert 'closest("dialog[open]")' in show
    assert "host.appendChild(tip)" in show
    # ...and it goes back to <body> for everything outside a dialog.
    assert "|| document.body" in show


def test_a_title_repainted_while_its_bubble_is_open_is_never_overwritten():
    body = _tip_init()
    # the bubble follows a repaint...
    assert 'attributeFilter: ["title"]' in body
    # ...and hide() keeps a title the app set, instead of writing the captured one back.
    hide = body[body.index("function hide(") :]
    assert re.search(
        r'cur\.hasAttribute\("title"\)\)\s*\{\s*cur\.dataset\.ooTip = cur\.getAttribute\("title"\)',
        hide,
    )


def test_the_task_manager_counts_healthy_as_healthy():
    tm = _read("taskmanager.html")
    assert 'h.status === "healthy"' in tm


def test_a_deep_linked_analysis_tab_does_not_also_load_the_restored_one():
    boot = _read("app-boot.js")
    hyd = boot[boot.index("(function _hydrateCardCorpus()") :]
    hyd = hyd[: hyd.index("})();")]
    # hydrated BEFORE showTab, or showTab loads the restored active tab first
    assert hyd.index("_anHydrated = true") < hyd.index('showTab("analyze", false)')


def test_a_superseded_analysis_run_never_writes():
    an = _read("app-analysis.js")
    body = an[an.index("async function loadAnalysis(p) {") :]
    body = body[: body.index("\n    }\n")]
    assert "++_anRunSeq" in body
    # every await in the run is followed by the staleness check
    code = "\n".join(ln.split("//")[0] if "http" not in ln else ln for ln in body.splitlines())
    awaits = [m.start() for m in re.finditer(r"\bawait\b", code)]
    assert awaits, "loadAnalysis lost its awaits?"
    for pos in awaits:
        after = code[pos : pos + 700]
        assert "if (stale()) return;" in after, code[pos : pos + 120]
    # the two un-awaited loaders carry the run and check it after their own fetch
    assert "_anLoadArticles(p, 0, run)" in body and "_anLoadArtFacets(p, run)" in body
    for fn in (
        "async function _anLoadArticles(p, page, run)",
        "async function _anLoadArtFacets(p, run)",
    ):
        seg = an[an.index(fn) :][:1800]
        assert "run !== _anRunSeq" in seg, fn
