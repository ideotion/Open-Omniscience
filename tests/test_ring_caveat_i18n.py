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
TEMPLATES = [*queries._RING_ALL_HIDDEN.values(), *queries._RING_NONE_INDEXED.values()]


def test_the_four_templates_exist_and_only_the_hidden_ones_carry_a_count():
    assert len(TEMPLATES) == len(set(TEMPLATES)) == 4
    for template in queries._RING_ALL_HIDDEN.values():
        assert template.count("{n}") == 1
    for template in queries._RING_NONE_INDEXED.values():
        assert "{" not in template


def test_every_template_is_keyed_in_every_locale_with_its_placeholder_intact():
    for path in sorted(LOCALES.glob("*.json")):
        table = json.loads(path.read_text("utf-8"))
        for template in TEMPLATES:
            assert template in table, f"{path.name} lacks {template[:50]!r}"
            have = re.findall(r"\{(\w+)\}", table[template])
            assert have == re.findall(r"\{(\w+)\}", template), f"{path.name} changes the placeholders of {template[:50]!r}"


def test_the_ring_map_fills_the_template_with_tf_and_keeps_the_plain_sentence_as_a_fallback():
    src = (ROOT / "src" / "static" / "app-insights.js").read_text("utf-8")
    assert "caveat_i18n" in src and "tf(d.caveat_i18n, d.caveat_vars)" in src
    assert "d.caveat ? t(d.caveat)" in src
