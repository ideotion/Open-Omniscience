"""An ooViz dumbbell wired to a real surface: ring per-country articles vs mentions (item #8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ring cross-country view gains an honest DUMBBELL chart built from the ooViz
primitives (linearScale + niceTicks): each country shows its distinct-article spread
(accent dot) and its total mentions (muted dot) with a connecting segment — the gap is
amplification, never a fabricated curve. Counts only; every country is drawn, capped with
the drop disclosed (no silent truncation, per invariant #16's honesty). Pure
string-assertion wiring guard (browser-unverified per fork-3).
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")


def test_dumbbell_uses_ooviz_primitives():
    assert "function ringDumbbellSvg(" in _JS
    assert "ooViz.linearScale" in _JS and "ooViz.niceTicks" in _JS
    # graceful degrade when ooViz isn't loaded
    assert 'typeof ooViz === "undefined" || !ooViz.linearScale' in _JS


def test_dumbbell_plots_real_counts_not_a_curve():
    # two real measured dots per country (articles = accent, mentions = muted) + a segment
    assert 'x(r.articles || 0)' in _JS and 'x(r.mentions || 0)' in _JS
    assert 'fill="var(--accent)"' in _JS and 'fill="var(--muted)"' in _JS
    # no interpolated path / fake curve — it is <line>/<circle> at exact values
    assert "dumbbellScore" not in _JS


def test_truncation_is_disclosed_never_silent():
    assert "_DUMBBELL_MAX" in _JS
    assert "dropped = data.length - shown.length" in _JS
    assert 't("+ {n} more (not shown)")' in _JS


def test_dumbbell_wired_into_ring_map_detail():
    assert "const dumb = ringDumbbellSvg(" in _JS
    assert "langs + langBd + unlocNote + dumb + tbl" in _JS


def test_dumbbell_strings_translated():
    en = (_STATIC / "locales" / "en.json").read_text(encoding="utf-8")
    ja = (_STATIC / "locales" / "ja.json").read_text(encoding="utf-8")
    assert "Per-country articles vs mentions" in en and "Per-country articles vs mentions" in ja
