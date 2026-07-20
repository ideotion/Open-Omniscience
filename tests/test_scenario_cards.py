"""Tests for the three no-schema scenario cards (Cards batch E).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

  * disputed_chronology — the SAME story dated differently across DISTINCT sources;
  * story_propagation   — the TEMPORAL cascade of a topic across sources (a shape, never
                          a cause);
  * supply_chain_ripple — a commodity/keyword coverage CO-MOVEMENT (co-occurrence, NEVER
                          causation), FDR-corrected over the pair family.

Every producer must pass the Card schema (no score keys), carry method + caveat + a
trigger + the exact article_ids of its evidence, and measure independence by DISTINCT
sources where that applies.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.briefing.card import Card, assert_no_score_fields
from src.database.models import (
    Article,
    ArticleMentionedDate,
    Base,
    CommodityPrice,  # noqa: F401 - imported so the table is created
    Keyword,
    KeywordMention,
    MarketExtractionRule,
    Source,
)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.api.main import app

    with TestClient(app) as c:
        yield c


_LONG_BODY = (
    "The regional council confirmed on the record that a major infrastructure programme "
    "will proceed across the northern districts, affecting transport, water and power for "
    "tens of thousands of residents over the coming months, according to officials who "
    "briefed reporters at the site and shared the detailed schedule and budget documents."
)


def _add_article(s, *, aid, source_id, content=_LONG_BODY, when=None):
    when = when or datetime.now(UTC)
    s.add(Article(
        id=aid, url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}",
        source_id=source_id, title=f"Story {aid}", content=content, hash=f"h{aid}",
        language="en", published_at=when, created_at=when,
    ))


# =========================================================================== #
#  Disputed chronology
# =========================================================================== #
def test_find_disagreement_pure_agree_disagree_and_self():
    from src.analytics.disputed_chronology import _find_disagreement

    d1, d2 = date(2026, 6, 1), date(2026, 7, 1)
    # Two sources, disjoint dates 30 days apart → a genuine disagreement.
    disputed, involved = _find_disagreement({"A": {d1}, "B": {d2}}, tolerance_days=2)
    assert len(disputed) == 2 and set(involved) == {"A", "B"}
    # Two sources agreeing on the same date → no disagreement.
    disputed2, involved2 = _find_disagreement({"A": {d1}, "B": {d1}}, tolerance_days=2)
    assert disputed2 == [] and involved2 == []
    # One source holding both dates is not a cross-source dispute.
    disputed3, involved3 = _find_disagreement({"A": {d1, d2}}, tolerance_days=2)
    assert disputed3 == [] and involved3 == []


def test_disputed_chronology_fires_across_sources(session):
    from src.analytics.disputed_chronology import find_disputed_chronology

    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    # Two near-identical articles (same story) from two sources; each deduces a
    # DIFFERENT event date, 30 days apart.
    _add_article(s, aid=1, source_id=1)
    _add_article(s, aid=2, source_id=2)
    s.add(ArticleMentionedDate(article_id=1, mentioned_on=date(2026, 6, 1), precision="day",
                               extractor="dateextract", status="candidate"))
    s.add(ArticleMentionedDate(article_id=2, mentioned_on=date(2026, 7, 1), precision="day",
                               extractor="dateextract", status="candidate"))
    s.commit()

    out = find_disputed_chronology(s, lookback_days=36500, min_sources=2, tolerance_days=2)
    assert out["count"] == 1, out
    it = out["items"][0]
    assert it["distinct_sources"] == 2
    assert set(it["disputed_dates"]) == {"2026-06-01", "2026-07-01"}
    assert it["span_days"] == 30
    assert sorted(it["article_ids"]) == [1, 2]
    assert "deduced" in out["caveat"].lower()


def test_disputed_chronology_agreeing_dates_do_not_fire(session):
    from src.analytics.disputed_chronology import find_disputed_chronology

    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    _add_article(s, aid=1, source_id=1)
    _add_article(s, aid=2, source_id=2)
    for aid in (1, 2):
        s.add(ArticleMentionedDate(article_id=aid, mentioned_on=date(2026, 6, 1),
                                   precision="day", extractor="dateextract", status="candidate"))
    s.commit()
    out = find_disputed_chronology(s, lookback_days=36500, min_sources=2, tolerance_days=2)
    assert out["count"] == 0


def test_disputed_chronology_single_source_does_not_fire(session):
    from src.analytics.disputed_chronology import find_disputed_chronology

    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.commit()
    # One source, two near-identical articles disagreeing with ITSELF — not a dispute.
    _add_article(s, aid=1, source_id=1)
    _add_article(s, aid=2, source_id=1)
    s.add(ArticleMentionedDate(article_id=1, mentioned_on=date(2026, 6, 1), precision="day",
                               extractor="dateextract", status="candidate"))
    s.add(ArticleMentionedDate(article_id=2, mentioned_on=date(2026, 7, 1), precision="day",
                               extractor="dateextract", status="candidate"))
    s.commit()
    out = find_disputed_chronology(s, lookback_days=36500, min_sources=2, tolerance_days=2)
    assert out["count"] == 0


def test_disputed_chronology_producer_card(session):
    from src.briefing.producers import disputed_chronology

    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    _add_article(s, aid=1, source_id=1)
    _add_article(s, aid=2, source_id=2)
    s.add(ArticleMentionedDate(article_id=1, mentioned_on=date(2026, 6, 1), precision="day",
                               extractor="dateextract", status="candidate"))
    s.add(ArticleMentionedDate(article_id=2, mentioned_on=date(2026, 7, 1), precision="day",
                               extractor="dateextract", status="candidate"))
    s.commit()

    cards = disputed_chronology(s)
    assert cards, "expected a disputed-chronology card"
    c = cards[0]
    assert isinstance(c, Card) and c.type == "disputed_chronology" and c.bucket == "debunk"
    assert "score" not in c.signal
    assert_no_score_fields(Card)
    assert c.method and c.caveat
    assert sorted(c.article_ids) == [1, 2]
    assert c.trigger and c.trigger["plain"].strip() and c.trigger["math"]


# =========================================================================== #
#  Story propagation
# =========================================================================== #
def _seed_term_cascade(s, term, per_source_offsets):
    """Seed a keyword mentioned across sources with given first-seen day offsets.

    ``per_source_offsets`` maps source_id -> the day offset (days ago) of its FIRST
    mention. Returns the keyword id.
    """
    kw = Keyword(term=term, normalized_term=term, language="en")
    s.add(kw)
    s.flush()
    today = date.today()
    aid = 5000
    for sid, offset in per_source_offsets.items():
        s.add(Source(id=sid, name=f"Src{sid}", domain=f"s{sid}.test", country="us"))
        on = today - timedelta(days=offset)
        _add_article(s, aid=aid, source_id=sid, when=datetime.now(UTC))
        s.add(KeywordMention(keyword_id=kw.id, article_id=aid, source_id=sid, observed_on=on, count=1))
        aid += 1
    s.commit()
    return kw.id


def test_story_propagation_fires_on_temporal_cascade(session):
    from src.analytics.story_propagation import find_story_propagation

    _seed_term_cascade(session, "sanctions", {1: 10, 2: 8, 3: 5})  # span 5 days, 3 sources
    out = find_story_propagation(session, lookback_days=30, min_sources=3, min_span_days=2)
    assert out["count"] == 1, out
    it = out["items"][0]
    assert it["term"] == "sanctions"
    assert it["distinct_sources"] == 3
    assert it["span_days"] == 5
    # The cascade is ordered by first-seen; the earliest source leads.
    assert [c["source"] for c in it["cascade"]] == ["Src1", "Src2", "Src3"]
    assert it["cascade"][0]["gap_days"] == 0 and it["cascade"][1]["gap_days"] == 2
    assert it["article_ids"] and "never a cause" in out["caveat"]


def test_story_propagation_all_at_once_is_not_a_cascade(session):
    from src.analytics.story_propagation import find_story_propagation

    _seed_term_cascade(session, "sanctions", {1: 5, 2: 5, 3: 5})  # same day → span 0
    out = find_story_propagation(session, lookback_days=30, min_sources=3, min_span_days=2)
    assert out["count"] == 0


def test_story_propagation_too_few_sources(session):
    from src.analytics.story_propagation import find_story_propagation

    _seed_term_cascade(session, "sanctions", {1: 10, 2: 5})  # only 2 sources
    out = find_story_propagation(session, lookback_days=30, min_sources=3, min_span_days=2)
    assert out["count"] == 0


def test_story_propagation_producer_card(session):
    from src.briefing.producers import story_propagation

    _seed_term_cascade(session, "sanctions", {1: 10, 2: 8, 3: 5})
    cards = story_propagation(session)
    assert cards
    c = cards[0]
    assert isinstance(c, Card) and c.type == "story_propagation" and c.bucket == "context"
    assert "score" not in c.signal
    assert c.method and c.caveat and c.article_ids
    assert c.signal["metric"] == "distinct_sources" and c.signal["value"] == 3
    assert c.trigger and c.trigger["math"]


def test_story_propagation_generic_furniture_term_is_gated_but_a_real_story_survives(session):
    """2026-07-18 field export (row 4, RTV SLO "vir"/"lani"): a term carried by nearly
    every active same-language source is publishing furniture, not a real topic, even
    when it clears the >= min_sources candidacy bar -- while a genuine story spreading
    across a small minority of the same cohort still surfaces."""
    from src.analytics.story_propagation import find_story_propagation

    s = session
    today = date.today()
    for sid in range(20, 30):  # 10 active sl sources
        s.add(Source(id=sid, name=f"Src{sid}", domain=f"s{sid}.test", language="sl"))
    s.add(Keyword(id=701, term="vir", normalized_term="vir", language="sl"))
    s.add(Keyword(id=702, term="event702", normalized_term="event702", language="sl"))
    s.commit()

    aid = 8000
    # "vir": ubiquitous furniture across 9 of the 10 active sources, same day (no cascade
    # needed -- the gate must stop it before the span check ever runs).
    for sid in range(20, 29):
        s.add(KeywordMention(keyword_id=701, article_id=aid, source_id=sid, observed_on=today, count=1))
        aid += 1
    # "event702": a genuine story spreading across exactly 3 of the same 10 sources, over
    # several days -- a real temporal cascade.
    for sid, offset in ((20, 5), (21, 3), (29, 0)):
        s.add(KeywordMention(
            keyword_id=702, article_id=aid, source_id=sid,
            observed_on=today - timedelta(days=offset), count=1,
        ))
        aid += 1
    s.commit()

    out = find_story_propagation(session, lookback_days=30, min_sources=3, min_span_days=2)
    terms = {it["term"] for it in out["items"]}
    assert "vir" not in terms, out["items"]
    assert "event702" in terms, out["items"]
    assert "DF-ubiquity" in out["method"] or "furniture" in out["method"]


# =========================================================================== #
#  Supply-chain ripple (native Pearson + Fisher-z + BH-FDR)
# =========================================================================== #
def test_pearson_native_values():
    from src.analytics.supply_chain_ripple import _pearson

    assert abs(_pearson([1, 2, 3], [2, 4, 6]) - 1.0) < 1e-9
    assert abs(_pearson([1, 2, 3], [6, 4, 2]) + 1.0) < 1e-9
    assert _pearson([1, 1, 1], [1, 2, 3]) is None  # zero variance → undefined, honest None
    r = _pearson([1, 2, 3, 4], [1, 1, 2, 1])
    assert r is not None and -1.0 <= r <= 1.0


def test_fisher_pvalue_native_monotonic():
    from src.analytics.supply_chain_ripple import _fisher_pvalue

    assert _fisher_pvalue(0.9, 4) is None  # n < 5 → no test
    p_hi = _fisher_pvalue(0.9, 30)
    p_lo = _fisher_pvalue(0.4, 30)
    assert p_hi is not None and p_lo is not None
    assert 0.0 <= p_hi <= 1.0 and p_hi < p_lo  # stronger r → smaller p
    p0 = _fisher_pvalue(0.0, 30)
    assert p0 is not None and p0 > 0.9  # no correlation → p near 1


def _seed_commodity_covariation(s, *, sources=(1, 2, 3)):
    """Seed a tracked commodity 'oil' whose daily coverage co-moves with 'sanctions',
    spread across ``sources`` distinct sources (the independence gate needs >= 3), plus a
    'quiet' keyword active on too few days to be tested."""
    for sid in sources:
        s.add(Source(id=sid, name=f"Market{sid}", domain=f"m{sid}.test", country="us"))
    s.flush()
    s.add(MarketExtractionRule(source_id=sources[0], symbol="OIL", label="Oil",
                               url="https://m.test/oil", selector=".price", category="commodity"))
    oil = Keyword(term="oil", normalized_term="oil", language="en")
    san = Keyword(term="sanctions", normalized_term="sanctions", language="en")
    quiet = Keyword(term="widgetco", normalized_term="widgetco", language="en")
    s.add_all([oil, san, quiet])
    s.flush()
    today = date.today()
    aid = 6000
    # oil and sanctions co-occur in the SAME articles on 8 days (varying counts); the
    # articles rotate across the distinct sources so both terms clear the independence gate.
    counts = {3: 3, 4: 1, 5: 4, 6: 1, 7: 5, 8: 2, 9: 3, 10: 2}
    for offset, n in counts.items():
        on = today - timedelta(days=offset)
        for _ in range(n):
            sid = sources[aid % len(sources)]
            _add_article(s, aid=aid, source_id=sid, when=datetime.now(UTC))
            s.add(KeywordMention(keyword_id=oil.id, article_id=aid, source_id=sid, observed_on=on, count=1))
            s.add(KeywordMention(keyword_id=san.id, article_id=aid, source_id=sid, observed_on=on, count=1))
            aid += 1
    # 'quiet' appears on only 3 days → below min_nonzero_days, never tested.
    for offset in (12, 13, 14):
        on = today - timedelta(days=offset)
        _add_article(s, aid=aid, source_id=sources[0], when=datetime.now(UTC))
        s.add(KeywordMention(keyword_id=quiet.id, article_id=aid, source_id=sources[0], observed_on=on, count=1))
        aid += 1
    s.commit()
    return oil.id, san.id


def test_supply_chain_ripple_surfaces_covariation(session):
    from src.analytics.supply_chain_ripple import find_supply_chain_ripples

    _seed_commodity_covariation(session)
    out = find_supply_chain_ripples(session, window_days=30, r_min=0.5, fdr_q=0.05)
    assert out["count"] >= 1, out
    keywords = {it["keyword"] for it in out["items"]}
    assert "sanctions" in keywords          # the strong co-movement surfaces
    assert "widgetco" not in keywords       # too few non-zero days → never tested
    it = next(it for it in out["items"] if it["keyword"] == "sanctions")
    assert it["commodity"] == "Oil"
    assert it["correlation"] >= 0.5
    assert 0.0 <= it["fdr_qvalue"] <= 1.0
    assert it["article_ids"]                 # the co-occurrence corpus
    # The independence gate is satisfied: both terms are carried by >= 3 distinct sources.
    assert it["distinct_sources_commodity"] >= 3 and it["distinct_sources_keyword"] >= 3
    assert "never causation" in out["caveat"].lower()


def test_supply_chain_ripple_single_source_cannot_manufacture(session):
    """The independence gate: a co-movement carried by ONE chatty source must not surface
    (non-negotiable #3) — even a perfect correlation is gated out below min_sources_per_term."""
    from src.analytics.supply_chain_ripple import find_supply_chain_ripples

    _seed_commodity_covariation(session, sources=(1,))  # oil & sanctions from ONE source
    out = find_supply_chain_ripples(session, window_days=30, r_min=0.5, min_sources_per_term=3)
    assert out["count"] == 0


def test_supply_chain_ripple_no_commodity_is_empty(session):
    from src.analytics.supply_chain_ripple import find_supply_chain_ripples

    # A frequent keyword but NO tracked commodity resolves → honest empty result.
    kw = Keyword(term="sanctions", normalized_term="sanctions", language="en")
    session.add(Source(id=1, name="S", domain="s.test"))
    session.add(kw)
    session.flush()
    today = date.today()
    for i in range(10):
        _add_article(session, aid=7000 + i, source_id=1)
        session.add(KeywordMention(keyword_id=kw.id, article_id=7000 + i, source_id=1,
                                   observed_on=today - timedelta(days=i + 3), count=1))
    session.commit()
    out = find_supply_chain_ripples(session, window_days=30)
    assert out["count"] == 0 and out["items"] == []


def test_supply_chain_ripple_producer_card(session):
    from src.briefing.producers import supply_chain_ripple

    _seed_commodity_covariation(session)
    cards = supply_chain_ripple(session)
    assert cards
    c = cards[0]
    assert isinstance(c, Card) and c.type == "supply_chain_ripple" and c.bucket == "context"
    assert "score" not in c.signal and c.signal["metric"] == "coverage_correlation"
    assert c.method and c.caveat and c.article_ids
    assert c.trigger and c.trigger["math"]


def test_supply_chain_ripple_homograph_resolution_finds_nothing(session):
    """S2.1 (row 13a, 2026-07-18 field export): a commodity labelled "Lead" must NEVER
    silently resolve, via a substring/"significant words" heuristic, to an unrelated
    common-word keyword -- it must resolve to NOTHING (an honest gap, no card) unless
    its OWN exact label/symbol is itself a stored keyword."""
    from src.analytics.supply_chain_ripple import _commodity_keywords, find_supply_chain_ripples

    session.add(Source(id=1, name="Metals", domain="metals.test", country="us"))
    session.flush()
    session.add(MarketExtractionRule(source_id=1, symbol="PB", label="Lead",
                                     url="https://metals.test/lead", selector=".price",
                                     category="commodity"))
    # NOT a keyword named "lead" or "pb" -- only an UNRELATED word that happens to
    # contain "lead" as a substring (the old "significant words" homograph vector).
    kw = Keyword(term="leadership", normalized_term="leadership", language="en")
    session.add(kw)
    session.flush()
    today = date.today()
    for i in range(10):
        _add_article(session, aid=6100 + i, source_id=1)
        session.add(KeywordMention(keyword_id=kw.id, article_id=6100 + i, source_id=1,
                                   observed_on=today - timedelta(days=i + 2), count=1))
    session.commit()

    assert _commodity_keywords(session) == {}  # neither "lead" nor "pb" exists -> no match
    out = find_supply_chain_ripples(session, window_days=30)
    assert out["count"] == 0 and out["items"] == []


def test_supply_chain_ripple_volume_confound_does_not_manufacture_a_pair(session):
    """S2.2 (row 13b): two terms that only both scale with total daily collection
    volume -- a FIXED share of it, every day, active across the whole window -- must
    NOT co-move once correlated on their SHARE of that volume: a busier scraping day
    inflates both terms' raw counts together (the confound a raw-count correlation
    would wrongly reward), but neither term moves RELATIVE to that day's total, so
    there is nothing left to correlate."""
    from src.analytics.supply_chain_ripple import find_supply_chain_ripples

    sources = (1, 2, 3)
    for sid in sources:
        session.add(Source(id=sid, name=f"Vol{sid}", domain=f"vol{sid}.test", country="us"))
    session.flush()
    session.add(MarketExtractionRule(source_id=1, symbol="HG", label="Copper",
                                     url="https://vol.test/copper", selector=".price",
                                     category="commodity"))
    copper = Keyword(term="copper", normalized_term="copper", language="en")
    weather = Keyword(term="weather", normalized_term="weather", language="en")
    filler = Keyword(term="filler", normalized_term="filler", language="en")
    session.add_all([copper, weather, filler])
    session.flush()

    today = date.today()
    aid = 6200
    # A fluctuating daily "scraping volume" driver, one entry per day of the analyzed
    # window (offsets 0..19 -- EVERY day active, no gaps, so there is no on/off pattern
    # to trivially correlate). copper/weather/filler ALWAYS keep the same 30%/20%/50%
    # share of that day's total, so a busier day (higher multiplier) inflates every
    # term's raw count together while none of them moves RELATIVE to the total.
    multipliers = [1, 2, 3, 2, 1, 3, 2, 1, 3, 2, 1, 2, 3, 1, 2, 3, 1, 2, 3, 2, 1]
    for offset, k in enumerate(multipliers):
        on = today - timedelta(days=offset)
        for kw, n in ((copper, 3 * k), (weather, 2 * k), (filler, 5 * k)):
            for _ in range(n):
                sid = sources[aid % len(sources)]
                _add_article(session, aid=aid, source_id=sid, when=datetime.now(UTC))
                session.add(KeywordMention(keyword_id=kw.id, article_id=aid, source_id=sid,
                                           observed_on=on, count=1))
                aid += 1
    session.commit()

    out = find_supply_chain_ripples(
        session, window_days=len(multipliers) - 1, r_min=0.5, fdr_q=0.05
    )
    keywords = {it["keyword"] for it in out["items"]}
    assert "weather" not in keywords, out["items"]
    assert "filler" not in keywords, out["items"]


# =========================================================================== #
#  Endpoints
# =========================================================================== #
def test_scenario_endpoints_are_wired(client):
    for path in (
        "/api/signals/disputed-chronology",
        "/api/signals/story-propagation",
        "/api/signals/supply-chain-ripple",
    ):
        out = client.get(path).json()
        assert "items" in out and "method" in out and "caveat" in out
