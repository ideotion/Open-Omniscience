"""
Reader near-dup "1 voice" badge + UI-language-dependent reader (PR 4a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled 2026-06-17: the offline reader gets the inline "1 voice" near-dup
badge, AND the reader interface becomes UI-language-dependent. The reader is a
standalone server-rendered page; including the i18n engine (same localStorage as
the SPA) makes every keyed string — incl. the badge caption — follow the chosen UI
language. The ≈N count is a language-neutral number; the caption is a keyed string.
"""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MAIN = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
_CAPTION = (
    "Near-identical copies in your corpus — effectively one voice, "
    "not independent confirmation. See Related."
)


def test_reader_loads_the_i18n_engine():
    # The single change that makes the reader UI-language-dependent.
    assert '"/static/i18n.js"' in _MAIN, "the reader must include the i18n engine"


def test_reader_computes_a_bounded_near_dup_badge():
    view = _MAIN.split("async def view_article(", 1)[1].split("\nasync def ", 1)[0]
    assert "near_duplicate_clusters" in view, "the reader badge must use the high-precision clusterer"
    assert "dup_badge" in view and "dup-pill" in view, "the badge markup must be built"
    assert "{dup_badge}" in view, "the badge must be placed into the Read pane"
    # the caption is emitted (source may wrap the literal; the full keyed string is
    # validated against the locales in the next test).
    assert "Near-identical copies in your corpus" in view, "the badge must show the keyed caption"
    # honest, bounded, no score: the count is the cluster size only.
    assert ".limit(40)" in view, "the near-dup candidate pool must be bounded"


def test_badge_caption_is_translated_in_all_locales():
    locales = _ROOT / "src" / "static" / "locales"
    for f in sorted(locales.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert _CAPTION in d, f"{f.name} must carry the badge caption key"
        if f.stem != "en":
            assert d[_CAPTION] != _CAPTION, f"{f.name}: caption should be translated, not English"
