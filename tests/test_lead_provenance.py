"""A Lead's provenance travels into its analysis window (rulings 15/16).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The RENDER is proven behaviourally in ``tests/lead_provenance_node_test.js`` against the
real extracted function. Only the source facts a node suite cannot see are checked here:
that the card's Open-corpus action actually PASSES the provenance (a perfect renderer fed
nothing renders nothing), that the transport is single-use, and that the header is
persisted with the seed so a reload does not silently drop it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.js_source_helper import function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


def _call_args(js: str, call: str) -> str:
    """The argument list of the first ``call`` in ``js``, by matching parentheses.

    A balanced scan, so a nested call in an argument cannot end the slice early and a
    long argument cannot run off the end of a fixed window.
    """
    at = js.index(call)
    i = at + len(call) - 1
    depth = 0
    for j in range(i, len(js)):
        if js[j] == "(":
            depth += 1
        elif js[j] == ")":
            depth -= 1
            if depth == 0:
                return js[i + 1 : j]
    raise AssertionError(f"unbalanced parentheses after {call!r}")


def test_the_open_corpus_action_passes_the_cards_provenance() -> None:
    """Ruling 16 is about TRANSPORT: if the card does not hand its provenance to the
    opener, the header is correct and permanently empty."""
    body = strip_comments(function_body(read_static("app.js"), "cardHtml"))
    assert "cardProvenance(c)" in body, (
        "cardHtml must capture the card's provenance for the analysis window"
    )
    # Read each opener's own argument LIST rather than a fixed window of characters after
    # it -- a byte window is a guess about formatting, and it answers about whatever else
    # happens to be nearby.
    for call in ("openCardCorpus(", "openCardCorpusQuery("):
        args = _call_args(body, call)
        assert "_prov" in args or "cardProvenance(" in args, (
            f"{call} is invoked without the provenance -- the header would stay empty"
        )


def test_the_provenance_carries_every_field_the_ruling_names() -> None:
    app = read_static("app.js")
    fn = function_body(app, "cardProvenance")
    # card | family | producer | trigger | method | caveat
    for field in ("card:", "bucket:", "family:", "producer:", "trigger:", "method:", "caveat:"):
        assert field in fn, f"cardProvenance drops {field!r} (ruling 16 names all six)"


def test_the_handoff_is_single_use_and_swept() -> None:
    """The transport must not accumulate: a window that is opened consumes its entry,
    and one that never opens is reclaimed by the sweep rather than left forever."""
    app = strip_comments(read_static("app.js"))
    take = function_body(app, "_anProvTake")
    assert "removeItem" in take, "a consumed handoff must be deleted (single use)"
    stash = function_body(app, "_anProvStash")
    assert "_anProvSweep()" in stash, "stashing must bound what earlier handoffs left behind"
    sweep = function_body(app, "_anProvSweep")
    assert "removeItem" in sweep and "_AN_PROV_KEEP" in sweep and "_AN_PROV_MAX_AGE_MS" in sweep, (
        "the sweep must bound BOTH the count and the age"
    )


def test_the_header_survives_a_reload() -> None:
    """The seed is persisted; provenance must ride it, or a reload turns a Lead-opened
    analysis into one that looks self-originated."""
    app = strip_comments(read_static("app.js"))
    save = function_body(app, "_anSaveTabs")
    assert "prov" in save, "_anSaveTabs must persist the provenance with the seed"


def test_lead_provenance_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "lead_provenance_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout
