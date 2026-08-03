"""The quality export must headline what it MEASURED, not what its own definitions guarantee.

Two real exports from the maintainer's merged 8-instance corpus (2026-08-03, 457 and 473
sources, 34,263 / 35,345 articles) showed the report leading with a number that could not
vary with the data:

  * ``flagged_articles: 14,353`` (41.9%) counts articles in the tail of at least one of 4
    ratios at p10/p90. Eight buckets, each firing on ~10% of the corpus BY THE DEFINITION
    OF A PERCENTILE -- every bucket landed within 2% of every other, and the rate was
    ~42% in every language from hu (n=270) to en (n=21,343). A real quality signal varies
    with the data. This one is a restatement of "10% of things are in the top decile".

  * The genuinely diagnostic quantity -- the CONJUNCTION, ``pathology_furniture_repetition``
    -- was 24 of 34,263, and was buried inside the 14,353 rather than reported.

  * ``furniture_ubiquity_cut`` was 137 against a maximum observed ``cross_source_df`` of
    71, so ``furniture_flagged_sources: 0`` meant "the detector cannot fire", which reads
    identically to "nothing is wrong" in a report that prints the threshold without its
    range.

These tests pin the corrected shape. The tail counts are KEPT -- they are the sampling
frame for the human review sample and they work as one; only their name and prominence
change.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from src.analytics.source_quality import (  # noqa: E402
    build_observed,
    pathology_rate_by_source,
)


def _outlier(article_id: int, source_id: int, *, pathological: bool) -> dict:
    return {
        "article_id": article_id,
        "source_id": source_id,
        "language": "en",
        "unsegmented": False,
        "flagged_dimensions": [{"dimension": "type_token", "value": 0.1, "direction": "low",
                                "baseline": {"median": 0.5, "p10": 0.2, "p90": 0.9,
                                             "p99": 0.95, "mad": 0.1, "n": 100}}],
        "pathology_furniture_repetition": pathological,
    }


# --------------------------------------------------------------------------- #
#  F1 -- the conjunction is the finding; the tail count is a sampling frame
# --------------------------------------------------------------------------- #
def test_the_pathology_rate_counts_only_the_conjunction() -> None:
    """One pathological article in 1,000 is a very different fact from 400 tail-flagged
    ones, and only the first can disqualify a source."""
    outliers = [_outlier(1, 7, pathological=True)]
    outliers += [_outlier(i, 7, pathological=False) for i in range(2, 500)]
    rates = pathology_rate_by_source(outliers, {7: list(range(1, 1001))})
    assert rates[7] == pytest.approx(0.001), "the tail flags leaked into the pathology rate"


def test_a_source_with_no_pathology_is_reported_at_zero_not_omitted() -> None:
    """Dropping the zeros would make "measured, nothing wrong" look identical to "never
    measured" -- which is the distinction this whole report exists to keep."""
    rates = pathology_rate_by_source([], {7: [1, 2, 3], 8: [4]})
    assert rates == {7: 0.0, 8: 0.0}


def test_the_observed_block_reports_the_worst_source_and_the_full_range() -> None:
    """Slice 5's measurement: the export emitted only the per-ARTICLE boolean, so the
    quantity the admission gate decides on could not be read off the report at all."""
    outliers = [_outlier(1, 7, pathological=True), _outlier(2, 7, pathological=True)]
    observed = build_observed(
        cross_df={"world": 3},
        furniture_ubiquity_cut=5,
        outliers=outliers,
        source_to_articles={7: [1, 2, 3, 4], 8: [5, 6]},
    )
    rate = observed["pathology_rate_per_source"]
    assert rate["max"] == pytest.approx(0.5)
    assert rate["n_sources"] == 2, "the clean source must be in the distribution"
    assert rate["worst_sources"][0] == {"source_id": 7, "pathology_rate": 0.5}
    assert all(w["pathology_rate"] > 0 for w in rate["worst_sources"]), (
        "a source with nothing wrong is not a 'worst source'"
    )


# --------------------------------------------------------------------------- #
#  F5 -- a threshold no observation can reach must say so
# --------------------------------------------------------------------------- #
def test_an_unreachable_furniture_cut_is_declared_unreachable() -> None:
    """THE finding this block exists for. With the cut above every observation, a zero
    furniture count means the detector never ran -- not that the corpus is clean."""
    observed = build_observed(
        cross_df={"world": 71, "data": 64, "public": 54},
        furniture_ubiquity_cut=137,          # the operator's real value
        outliers=[],
        source_to_articles={1: [1]},
    )
    df = observed["cross_source_df"]
    assert df["max"] == 71
    assert df["threshold"] == 137
    assert df["reachable"] is False, "an unreachable threshold reported as if it could fire"


def test_a_reachable_cut_is_not_maligned_as_unreachable() -> None:
    """The negative-space twin: a fabricated "cannot fire" would be exactly as dishonest
    as the fabricated "nothing found" it replaces, and would teach an operator to ignore a
    detector that works."""
    observed = build_observed(
        cross_df={"world": 71, "data": 64},
        furniture_ubiquity_cut=20,
        outliers=[],
        source_to_articles={1: [1]},
    )
    assert observed["cross_source_df"]["reachable"] is True


def test_an_empty_corpus_does_not_claim_a_reachable_threshold() -> None:
    """No observations at all is not evidence that the detector works."""
    observed = build_observed(
        cross_df={}, furniture_ubiquity_cut=5, outliers=[], source_to_articles={},
    )
    assert observed["cross_source_df"]["reachable"] is False
    assert observed["pathology_rate_per_source"]["n_sources"] == 0


# --------------------------------------------------------------------------- #
#  F4 -- the audit judges scrapes, and only scrapes
# --------------------------------------------------------------------------- #
def test_synthetic_internal_channels_are_exempt_from_the_ratio_cohorts() -> None:
    """The 100%-outlier cohort in both field exports was led by the app's OWN synthetic
    sources -- 194 hazard records whose "article" is "M 5.0 - Kermadec Islands region".
    They are not scrapes, so "is this source's extraction valid?" is not a question the
    ratios can answer about them, and their presence distorted the baseline every real
    source was judged against."""
    from src.analytics.source_quality import audited_source_ids
    from src.database.models import Source

    sources = {
        1: Source(id=1, name="Le Monde", domain="lemonde.fr"),
        2: Source(id=2, name="USGS", domain="hazard.usgs.local"),
        3: Source(id=3, name="UK law", domain="law.uk.local"),
        4: Source(id=4, name="FR wiki", domain="fr.wikipedia.org"),
    }
    audited, excluded = audited_source_ids(sources)
    assert audited == {1}, "a synthetic internal channel was audited as if it were a scrape"
    assert excluded == {"hazard": 1, "law": 1, "wikipedia": 1}, (
        "the exemption must be counted, not silent"
    )


def test_a_terse_or_atypical_REAL_source_is_still_audited() -> None:
    """THE negative-space case, and the line that keeps the exemption from becoming a way to
    excuse bad scrapes. The exemption is by PROVENANCE CLASS -- an asserted fact about the
    ingest channel -- never by "this source looks unusual". A wire service that publishes
    four-sentence briefs is exactly the kind of source a lazy exemption would swallow."""
    from src.analytics.source_quality import audited_source_ids
    from src.database.models import Source

    sources = {
        1: Source(id=1, name="Terse wire", domain="wire.example", source_type="news"),
        2: Source(id=2, name="Cited find", domain="cited.example", source_type="cited"),
    }
    audited, excluded = audited_source_ids(sources)
    assert audited == {1, 2}, "a real scraped source was exempted"
    assert excluded == {}


def test_quarantined_articles_do_not_count_toward_their_sources_verdict(tmp_path) -> None:
    """The two gates share an input and disagreed about it: the article gate condemns an
    item, and the source gate then counted that same item toward the source's extraction
    verdict AND toward the cohort baseline. Fixing the filter is what makes showing both
    gates in one panel honest."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.analytics.source_quality import collect_article_stats
    from src.database.models import Article, Base, Source

    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True)
    Base.metadata.create_all(engine)
    s = Session(engine, future=True)
    src = Source(name="S", domain="s.example")
    s.add(src)
    s.flush()
    for i, quarantined in enumerate([False, True, True]):
        s.add(Article(
            url=f"https://s.example/{i}", canonical_url=f"https://s.example/{i}",
            source_id=src.id, title="T", content="body", hash=f"h{i}",
            word_count=100, language="en", quarantined=quarantined,
        ))
    s.commit()

    stats = collect_article_stats(s)
    assert len(stats) == 1, "a quarantined article still counted toward its source's audit"


# --------------------------------------------------------------------------- #
#  F3 -- measure the selectors instead of assuming them
# --------------------------------------------------------------------------- #
def test_each_selector_reports_its_own_hit_rate_against_the_control() -> None:
    """The expensive selector cost ~90% of the human review budget for 1.64x chance on the
    field corpus, and nothing in the export said so. Now it has to."""
    from src.analytics.source_quality import selector_enrichment

    records = [
        {"selection_method": ["random_per_source"], "pre_label": []},
        {"selection_method": ["random_per_source"], "pre_label": ["very_short:12"]},
        {"selection_method": ["keyword_outlier"], "pre_label": ["very_short:8"]},
        {"selection_method": ["keyword_outlier"], "pre_label": ["high_link_density:0.4"]},
        {"selection_method": ["keyword_outlier"], "pre_label": []},
        {"selection_method": ["keyword_outlier"], "pre_label": []},
    ]
    per = selector_enrichment(records)
    assert per["random_per_source"]["rate"] == pytest.approx(0.5)
    assert per["keyword_outlier"]["rate"] == pytest.approx(0.5)
    assert per["keyword_outlier"]["enrichment_over_control"] == pytest.approx(1.0)
    assert per["random_per_source"]["enrichment_over_control"] is None, (
        "the control cannot be enriched over itself"
    )


def test_a_selector_that_sampled_nothing_reports_null_not_zero() -> None:
    """The retired `source_fingerprint` selector is exactly this case. A selector that never
    ran must not report a 0% hit-rate, which reads as "it looked and found nothing"."""
    from src.analytics.source_quality import selector_enrichment

    per = selector_enrichment([{"selection_method": ["random_per_source"], "pre_label": []}])
    assert per["random_per_source"]["rate"] is None or per["random_per_source"]["rate"] == 0.0
    assert "source_fingerprint" not in per


def test_enrichment_is_not_fabricated_when_the_control_found_nothing() -> None:
    """NEGATIVE SPACE, and the one the brief names: the enrichment figure is meaningless
    unless the control is genuinely unbiased and genuinely measured. A control that hit zero
    would make every other selector look infinitely good if the ratio were computed anyway."""
    from src.analytics.source_quality import selector_enrichment

    per = selector_enrichment([
        {"selection_method": ["random_per_source"], "pre_label": []},
        {"selection_method": ["keyword_outlier"], "pre_label": ["very_short:3"]},
    ])
    assert per["random_per_source"]["rate"] == 0.0
    assert per["keyword_outlier"]["enrichment_over_control"] is None, (
        "an enrichment ratio was fabricated against a control that found nothing"
    )


def test_the_cheap_signal_selector_and_the_pre_label_agree(tmp_path) -> None:
    """They must fire on the same articles, or the enrichment figure compares a selector
    against a label that means something else. Shared constants, pinned behaviourally."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.analytics.source_quality import _pre_label, select_cheap_signals
    from src.database.models import Article, ArticleLink, Base, Source

    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True)
    Base.metadata.create_all(engine)
    s = Session(engine, future=True)
    src = Source(name="S", domain="s.example")
    s.add(src)
    s.flush()
    # 1: very short.  2: link-dense.  3: an ordinary article (must NOT be selected).
    for i, wc in ((1, 10), (2, 100), (3, 400)):
        s.add(Article(url=f"https://s.example/{i}", canonical_url=f"https://s.example/{i}",
                      source_id=src.id, title="T", content="body", hash=f"h{i}",
                      word_count=wc, language="en"))
    s.flush()
    for _ in range(20):
        s.add(ArticleLink(article_id=2, url="https://x.example",
                          normalized_url="x.example", link_type="external"))
    s.add(ArticleLink(article_id=3, url="https://x.example",
                      normalized_url="x.example", link_type="external"))
    s.commit()

    chosen = select_cheap_signals(s, {int(src.id)})
    assert chosen == {1, 2}, "the cheap selector picked the wrong articles"
    assert 3 not in chosen, "an ordinary article was selected as a cheap signal"
    # and the label agrees on each, using the same thresholds
    assert _pre_label(None, word_count=10, external_links=0), "very_short must label"
    assert _pre_label(None, word_count=100, external_links=20), "link density must label"
    assert not _pre_label(None, word_count=400, external_links=1), "ordinary must not label"
