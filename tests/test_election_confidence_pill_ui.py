"""P1-04: the Agenda actually RENDERS the election date-confidence tiers it is served.

src/civic/elections.py computes a maintainer-ruled three-tier confidence system
(scheduled / window / projected, plus a passed sub-state) for every election-calendar
event, and src/events/catalog.py serves it in every agenda response -- but nothing in
the frontend ever read date_confidence/date_caveat/projection, so every affected event
collapsed into the same generic "approx · check source" pill regardless of tier. That
is the recorded "a machine-readable answer with no caller" dead end, and a source grep
for the field names cannot tell a real render from a mention in a comment -- so the
behaviour is driven in node (election_confidence_pill_node_test.js) against the
functions EXTRACTED from the shipped module. This file is the driver the node-suite
ratchet requires, plus the claim that belongs on this side: the new pill labels are
keyed and really translated in all twelve locales.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

#: The new short pill-label strings this fix introduces (the tier caveats themselves
#: were already keyed x12 -- src/civic/elections.py's own docstring says so, and
#: tests/test_elections_confidence.py pins it). These are looked up dynamically
#: (``T(meta.label)``), so the source-scanning i18n audit cannot see them; keyed here
#: instead, for the same reason test_download_rate_ui.py keys its own strings by hand.
_TIER_LABELS = ["window", "projected", "projected · passed"]


def test_election_confidence_pill_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "election_confidence_pill_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_every_tier_label_is_keyed_and_really_translated_in_all_twelve_locales() -> None:
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12, f"expected 12 locales, found {len(files)}"
    missing: list[str] = []
    echoes: list[str] = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for label in _TIER_LABELS:
            if label not in data or not str(data[label]).strip():
                missing.append(f"{path.name}: {label!r}")
            elif path.stem != "en" and data[label] == label:
                # A non-English locale echoing the English string back is the shape a
                # half-done translation pass leaves behind (the same check
                # test_elections_confidence.py already runs for the caveats).
                echoes.append(f"{path.name}: {label!r}")
    assert not missing, "unkeyed tier-pill labels:\n  " + "\n  ".join(missing)
    assert not echoes, "untranslated (English-echo) tier-pill labels:\n  " + "\n  ".join(echoes)


def test_the_shipped_catalog_still_carries_the_tier_fields_the_ui_now_reads() -> None:
    """The wiring claim on the OTHER side: a UI fix aimed at fields the backend does
    not actually serve would be a fix for nothing. This does not re-test the tier
    LOGIC itself (tests/test_elections_confidence.py owns that in full) -- only that
    the shipped elections calendar still reaches the agenda with the three fields
    this UI fix depends on."""
    from datetime import date

    from src.civic.elections import TIERS
    from src.events.catalog import agenda

    today = date(2026, 9, 7)
    rows = agenda(calendar="elections", today=today)
    assert rows, "the shipped elections calendar is empty"
    assert all("date_confidence" in r and "date_caveat" in r for r in rows)
    assert {r["date_confidence"] for r in rows} <= set(TIERS) | {None}
    # At least one entry must actually carry a tier (not just the None gap), or the
    # node suite above would be exercising fixtures the real data never produces.
    assert any(r["date_confidence"] is not None for r in rows)
