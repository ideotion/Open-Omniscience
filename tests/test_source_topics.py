"""Tests for the corpus-derived source topic fingerprint (pure aggregation)."""

from src.analytics.source_topics import aggregate_source_topics


def test_applies_min_articles_floor():
    rows = [
        ("a.com", "politics", 10),
        ("a.com", "sports", 2),  # below floor=5 -> dropped
        ("b.com", "science", 3),  # whole source below floor -> no row
    ]
    out = aggregate_source_topics(rows, min_articles=5)
    assert len(out) == 1
    assert out[0]["domain"] == "a.com"
    assert out[0]["topics"] == ["politics"]


def test_topics_ranked_by_article_count_and_capped_at_top_n():
    rows = [
        ("a.com", "politics", 30),
        ("a.com", "economy", 20),
        ("a.com", "science", 10),
        ("a.com", "health", 6),
        ("a.com", "climate", 8),
    ]
    out = aggregate_source_topics(rows, min_articles=5, top_n=3)
    assert out[0]["topics"] == ["politics", "economy", "science"]  # by count desc (30,20,10)


def test_confidence_is_medium_when_strong_else_low_never_high():
    strong = aggregate_source_topics([("a.com", "politics", 15)], min_articles=5, strong_factor=3)
    weak = aggregate_source_topics([("b.com", "politics", 6)], min_articles=5, strong_factor=3)
    assert strong[0]["confidence"] == "medium"  # 15 >= 5*3
    assert weak[0]["confidence"] == "low"       # 6 < 15
    # deduced is never asserted as high
    assert all(r["confidence"] != "high" for r in strong + weak)


def test_rows_carry_deduced_provenance_note():
    out = aggregate_source_topics([("a.com", "politics", 9)], min_articles=5)
    assert out[0]["note"] == "deduced:corpus"


def test_counts_for_same_topic_accumulate_and_empty_is_safe():
    out = aggregate_source_topics([("a.com", "politics", 3), ("a.com", "politics", 4)], min_articles=5)
    assert out[0]["topics"] == ["politics"]  # 3+4=7 >= 5
    assert aggregate_source_topics([]) == []
    assert aggregate_source_topics([("a.com", "", 9), ("a.com", "x", None)]) == []


def test_output_is_deterministic_across_domains():
    rows = [("z.com", "a", 9), ("a.com", "b", 9)]
    out = aggregate_source_topics(rows, min_articles=5)
    assert [r["domain"] for r in out] == ["a.com", "z.com"]  # sorted
