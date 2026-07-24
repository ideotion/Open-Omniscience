"""
Tests for the LLM source-tag-assignment CORE (design entry + GO ruling,
maintainer 2026-07-20) -- mirrors ``tests/test_keyword_triage.py``'s shape.

The negative-space cases (out-of-vocabulary tag / hallucinated domain / an
empty-evidence source) are mandatory for a closed-set parser (the same #590
lesson triage.py's tests already cover); the EVIDENCE FLOOR and the explicit
'none' verdict are this module's own additions and get their own tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import source_tags as ST
from src.database.models import Article, Base, Keyword, KeywordMention, Source


# --------------------------------------------------------------------------- #
# The self-test (the exported mechanism proof).
# --------------------------------------------------------------------------- #
def test_selftest_passes():
    r = ST.run_source_tags_selftest()
    assert r["passed"] is True, r["checks"]
    assert r["schema"] == "oo-source-tags-selftest-1"


# --------------------------------------------------------------------------- #
# parse_source_tags -- the closed-vocabulary parser + echo-back (negative space).
# --------------------------------------------------------------------------- #
def test_parse_happy_path_multiple_tags():
    pb = ST.parse_source_tags(
        "a.com :: sports|finance", ["a.com"], ["sports", "finance", "technology"]
    )
    assert pb.tags["a.com"] == ("finance", "sports")  # sorted, deduped
    assert pb.parse_failures == 0


def test_explicit_none_is_a_valid_verdict_not_a_parse_failure():
    pb = ST.parse_source_tags("a.com :: none", ["a.com"], ["sports"])
    assert pb.tags["a.com"] == ()
    assert pb.none_count == 1
    assert pb.assigned_count == 0
    assert pb.parse_failures == 0
    assert "a.com" not in pb.missing  # 'none' is stored, distinct from missing


def test_out_of_vocabulary_tag_rejects_the_whole_line_never_partial():
    # 'startups' is not in the vocabulary -- the model also said 'technology'
    # (which IS valid), but the WHOLE line must be rejected, never half-stored.
    pb = ST.parse_source_tags("a.com :: technology|startups", ["a.com"], ["technology", "sports"])
    assert "a.com" not in pb.tags
    assert "technology" not in pb.tags.get("a.com", ())  # nothing partial stored
    assert pb.parse_failures == 1
    assert "a.com" in pb.missing


def test_hallucinated_domain_is_rejected():
    pb = ST.parse_source_tags("ghost.example :: sports", ["real.example"], ["sports"])
    assert "ghost.example" not in pb.tags
    assert pb.parse_failures == 1


def test_ambiguous_tag_fold_is_rejected_never_guessed():
    # two vocabulary entries fold to the SAME normalized key -- never silently
    # collapse a model's answer onto one of them (the same lesson triage.py's
    # Straße/Strasse case tests).
    pb = ST.parse_source_tags("a.com :: strasse", ["a.com"], ["Straße", "STRASSE"])
    assert "a.com" not in pb.tags
    assert pb.parse_failures == 1


def test_missing_source_is_counted_when_model_gives_no_line():
    pb = ST.parse_source_tags("a.com :: sports", ["a.com", "b.com"], ["sports"])
    assert pb.tagged_out == 1
    assert pb.missing == ["b.com"]


def test_duplicate_line_first_valid_wins():
    raw = "a.com :: sports\na.com :: finance"
    pb = ST.parse_source_tags(raw, ["a.com"], ["sports", "finance"])
    assert pb.tags["a.com"] == ("sports",)


# --------------------------------------------------------------------------- #
# Canaries -- vocabulary-conditional evaluation (never assert a tag the corpus
# doesn't have; a canary applies only when its expected tag exists live).
# --------------------------------------------------------------------------- #
def test_canary_fails_when_expected_tag_present_but_not_proposed():
    pb = ST.ParsedSourceBatch(tags={"canary.example": ()}, sources_in=1)
    out = ST.check_source_canaries(
        pb, {"canary.example": frozenset({"sports"})}, vocabulary=["sports"]
    )
    assert out["ok"] is False
    assert out["checked"] == 1
    assert out["failed"][0]["domain"] == "canary.example"


def test_canary_is_skipped_not_failed_when_its_tag_is_out_of_this_installs_vocabulary():
    pb = ST.ParsedSourceBatch(tags={}, sources_in=0)
    out = ST.check_source_canaries(
        pb, {"canary.example": frozenset({"sports"})}, vocabulary=["finance"]
    )
    assert out["ok"] is True  # nothing APPLICABLE failed
    assert out["checked"] == 0
    assert out["skipped"] and out["skipped"][0]["domain"] == "canary.example"


def test_canary_passes_with_extra_correct_tags_beyond_the_expected_subset():
    pb = ST.ParsedSourceBatch(tags={"canary.example": ("finance", "government")}, sources_in=1)
    out = ST.check_source_canaries(
        pb, {"canary.example": frozenset({"finance"})}, vocabulary=["finance", "government"]
    )
    assert out["ok"] is True and out["checked"] == 1


# --------------------------------------------------------------------------- #
# resolve_tag_vocabulary + select_source_tag_candidates -- the EVIDENCE FLOOR,
# on an in-memory corpus (mirrors test_source_enrichment.py's fixture style).
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed_source_with_articles(db, *, domain, tags, n_articles, term="football", stopword=False):
    src = Source(name=domain, domain=domain, tags=tags)
    db.add(src)
    db.flush()
    kw = Keyword(term=("the" if stopword else term), normalized_term=term, language="en")
    db.add(kw)
    db.flush()
    for i in range(n_articles):
        a = Article(
            url=f"https://{domain}/{i}",
            canonical_url=f"https://{domain}/{i}",
            source_id=src.id,
            title="T",
            content=term,
            hash=f"{domain}-h{i}",
        )
        db.add(a)
        db.flush()
        db.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=2, source_id=src.id))
    db.commit()
    return src


def test_resolve_vocabulary_is_the_live_distinct_tag_set(db):
    _seed_source_with_articles(db, domain="a.test", tags="sports, us", n_articles=1)
    _seed_source_with_articles(db, domain="b.test", tags="technology", n_articles=1)
    vocab = ST.resolve_tag_vocabulary(db)
    assert vocab == ["sports", "technology", "us"]


def test_evidence_floor_skips_a_source_below_min_articles_never_a_guess(db):
    _seed_source_with_articles(db, domain="thin.test", tags=None, n_articles=1)
    items, skipped, _last_domain = ST.select_source_tag_candidates(db, min_articles=3)
    assert items == []
    assert skipped[0].domain == "thin.test"
    assert skipped[0].reason == "insufficient evidence"


def test_a_source_with_zero_keyword_mentions_is_an_honest_skip_not_a_silent_drop(db):
    # a source with NO keyword_mentions rows at all must still be REPORTED as a
    # skip -- never silently absent from both items and skipped.
    src = Source(name="empty.test", domain="empty.test", tags="news")
    db.add(src)
    db.commit()
    items, skipped, _last_domain = ST.select_source_tag_candidates(db, min_articles=1)
    domains_seen = {i.domain for i in items} | {s.domain for s in skipped}
    assert "empty.test" in domains_seen
    assert any(s.domain == "empty.test" and s.reason == "insufficient evidence" for s in skipped)


def test_source_with_only_stoplisted_terms_is_skipped_not_sent_as_content(db):
    _seed_source_with_articles(db, domain="junk.test", tags=None, n_articles=5, stopword=True)
    items, skipped, _last_domain = ST.select_source_tag_candidates(db, min_articles=1)
    assert items == []
    assert any(
        s.domain == "junk.test" and s.reason == "no content terms after stoplist" for s in skipped
    )


def test_a_source_with_real_evidence_is_a_candidate_with_its_top_terms(db):
    _seed_source_with_articles(
        db, domain="ok.test", tags=None, n_articles=5, term="quarterly earnings"
    )
    items, skipped, _last_domain = ST.select_source_tag_candidates(db, min_articles=3)
    assert len(items) == 1
    assert items[0].domain == "ok.test"
    assert "quarterly earnings" in items[0].top_terms
    assert skipped == []
