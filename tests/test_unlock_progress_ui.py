"""EPSILON E3 guard: honest unlock progress (elapsed clock + migration explanation).

The unlock POST runs init_db() SYNCHRONOUSLY (schema self-heal + one-time migrations +
index builds + WAL recovery) before it returns, so on a first unlock after an upgrade
the button could sit pending for minutes with no feedback (the 981 s field case,
invisible). unlock.html now shows the preparing view + a ticking elapsed clock the
moment the passphrase is submitted, plus an honest one-time-migration explanation — and
NEVER a fabricated percent. Source-text guard (no browser).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"


def _unlock() -> str:
    return (_STATIC / "unlock.html").read_text(encoding="utf-8")


def test_preparing_view_has_elapsed_and_migration_explanation() -> None:
    html = _unlock()
    assert 'id="prep-elapsed"' in html, "no elapsed-time element in the preparing view"
    assert "run one-time migrations and rebuild indexes" in html, "no migration explanation"


def test_elapsed_clock_shown_immediately_on_submit() -> None:
    html = _unlock()
    assert "function _startPrep(" in html, "no _startPrep helper"
    # _startPrep must be called in go() BEFORE the (possibly multi-minute) fn() await,
    # otherwise the synchronous init_db stays invisible. It also takes the view that
    # is currently on-screen (derived from btn.id) so a thrown error can re-show that
    # exact view instead of leaving the whole form hidden forever (LC-VIEW-HIDDEN-ON-ERROR).
    go = html.index("async function go(")
    end = html.index("document.addEventListener", go)
    body = html[go:end]
    prep_call = '_startPrep(btn.id === "btn-unlock" ? "view-unlock" : "view-create");'
    assert prep_call in body, "go() must tell _startPrep which view it is currently hiding"
    assert body.index(prep_call) < body.index("await fn()"), "prep must show BEFORE the POST"


def test_no_fabricated_percent() -> None:
    html = _unlock()
    start = html.index("function _startPrep(")
    body = html[start : html.index("async function go(", start)]
    # The clock is mm:ss real elapsed — never a computed completion percent. (A bare
    # "%" would be the modulo operator, so check for a rendered percent LITERAL.)
    assert 't("Elapsed")' in body
    assert 'padStart(2, "0")' in body
    assert '"%"' not in body and "'%'" not in body, "the elapsed clock must not render a percent"
    # The visible progress bar stays the honest INDETERMINATE slider (declared in CSS).
    assert "we do not fabricate a %" in html


def test_e3_keys_present_in_en_locale() -> None:
    d = json.loads((_STATIC / "locales" / "en.json").read_text(encoding="utf-8"))
    assert "Elapsed" in d
    assert any(
        k.startswith("After an update, the first unlock may run one-time migrations") for k in d
    ), "migration-explanation key missing"
