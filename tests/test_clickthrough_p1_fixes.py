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

from tests.js_source_helper import function_body, read_static


def test_the_hover_bubble_is_hosted_in_the_open_dialog_that_holds_its_element():
    # A showModal() dialog is in the browser's TOP LAYER, which no z-index reaches, so a
    # bubble left on <body> is drawn UNDER it: Q1002's per-lane hosts were unreadable.
    show = function_body(read_static("app-boot.js"), "show")
    assert 'closest("dialog[open]")' in show
    assert "host.appendChild(tip)" in show
    # ...and it goes back to <body> for everything outside a dialog.
    assert "|| document.body" in show


def test_a_title_repainted_while_its_bubble_is_open_is_never_overwritten():
    boot = read_static("app-boot.js")
    # the bubble follows a repaint...
    assert 'attributeFilter: ["title"]' in function_body(boot, "ooTipInit")
    # ...and hide() keeps a title the app set, instead of writing the captured one back.
    assert re.search(
        r'cur\.hasAttribute\("title"\)\)\s*\{\s*cur\.dataset\.ooTip = cur\.getAttribute\("title"\)',
        function_body(boot, "hide"),
    )


def test_the_task_manager_counts_healthy_as_healthy():
    assert 'h.status === "healthy"' in read_static("taskmanager.html")


def test_a_deep_linked_analysis_tab_does_not_also_load_the_restored_one():
    hyd = function_body(read_static("app-boot.js"), "_hydrateCardCorpus")
    # hydrated BEFORE showTab, or showTab loads the restored active tab first
    flag = re.search(r"_anHydrated = true", hyd)
    show = re.search(r'showTab\("analyze", false\)', hyd)
    assert flag and show and flag.start() < show.start()


def test_a_superseded_analysis_run_never_writes():
    an = read_static("app-analysis.js")
    body = function_body(an, "loadAnalysis")
    assert "++_anRunSeq" in body
    # every await in the run is followed by the staleness check (comments dropped, so an
    # "await" in prose cannot pass or fail this)
    code = "\n".join(
        ln if "http" in ln else re.sub(r"//.*", "", ln) for ln in body.splitlines()
    )
    awaits = [m.start() for m in re.finditer(r"\bawait\b", code)]
    assert awaits, "loadAnalysis lost its awaits?"
    for pos in awaits:
        assert "if (stale()) return;" in code[pos : pos + 700], code[pos : pos + 120]
    # the two un-awaited loaders carry the run and check it after their own fetch
    assert "_anLoadArticles(p, 0, run)" in body and "_anLoadArtFacets(p, run)" in body
    for fn in ("_anLoadArticles", "_anLoadArtFacets"):
        assert "run !== _anRunSeq" in function_body(an, fn), fn
