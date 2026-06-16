"""
Tests for the keyword-diagnostics log analyzer (scripts/analyze_keyword_log.py)
and a regression guard for the 2026-06-14 evidence-batch stopword additions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The analyzer is the "ingest a manageable log -> propose optimizations" loop. It
must (a) only propose NET-NEW stopwords (never re-propose an already-filtered
word), (b) keep genuine function words in high-confidence while pushing names /
loan-words that SPREAD across languages to 'review' (signature evidence, not
surface case), (c) detect weekday leaks + sentence-initial false entities, and
(d) cluster cognates only as low-confidence hints. None of it edits source.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load_analyzer():
    path = _ROOT / "scripts" / "analyze_keyword_log.py"
    spec = importlib.util.spec_from_file_location("analyze_keyword_log", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = _load_analyzer()


def _kw(term, *, kind="term", language="de", mentions=10, articles=5, sig=None, mismatch=False):
    return {
        "term": term,
        "normalized": term.casefold(),
        "kind": kind,
        "language": language,
        "mentions": mentions,
        "articles": articles,
        "language_signature": sig if sig is not None else {language: articles},
        "language_mismatch": mismatch,
    }


# --- stopword candidates ----------------------------------------------------- #

def test_stopword_candidate_function_word_is_high_confidence():
    # a short word, concentrated in its own language's articles, not yet listed
    kws = [_kw("zzzfunc", language="de", articles=6, sig={"de": 6})]
    out = A.stopword_candidates(kws, existing=set(), top=10)
    assert out["de"][0]["bucket"] == "high_confidence"


def test_already_listed_word_is_never_reproposed():
    kws = [_kw("zzzfunc", language="de", articles=6)]
    out = A.stopword_candidates(kws, existing={"zzzfunc"}, top=10)
    assert "de" not in out or all(i["normalized"] != "zzzfunc" for i in out["de"])


def test_name_spread_across_languages_goes_to_review_not_high_confidence():
    # "york" stored es but signature is overwhelmingly en -> a spread loan/name
    kws = [_kw("york", language="es", articles=60, sig={"en": 40, "es": 20})]
    out = A.stopword_candidates(kws, existing=set(), top=10)
    assert out["es"][0]["bucket"] == "review"
    assert out["es"][0]["dominant_signature"] == "en"


# --- weekday + tagging + rings ----------------------------------------------- #

def test_weekday_leak_detected_across_languages():
    kws = [_kw("Sunday", kind="entity", language="en"), _kw("sábado", language="es")]
    hits = {h["normalized"] for h in A.weekday_leaks(kws)}
    assert "sunday" in hits and "sábado" in hits


def test_mistagged_entity_flags_lowercase_common_word():
    kws = [_kw("world", kind="entity", language="en", articles=134)]
    flagged = A.mistagged_entities(kws, top=10)
    assert flagged and flagged[0]["term"] == "world"


def test_ring_candidates_cluster_cognates_but_label_low_confidence():
    kws = [
        _kw("minister", language="en", articles=75),
        _kw("ministre", language="fr", articles=20),
        _kw("ministro", language="it", articles=15),
    ]
    rings = A.ring_candidates(kws, existing_members=set(), top=10)
    assert rings, "expected a cognate cluster"
    members = set(rings[0]["members"])
    assert {"en:minister", "fr:ministre", "it:ministro"} <= members
    assert "LOW-CONFIDENCE" in rings[0]["note"]


def test_ring_skips_existing_members():
    kws = [_kw("minister", language="en", articles=75), _kw("ministre", language="fr", articles=20)]
    rings = A.ring_candidates(kws, existing_members={"en:minister"}, top=10)
    # en:minister already a member -> can't form a >=2-language cluster on this prefix
    assert all("en:minister" not in r["members"] for r in rings)


def test_build_proposals_runs_end_to_end():
    doc = {
        "app_version": "0.0.9",
        "kind": "keyword-diagnostics",
        "data": {
            "corpus": {"articles": 2, "sources": 1},
            "keywords": [_kw("zzzfunc", language="de"), _kw("Sunday", kind="entity", language="en")],
            "per_source_concentration": {"suspects": [], "suspects_total": 0},
        },
    }
    p = A.build_proposals(doc, existing=set(), members=set(), top=5)
    for key in (
        "stopword_candidates",
        "weekday_leaks",
        "boilerplate",
        "mistagged_entities",
        "ring_candidates",
        "top_concepts",
        "inflection_pairs",
        "language_mismatch",
    ):
        assert key in p


# --- regression guard: the 2026-06-14 evidence batch is actually filtered ----- #

def test_2026_06_14_evidence_batch_words_are_filtered():
    from src.analytics.extract import global_stopwords

    gs = global_stopwords()
    # representative function words + weekdays from the applied batch, per language
    must_filter = [
        "können", "sondern",          # de
        "dalam", "oleh",              # id
        "szerint", "pedig",           # hu
        "чтобы", "которые",           # ru
        "tudi", "kot",                # sl
        "خلال", "قبل",                # ar
        "pročitajte", "diskusiji",    # sr comment-widget boilerplate
        "sunday", "saturday",          # en weekdays
        "sábado", "lørdag", "vasárnap",  # es/da/hu weekdays
    ]
    missing = [w for w in must_filter if w not in gs]
    assert not missing, f"evidence-batch words not filtered: {missing}"


def test_cross_language_collisions_deliberately_not_filtered():
    # global_stopwords() is unioned across ALL languages, so these meaningful
    # English words must NOT have been added by the batch.
    from src.analytics.extract import _EXTRA_STOPWORDS

    for w in ("sea", "tom", "fin", "laut"):
        assert w not in _EXTRA_STOPWORDS
