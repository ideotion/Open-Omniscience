"""World-map time slider: a labelled LINEAR/LOG scale toggle (batch F item 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ooMap Signals time slider previously hard-coded a logarithmic position->year
mapping. Batch F adds a Linear/Log toggle plus a labelled tick strip, so the user
can choose an even year sweep or the antiquity-compressing log sweep — and the
actual year at every position is always named (no hidden warp). Pure frontend over
the existing /api/timemap payload; string-assertion wiring guard (browser-unverified
per fork-3).
"""

from __future__ import annotations

from pathlib import Path

from tests.test_repo_invariants import _ui_source

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")


def test_time_scale_state_defaults_to_log():
    # the mapping state exists and preserves the shipped log behaviour by default
    assert "_ooMapTimeScale" in _JS
    assert '_ooMapTimeScale = "log"' in _JS


def test_both_linear_and_log_mappings_present():
    # LINEAR = even sweep (age = span * (1 - fraction)); LOG = the existing
    # antiquity-compressing power mapping (kept as-is, invariant-pinned) — both exist.
    assert 'spanY * (1 - frac)' in _JS, "linear (even) mapping missing"
    assert "Math.pow(_LOGB, 1 - frac)" in _JS, "log mapping must be preserved"
    assert '_ooMapTimeScale === "linear"' in _JS


def test_no_hidden_warp_focus_label_and_labelled_ticks():
    # the actual year is named at the cursor (focusLabel) AND at 0/¼/½/¾/1 (ticks),
    # so the compression is explicit — the ruling's "honest labelled ticks".
    assert "focusTicks" in _JS
    assert "[0, 0.25, 0.5, 0.75, 1].map(frac =>" in _JS
    assert "yearAt(frac)" in _JS
    # ticks rendered in the slider overlay
    assert "opts.focusTicks.map(tk =>" in _JS


def test_toggle_buttons_and_wiring_present():
    ui = _ui_source()
    assert "data-oomap-tscale" in ui, "the Linear/Log toggle buttons must render"
    assert "onTimeScale" in _JS, "the toggle callback must be threaded through opts"
    # wired in _wireOoMap (click -> opts.onTimeScale(scale))
    assert "opts.onTimeScale(b.dataset.oomapTscale)" in _JS
    # the callback flips the state and re-renders (no extra fetch)
    assert 'v === "linear" ? "linear" : "log"' in _JS


def test_toggle_labels_use_t_translation_wrapper():
    # user-facing strings go through the translation wrapper (keyable later)
    assert 't("Time scale")' in _JS
    assert 't("Linear")' in _JS and 't("Log")' in _JS
