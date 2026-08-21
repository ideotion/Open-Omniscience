"""The family identity colour is keyed on the family, not on its position.

Ruling 14 (field feedback 2026-08-07).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The BEHAVIOUR is proven in ``tests/fam_hue_node_test.js``, which extracts the real
``famHue`` from ``app.js`` and feeds families through it. Only the WIRING -- which
argument each call site passes -- is checked here, because that is a source fact the
node suite cannot see: a perfectly correct ``famHue`` called with the loop index
reproduces the whole defect.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.js_source_helper import function_body, object_literal, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


def _render_briefing_and_overview() -> str:
    """The two functions that paint a family colour, COMMENT-STRIPPED.

    Sliced BY NAME through the shared helper, not by "everything between these two
    landmarks": a region bounded by the next declaration someone happens to remember
    sweeps in whatever is written between them, which is how a guard ends up reading
    code it says nothing about.

    Stripped because the fix's own comments necessarily quote the removed
    ``famHue(bi)`` form to explain what changed -- the recorded trap where a
    "must be gone" guard is satisfied by the explanation of the rule it guards.
    """
    app = read_static("app.js")
    return strip_comments(
        function_body(app, "renderBriefing") + "\n" + function_body(app, "_overviewHtml")
    )


def test_every_family_colour_is_keyed_on_the_stable_bucket_name() -> None:
    body = _render_briefing_and_overview()
    calls = [
        body[m : m + 60]
        for m in range(len(body))
        # The DECLARATION lives in this same slice, so skip it: `function famHue(name)`
        # is not a call site and its parameter name is not a call argument.
        if body.startswith("famHue(", m) and not body[:m].rstrip().endswith("function")
    ]
    assert len(calls) >= 4, f"expected the four painting call sites, found {len(calls)}"
    for c in calls:
        arg = c[len("famHue(") :].split(")", 1)[0].strip()
        assert arg == "b.bucket", (
            f"famHue must be called with the stable bucket key, not {arg!r}. "
            "The index is a POSITION: a family with no cards is omitted, so every "
            "family after it shifts and changes colour (ruling 14). `label` is the "
            "TRANSLATED string, so keying on it would recolour families per locale."
        )


def test_the_curated_table_covers_every_shipped_family() -> None:
    """A shipped family must not fall through to the hash fallback: the fallback
    cannot guarantee two families are visually separable, which is the point."""
    from src.briefing.card import BUCKETS

    table = object_literal(read_static("app.js"), "FAM_HUE")
    missing = [b for b in BUCKETS if f"{b}:" not in table]
    assert not missing, f"families with no curated hue: {missing}"


def test_fam_hue_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "fam_hue_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout
