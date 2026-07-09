"""BETA wave — B2: map-coverage rollup-staleness disclosure chip (field-test F1 / D4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

When the D4 columnar rollup serves /api/insights/map-coverage (OO_COLUMNAR_MAP_SERVE),
the payload carries a `basis` {source, as_of, note} disclosure (src/analytics/map_serve.py)
that the UI never rendered — a visible-caveat gap. B2 renders it via the SHARED basisChip
helper, and renders NOTHING when basis is absent (the live path) — never a fabricated
staleness. Pure file-reads; no app import.
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_APP = (_STATIC / "app.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")


def test_basis_chip_container_exists_on_the_map():
    assert 'id="oo-coverage-basis"' in _HTML


def test_renders_basis_via_the_shared_basisChip_helper():
    """The disclosure reuses the existing basisChip/_basisWhen helpers (the disc form:
    'cached · as of …' with the method note in the #oo-tip hover) — no bespoke chip."""
    assert "function _renderMapBasis(" in _APP
    assert "basisChip(null, b)" in _APP
    # basisChip + _basisWhen are the pre-existing shared helpers (unchanged)
    assert "function basisChip(" in _APP
    assert "function _basisWhen(" in _APP


def test_renders_nothing_when_basis_absent_no_fabricated_staleness():
    """The live path has no `basis`, so the chip must render an empty string, never a
    guessed/blank staleness label."""
    assert 'el.innerHTML = b ? basisChip(null, b) : ""' in _APP
    # it reads the basis STRAIGHT off the payload — never synthesized
    assert "_ooMapPayload && _ooMapPayload.basis" in _APP


def test_wired_into_the_map_loader_and_langchange():
    assert "_renderMapBasis();" in _APP  # called in loadOoMapCoverage
    # re-rendered on locale switch so the 'cached · as of' label tracks the UI language
    assert 'if (typeof _renderMapBasis === "function") _renderMapBasis();' in _APP


def test_basis_is_a_disclosure_not_a_score():
    """The disclosure never introduces a numeric grade — it is the standard basisChip
    (a documented DISCLOSURE, not a score). Guard the comment intent is present."""
    assert "A DISCLOSURE, never a score." in _APP
