"""
Source-integrity tab DISSOLVED from the sidebar, preserved in Settings (PR 5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled (TRUST TABS -> DISSOLVE, content-first): coordination is now
surfaced automatically (Leads + the analysis Related view + inline list/reader
badges), so the manual "Source integrity" tab leaves the sidebar. ABSORPTION GATE /
Desk lesson: nothing is lost — the tab's manual tools (collapse-to-one-voice,
source profile, web-of-trust annotations) stay reachable from Settings -> Safety.
This guards that dissolution-without-loss.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
_JS = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")


def test_integrity_left_the_sidebar():
    # The sidebar is now a FLAT list (#22, 2026-06-22) — no per-group anchors — so check
    # the whole nav for the absence of the integrity button.
    nav = _HTML.split('id="navGroups"', 1)[1].split("</nav>", 1)[0]
    assert 'data-tab="integrity"' not in nav, "the Source-integrity sidebar button must be removed"


def test_integrity_reachable_from_settings():
    assert "showTab('integrity')" in _HTML, "Settings must carry an entry point to the integrity desk"


def test_integrity_tools_preserved_desk_lesson():
    # The page + every manual tool still exist (never lose a tool).
    assert 'id="tab-integrity"' in _HTML, "the integrity tab-page must be preserved"
    assert "function loadActors" in _JS and "function cardCollapse" in _JS, "collapse curation preserved"
    assert "function loadProfile" in _JS, "source-profile lookup preserved"
    assert "function addAnnotation" in _JS and "function lookupAnnotations" in _JS, "web-of-trust annotations preserved"
