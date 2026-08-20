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

from tests.js_source_helper import read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


def test_the_open_corpus_action_passes_the_cards_provenance() -> None:
    """Ruling 16 is about TRANSPORT: if the card does not hand its provenance to the
    opener, the header is correct and permanently empty."""
    app = strip_comments(read_static("app.js"))
    body = app.split("function cardHtml(", 1)[1].split("\n    function ", 1)[0]
    assert "cardProvenance(c)" in body, (
        "cardHtml must capture the card's provenance for the analysis window"
    )
    for call in ("openCardCorpus(", "openCardCorpusQuery("):
        i = body.index(call)
        args = body[i : i + 400]
        assert "_prov" in args or "cardProvenance(" in args, (
            f"{call} is invoked without the provenance -- the header would stay empty"
        )


def test_the_provenance_carries_every_field_the_ruling_names() -> None:
    app = read_static("app.js")
    fn = app.split("function cardProvenance(", 1)[1].split("\n    function ", 1)[0]
    # card | family | producer | trigger | method | caveat
    for field in ("card:", "bucket:", "family:", "producer:", "trigger:", "method:", "caveat:"):
        assert field in fn, f"cardProvenance drops {field!r} (ruling 16 names all six)"


def test_the_handoff_is_single_use_and_swept() -> None:
    """The transport must not accumulate: a window that is opened consumes its entry,
    and one that never opens is reclaimed by the sweep rather than left forever."""
    app = strip_comments(read_static("app.js"))
    take = app.split("function _anProvTake(", 1)[1].split("\n    function ", 1)[0]
    assert "removeItem" in take, "a consumed handoff must be deleted (single use)"
    stash = app.split("function _anProvStash(", 1)[1].split("\n    function ", 1)[0]
    assert "_anProvSweep()" in stash, "stashing must bound what earlier handoffs left behind"
    sweep = app.split("function _anProvSweep(", 1)[1].split("\n    function ", 1)[0]
    assert "removeItem" in sweep and "_AN_PROV_KEEP" in sweep and "_AN_PROV_MAX_AGE_MS" in sweep, (
        "the sweep must bound BOTH the count and the age"
    )


def test_the_header_survives_a_reload() -> None:
    """The seed is persisted; provenance must ride it, or a reload turns a Lead-opened
    analysis into one that looks self-originated."""
    app = strip_comments(read_static("app.js"))
    save = app.split("function _anSaveTabs(", 1)[1].split("\n    function ", 1)[0]
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
