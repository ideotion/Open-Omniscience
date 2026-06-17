"""
Related subtab — SHARED-ORIGIN lens (PR 2: broaden "Related" beyond near-dup).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled 2026-06-17: the analysis window's Related subtab also surfaces
articles citing the SAME outbound origin (the anti-false-triangulation lens) and
lets the user BRANCH that group into a new corpus — reusing the existing
/api/links/corpus + /api/links/articles-by-link endpoints (no new backend). The
near-dup section (#299) is preserved. Browser-unverified, so the static guard
matters.
"""

from __future__ import annotations

from pathlib import Path

_JS = (Path(__file__).resolve().parents[1] / "src" / "static" / "app.js").read_text(encoding="utf-8")


def test_shared_origins_section_reuses_existing_link_endpoints():
    assert "Shared origins" in _JS, "the Related subtab must add a Shared-origins section"
    assert "/api/links/corpus" in _JS, "shared origins reuse the corpus-links endpoint"
    assert "function branchFromOrigin" in _JS, "each shared origin must branch into a new corpus"
    assert "/api/links/articles-by-link?url=" in _JS, (
        "branching a shared origin fetches the citing-article ids by link"
    )
    assert "openAnalysisForIds(ids" in _JS, "the shared-origin branch spawns a corpus over those ids"


def test_shared_origin_independence_caveat_is_visible():
    # The anti-false-triangulation honesty must travel with the lens.
    assert "not independent confirmation" in _JS, "shared origins must state one-origin-several-echoes"
    assert "card-caveat" in _JS, "the caveat must render in the visible .card-caveat surface"


def test_near_dup_section_preserved():
    # PR 2 must not regress the #299 near-dup coordination lens / its branch.
    assert "function renderAnRelated" in _JS and "function branchFromRelated" in _JS
    assert "/api/insights/corpus-coordination" in _JS
    assert "openAnalysisForIds(c.article_ids" in _JS
    assert "= effectively one voice" in _JS and "= one voice" in _JS
