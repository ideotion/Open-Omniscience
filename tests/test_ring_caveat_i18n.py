"""The empty-ring caveat is a fixed template the UI translates (R131, the T5 layout PR).

An empty ring or group carries one of four sentences (every keyword hidden, or none indexed yet, for a ring or a
group). The count in the first is DATA: the server sends the fixed template (``caveat_i18n``) and the values
(``caveat_vars``), the UI fills it with ``OOI18N.tf`` and the template is keyed in all twelve locales, so the frame
reads in the user's language and the number is never part of a key.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.analytics import queries

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "src" / "static" / "locales"
TEMPLATES = [queries._RING_ALL_HIDDEN, queries._RING_NONE_INDEXED]


def test_the_two_templates_say_group_and_only_the_hidden_one_carries_a_count():
    # a ring is a GROUP to the user (the naming sweep): the word "ring" never reaches the screen
    assert len(TEMPLATES) == len(set(TEMPLATES)) == 2
    assert queries._RING_ALL_HIDDEN.count("{n}") == 1 and "{" not in queries._RING_NONE_INDEXED
    assert not any(re.search(r"\bring\b", t, re.I) for t in TEMPLATES)


def test_every_template_is_keyed_in_every_locale_with_its_placeholder_intact():
    for path in sorted(LOCALES.glob("*.json")):
        table = json.loads(path.read_text("utf-8"))
        for template in TEMPLATES:
            assert template in table, f"{path.name} lacks {template[:50]!r}"
            have = re.findall(r"\{(\w+)\}", table[template])
            assert have == re.findall(r"\{(\w+)\}", template), f"{path.name} changes the placeholders of {template[:50]!r}"


def test_the_ring_map_shows_the_caveat_in_its_empty_state_too():
    """An empty ring's payload has no countries, so the branch that draws no map is the one that must carry the
    caveat: otherwise "every keyword is hidden" reads as "no located sources" (the misreading R111 T2 exists to stop)."""
    src = (ROOT / "src" / "static" / "app-insights.js").read_text("utf-8")
    assert "d.caveat_i18n && tf ? tf(d.caveat_i18n, d.caveat_vars) : (d.caveat ? t(d.caveat) : \"\")" in src
    start = src.index("if (!shownCountries) {")
    empty_branch = src[start:src.index("} else {", start)]
    assert "ringCaveat" in empty_branch, "the empty state dropped the caveat"
    assert "caveat: ringCaveat" in src
