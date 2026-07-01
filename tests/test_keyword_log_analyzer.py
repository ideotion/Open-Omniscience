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


# --- diff mode: measure an optimization's impact between two logs ------------- #


def _doc(keywords, **corpus):
    return {"kind": "keyword-diagnostics", "data": {"corpus": corpus, "keywords": keywords}}


def test_diff_measures_entity_to_term_kind_shift():
    old = _doc([_kw("welt", kind="entity", language="de")])
    new = _doc([_kw("welt", kind="term", language="de")])
    diff = A.diff_logs(old, new, top=10)
    assert diff["kind_shift"]["entity->term"]["count"] == 1
    assert diff["kind_shift"]["term->entity"]["count"] == 0
    assert diff["kind_distribution"]["before"] == {"entity": 1}
    assert diff["kind_distribution"]["after"] == {"term": 1}


def test_diff_detects_gone_and_appeared_keywords():
    old = _doc([_kw("dat", language="nl"), _kw("climate", language="en")])
    new = _doc([_kw("climate", language="en"), _kw("election", language="en")])
    diff = A.diff_logs(old, new, top=10)
    assert {b["term"] for b in diff["gone"]["top"]} == {"dat"}
    assert {b["term"] for b in diff["appeared"]["top"]} == {"election"}


def test_diff_keeps_acronym_distinct_from_word_homograph():
    # The index is case-sensitive on normalized, so "WHO" (acronym) and "who"
    # (word) are different keys — WHO is correctly seen as APPEARED, who unchanged.
    who_org = {"term": "WHO", "normalized": "WHO", "kind": "entity", "language": "en",
               "mentions": 3, "articles": 2, "language_signature": {"en": 2}, "language_mismatch": False}
    old = _doc([_kw("who", kind="term", language="en")])
    new = _doc([who_org, _kw("who", kind="term", language="en")])
    diff = A.diff_logs(old, new, top=10)
    assert "WHO" in {b["term"] for b in diff["appeared"]["top"]}
    assert diff["gone"]["count"] == 0


def test_load_baseline_keys_parses_yaml_keys_without_yaml(tmp_path):
    d = tmp_path / "kb"
    d.mkdir()
    (d / "en.yml").write_text(
        "baseline_keywords:\n  election: {type: event, topic: politics}\n  inflation: {topic: economy}\n",
        encoding="utf-8",
    )
    (d / "fr.yml").write_text(
        '# comment\nbaseline_keywords:\n  "cessez-le-feu": {type: event}\n', encoding="utf-8"
    )
    keys = A.load_baseline_keys(d)
    assert keys["en"] == {"election", "inflation"}
    assert keys["fr"] == {"cessez-le-feu"}  # quoted key, comment skipped


def test_baseline_gaps_proposes_untagged_terms_only():
    kws = [
        _kw("inflation", language="en", kind="term", articles=20),  # already in baseline -> skip
        _kw("protest", language="en", kind="term", articles=15),  # untagged term -> candidate
        _kw("trump", language="en", kind="entity", articles=30),  # entity -> excluded
        _kw("rare", language="en", kind="term", articles=1),  # below min_articles -> skip
    ]
    gaps = A.baseline_gaps(kws, {"en": {"inflation"}}, top=10, min_articles=3)
    assert {x["normalized"] for x in gaps.get("en", [])} == {"protest"}


def test_mistagged_entities_is_acronym_aware():
    # The acronym WHO is the EXPECTED entity shape -> not flagged; a single-word
    # non-acronym entity ("world") is case-noise -> flagged.
    kws = [
        {"term": "WHO", "normalized": "WHO", "kind": "entity", "language": "en", "articles": 5},
        {"term": "world", "normalized": "world", "kind": "entity", "language": "en", "articles": 100},
    ]
    flagged = {h["term"] for h in A.mistagged_entities(kws, top=10)}
    assert "world" in flagged and "WHO" not in flagged


def test_generic_term_candidates_surfaces_high_df_open_class_for_review():
    """The open-class detector: high-df single-word TERMS surviving the stoplist, ranked
    by article-spread — the generic adjectives/nouns a function-word list can't catch.
    Entities, acronyms, proper-noun-suspects, ring members and already-stoplisted words
    are excluded; every survivor is a REVIEW candidate (dual-use is the human's call)."""
    kws = [
        {"term": "system", "normalized": "system", "kind": "term", "language": "en",
         "articles": 500, "mentions": 900},
        {"term": "global", "normalized": "global", "kind": "term", "language": "en",
         "articles": 250, "mentions": 400},
        {"term": "the", "normalized": "the", "kind": "term", "language": "en",
         "articles": 900, "mentions": 5000},  # already-stoplisted -> excluded
        {"term": "NATO", "normalized": "nato", "kind": "entity", "language": "en",
         "articles": 300, "mentions": 500},  # entity -> excluded
        {"term": "Trump", "normalized": "trump", "kind": "term", "language": "en",
         "articles": 400, "mentions": 600},  # proper-noun suspect (initial cap) -> excluded
        {"term": "inflation", "normalized": "inflation", "kind": "term", "language": "en",
         "articles": 120, "mentions": 200},  # ring member -> excluded
    ]
    out = A.generic_term_candidates(kws, existing={"the"}, members={"inflation"}, top=10)
    en = [i["normalized"] for i in out["en"]]
    assert "system" in en and "global" in en
    assert not ({"the", "nato", "trump", "inflation"} & set(en))  # all four excluded
    # ranked by df, self-normalising df_ratio present (~1.0 for the most ubiquitous)
    assert en[0] == "system" and out["en"][0]["df_ratio"] == 1.0


def test_parse_stoplist_reads_vendored_txt_lists(tmp_path):
    """The detector's 'already filtered' baseline must include the vendored per-language
    *.txt lists (line-based), not only quoted tokens in the .py source."""
    d = tmp_path / "stopwords_iso"
    d.mkdir()
    (d / "de.txt").write_text("und\nder\ngestern\n", encoding="utf-8")
    py = tmp_path / "src.py"
    py.write_text('X = {"foo", "bar baz"}\n', encoding="utf-8")
    existing = A.parse_stoplist([d, py])
    assert {"und", "der", "gestern"} <= existing  # line-based .txt in the dir
    assert {"foo", "bar", "baz"} <= existing  # quoted tokens in the .py
