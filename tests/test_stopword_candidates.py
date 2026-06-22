"""The stopword-candidate digest in the keyword diagnostics log (maintainer
2026-06-18, "full authority on the logging process").

The recursive-improvement loop is "grow the not-a-keyword list". This digest gives
the analyst, per language, the terms that LOOK like function words but aren't
stoplisted yet — short, frequent, ubiquitous (high article spread) — prioritising
languages with no stoplist. It's computed from the survivors the export already
built (zero extra DB cost). Pure helper test -> imports fastapi (CI).
"""

from __future__ import annotations

import src.api.diagnostics as d


def test_stopword_candidates_shape_and_filters():
    # survivors: (keyword_id, mentions, distinct_articles, first_seen, last_seen)
    survivors = [
        (1, 100, 50, None, None),  # short vi term, wide spread        -> candidate
        (2, 200, 80, None, None),  # already stoplisted                -> excluded
        (3, 5, 2, None, None),     # too little article spread (<5)    -> excluded
        (4, 50, 30, None, None),   # an ENTITY                         -> excluded
        (5, 40, 20, None, None),   # term too long (> max len)         -> excluded
        (6, 30, 12, None, None),   # a managed-language (en) candidate -> candidate
    ]
    meta = {
        1: ("ve", "ve", "vi", False, None),
        2: ("the", "the", "en", False, None),
        3: ("rare", "rare", "vi", False, None),
        4: ("ACME", "acme", "vi", True, "org"),
        5: ("supercalifragilistic", "supercalifragilistic", "vi", False, None),
        6: ("xand", "xand", "en", False, None),
    }
    dom_lang = {1: "vi", 2: "en", 3: "vi", 4: "vi", 5: "vi", 6: "en"}
    is_hidden = lambda norm: norm == "the"  # noqa: E731 - 'the' is already stoplisted

    out = d._stopword_candidates(survivors, meta, dom_lang, is_hidden)
    assert set(out) == {"method", "priority_languages", "by_language"}

    vi_terms = [c["normalized"] for c in out["by_language"]["vi"]["candidates"]]
    assert "ve" in vi_terms
    assert "rare" not in vi_terms                 # below the article-spread floor
    assert "acme" not in vi_terms                 # an entity, not a function word
    assert "supercalifragilistic" not in vi_terms  # too long to be a function word
    assert "the" not in str(out["by_language"])    # already stoplisted -> excluded

    # vi has NO stoplist (syllable-segmented) -> flagged and surfaced as a priority language; en is managed.
    assert out["by_language"]["vi"]["status"] == "no_stoplist"
    assert out["by_language"]["en"]["status"] == "functional"
    assert "vi" in out["priority_languages"] and "en" not in out["priority_languages"]
    # Unmanaged (no_stoplist) buckets come FIRST in by_language (the worklist).
    assert list(out["by_language"])[0] == "vi"


def test_stopword_candidates_ranks_by_article_spread():
    survivors = [
        (1, 10, 9, None, None),
        (2, 999, 40, None, None),  # fewer mentions-per-article but WIDER spread -> first
    ]
    meta = {1: ("a", "a", "vi", False, None), 2: ("b", "b", "vi", False, None)}
    out = d._stopword_candidates(survivors, meta, {1: "vi", 2: "vi"}, lambda n: False)
    ranked = [c["normalized"] for c in out["by_language"]["vi"]["candidates"]]
    assert ranked == ["b", "a"]  # widest article spread first
