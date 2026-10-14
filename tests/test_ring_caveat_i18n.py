"""The empty-ring caveat is a fixed template the UI translates (R131, the T5 layout PR).

An empty ring or group carries one of four sentences (every keyword hidden, or none indexed yet, for a ring or a
group). The count in the first is DATA: the server sends the fixed template (``caveat_i18n``) and the values
(``caveat_vars``), the UI fills it with ``OOI18N.tf`` and the template is keyed in all twelve locales, so the frame
reads in the user's language and the number is never part of a key.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from src.analytics import queries

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "src" / "static" / "locales"
TEMPLATES = [queries._RING_ALL_HIDDEN, queries._RING_NONE_INDEXED]
# the sentence of a ring that has mention rows: keyed too, and shown in the empty state of an unlocated-only ring
SENTENCES = [*TEMPLATES, queries._RING_COUNTRY_CAVEAT]


def test_the_two_templates_say_group_and_only_the_hidden_one_carries_a_count():
    # a ring is a GROUP to the user (the naming sweep): the word "ring" never reaches the screen
    assert len(TEMPLATES) == len(set(TEMPLATES)) == 2
    assert queries._RING_ALL_HIDDEN.count("{n}") == 1 and "{" not in queries._RING_NONE_INDEXED
    assert not any(re.search(r"\bring\b", t, re.I) for t in TEMPLATES)


def test_every_template_is_keyed_in_every_locale_with_its_placeholder_intact():
    for path in sorted(LOCALES.glob("*.json")):
        table = json.loads(path.read_text("utf-8"))
        for template in SENTENCES:
            assert template in table, f"{path.name} lacks {template[:50]!r}"
            have = re.findall(r"\{(\w+)\}", table[template])
            assert have == re.findall(r"\{(\w+)\}", template), f"{path.name} changes the placeholders of {template[:50]!r}"


def test_the_rendered_states_carry_the_caveat_in_every_locale():
    """showRingMap, extracted from the shipped source, run with the real locale files and the real tf()
    (tests/ring_caveat_node_test.js), for every locale in the directory: the empty state (which draws no map) shows
    the translated sentence with its count, the two causes read differently, a missing tf falls back to the plain
    sentence, a language switch repaints the empty state in the new language (and never resurrects a group no longer on screen), an unlocated-only payload and a ring with no mention rows keep the translated standard caveat, and a
    located payload hands it to the map. The payloads carry the endpoint's own sentence (``_RING_COUNTRY_CAVEAT``)."""
    locales = sorted(p.stem for p in LOCALES.glob("*.json"))
    assert len(locales) >= 12
    proc = subprocess.run(["node", str(ROOT / "tests" / "ring_caveat_node_test.js")],
                          capture_output=True, text=True, check=False,
                          env={**os.environ, "RING_COUNTRY_CAVEAT": queries._RING_COUNTRY_CAVEAT})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # five rendered shapes per locale, plus the four locale-free checks (the two language-switch repaints among them): a loop that ran zero times fails here
    assert f"{5 * len(locales) + 4} passed" in proc.stdout, proc.stdout
