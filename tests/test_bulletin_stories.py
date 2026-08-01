"""
Story clusters — what a narrated paragraph is about.

The grouping is LEXICAL, by the trusted keyword index, and these tests pin that
honestly: they prove it joins articles sharing vocabulary, prove it does NOT join
unrelated ones, and prove the payload states the two failure modes that follow
from grouping by words rather than hiding them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.bulletin.period import resolve_period
from src.bulletin.stories import (
    article_keyword_sets,
    build_stories,
    cluster_articles,
    story_evidence,
)
from src.database.models import Article, Base, Keyword, KeywordMention, Source

_P = resolve_period("weekly", end=date(2026, 8, 1))
_DAY = "2026-07-27"


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(s, spec: dict[str, list[str]], *, day: str = _DAY, sources: dict | None = None):
    """spec: {article label: [keyword terms]}. One article per label."""
    srcs = {}
    for name in (sources or {}).values():
        if name not in srcs:
            o = Source(name=name, domain=f"{name}.test")
            s.add(o)
            s.flush()
            srcs[name] = o
    if not srcs:
        o = Source(name="Only", domain="only.test")
        s.add(o)
        s.flush()
        srcs["Only"] = o

    kws: dict[str, Keyword] = {}
    ids: dict[str, int] = {}
    for i, (label, terms) in enumerate(spec.items(), start=1):
        src = srcs[(sources or {}).get(label, next(iter(srcs)))]
        art = Article(
            url=f"https://x/{i}",
            canonical_url=f"https://x/{i}",
            source_id=src.id,
            title=f"Article {label}",
            # Comfortably longer than any per-article budget these tests use, so a
            # truncation assertion tests the code rather than the fixture length.
            content=f"Body of {label}. " * 200,
            hash=f"{i:064d}",
            published_at=datetime.fromisoformat(f"{day} 12:00:00"),
            quarantined=False,
        )
        s.add(art)
        s.flush()
        ids[label] = art.id
        for t in terms:
            if t not in kws:
                k = Keyword(term=t, normalized_term=t)
                s.add(k)
                s.flush()
                kws[t] = k
            s.add(
                KeywordMention(
                    keyword_id=kws[t].id,
                    article_id=art.id,
                    count=1,
                    observed_on=date.fromisoformat(day),
                    source_id=src.id,
                )
            )
    s.commit()
    return ids


# -- the grouping ----------------------------------------------------------- #


def test_articles_sharing_vocabulary_become_one_story():
    s = _session()
    shared = ["flood", "valencia", "evacuation", "rainfall"]
    ids = _seed(s, {"a": shared, "b": shared, "c": ["election", "ballot", "turnout", "senate"]})
    out = build_stories(s, _P)
    clusters = [set(st["article_ids"]) for st in out["stories"]]
    assert {ids["a"], ids["b"]} in clusters
    assert not any(ids["c"] in c for c in clusters), "an unrelated article must not be joined"


def test_a_lone_article_is_not_a_story():
    """One article is an article. Calling it a story would inflate the shape of
    the period."""
    s = _session()
    _seed(s, {"a": ["flood", "valencia", "evacuation", "rainfall"]})
    assert build_stories(s, _P)["stories"] == []


def test_a_single_source_cluster_is_flagged_as_repetition_not_corroboration():
    s = _session()
    shared = ["flood", "valencia", "evacuation", "rainfall"]
    _seed(s, {"a": shared, "b": shared}, sources={"a": "Solo", "b": "Solo"})
    story = build_stories(s, _P)["stories"][0]
    assert story["single_source"] is True
    assert story["distinct_sources"] == 1


def test_several_sources_are_counted_as_several():
    s = _session()
    shared = ["flood", "valencia", "evacuation", "rainfall"]
    _seed(s, {"a": shared, "b": shared}, sources={"a": "One", "b": "Two"})
    story = build_stories(s, _P)["stories"][0]
    assert story["single_source"] is False
    assert story["distinct_sources"] == 2
    assert sorted(story["sources"]) == ["One", "Two"]


def test_the_shared_terms_are_reported_so_the_grouping_is_inspectable():
    s = _session()
    shared = ["flood", "valencia", "evacuation", "rainfall"]
    _seed(s, {"a": shared, "b": shared})
    assert set(build_stories(s, _P)["stories"][0]["shared_terms"]) == set(shared)


def test_only_in_period_articles_are_grouped():
    s = _session()
    shared = ["flood", "valencia", "evacuation", "rainfall"]
    _seed(s, {"a": shared, "b": shared}, day="2026-08-05")
    assert build_stories(s, _P)["stories"] == []


def test_the_grouping_is_deterministic_across_runs():
    """An edition regenerated from its record must come out the same."""
    s = _session()
    shared = ["flood", "valencia", "evacuation", "rainfall"]
    _seed(s, {"a": shared, "b": shared, "c": shared})
    first = build_stories(s, _P)["stories"]
    second = build_stories(s, _P)["stories"]
    assert [st["article_ids"] for st in first] == [st["article_ids"] for st in second]


# -- the pure clusterer ----------------------------------------------------- #


def test_the_threshold_decides_and_is_reported():
    sets = {1: {1, 2, 3, 4}, 2: {1, 2, 3, 9}}  # jaccard 3/5 = 0.6
    assert cluster_articles(sets, threshold=0.5) == [[1, 2]]
    assert cluster_articles(sets, threshold=0.7) == []


def test_an_article_with_no_keywords_never_joins_anything():
    sets = {1: {1, 2, 3}, 2: set(), 3: {1, 2, 3}}
    assert cluster_articles(sets) == [[1, 3]]


def test_transitive_overlap_forms_one_cluster_not_three():
    sets = {1: {1, 2, 3}, 2: {2, 3, 4}, 3: {3, 4, 5}}
    out = cluster_articles(sets, threshold=0.4)
    assert len(out) == 1 and out[0] == [1, 2, 3]


def test_an_out_of_range_threshold_is_refused():
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        cluster_articles({1: {1}}, threshold=1.5)


def test_clusters_come_back_largest_first_deterministically():
    sets = {1: {1, 2}, 2: {1, 2}, 3: {8, 9}, 4: {8, 9}, 5: {8, 9}}
    assert cluster_articles(sets, threshold=0.9) == [[3, 4, 5], [1, 2]]


# -- bounds are disclosed, counts are not changed --------------------------- #


def test_a_bounded_comparison_says_so_and_leaves_the_period_count_intact():
    """A cap bounds WHICH articles were compared. It never bounds a reported count,
    and the payload states both numbers."""
    s = _session()
    shared = ["flood", "valencia", "evacuation", "rainfall"]
    _seed(s, {chr(97 + i): shared for i in range(6)})
    out = build_stories(s, _P, max_articles=3)
    assert out["articles_in_period"] == 6
    assert out["articles_compared"] == 3
    assert out["comparison_bounded"] is True
    assert "of 6" in out["caveat"] or "6 in-period" in out["caveat"]


def test_an_unbounded_run_does_not_claim_to_be_bounded():
    s = _session()
    shared = ["flood", "valencia", "evacuation", "rainfall"]
    _seed(s, {"a": shared, "b": shared})
    out = build_stories(s, _P, max_articles=1000)
    assert out["comparison_bounded"] is False
    assert "in-period articles were compared" not in out["caveat"]


def test_the_shown_limit_is_separate_from_the_number_found():
    s = _session()
    _seed(
        s,
        {
            "a": ["p", "q", "r", "s"],
            "b": ["p", "q", "r", "s"],
            "c": ["t", "u", "v", "w"],
            "d": ["t", "u", "v", "w"],
        },
    )
    out = build_stories(s, _P, limit=1)
    assert out["stories_found"] == 2
    assert out["stories_shown"] == 1 == len(out["stories"])


def test_the_caveat_states_both_failure_modes_of_grouping_by_words():
    out = build_stories(_session(), _P)
    assert "split one story told in two languages" in out["caveat"]
    assert "join two unrelated stories that share a vocabulary" in out["caveat"]


def test_no_score_shaped_field():
    s = _session()
    shared = ["flood", "valencia", "evacuation", "rainfall"]
    _seed(s, {"a": shared, "b": shared})
    flat = json.dumps(build_stories(s, _P), default=str).lower()
    for banned in ("score", "ranking", "rating", "grade"):
        assert f'"{banned}"' not in flat and f'_{banned}"' not in flat


# -- the evidence a story is narrated from ---------------------------------- #


def test_evidence_names_exactly_the_articles_it_covers():
    """A sentence's provenance must name what it could have come from, not the
    whole cluster."""
    s = _session()
    ids = _seed(s, {"a": ["x"], "b": ["x"], "c": ["x"]})
    ev = story_evidence(s, [ids["a"], ids["b"], ids["c"]], budget_chars=900)
    assert ev["article_ids"] == sorted(ev["article_ids"])
    assert set(ev["article_ids"]) <= {ids["a"], ids["b"], ids["c"]}
    assert ev["articles_covered"] == len(ev["excerpts"])


def test_the_budget_is_respected_and_truncation_is_marked():
    s = _session()
    ids = _seed(s, {"a": ["x"], "b": ["x"]})
    ev = story_evidence(s, [ids["a"], ids["b"]], budget_chars=900)
    assert ev["chars"] <= ev["budget_chars"] + 1
    assert any(e["truncated"] for e in ev["excerpts"]), "long bodies must be marked truncated"


def test_an_article_the_budget_never_reached_is_not_claimed_as_evidence():
    s = _session()
    ids = _seed(s, {chr(97 + i): ["x"] for i in range(6)})
    ev = story_evidence(s, list(ids.values()), budget_chars=500)
    assert ev["articles_covered"] < ev["articles_requested"]
    assert len(ev["article_ids"]) == ev["articles_covered"]
    assert "NOT part of the evidence" in ev["caveat"]


def test_an_unreadable_article_never_loses_the_story(monkeypatch):
    s = _session()
    ids = _seed(s, {"a": ["x"], "b": ["x"]})
    real = Article.get_content

    def _boom(self):
        if self.id == ids["a"]:
            raise RuntimeError("content unreadable")
        return real(self)

    monkeypatch.setattr(Article, "get_content", _boom)
    ev = story_evidence(s, [ids["a"], ids["b"]], budget_chars=900)
    assert ids["a"] not in ev["article_ids"]
    assert ids["b"] in ev["article_ids"]


def test_keyword_sets_are_read_without_touching_article_text(monkeypatch):
    """The grouping must cost no article decrypt — that is what makes it cheap
    enough to run over a whole period."""
    s = _session()
    _seed(s, {"a": ["x", "y"], "b": ["x", "y"]})
    monkeypatch.setattr(
        Article, "get_content", lambda self: (_ for _ in ()).throw(AssertionError("decrypted!"))
    )
    assert len(article_keyword_sets(s, _P)) == 2
    build_stories(s, _P)  # must not raise
