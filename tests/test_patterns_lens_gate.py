"""Q1124 = a — the Patterns lens flips on only when BOTH numbers are measured and met.

«Flip on only when the corpus is >= 100 k articles and a labelled sample shows a
false-positive rate <= 5%; both numbers on the toggle.»

The load-bearing half is not the arithmetic, it is that ONE of the two numbers
cannot be measured by this app at all. A labelled sample is a person judging which
flags were wrong; nothing here produces one. So the endpoint OMITS the field and the
panel reads the omission as "unmeasured" — never as 0.0, which on a false-positive
rate would claim a perfect detector.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.js_source_helper import (
    app_js,
    event_listener_bodies,
    function_body,
    object_literal,
    python_function_source,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parent.parent


def _gate_source() -> str:
    return (_ROOT / "src" / "api" / "signals.py").read_text(encoding="utf-8")


def test_the_two_bars_are_the_ruled_numbers():
    src = _gate_source()
    assert "PATTERNS_CORPUS_BAR = 100_000" in src, "Q1124's corpus bar is 100,000 articles"
    assert "PATTERNS_FALSE_POSITIVE_BAR = 0.05" in src, "Q1124's false-positive bar is 5%"


def test_the_false_positive_rate_is_absent_not_zero():
    """The whole honesty of the gate. A 0.0 here reads as 'measured, and perfect'."""
    body = python_function_source(_gate_source(), "signals_patterns_gate")
    # COMMENT-STRIPPED: the comment beside the omission necessarily QUOTES the key it
    # says is absent, and that comment is what a future reader needs before deciding
    # the omission was an oversight. Strip it; never reword it.
    payload = re.sub(r"#[^\n]*", "", body.split("return {", 1)[1])
    assert '"false_positive_rate"' not in payload, (
        "the rate must be OMITTED while unmeasured -- an omitted field and a 0.0 are "
        "different facts, and only one of them is true here"
    )
    assert '"false_positive_basis": "unmeasured"' in payload, "the absence must carry its reason"
    assert '"can_flip": False' in payload, "Q1124 forbids the flip until both numbers are met"


def test_the_refusal_names_which_half_blocks_it():
    body = python_function_source(_gate_source(), "signals_patterns_gate")
    assert 'blocked_by.append("false_positive_rate")' in body
    assert 'blocked_by.append("corpus")' in body, (
        "a reader must be able to tell a small corpus from an unmeasured rate"
    )


def test_the_panel_distinguishes_absent_from_zero():
    """A source grep cannot tell `!= null` from a truthiness test, and the difference
    is the whole ruling: `if (g.false_positive_rate)` renders a measured 0.0% as
    'unmeasured', and `if (g.false_positive_rate != null)` renders it as 0.0%."""
    body = strip_comments(function_body(app_js(), "_renderPatternsGate"))
    assert re.search(r"g\.false_positive_rate\s*!=\s*null", body), (
        "the panel must branch on PRESENCE, never on truthiness -- 0.0 is a legal rate"
    )
    assert "unmeasured" in body and "labelled sample" in body


def test_the_panel_is_filled_by_a_CONTROL_and_never_by_expanding_the_section():
    """A panel nothing fills never fills -- but the fix is NOT a section loader.

    This guard first asserted an ``_ADV_LOADERS.diagnostics`` entry, and the full suite
    said why that was wrong: ``test_opening_advanced_still_fetches_nothing_for_diagnostics``
    pins that Advanced -> Diagnostics fetches NOTHING on expand, and its own words are
    "adding one means something now fetches on expand, which is a decision, not a
    refactor". The decision was made deliberately and against the loader: this gate reads
    a COUNT over every article, a table scan on the ~1M-article instance row C of the 0.4
    gate targets, and the section's whole grammar is button-driven reports. So the panel
    has a CONTROL, the loader entry is absent, and this test pins BOTH halves so the two
    guards agree with each other rather than taking turns being red.
    """
    shell = (_ROOT / "src" / "static" / "app-shell.js").read_text(encoding="utf-8")
    loaders = object_literal(shell, "_ADV_LOADERS")
    assert "diagnostics:" not in loaders, (
        "expanding Advanced must fetch nothing -- the gate panel is button-driven"
    )
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    at = html.index('id="patterns-gate"')
    section = html.rfind('data-adv="', 0, at)
    assert html[section:section + 30].startswith('data-adv="diagnostics"'), (
        "the panel must sit in the Diagnostics section"
    )
    # the control that fills it lives in the SAME section, above the panel
    control = html.rfind("loadPatternsGate()", 0, at)
    assert control > section, (
        "nothing in the Diagnostics section calls loadPatternsGate() -- the panel would "
        "render empty forever, which is the failure the loader was reached for"
    )
    tag = html[html.rfind("<button", 0, control):html.index("</button>", control) + 9]
    assert 'onclick="loadPatternsGate()"' in tag, f"the control must be a button: {tag[:90]!r}"
    label = tag[tag.index(">") + 1:tag.index("</button>")].strip()
    en = json.loads((_ROOT / "src" / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    assert label in en, f"the button label {label!r} must be keyed, or it is English x12"


def test_the_toggle_cannot_be_flipped_on_in_0_4():
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    at = html.index('id="patterns-lens"')
    tag = html[html.rfind("<", 0, at):html.index(">", at) + 1]
    assert "disabled" in tag, "Q1124: no flip in 0.4 -- the control ships disabled"
    assert 'type="checkbox"' in tag


def test_the_endpoint_is_reachable_through_http_not_only_as_a_function():
    """A route defined under a prefix that also carries a `/{id}` route can be
    shadowed; a handler tested as a function never speaks HTTP and cannot see it."""
    from src.api.signals import router

    paths = {r.path for r in router.routes}  # the ROUTER's own definitions, never app.routes
    assert "/api/signals/patterns-gate" in paths, f"route not registered: {sorted(paths)[:5]}"


def test_the_gate_answers_over_http_and_omits_the_rate_on_the_wire():
    """A handler tested as a function never speaks HTTP, so it cannot see a route
    shadowed by a sibling `/{id}` on the same prefix -- and it cannot see what the
    SERIALISER does either. The omission has to survive the wire: a response model
    or a default could put `false_positive_rate: 0.0` back in without touching the
    handler."""
    import os
    import tempfile

    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory() as tmp:
        os.environ.update(OO_DATA_DIR=tmp, OO_DB_PLAINTEXT="1", OO_NO_SCHEDULER="1")
        from src.api.main import app

        with TestClient(app) as client:
            r = client.get("/api/signals/patterns-gate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "false_positive_rate" not in body, (
        "the rate must be absent ON THE WIRE, not merely absent in the handler"
    )
    assert body["false_positive_basis"] == "unmeasured"
    assert body["can_flip"] is False
    assert body["corpus_bar"] == 100_000 and body["false_positive_bar"] == 0.05
    assert "false_positive_rate" in body["blocked_by"]


def test_the_panel_repaints_on_a_language_switch():
    """The frozen-locale class, MEASURED here rather than reasoned about.

    The panel's lines are composed at render time from ``t()`` calls plus measured
    numbers, so ``i18n.js``'s exact-text walker can never match them -- and the panel
    is painted once, behind ``advLoaded``. The first Chromium walk of this slice caught
    exactly that: "Corpus size: 24 / 100 000" stayed English in ``fr`` while the pills
    beside it translated. The fix is a pure renderer registered on the ONE canonical
    ``oo:langchange`` listener, repainting from the CACHED payload so a switch costs no
    request -- which is also why the guard below forbids ``loadPatternsGate`` there.
    """
    boot = (_ROOT / "src" / "static" / "app-boot.js").read_text(encoding="utf-8")
    bodies = event_listener_bodies(boot, "oo:langchange")
    assert bodies, "no oo:langchange listener found in app-boot.js"
    repaints = [b for b in bodies if "_renderPatternsGate" in strip_comments(b)]
    assert repaints, (
        f"{len(bodies)} oo:langchange listener(s) found, none of them repaints the "
        "Patterns gate panel -- it will freeze in the boot locale"
    )
    assert not any("loadPatternsGate" in strip_comments(b) for b in bodies), (
        "a language switch must repaint from the cached payload, never re-fetch"
    )


def test_the_renderer_is_separable_from_the_fetch():
    """A renderer that fetches cannot be called from a language switch without asking
    the backend behind the reader, so the split is the load-bearing part, not a tidy-up."""
    render = strip_comments(function_body(app_js(), "_renderPatternsGate"))
    assert "api(" not in render and "await" not in render, (
        "the renderer must be pure -- the fetch belongs in loadPatternsGate"
    )
    load = strip_comments(function_body(app_js(), "loadPatternsGate"))
    assert "_renderPatternsGate()" in load, "the fetch must paint once through the renderer"
