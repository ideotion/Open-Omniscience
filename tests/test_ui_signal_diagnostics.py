"""Signal-surface diagnostics buttons (wave 4 I, task 4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The read-only statistical-signal endpoints that had no UI now have explicit
exploration buttons in Settings → Diagnostics: the Benjamini-Hochberg FDR self-test,
the flood + bury manipulation-pattern surfaces, the lunar-correlation screen (all GET,
each opens/downloads its honest JSON with its own method + caveat). flood/bury also
auto-render as Home Leads — this is the explicit dig-in surface. Counts + statistics
only, never a score. Un-keyed English (matches the diagnostics panel). Pure
string-assertion wiring guard (browser-unverified per fork-3).

The poll-transparency checklist that used to live beside these was REMOVED entirely
(frontend, endpoint and module) by the 2026-07-31 Settings review; its two guards went
with it rather than being weakened to keep passing.
"""

from __future__ import annotations

from pathlib import Path
from tests.js_source_helper import app_js

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = app_js()


def test_get_signal_buttons_present():
    assert "window.open('/api/signals/fdr-selftest?download=1','_blank')" in _HTML
    assert "window.open('/api/signals/flood','_blank')" in _HTML
    assert "window.open('/api/signals/bury','_blank')" in _HTML
    assert "window.open('/api/insights/lunar-correlation','_blank')" in _HTML


def test_poll_transparency_is_gone():
    """The checklist was removed whole — a leftover input, handler or endpoint call would
    mean a half-removal, which is the failure mode worth guarding here."""
    for gone in ('id="poll-fields"', 'id="poll-transparency-out"', "pollTransparencyCheck"):
        assert gone not in _HTML, gone
        assert gone not in _JS, gone
    assert "/api/insights/poll-transparency" not in _JS


def test_honesty_statistics_not_a_score():
    # the surrounding hints state the honesty stance (shape not verdict, no score)
    assert "never a composite score" in _HTML
    assert "a microscope, not a detector" in _HTML
