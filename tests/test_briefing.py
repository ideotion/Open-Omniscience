"""
Tests for the briefing card framework, producers, cache and draft.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Covers the §6 honesty guard (no composite-score field), the "now" producers over a
small indexed corpus, the precompute/cache + dismiss flow, and the card→draft→Markdown
export. The DB is in-memory; cache/draft/dismiss state is isolated via OO_DATA_DIR.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.briefing import draft as draft_store
from src.briefing import service
from src.briefing.card import Card, CardSchemaError, assert_no_score_fields
from src.database.models import Article, Base, Source


# --------------------------------------------------------------------------- #
#  §6 honesty guard — no composite trust/quality score, enforced in code
# --------------------------------------------------------------------------- #
def test_card_has_no_score_field():
    # The guard runs at import; assert it still holds for the live Card.
    assert_no_score_fields(Card)
    names = set(Card.__dataclass_fields__)
    for banned in ("score", "trust_score", "credibility", "rating", "verdict"):
        assert banned not in names


def test_assert_no_score_fields_rejects_a_score_field():
    @dataclass
    class Bad:
        trust_score: float = 0.0

    with pytest.raises(CardSchemaError):
        assert_no_score_fields(Bad)


def test_card_rejects_unknown_bucket():
    with pytest.raises(ValueError):
        Card(type="x", title="t", summary="s", bucket="not-a-bucket", method="m", caveat="c")


def test_card_stable_id_from_type_and_key():
    a = Card(
        type="rising",
        title="A",
        summary="s",
        bucket="rising",
        method="m",
        caveat="c",
        key="election",
    )
    b = Card(
        type="rising",
        title="DIFFERENT",
        summary="s",
        bucket="rising",
        method="m",
        caveat="c",
        key="election",
    )
    assert a.id == b.id  # identity is type+key, not the (volatile) title


def test_card_to_dict_carries_key_for_clickable_analysis_seed():
    """Item I (clickable cards): the UI seeds the analysis window over a card's
    article selection from the card key (the normalized term/identity) when the
    title has no quoted term — so to_dict MUST expose `key`. It is an identity
    string, never a score (the §6 ban still holds)."""
    d = Card(
        type="rising", title="A", summary="s", bucket="rising",
        method="m", caveat="c", key="election",
    ).to_dict()
    assert d["key"] == "election"
    assert all("score" not in k for k in d)


# --------------------------------------------------------------------------- #
#  Producers over a real, small indexed corpus
# --------------------------------------------------------------------------- #
@pytest.fixture()
def corpus(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(name="Beta", domain="beta.test", country="us"))
    s.commit()

    now = datetime.now(UTC)
    # 12 articles in the last few days; "election" mentioned repeatedly & recently
    # so it trends. Split across two sources for the diet-concentration card.
    for i in range(12):
        src_id = 1 if i % 3 else 2  # Alpha-heavy -> a concentrated diet
        when = now - timedelta(days=i % 5)
        a = Article(
            url=f"https://x.test/{i}",
            canonical_url=f"https://x.test/{i}",
            source_id=src_id,
            title=f"Story {i}",
            hash=f"h{i}",
            language="en",
            content=(
                "The election dominated the election news as election coverage spread."
                if i < 6
                else "Markets moved on quiet trading and steady prices today."
            ),
            published_at=when,
            created_at=now,
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=BaselineExtractor(), country="fr" if src_id == 1 else "us")
    return s


def test_rising_producer_surfaces_trending_term(corpus):
    from src.briefing.producers import rising_now

    cards = rising_now(corpus)
    assert cards, "expected at least one rising card from a clearly trending term"
    c = cards[0]
    assert c.bucket == "rising"
    assert c.signal["metric"] == "growth_ratio"
    assert c.method and c.caveat  # honesty: method + caveat always present
    # A rising card links back to evidence in the corpus.
    assert any(ev.get("url") for ev in c.evidence)


def test_diet_self_audit_uses_concentration(corpus):
    from src.briefing.producers import diet_self_audit

    cards = diet_self_audit(corpus)
    assert cards, "expected a diet card with >=10 articles across 2 sources"
    c = cards[0]
    assert c.bucket == "context"
    assert 0.0 <= c.signal["value"] <= 1.0  # a top-share fraction, not a score
    assert c.signal["gini"] is not None
    assert "owner" in c.caveat.lower()  # honest: source != owner


# --------------------------------------------------------------------------- #
#  Evidence-tiered cards (invariant #9): every emitted card carries a trigger
#  with a non-empty plain sentence + >=1 real math row. Slice 1 instrumented
#  ~8 producers; this asserts the remaining card producers now do too.
# --------------------------------------------------------------------------- #
def _assert_valid_trigger(card):
    """The evidence-tier contract: plain (non-empty str) + >=1 {label,value} row."""
    assert card.trigger is not None, f"{card.type}: missing 'Why am I seeing this?' trigger"
    plain = card.trigger.get("plain")
    assert isinstance(plain, str) and plain.strip(), f"{card.type}: empty plain sentence"
    rows = card.trigger.get("math")
    assert isinstance(rows, list) and rows, f"{card.type}: no math rows"
    for row in rows:
        assert row.get("label"), f"{card.type}: a math row has no label"
        # value may be a number-bearing string ("0", "—" only when honestly absent);
        # the contract is that the row EXISTS and is labelled — values are real.
        assert "value" in row, f"{card.type}: a math row has no value"


def test_corpus_producers_all_carry_a_trigger(corpus):
    """Every card produced over the live corpus fixture carries a valid trigger.

    Covers the producers that fire on this fixture (rising/diet/framing/echo/
    lonely/etc.); the law/wiki/lineage producers are covered below with the
    data they need.
    """
    from src.briefing import producers as P

    fired = 0
    for _name, producer in P._DEFAULT_PRODUCERS:
        for card in producer(corpus):
            _assert_valid_trigger(card)
            fired += 1
    assert fired, "the corpus fixture should fire at least some cards"


@pytest.fixture()
def law_corpus(monkeypatch, tmp_path):
    """A corpus carrying tracked legal documents: a flagged revision (law_change)
    and near-identical text across two jurisdictions (model_legislation)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.database.models import LawDocument, LawRevision

    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    shared_text = (
        "Section 1. Every operator of a regulated platform shall maintain a public "
        "register of automated decisions and provide a means of human review on "
        "request, retaining records for a period of not less than five years."
    ) * 3
    for jur, title in (("fr", "Loi sur les plateformes"), ("uk", "Platforms Act")):
        doc = LawDocument(
            jurisdiction=jur,
            title=title,
            url=f"https://law.test/{jur}",
            official_url=f"https://law.test/{jur}",
            category="legislation",
            watched=True,
            baseline_text=shared_text,
            baseline_hash=f"bh-{jur}",
        )
        s.add(doc)
        s.commit()
        s.add(
            LawRevision(
                document_id=doc.id,
                observed_at=datetime.now(UTC),
                content_hash=f"ch-{jur}",
                size=len(shared_text) + 500,
                delta_bytes=500,
                flagged=True,
                flag_reasons="large_change,structure",
            )
        )
        s.commit()
    return s


def test_law_change_carries_a_trigger(law_corpus):
    from src.briefing.producers import law_change

    cards = law_change(law_corpus)
    assert cards, "a flagged law revision should produce a law_change card"
    for c in cards:
        _assert_valid_trigger(c)
        # the math is REAL, descriptive (delta bytes + flag count), not invented stats.
        labels = {r["label"] for r in c.trigger["math"]}
        assert any("bytes" in lb.lower() for lb in labels)


def test_model_legislation_carries_a_trigger(law_corpus):
    from src.briefing.producers import model_legislation

    cards = model_legislation(law_corpus)
    assert cards, "near-identical cross-jurisdiction text should fire model_legislation"
    for c in cards:
        _assert_valid_trigger(c)
        # the similarity row is a REAL Jaccard value the near-dup signal computed.
        labels = {r["label"] for r in c.trigger["math"]}
        assert any("similarity" in lb.lower() for lb in labels)


@pytest.fixture()
def wiki_corpus(monkeypatch, tmp_path):
    """A corpus with a flagged Wikipedia revision (record_reshaped)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.database.models import WikiPage, WikiRevision

    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    page = WikiPage(wiki="en", title="Some Event", watched=True)
    s.add(page)
    s.commit()
    s.add(
        WikiRevision(
            page_id=page.id,
            revid=12345,
            timestamp=datetime.now(UTC),
            editor_anon=True,
            delta_bytes=-4200,
            flagged=True,
            flag_reasons="large_removal,anon",
        )
    )
    s.commit()
    return s


def test_record_reshaped_carries_a_trigger(wiki_corpus):
    from src.briefing.producers import record_reshaped

    cards = record_reshaped(wiki_corpus)
    assert cards, "a flagged wiki revision should fire record_reshaped"
    for c in cards:
        _assert_valid_trigger(c)


# --------------------------------------------------------------------------- #
#  Service: precompute → cache → serve; dismiss is reversible
# --------------------------------------------------------------------------- #
def test_refresh_then_cached_get(corpus):
    fresh = service.refresh_briefing(corpus)
    assert fresh["cards"], "a real corpus should yield real cards"
    view = service.get_briefing(corpus)  # served from cache, grouped by bucket
    assert view["count"] == len(fresh["cards"])
    assert view["buckets"] and all("label" in b for b in view["buckets"])


def test_sorted_uses_disclosed_order_key_not_raw_magnitude():
    """S5.2 (Leads-calibration): within the SAME bucket, ordering follows the
    Leads-2.0 disclosed order_key (independent sources -> magnitude tier -> recency)
    -- a card with FEWER independent sources but a huge raw n/signal value must NOT
    outrank one with more independent sources, unlike the old raw-magnitude sort."""
    huge_but_lonely = Card(
        type="a", title="huge", summary="s", bucket="context", method="m", caveat="c",
        key="a", n=500, signal={"value": 500}, evidence=[{"source": "OnlyOne"}],
    )
    small_but_corroborated = Card(
        type="b", title="small", summary="s", bucket="context", method="m", caveat="c",
        key="b", n=10, signal={"value": 10},
        evidence=[{"source": f"Src{i}"} for i in range(6)],
    )
    out = service._sorted([huge_but_lonely.to_dict(), small_but_corroborated.to_dict()])
    assert [c["key"] for c in out] == ["b", "a"], out  # more independent sources first


def test_dismiss_hides_card_and_is_reversible(corpus):
    view = service.get_briefing(corpus, force=True)
    card_id = view["cards"][0]["id"]
    service.dismiss(card_id)
    after = service.get_briefing(corpus)
    assert all(c["id"] != card_id for c in after["cards"])
    assert after["dismissed_count"] == 1
    service.restore(card_id)
    restored = service.get_briefing(corpus)
    assert any(c["id"] == card_id for c in restored["cards"])


# --------------------------------------------------------------------------- #
#  Draft accumulator → evidence-carrying Markdown
# --------------------------------------------------------------------------- #
def test_draft_add_and_export_markdown(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    card = Card(
        type="rising",
        title="“election” is rising",
        summary="Mentions climbing.",
        bucket="rising",
        method="ratio",
        caveat="not a significance test",
        signal={"metric": "growth_ratio", "value": 4.2},
        evidence=[{"title": "Story 1", "url": "https://x.test/1", "source": "Alpha"}],
        n=6,
        key="election",
    ).to_dict()

    draft_store.add_card(card, note="Lead item this week.")
    draft_store.add_card(card)  # idempotent by id
    loaded = draft_store.load_draft()
    assert len(loaded["items"]) == 1

    md = draft_store.export_markdown()
    assert "# Open Omniscience briefing" in md
    assert "“election” is rising" in md
    assert "https://x.test/1" in md  # evidence link travels with the claim
    assert "Method:" in md and "Caveat:" in md
    assert "Lead item this week." in md

    draft_store.remove_card(card["id"])
    assert draft_store.load_draft()["items"] == []


# --------------------------------------------------------------------------- #
#  Corpus maturity tier — a DESCRIPTIVE stage, never a score (evidence-tier)
# --------------------------------------------------------------------------- #
def _tier_session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Alpha", domain="alpha.test", country="fr"))
    s.commit()
    return s


def _populate(session, n, span_days):
    """Add ``n`` articles whose published_at spans exactly ``span_days`` days."""
    now = datetime.now(UTC)
    for i in range(n):
        # Spread evenly so min->max == span_days regardless of n (>=2 needed).
        offset = 0 if n <= 1 else round(span_days * i / (n - 1))
        a = Article(
            url=f"https://x.test/{i}",
            canonical_url=f"https://x.test/{i}",
            source_id=1,
            title=f"Story {i}",
            hash=f"h{i}",
            language="en",
            content="some text",
            published_at=now - timedelta(days=offset),
            created_at=now,
        )
        session.add(a)
    session.commit()


def test_corpus_tier_no_score_field():
    """The tier must never carry a composite score (the §6 honesty guard)."""
    from src.briefing.producers import corpus_tier

    s = _tier_session()
    _populate(s, 5, 3)
    out = corpus_tier(s)
    for banned in ("score", "trust_score", "credibility", "rating", "verdict", "maturity_score"):
        assert banned not in out


def test_corpus_tier_empty_is_early():
    from src.briefing.producers import corpus_tier

    s = _tier_session()  # zero articles
    out = corpus_tier(s)
    assert out["tier"] == "early"
    assert out["articles"] == 0
    assert out["age_days"] == 0
    # The thresholds travel so the UI can state them verbatim.
    th = out["thresholds"]
    assert {"young_articles", "min_span_days", "established_articles", "established_days"} <= set(th)


def test_corpus_tier_small_young_is_early():
    from src.briefing.producers import corpus_tier

    s = _tier_session()
    _populate(s, 10, 2)  # few articles, short span
    out = corpus_tier(s)
    assert out["tier"] == "early"
    assert out["articles"] == 10


def test_corpus_tier_enough_articles_but_short_span_is_early():
    # Reuses _is_young's article threshold AND the min-span rule: a big, brand-new
    # burst is still EARLY because the span is too short to lean on.
    from src.briefing.producers import corpus_tier

    s = _tier_session()
    _populate(s, 1200, 3)  # plenty of articles, only 3 days of span
    out = corpus_tier(s)
    assert out["tier"] == "early"


def test_corpus_tier_middle_is_developing():
    from src.briefing.producers import corpus_tier

    s = _tier_session()
    _populate(s, 400, 40)  # past young + min-span, below established thresholds
    out = corpus_tier(s)
    assert out["tier"] == "developing"
    assert out["age_days"] == 40


def test_corpus_tier_large_and_old_is_established():
    from src.briefing.producers import corpus_tier

    s = _tier_session()
    _populate(s, 1500, 120)  # >= established_articles AND >= established_days
    out = corpus_tier(s)
    assert out["tier"] == "established"
    assert out["articles"] == 1500
    assert out["age_days"] == 120


def test_briefing_view_carries_corpus_tier(corpus):
    """The Home briefing API response gains the additive corpus_tier field."""
    view = service.get_briefing(corpus)
    assert "corpus_tier" in view
    assert view["corpus_tier"]["tier"] in ("early", "developing", "established")
    # Additive only: the existing contract keys are all still present.
    for key in ("generated_at", "count", "total", "dismissed_count", "buckets", "cards"):
        assert key in view
