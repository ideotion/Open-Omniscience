"""Signal-surface diagnostics buttons (wave 4 I, task 4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The read-only statistical-signal endpoints that had no UI now have explicit
exploration buttons in Settings → Diagnostics: the Benjamini-Hochberg FDR self-test,
the flood + bury manipulation-pattern surfaces, the lunar-correlation screen (all GET,
each opens/downloads its honest JSON with its own method + caveat), and a POST
poll-transparency checklist form. flood/bury also auto-render as Home Leads — this is
the explicit dig-in surface. Counts + statistics only, never a score. Un-keyed English
(matches the diagnostics panel). Pure string-assertion wiring guard (browser-unverified
per fork-3).
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")


def test_get_signal_buttons_present():
    assert "window.open('/api/signals/fdr-selftest?download=1','_blank')" in _HTML
    assert "window.open('/api/signals/flood','_blank')" in _HTML
    assert "window.open('/api/signals/bury','_blank')" in _HTML
    assert "window.open('/api/insights/lunar-correlation','_blank')" in _HTML


def test_poll_transparency_form_and_handler():
    assert 'id="poll-fields"' in _HTML
    assert 'id="poll-transparency-out"' in _HTML
    assert 'onclick="pollTransparencyCheck()"' in _HTML
    assert "async function pollTransparencyCheck(" in _JS
    # a POST of the disclosed fields to the checklist endpoint
    assert '"/api/insights/poll-transparency", {method: "POST", body: JSON.stringify(fields)}' in _JS
    # invalid JSON is reported, never a silent failure
    assert "Invalid JSON:" in _JS


def test_honesty_statistics_not_a_score():
    # the surrounding hints state the honesty stance (shape not verdict, no score)
    assert "never a composite score" in _HTML
    assert "a microscope, not a detector" in _HTML
    # poll-transparency records presence only, never grades/ranks
    assert "records PRESENCE only" in _HTML
