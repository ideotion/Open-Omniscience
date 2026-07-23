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
import re
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
    # S2.5 (2026-07-12) made view_article a plain ``def`` (Starlette threadpool, so the
    # synchronous DB + SQLCipher-codec work no longer freezes the event loop). Slice its
    # body from the def up to the next TOP-LEVEL def — async or not — so this source anchor
    # survives that and any further def-conversion instead of silently IndexError-ing.
    after = _MAIN.split("def view_article(", 1)[1]
    view = re.split(r"\n(?:async )?def ", after, maxsplit=1)[0]
    assert "near_duplicate_clusters" in view, "the reader badge must use the high-precision clusterer"
    assert "dup_badge" in view and "dup-pill" in view, "the badge markup must be built"
    assert "{dup_badge}" in view, "the badge must be placed into the Read pane"
    # the caption is emitted (source may wrap the literal; the full keyed string is
    # validated against the locales in the next test).
    assert "Near-identical copies in your corpus" in view, "the badge must show the keyed caption"
    # honest, bounded, no score: the count is the cluster size only. Reads
    # KeywordMention (the real per-article extraction chokepoint), NOT the legacy,
    # never-written article_keyword_association table (P0 fix,
    # reader-dead-legacy-table-related) -- and the candidate cap is tightened to 12
    # (from an earlier 40) so the per-page-view MinHash decrypt stays bounded
    # (reader-dupbadge-n-plus-1-decrypt-risk).
    assert "KeywordMention" in view, "the badge must read the real keyword-mention table"
    # the dead legacy table is only mentioned in an explanatory comment now (why it
    # was replaced) -- it must never be IMPORTED/queried as the candidate source.
    assert "import article_keyword_association" not in view, (
        "the badge must not import/query the dead legacy table"
    )
    assert ".limit(12)" in view, "the near-dup candidate pool must be bounded"


def test_badge_caption_is_translated_in_all_locales():
    locales = _ROOT / "src" / "static" / "locales"
    for f in sorted(locales.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert _CAPTION in d, f"{f.name} must carry the badge caption key"
        if f.stem != "en":
            assert d[_CAPTION] != _CAPTION, f"{f.name}: caption should be translated, not English"
